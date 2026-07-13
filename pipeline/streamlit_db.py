"""Streamlit-compatible data loading from PostgreSQL.

Provides cached data loading functions for the ACECARD Streamlit dashboard.
Each function gets its own DB connection (short-lived) to avoid holding
connection pools across Streamlit re-renders.

All functions are safe to call when DB is unavailable — they return empty
DataFrames/dicts and the Streamlit app can fall back to file-based loading.
"""

import json
import os
from datetime import date, datetime

import numpy as np
import pandas as pd


_db_checked = None


def _get_conn():
    """Get a fresh DB connection. Returns None if unavailable."""
    global _db_checked
    if _db_checked is False:
        return None
    try:
        from pipeline.db_connect import get_connection
        return get_connection()
    except Exception:
        _db_checked = False
        return None


def db_available() -> bool:
    """Check if PostgreSQL is reachable."""
    global _db_checked
    if _db_checked is not None:
        return _db_checked
    conn = _get_conn()
    if conn is None:
        _db_checked = False
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        _db_checked = True
        return True
    except Exception:
        _db_checked = False
        return False


def load_dashboard_stats() -> dict:
    """Load KPI stats for the dashboard page."""
    conn = _get_conn()
    if conn is None:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM trajectory_events")
            n_events = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM trajectory_events WHERE severity = 'high'")
            n_high = cur.fetchone()[0]

            cur.execute("SELECT count(DISTINCT entity_id) FROM trajectory_events")
            n_entities = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM behavioral_snapshots")
            n_snapshots = cur.fetchone()[0]

            cur.execute("SELECT count(DISTINCT entity_id) FROM behavioral_snapshots WHERE entity_type = 'user'")
            n_users = cur.fetchone()[0]

            cur.execute("SELECT min(cutoff_date), max(cutoff_date) FROM behavioral_snapshots")
            row = cur.fetchone()
            date_range = (str(row[0]), str(row[1])) if row[0] else ("", "")

        conn.close()
        return {
            "total_events": n_events,
            "high_events": n_high,
            "entities_affected": n_entities,
            "total_snapshots": n_snapshots,
            "total_users": n_users,
            "date_range": date_range,
        }
    except Exception:
        conn.close()
        return {}


def load_trajectory_events(severity: str = None, limit: int = 200) -> pd.DataFrame:
    """Load trajectory events for the alerts/dashboard page."""
    conn = _get_conn()
    if conn is None:
        return pd.DataFrame()
    try:
        sql = """
            SELECT entity_type, entity_id, event_date, event_type,
                   severity, magnitude, shift_type, direction,
                   contributing_factors
            FROM trajectory_events
            ORDER BY event_date DESC, magnitude DESC
        """
        params = []
        if severity:
            sql = sql.replace("ORDER BY", f"WHERE severity = %s ORDER BY")
            params.append(severity)
        sql += " LIMIT %s"
        params.append(limit)

        df = pd.read_sql(sql, conn, params=params)
        conn.close()
        return df
    except Exception:
        conn.close()
        return pd.DataFrame()


def load_drift_heatmap() -> pd.DataFrame:
    """Load drift heatmap data from the latest trajectory snapshot date."""
    conn = _get_conn()
    if conn is None:
        return pd.DataFrame()
    try:
        sql = """
            SELECT entity_id, velocity_magnitude, acceleration, stability,
                   total_drift, current_regime, zone_drifts, context_drifts
            FROM trajectory_snapshots
            WHERE entity_type = 'user'
              AND cutoff_date = (
                  SELECT max(cutoff_date) FROM trajectory_snapshots WHERE entity_type = 'user'
              )
            ORDER BY total_drift DESC
        """
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        conn.close()
        if not rows:
            return pd.DataFrame()

        flat_rows = []
        for r in rows:
            flat = {
                "entity_id": r["entity_id"],
                "velocity_magnitude": float(r["velocity_magnitude"]),
                "acceleration": float(r["acceleration"]),
                "stability": float(r["stability"]),
                "total_drift": float(r["total_drift"]),
                "current_regime": r["current_regime"],
            }
            zd = r.get("zone_drifts")
            if zd:
                if isinstance(zd, str):
                    zd = json.loads(zd)
                for k, v in zd.items():
                    flat[f"zone_{k}"] = float(v)
            cd = r.get("context_drifts")
            if cd:
                if isinstance(cd, str):
                    cd = json.loads(cd)
                for k, v in cd.items():
                    flat[f"ctx_{k}"] = float(v)
            flat_rows.append(flat)

        return pd.DataFrame(flat_rows)
    except Exception:
        conn.close()
        return pd.DataFrame()


