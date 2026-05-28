"""UI/UX Data-Layer Tests -- Streamlit ACECARD dashboard data functions.

Test IDs: UX-001 through UX-013
Covers: DB load functions (return types, consistency, performance),
        file-based fallback functions, chart data format validation,
        behavioral profile data flow, and event filtering.

Requires PostgreSQL at 127.0.0.1:5437 for DB tests (skip if unavailable).
File-based tests skip if data files are missing.
"""

import os
import sys
import time

import numpy as np
import pandas as pd
import pytest

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set DB env vars before importing pipeline modules
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5437")
os.environ.setdefault("DB_NAME", "cyber_ueba")
os.environ.setdefault("DB_USER", "cyber_ueba")
os.environ.setdefault("DB_PASSWORD", "password")

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = DATA_DIR / "pipeline_results"
GENERATED_DIR = DATA_DIR / "generated"

from pipeline.streamlit_db import (
    db_available,
    load_dashboard_stats,
    load_drift_heatmap,
    load_entity_timeline,
    load_entity_structure,
    load_all_user_ids,
    load_trajectory_events,
    load_zone_drift_series,
    load_daily_features_for_entity,
    load_behavioral_signals_from_db,
)

# Known attack users referenced throughout the dashboard
ATTACK_USERS = {"USR-156", "USR-234", "USR-042", "USR-118"}

# Check DB availability once; reuse across tests
DB_IS_UP = db_available()

requires_db = pytest.mark.skipif(not DB_IS_UP, reason="PostgreSQL not reachable at 127.0.0.1:5437")


# ──────────────────────────────────────────────────────────────────────────────
# Helper: standalone compute_signal_drift_scores (no Streamlit cache)
# ──────────────────────────────────────────────────────────────────────────────

def compute_signal_drift_scores(profile_df: pd.DataFrame) -> pd.DataFrame:
    """Replicates streamlit_app.compute_signal_drift_scores without @st.cache_data."""
    signal_groups = {
        "auth": ["auth_volume", "auth_failure_rate", "auth_offhours_rate"],
        "privilege": ["privilege_ops", "privilege_denied_rate"],
        "data_access": ["data_access_ops", "data_access_bytes_mb", "data_access_sensitive_rate"],
        "network": ["network_bytes_gb", "network_unique_dst", "network_protocols"],
        "communication": ["communication_events", "communication_apps"],
    }
    result = pd.DataFrame({"week": profile_df["week"]})

    for signal_name, cols in signal_groups.items():
        available_cols = [c for c in cols if c in profile_df.columns]
        if not available_cols:
            result[signal_name] = 0.0
            continue
        baseline_end = min(2, len(profile_df))
        scores = []
        for col in available_cols:
            baseline_mean = profile_df[col].iloc[:baseline_end].mean()
            baseline_std = profile_df[col].iloc[:baseline_end].std()
            if baseline_std < 1e-10:
                baseline_std = profile_df[col].std()
            if baseline_std < 1e-10:
                scores.append(pd.Series(0.0, index=profile_df.index))
            else:
                z = ((profile_df[col] - baseline_mean) / baseline_std).abs()
                scores.append(z)
        combined = pd.concat(scores, axis=1).mean(axis=1)
        cmax = combined.max()
        if cmax > 0:
            combined = combined / cmax
        result[signal_name] = combined.values

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def all_user_ids():
    """Cached list of all user IDs from DB."""
    if not DB_IS_UP:
        return []
    return load_all_user_ids()


@pytest.fixture(scope="module")
def dashboard_stats():
    """Cached dashboard KPI stats dict."""
    if not DB_IS_UP:
        return {}
    return load_dashboard_stats()


@pytest.fixture(scope="module")
def drift_heatmap_df():
    """Cached heatmap DataFrame."""
    if not DB_IS_UP:
        return pd.DataFrame()
    return load_drift_heatmap()


@pytest.fixture(scope="module")
def sample_user_id(all_user_ids):
    """Return first user ID for entity-level tests."""
    if not all_user_ids:
        return None
    return all_user_ids[0]


