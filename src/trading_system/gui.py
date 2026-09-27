from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from trading_system.config import Settings, load_settings
from trading_system.data_collection.aggregation import AggregateBuilder
from trading_system.data_collection.collector import HistoricalCandleCollector
from trading_system.data_collection.storage import ParquetCandleStorage
from trading_system.data_collection.t_invest_client import TInvestMarketDataClient


TIMEFRAME_PERIODS = {
    "1m": (1, 3, 7, 30),
    "15m": (7, 30, 90, 365),
    "30m": (30, 90, 365, 730),
    "1h": (30, 90, 365, 730, 1825),
}

PAGE_OVERVIEW = "🏠 Обзор"
PAGE_COLLECTION = "⬇️ Сбор данных"
PAGE_AGGREGATION = "🧱 Агрегация"
PAGE_CHART = "📊 График"
PAGE_SETTINGS = "⚙️ Настройки"


def _create_storage(settings: Settings) -> ParquetCandleStorage:
    storage = ParquetCandleStorage(
        settings.storage.root_path,
        settings.storage.catalog_path,
        compression=settings.storage.compression,
    )
    storage.initialize()
    return storage


def _instrument_label(settings: Settings, instrument_id: str) -> str:
    for item in settings.instruments:
        if item.instrument_id == instrument_id:
            return item.ticker or item.instrument_id
    return instrument_id


def _format_count(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _format_time(value: Any) -> str:
    if value is None or pd.isna(value):
        return "—"
    return value.strftime("%Y-%m-%d %H:%M UTC")


def _stats_frame(storage: ParquetCandleStorage, settings: Settings) -> pd.DataFrame:
    rows = storage.stats()
    frame = pd.DataFrame(
        [
            {
                "Таймфрейм": timeframe,
                "Инструмент": _instrument_label(settings, instrument_id),
                "Instrument ID": instrument_id,
                "Свечей": count,
                "Первая свеча": first,
                "Последняя свеча": last,
            }
            for timeframe, instrument_id, count, first, last in rows
        ]
    )
    if frame.empty:
        return frame

    order = {"1m": 0, "15m": 1, "30m": 2, "1h": 3}
    frame["_order"] = frame["Таймфрейм"].map(order).fillna(99)
    return frame.sort_values(["_order", "Инструмент"]).drop(columns="_order")


def _price_frame(candles) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "time": candle.time,
                "open": candle.open_nano / 1_000_000_000,
                "high": candle.high_nano / 1_000_000_000,
                "low": candle.low_nano / 1_000_000_000,
                "close": candle.close_nano / 1_000_000_000,
                "volume": candle.volume,
            }
            for candle in candles
        ]
    )


def _render_header(config_path: Path, settings: Settings) -> None:
    st.title("Trading Robot System")
    st.caption(
        "Market Data Console · "
        f"{len([item for item in settings.instruments if item.enabled])} инструментов · "
        f"конфигурация: {config_path}"
    )


