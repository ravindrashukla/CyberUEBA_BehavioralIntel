"""Populate dashboard PostgreSQL tables from CSV files.

Usage:
    python -m pipeline.populate_dashboard_tables
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from pipeline.db_connect import get_connection

TIER3_DIR = Path("data/tier3_results")
COMP_DIR = Path("data/comparison_results")


def populate_composite_scores(conn):
    path = TIER3_DIR / "composite_scores.csv"
    if not path.exists():
        print(f"  SKIP composite_scores: {path} not found")
        return
    df = pd.read_csv(path)
    cur = conn.cursor()
    cur.execute("DELETE FROM composite_scores")
    for _, r in df.iterrows():
        cur.execute(
            """INSERT INTO composite_scores
               (uid, is_attack, grp, role, signal_strength, breadth_15, breadth_20,
                sustained_signal, ctx_spread_z, ctx_max_z, novelty_score, composite)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (r.uid, bool(r.is_attack), r.grp, r.role, float(r.signal_strength),
             int(r.breadth_15), int(r.breadth_20), float(r.sustained_signal),
             float(r.ctx_spread_z), float(r.ctx_max_z), float(r.novelty_score),
             float(r.composite)),
        )
    conn.commit()
    print(f"  composite_scores: {len(df)} rows")


def populate_detection_results(conn):
    path = TIER3_DIR / "tier3_comparison.csv"
    if not path.exists():
        print(f"  SKIP detection_results: {path} not found")
        return
    df = pd.read_csv(path)
    cur = conn.cursor()
    cur.execute("DELETE FROM detection_results")

    core_cols = [
        "iforest_score", "iforest_anomaly", "ocsvm_score", "ocsvm_anomaly",
        "lof_score", "lof_anomaly", "zscore_max", "zscore_anomaly",
        "temporal_max_z", "temporal_mean_z", "temporal_anomaly",
        "feat_cusum_value", "feat_cusum_detected",
        "acecard_cusum_value", "acecard_cusum_detected",
        "t3_cusum_max", "t3_cusum_detected",
    ]
    extra_cols = [c for c in df.columns if c not in core_cols + ["user_id", "is_attack"]]

    for _, r in df.iterrows():
        extra = {c: _safe_val(r.get(c)) for c in extra_cols if pd.notna(r.get(c))}
        cur.execute(
            """INSERT INTO detection_results
               (user_id, is_attack, iforest_score, iforest_anomaly,
                ocsvm_score, ocsvm_anomaly, lof_score, lof_anomaly,
                zscore_max, zscore_anomaly, temporal_max_z, temporal_mean_z,
                temporal_anomaly, feat_cusum_value, feat_cusum_detected,
                acecard_cusum_value, acecard_cusum_detected,
                t3_cusum_max, t3_cusum_detected, extra_columns)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (r.user_id, bool(r.get("is_attack", False)),
             _safe_float(r, "iforest_score"), _safe_bool(r, "iforest_anomaly"),
             _safe_float(r, "ocsvm_score"), _safe_bool(r, "ocsvm_anomaly"),
             _safe_float(r, "lof_score"), _safe_bool(r, "lof_anomaly"),
             _safe_float(r, "zscore_max"), _safe_bool(r, "zscore_anomaly"),
             _safe_float(r, "temporal_max_z"), _safe_float(r, "temporal_mean_z"),
             _safe_bool(r, "temporal_anomaly"),
             _safe_float(r, "feat_cusum_value"), _safe_bool(r, "feat_cusum_detected"),
             _safe_float(r, "acecard_cusum_value"), _safe_bool(r, "acecard_cusum_detected"),
             _safe_float(r, "t3_cusum_max"), _safe_bool(r, "t3_cusum_detected"),
             json.dumps(extra)),
        )
    conn.commit()
    print(f"  detection_results: {len(df)} rows ({len(extra_cols)} extra columns as JSONB)")


def populate_novelty_metrics(conn):
    path = TIER3_DIR / "novelty_metrics.csv"
    if not path.exists():
        print(f"  SKIP novelty_metrics: {path} not found")
        return
    df = pd.read_csv(path)
    cur = conn.cursor()
    cur.execute("DELETE FROM novelty_metrics")
    for _, r in df.iterrows():
        cur.execute(
            """INSERT INTO novelty_metrics
               (uid, persistent_novel_ips, novel_ip_max_persistence, novel_ip_weeks_frac)
               VALUES (%s,%s,%s,%s)""",
            (r.uid, int(r.persistent_novel_ips), int(r.novel_ip_max_persistence),
             float(r.novel_ip_weeks_frac)),
        )
    conn.commit()
    print(f"  novelty_metrics: {len(df)} rows")


def populate_zscored_features(conn):
    path = TIER3_DIR / "zscored_features.csv"
    if not path.exists():
        print(f"  SKIP zscored_features: {path} not found")
        return
    df = pd.read_csv(path)
    cur = conn.cursor()
    cur.execute("DELETE FROM zscored_features")
    z_cols = [c for c in df.columns if c.startswith("z_")]
    for _, r in df.iterrows():
        z_scores = {c: float(r[c]) for c in z_cols if pd.notna(r[c])}
        cur.execute(
            """INSERT INTO zscored_features (uid, is_attack, grp, role, z_scores)
               VALUES (%s,%s,%s,%s,%s)""",
            (r.uid, bool(r.is_attack), r.grp, r.role, json.dumps(z_scores)),
        )
    conn.commit()
    print(f"  zscored_features: {len(df)} rows ({len(z_cols)} z-score columns)")


def populate_weekly_trajectories(conn):
    path = TIER3_DIR / "all250_trajectories.csv"
    if not path.exists():
        print(f"  SKIP weekly_trajectories: {path} not found")
        return
    df = pd.read_csv(path)
    cur = conn.cursor()
    cur.execute("DELETE FROM weekly_trajectories")
    cols = [
        "user_id", "is_attack", "department", "role", "week_idx",
        "week_start", "week_end", "identity_drift", "access_pattern_drift",
        "data_behavior_drift", "network_footprint_drift", "risk_posture_drift",
        "composite_drift", "velocity", "acceleration", "week_to_week_drift",
        "composite_drift_normal_ops", "composite_drift_insider_investigation",
        "composite_drift_apt_hunt", "composite_drift_privilege_audit",
        "relationship_drift", "zone_divergence",
    ]
    placeholders = ",".join(["%s"] * len(cols))
    col_names = ",".join(cols)
    batch = []
    for _, r in df.iterrows():
        vals = []
        for c in cols:
            v = r.get(c)
            if c == "is_attack":
                vals.append(bool(v))
            elif c in ("user_id", "department", "role", "week_start", "week_end"):
                vals.append(str(v) if pd.notna(v) else None)
            elif c == "week_idx":
                vals.append(int(v))
            else:
                vals.append(float(v) if pd.notna(v) else None)
        batch.append(tuple(vals))
        if len(batch) >= 1000:
            cur.executemany(
                f"INSERT INTO weekly_trajectories ({col_names}) VALUES ({placeholders})",
                batch,
            )
            batch = []
    if batch:
        cur.executemany(
            f"INSERT INTO weekly_trajectories ({col_names}) VALUES ({placeholders})",
            batch,
        )
    conn.commit()
    print(f"  weekly_trajectories: {len(df)} rows")


def populate_weekly_features(conn):
    path = COMP_DIR / "weekly_features.csv"
    if not path.exists():
        print(f"  SKIP weekly_features: {path} not found")
        return
    df = pd.read_csv(path)
    cur = conn.cursor()
    cur.execute("DELETE FROM weekly_features")
    meta_cols = {"user_id", "week_idx", "week_start", "week_end"}
    feat_cols = [c for c in df.columns if c not in meta_cols]
    batch = []
    for _, r in df.iterrows():
        features = {c: float(r[c]) for c in feat_cols if pd.notna(r[c])}
        batch.append((
            r.user_id, int(r.week_idx),
            str(r.get("week_start")) if pd.notna(r.get("week_start")) else None,
            str(r.get("week_end")) if pd.notna(r.get("week_end")) else None,
            json.dumps(features),
        ))
        if len(batch) >= 1000:
            cur.executemany(
                "INSERT INTO weekly_features (user_id, week_idx, week_start, week_end, features) "
                "VALUES (%s,%s,%s,%s,%s)", batch,
            )
            batch = []
    if batch:
        cur.executemany(
            "INSERT INTO weekly_features (user_id, week_idx, week_start, week_end, features) "
            "VALUES (%s,%s,%s,%s,%s)", batch,
        )
    conn.commit()
    print(f"  weekly_features: {len(df)} rows ({len(feat_cols)} feature columns)")


def _safe_float(row, col):
    v = row.get(col)
    return float(v) if pd.notna(v) else None


def _safe_bool(row, col):
    v = row.get(col)
    return bool(v) if pd.notna(v) else False


def _safe_val(v):
    if isinstance(v, (int, float)):
        return v
    return str(v) if pd.notna(v) else None


def populate_alerts(conn):
    path = Path("data/pipeline_results/alerts.json")
    if not path.exists():
        print(f"  SKIP alerts: {path} not found")
        return
    with open(path) as f:
        data = json.load(f)
    cur = conn.cursor()
    cur.execute("DELETE FROM alerts")
    for r in data:
        cur.execute(
            """INSERT INTO alerts
               (id, entity_type, entity_id, severity, title, description,
                drift_magnitude, concept_alignments, mitre_techniques,
                detected_at, status, detection_method, confidence, kill_chain_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (r["id"], r.get("entity_type", "user"), r["entity_id"],
             r.get("severity", "medium"), r.get("title", ""),
             r.get("description", ""),
             float(r["drift_magnitude"]) if r.get("drift_magnitude") else None,
             json.dumps(r.get("concept_alignments", [])),
             json.dumps(r.get("mitre_techniques", [])),
             r.get("detected_at"), r.get("status", "new"),
             r.get("detection_method"), float(r["confidence"]) if r.get("confidence") else None,
             r.get("kill_chain_id")),
        )
    conn.commit()
    print(f"  alerts: {len(data)} rows")


def populate_kill_chains(conn):
    path = Path("data/pipeline_results/kill_chains.json")
    if not path.exists():
        print(f"  SKIP kill_chains: {path} not found")
        return
    with open(path) as f:
        data = json.load(f)
    cur = conn.cursor()
    cur.execute("DELETE FROM kill_chain_events")
    cur.execute("DELETE FROM kill_chains")
    for kc in data:
        cur.execute(
            """INSERT INTO kill_chains
               (id, created_at, status, severity, duration_seconds,
                tactics_observed, entities_involved)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (kc["id"], kc.get("created_at"), kc.get("status", "active"),
             kc.get("severity", "medium"),
             float(kc["duration_seconds"]) if kc.get("duration_seconds") else None,
             json.dumps(kc.get("tactics_observed", [])),
             json.dumps(kc.get("entities_involved", []))),
        )
        for i, evt in enumerate(kc.get("events", [])):
            cur.execute(
                """INSERT INTO kill_chain_events
                   (kill_chain_id, alert_id, entity_type, entity_id,
                    timestamp, tactic, techniques, description, confidence, event_order)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (kc["id"], evt.get("alert_id"), evt.get("entity_type", "user"),
                 evt["entity_id"], evt.get("timestamp"), evt.get("tactic"),
                 json.dumps(evt.get("techniques", [])),
                 evt.get("description"),
                 float(evt["confidence"]) if evt.get("confidence") else None,
                 i),
            )
    conn.commit()
    total_events = sum(len(kc.get("events", [])) for kc in data)
    print(f"  kill_chains: {len(data)} chains, {total_events} events")


def populate_log_stats(conn):
    generated_dir = Path("data/generated")
    if not generated_dir.exists():
        print(f"  SKIP log_stats: {generated_dir} not found")
        return
    cur = conn.cursor()
    cur.execute("DELETE FROM log_stats")
    log_types = ["auth", "network", "dns", "endpoint", "file_access", "app", "privilege"]
    count = 0
    for lt in log_types:
        log_dir = generated_dir / lt
        if not log_dir.exists():
            continue
        csvs = list(log_dir.glob("*.csv"))
        total_rows = 0
        for csv_path in csvs[:5]:
            try:
                total_rows += sum(1 for _ in open(csv_path, encoding="utf-8")) - 1
            except Exception:
                pass
        est_total = total_rows * len(csvs) // max(min(5, len(csvs)), 1) if csvs else 0
        cur.execute(
            "INSERT INTO log_stats (source, file_count, sample_rows, est_total_events) "
            "VALUES (%s,%s,%s,%s)",
            (lt, len(csvs), total_rows, est_total),
        )
        count += 1
    conn.commit()
    print(f"  log_stats: {count} sources")


def populate_drift_series(conn):
    path = Path("data/pipeline_results/drift_series.csv")
    if not path.exists():
        print(f"  SKIP drift_series: {path} not found")
        return
    df = pd.read_csv(path)
    cur = conn.cursor()
    cur.execute("DELETE FROM drift_series")
    batch = []
    for _, r in df.iterrows():
        batch.append((
            r.get("entity_type", "user"), r["entity_id"],
            str(r["cutoff_date"])[:10] if pd.notna(r.get("cutoff_date")) else None,
            float(r["drift_from_first"]) if pd.notna(r.get("drift_from_first")) else None,
        ))
        if len(batch) >= 1000:
            cur.executemany(
                "INSERT INTO drift_series (entity_type, entity_id, cutoff_date, drift_from_first) "
                "VALUES (%s,%s,%s,%s)", batch,
            )
            batch = []
    if batch:
        cur.executemany(
            "INSERT INTO drift_series (entity_type, entity_id, cutoff_date, drift_from_first) "
            "VALUES (%s,%s,%s,%s)", batch,
        )
    conn.commit()
    print(f"  drift_series: {len(df)} rows")


def main():
    print("Populating dashboard tables from CSV/JSON files...")
    conn = get_connection()
    try:
        populate_composite_scores(conn)
        populate_detection_results(conn)
        populate_novelty_metrics(conn)
        populate_zscored_features(conn)
        populate_weekly_trajectories(conn)
        populate_weekly_features(conn)
        populate_alerts(conn)
        populate_kill_chains(conn)
        populate_log_stats(conn)
        populate_drift_series(conn)
        print("\nDone. All dashboard tables populated.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
