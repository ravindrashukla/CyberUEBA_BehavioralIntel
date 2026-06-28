-- Migration 002: Daily feature aggregation table (Silver layer)
--
-- 2026-05-27. Core aggregation unit for CyberUEBA.
-- One row per user per day, aggregated from 7 raw log types.
-- In cyber, daily granularity matters — an insider can exfiltrate in hours.
--
-- Features map to the 5 behavioral zones:
--   identity:          role, department, clearance (from entity table, not daily)
--   access_pattern:    auth_total, auth_fail_rate, auth_off_hours_ratio, ...
--   data_behavior:     file_total, file_restricted_ratio, file_write_ratio, ...
--   network_footprint: net_bytes_out, net_unique_dsts, net_external_ratio, ...
--   risk_posture:      endpoint_suspicious_ratio, endpoint_max_risk, ...

BEGIN;

CREATE TABLE IF NOT EXISTS daily_features (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT          NOT NULL,
    feature_date    DATE          NOT NULL,

    -- access_pattern zone (from auth_logs)
    auth_total              INT       NOT NULL DEFAULT 0,
    auth_success            INT       NOT NULL DEFAULT 0,
    auth_fail_rate          FLOAT     NOT NULL DEFAULT 0.0,
    auth_off_hours_ratio    FLOAT     NOT NULL DEFAULT 0.0,
    auth_unique_sources     INT       NOT NULL DEFAULT 0,
    auth_unique_dests       INT       NOT NULL DEFAULT 0,
    auth_methods            INT       NOT NULL DEFAULT 0,

    -- data_behavior zone (from file_access_logs)
    file_total              INT       NOT NULL DEFAULT 0,
    file_restricted_ratio   FLOAT     NOT NULL DEFAULT 0.0,
    file_confidential_ratio FLOAT     NOT NULL DEFAULT 0.0,
    file_write_ratio        FLOAT     NOT NULL DEFAULT 0.0,
    file_unique_paths       INT       NOT NULL DEFAULT 0,
    file_total_bytes        BIGINT    NOT NULL DEFAULT 0,

    -- network_footprint zone (from network_flows + dns_queries)
    net_bytes_out           BIGINT    NOT NULL DEFAULT 0,
    net_unique_dsts         INT       NOT NULL DEFAULT 0,
    net_external_ratio      FLOAT     NOT NULL DEFAULT 0.0,
    dns_unique_domains      INT       NOT NULL DEFAULT 0,
    dns_nxdomain_ratio      FLOAT     NOT NULL DEFAULT 0.0,

    -- risk_posture zone (from endpoint_telemetry)
    endpoint_total          INT       NOT NULL DEFAULT 0,
    endpoint_suspicious_ratio FLOAT   NOT NULL DEFAULT 0.0,
    endpoint_max_risk       INT       NOT NULL DEFAULT 0,
    endpoint_mean_risk      FLOAT     NOT NULL DEFAULT 0.0,
    endpoint_unique_processes INT     NOT NULL DEFAULT 0,

    -- app_activity zone (from app_activity_logs)
    app_total               INT       NOT NULL DEFAULT 0,
    app_unique_apps         INT       NOT NULL DEFAULT 0,
    app_admin_actions       INT       NOT NULL DEFAULT 0,
    app_export_count        INT       NOT NULL DEFAULT 0,
    app_error_ratio         FLOAT     NOT NULL DEFAULT 0.0,

    -- privilege zone (from privilege_operations)
    priv_total              INT       NOT NULL DEFAULT 0,
    priv_elevations         INT       NOT NULL DEFAULT 0,
    priv_denied_ratio       FLOAT     NOT NULL DEFAULT 0.0,

    computed_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT daily_features_uq UNIQUE (user_id, feature_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_features_user_date
    ON daily_features (user_id, feature_date);

CREATE INDEX IF NOT EXISTS idx_daily_features_date
    ON daily_features (feature_date);

COMMENT ON TABLE daily_features IS
    'Daily aggregated features per user from 7 raw log types. Silver layer. '
    'One row per user per day. Upsert via ON CONFLICT (user_id, feature_date).';

COMMIT;
