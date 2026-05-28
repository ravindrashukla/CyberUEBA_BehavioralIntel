"""Verify ACECARD design commitments against the actual system.

Tests cover all 6 architecture layers (Bronze, Silver, Gold, Trajectory,
History, Entity) and validate the design specification's exact numbers:
250 users, 130 days, 4 attack users, 7 log types, 23+ features, 5 zones,
4 composites, bi-temporal SCD2 columns, and correct row counts.

Requires a running PostgreSQL at 127.0.0.1:5437 with populated tables.
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from dataclasses import fields

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5437")

import psycopg2

DATA_DIR = Path(os.getenv("DATA_DIR", "data/generated"))
ATTACK_USERS = ["USR-156", "USR-234", "USR-042", "USR-118"]
EXPECTED_USERS = 250
EXPECTED_DAYS = 130
EXPECTED_DEVICES = 300
EXPECTED_SEGMENTS = 25
EXPECTED_APPS = 60
MIN_DATE = date(2025, 1, 1)
MAX_DATE = date(2025, 5, 10)

LOG_TYPES = ["auth", "network", "dns", "endpoint", "file_access", "app", "privilege"]

ZONE_COLUMNS = [
    "zone_identity",
    "zone_access_pattern",
    "zone_data_behavior",
    "zone_network_footprint",
    "zone_risk_posture",
]

COMPOSITE_COLUMNS = [
    "composite_normal_ops",
    "composite_insider_inv",
    "composite_apt_hunt",
    "composite_privilege_audit",
]

ZONE_TEXT_KEYS = {"identity", "access_pattern", "data_behavior", "network_footprint", "risk_posture"}

TRAJECTORY_SCALAR_FEATURES = [
    "velocity_magnitude", "acceleration", "stability",
    "regime_shifts", "trend_consistency", "total_drift",
]

VALID_REGIMES = {"stable", "drifting", "regime_shift", "accelerating"}


@pytest.fixture(scope="module")
def conn():
    """Autocommit connection to cyber_ueba database."""
    c = psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "5437")),
        dbname=os.getenv("DB_NAME", "cyber_ueba"),
        user=os.getenv("DB_USER", "cyber_ueba"),
        password=os.getenv("DB_PASSWORD", "password"),
    )
    c.autocommit = True
    yield c
    c.close()


# ---------------------------------------------------------------------------
# 1. DAILY not weekly — daily_features consecutive dates are 1 day apart
# ---------------------------------------------------------------------------
class TestDailyNotWeekly:
    def test_consecutive_dates_one_day_apart(self, conn):
        """Consecutive feature_dates for a given user must be 1 day apart."""
        with conn.cursor() as cur:
            cur.execute("""
                SELECT feature_date
                FROM daily_features
                WHERE user_id = (SELECT user_id FROM daily_features LIMIT 1)
                ORDER BY feature_date
            """)
            dates = [row[0] for row in cur.fetchall()]
        assert len(dates) >= 2, "Need at least 2 dates to check interval"
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        assert all(g == 1 for g in gaps), (
            f"Expected all gaps = 1 day, got unique gaps: {sorted(set(gaps))}"
        )

    def test_distinct_dates_per_user_is_130(self, conn):
        """Each user should have exactly 130 distinct dates."""
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, COUNT(DISTINCT feature_date) AS cnt
                FROM daily_features
                GROUP BY user_id
            """)
            rows = cur.fetchall()
        assert len(rows) > 0, "No users found in daily_features"
        for uid, cnt in rows:
            assert cnt == EXPECTED_DAYS, (
                f"User {uid} has {cnt} dates, expected {EXPECTED_DAYS}"
            )


# ---------------------------------------------------------------------------
# 2. 250 users — every table has exactly 250 distinct users
# ---------------------------------------------------------------------------
class TestUserCount:
    @pytest.mark.parametrize("table,col", [
        ("daily_features", "user_id"),
        ("behavioral_snapshots", "entity_id"),
        ("trajectory_snapshots", "entity_id"),
        ("user_embeddings_history", "user_id"),
    ])
    def test_250_distinct_users(self, conn, table, col):
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(DISTINCT {col}) FROM {table}")
            count = cur.fetchone()[0]
        assert count == EXPECTED_USERS, (
            f"{table} has {count} distinct users, expected {EXPECTED_USERS}"
        )

    def test_trajectory_events_250_users(self, conn):
        """trajectory_events may have fewer users if not all had events.
        We check it has at least the 4 attack users."""
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(DISTINCT entity_id) FROM trajectory_events")
            count = cur.fetchone()[0]
        assert count >= 4, (
            f"trajectory_events has {count} distinct users, expected >= 4 attack users"
        )


