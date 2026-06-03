"""Database access layer for the Streamlit dashboard.

All dashboard data loading goes through this module.
Falls back to CSV if the DB is unavailable.
"""
import json
import os
from pathlib import Path

import pandas as pd

TIER3_DIR = Path("data/tier3_results")
COMP_DIR = Path("data/comparison_results")

_engine_cache = None
_raw_conn_cache = None
_db_available_cache = None


def _get_engine():
    global _engine_cache
    if _engine_cache is not None:
        return _engine_cache
    try:
        from sqlalchemy import create_engine
        db_url = os.getenv("DATABASE_URL_HOST")
        if db_url:
            sa_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        else:
            host = os.getenv("DB_HOST", "127.0.0.1")
            port = os.getenv("DB_PORT", "5437")
            dbname = os.getenv("DB_NAME", "cyber_ueba")
            user = os.getenv("DB_USER", "cyber_ueba")
            pw = os.getenv("DB_PASSWORD", "password")
            sa_url = f"postgresql+psycopg2://{user}:{pw}@{host}:{port}/{dbname}"
        _engine_cache = create_engine(sa_url, connect_args={"connect_timeout": 3})
        return _engine_cache
    except Exception:
        _engine_cache = None
        return None


def _get_conn():
    global _raw_conn_cache
    if _raw_conn_cache is not None and _raw_conn_cache.closed == 0:
        return _raw_conn_cache
    try:
        from pipeline.db_connect import get_connection
        _raw_conn_cache = get_connection()
        return _raw_conn_cache
    except Exception:
        _raw_conn_cache = None
        return None


def _db_available() -> bool:
    global _db_available_cache
    if _db_available_cache is not None:
        return _db_available_cache
    conn = _get_conn()
    if conn is None:
        _db_available_cache = False
        return False
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM composite_scores LIMIT 1")
        _db_available_cache = cur.fetchone() is not None
        return _db_available_cache
    except Exception:
        _db_available_cache = False
        return False


def load_composite_scores() -> pd.DataFrame:
    engine = _get_engine()
    if engine and _db_available():
        try:
            df = pd.read_sql(
                "SELECT uid, is_attack, grp, role, signal_strength, breadth_15, "
                "breadth_20, sustained_signal, ctx_spread_z, ctx_max_z, "
                "novelty_score, composite FROM composite_scores ORDER BY composite DESC",
                engine,
            )
            if not df.empty:
                return df
        except Exception:
            pass
    path = TIER3_DIR / "composite_scores.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def load_detection_results() -> pd.DataFrame:
    engine = _get_engine()
    if engine and _db_available():
        try:
            df = pd.read_sql("SELECT * FROM detection_results ORDER BY user_id", engine)
            if not df.empty:
                if "extra_columns" in df.columns:
                    extras = df["extra_columns"].apply(
                        lambda x: json.loads(x) if isinstance(x, str) else (x or {})
                    )
                    extra_df = pd.DataFrame(extras.tolist(), index=df.index)
                    df = pd.concat([df.drop(columns=["extra_columns", "computed_at"], errors="ignore"), extra_df], axis=1)
                else:
                    df = df.drop(columns=["computed_at"], errors="ignore")
                return df
        except Exception:
            pass
    path = TIER3_DIR / "tier3_comparison.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def load_novelty_metrics() -> pd.DataFrame:
    engine = _get_engine()
    if engine and _db_available():
        try:
            df = pd.read_sql(
                "SELECT uid, persistent_novel_ips, novel_ip_max_persistence, "
                "novel_ip_weeks_frac FROM novelty_metrics ORDER BY uid",
                engine,
            )
            if not df.empty:
                return df
        except Exception:
            pass
    path = TIER3_DIR / "novelty_metrics.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def load_zscored_features() -> pd.DataFrame:
    engine = _get_engine()
    if engine and _db_available():
        try:
            df = pd.read_sql(
                "SELECT uid, is_attack, grp, role, z_scores FROM zscored_features ORDER BY uid",
                engine,
            )
            if not df.empty:
                z_expanded = df["z_scores"].apply(
                    lambda x: json.loads(x) if isinstance(x, str) else (x or {})
                )
                z_df = pd.DataFrame(z_expanded.tolist(), index=df.index)
                z_df = z_df.apply(pd.to_numeric, errors="coerce")
                return pd.concat([df.drop(columns=["z_scores"]), z_df], axis=1)
        except Exception:
            pass
    path = TIER3_DIR / "zscored_features.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def load_weekly_trajectories() -> pd.DataFrame:
    engine = _get_engine()
    if engine and _db_available():
        try:
            df = pd.read_sql(
                "SELECT user_id, is_attack, department, role, week_idx, week_start, "
                "week_end, identity_drift, access_pattern_drift, data_behavior_drift, "
                "network_footprint_drift, risk_posture_drift, composite_drift, "
                "velocity, acceleration, week_to_week_drift, "
                "composite_drift_normal_ops, composite_drift_insider_investigation, "
                "composite_drift_apt_hunt, composite_drift_privilege_audit, "
                "relationship_drift, zone_divergence "
                "FROM weekly_trajectories ORDER BY user_id, week_idx",
                engine,
            )
            if not df.empty:
                return df
        except Exception:
            pass
    path = TIER3_DIR / "all250_trajectories.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def load_weekly_features() -> pd.DataFrame:
    engine = _get_engine()
    if engine and _db_available():
        try:
            df = pd.read_sql(
                "SELECT user_id, week_idx, week_start, week_end, features "
                "FROM weekly_features ORDER BY user_id, week_idx",
                engine,
            )
            if not df.empty:
                feat_expanded = df["features"].apply(
                    lambda x: json.loads(x) if isinstance(x, str) else (x or {})
                )
                feat_df = pd.DataFrame(feat_expanded.tolist(), index=df.index)
                return pd.concat([df[["user_id", "week_idx", "week_start", "week_end"]], feat_df], axis=1)
        except Exception:
            pass
    path = COMP_DIR / "weekly_features.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def load_alerts() -> pd.DataFrame:
    engine = _get_engine()
    if engine and _db_available():
        try:
            df = pd.read_sql(
                "SELECT id, entity_type, entity_id, severity, title, description, "
                "drift_magnitude, concept_alignments, mitre_techniques, "
                "detected_at, status, detection_method, confidence, kill_chain_id "
                "FROM alerts ORDER BY detected_at DESC",
                engine,
            )
            if not df.empty:
                for jcol in ("concept_alignments", "mitre_techniques"):
                    if jcol in df.columns:
                        df[jcol] = df[jcol].apply(
                            lambda x: json.loads(x) if isinstance(x, str) else (x if x is not None else [])
                        )
                if "detected_at" in df.columns:
                    df["detected_at"] = pd.to_datetime(df["detected_at"])
                return df
        except Exception:
            pass
    path = Path("data/pipeline_results/alerts.json")
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        df = pd.DataFrame(data)
        if "detected_at" in df.columns:
            df["detected_at"] = pd.to_datetime(df["detected_at"])
        return df
    return pd.DataFrame()


