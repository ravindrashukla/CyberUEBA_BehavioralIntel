"""Data Engineering Agent Tests — Entity Generation, Config Validation, Attack Scenarios,
and Bronze/Silver/Gold/Trajectory/SCD2 pipeline validation against live DB.

Test IDs: DE-001 through DE-020  — Entity generation & config (offline)
Test IDs: DE-021 through DE-032  — Pipeline data engineering (requires DB at 127.0.0.1:5437)
"""

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import pandas as pd

from simulator.config import (
    SIM_START,
    SIM_END,
    SIM_DAYS,
    N_USERS,
    N_DEVICES,
    N_SEGMENTS,
    N_APPLICATIONS,
    DEPARTMENTS,
    ROLES,
    ATTACK_SCENARIOS,
)
from simulator.entities import (
    generate_users,
    generate_network_segments,
    generate_devices,
    generate_applications,
    generate_all,
)


# ── DE-001 through DE-003: User generation ────────────────────────────────────

@pytest.mark.p0
def test_generate_users_count():
    """DE-001: generate_users returns exactly N_USERS (500) rows."""
    users = generate_users()
    assert len(users) == N_USERS


@pytest.mark.p0
def test_generate_users_id_format():
    """DE-002: All user IDs match the pattern USR-NNN."""
    users = generate_users()
    pattern = re.compile(r"^USR-\d{3}$")
    for uid in users["user_id"]:
        assert pattern.match(uid), f"user_id '{uid}' does not match ^USR-\\d{{3}}$"


@pytest.mark.p1
def test_generate_users_type_distribution():
    """DE-003: User type distribution is ~80% employee, ~15% contractor (+-5%)."""
    users = generate_users()
    total = len(users)
    employee_pct = (users["user_type"] == "employee").sum() / total * 100
    contractor_pct = (users["user_type"] == "contractor").sum() / total * 100
    assert 75 <= employee_pct <= 85, f"employee % = {employee_pct:.1f}, expected 75-85"
    assert 10 <= contractor_pct <= 20, f"contractor % = {contractor_pct:.1f}, expected 10-20"


# ── DE-004 through DE-006: Device generation ──────────────────────────────────

@pytest.mark.p0
def test_generate_devices_count():
    """DE-004: generate_devices returns exactly N_DEVICES (800) rows."""
    users = generate_users()
    segments = generate_network_segments()
    devices = generate_devices(users, segments)
    assert len(devices) == N_DEVICES


@pytest.mark.p0
def test_generate_devices_id_format():
    """DE-005: All device IDs match the pattern DEV-NNN."""
    users = generate_users()
    segments = generate_network_segments()
    devices = generate_devices(users, segments)
    pattern = re.compile(r"^DEV-\d{3}$")
    for did in devices["device_id"]:
        assert pattern.match(did), f"device_id '{did}' does not match ^DEV-\\d{{3}}$"


@pytest.mark.p0
def test_generate_devices_ip_uniqueness():
    """DE-006: All device IP addresses are unique."""
    users = generate_users()
    segments = generate_network_segments()
    devices = generate_devices(users, segments)
    ips = devices["ip_address"]
    assert ips.nunique() == len(ips), "Duplicate IP addresses found among devices"


# ── DE-007 through DE-008: Segments and Applications ──────────────────────────

@pytest.mark.p0
def test_generate_segments_count():
    """DE-007: generate_network_segments returns exactly N_SEGMENTS (25) rows."""
    segments = generate_network_segments()
    assert len(segments) == N_SEGMENTS


@pytest.mark.p0
def test_generate_applications_count():
    """DE-008: generate_applications returns exactly N_APPLICATIONS (60) rows."""
    segments = generate_network_segments()
    apps = generate_applications(segments)
    assert len(apps) == N_APPLICATIONS


# ── DE-009 through DE-011: generate_all integration ───────────────────────────

@pytest.mark.p0
def test_generate_all_returns_all_types():
    """DE-009: generate_all returns dict with keys users, devices, segments, applications."""
    data = generate_all()
    expected_keys = {"users", "devices", "segments", "applications"}
    assert set(data.keys()) == expected_keys