def load_entity_timeline(entity_id: str) -> pd.DataFrame:
    """Load daily trajectory metrics for one entity over time."""
    conn = _get_conn()
    if conn is None:
        return pd.DataFrame()
    try:
        sql = """
            SELECT cutoff_date, velocity_magnitude, acceleration, stability,
                   total_drift, current_regime, zone_drifts
            FROM trajectory_snapshots
            WHERE entity_type = 'user' AND entity_id = %s
            ORDER BY cutoff_date
        """
        with conn.cursor() as cur:
            cur.execute(sql, (entity_id,))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        conn.close()
        if not rows:
            return pd.DataFrame()

        flat = []
        for r in rows:
            entry = {
                "cutoff_date": r["cutoff_date"],
                "velocity_magnitude": float(r["velocity_magnitude"]),
                "acceleration": float(r["acceleration"]),
                "stability": float(r["stability"]),
                "total_drift": float(r["total_drift"]),
                "current_regime": r["current_regime"],
            }
            zd = r.get("zone_drifts")
            if zd:
                if isinstance(zd, str):
                    zd = json.loads(zd)
                for k, v in zd.items():
                    entry[f"zone_{k}"] = float(v)
            flat.append(entry)

        return pd.DataFrame(flat)
    except Exception:
        conn.close()
        return pd.DataFrame()


def load_entity_structure(entity_id: str) -> dict:
    """Load Digital Entity structure from DB for the entity detail page."""
    conn = _get_conn()
    if conn is None:
        return {}
    try:
        # Latest behavioral snapshot
        sql = """
            SELECT cutoff_date, zone_texts
            FROM behavioral_snapshots
            WHERE entity_type = 'user' AND entity_id = %s
            ORDER BY cutoff_date DESC
            LIMIT 1
        """
        with conn.cursor() as cur:
            cur.execute(sql, (entity_id,))
            snap_row = cur.fetchone()

        if not snap_row:
            conn.close()
            return {}

        zone_texts = {}
        if snap_row[1]:
            zone_texts = json.loads(snap_row[1]) if isinstance(snap_row[1], str) else snap_row[1]

        if not zone_texts:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT zone_texts FROM behavioral_snapshots "
                    "WHERE entity_type = 'user' AND entity_id = %s "
                    "AND zone_texts IS NOT NULL AND zone_texts != '{}' "
                    "ORDER BY cutoff_date DESC LIMIT 1",
                    (entity_id,),
                )
                zt_row = cur.fetchone()
                if zt_row and zt_row[0]:
                    zone_texts = json.loads(zt_row[0]) if isinstance(zt_row[0], str) else zt_row[0]

        # Latest trajectory
        traj_sql = """
            SELECT velocity_magnitude, acceleration, stability,
                   regime_shifts, trend_consistency, total_drift,
                   current_regime, zone_drifts, context_drifts
            FROM trajectory_snapshots
            WHERE entity_type = 'user' AND entity_id = %s
            ORDER BY cutoff_date DESC LIMIT 1
        """
        with conn.cursor() as cur:
            cur.execute(traj_sql, (entity_id,))
            traj_row = cur.fetchone()

        # Latest daily features
        feat_sql = """
            SELECT * FROM daily_features
            WHERE user_id = %s
            ORDER BY feature_date DESC LIMIT 1
        """
        feat_df = pd.read_sql(feat_sql, conn, params=(entity_id,))

        # User profile
        from pipeline.entity_materialize import _load_user_profiles
        profiles = _load_user_profiles()
        profile = profiles.get(entity_id, {"user_id": entity_id})

        conn.close()

        phase_state = {}
        if traj_row:
            phase_state = {
                "velocity_magnitude": float(traj_row[0]),
                "acceleration": float(traj_row[1]),
                "stability": float(traj_row[2]),
                "regime_shifts": float(traj_row[3]),
                "trend_consistency": float(traj_row[4]),
                "total_drift": float(traj_row[5]),
                "current_regime": traj_row[6],
            }

        raw_features = {}
        zone_features = {}
        if not feat_df.empty:
            row = feat_df.iloc[0]
            skip_cols = {"id", "user_id", "feature_date", "computed_at"}
            raw_features = {
                col: float(row[col]) for col in feat_df.columns
                if col not in skip_cols and pd.notna(row[col])
            }
            zone_features = {
                "identity": {k: profile.get(k, "") for k in ["department", "role", "clearance", "user_type"]},
                "access_pattern": {k: v for k, v in raw_features.items() if k.startswith("auth_")},
                "data_behavior": {k: v for k, v in raw_features.items() if k.startswith("file_")},
                "network_footprint": {k: v for k, v in raw_features.items() if k.startswith(("net_", "dns_"))},
                "risk_posture": {k: v for k, v in raw_features.items() if k.startswith("endpoint_")},
            }

        from models.hierarchical_zones import CONTEXT_WEIGHTS
        ctx_weights = {
            ctx: dict(weights)
            for ctx, weights in CONTEXT_WEIGHTS.get("user", {}).items()
        }

        return {
            "entity_id": entity_id,
            "entity_type": "user",
            "profile": profile,
            "is_attack": entity_id in {"USR-156", "USR-234", "USR-042", "USR-118", "USR-EVA"},
            "raw_features": raw_features,
            "zone_features": zone_features,
            "zone_serialized_text": zone_texts,
            "zone_embedding_dims": {z: 1536 for z in ["identity", "access_pattern", "data_behavior",
                                                        "network_footprint", "risk_posture"]},
            "phase_state": phase_state,
            "context_weights": ctx_weights,
        }
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return {}


