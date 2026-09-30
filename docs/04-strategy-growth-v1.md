# 04. Стратегия GrowthTrendV1

## 1. Назначение

Первая стратегия — long-only стратегия, пытающаяся войти в движение при подтвержденном росте цены и выйти при потере импульса или достижении risk exit.

Цель этой версии — не найти «идеальную формулу», а создать стратегию с ограниченным числом понятных параметров, пригодную для корректной оптимизации и проверки устойчивости.

## 2. Исходные допущения

- только long;
- один инструмент — не более одной открытой позиции для одной strategy instance;
- решение принимается только на закрытом баре;
- вход моделируется/исполняется после сигнала, а не по цене бара, на котором сигнал возник;
- стратегия не знает о размере счета — она формирует направление и stop-distance; position sizing делает risk engine.

## 3. Признаки

Для закрытого бара `t`:

### Momentum

```text
momentum(t, N) = close[t] / close[t-N] - 1
```

### Быстрый/медленный тренд

```text
ema_fast  = EMA(close, fast_period)
ema_slow  = EMA(close, slow_period)
trend_up  = ema_fast > ema_slow
```

### Волатильность

```text
atr = ATR(atr_period)
atr_pct = atr / close
```

### Breakout

```text
previous_high = max(high[t-breakout_lookback : t-1])
breakout = close[t] > previous_high
```

Breakout допускается сделать optional-параметром, чтобы сравнить momentum-only и momentum+breakout без создания нового движка.

## 4. Условие входа

Базовый вариант:

```text
not in_position
AND momentum >= min_momentum
AND ema_fast > ema_slow
AND atr_pct between [min_atr_pct, max_atr_pct]
AND (breakout_filter disabled OR breakout)
AND session_filter allows trading
```

После закрытия бара `t` создается `ENTER_LONG` intent. Исполнение — не раньше следующего доступного market event.

## 5. Условия выхода

Выход выполняется при первом сработавшем условии:

1. hard stop:

```text
price <= entry_price - stop_atr_mult * entry_atr
```

2. trailing stop:

```text
price <= highest_price_since_entry - trailing_atr_mult * current_atr
```

3. потеря тренда:

```text
ema_fast < ema_slow
```

4. максимальное время удержания:

```text
bars_in_position >= max_holding_bars
```

5. optional take profit:

```text
price >= entry_price + take_profit_atr_mult * entry_atr
```

6. forced session close, если `allow_overnight=false`.

## 6. Параметры, доступные оптимизатору

Рекомендуемое стартовое пространство:

```yaml
timeframe_minutes: [5, 10, 15, 30, 60]
momentum_lookback: [3..24]
min_momentum_pct: [0.10..2.00]
fast_ema: [3..30]
slow_ema: [10..120]
atr_period: [7..40]
min_atr_pct: [0.05..1.50]
max_atr_pct: [0.30..5.00]
stop_atr_mult: [0.8..4.0]
trailing_atr_mult: [1.0..6.0]
max_holding_bars: [2..80]
breakout_enabled: [false, true]
breakout_lookback: [3..40]
take_profit_enabled: [false, true]
take_profit_atr_mult: [1.0..8.0]
allow_overnight: [false, true]
```

Ограничения:

```text
fast_ema < slow_ema
min_atr_pct < max_atr_pct
```

На первом цикле не следует оптимизировать все параметры одновременно. Сначала подобрать timeframe + trend/momentum, затем risk exits.

## 7. Warmup

До момента накопления:

```text
max(slow_ema, atr_period, momentum_lookback, breakout_lookback) + safety_margin
```

стратегия находится в `WARMUP` и не торгует.

## 8. Position sizing

Strategy возвращает stop-distance, а risk engine считает количество лотов.

Пример fixed-risk sizing:

```text
risk_budget = equity * risk_per_trade
risk_per_share = abs(entry_price - stop_price)
raw_qty = floor(risk_budget / risk_per_share)
lot_qty = floor(raw_qty / lot_size)
```

Дополнительно применяется `max_position_pct`.

## 9. Версионирование

Любое изменение формулы сигнала, набора признаков или exit semantics увеличивает `strategy_version`.

Изменение только значений параметров создает новую `strategy_config`, но не новую версию алгоритма.