@pytest.mark.p1
def test_users_have_primary_device():
    """DE-010: After generate_all, no user has NaN for primary_device_id."""
    data = generate_all()
    users = data["users"]
    assert "primary_device_id" in users.columns, "primary_device_id column missing"
    assert users["primary_device_id"].notna().all(), "Some users have NaN primary_device_id"


@pytest.mark.p1
def test_users_have_subnet():
    """DE-011: After generate_all, no user has NaN for subnet."""
    data = generate_all()
    users = data["users"]
    assert "subnet" in users.columns, "subnet column missing"
    assert users["subnet"].notna().all(), "Some users have NaN subnet"


# ── DE-012 through DE-014: Config constants ───────────────────────────────────

@pytest.mark.p0
def test_config_sim_days_correct():
    """DE-012: SIM_DAYS equals (SIM_END - SIM_START).days."""
    assert SIM_DAYS == (SIM_END - SIM_START).days


@pytest.mark.p1
def test_config_departments_count():
    """DE-013: DEPARTMENTS list has exactly 15 entries."""
    assert len(DEPARTMENTS) == 15


@pytest.mark.p1
def test_config_roles_count():
    """DE-014: ROLES list has exactly 31 entries (note: N_ROLES is 30)."""
    assert len(ROLES) == 31


# ── DE-015 through DE-016: Attack scenarios config ────────────────────────────

@pytest.mark.p0
def test_attack_scenarios_count():
    """DE-015: ATTACK_SCENARIOS has exactly 8 entries."""
    assert len(ATTACK_SCENARIOS) == 8


@pytest.mark.p1
def test_attack_scenarios_unique_ids():
    """DE-016: All attack scenario IDs are unique."""
    ids = [s["id"] for s in ATTACK_SCENARIOS]
    assert len(ids) == len(set(ids)), f"Duplicate attack IDs found: {ids}"


# ── DE-017 through DE-019: Specific attack scenario validation ────────────────

@pytest.mark.p0
def test_brute_force_active_on_date():
    """DE-017: ATK-001 start date is date(2026, 3, 15)."""
    atk001 = next(s for s in ATTACK_SCENARIOS if s["id"] == "ATK-001")
    assert atk001["start"] == date(2026, 3, 15), (
        f"ATK-001 start is {atk001['start']}, expected 2026-03-15"
    )


@pytest.mark.p0
def test_brute_force_injects_auth():
    """DE-018: ATK-001 has type 'brute_force' and target_users 50."""
    atk001 = next(s for s in ATTACK_SCENARIOS if s["id"] == "ATK-001")
    assert atk001["type"] == "brute_force", f"ATK-001 type is '{atk001['type']}'"
    assert atk001["target_users"] == 50, f"ATK-001 target_users is {atk001['target_users']}"


@pytest.mark.p0
def test_credential_theft_5_day_campaign():
    """DE-019: ATK-002 has duration_days 5 and start date(2026, 2, 1)."""
    atk002 = next(s for s in ATTACK_SCENARIOS if s["id"] == "ATK-002")
    assert atk002["start"] == date(2026, 2, 1), (
        f"ATK-002 start is {atk002['start']}, expected 2026-02-01"
    )
    assert atk002["duration_days"] == 5, (
        f"ATK-002 duration_days is {atk002['duration_days']}, expected 5"
    )


# ── DE-020: Reproducibility ──────────────────────────────────────────────────

@pytest.mark.p0
def test_entity_generation_reproducible():
    """DE-020: Two calls to generate_users produce identical DataFrames (seeded RNG)."""
    df1 = generate_users()
    df2 = generate_users()
    pd.testing.assert_frame_equal(df1, df2)


# ═══════════════════════════════════════════════════════════════════════════════
# DE-021 through DE-032: Pipeline Data Engineering Tests (DB-backed)
#
# These tests validate the Bronze->Silver->Gold->Trajectory->SCD2 pipeline
# against the live PostgreSQL database at 127.0.0.1:5437.
# ═══════════════════════════════════════════════════════════════════════════════

os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5437")

DATA_DIR = Path(os.getenv("DATA_DIR", "data/generated"))
LOG_TYPES = ["auth", "network", "dns", "endpoint", "file_access", "app", "privilege"]
EXPECTED_USERS = 250
EXPECTED_DAYS = 130
EXPECTED_ZONE_KEYS = {"identity", "access_pattern", "data_behavior",
                      "network_footprint", "risk_posture"}
