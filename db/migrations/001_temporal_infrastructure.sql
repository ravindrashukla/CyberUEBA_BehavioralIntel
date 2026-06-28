-- Migration 001: Temporal infrastructure — session var + SCD2 guard trigger
--
-- 2026-05-27. Ported from DLA MVP migration 010.
--
-- Two reusable server-side objects:
--   1. app_set_temporal_write(BOOLEAN) — transaction-local session variable toggle
--   2. temporal_scd2_guard() — BEFORE trigger that blocks direct writes unless
--      app.temporal_write = 'on'. Applied to all *_history and *_events tables.

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

-- 1. Session-variable setter
CREATE OR REPLACE FUNCTION app_set_temporal_write(enabled BOOLEAN)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM set_config(
        'app.temporal_write',
        CASE WHEN enabled THEN 'on' ELSE 'off' END,
        true  -- is_local = true → resets at end of current transaction
    );
END;
$$;

COMMENT ON FUNCTION app_set_temporal_write(BOOLEAN) IS
    'Toggles the transaction-local app.temporal_write session variable. '
    'Gates mutation on *_history / *_events tables via temporal_scd2_guard.';

-- 2. SCD2 guard trigger function
CREATE OR REPLACE FUNCTION temporal_scd2_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(current_setting('app.temporal_write', true), 'off') <> 'on' THEN
        RAISE EXCEPTION
            'Direct % on temporal table % is blocked. '
            'Route writes through pipeline.temporal_store.',
            TG_OP, TG_TABLE_NAME
            USING HINT =
                'Ensure set_temporal_write(conn, True) was called in the same transaction.',
            ERRCODE = 'insufficient_privilege';
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    ELSE
        RETURN NEW;
    END IF;
END;
$$;

COMMENT ON FUNCTION temporal_scd2_guard() IS
    'BEFORE trigger applied to *_history and *_events tables. Raises unless '
    'the caller has opened a temporal write window via app_set_temporal_write(TRUE).';

COMMIT;