@pytest.fixture(scope="module")
def attack_user_id():
    """Return a known attack user ID for tests that need flagged entities."""
    return "USR-156"


# ══════════════════════════════════════════════════════════════════════════════
# UX-001: DB function return types
# ══════════════════════════════════════════════════════════════════════════════

@requires_db
class TestUX001_DBReturnTypes:
    """UX-001: Each load_* function returns the correct type and non-empty."""

    def test_load_dashboard_stats_returns_dict(self, dashboard_stats):
        assert isinstance(dashboard_stats, dict)
        assert len(dashboard_stats) > 0

    def test_load_drift_heatmap_returns_dataframe(self, drift_heatmap_df):
        assert isinstance(drift_heatmap_df, pd.DataFrame)
        assert not drift_heatmap_df.empty

    def test_load_entity_timeline_returns_dataframe(self, sample_user_id):
        df = load_entity_timeline(sample_user_id)
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_load_entity_structure_returns_dict(self, sample_user_id):
        result = load_entity_structure(sample_user_id)
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_load_all_user_ids_returns_list(self, all_user_ids):
        assert isinstance(all_user_ids, list)
        assert len(all_user_ids) > 0

    def test_load_trajectory_events_returns_dataframe(self):
        df = load_trajectory_events()
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_load_zone_drift_series_returns_dataframe(self, sample_user_id):
        df = load_zone_drift_series(sample_user_id)
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_load_daily_features_returns_dataframe(self, sample_user_id):
        df = load_daily_features_for_entity(sample_user_id)
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_load_behavioral_signals_returns_dataframe(self, sample_user_id):
        df = load_behavioral_signals_from_db(sample_user_id)
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_db_available_returns_bool(self):
        result = db_available()
        assert isinstance(result, bool)
        assert result is True


# ══════════════════════════════════════════════════════════════════════════════
# UX-002: Dashboard KPI consistency
# ══════════════════════════════════════════════════════════════════════════════

@requires_db
class TestUX002_DashboardKPIConsistency:
    """UX-002: total_users from stats matches len(load_all_user_ids())."""

    def test_total_users_matches_user_ids_count(self, dashboard_stats, all_user_ids):
        assert "total_users" in dashboard_stats
        assert dashboard_stats["total_users"] == len(all_user_ids)

    def test_stats_keys_present(self, dashboard_stats):
        expected_keys = {"total_events", "high_events", "entities_affected",
                         "total_snapshots", "total_users", "date_range"}
        assert expected_keys.issubset(set(dashboard_stats.keys()))

    def test_stats_values_non_negative(self, dashboard_stats):
        for key in ["total_events", "high_events", "entities_affected",
                     "total_snapshots", "total_users"]:
            assert dashboard_stats[key] >= 0, f"{key} should be non-negative"


# ══════════════════════════════════════════════════════════════════════════════
# UX-003: Heatmap chart readiness
# ══════════════════════════════════════════════════════════════════════════════

@requires_db
class TestUX003_HeatmapChartReadiness:
    """UX-003: Drift heatmap has entity_id and zone_* float columns for plotly."""

    def test_has_entity_id_column(self, drift_heatmap_df):
        assert "entity_id" in drift_heatmap_df.columns

    def test_has_zone_columns(self, drift_heatmap_df):
        zone_cols = [c for c in drift_heatmap_df.columns if c.startswith("zone_")]
        assert len(zone_cols) >= 1, "Should have at least 1 zone_* column"

    def test_zone_values_are_float(self, drift_heatmap_df):
        zone_cols = [c for c in drift_heatmap_df.columns if c.startswith("zone_")]
        for col in zone_cols:
            assert drift_heatmap_df[col].dtype in [np.float64, np.float32, float], \
                f"Column {col} should be float, got {drift_heatmap_df[col].dtype}"

    def test_has_total_drift(self, drift_heatmap_df):
        assert "total_drift" in drift_heatmap_df.columns
        assert drift_heatmap_df["total_drift"].dtype in [np.float64, np.float32, float]

    def test_has_velocity_magnitude(self, drift_heatmap_df):
        assert "velocity_magnitude" in drift_heatmap_df.columns