EXPECTED_CONTEXT_KEYS = {"normal_ops", "insider_investigation", "apt_hunt",
                         "privilege_audit"}


def _get_db_connection():
    """Get a psycopg2 connection to the pipeline DB."""
    import psycopg2
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "5437")),
        dbname=os.environ.get("DB_NAME", "cyber_ueba"),
        user=os.environ.get("DB_USER", "cyber_ueba"),
        password=os.environ.get("DB_PASSWORD", "password"),
    )


@pytest.fixture
def db_conn():
    """Per-test DB connection for pipeline tests. Autocommit to avoid
    transaction-abort cascades between tests."""
    conn = _get_db_connection()
    conn.autocommit = True
    yield conn
    conn.close()


# ── DE-021: Bronze layer completeness ────────────────────────────────────────

@pytest.mark.p0
def test_bronze_layer_completeness():
    """DE-021: CSV files exist for all 7 log types with at least 10 dates each."""
    for log_type in LOG_TYPES:
        type_dir = DATA_DIR / log_type
        assert type_dir.exists(), f"Missing Bronze directory: {type_dir}"
        csv_files = sorted(type_dir.glob("*.csv"))
        assert len(csv_files) >= 10, (
            f"{log_type}: only {len(csv_files)} CSV files found, need >= 10"
        )
        # Verify files are parseable date-named
        for f in csv_files[:3]:
            try:
                date.fromisoformat(f.stem)
            except ValueError:
                pytest.fail(f"{log_type}: file '{f.name}' is not a valid date name")


# ── DE-022: Silver layer data lineage ────────────────────────────────────────

@pytest.mark.p0
def test_silver_layer_data_lineage(db_conn):
    """DE-022: For 3 users+dates, manually compute auth_total and auth_fail_rate
    from raw CSV and compare against daily_features table values."""
    cur = db_conn.cursor()
    # Pick 3 random user+date combos that have nonzero auth_total
    cur.execute("""
        SELECT user_id, feature_date, auth_total, auth_fail_rate
        FROM daily_features
        WHERE auth_total > 0
        ORDER BY random()
        LIMIT 3
    """)
    samples = cur.fetchall()
    assert len(samples) == 3, "Could not find 3 rows with auth_total > 0"

    for user_id, feature_date, db_auth_total, db_auth_fail_rate in samples:
        day_str = feature_date.isoformat()
        csv_path = DATA_DIR / "auth" / f"{day_str}.csv"
        assert csv_path.exists(), f"Auth CSV missing for {day_str}"

        df = pd.read_csv(csv_path, dtype=str)
        user_rows = df[df["user_id"] == user_id]

        expected_total = len(user_rows)
        success_count = (user_rows["success"].str.lower() == "true").sum()
        expected_fail_rate = (
            float((expected_total - success_count) / expected_total)
            if expected_total > 0 else 0.0
        )

        assert db_auth_total == expected_total, (
            f"{user_id}@{day_str}: auth_total DB={db_auth_total} vs CSV={expected_total}"
        )
        assert abs(db_auth_fail_rate - expected_fail_rate) < 0.001, (
            f"{user_id}@{day_str}: auth_fail_rate DB={db_auth_fail_rate:.4f} "
            f"vs CSV={expected_fail_rate:.4f}"
        )


# ── DE-023: Gold layer vector integrity ──────────────────────────────────────

