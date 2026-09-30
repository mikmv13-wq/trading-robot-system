# 06. Подбор параметров и устойчивость

## 1. Принцип

Оптимизатор не должен искать максимальный исторический PnL. Его задача — найти **область параметров**, которая остается приемлемой:

- на нескольких последовательных периодах;
- при небольшом изменении параметров;
- после комиссий и проскальзывания;
- желательно на нескольких из ~10 акций, а не на единственном удачном инструменте.

## 2. Что оптимизируется в первой версии

Алгоритм стратегии только один: `GrowthTrendV1`.

Оптимизатор меняет **параметры**, а не генерирует новые стратегии.

Это важно для контроля data mining: сначала нужно понять, существует ли устойчивый edge у одной четко определенной модели.

## 3. Разбиение 5-летней истории

Никакого random train/test split.

Рекомендуемая схема первой версии:

```text
5 years total

|------- research / walk-forward -------|--- final holdout ---|
<------------- ~4 years ---------------><----- ~1 year ------>
```

Внутри research-части:

```text
Fold 1: [TRAIN 12-18m][TEST 3m]
Fold 2:       [TRAIN 12-18m][TEST 3m]
Fold 3:              [TRAIN 12-18m][TEST 3m]
...
```

Конкретные границы должны рассчитываться по доступным торговым датам и фиксироваться в experiment metadata.

Пример config:

```yaml
history_years: 5
final_holdout_months: 12
walk_forward:
  train_months: 15
  test_months: 3
  step_months: 3
  embargo_bars: auto
```

`embargo_bars` должен быть не меньше максимально возможного holding horizon около границы, чтобы сделка не «перетекала» между участками оценки.

## 4. Multi-instrument режим для ~10 акций

Нужно поддержать два режима исследования.

### A. Per-instrument config

Для каждой акции подбирается собственный набор параметров.

Плюсы:

- лучше учитывает характер инструмента.

Минусы:

- выше риск overfit;
- 10 независимых поисков увеличивают multiple-testing risk.

### B. Shared config

Один набор параметров проверяется на группе инструментов.

Плюсы:

- более сильная проверка переносимости;
- меньше параметризации.

Минусы:

- потенциально хуже подгоняется под особенности конкретной бумаги.

Для MVP рекомендуется реализовать **оба режима**, но основной кандидат на устойчивость — shared config или небольшое число кластерных конфигураций, а не 10 полностью независимых «идеальных» параметров.

## 5. Двухэтапный поиск

### Stage A — coarse search

- ограниченный набор параметров;
- Optuna TPE/random search;
- быстро отсечь нежизнеспособные области;
- данные нужного timeframe предварительно читаются из DuckDB в память.

### Stage B — local robustness search

Для лучших кандидатов проверить соседние точки.

Например для `fast_ema=12`, `slow_ema=48`, `stop=2.0`:

```text
fast_ema: 10, 12, 14
slow_ema: 42, 48, 54
stop: 1.8, 2.0, 2.2
```

Если результат существует только в одной точке, кандидат считается хрупким.

## 6. Hard filters до scoring

Trial исключается, если:

- число сделок ниже `min_trades`;
- max drawdown выше допустимого;
- нет сделок в значительной части folds;
- комиссии уничтожают результат;
- одна сделка дает непропорционально большую долю PnL;
- нарушены constraints параметров;
- результат зависит почти полностью от одной акции;
- большая часть инструментов имеет явно отрицательный out-of-sample результат.

## 7. Stability score

Не использовать один PnL.

Для каждого fold × instrument считаются метрики, затем агрегируются.

Пример conceptual score:

```text
base = median(oos_sharpe across fold×instrument)
time_consistency = profitable_fold_ratio
instrument_consistency = acceptable_instrument_ratio
robustness = neighbor_pass_ratio
risk_penalty = abs(worst_drawdown)
variance_penalty = dispersion(oos_sharpe)

score =
    1.0 * base
  + 0.7 * time_consistency
  + 0.7 * instrument_consistency
  + 0.5 * robustness
  - 0.8 * risk_penalty
  - 0.5 * variance_penalty
```

Коэффициенты являются versioned configuration. Они не являются универсальными финансовыми константами.

## 8. Pareto вместо одного winner score

После MVP предпочтительно:

1. применить hard risk gates;
2. построить Pareto frontier по:
   - median OOS return;
   - median Sharpe;
   - max drawdown;
   - temporal stability;
   - cross-instrument stability;
   - turnover;
3. выбирать параметры из устойчивого плато.

## 9. Защита от переобучения

- ограничить число параметров;
- фиксировать search space до запуска;
- не расширять search space после просмотра holdout;
- логировать все trials, включая неудачные;
- penalize слишком редкие сделки;
- учитывать realistic costs;
- сравнивать с простыми baselines;
- не создавать десятки почти одинаковых версий стратегии после просмотра результата;
- final holdout открыть только после фиксации candidate config;
- после неудачного holdout не продолжать «доподбор» на том же holdout без объявления новой research итерации.

## 10. Baselines

Каждый experiment сравнивается минимум с:

- buy-and-hold каждого инструмента на том же периоде;
- cash/no-signal;
- упрощенной momentum-версией без части фильтров.

Для shared config также нужен агрегированный cross-instrument baseline.

## 11. Работа с DuckDB во время optimization

DuckDB используется для **batch extraction**, а не как источник каждого бара.

Правильный паттерн:

```text
1. coordinator определяет fold/timeframe
2. одним запросом читает диапазон instrument data
3. Arrow/Polars dataset передается worker-у или кэшируется
4. worker выполняет trial в памяти
5. worker возвращает metrics
6. coordinator пишет result в research.duckdb
```

Это устраняет DB contention и делает CPU главным ограничением optimizer-а.

## 12. Experiment record

Для каждого optimization run сохранять:

```yaml
experiment_id:
strategy_version:
dataset_id:
instruments:
parameter_mode: shared | per_instrument
train_definition:
walk_forward_definition:
search_space:
cost_model:
objective_version:
code_commit:
started_at:
finished_at:
```

Для каждого trial:

- parameters;
- per-instrument/per-fold metrics;
- aggregated metrics;
- rejection reason;
- stability score;
- runtime;
- seed.