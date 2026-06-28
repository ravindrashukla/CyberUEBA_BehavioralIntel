-- Migration 004: Bi-temporal embedding history for users
--
-- 2026-05-27. Ported from DLA MVP migration 028.
--
-- Embeddings live on their own bi-temporal history table, separate from
-- the daily behavioral_snapshots. Reasons:
--   1. Retention profile differs — embeddings recomputed on model retrains
--   2. History table supports model versioning (embedding_model column)
--   3. Bi-temporal: valid_from/to (when fact is true) + knowledge_from/to (when we learned it)
--
-- Layout: one row per (user_id, embedding_model, time-version). All 5 zone
-- vectors + composite land on the same row (wide layout).
--
-- SCD2 guard trigger is applied after initial backfill to enforce
-- write-through-temporal-store invariant.

BEGIN;

CREATE TABLE IF NOT EXISTS user_embeddings_history (
    history_id          BIGSERIAL PRIMARY KEY,
    user_id             TEXT          NOT NULL,

    -- 5 zone embeddings (1536-d each)
    zone_identity           vector(1536),
    zone_access_pattern     vector(1536),
    zone_data_behavior      vector(1536),
    zone_network_footprint  vector(1536),
    zone_risk_posture       vector(1536),

    -- Attention-weighted composite
    composite               vector(1536),

    embedding_model     TEXT          NOT NULL DEFAULT 'v1',

    -- Bi-temporal columns
    valid_from          DATE          NOT NULL,
    valid_to            DATE,
    knowledge_from      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    knowledge_to        TIMESTAMPTZ,
    reason              TEXT          NOT NULL DEFAULT 'initial_load',

    CONSTRAINT user_emb_history_valid_chk
        CHECK (valid_to IS NULL OR valid_to >= valid_from),
    CONSTRAINT user_emb_history_knowledge_chk
        CHECK (knowledge_to IS NULL OR knowledge_to >= knowledge_from)
);

-- Partial unique index: only one open row per (user_id, model) at a time
CREATE UNIQUE INDEX IF NOT EXISTS user_emb_history_current_uq
    ON user_embeddings_history (user_id, embedding_model)
    WHERE valid_to IS NULL AND knowledge_to IS NULL;

CREATE INDEX IF NOT EXISTS user_emb_history_valid_ix
    ON user_embeddings_history (user_id, embedding_model, valid_from, valid_to);

CREATE INDEX IF NOT EXISTS user_emb_history_knowledge_ix
    ON user_embeddings_history (user_id, embedding_model, knowledge_from, knowledge_to);

-- HNSW index on composite for similarity search across history
CREATE INDEX IF NOT EXISTS user_emb_history_composite_hnsw
    ON user_embeddings_history
    USING hnsw (composite vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

COMMENT ON TABLE user_embeddings_history IS
    'Bi-temporal embedding history for users. Wide-row layout (5 zone vectors + '
    'composite per row). Writes must route through pipeline.temporal_store. '
    'SCD2 protocol: supersede old row, insert closed historical, insert new open.';

-- Apply SCD2 guard trigger to protect history table
CREATE TRIGGER user_emb_history_guard
    BEFORE INSERT OR UPDATE OR DELETE ON user_embeddings_history
    FOR EACH ROW EXECUTE FUNCTION temporal_scd2_guard();

-- Also apply guard to trajectory_events (append-only)
CREATE TRIGGER traj_events_guard
    BEFORE INSERT OR UPDATE OR DELETE ON trajectory_events
    FOR EACH ROW EXECUTE FUNCTION temporal_scd2_guard();

COMMIT;