@pytest.mark.p0
def test_gold_layer_vector_integrity(db_conn):
    """DE-023: 5 random behavioral_snapshots have all zone/composite vectors at 1536-d
    and zone_texts JSONB has all 5 zone keys."""
    cur = db_conn.cursor()
    cur.execute("""
        SELECT zone_identity, zone_access_pattern, zone_data_behavior,
               zone_network_footprint, zone_risk_posture,
               composite, composite_normal_ops, composite_insider_inv,
               composite_apt_hunt, composite_privilege_audit,
               zone_texts
        FROM behavioral_snapshots
        ORDER BY random()
        LIMIT 5
    """)
    rows = cur.fetchall()
    assert len(rows) == 5, "Could not fetch 5 behavioral_snapshots"

    zone_col_names = [
        "zone_identity", "zone_access_pattern", "zone_data_behavior",
        "zone_network_footprint", "zone_risk_posture",
    ]
    composite_col_names = [
        "composite", "composite_normal_ops", "composite_insider_inv",
        "composite_apt_hunt", "composite_privilege_audit",
    ]

    for i, row in enumerate(rows):
        # Check 5 zone vectors (indices 0-4)
        for j, col_name in enumerate(zone_col_names):
            vec = row[j]
            assert vec is not None, f"Row {i}: {col_name} is NULL"
            vec_str = str(vec).strip("[]")
            dims = len(vec_str.split(","))
            assert dims == 1536, (
                f"Row {i}: {col_name} has {dims} dims, expected 1536"
            )

        # Check 5 composite vectors (indices 5-9)
        for j, col_name in enumerate(composite_col_names):
            vec = row[5 + j]
            assert vec is not None, f"Row {i}: {col_name} is NULL"
            vec_str = str(vec).strip("[]")
            dims = len(vec_str.split(","))
            assert dims == 1536, (
                f"Row {i}: {col_name} has {dims} dims, expected 1536"
            )

        # Check zone_texts JSONB (index 10)
        zt = row[10]
        if isinstance(zt, str):
            zt = json.loads(zt)
        assert isinstance(zt, dict), f"Row {i}: zone_texts is not a dict"
        assert set(zt.keys()) == EXPECTED_ZONE_KEYS, (
            f"Row {i}: zone_texts keys {set(zt.keys())} != {EXPECTED_ZONE_KEYS}"
        )


# ── DE-024: Trajectory computation correctness ──────────────────────────────

@pytest.mark.p0
def test_trajectory_computation_correctness(db_conn):
    """DE-024: For a user, manually compute cosine distance between first and last
    composite, compare against total_drift in trajectory_snapshots."""
    cur = db_conn.cursor()

    # Pick a user with nonzero total_drift
    cur.execute("""
        SELECT entity_id, cutoff_date, total_drift
        FROM trajectory_snapshots
        WHERE total_drift > 0.001
        ORDER BY random()
        LIMIT 1
    """)
    row = cur.fetchone()
    assert row is not None, "No trajectory_snapshot with nonzero total_drift"
    user_id, cutoff_date, db_total_drift = row

    # Fetch the behavioral snapshot window this trajectory was built from
    cur.execute("""
        SELECT cutoff_date, composite
        FROM behavioral_snapshots
        WHERE entity_type = 'user' AND entity_id = %s
          AND cutoff_date <= %s
          AND cutoff_date > %s::date - 30
        ORDER BY cutoff_date
    """, (user_id, cutoff_date, cutoff_date))
    snap_rows = cur.fetchall()
    assert len(snap_rows) >= 2, (
        f"User {user_id}@{cutoff_date}: only {len(snap_rows)} snapshots in window"
    )

    def _parse_vec(v):
        s = str(v).strip()
        if s.startswith("[") and s.endswith("]"):
            return np.array([float(x) for x in s[1:-1].split(",")], dtype=np.float64)
        return None

    first_vec = _parse_vec(snap_rows[0][1])
    last_vec = _parse_vec(snap_rows[-1][1])
    assert first_vec is not None and last_vec is not None

    # Cosine distance = 1 - cosine_similarity
    dot = np.dot(first_vec, last_vec)
    norm_a = np.linalg.norm(first_vec)
    norm_b = np.linalg.norm(last_vec)
    cos_sim = dot / (norm_a * norm_b) if (norm_a > 0 and norm_b > 0) else 1.0
    manual_drift = 1.0 - cos_sim

    # Allow tolerance -- pipeline may use float32 while we compute float64
    assert abs(db_total_drift - manual_drift) < 0.01, (
        f"User {user_id}@{cutoff_date}: total_drift DB={db_total_drift:.6f} "
        f"vs manual={manual_drift:.6f}"
    )


# ── DE-025: SCD2 bi-temporal correctness ─────────────────────────────────────

