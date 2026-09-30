# 09. DuckDB storage schema

## 1. Общий принцип

Используются три DuckDB-файла:

```text
data/market.duckdb
data/research.duckdb
data/live.duckdb
```

Разделение сделано не из-за объема, а из-за разных режимов доступа и жизненного цикла данных.

## 2. `market.duckdb`

### `instruments`

```sql
CREATE TABLE instruments (
    instrument_uid VARCHAR PRIMARY KEY,
    ticker VARCHAR NOT NULL,
    figi VARCHAR,
    name VARCHAR,
    currency VARCHAR,
    lot_size INTEGER NOT NULL,
    min_price_increment DECIMAL(18, 9),
    exchange VARCHAR,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_updated_at TIMESTAMP NOT NULL
);
```

### `candles_1m`

```sql
CREATE TABLE candles_1m (
    instrument_uid VARCHAR NOT NULL,
    ts TIMESTAMP NOT NULL,
    open DECIMAL(18, 9) NOT NULL,
    high DECIMAL(18, 9) NOT NULL,
    low DECIMAL(18, 9) NOT NULL,
    close DECIMAL(18, 9) NOT NULL,
    volume BIGINT NOT NULL,
    is_complete BOOLEAN NOT NULL,
    source VARCHAR NOT NULL DEFAULT 'tinvest',
    ingested_at TIMESTAMP NOT NULL,
    PRIMARY KEY (instrument_uid, ts)
);
```

Для исследования можно рассмотреть хранение OHLC как `DOUBLE`, если тесты покажут достаточную точность и это заметно ускорит расчет. Денежные значения заявок/fills в live-контуре лучше не смешивать с такой оптимизацией преждевременно.

### `candles_agg`

```sql
CREATE TABLE candles_agg (
    instrument_uid VARCHAR NOT NULL,
    timeframe_minutes INTEGER NOT NULL,
    ts TIMESTAMP NOT NULL,
    open DECIMAL(18, 9) NOT NULL,
    high DECIMAL(18, 9) NOT NULL,
    low DECIMAL(18, 9) NOT NULL,
    close DECIMAL(18, 9) NOT NULL,
    volume BIGINT NOT NULL,
    source_minute_count INTEGER NOT NULL,
    expected_minute_count INTEGER,
    is_complete BOOLEAN NOT NULL,
    aggregation_version INTEGER NOT NULL,
    PRIMARY KEY (instrument_uid, timeframe_minutes, ts, aggregation_version)
);
```

### `ingestion_ranges`

Хранит статус chunked backfill:

```text
instrument_uid
from_ts
to_ts
status
row_count
started_at
finished_at
error
```

### `data_quality_runs`

Хранит результат проверок coverage/gaps/duplicates/range constraints.

## 3. Физическая организация и сортировка

Главный паттерн чтения:

```text
WHERE instrument_uid = ?
  AND ts >= ?
  AND ts < ?
ORDER BY ts
```

Данные следует загружать батчами, логически отсортированными по:

```text
instrument_uid, ts
```

Для текущих 8–15 млн строк не требуется усложнять проект ручным partition manager.

Если база заметно вырастет, можно экспортировать исторические immutable данные в Parquet с partitioning по `instrument_uid/year/month` и читать их напрямую через DuckDB.

## 4. `research.duckdb`

Основные таблицы:

### `datasets`

```text
dataset_id
base_interval
from_ts
to_ts
instrument_set_hash
ingestion_version
aggregation_version
quality_status
created_at
```

### `experiments`

```text
experiment_id
strategy_version
dataset_id
search_space_json
walk_forward_json
cost_model_json
objective_version
code_commit
status
started_at
finished_at
```

### `trials`

```text
experiment_id
trial_id
params_json
status
score
rejection_reason
runtime_ms
seed
```

### `trial_fold_metrics`

```text
experiment_id
trial_id
fold_id
instrument_uid
period_from
period_to
trades
net_return
sharpe
max_drawdown
turnover
... 
```

### `strategy_configs`

```text
strategy_config_id
strategy_version
params_json
source_experiment_id
status
created_at
```

### `validations`

```text
validation_id
strategy_config_id
dataset_id
result
metrics_json
stress_metrics_json
created_at
```

## 5. `live.duckdb`

### `strategy_instances`

Одна и та же `GrowthTrendV1` может быть запущена для разных инструментов/конфигураций.

```text
instance_id
instrument_uid
strategy_config_id
mode            # sandbox/prod
status
started_at
stopped_at
```

### `decisions`

```text
decision_id
instance_id
bar_ts
decision
reason_json
strategy_state_json
created_at
```

### `order_intents`

```text
intent_id
instance_id
decision_id
instrument_uid
side
quantity
client_order_id
status
created_at
```

### `broker_orders`

```text
client_order_id
broker_order_id
status
requested_qty
executed_qty
avg_price
last_update_at
raw_json
```

### `fills`

```text
fill_id
broker_order_id
instrument_uid
qty
price
commission
ts
```

### `positions`

Текущее локальное представление позиции + timestamp последней reconciliation.

### `reconciliation_events`

Каждое расхождение local/broker state фиксируется отдельным событием.

## 6. Миграции без Alembic

Используется простая таблица:

```sql
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    applied_at TIMESTAMP NOT NULL
);
```

SQL-файлы:

```text
sql/market/001_init.sql
sql/market/002_add_quality.sql
sql/research/001_init.sql
sql/live/001_init.sql
```

Application startup применяет отсутствующие migration scripts последовательно в transaction, где это поддерживается выбранным изменением схемы.

## 7. Concurrency rules

Обязательные правила MVP:

- один writer на один `.duckdb` файл;
- worker-процессы оптимизатора не пишут напрямую в `research.duckdb`;
- live-runner не использует `market.duckdb` как operational event log;
- research открывает historical DB read-only, когда не требуется aggregation/materialization;
- долгий backtest не держит write transaction;
- перед backup writer корректно закрывает/flush-ит соединение.

## 8. Backup

Минимальная политика:

- `market.duckdb`: ежедневный/еженедельный snapshot после завершения записи;
- `research.duckdb`: snapshot после значимых optimization/validation runs;
- `live.duckdb`: более частый backup + export критичного order/fill ledger;
- `.duckdb` файлы не хранятся в git.

## 9. Почему не PostgreSQL на этом этапе

Для текущего scope PostgreSQL добавляет:

- отдельный сервис;
- migrations/connection management;
- операционную поддержку;
- сетевой слой;
- дополнительную сложность локальных воспроизводимых экспериментов.

При этом 10 акций × 5 лет 1m истории не требуют серверной БД по объему или скорости.

Поэтому DuckDB является осознанным архитектурным выбором для MVP, а не временной заглушкой.

## 10. Доступ из desktop GUI

Qt widgets и view models **не открывают DuckDB напрямую**.

Правильный путь:

```text
View / ViewModel
    → Application Service
    → Repository Port
    → DuckDB Adapter
```

Это сохраняет single-writer rules и позволяет тем же use cases пользоваться из GUI, developer CLI и automated tests.

UI-specific настройки окна и display preferences не помещаются в domain DuckDB. Для них используется `QSettings`. API token хранится в OS keychain/credential storage и никогда не сохраняется в `.duckdb`.