# ---------------------------------------------------------------------------
# 3. 4 attack users exist in all tables
# ---------------------------------------------------------------------------
class TestAttackUsersPresent:
    @pytest.mark.parametrize("table,col", [
        ("daily_features", "user_id"),
        ("behavioral_snapshots", "entity_id"),
        ("trajectory_snapshots", "entity_id"),
        ("user_embeddings_history", "user_id"),
    ])
    def test_attack_users_in_table(self, conn, table, col):
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(ATTACK_USERS))
            cur.execute(
                f"SELECT DISTINCT {col} FROM {table} WHERE {col} IN ({placeholders})",
                ATTACK_USERS,
            )
            found = {row[0] for row in cur.fetchall()}
        missing = set(ATTACK_USERS) - found
        assert not missing, f"Attack users missing from {table}: {missing}"

    def test_attack_users_in_trajectory_events(self, conn):
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(ATTACK_USERS))
            cur.execute(
                f"SELECT DISTINCT entity_id FROM trajectory_events WHERE entity_id IN ({placeholders})",
                ATTACK_USERS,
            )
            found = {row[0] for row in cur.fetchall()}
        missing = set(ATTACK_USERS) - found
        assert not missing, f"Attack users missing from trajectory_events: {missing}"


# ---------------------------------------------------------------------------
# 4. Bronze layer: 7 log type directories with ~130 CSVs each
# ---------------------------------------------------------------------------
class TestBronzeLogTypes:
    @pytest.mark.parametrize("log_type", LOG_TYPES)
    def test_log_directory_exists(self, log_type):
        d = DATA_DIR / log_type
        assert d.is_dir(), f"Bronze log directory missing: {d}"

    @pytest.mark.parametrize("log_type", LOG_TYPES)
    def test_log_csv_count_approximately_130(self, log_type):
        d = DATA_DIR / log_type
        csvs = list(d.glob("*.csv"))
        assert len(csvs) >= 125 and len(csvs) <= 135, (
            f"{log_type}/ has {len(csvs)} CSVs, expected ~130"
        )


# ---------------------------------------------------------------------------
# 5. Bronze: entity files — users 250, devices 300, segments 25, apps 60
# ---------------------------------------------------------------------------
class TestBronzeEntities:
    def test_users_csv_250_rows(self):
        import pandas as pd
        path = DATA_DIR / "entities" / "users.csv"
        assert path.exists(), f"Missing {path}"
        df = pd.read_csv(path)
        assert len(df) == EXPECTED_USERS, f"users.csv has {len(df)} rows, expected {EXPECTED_USERS}"

    def test_devices_csv_300_rows(self):
        import pandas as pd
        path = DATA_DIR / "entities" / "devices.csv"
        assert path.exists(), f"Missing {path}"
        df = pd.read_csv(path)
        assert len(df) == EXPECTED_DEVICES, f"devices.csv has {len(df)} rows, expected {EXPECTED_DEVICES}"

    def test_segments_csv_25_rows(self):
        import pandas as pd
        path = DATA_DIR / "entities" / "segments.csv"
        assert path.exists(), f"Missing {path}"
        df = pd.read_csv(path)
        assert len(df) == EXPECTED_SEGMENTS, f"segments.csv has {len(df)} rows, expected {EXPECTED_SEGMENTS}"

    def test_apps_csv_60_rows(self):
        import pandas as pd
        path = DATA_DIR / "entities" / "applications.csv"
        assert path.exists(), f"Missing {path}"
        df = pd.read_csv(path)
        assert len(df) == EXPECTED_APPS, f"applications.csv has {len(df)} rows, expected {EXPECTED_APPS}"