@pytest.mark.p0
def test_scd2_bitemporal_correctness(db_conn):
    """DE-025: For 3 users, verify no overlapping valid_from/valid_to periods,
    knowledge_from always set, most recent record valid constraints."""
    cur = db_conn.cursor()

    # Pick 3 random users
    cur.execute("""
        SELECT user_id FROM (
            SELECT DISTINCT user_id FROM user_embeddings_history
        ) sub ORDER BY random() LIMIT 3
    """)
    user_ids = [r[0] for r in cur.fetchall()]
    assert len(user_ids) == 3, "Could not find 3 users in embedding history"

    for uid in user_ids:
        cur.execute("""
            SELECT history_id, valid_from, valid_to, knowledge_from, knowledge_to
            FROM user_embeddings_history
            WHERE user_id = %s AND embedding_model = 'v1'
            ORDER BY valid_from, knowledge_from
        """, (uid,))
        records = cur.fetchall()
        assert len(records) > 0, f"No history records for {uid}"

        # (a) No overlapping valid_from/valid_to periods within same knowledge lineage
        # Check that closed records don't overlap: for any two with non-null valid_to,
        # one should end before the other starts
        closed = [(r[1], r[2]) for r in records if r[2] is not None]
        for i in range(len(closed)):
            for j in range(i + 1, len(closed)):
                a_from, a_to = closed[i]
                b_from, b_to = closed[j]
                # They overlap if a_from < b_to AND b_from < a_to
                if a_from == b_from:
                    continue  # Same valid_from can exist (superseded + new)
                if a_from < b_to and b_from < a_to:
                    pytest.fail(
                        f"{uid}: overlapping periods [{a_from},{a_to}) "
                        f"and [{b_from},{b_to})"
                    )

        # (b) knowledge_from is always set
        for r in records:
            assert r[3] is not None, (
                f"{uid}: history_id={r[0]} has NULL knowledge_from"
            )

        # (c) Most recent open record: valid_to IS NULL or valid_to >= valid_from
        open_records = [r for r in records if r[2] is None and r[4] is None]
        if open_records:
            latest = open_records[-1]
            # valid_to is NULL (open) -- that's valid
            assert latest[2] is None, (
                f"{uid}: latest record has valid_to={latest[2]}, expected NULL"
            )
        # Also check: no record has valid_to < valid_from
        for r in records:
            if r[2] is not None:
                assert r[2] >= r[1], (
                    f"{uid}: history_id={r[0]} has valid_to={r[2]} < "
                    f"valid_from={r[1]}"
                )


# ── DE-026: Pipeline idempotency (row counts) ───────────────────────────────

@pytest.mark.p0
def test_pipeline_idempotency_row_counts(db_conn):
    """DE-026: Verify row counts match expected pipeline output."""
    cur = db_conn.cursor()

    cur.execute("SELECT COUNT(*) FROM daily_features")
    df_count = cur.fetchone()[0]
    assert df_count == 32500, f"daily_features: {df_count} rows, expected 32500"

    cur.execute("SELECT COUNT(*) FROM behavioral_snapshots")
    bs_count = cur.fetchone()[0]
    assert bs_count == 32500, f"behavioral_snapshots: {bs_count} rows, expected 32500"

    cur.execute("SELECT COUNT(*) FROM trajectory_snapshots")
    ts_count = cur.fetchone()[0]
    assert ts_count == 32250, f"trajectory_snapshots: {ts_count} rows, expected 32250"

    cur.execute("SELECT COUNT(*) FROM trajectory_events")
    te_count = cur.fetchone()[0]
    assert te_count == 32250, f"trajectory_events: {te_count} rows, expected 32250"

    cur.execute("SELECT COUNT(*) FROM user_embeddings_history")
    eh_count = cur.fetchone()[0]
    assert eh_count >= 32500, (
        f"user_embeddings_history: {eh_count} rows, expected >= 32500"
    )


# ── DE-027: Foreign key integrity ────────────────────────────────────────────

