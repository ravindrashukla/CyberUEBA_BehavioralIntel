-- Migration 006: Alerts, Kill Chains, and Log Stats tables
--
-- Stores pipeline-generated alerts and kill chain reconstructions
-- that the Streamlit dashboard reads from JSON files.

BEGIN;

-- 1. Alerts (one row per behavioral anomaly alert)
CREATE TABLE IF NOT EXISTS alerts (
    id                  TEXT PRIMARY KEY,
    entity_type         TEXT NOT NULL DEFAULT 'user',
    entity_id           TEXT NOT NULL,
    severity            TEXT NOT NULL DEFAULT 'medium',
    title               TEXT NOT NULL,
    description         TEXT,
    drift_magnitude     FLOAT,
    concept_alignments  JSONB DEFAULT '[]',
    mitre_techniques    JSONB DEFAULT '[]',
    detected_at         TIMESTAMPTZ,
    status              TEXT DEFAULT 'new',
    detection_method    TEXT,
    confidence          FLOAT,
    kill_chain_id       TEXT,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alerts_entity
    ON alerts (entity_id);
CREATE INDEX IF NOT EXISTS idx_alerts_severity
    ON alerts (severity);

-- 2. Kill chains (one row per reconstructed attack chain)
CREATE TABLE IF NOT EXISTS kill_chains (
    id                  TEXT PRIMARY KEY,
    created_at          TIMESTAMPTZ,
    status              TEXT DEFAULT 'active',
    severity            TEXT DEFAULT 'medium',
    duration_seconds    FLOAT,
    tactics_observed    JSONB DEFAULT '[]',
    entities_involved   JSONB DEFAULT '[]',
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Kill chain events (one row per event in a chain)
CREATE TABLE IF NOT EXISTS kill_chain_events (
    id                  BIGSERIAL PRIMARY KEY,
    kill_chain_id       TEXT NOT NULL REFERENCES kill_chains(id) ON DELETE CASCADE,
    alert_id            TEXT,
    entity_type         TEXT DEFAULT 'user',
    entity_id           TEXT NOT NULL,
    timestamp           TIMESTAMPTZ,
    tactic              TEXT,
    techniques          JSONB DEFAULT '[]',
    description         TEXT,
    confidence          FLOAT,
    event_order         INT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_kc_events_chain
    ON kill_chain_events (kill_chain_id, event_order);

-- 4. Log stats (one row per telemetry source)
CREATE TABLE IF NOT EXISTS log_stats (
    source              TEXT PRIMARY KEY,
    file_count          INT NOT NULL DEFAULT 0,
    sample_rows         INT NOT NULL DEFAULT 0,
    est_total_events    BIGINT NOT NULL DEFAULT 0,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 5. Drift series (one row per entity per cutoff date)
CREATE TABLE IF NOT EXISTS drift_series (
    id                  BIGSERIAL PRIMARY KEY,
    entity_type         TEXT NOT NULL DEFAULT 'user',
    entity_id           TEXT NOT NULL,
    cutoff_date         DATE NOT NULL,
    drift_from_first    FLOAT,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT drift_series_uq UNIQUE (entity_type, entity_id, cutoff_date)
);

CREATE INDEX IF NOT EXISTS idx_drift_series_entity
    ON drift_series (entity_id, cutoff_date);

COMMIT;
