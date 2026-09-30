# 03. Market data: 10 акций × 5 лет × 1m

## 1. Канонические данные

Единственный канонический market dataset первой версии — **закрытые минутные свечи 1m** из T‑Инвестиций.

Все 5m/10m/15m/30m/1h/... свечи являются производными и могут быть полностью пересозданы.

Это дает два свойства:

1. backtest и live используют одинаковую базовую семантику баров;
2. смена набора исследуемых таймфреймов не требует повторной загрузки истории у брокера.

## 2. Ожидаемый объем

Для 10 акций и 5 лет:

```text
10 instruments
× ~250 trading days/year
× 5 years
× ~600–1200 minute bars/day
≈ 7.5–15 million 1m rows
```

Это оценка порядка величины, а не контракт: фактическое число зависит от торговых режимов, расписания конкретного инструмента и доступности исторических свечей.

Даже двукратный запас по объему остается небольшим для DuckDB.

## 3. Исторический backfill

Пайплайн для каждого instrument UID:

```text
instrument metadata
    → determine requested 5y range
    → split into API-supported chunks
    → fetch candles
    → normalize
    → reject invalid rows
    → deduplicate by instrument_uid + interval + ts
    → write batch transaction
    → update ingestion checkpoint
    → run coverage/gap checks
```

Backfill должен быть **возобновляемым**. При падении процесса повторный запуск продолжает работу с последнего подтвержденного диапазона.

## 4. Идемпотентность

Natural key canonical candle:

```text
(instrument_uid, ts)
```

для таблицы `candles_1m`.

Повторная загрузка того же диапазона не должна создавать дубликаты.

Если источник возвращает измененную историческую свечу, политика должна быть явной:

- `IGNORE_IF_EXISTS` — для immutable snapshot;
- либо `UPDATE_IF_SOURCE_NEWER` с увеличением `dataset_version`.

Для первой версии рекомендуется обновлять только данные последнего небольшого хвоста, а старую историю считать immutable после quality validation.

## 5. Data quality

Для каждого инструмента проверяются:

- `open/high/low/close > 0`;
- `low <= open, close <= high`;
- `volume >= 0`;
- timestamp выровнен на минуту;
- нет дублей natural key;
- время монотонно;
- gaps классифицированы как expected/unknown;
- неизвестный gap не маскируется автоматически синтетической свечой.

Нельзя просто требовать 1m свечу на каждую календарную минуту — биржа имеет закрытые периоды, паузы и особенности торгового расписания.

## 6. Aggregation

Старший бар строится только из канонических 1m:

```text
open   = first(open)
high   = max(high)
low    = min(low)
close  = last(close)
volume = sum(volume)
```

Для каждой агрегированной свечи желательно хранить:

- `source_minute_count`;
- `expected_minute_count`;
- `is_complete`;
- `aggregation_version`.

Неполный bucket не должен попадать в research как обычная завершенная свеча.

## 7. Materialize или считать on demand

При текущем масштабе допустимы оба подхода, но рекомендуется:

- 1m хранить всегда;
- часто используемые 5m/10m/15m/30m/60m materialize;
- редкие экспериментальные timeframe считать on demand.

Причина — optimizer многократно читает одни и те же интервалы, поэтому materialized bars уменьшают повторную CPU-работу.

## 8. Работа с 10 акциями

На первом этапе не нужен сложный instrument universe service.

Достаточно config:

```yaml
universe:
  - instrument_uid: "..."
    ticker: "SBER"
    enabled: true
  - instrument_uid: "..."
    ticker: "LKOH"
    enabled: true
```

UID брокера является первичным идентификатором. Ticker используется только как человекочитаемый label.

## 9. Dataset definition

Backtest/experiment не должен говорить только «5 лет SBER».

Он ссылается на конкретный dataset definition:

```yaml
dataset_id: market-v1-20260930
source: tinvest
base_interval: 1m
instruments:
  - uid-1
  - uid-2
from: 2021-10-01T00:00:00Z
to: 2026-09-30T00:00:00Z
ingestion_version: 1
aggregation_version: 1
quality_status: PASSED
```

Это позволяет позже воспроизвести optimization result.

## 10. Инкрементальное обновление

После первоначального 5-летнего backfill ежедневный объем очень мал.

Режим:

```text
on startup:
    find last complete 1m per instrument
    backfill missing tail

while market open:
    consume closed candles from stream

periodically / after reconnect:
    reconcile stream tail with historical endpoint
```

Stream не считается единственным источником истины: после reconnect хвост нужно перепроверять.

## 11. Отображение market data в desktop GUI

Экран `Data` работает только через application services и repository API — widgets не выполняют SQL напрямую.

Для таблиц coverage UI запрашивает агрегированную metadata, а не загружает миллионы свечей в память.

`Chart Explorer` всегда работает с ограниченным диапазоном данных. Для длинных периодов application layer выбирает более крупный timeframe/downsampling, чтобы UI не пытался отрисовать 5 лет минутных точек одновременно.

Backfill, gap scan, validation и aggregation отображаются как background jobs с progress/cancel state. Закрытие окна не должно оставлять незавершенную DuckDB transaction.