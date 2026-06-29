-- =============================================================================
-- CyberUEBA Behavioral Intelligence — PostgreSQL Schema
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- ENTITY TABLES
-- =============================================================================

CREATE TABLE users (
    user_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        TEXT NOT NULL UNIQUE,
    display_name    TEXT,
    user_type       TEXT NOT NULL CHECK (user_type IN ('employee', 'contractor', 'service_account')),
    department      TEXT,
    role            TEXT,
    clearance_level TEXT,
    manager_id      UUID REFERENCES users(user_id),
    hire_date       DATE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE network_segments (
    segment_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_name        TEXT NOT NULL UNIQUE,
    subnet_cidr         CIDR NOT NULL,
    vlan_id             INT,
    zone_type           TEXT NOT NULL CHECK (zone_type IN ('dmz', 'internal', 'restricted', 'management', 'guest')),
    trust_level         INT NOT NULL CHECK (trust_level BETWEEN 1 AND 5),
    gateway_ip          INET,
    connected_segments  TEXT[],
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE devices (
    device_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hostname        TEXT NOT NULL,
    device_type     TEXT NOT NULL CHECK (device_type IN ('endpoint', 'server', 'network_appliance', 'iot')),
    os_type         TEXT,
    os_version      TEXT,
    ip_address      INET,
    mac_address     MACADDR,
    segment_id      UUID REFERENCES network_segments(segment_id),
    owner_user_id   UUID REFERENCES users(user_id),
    criticality     TEXT,
    last_seen       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE applications (
    app_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_name            TEXT NOT NULL,
    app_type            TEXT NOT NULL CHECK (app_type IN ('service', 'database', 'cloud_resource', 'web_app', 'api')),
    owner_team          TEXT,
    data_classification TEXT NOT NULL CHECK (data_classification IN ('public', 'internal', 'confidential', 'restricted')),
    hosting_segment     UUID REFERENCES network_segments(segment_id),
    criticality         TEXT,
    version             TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    session_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(user_id),
    device_id       UUID NOT NULL REFERENCES devices(device_id),
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ,
    src_ip          INET,
    auth_method     TEXT,
    risk_score      NUMERIC,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- LOG TABLES (high-volume)
-- =============================================================================

CREATE TABLE auth_logs (
    log_id          BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    user_id         UUID NOT NULL REFERENCES users(user_id),
    device_id       UUID REFERENCES devices(device_id),
    source_ip       INET,
    dest_system     TEXT,
    success         BOOLEAN NOT NULL,
    auth_method     TEXT,
    failure_reason  TEXT,
    geo_location    TEXT,
    session_id      UUID REFERENCES sessions(session_id)
);

CREATE TABLE network_flows (
    flow_id         BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    src_ip          INET NOT NULL,
    dst_ip          INET NOT NULL,
    src_port        INT,
    dst_port        INT,
    protocol        TEXT,
    bytes_in        BIGINT,
    bytes_out       BIGINT,
    duration_ms     INT,
    tcp_flags       TEXT,
    device_id       UUID REFERENCES devices(device_id),
    segment_id      UUID REFERENCES network_segments(segment_id)
);

CREATE TABLE dns_queries (
    query_id        BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    client_ip       INET NOT NULL,
    query_domain    TEXT NOT NULL,
    query_type      TEXT,
    response_code   TEXT,
    response_ip     INET,
    device_id       UUID REFERENCES devices(device_id)
);

CREATE TABLE endpoint_telemetry (
    event_id        BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    device_id       UUID NOT NULL REFERENCES devices(device_id),
    process_name    TEXT,
    parent_process  TEXT,
    command_line    TEXT,
    user_id         UUID REFERENCES users(user_id),
    file_access_path TEXT,
    registry_key    TEXT,
    event_type      TEXT
);

CREATE TABLE file_access_logs (
    access_id           BIGSERIAL PRIMARY KEY,
    timestamp           TIMESTAMPTZ NOT NULL,
    user_id             UUID NOT NULL REFERENCES users(user_id),
    file_path           TEXT NOT NULL,
    operation           TEXT NOT NULL CHECK (operation IN ('read', 'write', 'delete', 'copy', 'move')),
    bytes               BIGINT,
    sensitivity_level   TEXT,
    device_id           UUID REFERENCES devices(device_id),
    app_id              UUID REFERENCES applications(app_id)
);

CREATE TABLE app_activity_logs (
    activity_id         BIGSERIAL PRIMARY KEY,
    timestamp           TIMESTAMPTZ NOT NULL,
    user_id             UUID NOT NULL REFERENCES users(user_id),
    app_id              UUID NOT NULL REFERENCES applications(app_id),
    action              TEXT,
    resource            TEXT,
    status_code         INT,
    response_time_ms    INT,
    data_volume_bytes   BIGINT
);

CREATE TABLE privilege_operations (
    op_id               BIGSERIAL PRIMARY KEY,
    timestamp           TIMESTAMPTZ NOT NULL,
    user_id             UUID NOT NULL REFERENCES users(user_id),
    operation           TEXT NOT NULL,
    target_resource     TEXT,
    previous_level      TEXT,
    new_level           TEXT,
    approved_by         UUID REFERENCES users(user_id),
    justification       TEXT,
    auto_approved       BOOLEAN NOT NULL DEFAULT FALSE
);

-- =============================================================================
-- BEHAVIORAL EMBEDDING TABLES (all vectors 1536-d)
-- =============================================================================

CREATE TABLE user_behavioral_embeddings (
    user_id             UUID PRIMARY KEY REFERENCES users(user_id),
    beh_authentication  vector(1536),
    beh_privilege       vector(1536),
    beh_data_access     vector(1536),
    beh_network         vector(1536),
    beh_communication   vector(1536),
    beh_composite       vector(1536),
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE device_behavioral_embeddings (
    device_id           UUID PRIMARY KEY REFERENCES devices(device_id),
    beh_process         vector(1536),
    beh_network_traffic vector(1536),
    beh_resource        vector(1536),
    beh_authentication  vector(1536),
    beh_configuration   vector(1536),
    beh_composite       vector(1536),
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE segment_behavioral_embeddings (
    segment_id              UUID PRIMARY KEY REFERENCES network_segments(segment_id),
    beh_traffic_volume      vector(1536),
    beh_connections         vector(1536),
    beh_protocols           vector(1536),
    beh_threat_indicators   vector(1536),
    beh_service_exposure    vector(1536),
    beh_composite           vector(1536),
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE app_behavioral_embeddings (
    app_id              UUID PRIMARY KEY REFERENCES applications(app_id),
    beh_access_patterns vector(1536),
    beh_query_behavior  vector(1536),
    beh_error_rates     vector(1536),
    beh_performance     vector(1536),
    beh_configuration   vector(1536),
    beh_composite       vector(1536),
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE session_behavioral_embeddings (
    session_id          UUID PRIMARY KEY REFERENCES sessions(session_id),
    beh_activity        vector(1536),
    beh_risk_accum      vector(1536),
    beh_data_movement   vector(1536),
    beh_lateral         vector(1536),
    beh_temporal        vector(1536),
    beh_composite       vector(1536),
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- TRAJECTORY TABLES
-- =============================================================================

CREATE TABLE trajectory_snapshots (
    snapshot_id     BIGSERIAL PRIMARY KEY,
    entity_type     TEXT NOT NULL,
    entity_id       UUID NOT NULL,
    cutoff_date     DATE NOT NULL,
    features        JSONB,
    velocity        JSONB,
    acceleration    JSONB,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (entity_type, entity_id, cutoff_date)
);

-- NOTE: This definition is SUPERSEDED. db/migrations/003_behavioral_trajectory.sql
-- DROPs and recreates behavioral_snapshots with zone-named columns
-- (zone_identity, zone_access_pattern, ... composite, composite_*context, zone_texts).
-- The live runtime schema is migration 003; the columns below are legacy/stale.
CREATE TABLE behavioral_snapshots (
    snapshot_id     BIGSERIAL PRIMARY KEY,
    entity_type     TEXT NOT NULL,
    entity_id       UUID NOT NULL,
    cutoff_date     DATE NOT NULL,
    beh_signal_1    vector(1536),
    beh_signal_2    vector(1536),
    beh_signal_3    vector(1536),
    beh_signal_4    vector(1536),
    beh_signal_5    vector(1536),
    beh_composite   vector(1536),
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (entity_type, entity_id, cutoff_date)
);

-- =============================================================================
-- DETECTION TABLES
-- =============================================================================

CREATE TABLE kill_chain_sequences (
    chain_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chain_name          TEXT NOT NULL,
    start_time          TIMESTAMPTZ NOT NULL,
    end_time            TIMESTAMPTZ,
    status              TEXT NOT NULL CHECK (status IN ('active', 'resolved', 'false_positive')),
    confidence          NUMERIC,
    involved_users      TEXT[],
    involved_devices    TEXT[],
    involved_segments   TEXT[],
    attack_narrative    TEXT,
    mitre_tactics       TEXT[],
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE trajectory_events (
    event_id                BIGSERIAL PRIMARY KEY,
    entity_type             TEXT NOT NULL,
    entity_id               UUID NOT NULL,
    event_date              TIMESTAMPTZ NOT NULL,
    event_type              TEXT NOT NULL CHECK (event_type IN ('behavioral_shift', 'anomaly', 'concept_alignment', 'cusum_alert')),
    severity                TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    magnitude               NUMERIC,
    drift_concept           TEXT,
    concept_alignment       NUMERIC,
    contributing_signals    JSONB,
    mitre_techniques        TEXT[],
    kill_chain_id           UUID REFERENCES kill_chain_sequences(chain_id),
    detected_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE kill_chain_events (
    id              BIGSERIAL PRIMARY KEY,
    chain_id        UUID NOT NULL REFERENCES kill_chain_sequences(chain_id),
    event_id        BIGINT NOT NULL REFERENCES trajectory_events(event_id),
    sequence_order  INT NOT NULL,
    entity_type     TEXT NOT NULL,
    entity_id       UUID NOT NULL,
    description     TEXT,
    timestamp       TIMESTAMPTZ NOT NULL
);

-- =============================================================================
-- HNSW INDEXES on beh_composite columns (vector_cosine_ops)
-- =============================================================================

CREATE INDEX idx_user_beh_composite_hnsw
    ON user_behavioral_embeddings
    USING hnsw (beh_composite vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_device_beh_composite_hnsw
    ON device_behavioral_embeddings
    USING hnsw (beh_composite vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_segment_beh_composite_hnsw
    ON segment_behavioral_embeddings
    USING hnsw (beh_composite vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_app_beh_composite_hnsw
    ON app_behavioral_embeddings
    USING hnsw (beh_composite vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_session_beh_composite_hnsw
    ON session_behavioral_embeddings
    USING hnsw (beh_composite vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_behavioral_snap_composite_hnsw
    ON behavioral_snapshots
    USING hnsw (beh_composite vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- =============================================================================
-- BTREE INDEXES on log tables (entity_id, timestamp) for time-window queries
-- =============================================================================

-- auth_logs
CREATE INDEX idx_auth_logs_user_ts ON auth_logs (user_id, timestamp);
CREATE INDEX idx_auth_logs_device_ts ON auth_logs (device_id, timestamp);

-- network_flows
CREATE INDEX idx_network_flows_device_ts ON network_flows (device_id, timestamp);
CREATE INDEX idx_network_flows_segment_ts ON network_flows (segment_id, timestamp);

-- dns_queries
CREATE INDEX idx_dns_queries_device_ts ON dns_queries (device_id, timestamp);

-- endpoint_telemetry
CREATE INDEX idx_endpoint_telemetry_device_ts ON endpoint_telemetry (device_id, timestamp);
CREATE INDEX idx_endpoint_telemetry_user_ts ON endpoint_telemetry (user_id, timestamp);

-- file_access_logs
CREATE INDEX idx_file_access_user_ts ON file_access_logs (user_id, timestamp);
CREATE INDEX idx_file_access_device_ts ON file_access_logs (device_id, timestamp);

-- app_activity_logs
CREATE INDEX idx_app_activity_user_ts ON app_activity_logs (user_id, timestamp);
CREATE INDEX idx_app_activity_app_ts ON app_activity_logs (app_id, timestamp);

-- privilege_operations
CREATE INDEX idx_priv_ops_user_ts ON privilege_operations (user_id, timestamp);

-- trajectory_snapshots
CREATE INDEX idx_traj_snap_entity_date ON trajectory_snapshots (entity_type, entity_id, cutoff_date);

-- behavioral_snapshots
CREATE INDEX idx_beh_snap_entity_date ON behavioral_snapshots (entity_type, entity_id, cutoff_date);

-- trajectory_events
CREATE INDEX idx_traj_events_entity_date ON trajectory_events (entity_type, entity_id, event_date);
CREATE INDEX idx_traj_events_kill_chain ON trajectory_events (kill_chain_id);

-- kill_chain_events
CREATE INDEX idx_kill_chain_events_chain ON kill_chain_events (chain_id, sequence_order);