# ══════════════════════════════════════════════════════════════════════════════
# UX-004: Behavioral Profile data flow
# ══════════════════════════════════════════════════════════════════════════════

@requires_db
class TestUX004_BehavioralProfileDataFlow:
    """UX-004: Behavioral signals -> drift scores produces valid 0-1 range."""

    def test_signals_to_drift_pipeline(self, sample_user_id):
        signals_df = load_behavioral_signals_from_db(sample_user_id)
        assert not signals_df.empty, "Behavioral signals should not be empty"

        drift_df = compute_signal_drift_scores(signals_df)
        assert isinstance(drift_df, pd.DataFrame)
        assert "week" in drift_df.columns

        signal_cols = ["auth", "privilege", "data_access", "network", "communication"]
        for col in signal_cols:
            assert col in drift_df.columns, f"Missing drift score column: {col}"
            vals = drift_df[col].dropna()
            assert (vals >= 0.0).all(), f"{col} has values below 0"
            assert (vals <= 1.0).all(), f"{col} has values above 1"

    def test_drift_scores_has_five_signal_columns(self, sample_user_id):
        signals_df = load_behavioral_signals_from_db(sample_user_id)
        drift_df = compute_signal_drift_scores(signals_df)
        # 'week' + 5 signal columns
        expected_cols = {"week", "auth", "privilege", "data_access", "network", "communication"}
        assert expected_cols == set(drift_df.columns)

    def test_behavioral_signals_has_13_columns(self, sample_user_id):
        signals_df = load_behavioral_signals_from_db(sample_user_id)
        expected_signal_cols = [
            "auth_volume", "auth_failure_rate", "auth_offhours_rate",
            "privilege_ops", "privilege_denied_rate",
            "data_access_ops", "data_access_bytes_mb", "data_access_sensitive_rate",
            "network_bytes_gb", "network_unique_dst", "network_protocols",
            "communication_events", "communication_apps",
        ]
        for col in expected_signal_cols:
            assert col in signals_df.columns, f"Missing signal column: {col}"


# ══════════════════════════════════════════════════════════════════════════════
# UX-005: Entity detail page data
# ══════════════════════════════════════════════════════════════════════════════

@requires_db
class TestUX005_EntityDetailData:
    """UX-005: load_entity_structure returns all keys for Digital Entity page."""

    def test_required_keys_present(self, sample_user_id):
        struct = load_entity_structure(sample_user_id)
        required = {"entity_id", "profile", "zone_features", "phase_state",
                     "context_weights", "is_attack"}
        missing = required - set(struct.keys())
        assert not missing, f"Missing keys: {missing}"

    def test_entity_id_matches(self, sample_user_id):
        struct = load_entity_structure(sample_user_id)
        assert struct["entity_id"] == sample_user_id

    def test_zone_features_has_five_zones(self, sample_user_id):
        struct = load_entity_structure(sample_user_id)
        expected_zones = {"identity", "access_pattern", "data_behavior",
                          "network_footprint", "risk_posture"}
        actual_zones = set(struct.get("zone_features", {}).keys())
        assert expected_zones == actual_zones, \
            f"Expected zones {expected_zones}, got {actual_zones}"

    def test_context_weights_has_four_contexts(self, sample_user_id):
        struct = load_entity_structure(sample_user_id)
        ctx = struct.get("context_weights", {})
        assert len(ctx) >= 4, f"Expected >= 4 contexts, got {len(ctx)}"

    def test_is_attack_flag_correct_for_attack_user(self, attack_user_id):
        struct = load_entity_structure(attack_user_id)
        if struct:
            assert struct["is_attack"] is True

    def test_is_attack_flag_correct_for_normal_user(self, all_user_ids):
        normal = [u for u in all_user_ids if u not in ATTACK_USERS]
        if normal:
            struct = load_entity_structure(normal[0])
            if struct:
                assert struct["is_attack"] is False


