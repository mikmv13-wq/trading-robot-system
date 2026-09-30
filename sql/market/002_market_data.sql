CREATE TABLE instruments (
    instrument_uid VARCHAR PRIMARY KEY,
    ticker VARCHAR NOT NULL,
    lot_size INTEGER NOT NULL CHECK (lot_size > 0),
    name VARCHAR,
    currency VARCHAR,
    figi VARCHAR,
    exchange VARCHAR,
    instrument_type VARCHAR,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE universes (
    universe_id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE universe_instruments (
    universe_id VARCHAR NOT NULL REFERENCES universes(universe_id),
    instrument_uid VARCHAR NOT NULL REFERENCES instruments(instrument_uid),
    PRIMARY KEY (universe_id, instrument_uid)
);

CREATE TABLE candles_1m (
    instrument_uid VARCHAR NOT NULL REFERENCES instruments(instrument_uid),
    ts TIMESTAMPTZ NOT NULL,
    open DECIMAL(38, 9) NOT NULL CHECK (open >= 0),
    high DECIMAL(38, 9) NOT NULL CHECK (high >= 0),
    low DECIMAL(38, 9) NOT NULL CHECK (low >= 0),
    close DECIMAL(38, 9) NOT NULL CHECK (close >= 0),
    volume BIGINT NOT NULL CHECK (volume >= 0),
    is_complete BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (instrument_uid, ts),
    CHECK (low <= open),
    CHECK (low <= close),
    CHECK (low <= high),
    CHECK (high >= open),
    CHECK (high >= close),
    CHECK (date_trunc('minute', ts) = ts)
);

CREATE TABLE ingestion_checkpoints (
    instrument_uid VARCHAR NOT NULL REFERENCES instruments(instrument_uid),
    interval VARCHAR NOT NULL,
    requested_from TIMESTAMPTZ NOT NULL,
    requested_to TIMESTAMPTZ NOT NULL,
    completed_until TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    last_error VARCHAR,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (instrument_uid, interval),
    CHECK (requested_from < requested_to)
);

CREATE TABLE data_gaps (
    instrument_uid VARCHAR NOT NULL REFERENCES instruments(instrument_uid),
    start_ts TIMESTAMPTZ NOT NULL,
    end_ts TIMESTAMPTZ NOT NULL,
    classification VARCHAR NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (instrument_uid, start_ts, end_ts),
    CHECK (start_ts < end_ts)
);

CREATE TABLE data_quality_runs (
    run_id VARCHAR PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    summary VARCHAR
);