@pytest.mark.p0
def test_foreign_key_integrity(db_conn):
    """DE-027: Every entity_id in trajectory tables exists in behavioral_snapshots,
    every user_id in history exists in daily_features."""
    cur = db_conn.cursor()

    # trajectory_snapshots entity_ids subset of behavioral_snapshots
    cur.execute("""
        SELECT COUNT(DISTINCT ts.entity_id)
        FROM trajectory_snapshots ts
        LEFT JOIN (
            SELECT DISTINCT entity_id FROM behavioral_snapshots
        ) bs ON ts.entity_id = bs.entity_id
        WHERE bs.entity_id IS NULL
    """)
    orphans = cur.fetchone()[0]
    assert orphans == 0, (
        f"{orphans} trajectory_snapshot entity_ids not in behavioral_snapshots"
    )

    # trajectory_events entity_ids subset of behavioral_snapshots
    cur.execute("""
        SELECT COUNT(DISTINCT te.entity_id)
        FROM trajectory_events te
        LEFT JOIN (
            SELECT DISTINCT entity_id FROM behavioral_snapshots
        ) bs ON te.entity_id = bs.entity_id
        WHERE bs.entity_id IS NULL
    """)
    orphans = cur.fetchone()[0]
    assert orphans == 0, (
        f"{orphans} trajectory_event entity_ids not in behavioral_snapshots"
    )

    # user_embeddings_history user_ids subset of daily_features user_ids
    cur.execute("""
        SELECT COUNT(DISTINCT h.user_id)
        FROM user_embeddings_history h
        LEFT JOIN (
            SELECT DISTINCT user_id FROM daily_features
        ) df ON h.user_id = df.user_id
        WHERE df.user_id IS NULL
    """)
    orphans = cur.fetchone()[0]
    assert orphans == 0, (
        f"{orphans} history user_ids not in daily_features"
    )


# ── DE-028: Date coverage ────────────────────────────────────────────────────

@pytest.mark.p0
def test_date_coverage(db_conn):
    """DE-028: Every user has exactly 130 days in daily_features,
    behavioral_snapshots dates match daily_features dates."""
    cur = db_conn.cursor()

    # Each user should have exactly EXPECTED_DAYS rows
    cur.execute("""
        SELECT user_id, COUNT(*) AS cnt
        FROM daily_features
        GROUP BY user_id
        HAVING COUNT(*) != %s
    """, (EXPECTED_DAYS,))
    mismatches = cur.fetchall()
    assert len(mismatches) == 0, (
        f"{len(mismatches)} users have != {EXPECTED_DAYS} days in daily_features. "
        f"First few: {mismatches[:5]}"
    )

    # behavioral_snapshots dates should match daily_features dates
    cur.execute("""
        SELECT df_dates.feature_date
        FROM (SELECT DISTINCT feature_date FROM daily_features) df_dates
        LEFT JOIN (SELECT DISTINCT cutoff_date FROM behavioral_snapshots) bs_dates
            ON df_dates.feature_date = bs_dates.cutoff_date
        WHERE bs_dates.cutoff_date IS NULL
    """)
    missing = cur.fetchall()
    assert len(missing) == 0, (
        f"{len(missing)} daily_features dates missing from behavioral_snapshots: "
        f"{[str(m[0]) for m in missing[:5]]}"
    )


# ── DE-029: JSONB structure validation ───────────────────────────────────────

@pytest.mark.p0
def test_jsonb_structure_validation(db_conn):
    """DE-029: trajectory_snapshots zone_drifts has 5 zone keys,
    context_drifts has 4 context keys."""
    cur = db_conn.cursor()

    cur.execute("""
        SELECT zone_drifts, context_drifts
        FROM trajectory_snapshots
        WHERE zone_drifts IS NOT NULL AND context_drifts IS NOT NULL
        ORDER BY random()
        LIMIT 10
    """)
    rows = cur.fetchall()
    assert len(rows) > 0, "No trajectory_snapshots with non-null JSONB found"

    for i, (zd, cd) in enumerate(rows):
        if isinstance(zd, str):
            zd = json.loads(zd)
        if isinstance(cd, str):
            cd = json.loads(cd)

        assert isinstance(zd, dict), f"Row {i}: zone_drifts is not a dict"
        assert set(zd.keys()) == EXPECTED_ZONE_KEYS, (
            f"Row {i}: zone_drifts keys {set(zd.keys())} != {EXPECTED_ZONE_KEYS}"
        )

        assert isinstance(cd, dict), f"Row {i}: context_drifts is not a dict"
        assert set(cd.keys()) == EXPECTED_CONTEXT_KEYS, (
            f"Row {i}: context_drifts keys {set(cd.keys())} != {EXPECTED_CONTEXT_KEYS}"
        )


# ── DE-030: Null safety ─────────────────────────────────────────────────────

