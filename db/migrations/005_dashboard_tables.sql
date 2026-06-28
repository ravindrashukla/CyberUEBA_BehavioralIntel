-- Migration 005: Dashboard analytics tables
--
-- Stores derived detection results that the Streamlit dashboard reads.
-- Replaces CSV-based data loading with PostgreSQL queries.

BEGIN;

-- 1. Composite scores (one row per user, from 5-phase composite scoring)
CREATE TABLE IF NOT EXISTS composite_scores (
    uid                 TEXT PRIMARY KEY,
    is_attack           BOOLEAN NOT NULL DEFAULT FALSE,
    grp                 TEXT,
    role                TEXT,
    signal_strength     FLOAT,
    breadth_15          INT,
    breadth_20          INT,
    sustained_signal    FLOAT,
    ctx_spread_z        FLOAT,
    ctx_max_z           FLOAT,
    novelty_score       FLOAT,
    composite           FLOAT NOT NULL,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_composite_scores_composite
    ON composite_scores (composite DESC);

-- 2. Detection results (one row per user, all method scores)
CREATE TABLE IF NOT EXISTS detection_results (
    user_id             TEXT PRIMARY KEY,
    is_attack           BOOLEAN NOT NULL DEFAULT FALSE,
    iforest_score       FLOAT,
    iforest_anomaly     BOOLEAN DEFAULT FALSE,
    ocsvm_score         FLOAT,
    ocsvm_anomaly       BOOLEAN DEFAULT FALSE,
    lof_score           FLOAT,
    lof_anomaly         BOOLEAN DEFAULT FALSE,
    zscore_max          FLOAT,
    zscore_anomaly      BOOLEAN DEFAULT FALSE,
    temporal_max_z      FLOAT,
    temporal_mean_z     FLOAT,
    temporal_anomaly    BOOLEAN DEFAULT FALSE,
    feat_cusum_value    FLOAT,
    feat_cusum_detected BOOLEAN DEFAULT FALSE,
    acecard_cusum_value FLOAT,
    acecard_cusum_detected BOOLEAN DEFAULT FALSE,
    t3_cusum_max        FLOAT,
    t3_cusum_detected   BOOLEAN DEFAULT FALSE,
    extra_columns       JSONB DEFAULT '{}',
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Novelty metrics (one row per user)
CREATE TABLE IF NOT EXISTS novelty_metrics (
    uid                      TEXT PRIMARY KEY,
    persistent_novel_ips     INT,
    novel_ip_max_persistence INT,
    novel_ip_weeks_frac      FLOAT,
    computed_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4. Z-scored features (one row per user, z-scores as JSONB)
CREATE TABLE IF NOT EXISTS zscored_features (
    uid         TEXT PRIMARY KEY,
    is_attack   BOOLEAN NOT NULL DEFAULT FALSE,
    grp         TEXT,
    role        TEXT,
    z_scores    JSONB NOT NULL DEFAULT '{}',
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 5. Weekly trajectories (one row per user per week)
CREATE TABLE IF NOT EXISTS weekly_trajectories (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT NOT NULL,
    is_attack           BOOLEAN NOT NULL DEFAULT FALSE,
    department          TEXT,
    role                TEXT,
    week_idx            INT NOT NULL,
    week_start          DATE,
    week_end            DATE,
    identity_drift              FLOAT,
    access_pattern_drift        FLOAT,
    data_behavior_drift         FLOAT,
    network_footprint_drift     FLOAT,
    risk_posture_drift          FLOAT,
    composite_drift             FLOAT,
    velocity                    FLOAT,
    acceleration                FLOAT,
    week_to_week_drift          FLOAT,
    composite_drift_normal_ops          FLOAT,
    composite_drift_insider_investigation FLOAT,
    composite_drift_apt_hunt            FLOAT,
    composite_drift_privilege_audit     FLOAT,
    relationship_drift          FLOAT,
    zone_divergence             FLOAT,
    computed_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT weekly_traj_uq UNIQUE (user_id, week_idx)
);

CREATE INDEX IF NOT EXISTS idx_weekly_traj_user
    ON weekly_trajectories (user_id, week_idx);

-- 6. Weekly features (one row per user per week, scalar features)
CREATE TABLE IF NOT EXISTS weekly_features (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL,
    week_idx    INT NOT NULL,
    week_start  DATE,
    week_end    DATE,
    features    JSONB NOT NULL DEFAULT '{}',
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT weekly_feat_uq UNIQUE (user_id, week_idx)
);

CREATE INDEX IF NOT EXISTS idx_weekly_feat_user
    ON weekly_features (user_id, week_idx);

COMMIT;