def load_all_user_ids() -> list[str]:
    """Get list of all user entity IDs."""
    conn = _get_conn()
    if conn is None:
        return []
    try:
        sql = "SELECT DISTINCT entity_id FROM behavioral_snapshots WHERE entity_type = 'user' ORDER BY entity_id"
        with conn.cursor() as cur:
            cur.execute(sql)
            ids = [r[0] for r in cur.fetchall()]
        conn.close()
        return ids
    except Exception:
        conn.close()
        return []


def load_daily_features_for_entity(entity_id: str) -> pd.DataFrame:
    """Load daily feature time series for one entity."""
    conn = _get_conn()
    if conn is None:
        return pd.DataFrame()
    try:
        sql = "SELECT * FROM daily_features WHERE user_id = %s ORDER BY feature_date"
        df = pd.read_sql(sql, conn, params=(entity_id,))
        conn.close()
        return df
    except Exception:
        conn.close()
        return pd.DataFrame()


def load_zone_drift_series(entity_id: str) -> pd.DataFrame:
    """Load per-zone drift time series from trajectory snapshots.

    Returns DataFrame with columns: cutoff_date, zone_identity, zone_access_pattern,
    zone_data_behavior, zone_network_footprint, zone_risk_posture, total_drift
    """
    conn = _get_conn()
    if conn is None:
        return pd.DataFrame()
    try:
        sql = """
            SELECT cutoff_date, total_drift, zone_drifts
            FROM trajectory_snapshots
            WHERE entity_type = 'user' AND entity_id = %s
            ORDER BY cutoff_date
        """
        with conn.cursor() as cur:
            cur.execute(sql, (entity_id,))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        conn.close()
        if not rows:
            return pd.DataFrame()

        flat = []
        for r in rows:
            entry = {"cutoff_date": r["cutoff_date"], "total_drift": float(r["total_drift"])}
            zd = r.get("zone_drifts")
            if zd:
                if isinstance(zd, str):
                    zd = json.loads(zd)
                for k, v in zd.items():
                    entry[f"zone_{k}"] = float(v)
            flat.append(entry)

        return pd.DataFrame(flat)
    except Exception:
        conn.close()
        return pd.DataFrame()


def load_behavioral_signals_from_db(entity_id: str) -> pd.DataFrame:
    """Load daily features and resample to weekly behavioral signals.

    Returns a DataFrame indexed by week with columns matching the format
    expected by the Behavioral Profile page: auth_volume, auth_failure_rate,
    auth_offhours_rate, privilege_ops, privilege_denied_rate, data_access_ops,
    data_access_bytes_mb, data_access_sensitive_rate, network_bytes_gb,
    network_unique_dst, network_protocols, communication_events,
    communication_apps.
    """
    conn = _get_conn()
    if conn is None:
        return pd.DataFrame()
    try:
        sql = """
            SELECT feature_date,
                   auth_total, auth_fail_rate, auth_off_hours_ratio,
                   priv_total, priv_denied_ratio,
                   file_total, file_total_bytes, file_restricted_ratio,
                   net_bytes_out, net_unique_dsts, net_external_ratio,
                   app_total, app_unique_apps
            FROM daily_features
            WHERE user_id = %s
            ORDER BY feature_date
        """
        df = pd.read_sql(sql, conn, params=(entity_id,))
        conn.close()

        if df.empty:
            return pd.DataFrame()

        df["feature_date"] = pd.to_datetime(df["feature_date"])
        df = df.set_index("feature_date")

        weekly = pd.DataFrame()
        weekly["auth_volume"] = df["auth_total"].resample("W").sum()
        weekly["auth_failure_rate"] = df["auth_fail_rate"].resample("W").mean()
        weekly["auth_offhours_rate"] = df["auth_off_hours_ratio"].resample("W").mean()
        weekly["privilege_ops"] = df["priv_total"].resample("W").sum()
        weekly["privilege_denied_rate"] = df["priv_denied_ratio"].resample("W").mean()
        weekly["data_access_ops"] = df["file_total"].resample("W").sum()
        weekly["data_access_bytes_mb"] = df["file_total_bytes"].resample("W").sum() / (1024 * 1024)
        weekly["data_access_sensitive_rate"] = df["file_restricted_ratio"].resample("W").mean()
        weekly["network_bytes_gb"] = df["net_bytes_out"].resample("W").sum() / (1024 ** 3)
        weekly["network_unique_dst"] = df["net_unique_dsts"].resample("W").max()
        weekly["network_protocols"] = df["net_external_ratio"].resample("W").mean()
        weekly["communication_events"] = df["app_total"].resample("W").sum()
        weekly["communication_apps"] = df["app_unique_apps"].resample("W").max()

        weekly = weekly.dropna(how="all")
        weekly.index.name = "week"
        weekly = weekly.reset_index()
        weekly["week"] = pd.to_datetime(weekly["week"])
        return weekly
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return pd.DataFrame()
