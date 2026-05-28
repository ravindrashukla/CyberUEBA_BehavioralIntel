"""DLA MVP Architecture Port Verification Tests.

Validates that the DLA MVP architectural patterns were correctly ported
to the ACECARD cyber system:
  - PostgreSQL + pgvector with SCD2 bi-temporal pattern
  - Temporal write guard (app_set_temporal_write + temporal_scd2_guard)
  - Bronze -> Silver -> Gold pipeline with daily cadence
  - Entity materialization from DB (not in-memory build_entity_zoo)
  - Streamlit DB integration layer

Test IDs: DLA-001 through DLA-015
"""

import importlib
import inspect
import os
import re
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set DB env vars before any pipeline imports
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5437")
os.environ.setdefault("DB_NAME", "cyber_ueba")
os.environ.setdefault("DB_USER", "cyber_ueba")
os.environ.setdefault("DB_PASSWORD", "password")


# ── Fixture: shared DB connection ────────────────────────────────────────────

@pytest.fixture(scope="module")
def db_conn():
    """Module-scoped DB connection for DLA port tests."""
    import psycopg2
    conn = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
    conn.autocommit = True
    yield conn
    conn.close()


# ── DLA-001: Pipeline files exist and are importable ─────────────────────────

EXPECTED_PIPELINE_FILES = [
    "pipeline.daily_ingest",
    "pipeline.behavioral_snapshots",
    "pipeline.trajectory_snapshots",
    "pipeline.embedding_history",
    "pipeline.entity_materialize",
    "pipeline.db_connect",
    "pipeline.streamlit_db",
]


@pytest.mark.p0
def test_pipeline_files_exist_and_importable():
    """DLA-001: All 7 pipeline/*.py files exist and are importable."""
    for module_name in EXPECTED_PIPELINE_FILES:
        # Check file exists
        file_path = PROJECT_ROOT / module_name.replace(".", "/")
        py_path = file_path.with_suffix(".py")
        assert py_path.exists(), f"Missing pipeline file: {py_path}"

        # Check importable
        mod = importlib.import_module(module_name)
        assert mod is not None, f"Failed to import {module_name}"


# ── DLA-002: Migration files exist ───────────────────────────────────────────

EXPECTED_MIGRATIONS = [
    "db/migrations/001_temporal_infrastructure.sql",
    "db/migrations/002_daily_features.sql",
    "db/migrations/003_behavioral_trajectory.sql",
    "db/migrations/004_embeddings_history.sql",
]


@pytest.mark.p0
def test_migration_files_exist():
    """DLA-002: All 4 db/migrations/*.sql files exist."""
    for migration in EXPECTED_MIGRATIONS:
        path = PROJECT_ROOT / migration
        assert path.exists(), f"Missing migration file: {path}"
        # Verify non-empty
        assert path.stat().st_size > 0, f"Migration file is empty: {path}"


# ── DLA-003: DB connection works ─────────────────────────────────────────────

@pytest.mark.p0
def test_db_connection(db_conn):
    """DLA-003: pipeline.db_connect.get_connection() returns a working connection."""
    from pipeline.db_connect import get_connection
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            result = cur.fetchone()[0]
        assert result == 1, f"SELECT 1 returned {result}, expected 1"
    finally:
        conn.close()


# ── DLA-004: pgvector extension installed ────────────────────────────────────

