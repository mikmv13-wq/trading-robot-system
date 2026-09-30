CREATE TABLE database_metadata (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL
);

INSERT INTO database_metadata(key, value) VALUES
    ('database_kind', 'market'),
    ('schema_baseline', 'stage-0');