@pytest.mark.p0
def test_null_safety(db_conn):
    """DE-030: No nulls in primary columns across all pipeline tables."""
    cur = db_conn.cursor()

    # daily_features: user_id, feature_date
    cur.execute("""
        SELECT COUNT(*) FROM daily_features
        WHERE user_id IS NULL OR feature_date IS NULL
    """)
    assert cur.fetchone()[0] == 0, "NULLs found in daily_features primary columns"

    # behavioral_snapshots: entity_id, entity_type, cutoff_date
    cur.execute("""
        SELECT COUNT(*) FROM behavioral_snapshots
        WHERE entity_id IS NULL OR entity_type IS NULL OR cutoff_date IS NULL
    """)
    assert cur.fetchone()[0] == 0, "NULLs found in behavioral_snapshots primary columns"

    # trajectory_snapshots: entity_id, entity_type, cutoff_date
    cur.execute("""
        SELECT COUNT(*) FROM trajectory_snapshots
        WHERE entity_id IS NULL OR entity_type IS NULL OR cutoff_date IS NULL
    """)
    assert cur.fetchone()[0] == 0, "NULLs found in trajectory_snapshots primary columns"

    # trajectory_events: entity_id, entity_type
    cur.execute("""
        SELECT COUNT(*) FROM trajectory_events
        WHERE entity_id IS NULL OR entity_type IS NULL
    """)
    assert cur.fetchone()[0] == 0, "NULLs found in trajectory_events primary columns"

    # user_embeddings_history: user_id
    cur.execute("""
        SELECT COUNT(*) FROM user_embeddings_history
        WHERE user_id IS NULL
    """)
    assert cur.fetchone()[0] == 0, "NULLs found in user_embeddings_history.user_id"


# ── DE-031: Index performance ────────────────────────────────────────────────

@pytest.mark.p0
def test_index_performance(db_conn):
    """DE-031: Key indexes exist on entity_type+entity_id+cutoff_date columns."""
    cur = db_conn.cursor()

    expected_indexes = {
        # table: [index_name, ...]
        "behavioral_snapshots": [
            "idx_beh_snap_entity_date",
            "idx_beh_snap_date",
            "beh_snap_uq",
        ],
        "trajectory_snapshots": [
            "idx_traj_snap_entity_date",
            "idx_traj_snap_date",
            "traj_snap_uq",
        ],
        "daily_features": [
            "idx_daily_features_user_date",
            "idx_daily_features_date",
            "daily_features_uq",
        ],
        "user_embeddings_history": [
            "user_emb_history_valid_ix",
            "user_emb_history_knowledge_ix",
            "user_emb_history_current_uq",
        ],
        "trajectory_events": [
            "idx_traj_event_entity_date",
            "idx_traj_event_type_date",
            "idx_traj_event_severity",
        ],
    }

    cur.execute("""
        SELECT tablename, indexname
        FROM pg_indexes
        WHERE schemaname = 'public'
    """)
    actual_indexes = {}
    for tablename, indexname in cur.fetchall():
        actual_indexes.setdefault(tablename, set()).add(indexname)

    for table, required in expected_indexes.items():
        assert table in actual_indexes, f"Table '{table}' has no indexes"
        for idx_name in required:
            assert idx_name in actual_indexes[table], (
                f"Missing index '{idx_name}' on table '{table}'. "
                f"Found: {sorted(actual_indexes[table])}"
            )


# ── DE-032: Data freshness ──────────────────────────────────────────────────

@pytest.mark.p1
def test_data_freshness(db_conn):
    """DE-032: computed_at timestamps should be within last 7 days."""
    cur = db_conn.cursor()

    tables_with_computed_at = [
        ("daily_features", "computed_at"),
        ("behavioral_snapshots", "computed_at"),
        ("trajectory_snapshots", "computed_at"),
    ]

    for table, col in tables_with_computed_at:
        cur.execute(f"SELECT MAX({col}) FROM {table}")
        max_ts = cur.fetchone()[0]
        assert max_ts is not None, f"{table}: no {col} values found"

        # Ensure max timestamp is timezone-aware for comparison
        now = datetime.now(timezone.utc)
        if max_ts.tzinfo is None:
            from datetime import timezone as tz
            max_ts = max_ts.replace(tzinfo=tz.utc)

        age_days = (now - max_ts).total_seconds() / 86400
        assert age_days <= 7.0, (
            f"{table}: newest {col} is {age_days:.1f} days old "
            f"(max_ts={max_ts}), expected <= 7 days"
        )