# ══════════════════════════════════════════════════════════════════════════════
# UX-006: Timeline chart data
# ══════════════════════════════════════════════════════════════════════════════

@requires_db
class TestUX006_TimelineChartData:
    """UX-006: load_entity_timeline returns ordered dates with valid metrics."""

    def test_dates_are_ordered(self, sample_user_id):
        df = load_entity_timeline(sample_user_id)
        assert not df.empty
        dates = pd.to_datetime(df["cutoff_date"])
        assert dates.is_monotonic_increasing, "Dates should be in ascending order"

    def test_velocity_non_negative(self, sample_user_id):
        df = load_entity_timeline(sample_user_id)
        assert (df["velocity_magnitude"] >= 0).all(), "velocity_magnitude should be >= 0"

    def test_has_zone_columns(self, sample_user_id):
        df = load_entity_timeline(sample_user_id)
        zone_cols = [c for c in df.columns if c.startswith("zone_")]
        assert len(zone_cols) >= 1, "Timeline should have zone_* columns for small multiples"


# ══════════════════════════════════════════════════════════════════════════════
# UX-007: User selector consistency
# ══════════════════════════════════════════════════════════════════════════════

@requires_db
class TestUX007_UserSelectorConsistency:
    """UX-007: load_all_user_ids returns sorted list with all attack users."""

    def test_returns_250_users(self, all_user_ids):
        assert len(all_user_ids) == 250, f"Expected 250 users, got {len(all_user_ids)}"

    def test_list_is_sorted(self, all_user_ids):
        assert all_user_ids == sorted(all_user_ids), "User IDs should be sorted"

    def test_attack_users_included(self, all_user_ids):
        for uid in ATTACK_USERS:
            assert uid in all_user_ids, f"Attack user {uid} should be in user list"


# ══════════════════════════════════════════════════════════════════════════════
# UX-008: Fallback path testing (file-based functions)
# ══════════════════════════════════════════════════════════════════════════════

class TestUX008_FallbackPaths:
    """UX-008: File-based functions work when data files exist."""

    def _load_alerts_no_cache(self):
        import json
        path = RESULTS_DIR / "alerts.json"
        if not path.exists():
            return pd.DataFrame()
        with open(path) as f:
            data = json.load(f)
        df = pd.DataFrame(data)
        if "detected_at" in df.columns:
            df["detected_at"] = pd.to_datetime(df["detected_at"])
        return df

    def _load_kill_chains_no_cache(self):
        import json
        path = RESULTS_DIR / "kill_chains.json"
        if not path.exists():
            return []
        with open(path) as f:
            return json.load(f)

    def _load_drift_series_no_cache(self):
        path = RESULTS_DIR / "drift_series.csv"
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_csv(path)
        if "cutoff_date" in df.columns:
            df["cutoff_date"] = pd.to_datetime(df["cutoff_date"])
        return df

    def _load_log_stats_no_cache(self):
        stats = {}
        log_types = ["auth", "network", "dns", "endpoint", "file_access", "app", "privilege"]
        for lt in log_types:
            log_dir = GENERATED_DIR / lt
            if log_dir.exists():
                csvs = list(log_dir.glob("*.csv"))
                total_rows = 0
                for csv_path in csvs[:5]:
                    try:
                        total_rows += sum(1 for _ in open(csv_path)) - 1
                    except Exception:
                        pass
                stats[lt] = {
                    "files": len(csvs),
                    "sample_rows": total_rows,
                    "est_total": total_rows * len(csvs) // max(min(5, len(csvs)), 1) if csvs else 0,
                }
        return stats

    @pytest.mark.skipif(
        not (RESULTS_DIR / "alerts.json").exists(),
        reason="alerts.json not found"
    )
    def test_load_alerts_returns_dataframe(self):
        df = self._load_alerts_no_cache()
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert "severity" in df.columns or "entity_id" in df.columns

    @pytest.mark.skipif(
        not (RESULTS_DIR / "kill_chains.json").exists(),
        reason="kill_chains.json not found"
    )
    def test_load_kill_chains_returns_list(self):
        chains = self._load_kill_chains_no_cache()
        assert isinstance(chains, list)
        assert len(chains) > 0

    @pytest.mark.skipif(
        not (RESULTS_DIR / "drift_series.csv").exists(),
        reason="drift_series.csv not found"
    )
    def test_load_drift_series_returns_dataframe(self):
        df = self._load_drift_series_no_cache()
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert "cutoff_date" in df.columns

    @pytest.mark.skipif(
        not (GENERATED_DIR / "auth").exists(),
        reason="Generated auth data not found"
    )
    def test_load_log_stats_returns_dict(self):
        stats = self._load_log_stats_no_cache()
        assert isinstance(stats, dict)
        assert len(stats) > 0
        for lt, info in stats.items():
            assert "files" in info
            assert "sample_rows" in info
            assert info["files"] > 0


