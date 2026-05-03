-- =============================================================================
-- CyberUEBA Behavioral Intelligence — Simplified Schema (TEXT IDs)
-- Matches simulator CSV output directly for rapid dev/demo.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- ENTITY TABLES
-- =============================================================================

CREATE TABLE users (
    user_id         TEXT PRIMARY KEY,
    username        TEXT NOT NULL,
    user_type       TEXT NOT NULL,
    department      TEXT,
    role            TEXT,
    clearance_level TEXT,
    manager_id      TEXT,
    tenure_days     INT,
    primary_device_id TEXT,
    primary_location TEXT,
    subnet          TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE network_segments (
    segment_id          TEXT PRIMARY KEY,
    cidr                TEXT NOT NULL,
    vlan                INT,
    zone                TEXT NOT NULL,
    trust_level         INT NOT NULL,
    adjacent_segments   TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE devices (
    device_id       TEXT PRIMARY KEY,
    hostname        TEXT NOT NULL,
    device_type     TEXT NOT NULL,
    os              TEXT,
    ip_address      TEXT,
    segment_id      TEXT REFERENCES network_segments(segment_id),
    owner_user_id   TEXT REFERENCES users(user_id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE applications (
    app_id              TEXT PRIMARY KEY,
    app_name            TEXT NOT NULL,
    app_type            TEXT NOT NULL,
    data_classification TEXT,
    hosting_segment     TEXT,
    criticality         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- LOG TABLES (high-volume, BIGSERIAL PK)
-- =============================================================================

CREATE TABLE auth_logs (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    device_id       TEXT REFERENCES devices(device_id),
    source_ip       TEXT,
    dest_system     TEXT,
    success         BOOLEAN,
    auth_method     TEXT,
    failure_reason  TEXT,
    geo_location    TEXT,
    attack_id       TEXT
);

CREATE TABLE network_flows (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    src_ip          TEXT,
    dst_ip          TEXT,
    src_port        INT,
    dst_port        INT,
    protocol        TEXT,
    bytes_in        BIGINT,
    bytes_out       BIGINT,
    duration_ms     FLOAT,
    tcp_flags       TEXT,
    attack_id       TEXT
);

CREATE TABLE dns_queries (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    device_id       TEXT NOT NULL,
    query_name      TEXT,
    record_type     TEXT,
    response_code   TEXT,
    response_ip     TEXT,
    ttl             INT,
    server_ip       TEXT,
    attack_id       TEXT
);

CREATE TABLE endpoint_telemetry (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    device_id       TEXT NOT NULL,
    user_id         TEXT,
    event_type      TEXT,
    process_name    TEXT,
    process_hash    TEXT,
    parent_process  TEXT,
    file_path       TEXT,
    command_line    TEXT,
    risk_score      INT,
    attack_id       TEXT
);

CREATE TABLE file_access_logs (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    user_id         TEXT NOT NULL,
    file_path       TEXT,
    operation       TEXT,
    file_size_bytes BIGINT,
    data_classification TEXT,
    source_device_id TEXT,
    success         BOOLEAN,
    attack_id       TEXT
);

CREATE TABLE app_activity_logs (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    user_id         TEXT NOT NULL,
    app_id          TEXT,
    event_type      TEXT,
    action_detail   TEXT,
    data_volume_bytes BIGINT,
    source_ip       TEXT,
    response_code   INT,
    duration_ms     FLOAT,
    attack_id       TEXT
);

CREATE TABLE privilege_operations (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    actor_user_id   TEXT NOT NULL,
    target_user_id  TEXT,
    operation       TEXT,
    resource        TEXT,
    justification   TEXT,
    approved        BOOLEAN,
    approver_id     TEXT,
    attack_id       TEXT
);

-- =============================================================================
-- EMBEDDING + TRAJECTORY TABLES
-- =============================================================================

CREATE TABLE behavioral_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    entity_type     TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    cutoff_date     DATE NOT NULL,
    signal_1        vector(1536),
    signal_2        vector(1536),
    signal_3        vector(1536),
    signal_4        vector(1536),
    signal_5        vector(1536),
    composite       vector(1536),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(entity_type, entity_id, cutoff_date)
);

CREATE TABLE trajectory_events (
    id              BIGSERIAL PRIMARY KEY,
    entity_type     TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type      TEXT NOT NULL,
    severity        TEXT NOT NULL,
    drift_magnitude FLOAT,
    concept_alignments JSONB,
    mitre_techniques TEXT[],
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'new',
    kill_chain_id   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE kill_chain_sequences (
    id              TEXT PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT NOT NULL DEFAULT 'active',
    severity        TEXT,
    entities_involved TEXT[],
    narrative       TEXT
);

-- =============================================================================
-- INDEXES
-- =============================================================================

CREATE INDEX idx_auth_logs_user_ts ON auth_logs(user_id, timestamp);
CREATE INDEX idx_auth_logs_device_ts ON auth_logs(device_id, timestamp);
CREATE INDEX idx_network_flows_ts ON network_flows(timestamp);
CREATE INDEX idx_network_flows_src ON network_flows(src_ip, timestamp);
CREATE INDEX idx_dns_device_ts ON dns_queries(device_id, timestamp);
CREATE INDEX idx_endpoint_device_ts ON endpoint_telemetry(device_id, timestamp);
CREATE INDEX idx_file_access_user_ts ON file_access_logs(user_id, timestamp);
CREATE INDEX idx_app_user_ts ON app_activity_logs(user_id, timestamp);
CREATE INDEX idx_priv_actor_ts ON privilege_operations(actor_user_id, timestamp);
CREATE INDEX idx_snapshots_entity ON behavioral_snapshots(entity_type, entity_id, cutoff_date);
CREATE INDEX idx_events_entity ON trajectory_events(entity_type, entity_id);
CREATE INDEX idx_events_severity ON trajectory_events(severity, status);

-- HNSW vector index on composite embeddings
CREATE INDEX idx_snapshot_composite_hnsw ON behavioral_snapshots
    USING hnsw (composite vector_cosine_ops) WITH (m = 16, ef_construction = 64);