# ---------------------------------------------------------------------------
# 6. Silver layer: 23+ feature columns
# ---------------------------------------------------------------------------
class TestSilverFeatureCount:
    def test_at_least_23_feature_columns(self, conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'daily_features'
                  AND column_name NOT IN ('id', 'user_id', 'feature_date', 'computed_at')
                ORDER BY ordinal_position
            """)
            feature_cols = [row[0] for row in cur.fetchall()]
        assert len(feature_cols) >= 23, (
            f"daily_features has {len(feature_cols)} feature columns, expected >= 23. "
            f"Columns: {feature_cols}"
        )


# ---------------------------------------------------------------------------
# 7. Gold layer: 5 zone embeddings each 1536-d
# ---------------------------------------------------------------------------
class TestGoldZoneEmbeddings:
    @pytest.mark.parametrize("col", ZONE_COLUMNS)
    def test_zone_column_exists_and_1536d(self, conn, col):
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT vector_dims({col})
                FROM behavioral_snapshots
                WHERE {col} IS NOT NULL
                LIMIT 1
            """)
            row = cur.fetchone()
        assert row is not None, f"No non-null rows found for {col}"
        assert row[0] == 1536, f"{col} has dimension {row[0]}, expected 1536"


# ---------------------------------------------------------------------------
# 8. Gold layer: 4 composite embeddings each 1536-d
# ---------------------------------------------------------------------------
class TestGoldCompositeEmbeddings:
    @pytest.mark.parametrize("col", COMPOSITE_COLUMNS)
    def test_composite_column_exists_and_1536d(self, conn, col):
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT vector_dims({col})
                FROM behavioral_snapshots
                WHERE {col} IS NOT NULL
                LIMIT 1
            """)
            row = cur.fetchone()
        assert row is not None, f"No non-null rows found for {col}"
        assert row[0] == 1536, f"{col} has dimension {row[0]}, expected 1536"


# ---------------------------------------------------------------------------
# 9. Gold layer: zone_texts JSONB has all 5 zone keys
# ---------------------------------------------------------------------------
class TestGoldZoneTexts:
    def test_zone_texts_has_5_keys(self, conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT zone_texts
                FROM behavioral_snapshots
                WHERE zone_texts IS NOT NULL
                LIMIT 1
            """)
            row = cur.fetchone()
        assert row is not None, "No behavioral_snapshots with zone_texts"
        import json
        zt = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        found_keys = set(zt.keys())
        assert found_keys == ZONE_TEXT_KEYS, (
            f"zone_texts keys = {found_keys}, expected {ZONE_TEXT_KEYS}"
        )


# ---------------------------------------------------------------------------
# 10. Trajectory layer: daily cadence
# ---------------------------------------------------------------------------
class TestTrajectoryDailyCadence:
    def test_consecutive_dates_one_day_apart(self, conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT cutoff_date
                FROM trajectory_snapshots
                WHERE entity_id = (SELECT entity_id FROM trajectory_snapshots LIMIT 1)
                ORDER BY cutoff_date
            """)
            dates = [row[0] for row in cur.fetchall()]
        assert len(dates) >= 2, "Need at least 2 trajectory dates"
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        assert all(g == 1 for g in gaps), (
            f"Trajectory gaps not all 1 day: unique gaps = {sorted(set(gaps))}"
        )


# ---------------------------------------------------------------------------
# 11. Trajectory: 6 scalar features present
# ---------------------------------------------------------------------------
class TestTrajectoryScalarFeatures:
    @pytest.mark.parametrize("col", TRAJECTORY_SCALAR_FEATURES)
    def test_scalar_column_exists(self, conn, col):
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT {col}
                FROM trajectory_snapshots
                WHERE {col} IS NOT NULL
                LIMIT 1
            """)
            row = cur.fetchone()
        assert row is not None, f"trajectory_snapshots.{col} has no non-null values"