# ══════════════════════════════════════════════════════════════════════════════
# UX-009: Chart data format validation (radar chart)
# ══════════════════════════════════════════════════════════════════════════════

@requires_db
class TestUX009_RadarChartFormat:
    """UX-009: Behavioral Profile radar chart data has 5 values in [0,1]."""

    def test_baseline_and_current_vals_valid(self, sample_user_id):
        signals_df = load_behavioral_signals_from_db(sample_user_id)
        assert not signals_df.empty

        drift_df = compute_signal_drift_scores(signals_df)
        signal_cols = ["auth", "privilege", "data_access", "network", "communication"]

        # Baseline = first row, current = last row (mimics dashboard radar)
        baseline_vals = [drift_df[c].iloc[0] for c in signal_cols]
        current_vals = [drift_df[c].iloc[-1] for c in signal_cols]

        assert len(baseline_vals) == 5
        assert len(current_vals) == 5

        for v in baseline_vals + current_vals:
            assert 0.0 <= v <= 1.0, f"Radar value {v} out of [0,1] range"

    def test_closed_polygon(self, sample_user_id):
        """Radar chart needs first value appended to close the polygon."""
        signals_df = load_behavioral_signals_from_db(sample_user_id)
        drift_df = compute_signal_drift_scores(signals_df)
        signal_cols = ["auth", "privilege", "data_access", "network", "communication"]

        vals = [drift_df[c].iloc[-1] for c in signal_cols]
        closed = vals + [vals[0]]  # Append first to close polygon
        assert len(closed) == 6
        assert closed[0] == closed[-1]


# ══════════════════════════════════════════════════════════════════════════════
# UX-010: Event filtering
# ══════════════════════════════════════════════════════════════════════════════

@requires_db
class TestUX010_EventFiltering:
    """UX-010: load_trajectory_events respects severity filter and limit."""

    def test_severity_filter_high(self):
        df = load_trajectory_events(severity="high", limit=50)
        assert isinstance(df, pd.DataFrame)
        if not df.empty:
            assert (df["severity"] == "high").all(), "All events should be severity=high"

    def test_limit_respected(self):
        df = load_trajectory_events(severity="high", limit=50)
        assert len(df) <= 50, f"Expected <= 50 rows, got {len(df)}"

    def test_no_filter_returns_all_severities(self):
        df = load_trajectory_events(limit=200)
        if not df.empty:
            assert "severity" in df.columns


# ══════════════════════════════════════════════════════════════════════════════
# UX-011: Zone drift series for sparklines
# ══════════════════════════════════════════════════════════════════════════════

