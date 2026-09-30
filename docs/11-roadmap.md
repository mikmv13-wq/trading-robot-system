# 11. Поэтапный roadmap разработки

Scope roadmap:

- DuckDB;
- один алгоритм `GrowthTrendV1`;
- около 10 акций;
- 5 лет 1m истории;
- T‑Инвестиции;
- один live-runner;
- **desktop GUI на PySide6/Qt без web frontend/backend**.

Каждый этап должен завершаться рабочим вертикальным срезом, тестами и Definition of Done.

---

## Этап 0. Skeleton проекта + DuckDB + Desktop shell

### Реализовать

- Python project;
- settings;
- logging;
- DuckDB connection/repository layer;
- versioned SQL migrations;
- создание `market.duckdb`, `research.duckdb`, `live.duckdb`;
- domain models;
- T-Invest client interface;
- PySide6 application shell;
- main window + navigation: Dashboard / Data / Charts / Backtest / Optimization / Validation / Strategies / Trading / Logs / Settings;
- application service layer, общий для GUI и developer CLI;
- базовый Job Manager + progress/error model;
- developer CLI skeleton;
- OS keychain abstraction для T-Invest token;
- CI с unit tests/lint/typecheck.

### DoD

- команда bootstrap с нуля создает все три БД;
- migrations идемпотентны;
- desktop application запускается и переключает основные пустые экраны;
- background test job не блокирует UI;
- `trader --help` работает как developer tool;
- `.duckdb` файлы и секреты не попадают в repo;
- repository tests работают на временных DuckDB-файлах.

---

## Этап 1. Universe из ~10 акций + исторические 1m данные

### Реализовать

- config списка инструментов;
- instrument sync по broker UID;
- `GetCandles` adapter;
- chunked 5-year backfill;
- batch inserts;
- candle normalization;
- dedup/upsert policy;
- resumable ingestion checkpoints;
- data gap scanner;
- data quality checks.

### GUI

Экран `Data` должен позволять:

- выбрать universe;
- запустить instrument sync;
- запустить/resume 5-year backfill;
- видеть progress по инструментам;
- запускать data validation;
- видеть coverage/gaps/min/max timestamp/row count.

Developer CLI может дублировать эти use cases для CI/diagnostics.

### DoD

- все выбранные ~10 акций имеют ожидаемый historical coverage;
- повторный backfill не создает дублей;
- interrupted backfill можно продолжить;
- можно получить row count/min/max timestamp по каждой акции;
- gaps отделены от закрытого рынка;
- все timestamps UTC;
- порядок размера dataset соответствует ожидаемому диапазону, а аномалии объяснены;
- весь этап можно выполнить из GUI без CLI.

---

## Этап 2. Агрегатор

### Реализовать

- trading session model;
- N-minute aggregation;
- 1h/2h/4h;
- partial-bucket detection;
- materialized bars для часто используемых timeframe;
- aggregation versioning.

### DoD

- 5m свеча совпадает с ручным расчетом из пяти 1m;
- bucket не пересекает session boundary;
- неполный bucket помечается и не используется как обычный closed bar;
- повторная агрегация идемпотентна;
- можно полностью пересоздать `candles_agg` из `candles_1m`;
- aggregation запускается из GUI как cancellable background job;
- Chart Explorer позволяет визуально проверить выбранный агрегированный диапазон.

---

## Этап 3. Fixed-config GrowthTrendV1 + backtester

На этом этапе **никакой оптимизации еще нет**.

### Реализовать

- EMA/momentum/ATR/breakout features;
- strategy pure core;
- position model;
- market-like execution model;
- commissions/slippage;
- metrics;
- trade ledger;
- backtest одного фиксированного config по всем 10 акциям.

### DoD

- golden dataset test;
- доказан next-bar execution;
- нет look-ahead;
- один config воспроизводимо прогоняется по всем инструментам;
- повторный запуск дает те же сделки и metrics;
- данные для backtest читаются batch-ом, а не SQL-запросом на каждый бар;
- backtest настраивается и запускается из GUI;
- UI показывает metrics, equity/drawdown и trade ledger;
- переход из сделки на соответствующий участок Chart Explorer работает.

---

## Этап 4. Dataset + Experiment tracking

### Реализовать