@pytest.mark.p0
def test_pgvector_extension(db_conn):
    """DLA-004: pgvector extension is installed in the database."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        row = cur.fetchone()
    assert row is not None, "pgvector extension 'vector' not found in pg_extension"
    assert row[0] == "vector"


# ── DLA-005: Temporal write guard function exists ────────────────────────────

@pytest.mark.p0
def test_temporal_write_guard(db_conn):
    """DLA-005: app_set_temporal_write function exists in the database."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT routine_name
            FROM information_schema.routines
            WHERE routine_name = 'app_set_temporal_write'
        """)
        row = cur.fetchone()
    assert row is not None, (
        "Function app_set_temporal_write not found in information_schema.routines"
    )
    assert row[0] == "app_set_temporal_write"


# ── DLA-006: SCD2 guard trigger/function exists ─────────────────────────────

@pytest.mark.p0
def test_scd2_trigger(db_conn):
    """DLA-006: temporal_scd2_guard trigger function exists and is applied as a trigger."""
    with db_conn.cursor() as cur:
        # Check the function exists
        cur.execute("""
            SELECT routine_name
            FROM information_schema.routines
            WHERE routine_name = 'temporal_scd2_guard'
        """)
        func_row = cur.fetchone()
        assert func_row is not None, (
            "Function temporal_scd2_guard not found in information_schema.routines"
        )

        # Check it is applied as a trigger on at least one table
        cur.execute("""
            SELECT tgname
            FROM pg_trigger
            WHERE tgfoid = (
                SELECT oid FROM pg_proc WHERE proname = 'temporal_scd2_guard'
            )
        """)
        triggers = cur.fetchall()
        assert len(triggers) > 0, (
            "temporal_scd2_guard function exists but is not applied as a trigger on any table"
        )


# ── DLA-007: SCD2 bi-temporal columns on user_embeddings_history ─────────────

@pytest.mark.p0
def test_scd2_bitemporal_columns(db_conn):
    """DLA-007: user_embeddings_history has valid_from, valid_to, knowledge_from, knowledge_to, reason columns."""
    required_columns = {"valid_from", "valid_to", "knowledge_from", "knowledge_to", "reason"}

    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'user_embeddings_history'
              AND table_schema = 'public'
        """)
        actual_columns = {row[0] for row in cur.fetchall()}

    assert actual_columns, "Table user_embeddings_history not found or has no columns"

    missing = required_columns - actual_columns
    assert not missing, (
        f"user_embeddings_history missing bi-temporal columns: {missing}. "
        f"Found columns: {sorted(actual_columns)}"
    )


# ── DLA-008: SCD2 open records (valid_to IS NULL for current version) ────────

@pytest.mark.p0
def test_scd2_open_records(db_conn):
    """DLA-008: For each user, the most recent record has valid_to IS NULL (open-ended = current version)."""
    with db_conn.cursor() as cur:
        # Get users that have history records
        cur.execute("""
            SELECT DISTINCT user_id FROM user_embeddings_history
            WHERE embedding_model = 'v1'
            LIMIT 10
        """)
        user_ids = [row[0] for row in cur.fetchall()]
        assert len(user_ids) > 0, "No records in user_embeddings_history"

        for uid in user_ids:
            cur.execute("""
                SELECT valid_from, valid_to, knowledge_to
                FROM user_embeddings_history
                WHERE user_id = %s AND embedding_model = 'v1'
                ORDER BY valid_from DESC
                LIMIT 1
            """, (uid,))
            row = cur.fetchone()
            assert row is not None, f"No history record found for {uid}"
            valid_to = row[1]
            knowledge_to = row[2]
            assert valid_to is None, (
                f"User {uid}: most recent record has valid_to={valid_to}, expected NULL (open-ended)"
            )
            assert knowledge_to is None, (
                f"User {uid}: most recent record has knowledge_to={knowledge_to}, expected NULL"
            )


# ── DLA-009: Entity materialization — get_entity_summary ─────────────────────

@pytest.mark.p0
def test_entity_materialization_summary(db_conn):
    """DLA-009: get_entity_summary(conn, 'USR-156') returns a non-empty dict."""
    from pipeline.entity_materialize import get_entity_summary
    from pipeline.db_connect import get_connection

    conn = get_connection()
    try:
        result = get_entity_summary(conn, "USR-156")
    finally:
        conn.close()

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert len(result) > 0, "get_entity_summary returned empty dict for USR-156"
    assert result.get("entity_id") == "USR-156", (
        f"entity_id mismatch: {result.get('entity_id')}"
    )
    assert "trajectory" in result, "Missing 'trajectory' key in entity summary"
    assert "recent_events" in result, "Missing 'recent_events' key in entity summary"


# ── DLA-010: Entity materialization — drift heatmap ──────────────────────────

@pytest.mark.p0
def test_entity_materialization_drift_heatmap(db_conn):
    """DLA-010: get_drift_heatmap_data(conn) returns DataFrame with 250 rows."""
    from pipeline.entity_materialize import get_drift_heatmap_data
    from pipeline.db_connect import get_connection
    import pandas as pd

    conn = get_connection()
    try:
        df = get_drift_heatmap_data(conn)
    finally:
        conn.close()

    assert isinstance(df, pd.DataFrame), f"Expected DataFrame, got {type(df)}"
    assert len(df) == 250, (
        f"Drift heatmap has {len(df)} rows, expected 250 (one per user)"
    )
    assert "entity_id" in df.columns, "Missing 'entity_id' column"
    assert "total_drift" in df.columns, "Missing 'total_drift' column"