@requires_db
class TestUX011_ZoneDriftSeries:
    """UX-011: load_zone_drift_series returns proper sparkline data."""

    def test_has_cutoff_date(self, sample_user_id):
        df = load_zone_drift_series(sample_user_id)
        assert not df.empty
        assert "cutoff_date" in df.columns

    def test_has_zone_columns(self, sample_user_id):
        df = load_zone_drift_series(sample_user_id)
        zone_cols = [c for c in df.columns if c.startswith("zone_")]
        assert len(zone_cols) >= 1, "Should have zone_* columns"

    def test_has_total_drift(self, sample_user_id):
        df = load_zone_drift_series(sample_user_id)
        assert "total_drift" in df.columns

    def test_values_are_float(self, sample_user_id):
        df = load_zone_drift_series(sample_user_id)
        float_cols = [c for c in df.columns if c.startswith("zone_") or c == "total_drift"]
        for col in float_cols:
            assert df[col].dtype in [np.float64, np.float32, float], \
                f"Column {col} should be float"

    def test_ordered_by_date(self, sample_user_id):
        df = load_zone_drift_series(sample_user_id)
        dates = pd.to_datetime(df["cutoff_date"])
        assert dates.is_monotonic_increasing, "Dates should be ascending"


# ══════════════════════════════════════════════════════════════════════════════
# UX-012: Daily features time series
# ══════════════════════════════════════════════════════════════════════════════

@requires_db
class TestUX012_DailyFeatures:
    """UX-012: load_daily_features_for_entity returns full time series."""

    def test_row_count(self, sample_user_id):
        df = load_daily_features_for_entity(sample_user_id)
        assert len(df) >= 130, f"Expected >= 130 rows, got {len(df)}"

    def test_column_count(self, sample_user_id):
        df = load_daily_features_for_entity(sample_user_id)
        assert len(df.columns) >= 30, f"Expected >= 30 columns, got {len(df.columns)}"

    def test_has_feature_date(self, sample_user_id):
        df = load_daily_features_for_entity(sample_user_id)
        assert "feature_date" in df.columns


# ══════════════════════════════════════════════════════════════════════════════
# UX-013: Performance for UI responsiveness
# ══════════════════════════════════════════════════════════════════════════════

@requires_db
class TestUX013_Performance:
    """UX-013: All DB functions complete in < 3 seconds."""

    def _timed_call(self, func, *args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        return result, elapsed

    def test_load_dashboard_stats_speed(self):
        _, elapsed = self._timed_call(load_dashboard_stats)
        assert elapsed < 3.0, f"load_dashboard_stats took {elapsed:.2f}s (limit 3s)"

    def test_load_drift_heatmap_speed(self):
        _, elapsed = self._timed_call(load_drift_heatmap)
        assert elapsed < 3.0, f"load_drift_heatmap took {elapsed:.2f}s (limit 3s)"

    def test_load_entity_timeline_speed(self, sample_user_id):
        _, elapsed = self._timed_call(load_entity_timeline, sample_user_id)
        assert elapsed < 3.0, f"load_entity_timeline took {elapsed:.2f}s (limit 3s)"

    def test_load_entity_structure_speed(self, sample_user_id):
        _, elapsed = self._timed_call(load_entity_structure, sample_user_id)
        assert elapsed < 3.0, f"load_entity_structure took {elapsed:.2f}s (limit 3s)"

    def test_load_all_user_ids_speed(self):
        _, elapsed = self._timed_call(load_all_user_ids)
        assert elapsed < 3.0, f"load_all_user_ids took {elapsed:.2f}s (limit 3s)"

    def test_load_trajectory_events_speed(self):
        _, elapsed = self._timed_call(load_trajectory_events)
        assert elapsed < 3.0, f"load_trajectory_events took {elapsed:.2f}s (limit 3s)"

    def test_load_zone_drift_series_speed(self, sample_user_id):
        _, elapsed = self._timed_call(load_zone_drift_series, sample_user_id)
        assert elapsed < 3.0, f"load_zone_drift_series took {elapsed:.2f}s (limit 3s)"

    def test_load_daily_features_speed(self, sample_user_id):
        _, elapsed = self._timed_call(load_daily_features_for_entity, sample_user_id)
        assert elapsed < 3.0, f"load_daily_features_for_entity took {elapsed:.2f}s (limit 3s)"

    def test_load_behavioral_signals_speed(self, sample_user_id):
        _, elapsed = self._timed_call(load_behavioral_signals_from_db, sample_user_id)
        assert elapsed < 3.0, f"load_behavioral_signals_from_db took {elapsed:.2f}s (limit 3s)"