def load_kill_chains() -> list:
    conn = _get_conn()
    if conn and _db_available():
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, created_at, status, severity, duration_seconds, "
                "tactics_observed, entities_involved FROM kill_chains ORDER BY created_at"
            )
            chains = []
            for row in cur.fetchall():
                kc_id = row[0]
                tactics = row[5]
                if isinstance(tactics, str):
                    tactics = json.loads(tactics)
                entities = row[6]
                if isinstance(entities, str):
                    entities = json.loads(entities)
                cur2 = conn.cursor()
                cur2.execute(
                    "SELECT alert_id, entity_type, entity_id, timestamp, tactic, "
                    "techniques, description, confidence FROM kill_chain_events "
                    "WHERE kill_chain_id = %s ORDER BY event_order", (kc_id,)
                )
                events = []
                for evt_row in cur2.fetchall():
                    techs = evt_row[5]
                    if isinstance(techs, str):
                        techs = json.loads(techs)
                    events.append({
                        "alert_id": evt_row[0],
                        "entity_type": evt_row[1],
                        "entity_id": evt_row[2],
                        "timestamp": str(evt_row[3]) if evt_row[3] else None,
                        "tactic": evt_row[4],
                        "techniques": techs if techs else [],
                        "description": evt_row[6],
                        "confidence": float(evt_row[7]) if evt_row[7] is not None else 0.0,
                    })
                chains.append({
                    "id": kc_id,
                    "created_at": str(row[1]) if row[1] else None,
                    "status": row[2],
                    "severity": row[3],
                    "duration_seconds": float(row[4]) if row[4] is not None else 0,
                    "tactics_observed": tactics if tactics else [],
                    "entities_involved": entities if entities else [],
                    "events": events,
                })
            if chains:
                return chains
        except Exception:
            pass
    path = Path("data/pipeline_results/kill_chains.json")
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def load_log_stats() -> dict:
    conn = _get_conn()
    if conn and _db_available():
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM log_stats LIMIT 1")
            if cur.fetchone():
                cur.execute(
                    "SELECT source, file_count, sample_rows, est_total_events FROM log_stats"
                )
                stats = {}
                for row in cur.fetchall():
                    stats[row[0]] = {
                        "files": row[1],
                        "sample_rows": row[2],
                        "est_total": row[3],
                    }
                if stats:
                    return stats
        except Exception:
            pass
    generated_dir = Path("data/generated")
    stats = {}
    log_types = ["auth", "network", "dns", "endpoint", "file_access", "app", "privilege"]
    for lt in log_types:
        log_dir = generated_dir / lt
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


def load_drift_series() -> pd.DataFrame:
    engine = _get_engine()
    if engine and _db_available():
        try:
            cur = _get_conn().cursor()
            cur.execute("SELECT 1 FROM drift_series LIMIT 1")
            if cur.fetchone():
                df = pd.read_sql(
                    "SELECT entity_type, entity_id, cutoff_date, drift_from_first "
                    "FROM drift_series ORDER BY entity_id, cutoff_date",
                    engine,
                )
                if not df.empty:
                    if "cutoff_date" in df.columns:
                        df["cutoff_date"] = pd.to_datetime(df["cutoff_date"])
                    return df
        except Exception:
            pass
    path = Path("data/pipeline_results/drift_series.csv")
    if path.exists():
        df = pd.read_csv(path)
        if "cutoff_date" in df.columns:
            df["cutoff_date"] = pd.to_datetime(df["cutoff_date"])
        return df
    return pd.DataFrame()


def load_user_roster() -> pd.DataFrame:
    conn = _get_conn()
    if conn and _db_available():
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'entity_profiles'")
            if cur.fetchone():
                engine = _get_engine()
                df = pd.read_sql(
                    "SELECT entity_id as user_id, profile->>'user_type' as user_type, "
                    "profile->>'department' as department, profile->>'role' as role, "
                    "profile->>'clearance' as clearance "
                    "FROM entity_profiles WHERE entity_type = 'user' ORDER BY entity_id",
                    engine,
                )
                if not df.empty:
                    return df
        except Exception:
            pass
    path = Path("data/generated/entities/users.csv")
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame()