# ── DLA-011: Streamlit DB functions count ────────────────────────────────────

EXPECTED_STREAMLIT_FUNCTIONS = [
    "db_available",
    "load_dashboard_stats",
    "load_drift_heatmap",
    "load_entity_timeline",
    "load_entity_structure",
    "load_all_user_ids",
    "load_trajectory_events",
    "load_zone_drift_series",
    "load_daily_features_for_entity",
    "load_behavioral_signals_from_db",
]


@pytest.mark.p0
def test_streamlit_db_functions_count():
    """DLA-011: pipeline.streamlit_db has all 10 expected functions and they are callable."""
    import pipeline.streamlit_db as sdb

    for func_name in EXPECTED_STREAMLIT_FUNCTIONS:
        assert hasattr(sdb, func_name), (
            f"pipeline.streamlit_db missing function: {func_name}"
        )
        func = getattr(sdb, func_name)
        assert callable(func), (
            f"pipeline.streamlit_db.{func_name} exists but is not callable"
        )


# ── DLA-012: Streamlit USE_DB pattern ────────────────────────────────────────

@pytest.mark.p0
def test_streamlit_use_db_pattern():
    """DLA-012: streamlit_app.py contains 'USE_DB = db_available()' pattern."""
    app_path = PROJECT_ROOT / "streamlit_app.py"
    assert app_path.exists(), "streamlit_app.py not found at project root"

    content = app_path.read_text(encoding="utf-8")
    assert "USE_DB = db_available()" in content, (
        "streamlit_app.py does not contain 'USE_DB = db_available()'"
    )

    # Also verify the import of db_available
    assert "from pipeline.streamlit_db import" in content, (
        "streamlit_app.py does not import from pipeline.streamlit_db"
    )
    assert "db_available" in content, (
        "streamlit_app.py does not reference db_available"
    )


# ── DLA-013: Daily cadence — consecutive dates are exactly 1 day apart ──────

@pytest.mark.p0
def test_daily_cadence(db_conn):
    """DLA-013: Consecutive dates for USR-001 in daily_features are exactly 1 day apart."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT feature_date
            FROM daily_features
            WHERE user_id = 'USR-001'
            ORDER BY feature_date
        """)
        dates = [row[0] for row in cur.fetchall()]

    assert len(dates) >= 2, (
        f"USR-001 has only {len(dates)} dates in daily_features, need >= 2"
    )

    gaps = []
    for i in range(1, len(dates)):
        delta = (dates[i] - dates[i - 1]).days
        if delta != 1:
            gaps.append((dates[i - 1], dates[i], delta))

    assert len(gaps) == 0, (
        f"Found {len(gaps)} non-daily gaps for USR-001. "
        f"First 5: {gaps[:5]}. Expected all consecutive dates to be exactly 1 day apart."
    )


# ── DLA-014: Pipeline idempotency — no duplicate (user_id, date) ────────────

@pytest.mark.p0
def test_pipeline_idempotency(db_conn):
    """DLA-014: daily_features has exactly 1 row per user per date (no duplicates)."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT user_id, feature_date, count(*)
            FROM daily_features
            GROUP BY user_id, feature_date
            HAVING count(*) > 1
        """)
        duplicates = cur.fetchall()

    assert len(duplicates) == 0, (
        f"Found {len(duplicates)} duplicate (user_id, feature_date) pairs in daily_features. "
        f"First 5: {duplicates[:5]}"
    )


# ── DLA-015: DB host is 127.0.0.1 not localhost ─────────────────────────────

@pytest.mark.p0
def test_db_host_is_ip_not_localhost():
    """DLA-015: pipeline/db_connect.py uses '127.0.0.1' as default host, not 'localhost'."""
    db_connect_path = PROJECT_ROOT / "pipeline" / "db_connect.py"
    assert db_connect_path.exists(), "pipeline/db_connect.py not found"

    content = db_connect_path.read_text(encoding="utf-8")

    # Find the default host value in the get_connection function
    assert '"127.0.0.1"' in content, (
        "pipeline/db_connect.py does not contain '127.0.0.1' as default host"
    )

    # Verify 'localhost' is NOT used as a default host value
    # Look specifically for host= assignment with localhost
    localhost_pattern = re.compile(r'host\s*=.*["\']localhost["\']')
    match = localhost_pattern.search(content)
    assert match is None, (
        f"pipeline/db_connect.py uses 'localhost' as host default: {match.group()}"
    )