- dataset definitions;
- experiment ids;
- config hashes;
- code commit capture;
- persistent metrics/trials в `research.duckdb`;
- reproducibility command.

### DoD

GUI показывает experiment metadata и предоставляет действие `Reproduce`. Developer CLI команда вида `trader experiment reproduce EXP-123` использует тот же application use case и повторяет backtest на том же dataset definition.

---

## Этап 5. Optimizer + walk-forward

### Реализовать

- Optuna study;
- constrained parameter space;
- ~4 years research / ~1 year untouched holdout как стартовая схема;
- time-series folds;
- hard filters;
- temporal stability;
- cross-instrument stability;
- neighbor robustness;
- shared-config mode;
- optional per-instrument mode;
- Pareto report;
- coordinator-only writes в `research.duckdb`.

### DoD

- optimizer не имеет доступа к final holdout;
- все trials сохранены;
- можно объяснить, почему config стал candidate;
- результат содержит fold × instrument metrics;
- worker processes не конкурируют за запись в DuckDB;
- плохой результат на большей части universe нельзя скрыть одной удачной акцией;
- Optimization screen показывает progress, rejected trials, stability metrics и candidates без блокировки GUI.

---

## Этап 6. Final validation

### Реализовать

- frozen strategy config;
- holdout runner;
- pass/fail gates;
- stress costs;
- sensitivity diagnostics;
- validation report;
- strategy registry.

### DoD

- config после начала validation нельзя незаметно изменить;
- `REJECTED` нельзя запустить в sandbox через обычный путь;
- отчет содержит per-instrument и aggregate результаты;
- holdout не использовался для выбора параметров;
- Validation screen не позволяет редактировать frozen config после старта;
- статус `APPROVED/REJECTED` сохраняется и сразу отражается в Strategy Registry.

---

## Этап 7. Live market pipeline

### Реализовать

- MarketDataStream;
- closed candle subscription для ~10 инструментов;
- reconnect;
- historical gap-fill хвоста;
- feature warmup;
- strategy live decisions without order submission;
- serial writes runtime событий.

### Режим

`paper-observer`: сигналы логируются, заявки не отправляются.

### DoD

- decisions на recorded stream совпадают с replay/backtest;
- после reconnect данные непрерывны;
- duplicate event не создает duplicate decision;
- один live-runner устойчиво обслуживает весь текущий universe;
- Trading screen в режиме `paper-observer` показывает live candles, decisions, connection/reconnect status и stale-data state.

---

## Этап 8. Sandbox execution

### Реализовать

- Orders adapter;
- order idempotency;
- order/trades streams;
- position state;
- reconciliation;
- circuit breakers;
- risk engine;
- `live.duckdb` event/state persistence.

### DoD

- restart с открытой позицией восстанавливает state;
- timeout submit не создает вторую заявку;
- broker/local mismatch ставит систему на pause;
- sandbox checklist пройден;
- тяжелые research queries не влияют на live DB;
- sandbox полностью запускается/останавливается из Trading screen;
- UI отображает order lifecycle, fills, positions, reconciliation и circuit breaker state.

---

## Этап 9. Controlled production

### Реализовать

- prod safety flags;
- alerts внутри desktop application;
- desktop monitoring panels;
- daily reconciliation report;
- controlled startup/shutdown;
- emergency flatten command;
- backup policy для `live.duckdb`;
- production confirmation dialog;
- persistent mode indicator;
- controlled app shutdown при активной торговле;
- emergency stop action.

### Порядок rollout

```text
1 instrument
→ несколько инструментов
→ весь approved universe
```

### DoD

- старт с минимальной позицией;
- no-margin;
- строгий daily risk cap;
- подтвержден полный entry/exit lifecycle;
- после рестарта order/position state корректно reconciled;
- случайное закрытие окна не оставляет runtime в неопределенном состоянии;
- production workflow не требует browser/web UI/CLI.

---

## Этап 10. Расширение только после стабильного MVP

Не делать раньше времени:

- дополнительные виды стратегий;
- сотни инструментов;
- portfolio optimizer;
- tick/trade storage;
- distributed optimizer;
- server DB;
- микросервисы.

Возвращаться к ним следует только после доказанной стабильности полного research → validation → live pipeline на текущих 10 акциях.