def _render_overview(storage: ParquetCandleStorage, settings: Settings) -> None:
    st.subheader("Состояние данных")
    frame = _stats_frame(storage, settings)
    dirty_partitions = storage.dirty_raw_partitions()

    if frame.empty:
        st.info(
            "Хранилище пока пустое. Перейдите в «Сбор данных», выберите инструменты "
            "и запустите первичную загрузку."
        )
        return

    raw = frame[frame["Таймфрейм"] == "1m"]
    total_raw = int(raw["Свечей"].sum()) if not raw.empty else 0
    instruments_with_data = int(raw["Instrument ID"].nunique()) if not raw.empty else 0
    latest = raw["Последняя свеча"].max() if not raw.empty else None
    enabled_count = len([item for item in settings.instruments if item.enabled])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Raw 1m свечей", _format_count(total_raw))
    c2.metric("Инструменты", f"{instruments_with_data} / {enabled_count}")
    c3.metric("Последняя raw свеча", _format_time(latest))
    c4.metric("Dirty месяцев", len(dirty_partitions))

    if dirty_partitions:
        st.warning(
            f"Есть {len(dirty_partitions)} raw-партиций, для которых агрегаты ещё нужно "
            "пересчитать."
        )
    else:
        st.success("Raw и агрегированные данные синхронизированы по dirty-флагам.")

    timeframe_tab, instrument_tab = st.tabs(["По таймфреймам", "По инструментам"])

    with timeframe_tab:
        summary = (
            frame.groupby("Таймфрейм", as_index=False)
            .agg(
                Инструментов=("Instrument ID", "nunique"),
                Свечей=("Свечей", "sum"),
                Первая_свеча=("Первая свеча", "min"),
                Последняя_свеча=("Последняя свеча", "max"),
            )
            .rename(
                columns={
                    "Первая_свеча": "Первая свеча",
                    "Последняя_свеча": "Последняя свеча",
                }
            )
        )
        summary["_order"] = summary["Таймфрейм"].map({"1m": 0, "15m": 1, "30m": 2, "1h": 3})
        summary = summary.sort_values("_order").drop(columns="_order")
        st.dataframe(
            summary,
            width="stretch",
            hide_index=True,
            column_config={
                "Свечей": st.column_config.NumberColumn(format="%d"),
                "Первая свеча": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                "Последняя свеча": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            },
        )

    with instrument_tab:
        st.dataframe(
            raw[["Инструмент", "Instrument ID", "Свечей", "Первая свеча", "Последняя свеча"]],
            width="stretch",
            hide_index=True,
            column_config={
                "Свечей": st.column_config.NumberColumn(format="%d"),
                "Первая свеча": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                "Последняя свеча": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            },
        )


def _render_token_input(settings: Settings) -> str:
    env_token = os.getenv(settings.t_invest.token_env, "")

    with st.expander("Доступ к T-Invest", expanded=not bool(env_token)):
        if env_token:
            st.success(f"Токен найден в переменной окружения {settings.t_invest.token_env}.")
            st.caption("Поле ниже можно использовать для временной замены токена в этой сессии.")
        else:
            st.warning(
                f"Переменная окружения {settings.t_invest.token_env} не задана. "
                "Введите токен для запуска сбора."
            )

        typed_token = st.text_input(
            "T-Invest API token",
            value="",
            type="password",
            placeholder="Временный токен для текущего процесса",
            help="Значение не записывается в YAML, DuckDB или репозиторий.",
        )

    return typed_token or env_token


