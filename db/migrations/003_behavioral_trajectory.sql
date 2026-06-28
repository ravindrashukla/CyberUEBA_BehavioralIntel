-- Migration 003: Behavioral snapshots + trajectory analysis tables (Gold layer)
--
-- 2026-05-27. Ported from DLA MVP migration 040, adapted for cyber domain.
--
-- Three tables:
--   behavioral_snapshots  — daily 5-zone embedding snapshots (5 × 1536-d + composite)
--   trajectory_snapshots  — daily velocity/acceleration/regime features
--   trajectory_events     — detected change-points, regime shifts, anomalies
--
-- Drops and recreates behavioral_snapshots and trajectory_events from schema_simple.sql
-- to match the new schema with proper zone naming and daily cadence.

BEGIN;

-- Drop old tables from schema_simple.sql (they have incompatible schemas)
DROP TABLE IF EXISTS kill_chain_sequences CASCADE;
DROP TABLE IF EXISTS trajectory_events CASCADE;
DROP TABLE IF EXISTS behavioral_snapshots CASCADE;

-- 1. Behavioral embedding snapshots (daily, per user)
CREATE TABLE behavioral_snapshots (
    snapshot_id         BIGSERIAL PRIMARY KEY,
    entity_type         TEXT          NOT NULL,
    entity_id           TEXT          NOT NULL,
    cutoff_date         DATE          NOT NULL,

    -- 5 behavioral zone embeddings (1536-d each)
    zone_identity           vector(1536),
    zone_access_pattern     vector(1536),
    zone_data_behavior      vector(1536),
    zone_network_footprint  vector(1536),
    zone_risk_posture       vector(1536),

    -- Attention-weighted composite
    composite               vector(1536),

    -- Context-specific composites (4 weighting scenarios)
    composite_normal_ops        vector(1536),
    composite_insider_inv       vector(1536),
    composite_apt_hunt          vector(1536),
    composite_privilege_audit   vector(1536),

    -- Zone serialization texts (for audit/debugging)
    zone_texts          JSONB,

    computed_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT beh_snap_type_chk
        CHECK (entity_type IN ('user', 'device', 'segment', 'application')),
    CONSTRAINT beh_snap_uq
        UNIQUE (entity_type, entity_id, cutoff_date)
);

CREATE INDEX IF NOT EXISTS idx_beh_snap_entity_date
    ON behavioral_snapshots (entity_type, entity_id, cutoff_date);

CREATE INDEX IF NOT EXISTS idx_beh_snap_date
    ON behavioral_snapshots (cutoff_date);

CREATE INDEX IF NOT EXISTS idx_beh_snap_composite_hnsw
    ON behavioral_snapshots
    USING hnsw (composite vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

COMMENT ON TABLE behavioral_snapshots IS
    'Daily behavioral embedding snapshots. 5 zone vectors + composite + 4 context '
    'composites per entity per day. Gold layer. 1536-d pgvector.';

-- 2. Trajectory snapshots (velocity, acceleration, regime per day)
CREATE TABLE trajectory_snapshots (
    snapshot_id     BIGSERIAL PRIMARY KEY,
    entity_type     TEXT          NOT NULL,
    entity_id       TEXT          NOT NULL,
    cutoff_date     DATE          NOT NULL,

    -- Scalar trajectory features
    velocity_magnitude      FLOAT,
    acceleration            FLOAT,
    stability               FLOAT,
    regime_shifts           FLOAT,
    trend_consistency       FLOAT,
    total_drift             FLOAT,
    current_regime          TEXT,

    -- Per-zone drift magnitudes
    zone_drifts             JSONB,

    -- Per-context drift magnitudes
    context_drifts          JSONB,

    -- Full velocity vector (optional, for advanced analysis)
    velocity_vector         vector(1536),

    -- Relationship drift (UserDevice Hadamard)
    relationship_drift      FLOAT,

    computed_at             TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT traj_snap_type_chk
        CHECK (entity_type IN ('user', 'device', 'segment', 'application')),
    CONSTRAINT traj_snap_uq
        UNIQUE (entity_type, entity_id, cutoff_date)
);

CREATE INDEX IF NOT EXISTS idx_traj_snap_entity_date
    ON trajectory_snapshots (entity_type, entity_id, cutoff_date);

CREATE INDEX IF NOT EXISTS idx_traj_snap_date
    ON trajectory_snapshots (cutoff_date);

COMMENT ON TABLE trajectory_snapshots IS
    'Daily trajectory features per entity. Velocity, acceleration, regime, '
    'zone-specific and context-specific drifts. Computed from behavioral_snapshots series.';

-- 3. Trajectory events (change-points with attribution)
CREATE TABLE trajectory_events (
    event_id                BIGSERIAL PRIMARY KEY,
    entity_type             TEXT          NOT NULL,
    entity_id               TEXT          NOT NULL,
    event_date              DATE          NOT NULL,
    event_type              TEXT          NOT NULL,
    shift_type              TEXT,
    severity                TEXT          NOT NULL,
    magnitude               FLOAT,
    direction               TEXT,
    contributing_factors    JSONB         NOT NULL DEFAULT '{}',
    from_regime             JSONB,
    to_regime               JSONB,
    mitre_techniques        TEXT[],
    description             TEXT,
    detected_at             TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT traj_event_type_chk
        CHECK (event_type IN ('regime_shift', 'trend_change',
                              'behavioral_shift', 'anomaly')),
    CONSTRAINT traj_event_shift_chk
        CHECK (shift_type IS NULL OR shift_type IN ('gradual', 'abrupt')),
    CONSTRAINT traj_event_dir_chk
        CHECK (direction IS NULL OR direction IN ('improving', 'degrading', 'lateral')),
    CONSTRAINT traj_event_severity_chk
        CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info'))
);

CREATE INDEX IF NOT EXISTS idx_traj_event_entity_date
    ON trajectory_events (entity_type, entity_id, event_date);

CREATE INDEX IF NOT EXISTS idx_traj_event_type_date
    ON trajectory_events (event_type, event_date);

CREATE INDEX IF NOT EXISTS idx_traj_event_severity
    ON trajectory_events (severity);

COMMENT ON TABLE trajectory_events IS
    'Detected change-points, regime shifts, and behavioral anomalies with '
    'full attribution in contributing_factors JSONB.';

COMMIT;
