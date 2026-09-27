from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from trading_system.config import Settings, load_settings
from trading_system.data_collection.aggregation import AggregateBuilder
from trading_system.data_collection.collector import HistoricalCandleCollector
from trading_system.data_collection.storage import ParquetCandleStorage
from trading_system.data_collection.t_invest_client import TInvestMarketDataClient


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


def _stats_frame(storage: ParquetCandleStorage, settings: Settings) -> pd.DataFrame:
    rows = storage.stats()
    return pd.DataFrame(
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


def _render_overview(storage: ParquetCandleStorage, settings: Settings) -> None:
    st.subheader("Состояние хранилища")
    frame = _stats_frame(storage, settings)

    if frame.empty:
        st.info("Данных пока нет. Запустите сбор на вкладке «Сбор данных».")
        return

    raw = frame[frame["Таймфрейм"] == "1m"]
    total_raw = int(raw["Свечей"].sum()) if not raw.empty else 0
    instruments = int(raw["Instrument ID"].nunique()) if not raw.empty else 0
    latest = raw["Последняя свеча"].max() if not raw.empty else None

    c1, c2, c3 = st.columns(3)
    c1.metric("Raw 1m свечей", f"{total_raw:,}".replace(",", " "))
    c2.metric("Инструментов с данными", instruments)
    c3.metric("Последняя raw свеча", latest.strftime("%Y-%m-%d %H:%M UTC") if latest else "—")

    st.dataframe(frame, width="stretch", hide_index=True)


def _render_collection(storage: ParquetCandleStorage, settings: Settings) -> None:
    st.subheader("Сбор исторических данных")
    enabled = [item for item in settings.instruments if item.enabled]
    if not enabled:
        st.warning("В конфигурации нет включённых инструментов.")
        return

    by_label = {(item.ticker or item.instrument_id): item for item in enabled}
    selected_labels = st.multiselect(
        "Инструменты",
        options=list(by_label),
        default=list(by_label),
    )

    configured_token = os.getenv(settings.t_invest.token_env, "")
    token = st.text_input(
        "T-Invest API token",
        value="",
        type="password",
        placeholder=(
            f"Можно не вводить, если задана переменная окружения {settings.t_invest.token_env}"
        ),
        help="Токен используется только в памяти текущего процесса и не сохраняется в проект.",
    )
    effective_token = token or configured_token

    st.caption(
        f"История начинается с {settings.collector.history_from.isoformat()}. "
        "Повторный запуск продолжает загрузку от последней свечи с overlap."
    )

    if st.button("Запустить сбор", type="primary", disabled=not selected_labels):
        if not effective_token:
            st.error(
                f"Не задан токен. Введите его выше или задайте {settings.t_invest.token_env}."
            )
            return

        selected = [by_label[label] for label in selected_labels]
        progress = st.progress(0.0)
        status = st.empty()
        results: list[dict[str, object]] = []

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
                    status.write(f"Загрузка: **{label}**")
                    result = collector.collect_instrument(instrument)
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
                status.write("Пересчёт изменившихся агрегатов…")
                totals = AggregateBuilder(storage, settings.aggregations.intervals).rebuild()
                st.success(
                    "Сбор завершён. Агрегаты: "
                    + ", ".join(f"{key}={value}" for key, value in totals.items())
                )
            else:
                st.success("Сбор завершён.")

            status.empty()
            st.dataframe(pd.DataFrame(results), width="stretch", hide_index=True)
        except Exception as exc:
            st.exception(exc)


def _render_aggregation(storage: ParquetCandleStorage, settings: Settings) -> None:
    st.subheader("Агрегация")
    if not settings.aggregations.enabled:
        st.warning("Агрегации отключены в конфигурации.")
        return

    st.write("Активные таймфреймы: " + ", ".join(settings.aggregations.intervals))
    mode = st.radio(
        "Режим",
        ["Только изменившиеся месяцы", "Полная перестройка"],
        horizontal=True,
    )

    if st.button("Пересчитать агрегаты"):
        try:
            with st.spinner("Пересчёт агрегатов…"):
                totals = AggregateBuilder(storage, settings.aggregations.intervals).rebuild(
                    all_partitions=mode == "Полная перестройка"
                )
            st.success(", ".join(f"{key}: {value}" for key, value in totals.items()))
        except Exception as exc:
            st.exception(exc)


def _render_chart(storage: ParquetCandleStorage, settings: Settings) -> None:
    st.subheader("Просмотр свечей")
    instruments = [item for item in settings.instruments if item.enabled]
    if not instruments:
        st.info("Нет включённых инструментов.")
        return

    by_label = {(item.ticker or item.instrument_id): item for item in instruments}
    c1, c2, c3 = st.columns(3)
    label = c1.selectbox("Инструмент", list(by_label))
    timeframe = c2.selectbox("Таймфрейм", ["1m", "15m", "30m", "1h"], index=1)
    period = c3.selectbox("Период", [7, 30, 90, 365], index=1, format_func=lambda x: f"{x} дней")

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
    st.line_chart(frame, x="time", y="close", height=420)
    st.caption(f"Показано свечей: {len(frame):,}".replace(",", " "))
    st.dataframe(frame.tail(500), width="stretch", hide_index=True)


def _render_settings(settings: Settings, config_path: Path) -> None:
    st.subheader("Текущая конфигурация")
    st.code(
        "\n".join(
            [
                f"config: {config_path}",
                f"storage.root_path: {settings.storage.root_path}",
                f"storage.catalog_path: {settings.storage.catalog_path}",
                f"collector.history_from: {settings.collector.history_from.isoformat()}",
                f"collector.request_window_hours: {settings.collector.request_window_hours}",
                f"collector.overlap_minutes: {settings.collector.overlap_minutes}",
                f"aggregations: {', '.join(settings.aggregations.intervals)}",
                f"instruments: {len(settings.instruments)}",
            ]
        ),
        language="text",
    )
    st.info(
        "Редактирование настроек из GUI пока намеренно отключено: конфигурация остаётся "
        "version-controlled YAML-файлом."
    )


def main() -> None:
    st.set_page_config(
        page_title="Trading Robot System",
        page_icon="📈",
        layout="wide",
    )
    st.title("Trading Robot System")
    st.caption("Управление модулем сбора и хранения рыночных данных")

    config_value = st.sidebar.text_input("Конфигурация", "config/settings.yaml")
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

    page = st.sidebar.radio(
        "Раздел",
        ["Обзор", "Сбор данных", "Агрегация", "График", "Настройки"],
    )

    if page == "Обзор":
        _render_overview(storage, settings)
    elif page == "Сбор данных":
        _render_collection(storage, settings)
    elif page == "Агрегация":
        _render_aggregation(storage, settings)
    elif page == "График":
        _render_chart(storage, settings)
    else:
        _render_settings(settings, config_path)


if __name__ == "__main__":
    main()