def _render_collection(storage: ParquetCandleStorage, settings: Settings) -> None:
    st.subheader("Сбор исторических данных")
    st.caption(
        "Дозагрузка идемпотентна: для каждого инструмента система продолжает работу "
        "от последней raw-свечи с настроенным overlap."
    )

    enabled = [item for item in settings.instruments if item.enabled]
    if not enabled:
        st.warning("В конфигурации нет включённых инструментов.")
        return

    by_label = {(item.ticker or item.instrument_id): item for item in enabled}
    stats = _stats_frame(storage, settings)
    raw_stats = stats[stats["Таймфрейм"] == "1m"] if not stats.empty else pd.DataFrame()
    last_by_id = (
        raw_stats.set_index("Instrument ID")["Последняя свеча"].to_dict()
        if not raw_stats.empty
        else {}
    )

    state_rows = [
        {
            "Инструмент": label,
            "Instrument ID": item.instrument_id,
            "Последняя raw свеча": last_by_id.get(item.instrument_id),
            "Старт при пустой базе": settings.collector.history_from,
        }
        for label, item in by_label.items()
    ]
    with st.expander("Текущее покрытие инструментов"):
        st.dataframe(
            pd.DataFrame(state_rows),
            width="stretch",
            hide_index=True,
            column_config={
                "Последняя raw свеча": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                "Старт при пустой базе": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            },
        )

    selected_labels = st.multiselect(
        "Инструменты для дозагрузки",
        options=list(by_label),
        default=list(by_label),
        help="По умолчанию выбраны все включённые инструменты из YAML.",
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Выбрано", len(selected_labels))
    c2.metric("Окно API", f"{settings.collector.request_window_hours} ч")
    c3.metric("Overlap", f"{settings.collector.overlap_minutes} мин")

    effective_token = _render_token_input(settings)

    if not effective_token:
        st.info("Запуск станет доступен после настройки T-Invest token.")

    if st.button(
        "Запустить дозагрузку",
        type="primary",
        disabled=not selected_labels or not effective_token,
    ):
        selected = [by_label[label] for label in selected_labels]
        results: list[dict[str, object]] = []

        status = st.status("Подготовка сбора…", expanded=True)
        progress = st.progress(0.0)

        try:
            with TInvestMarketDataClient(
                token=effective_token,
                base_url=settings.t_invest.base_url,
                timeout_seconds=settings.t_invest.request_timeout_seconds,
                requests_per_minute=settings.t_invest.requests_per_minute,
                max_retries=settings.t_invest.max_retries,
                app_name=settings.t_invest.app_name,
            ) as client:
                collector = HistoricalCandleCollector(
                    client=client,
                    storage=storage,
                    config=settings.collector,
                )

                for index, instrument in enumerate(selected, start=1):
                    label = instrument.ticker or instrument.instrument_id
                    status.update(
                        label=f"Загрузка {label} · {index}/{len(selected)}",
                        state="running",
                    )
                    result = collector.collect_instrument(instrument)
                    status.write(
                        f"**{label}:** получено {_format_count(result.received)}, "
                        f"сохранено {_format_count(result.saved)}"
                    )
                    results.append(
                        {
                            "Инструмент": label,
                            "Получено": result.received,
                            "Сохранено": result.saved,
                            "С": result.requested_from,
                            "По": result.requested_to,
                        }
                    )
                    progress.progress(index / len(selected))

            if settings.aggregations.enabled and settings.aggregations.run_after_collect:
                status.update(label="Пересчёт изменившихся агрегатов…")
                totals = AggregateBuilder(storage, settings.aggregations.intervals).rebuild()
                status.write(
                    "Агрегаты: " + ", ".join(f"{key}={value}" for key, value in totals.items())
                )

            status.update(label="Сбор завершён", state="complete", expanded=False)
            st.success(f"Обработано инструментов: {len(selected)}")
            st.dataframe(pd.DataFrame(results), width="stretch", hide_index=True)
        except Exception as exc:
            status.update(label="Сбор завершился с ошибкой", state="error", expanded=True)
            st.exception(exc)


def _run_aggregation(
    storage: ParquetCandleStorage,
    settings: Settings,
    *,
    all_partitions: bool,
) -> None:
    mode_label = "Полная перестройка агрегатов" if all_partitions else "Инкрементальный пересчёт"
    status = st.status(mode_label, expanded=True)
    try:
        totals = AggregateBuilder(storage, settings.aggregations.intervals).rebuild(
            all_partitions=all_partitions
        )
        status.write(", ".join(f"{key}: {_format_count(value)}" for key, value in totals.items()))
        status.update(label=f"{mode_label} завершён", state="complete", expanded=False)
        st.success("Агрегированные данные обновлены.")
    except Exception as exc:
        status.update(label=f"{mode_label}: ошибка", state="error", expanded=True)
        st.exception(exc)


def _render_aggregation(storage: ParquetCandleStorage, settings: Settings) -> None:
    st.subheader("Агрегация")
    if not settings.aggregations.enabled:
        st.warning("Агрегации отключены в конфигурации.")
        return

    dirty_count = len(storage.dirty_raw_partitions())
    raw_partition_count = len(storage.all_raw_partitions())

    c1, c2, c3 = st.columns(3)
    c1.metric("Dirty raw месяцев", dirty_count)
    c2.metric("Raw партиций всего", raw_partition_count)
    c3.metric("Таймфреймы", " · ".join(settings.aggregations.intervals))

    st.markdown("#### Обычный режим")
    st.write(
        "Пересчитывает только месяцы с изменившимися raw 1m данными. "
        "Это основной безопасный режим после дозагрузки."
    )
    if dirty_count == 0:
        st.success("Изменившихся raw-партиций нет.")

    if st.button(
        "Пересчитать изменившиеся месяцы",
        type="primary",
        disabled=dirty_count == 0,
    ):
        _run_aggregation(storage, settings, all_partitions=False)

    st.divider()
    with st.expander("Полная перестройка всех агрегатов"):
        st.warning(
            "Операция заново строит 15m/30m/1h для всех raw-партиций. "
            "Используйте её после изменения алгоритма агрегации или для полной проверки."
        )
        confirmed = st.checkbox(
            f"Подтверждаю перестройку всех {raw_partition_count} raw-партиций",
            disabled=raw_partition_count == 0,
        )
        if st.button(
            "Запустить полную перестройку",
            disabled=not confirmed or raw_partition_count == 0,
        ):
            _run_aggregation(storage, settings, all_partitions=True)


def _build_market_figure(frame: pd.DataFrame, label: str, timeframe: str) -> go.Figure:
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.76, 0.24],
    )
    figure.add_trace(
        go.Candlestick(
            x=frame["time"],
            open=frame["open"],
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            name=f"{label} {timeframe}",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Bar(
            x=frame["time"],
            y=frame["volume"],
            name="Volume",
        ),
        row=2,
        col=1,
    )
    figure.update_layout(
        height=680,
        margin=dict(l=10, r=10, t=35, b=10),
        showlegend=False,
        hovermode="x unified",
    )
    figure.update_xaxes(rangeslider_visible=False, row=1, col=1)
    figure.update_yaxes(title_text="Цена", row=1, col=1)
    figure.update_yaxes(title_text="Объём", row=2, col=1)
    return figure


def _render_chart(storage: ParquetCandleStorage, settings: Settings) -> None:
    st.subheader("Просмотр рынка")
    instruments = [item for item in settings.instruments if item.enabled]
    if not instruments:
        st.info("Нет включённых инструментов.")
        return

    by_label = {(item.ticker or item.instrument_id): item for item in instruments}
    c1, c2, c3 = st.columns([2, 1, 1])
    label = c1.selectbox("Инструмент", list(by_label))
    timeframe = c2.selectbox("Таймфрейм", ["1m", "15m", "30m", "1h"], index=1)
    periods = TIMEFRAME_PERIODS[timeframe]
    default_period = 30 if 30 in periods else periods[0]
    period = c3.selectbox(
        "Период",
        periods,
        index=periods.index(default_period),
        format_func=lambda value: f"{value} дней",
    )

    if timeframe == "1m" and period >= 30:
        st.info(
            "Для 1m выбран длинный период. Построение интерактивного свечного графика "
            "может быть тяжелее, чем для агрегированных таймфреймов."
        )

    until = datetime.now(timezone.utc)
    from_ = until - timedelta(days=period)

    try:
        candles = storage.query_candles(
            timeframe,
            by_label[label].instrument_id,
            from_=from_,
            to=until,
        )
    except Exception as exc:
        st.exception(exc)
        return

    if not candles:
        st.info("Для выбранного периода данных нет.")
        return

    frame = _price_frame(candles)
    first_close = float(frame.iloc[0]["close"])
    last_close = float(frame.iloc[-1]["close"])
    change = ((last_close / first_close) - 1) * 100 if first_close else 0.0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Последняя цена", f"{last_close:,.4f}")
    m2.metric("Изменение за период", f"{change:+.2f}%")
    m3.metric("Максимум", f"{frame['high'].max():,.4f}")
    m4.metric("Минимум", f"{frame['low'].min():,.4f}")

    figure = _build_market_figure(frame, label, timeframe)
    st.plotly_chart(
        figure,
        width="stretch",
        config={"displaylogo": False, "scrollZoom": True},
    )

    table_tab, export_tab = st.tabs(["Последние свечи", "Экспорт"])
    with table_tab:
        latest = frame.tail(500).sort_values("time", ascending=False)
        st.dataframe(
            latest,
            width="stretch",
            hide_index=True,
            column_config={
                "time": st.column_config.DatetimeColumn("Время", format="YYYY-MM-DD HH:mm"),
                "open": st.column_config.NumberColumn("Open", format="%.6f"),
                "high": st.column_config.NumberColumn("High", format="%.6f"),
                "low": st.column_config.NumberColumn("Low", format="%.6f"),
                "close": st.column_config.NumberColumn("Close", format="%.6f"),
                "volume": st.column_config.NumberColumn("Volume", format="%d"),
            },
        )

    with export_tab:
        st.write(
            f"Диапазон: {_format_time(frame['time'].min())} — "
            f"{_format_time(frame['time'].max())}. "
            f"Свечей: {_format_count(len(frame))}."
        )
        st.download_button(
            "Скачать CSV",
            data=frame.to_csv(index=False).encode("utf-8"),
            file_name=f"{label}_{timeframe}_{period}d.csv",
            mime="text/csv",
        )


def _render_settings(settings: Settings, config_path: Path) -> None:
    st.subheader("Текущая конфигурация")
    st.caption("GUI читает настройки из YAML, но не изменяет их автоматически.")

    c1, c2, c3, c4 = st.columns(4)
    enabled_count = len([item for item in settings.instruments if item.enabled])
    c1.metric("Инструменты", enabled_count)
    c2.metric("История с", settings.collector.history_from.strftime("%Y-%m-%d"))
    c3.metric("Окно API", f"{settings.collector.request_window_hours} ч")
    c4.metric("Overlap", f"{settings.collector.overlap_minutes} мин")

    general_tab, instruments_tab = st.tabs(["Система", "Инструменты"])
    with general_tab:
        values = pd.DataFrame(
            [
                ("Config", str(config_path)),
                ("Market data", str(settings.storage.root_path)),
                ("DuckDB catalog", str(settings.storage.catalog_path)),
                ("Compression", settings.storage.compression),
                ("T-Invest URL", settings.t_invest.base_url),
                ("Token env", settings.t_invest.token_env),
                ("Requests/min", settings.t_invest.requests_per_minute),
                ("Aggregations", ", ".join(settings.aggregations.intervals)),
                ("Aggregate after collect", settings.aggregations.run_after_collect),
            ],
            columns=["Параметр", "Значение"],
        )
        st.dataframe(values, width="stretch", hide_index=True)

    with instruments_tab:
        instrument_frame = pd.DataFrame(
            [
                {
                    "Ticker": item.ticker or "—",
                    "Instrument ID": item.instrument_id,
                    "Enabled": item.enabled,
                }
                for item in settings.instruments
            ]
        )
        st.dataframe(instrument_frame, width="stretch", hide_index=True)


def main() -> None:
    st.set_page_config(
        page_title="Trading Robot System",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.sidebar.title("TRS")
    st.sidebar.caption("Market Data Console")
    page = st.sidebar.radio(
        "Навигация",
        [
            PAGE_OVERVIEW,
            PAGE_COLLECTION,
            PAGE_AGGREGATION,
            PAGE_CHART,
            PAGE_SETTINGS,
        ],
    )
    st.sidebar.divider()

    with st.sidebar.expander("Конфигурация", expanded=False):
        config_value = st.text_input(
            "YAML-файл",
            "config/settings.yaml",
            help="Путь задаётся относительно директории, из которой запущен trading-gui.",
        )
    config_path = Path(config_value)

    if not config_path.exists():
        st.error(
            f"Файл {config_path} не найден. Создайте его на основе "
            "config/settings.example.yaml."
        )
        return

    try:
        settings = load_settings(config_path)
        storage = _create_storage(settings)
    except Exception as exc:
        st.exception(exc)
        return

    st.sidebar.caption(f"Data: {settings.storage.root_path}")
    token_ready = bool(os.getenv(settings.t_invest.token_env))
    st.sidebar.caption(
        f"T-Invest token: {'env ✓' if token_ready else 'не задан в env'}"
    )

    _render_header(config_path, settings)

    if page == PAGE_OVERVIEW:
        _render_overview(storage, settings)
    elif page == PAGE_COLLECTION:
        _render_collection(storage, settings)
    elif page == PAGE_AGGREGATION:
        _render_aggregation(storage, settings)
    elif page == PAGE_CHART:
        _render_chart(storage, settings)
    else:
        _render_settings(settings, config_path)


if __name__ == "__main__":
    main()