# ---------------------------------------------------------------------------
# 12. Trajectory: 4 regime types
# ---------------------------------------------------------------------------
class TestTrajectoryRegimes:
    def test_current_regime_values_are_valid(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT current_regime FROM trajectory_snapshots")
            regimes = {row[0] for row in cur.fetchall()}
        invalid = regimes - VALID_REGIMES
        assert not invalid, (
            f"Invalid regime values: {invalid}. "
            f"Found: {regimes}, allowed: {VALID_REGIMES}"
        )


# ---------------------------------------------------------------------------
# 13. Trajectory events structure
# ---------------------------------------------------------------------------
class TestTrajectoryEventsStructure:
    @pytest.mark.parametrize("col", [
        "entity_type", "entity_id", "event_date",
        "event_type", "severity", "magnitude",
    ])
    def test_column_exists(self, conn, col):
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'trajectory_events'
                  AND column_name = %s
            """, (col,))
            row = cur.fetchone()
        assert row is not None, f"trajectory_events missing column: {col}"


# ---------------------------------------------------------------------------
# 14. History layer: bi-temporal SCD2 columns
# ---------------------------------------------------------------------------
class TestHistoryBitemporal:
    @pytest.mark.parametrize("col", [
        "valid_from", "valid_to", "knowledge_from", "knowledge_to",
    ])
    def test_scd2_column_exists(self, conn, col):
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'user_embeddings_history'
                  AND column_name = %s
            """, (col,))
            row = cur.fetchone()
        assert row is not None, (
            f"user_embeddings_history missing SCD2 column: {col}"
        )

    def test_valid_to_gte_valid_from_for_closed_records(self, conn):
        """For closed records (valid_to IS NOT NULL), valid_to >= valid_from."""
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM user_embeddings_history
                WHERE valid_to IS NOT NULL AND valid_to < valid_from
            """)
            bad_count = cur.fetchone()[0]
        assert bad_count == 0, (
            f"{bad_count} rows violate valid_to >= valid_from"
        )


# ---------------------------------------------------------------------------
# 15. History: 5 zone + composite vectors
# ---------------------------------------------------------------------------
class TestHistoryVectors:
    @pytest.mark.parametrize("col", ZONE_COLUMNS + ["composite"])
    def test_vector_column_exists_in_history(self, conn, col):
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'user_embeddings_history'
                  AND column_name = %s
            """, (col,))
            row = cur.fetchone()
        assert row is not None, (
            f"user_embeddings_history missing vector column: {col}"
        )


# ---------------------------------------------------------------------------
# 16. Entity layer: CyberEntity dataclass fields
# ---------------------------------------------------------------------------
class TestCyberEntityDataclass:
    def test_required_fields(self):
        from models.cyber_entity import CyberEntity
        field_names = {f.name for f in fields(CyberEntity)}
        expected = {
            "entity_type", "entity_id", "profile",
            "zone_embeddings", "composite_embedding",
            "phase_state", "relationships", "risk_scores",
            "computed_at", "data_gaps", "context",
        }
        missing = expected - field_names
        assert not missing, f"CyberEntity missing fields: {missing}"


# ---------------------------------------------------------------------------
# 17. Entity layer: PhaseState dataclass fields
# ---------------------------------------------------------------------------
class TestPhaseStateDataclass:
    def test_required_fields(self):
        from models.cyber_entity import PhaseState
        field_names = {f.name for f in fields(PhaseState)}
        expected = {
            "velocity_vector", "velocity_magnitude", "acceleration",
            "stability", "regime_shifts", "trend_consistency",
            "total_drift", "current_regime",
        }
        missing = expected - field_names
        assert not missing, f"PhaseState missing fields: {missing}"


# ---------------------------------------------------------------------------
# 18. Data range: 2025-01-01 to 2025-05-10
# ---------------------------------------------------------------------------
class TestDataRange:
    def test_min_date(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT MIN(feature_date) FROM daily_features")
            actual_min = cur.fetchone()[0]
        assert actual_min == MIN_DATE, (
            f"daily_features min date = {actual_min}, expected {MIN_DATE}"
        )

    def test_max_date(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(feature_date) FROM daily_features")
            actual_max = cur.fetchone()[0]
        assert actual_max == MAX_DATE, (
            f"daily_features max date = {actual_max}, expected {MAX_DATE}"
        )


# ---------------------------------------------------------------------------
# 19. Row counts
# ---------------------------------------------------------------------------
class TestRowCounts:
    def test_daily_features_count(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM daily_features")
            count = cur.fetchone()[0]
        assert count == 32500, (
            f"daily_features has {count} rows, expected 32500 (250 users x 130 days)"
        )

    def test_behavioral_snapshots_count(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM behavioral_snapshots")
            count = cur.fetchone()[0]
        assert count == 32500, (
            f"behavioral_snapshots has {count} rows, expected 32500"
        )

    def test_trajectory_snapshots_count(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM trajectory_snapshots")
            count = cur.fetchone()[0]
        assert count == 32250, (
            f"trajectory_snapshots has {count} rows, expected 32250 "
            "(250 users x 129 days, needs 2+ snapshots for velocity)"
        )

    def test_trajectory_events_count(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM trajectory_events")
            count = cur.fetchone()[0]
        assert count == 32250, (
            f"trajectory_events has {count} rows, expected 32250"
        )

    def test_user_embeddings_history_count(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM user_embeddings_history")
            count = cur.fetchone()[0]
        assert count >= 32500, (
            f"user_embeddings_history has {count} rows, expected >= 32500"
        )
