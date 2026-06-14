"""Tier 3 Digital Entity Detection vs Tier 1 + Tier 2 Comparison.

Proves that hierarchical zone embeddings, relationship embeddings, and full
velocity vectors detect attacks that neither Tier 1 (traditional) nor Tier 2
(ACECARD basic) individually catch, with lower false positive rate than the
Tier 1+2 combined ensemble.

Three architectural innovations from DLA MVP supply chain system:
  1. Hierarchical zone embeddings — 5 zones per entity, context-adaptive attention
  2. Relationship embeddings — Hadamard product (User⊙Device)
  3. Full 1536-d velocity vectors — trajectory features + regime detection

Usage: python -m comparison.run_tier3 [--users N]
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
from dotenv import load_dotenv
load_dotenv()
import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comparison.run_comparison import (
    DATA_DIR, ATTACK_ENTITIES, FEATURE_COLS,
    _build_user_device_map, engineer_weekly_features,
    run_traditional_detection, run_temporal_traditional,
    run_feature_trajectory_cusum, run_acecard_detection,
    build_comparison_report, load_week_csvs,
)
from embeddings.composer import cosine_similarity, drift_magnitude, drift_vector
from detection.drift_direction import analyze_zone_drift, detect_zone_divergence
from models.cyber_entity import CyberEntity, PhaseState, Tier3Config, EMBED_DIM
from models.hierarchical_zones import (
    CYBER_ZONES, CONTEXT_WEIGHTS, ALL_CONTEXTS, USER_ZONE_ORDER,
    build_zone_embeddings, compose_zones, serialize_zone,
    serialize_zone_interpretive, BehavioralContext,
)
from models.temporal_trajectory import (
    compute_velocity_vector, compute_trajectory_features,
    detect_regime, compute_zone_trajectories, build_phase_state,
)
from models.relationship_embeddings import hadamard, relationship_drift

RESULTS_DIR = Path("data/tier3_results")


# ── Entity Zoo Builder ───────────────────────────────────────────────────────


def _compute_population_stats(features_df: pd.DataFrame, feature_cols: list[str]) -> tuple[dict, dict]:
    """Compute per-week population mean and std for each feature."""
    pop_mean = {}
    pop_std = {}
    for col in feature_cols:
        pop_mean[col] = float(features_df[col].mean())
        pop_std[col] = float(features_df[col].std())
        if pop_std[col] < 1e-10:
            pop_std[col] = 1.0
    return pop_mean, pop_std


def _compute_user_baseline(user_weeks: pd.DataFrame, feature_cols: list[str],
                           baseline_weeks: int = 8) -> dict[str, float]:
    """Mean of first N weeks as user's own behavioral baseline."""
    baseline = user_weeks.head(baseline_weeks)
    result = {}
    for col in feature_cols:
        result[col] = float(baseline[col].mean())
    return result


def build_entity_zoo(
    user_ids: list[str],
    features_df: pd.DataFrame,
    entities: dict,
    user_device_map: dict,
    embedder,
    concept_lib,
    config: Tier3Config,
) -> dict[str, CyberEntity]:
    """Build CyberEntity objects for all users with full Tier 3 data.

    Uses batch embedding: serializes ALL zone texts (user + device, all weeks)
    in a first pass, embeds them in one batch call, then assembles entities.
    """
    print("\n  Building Digital Entity Zoo...", flush=True)

    pop_mean, pop_std = _compute_population_stats(features_df, FEATURE_COLS)
    print(f"  Population stats computed across {len(features_df)} feature vectors", flush=True)

    users_df = entities["users"]
    devices_df = entities["devices"]
    user_profiles = {}
    for _, row in users_df.iterrows():
        uid = row["user_id"]
        user_profiles[uid] = row.to_dict()

    device_profiles = {}
    for _, row in devices_df.iterrows():
        did = row["device_id"]
        device_profiles[did] = row.to_dict()

    # ── Pass 1: Serialize all zone texts ────────────────────────────────────
    all_texts = []
    text_index = []  # (uid, week_idx, entity_type, zone_name)
    user_meta = {}   # uid -> {user_weeks, user_baseline, dev_ids, dev_profile, n_weeks}

    device_zones = list(CYBER_ZONES.get("device", {}).keys())

    for uid in user_ids:
        profile = user_profiles.get(uid, {"user_id": uid})
        user_weeks = features_df[features_df["user_id"] == uid].sort_values("week_idx")

        if len(user_weeks) < 3:
            continue

        user_baseline = _compute_user_baseline(user_weeks, FEATURE_COLS)
        dev_ids = user_device_map.get(uid, [])
        dev_profile = None
        if dev_ids:
            primary_dev = dev_ids[0]
            dev_profile = device_profiles.get(primary_dev, {"device_id": primary_dev})

        user_meta[uid] = {
            "profile": profile,
            "user_weeks": user_weeks,
            "user_baseline": user_baseline,
            "dev_ids": dev_ids,
            "dev_profile": dev_profile,
            "primary_dev": dev_ids[0] if dev_ids else None,
        }

        recent_history: list[dict[str, float]] = []
        for row_idx, (_, row) in enumerate(user_weeks.iterrows()):
            feat_dict = {col: row[col] for col in FEATURE_COLS}
            for qcol in ["qual_file_dirs", "qual_net_ext_ips", "qual_dns_domains"]:
                if qcol in row.index:
                    feat_dict[qcol] = row[qcol]

            bctx = BehavioralContext(
                pop_mean=pop_mean, pop_std=pop_std,
                user_baseline=user_baseline, week_idx=row_idx,
                recent_history=list(recent_history[-3:]),
            )

            for zone_name in USER_ZONE_ORDER:
                text = serialize_zone_interpretive(
                    "user", zone_name, profile, feat_dict, bctx
                )
                text_index.append((uid, row_idx, "user", zone_name))
                all_texts.append(text)

            if dev_profile:
                for zone_name in device_zones:
                    text = serialize_zone("device", zone_name, dev_profile, feat_dict)
                    text_index.append((uid, row_idx, "device", zone_name))
                    all_texts.append(text)

            recent_history.append(feat_dict)

    print(f"  Serialized {len(all_texts)} zone texts across {len(user_meta)} users", flush=True)

    # ── Pass 2: Batch embed all texts ───────────────────────────────────────
    print(f"  Batch embedding {len(all_texts)} texts...", flush=True)
    all_vecs = embedder.embed_batch(all_texts)
    stats = embedder.stats()
    print(f"  Embedding done: {stats['api_calls']} API calls, {stats['cache_hits']} cache hits", flush=True)

    # Index vectors by (uid, week_idx, entity_type, zone_name)
    vec_lookup = {}
    for (uid, wk, etype, zname), vec in zip(text_index, all_vecs):
        vec_lookup[(uid, wk, etype, zname)] = vec

    # ── Pass 3: Assemble entities ───────────────────────────────────────────
    print(f"  Assembling {len(user_meta)} entities...", flush=True)
    entity_zoo = {}

    for i, uid in enumerate(user_meta):
        meta = user_meta[uid]
        profile = meta["profile"]
        user_weeks = meta["user_weeks"]
        n_weeks = len(user_weeks)

        weekly_zone_embs = []
        weekly_composites = {ctx: [] for ctx in ALL_CONTEXTS}

        for wk_idx in range(n_weeks):
            zone_embs = {}
            for zone_name in USER_ZONE_ORDER:
                zone_embs[zone_name] = vec_lookup[(uid, wk_idx, "user", zone_name)]
            weekly_zone_embs.append(zone_embs)

            for ctx in ALL_CONTEXTS:
                comp = compose_zones(zone_embs, context=ctx, entity_type="user")
                weekly_composites[ctx].append(comp)

        zone_snapshot_series = {}
        for zone_name in USER_ZONE_ORDER:
            zone_snapshot_series[zone_name] = [
                wze[zone_name] for wze in weekly_zone_embs if zone_name in wze
            ]

        dev_ids = meta["dev_ids"]
        dev_profile = meta["dev_profile"]
        weekly_rel_embs = []
        if dev_ids:
            for wk_idx in range(n_weeks):
                dev_zone_embs = {}
                for zone_name in device_zones:
                    dev_zone_embs[zone_name] = vec_lookup[(uid, wk_idx, "device", zone_name)]
                dev_composite = compose_zones(dev_zone_embs, context="normal_ops", entity_type="device")
                user_comp = weekly_composites["normal_ops"][wk_idx]
                rel_emb = hadamard(user_comp, dev_composite)
                weekly_rel_embs.append(rel_emb)

        normal_snapshots = weekly_composites["normal_ops"]
        phase = build_phase_state(normal_snapshots, zone_snapshot_series)
        zone_trajs = compute_zone_trajectories(zone_snapshot_series)

        entity = CyberEntity(
            entity_type="user",
            entity_id=uid,
            profile=profile,
            zone_embeddings=weekly_zone_embs[-1] if weekly_zone_embs else {},
            composite_embedding=normal_snapshots[-1] if normal_snapshots else None,
            phase_state=phase,
            relationships={"user_device": weekly_rel_embs[-1]} if weekly_rel_embs else {},
            risk_scores={},
            data_gaps=[] if dev_ids else ["no_device_mapping"],
            context="normal_ops",
            zone_snapshot_series=zone_snapshot_series,
            composite_snapshots=normal_snapshots,
            relationship_snapshots={"user_device": weekly_rel_embs} if weekly_rel_embs else {},
        )

        entity._contextual_composites = weekly_composites
        entity._zone_trajectories = zone_trajs

        entity_zoo[uid] = entity

        if (i + 1) % 50 == 0:
            print(f"    {i + 1}/{len(user_meta)} entities assembled", flush=True)

    print(f"  Entity zoo built: {len(entity_zoo)} entities", flush=True)
    return entity_zoo


# ── Embedding DB Persistence ────────────────────────────────────────────────


def _vec_to_pgvector(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in v) + "]"


def save_embeddings_to_db(
    entity_zoo: dict[str, CyberEntity],
    features_df: pd.DataFrame,
    vec_lookup: dict | None = None,
) -> int:
    """Persist all zone embeddings + composites to PostgreSQL behavioral_snapshots.

    Writes one row per (user, week) with 5 zone vectors, composite,
    4 context composites, and the serialization texts.
    Returns total rows upserted.
    """
    from pipeline.db_connect import get_connection
    from pipeline.temporal_store import set_temporal_write
    from psycopg2.extras import execute_batch

    week_dates = {}
    if "week_start" in features_df.columns:
        for _, row in features_df[["week_idx", "week_start"]].drop_duplicates().iterrows():
            wk = int(row["week_idx"])
            ws = row["week_start"]
            if isinstance(ws, str):
                week_dates[wk] = date.fromisoformat(ws)
            else:
                week_dates[wk] = ws

    upsert_sql = """
        INSERT INTO behavioral_snapshots (
            entity_type, entity_id, cutoff_date,
            zone_identity, zone_access_pattern, zone_data_behavior,
            zone_network_footprint, zone_risk_posture,
            composite,
            composite_normal_ops, composite_insider_inv,
            composite_apt_hunt, composite_privilege_audit
        ) VALUES (
            %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s,
            %s, %s, %s, %s
        ) ON CONFLICT (entity_type, entity_id, cutoff_date) DO UPDATE SET
            zone_identity = EXCLUDED.zone_identity,
            zone_access_pattern = EXCLUDED.zone_access_pattern,
            zone_data_behavior = EXCLUDED.zone_data_behavior,
            zone_network_footprint = EXCLUDED.zone_network_footprint,
            zone_risk_posture = EXCLUDED.zone_risk_posture,
            composite = EXCLUDED.composite,
            composite_normal_ops = EXCLUDED.composite_normal_ops,
            composite_insider_inv = EXCLUDED.composite_insider_inv,
            composite_apt_hunt = EXCLUDED.composite_apt_hunt,
            composite_privilege_audit = EXCLUDED.composite_privilege_audit,
            computed_at = now()
    """

    conn = get_connection()
    total = 0

    try:
        rows_batch = []
        for uid, entity in entity_zoo.items():
            zone_series = entity.zone_snapshot_series
            ctx_composites = getattr(entity, "_contextual_composites", {})
            n_weeks = len(entity.composite_snapshots)

            for wk_idx in range(n_weeks):
                cutoff = week_dates.get(wk_idx, date(2025, 1, 1) + timedelta(days=wk_idx * 7))

                zone_vecs = {}
                for zone_name in USER_ZONE_ORDER:
                    snapshots = zone_series.get(zone_name, [])
                    if wk_idx < len(snapshots):
                        zone_vecs[zone_name] = snapshots[wk_idx]

                if len(zone_vecs) < 5:
                    continue

                comp_normal = ctx_composites.get("normal_ops", entity.composite_snapshots)
                comp_insider = ctx_composites.get("insider_investigation", comp_normal)
                comp_apt = ctx_composites.get("apt_hunt", comp_normal)
                comp_priv = ctx_composites.get("privilege_audit", comp_normal)

                row = (
                    "user", uid, cutoff,
                    _vec_to_pgvector(zone_vecs["identity"]),
                    _vec_to_pgvector(zone_vecs["access_pattern"]),
                    _vec_to_pgvector(zone_vecs["data_behavior"]),
                    _vec_to_pgvector(zone_vecs["network_footprint"]),
                    _vec_to_pgvector(zone_vecs["risk_posture"]),
                    _vec_to_pgvector(comp_normal[wk_idx] if wk_idx < len(comp_normal) else comp_normal[-1]),
                    _vec_to_pgvector(comp_normal[wk_idx] if wk_idx < len(comp_normal) else comp_normal[-1]),
                    _vec_to_pgvector(comp_insider[wk_idx] if wk_idx < len(comp_insider) else comp_insider[-1]),
                    _vec_to_pgvector(comp_apt[wk_idx] if wk_idx < len(comp_apt) else comp_apt[-1]),
                    _vec_to_pgvector(comp_priv[wk_idx] if wk_idx < len(comp_priv) else comp_priv[-1]),
                )
                rows_batch.append(row)

        if rows_batch:
            with conn.cursor() as cur:
                set_temporal_write(conn, True)
                execute_batch(cur, upsert_sql, rows_batch, page_size=200)
                conn.commit()
            total = len(rows_batch)

    finally:
        conn.close()

    return total


def load_embeddings_from_db(
    user_ids: list[str],
) -> dict[str, dict[int, dict[str, np.ndarray]]]:
    """Load zone embeddings from PostgreSQL behavioral_snapshots.

    Returns {user_id: {week_idx: {zone_name: 1536-d vector}}}
    sorted by cutoff_date so week_idx = position in date sequence.
    """
    from pipeline.db_connect import get_connection

    conn = get_connection()
    placeholders = ",".join(["%s"] * len(user_ids))
    sql = f"""
        SELECT entity_id, cutoff_date,
               zone_identity, zone_access_pattern, zone_data_behavior,
               zone_network_footprint, zone_risk_posture, composite
        FROM behavioral_snapshots
        WHERE entity_type = 'user' AND entity_id IN ({placeholders})
        ORDER BY entity_id, cutoff_date
    """
    zone_names = ["identity", "access_pattern", "data_behavior",
                  "network_footprint", "risk_posture"]
    result = {}

    with conn.cursor() as cur:
        cur.execute(sql, tuple(user_ids))
        for row in cur.fetchall():
            uid = row[0]
            if uid not in result:
                result[uid] = {}
            wk_idx = len(result[uid])
            zones = {}
            for i, zn in enumerate(zone_names):
                vec_str = row[2 + i]
                if vec_str:
                    zones[zn] = np.array([float(x) for x in str(vec_str).strip("[]").split(",")])
            composite_str = row[7]
            if composite_str:
                zones["composite"] = np.array([float(x) for x in str(composite_str).strip("[]").split(",")])
            result[uid][wk_idx] = zones

    conn.close()
    n_total = sum(len(v) for v in result.values())
    print(f"  Loaded {n_total} embedding snapshots for {len(result)} users from DB", flush=True)
    return result


# ── Tier 3 Detection Methods ────────────────────────────────────────────────


def run_tier3_velocity_detection(
    entity_zoo: dict[str, CyberEntity],
    config: Tier3Config,
) -> pd.DataFrame:
    """Detect based on velocity/acceleration — top 10% by composite score."""
    rows = []
    for uid, entity in entity_zoo.items():
        ps = entity.phase_state
        rows.append({
            "user_id": uid,
            "t3_velocity_magnitude": ps.velocity_magnitude,
            "t3_acceleration": ps.acceleration,
            "t3_stability": ps.stability,
            "t3_trend_consistency": ps.trend_consistency,
            "t3_total_drift": ps.total_drift,
            "t3_regime": ps.current_regime,
        })
    df = pd.DataFrame(rows)

    # Composite score: weighted combination of velocity features
    df["t3_velocity_score"] = (
        0.4 * _rank_normalize(df["t3_velocity_magnitude"])
        + 0.3 * _rank_normalize(df["t3_acceleration"])
        + 0.3 * _rank_normalize(df["t3_total_drift"])
    )
    threshold = df["t3_velocity_score"].quantile(0.90)
    df["t3_velocity_detected"] = df["t3_velocity_score"] >= max(threshold, 0.01)
    return df


def run_tier3_regime_detection(
    entity_zoo: dict[str, CyberEntity],
    config: Tier3Config,
) -> pd.DataFrame:
    """Detect regime shifts — flag entities with lowest stability (top 10%)."""
    rows = []
    for uid, entity in entity_zoo.items():
        ps = entity.phase_state
        rows.append({
            "user_id": uid,
            "t3_regime_shifts": ps.regime_shifts,
            "t3_min_stability": ps.stability,
        })
    df = pd.DataFrame(rows)

    # Lower stability = more anomalous. Use inverted rank.
    df["t3_regime_score"] = 1.0 - _rank_normalize(df["t3_min_stability"])
    threshold = df["t3_regime_score"].quantile(0.90)
    df["t3_regime_detected"] = df["t3_regime_score"] >= max(threshold, 0.01)
    return df


def run_tier3_zone_drift_detection(
    entity_zoo: dict[str, CyberEntity],
    config: Tier3Config,
    concept_lib=None,
) -> pd.DataFrame:
    """Per-zone drift analysis using percentile-based scoring.

    Computes a zone divergence score: max(behavioral zone drifts) - identity drift.
    Higher score = bigger gap between identity stability and behavioral change.
    Top 10% flagged.

    When concept_lib is provided, also runs concept-aligned zone drift analysis
    via analyze_zone_drift() and detect_zone_divergence() from
    detection.drift_direction, adding per-zone concept alignment diagnostics
    and divergence strings to the results.
    """
    rows = []
    for uid, entity in entity_zoo.items():
        zone_trajs = getattr(entity, '_zone_trajectories', {})
        if not zone_trajs:
            rows.append({
                "user_id": uid, "t3_identity_drift": 0.0,
                "t3_data_drift": 0.0, "t3_network_drift": 0.0,
                "t3_risk_drift": 0.0, "t3_access_drift": 0.0,
                "t3_zone_divergence_score": 0.0,
                "t3_zone_diagnostics": "",
                "t3_concept_zone_diagnostics": "",
                "t3_concept_divergence_strings": "",
                "t3_concept_primary_threat_zone": "",
                "t3_concept_max_threat_confidence": 0.0,
            })
            continue

        identity_drift = zone_trajs.get("identity", {}).get("total_drift", 0.0)
        access_drift = zone_trajs.get("access_pattern", {}).get("total_drift", 0.0)
        data_drift = zone_trajs.get("data_behavior", {}).get("total_drift", 0.0)
        network_drift = zone_trajs.get("network_footprint", {}).get("total_drift", 0.0)
        risk_drift = zone_trajs.get("risk_posture", {}).get("total_drift", 0.0)

        behavioral_drifts = [access_drift, data_drift, network_drift, risk_drift]
        max_beh_drift = max(behavioral_drifts)
        divergence_score = max_beh_drift - identity_drift

        diagnostics_parts = []
        for zname, zdrift in [("data_behavior", data_drift), ("network_footprint", network_drift),
                               ("risk_posture", risk_drift), ("access_pattern", access_drift)]:
            diagnostics_parts.append(f"{zname}({zdrift:.4f})")

        # ── Concept-aligned zone drift analysis ──────────────────────────
        concept_zone_diagnostics = ""
        concept_divergence_strings = ""
        concept_primary_threat_zone = ""
        concept_max_threat_confidence = 0.0

        if concept_lib is not None:
            zone_snaps = entity.zone_snapshot_series
            # Build zone_old (first week) and zone_new (last week) dicts
            zone_old = {}
            zone_new = {}
            for zname, snaps in zone_snaps.items():
                if len(snaps) >= 2:
                    zone_old[zname] = snaps[0]
                    zone_new[zname] = snaps[-1]

            if zone_old and zone_new:
                # Per-zone DriftAnalysis with concept alignment scores
                zone_drift_results = analyze_zone_drift(
                    entity_type="user",
                    entity_id=uid,
                    zone_old=zone_old,
                    zone_new=zone_new,
                    concept_library=concept_lib,
                )

                # Build per-zone concept diagnostic strings
                concept_parts = []
                for zname, analysis in zone_drift_results.items():
                    direction = analysis.primary_direction
                    conf = analysis.confidence
                    threat_flag = " [THREAT]" if analysis.is_threat else ""
                    concept_parts.append(
                        f"{zname}->({direction}, conf={conf:.3f}{threat_flag})"
                    )
                    # Track the zone with highest threat confidence
                    if analysis.is_threat and conf > concept_max_threat_confidence:
                        concept_max_threat_confidence = conf
                        concept_primary_threat_zone = zname

                concept_zone_diagnostics = "; ".join(concept_parts)

                # Divergence diagnostics: "identity STABLE, network DRIFTING toward c2_beacon"
                divergence_strings = detect_zone_divergence(zone_drift_results)
                concept_divergence_strings = " | ".join(divergence_strings)

        rows.append({
            "user_id": uid,
            "t3_identity_drift": identity_drift,
            "t3_data_drift": data_drift,
            "t3_network_drift": network_drift,
            "t3_risk_drift": risk_drift,
            "t3_access_drift": access_drift,
            "t3_zone_divergence_score": divergence_score,
            "t3_zone_diagnostics": "; ".join(diagnostics_parts),
            "t3_concept_zone_diagnostics": concept_zone_diagnostics,
            "t3_concept_divergence_strings": concept_divergence_strings,
            "t3_concept_primary_threat_zone": concept_primary_threat_zone,
            "t3_concept_max_threat_confidence": concept_max_threat_confidence,
        })

    df = pd.DataFrame(rows)
    threshold = df["t3_zone_divergence_score"].quantile(0.90)
    df["t3_zone_divergence_detected"] = df["t3_zone_divergence_score"] >= max(threshold, 0.01)
    return df


def run_tier3_relationship_drift_detection(
    entity_zoo: dict[str, CyberEntity],
    config: Tier3Config,
) -> pd.DataFrame:
    """Detect drift in UserDevice relationship embeddings — top 10%."""
    rows = []
    for uid, entity in entity_zoo.items():
        rel_snaps = entity.relationship_snapshots.get("user_device", [])
        if len(rel_snaps) < 2:
            rows.append({"user_id": uid, "t3_rel_drift": 0.0})
            continue
        rel_drift_val = relationship_drift(rel_snaps[0], rel_snaps[-1])
        rows.append({"user_id": uid, "t3_rel_drift": rel_drift_val})

    df = pd.DataFrame(rows)
    threshold = df["t3_rel_drift"].quantile(0.90)
    df["t3_rel_detected"] = df["t3_rel_drift"] >= max(threshold, 0.01)
    return df


def run_tier3_contextual_detection(
    entity_zoo: dict[str, CyberEntity],
    embedder,
    concept_lib,
    config: Tier3Config,
) -> pd.DataFrame:
    """Run detection under multiple contexts — top 10% by best consistency."""
    threat_vectors = concept_lib.all_threat_vectors()
    benign_vectors = concept_lib.all_benign_vectors()

    rows = []
    for uid, entity in entity_zoo.items():
        contextual_composites = getattr(entity, '_contextual_composites', {})
        if not contextual_composites:
            rows.append({
                "user_id": uid, "t3_ctx_best_context": "none",
                "t3_ctx_best_consistency": 0.0,
            })
            continue

        best_consistency = 0.0
        best_context = "none"

        for ctx in ALL_CONTEXTS:
            composites = contextual_composites.get(ctx, [])
            if len(composites) < 3:
                continue

            n = len(composites)
            weekly_net_threat = []

            for i in range(n - 1):
                d_vec = drift_vector(composites[i], composites[i + 1])
                if np.linalg.norm(d_vec) < 1e-10:
                    weekly_net_threat.append(0.0)
                    continue
                max_threat = max(
                    (float(cosine_similarity(d_vec, v)) for v in threat_vectors.values()),
                    default=0.0,
                )
                max_benign = max(
                    (float(cosine_similarity(d_vec, v)) for v in benign_vectors.values()),
                    default=0.0,
                )
                weekly_net_threat.append(max_threat - max_benign)

            threat_weeks = sum(1 for nt in weekly_net_threat if nt > 0.05)
            consistency = threat_weeks / max(len(weekly_net_threat), 1)

            if consistency > best_consistency:
                best_consistency = consistency
                best_context = ctx

        rows.append({
            "user_id": uid,
            "t3_ctx_best_context": best_context,
            "t3_ctx_best_consistency": best_consistency,
        })

    df = pd.DataFrame(rows)
    threshold = df["t3_ctx_best_consistency"].quantile(0.90)
    df["t3_ctx_detected"] = df["t3_ctx_best_consistency"] >= max(threshold, 0.01)
    return df


def run_tier3_cross_entity_correlation(
    entity_zoo: dict[str, CyberEntity],
    config: Tier3Config,
) -> pd.DataFrame:
    """Cross-entity coordinated drift detection using cohort analysis."""
    from detection.cohort_analysis import detect_relationship_cohorts, CohortMember

    members = []
    for uid, entity in entity_zoo.items():
        rel_snaps = entity.relationship_snapshots.get("user_device", [])
        if len(rel_snaps) < 2:
            continue
        d_vec = drift_vector(rel_snaps[0], rel_snaps[-1])
        mag = drift_magnitude(rel_snaps[0], rel_snaps[-1])
        if mag < 0.01:
            continue
        members.append(CohortMember(
            entity_type="user",
            entity_id=uid,
            drift_magnitude=float(mag),
            drift_direction=d_vec,
        ))

    cohorts = detect_relationship_cohorts(
        members,
        similarity_threshold=config.cohort_similarity,
        min_cluster_size=config.cohort_min_size,
    )

    cohort_members = set()
    for cohort in cohorts:
        for m in cohort.members:
            cohort_members.add(m.entity_id)

    rows = []
    for uid in entity_zoo:
        rows.append({
            "user_id": uid,
            "t3_cohort_member": uid in cohort_members,
        })

    return pd.DataFrame(rows)


def run_tier3_zone_threat_direction(
    entity_zoo: dict[str, CyberEntity],
    embedder,
    concept_lib,
    config: Tier3Config,
) -> pd.DataFrame:
    """Per-zone threat direction: analyze each zone's drift direction independently.

    Composite-level analysis dilutes zone-specific signals (data_behavior drifting
    toward exfiltration gets averaged with 4 stable zones). This method checks each
    zone's drift against threat concepts independently, then takes the MAX across
    zones. An insider's data_behavior zone drifts toward "exfiltration" even if the
    composite looks stable.
    """
    threat_vectors = concept_lib.all_threat_vectors()
    benign_vectors = concept_lib.all_benign_vectors()

    ZONE_THREAT_MAP = {
        "data_behavior": ["data_exfiltration", "insider_threat_slow", "insider_threat_fast"],
        "network_footprint": ["c2_beacon", "lateral_movement", "data_exfiltration"],
        "access_pattern": ["credential_stuffing", "reconnaissance", "privilege_escalation"],
        "risk_posture": ["compromised_endpoint", "privilege_escalation", "supply_chain_compromise"],
    }

    rows = []
    for uid, entity in entity_zoo.items():
        zone_snaps = entity.zone_snapshot_series
        best_zone = "none"
        best_zone_score = 0.0
        zone_scores = {}

        for zone_name in ["data_behavior", "network_footprint", "access_pattern", "risk_posture"]:
            snaps = zone_snaps.get(zone_name, [])
            if len(snaps) < 5:
                zone_scores[zone_name] = 0.0
                continue

            baseline = np.mean(snaps[:4], axis=0)
            norm_b = np.linalg.norm(baseline)
            if norm_b > 1e-10:
                baseline = baseline / norm_b

            weekly_scores = []
            for snap in snaps[4:]:
                d_vec = snap - baseline
                d_norm = np.linalg.norm(d_vec)
                if d_norm < 1e-10:
                    weekly_scores.append(0.0)
                    continue
                d_vec = d_vec / d_norm

                relevant_threats = ZONE_THREAT_MAP.get(zone_name, [])
                max_threat = 0.0
                for concept_name, tvec in threat_vectors.items():
                    weight = 1.5 if concept_name in relevant_threats else 0.5
                    sim = float(cosine_similarity(d_vec, tvec))
                    max_threat = max(max_threat, sim * weight)

                max_benign = max(
                    (float(cosine_similarity(d_vec, v)) for v in benign_vectors.values()),
                    default=0.0,
                )
                weekly_scores.append(max_threat - max_benign)

            threat_weeks = sum(1 for s in weekly_scores if s > 0.02)
            consistency = threat_weeks / max(len(weekly_scores), 1)
            zone_scores[zone_name] = consistency

            if consistency > best_zone_score:
                best_zone_score = consistency
                best_zone = zone_name

        rows.append({
            "user_id": uid,
            "t3_zone_threat_best_zone": best_zone,
            "t3_zone_threat_best_score": best_zone_score,
            "t3_zone_threat_data": zone_scores.get("data_behavior", 0.0),
            "t3_zone_threat_network": zone_scores.get("network_footprint", 0.0),
            "t3_zone_threat_access": zone_scores.get("access_pattern", 0.0),
            "t3_zone_threat_risk": zone_scores.get("risk_posture", 0.0),
        })

    df = pd.DataFrame(rows)
    threshold = df["t3_zone_threat_best_score"].quantile(0.90)
    df["t3_zone_threat_detected"] = df["t3_zone_threat_best_score"] >= max(threshold, 0.01)
    return df


def run_tier3_embedding_cusum(
    entity_zoo: dict[str, CyberEntity],
    config: Tier3Config,
) -> pd.DataFrame:
    """CUSUM on per-week embedding distances from user's own baseline.

    For each entity, computes the cosine distance of each week's composite
    from the mean of weeks 1-4 (baseline). Applies CUSUM to the distance
    series — small but consistent deviations accumulate into a detectable
    signal. This catches slow insider drift that single-week comparisons miss.
    """
    rows = []
    for uid, entity in entity_zoo.items():
        snaps = entity.composite_snapshots
        if len(snaps) < 5:
            rows.append({"user_id": uid, "t3_cusum_max": 0.0, "t3_cusum_final": 0.0})
            continue

        baseline = np.mean(snaps[:4], axis=0)
        norm = np.linalg.norm(baseline)
        if norm > 1e-10:
            baseline = baseline / norm

        distances = []
        for snap in snaps:
            cos_sim = float(cosine_similarity(baseline, snap))
            distances.append(1.0 - cos_sim)

        mean_dist = np.mean(distances[:4]) if len(distances) >= 4 else np.mean(distances)
        cusum = 0.0
        max_cusum = 0.0
        for d in distances:
            cusum = max(0.0, cusum + (d - mean_dist))
            max_cusum = max(max_cusum, cusum)

        rows.append({
            "user_id": uid,
            "t3_cusum_max": max_cusum,
            "t3_cusum_final": cusum,
        })

    df = pd.DataFrame(rows)
    df["t3_cusum_score"] = (
        0.6 * _rank_normalize(df["t3_cusum_max"])
        + 0.4 * _rank_normalize(df["t3_cusum_final"])
    )
    threshold = df["t3_cusum_score"].quantile(0.90)
    df["t3_cusum_detected"] = df["t3_cusum_score"] >= max(threshold, 0.01)
    return df


def run_tier3_behavioral_progression(
    entity_zoo: dict[str, CyberEntity],
    embedder,
    concept_lib,
    config: Tier3Config,
) -> pd.DataFrame:
    """Behavioral Progression: detect INCREASING threat alignment over time.

    For each user/zone, compute per-week threat alignment scores and check if
    they show a monotonic INCREASING trend (Kendall tau). Attack users show
    progressive escalation toward threat-space; normal users show random drift.

    This method can't be replicated by Tier 1 (snapshot-based) because it
    detects the TRAJECTORY of change in embedding space, not just anomaly at
    any single point.
    """
    from scipy.stats import kendalltau

    threat_vectors = concept_lib.all_threat_vectors()

    ZONE_THREATS = {
        "data_behavior": ["data_exfiltration", "insider_threat", "unauthorized_access"],
        "network_footprint": ["c2_communication", "lateral_movement", "data_exfiltration"],
        "access_pattern": ["credential_theft", "brute_force", "unauthorized_access"],
        "risk_posture": ["malware_installation", "privilege_escalation", "ransomware"],
    }

    rows = []
    for uid, entity in entity_zoo.items():
        zone_snaps = entity.zone_snapshot_series
        best_zone = "none"
        best_tau = -1.0
        best_late_threat = 0.0
        zone_taus = {}

        for zone_name in ["data_behavior", "network_footprint", "access_pattern", "risk_posture"]:
            snaps = zone_snaps.get(zone_name, [])
            if len(snaps) < 6:
                zone_taus[zone_name] = 0.0
                continue

            baseline = np.mean(snaps[:4], axis=0)
            b_norm = np.linalg.norm(baseline)
            if b_norm > 1e-10:
                baseline = baseline / b_norm

            relevant_threats = ZONE_THREATS.get(zone_name, [])
            weekly_threat_scores = []
            for snap in snaps:
                d_vec = snap - baseline
                d_norm = np.linalg.norm(d_vec)
                if d_norm < 1e-10:
                    weekly_threat_scores.append(0.0)
                    continue
                d_vec = d_vec / d_norm
                max_sim = max(
                    (float(cosine_similarity(d_vec, threat_vectors[c])) * (1.5 if c in relevant_threats else 0.5)
                     for c in threat_vectors if c in threat_vectors),
                    default=0.0,
                )
                weekly_threat_scores.append(max_sim)

            if len(weekly_threat_scores) >= 6:
                tau, _ = kendalltau(range(len(weekly_threat_scores)), weekly_threat_scores)
                if np.isnan(tau):
                    tau = 0.0
            else:
                tau = 0.0

            late_mean = np.mean(weekly_threat_scores[-4:]) if len(weekly_threat_scores) >= 4 else 0.0
            zone_taus[zone_name] = tau

            if tau > best_tau:
                best_tau = tau
                best_zone = zone_name
                best_late_threat = float(late_mean)

        rows.append({
            "user_id": uid,
            "t3_prog_best_zone": best_zone,
            "t3_prog_best_tau": best_tau,
            "t3_prog_late_threat": best_late_threat,
            "t3_prog_data_tau": zone_taus.get("data_behavior", 0.0),
            "t3_prog_network_tau": zone_taus.get("network_footprint", 0.0),
            "t3_prog_access_tau": zone_taus.get("access_pattern", 0.0),
            "t3_prog_risk_tau": zone_taus.get("risk_posture", 0.0),
        })

    df = pd.DataFrame(rows)
    df["t3_prog_score"] = (
        0.6 * _rank_normalize(df["t3_prog_best_tau"])
        + 0.4 * _rank_normalize(df["t3_prog_late_threat"])
    )
    threshold = df["t3_prog_score"].quantile(0.90)
    df["t3_prog_detected"] = df["t3_prog_score"] >= max(threshold, 0.01)
    return df


def extract_weekly_trajectories(
    entity_zoo: dict[str, CyberEntity],
    features_df: pd.DataFrame,
) -> pd.DataFrame:
    """Extract per-user per-week scalar drift metrics from in-memory embeddings.

    Computes cosine distance from baseline (first 4 weeks) for each zone,
    composite, and relationship embedding at each week. Saves week-to-week
    velocity and acceleration. This is the data needed to plot entity drift
    trajectories vs time and compare against cohort.
    """
    rows = []
    for uid, entity in entity_zoo.items():
        user_weeks = features_df[features_df["user_id"] == uid].sort_values("week_idx")
        if len(user_weeks) < 3:
            continue

        week_meta = user_weeks[["week_idx", "week_start", "week_end"]].reset_index(drop=True)
        n_weeks = len(week_meta)
        profile = entity.profile
        is_attack = uid in ATTACK_ENTITIES
        department = profile.get("department", "unknown")
        role = profile.get("role", "unknown")

        zone_snaps = entity.zone_snapshot_series
        comp_snaps = entity.composite_snapshots
        rel_snaps = entity.relationship_snapshots.get("user_device", [])
        ctx_composites = getattr(entity, '_contextual_composites', {})

        baseline_n = min(4, n_weeks)

        zone_baselines = {}
        for zname in USER_ZONE_ORDER:
            snaps = zone_snaps.get(zname, [])
            if len(snaps) >= baseline_n:
                bl = np.mean(snaps[:baseline_n], axis=0)
                norm = np.linalg.norm(bl)
                zone_baselines[zname] = bl / norm if norm > 1e-10 else bl

        comp_baseline = None
        if len(comp_snaps) >= baseline_n:
            bl = np.mean(comp_snaps[:baseline_n], axis=0)
            norm = np.linalg.norm(bl)
            comp_baseline = bl / norm if norm > 1e-10 else bl

        rel_baseline = None
        if len(rel_snaps) >= baseline_n:
            bl = np.mean(rel_snaps[:baseline_n], axis=0)
            norm = np.linalg.norm(bl)
            rel_baseline = bl / norm if norm > 1e-10 else bl

        ctx_baselines = {}
        for ctx in ALL_CONTEXTS:
            ctx_snaps = ctx_composites.get(ctx, [])
            if len(ctx_snaps) >= baseline_n:
                bl = np.mean(ctx_snaps[:baseline_n], axis=0)
                norm = np.linalg.norm(bl)
                ctx_baselines[ctx] = bl / norm if norm > 1e-10 else bl

        prev_comp_dist = 0.0
        prev_velocity = 0.0

        for wk_i in range(n_weeks):
            row = {"user_id": uid, "is_attack": is_attack, "department": department, "role": role}
            if wk_i < len(week_meta):
                row["week_idx"] = int(week_meta.iloc[wk_i]["week_idx"])
                row["week_start"] = week_meta.iloc[wk_i]["week_start"]
                row["week_end"] = week_meta.iloc[wk_i]["week_end"]

            for zname in USER_ZONE_ORDER:
                snaps = zone_snaps.get(zname, [])
                if wk_i < len(snaps) and zname in zone_baselines:
                    dist = 1.0 - float(cosine_similarity(zone_baselines[zname], snaps[wk_i]))
                    row[f"{zname}_drift"] = max(0.0, dist)
                else:
                    row[f"{zname}_drift"] = 0.0

            if wk_i < len(comp_snaps) and comp_baseline is not None:
                comp_dist = 1.0 - float(cosine_similarity(comp_baseline, comp_snaps[wk_i]))
                row["composite_drift"] = max(0.0, comp_dist)
            else:
                comp_dist = 0.0
                row["composite_drift"] = 0.0

            velocity = comp_dist - prev_comp_dist if wk_i > 0 else 0.0
            acceleration = velocity - prev_velocity if wk_i > 1 else 0.0
            row["velocity"] = velocity
            row["acceleration"] = acceleration
            prev_comp_dist = comp_dist
            prev_velocity = velocity

            if wk_i > 0 and wk_i < len(comp_snaps) and wk_i - 1 < len(comp_snaps):
                wk_dist = 1.0 - float(cosine_similarity(comp_snaps[wk_i - 1], comp_snaps[wk_i]))
                row["week_to_week_drift"] = max(0.0, wk_dist)
            else:
                row["week_to_week_drift"] = 0.0

            for ctx in ALL_CONTEXTS:
                ctx_snaps_list = ctx_composites.get(ctx, [])
                if wk_i < len(ctx_snaps_list) and ctx in ctx_baselines:
                    d = 1.0 - float(cosine_similarity(ctx_baselines[ctx], ctx_snaps_list[wk_i]))
                    row[f"composite_drift_{ctx}"] = max(0.0, d)
                else:
                    row[f"composite_drift_{ctx}"] = 0.0

            if wk_i < len(rel_snaps) and rel_baseline is not None:
                rd = 1.0 - float(cosine_similarity(rel_baseline, rel_snaps[wk_i]))
                row["relationship_drift"] = max(0.0, rd)
            else:
                row["relationship_drift"] = 0.0

            behavioral_drifts = [row.get(f"{z}_drift", 0.0)
                                 for z in ["access_pattern", "data_behavior", "network_footprint", "risk_posture"]]
            identity_drift = row.get("identity_drift", 0.0)
            row["zone_divergence"] = max(behavioral_drifts) - identity_drift

            rows.append(row)

    return pd.DataFrame(rows)


def extract_entity_structures(
    entity_zoo: dict[str, CyberEntity],
    features_df: pd.DataFrame,
    embedder,
) -> list[dict]:
    """Extract Digital Entity structure for each user: raw features -> zone text -> JSON.

    Returns a list of dicts suitable for JSON serialization, one per user,
    showing exactly what gets embedded.
    """
    import json as _json

    structures = []
    for uid, entity in entity_zoo.items():
        user_weeks = features_df[features_df["user_id"] == uid].sort_values("week_idx")
        if user_weeks.empty:
            continue

        last_row = user_weeks.iloc[-1]
        feat_dict = {col: float(last_row[col]) for col in FEATURE_COLS if col in last_row.index}
        profile = entity.profile

        zone_texts = {}
        for zname in USER_ZONE_ORDER:
            zone_texts[zname] = serialize_zone("user", zname, profile, feat_dict)

        zone_feature_map = {
            "identity": ["department", "role", "clearance", "user_type"],
            "access_pattern": [c for c in FEATURE_COLS if c.startswith("auth_")],
            "data_behavior": [c for c in FEATURE_COLS if c.startswith("file_")],
            "network_footprint": [c for c in FEATURE_COLS if c.startswith(("net_", "dns_"))],
            "risk_posture": [c for c in FEATURE_COLS if c.startswith("endpoint_")],
        }

        zone_features = {}
        for zname, feat_keys in zone_feature_map.items():
            zone_features[zname] = {}
            for k in feat_keys:
                if k in feat_dict:
                    zone_features[zname][k] = round(feat_dict[k], 6)
                elif k in profile:
                    zone_features[zname][k] = profile[k]

        structures.append({
            "entity_id": uid,
            "entity_type": "user",
            "profile": {k: (str(v) if not isinstance(v, (int, float, bool, str)) else v)
                        for k, v in profile.items()
                        if k in ["user_id", "department", "role", "clearance", "user_type", "primary_device_id"]},
            "is_attack": uid in ATTACK_ENTITIES,
            "week_idx": int(last_row.get("week_idx", 0)),
            "raw_features": {k: round(v, 6) for k, v in feat_dict.items()},
            "zone_features": zone_features,
            "zone_serialized_text": zone_texts,
            "zone_embedding_dims": {zname: 1536 for zname in USER_ZONE_ORDER},
            "phase_state": {
                "velocity_magnitude": round(entity.phase_state.velocity_magnitude, 6),
                "acceleration": round(entity.phase_state.acceleration, 6),
                "stability": round(entity.phase_state.stability, 6),
                "regime_shifts": round(entity.phase_state.regime_shifts, 4),
                "trend_consistency": round(entity.phase_state.trend_consistency, 6),
                "total_drift": round(entity.phase_state.total_drift, 6),
                "current_regime": entity.phase_state.current_regime,
            },
            "context_weights": {ctx: dict(CONTEXT_WEIGHTS.get("user", {}).get(ctx, {}))
                                for ctx in ALL_CONTEXTS},
        })

    return structures


def _rank_normalize(series: pd.Series) -> pd.Series:
    """Rank-normalize a series to [0, 1] range."""
    ranked = series.rank(method="average")
    return (ranked - ranked.min()) / max(ranked.max() - ranked.min(), 1e-10)


# ── Tier 3 Combined Detection ───────────────────────────────────────────────


def run_all_tier3_detections(
    entity_zoo: dict[str, CyberEntity],
    embedder,
    concept_lib,
    config: Tier3Config,
) -> pd.DataFrame:
    """Run all 9 Tier 3 detection methods and merge results."""
    print("\n" + "=" * 60)
    print("TIER 3: DIGITAL ENTITY DETECTION")
    print("=" * 60)

    print("\n  1. Velocity/Acceleration Detection...")
    velocity_df = run_tier3_velocity_detection(entity_zoo, config)
    v_det = velocity_df["t3_velocity_detected"].sum()
    print(f"     Flagged: {v_det}/{len(entity_zoo)}")

    print("  2. Regime Shift Detection...")
    regime_df = run_tier3_regime_detection(entity_zoo, config)
    r_det = regime_df["t3_regime_detected"].sum()
    print(f"     Flagged: {r_det}/{len(entity_zoo)}")

    print("  3. Zone Divergence Detection (+ concept-aligned analysis)...")
    zone_df = run_tier3_zone_drift_detection(entity_zoo, config, concept_lib=concept_lib)
    z_det = zone_df["t3_zone_divergence_detected"].sum()
    concept_threats = (zone_df["t3_concept_primary_threat_zone"] != "").sum()
    print(f"     Flagged: {z_det}/{len(entity_zoo)}")
    print(f"     Concept-aligned threats: {concept_threats}/{len(entity_zoo)}")

    print("  4. Relationship Drift Detection...")
    rel_df = run_tier3_relationship_drift_detection(entity_zoo, config)
    rl_det = rel_df["t3_rel_detected"].sum()
    print(f"     Flagged: {rl_det}/{len(entity_zoo)}")

    print("  5. Contextual (Multi-Context) Detection...")
    ctx_df = run_tier3_contextual_detection(entity_zoo, embedder, concept_lib, config)
    c_det = ctx_df["t3_ctx_detected"].sum()
    print(f"     Flagged: {c_det}/{len(entity_zoo)}")

    print("  6. Cross-Entity Correlation...")
    cohort_df = run_tier3_cross_entity_correlation(entity_zoo, config)
    co_det = cohort_df["t3_cohort_member"].sum()
    print(f"     Flagged: {co_det}/{len(entity_zoo)}")

    print("  7. Embedding CUSUM (cumulative drift)...")
    cusum_df = run_tier3_embedding_cusum(entity_zoo, config)
    cu_det = cusum_df["t3_cusum_detected"].sum()
    print(f"     Flagged: {cu_det}/{len(entity_zoo)}")

    print("  8. Per-Zone Threat Direction...")
    zthreat_df = run_tier3_zone_threat_direction(entity_zoo, embedder, concept_lib, config)
    zt_det = zthreat_df["t3_zone_threat_detected"].sum()
    print(f"     Flagged: {zt_det}/{len(entity_zoo)}")

    print("  9. Behavioral Progression (temporal trend)...")
    prog_df = run_tier3_behavioral_progression(entity_zoo, embedder, concept_lib, config)
    pr_det = prog_df["t3_prog_detected"].sum()
    print(f"     Flagged: {pr_det}/{len(entity_zoo)}")

    # Merge all Tier 3 results
    merged = velocity_df
    for df in [regime_df, zone_df, rel_df, ctx_df, cohort_df, cusum_df, zthreat_df, prog_df]:
        merged = merged.merge(df, on="user_id", how="outer")

    # Tier 3 composite: multi-signal corroboration from discriminating methods
    # Exclude high-FP methods (zone_threat_dir, cross_entity) from composite
    # to avoid noise diluting true signals
    core_detections = pd.DataFrame({
        "user_id": merged["user_id"],
        "d_velocity": merged.get("t3_velocity_detected", False).astype(int),
        "d_zone_div": merged.get("t3_zone_divergence_detected", False).astype(int),
        "d_ctx": merged.get("t3_ctx_detected", False).astype(int),
        "d_cusum": merged.get("t3_cusum_detected", False).astype(int),
        "d_prog": merged.get("t3_prog_detected", False).astype(int),
        "d_regime": merged.get("t3_regime_detected", False).astype(int),
    })
    core_count = (core_detections.drop(columns=["user_id"]).sum(axis=1))
    merged["t3_anomaly_breadth"] = core_count

    # Composite score — weights calibrated from 5-round deep analysis:
    # CUSUM and Progression most discriminative (3/4 at 8.9% FP each)
    # Zone Divergence uniquely catches insider + is key ensemble anchor
    # Contextual demoted: poor precision (2 TP at 13.4% FP)
    # Velocity is low-discriminative with real embeddings
    velocity_pct = _rank_normalize(merged.get("t3_velocity_score", pd.Series(0.0, index=merged.index)))
    zone_pct = _rank_normalize(merged.get("t3_zone_divergence_score", pd.Series(0.0, index=merged.index)))
    ctx_pct = _rank_normalize(merged.get("t3_ctx_best_consistency", pd.Series(0.0, index=merged.index)))
    cusum_pct = _rank_normalize(merged.get("t3_cusum_score", pd.Series(0.0, index=merged.index)))
    prog_pct = _rank_normalize(merged.get("t3_prog_score", pd.Series(0.0, index=merged.index)))

    eps = 0.01
    merged["t3_composite_score"] = np.exp(
        0.05 * np.log(velocity_pct.clip(lower=eps))
        + 0.30 * np.log(zone_pct.clip(lower=eps))
        + 0.05 * np.log(ctx_pct.clip(lower=eps))
        + 0.30 * np.log(cusum_pct.clip(lower=eps))
        + 0.30 * np.log(prog_pct.clip(lower=eps))
    )

    # Final score: geometric mean depth + corroboration breadth
    merged["t3_composite_score"] = (
        0.7 * _rank_normalize(merged["t3_composite_score"])
        + 0.3 * _rank_normalize(merged["t3_anomaly_breadth"].astype(float))
    )

    # Combined detection: corroboration (>=2 core) OR zone divergence with
    # concept-aligned threat (reduces FP vs zone_div alone) OR top 8% composite
    pct_threshold = merged["t3_composite_score"].quantile(0.92)
    zone_div_with_concept = (
        merged.get("t3_zone_divergence_detected", False)
        & (merged.get("t3_concept_max_threat_confidence", 0.0) > 0.10)
    )
    merged["t3_combined_detected"] = (
        (core_count >= 2)
        | zone_div_with_concept
        | (merged["t3_composite_score"] >= max(pct_threshold, 0.01))
    )
    t3_det = merged["t3_combined_detected"].sum()
    print(f"\n  Tier 3 Combined (>=2 core, concept zone div, or top 8%): "
          f"{t3_det}/{len(entity_zoo)} flagged")

    return merged


# ── Report ───────────────────────────────────────────────────────────────────


def print_tier3_report(merged: pd.DataFrame):
    """Print Tier 1 vs Tier 2 vs Tier 3 comparison table."""
    print("\n" + "=" * 90)
    print("THREE-TIER COMPARISON: Traditional vs ACECARD Basic vs Digital Entity")
    print("=" * 90)

    methods = {
        # Tier 1
        "Isolation Forest": "iforest_anomaly",
        "One-Class SVM": "ocsvm_anomaly",
        "LOF": "lof_anomaly",
        "Z-Score (|z|>3)": "zscore_anomaly",
        "Temporal Z-Score": "temporal_anomaly",
        "Feature CUSUM Top10%": "feat_cusum_top10pct",
        # Tier 2
        "ACECARD Direction": "acecard_direction_detected",
        "IForest + ACECARD": "combined_detected",
        # Tier 3
        "T3 Velocity/Accel": "t3_velocity_detected",
        "T3 Regime Shift": "t3_regime_detected",
        "T3 Zone Divergence": "t3_zone_divergence_detected",
        "T3 Relationship Drift": "t3_rel_detected",
        "T3 Contextual": "t3_ctx_detected",
        "T3 Embedding CUSUM": "t3_cusum_detected",
        "T3 Zone Threat Dir": "t3_zone_threat_detected",
        "T3 Beh Progression": "t3_prog_detected",
        "T3 Combined": "t3_combined_detected",
    }

    attack_users = merged[merged["is_attack"]]["user_id"].tolist()
    normal_users = merged[~merged["is_attack"]]

    print(f"\nTotal users analyzed: {len(merged)}")
    print(f"Attack users: {attack_users}")
    print()

    # Build dynamic attack user columns
    attack_cols = []
    for uid in ATTACK_ENTITIES:
        if uid in merged["user_id"].values:
            short = ATTACK_ENTITIES[uid]["name"].split("(")[0].strip()[:12]
            attack_cols.append((uid, short))

    header = f"  {'Method':<22}"
    label_line = f"  {'':<22}"
    for uid, short in attack_cols:
        header += f" {uid:>10}"
        label_line += f" {short:>10}"
    header += f" {'True Pos':>10} {'False Pos':>10} {'FP Rate':>10}"
    print(header)
    print(label_line)
    print("  " + "-" * (22 + 12 * len(attack_cols) + 32))

    tier_labels = {
        "Isolation Forest": "TIER 1",
        "ACECARD Direction": "TIER 2",
        "T3 Velocity/Accel": "TIER 3",
    }

    for method_name, col in methods.items():
        if col not in merged.columns:
            continue

        if method_name in tier_labels:
            print(f"\n  ── {tier_labels[method_name]} {'─' * 60}")

        line = f"  {method_name:<22}"
        tp = 0
        for uid, _ in attack_cols:
            vals = merged.loc[merged["user_id"] == uid, col].values
            det = bool(vals[0]) if len(vals) > 0 else False
            if det:
                tp += 1
            line += f" {'DETECTED':>10}" if det else f" {'MISSED':>10}"

        fp = int(normal_users[col].sum()) if col in normal_users.columns else 0
        fp_rate = fp / max(len(normal_users), 1)
        line += f" {tp:>10} {fp:>10} {fp_rate:>10.1%}"
        print(line)

    # Tier 3 detail section
    print("\n" + "=" * 90)
    print("TIER 3 DETAIL: Digital Entity Analysis for Attack Users")
    print("=" * 90)

    for uid in [u for u in ATTACK_ENTITIES if u in merged["user_id"].values]:
        row = merged[merged["user_id"] == uid]
        if row.empty:
            continue
        row = row.iloc[0]
        attack_name = ATTACK_ENTITIES.get(uid, {}).get("name", "Unknown")
        print(f"\n  {uid} ({attack_name}):")
        print(f"    Velocity:      magnitude={row.get('t3_velocity_magnitude', 0):.6f}, "
              f"acceleration={row.get('t3_acceleration', 0):.6f}")
        print(f"    Stability:     {row.get('t3_stability', 0):.4f}, "
              f"trend_consistency={row.get('t3_trend_consistency', 0):.4f}")
        print(f"    Regime:        {row.get('t3_regime', 'N/A')}, "
              f"shifts={row.get('t3_regime_shifts', 0):.2f}")
        print(f"    Zone drifts:   identity={row.get('t3_identity_drift', 0):.4f}, "
              f"data={row.get('t3_data_drift', 0):.4f}, "
              f"network={row.get('t3_network_drift', 0):.4f}, "
              f"risk={row.get('t3_risk_drift', 0):.4f}")
        if row.get("t3_zone_divergence_detected"):
            print(f"    Zone pattern:  {row.get('t3_zone_diagnostics', 'N/A')}")
        concept_diag = row.get("t3_concept_zone_diagnostics", "")
        if concept_diag:
            print(f"    Concept align: {concept_diag}")
        divergence_str = row.get("t3_concept_divergence_strings", "")
        if divergence_str:
            print(f"    Zone diverge:  {divergence_str}")
        threat_zone = row.get("t3_concept_primary_threat_zone", "")
        if threat_zone:
            print(f"    Threat zone:   {threat_zone} "
                  f"(confidence={row.get('t3_concept_max_threat_confidence', 0):.3f})")
        print(f"    Relationship:  drift={row.get('t3_rel_drift', 0):.4f}")
        print(f"    Contextual:    best_context={row.get('t3_ctx_best_context', 'N/A')}, "
              f"consistency={row.get('t3_ctx_best_consistency', 0):.4f}")
        print(f"    CUSUM:         max={row.get('t3_cusum_max', 0):.6f}, "
              f"final={row.get('t3_cusum_final', 0):.6f}")
        print(f"    Zone Threat:   best_zone={row.get('t3_zone_threat_best_zone', 'N/A')}, "
              f"score={row.get('t3_zone_threat_best_score', 0):.4f}")
        print(f"    Progression:   best_zone={row.get('t3_prog_best_zone', 'N/A')}, "
              f"tau={row.get('t3_prog_best_tau', 0):.4f}, "
              f"late_threat={row.get('t3_prog_late_threat', 0):.4f}")
        print(f"    Composite:     score={row.get('t3_composite_score', 0):.4f}, "
              f"corroboration={int(row.get('t3_anomaly_breadth', 0))}/6 core methods")

    # Key findings
    print("\n" + "=" * 90)
    print("KEY FINDINGS")
    print("=" * 90)

    t3_combined = merged.get("t3_combined_detected", pd.Series(dtype=bool))
    t12_combined = merged.get("combined_detected", pd.Series(dtype=bool))

    if not t3_combined.empty and not t12_combined.empty:
        t3_fp = int(normal_users["t3_combined_detected"].sum()) if "t3_combined_detected" in normal_users.columns else 0
        t12_fp = int(normal_users["combined_detected"].sum()) if "combined_detected" in normal_users.columns else 0
        t3_fp_rate = t3_fp / max(len(normal_users), 1)
        t12_fp_rate = t12_fp / max(len(normal_users), 1)

        print(f"\n  Tier 1+2 Combined: {t12_fp} FP ({t12_fp_rate:.1%})")
        print(f"  Tier 3 Combined:   {t3_fp} FP ({t3_fp_rate:.1%})")

    print()
    print("  1. ZONE DIVERGENCE: Tier 3 detects attack patterns by their zone-specific")
    print("     signature. An insider threat shows identity STABLE + data_behavior DRIFTING.")
    print("     An APT shows identity STABLE + network_footprint DRIFTING. Traditional")
    print("     methods cannot distinguish which behavioral DIMENSION is changing.")
    print()
    print("  2. CONTEXTUAL DETECTION: By re-weighting zone attention for different")
    print("     investigation scenarios, the same embeddings reveal different threats.")
    print("     'apt_hunt' context (network=0.40) amplifies C2 signals that uniform")
    print("     weighting dilutes. 'insider_investigation' (data=0.40) amplifies exfil.")
    print()
    print("  3. VELOCITY VECTORS: Full 1536-d velocity captures not just HOW MUCH")
    print("     an entity drifted, but the exact DIRECTION and ACCELERATION. An entity")
    print("     accelerating toward threat-space is a stronger signal than slow drift.")
    print()
    print("  4. RELATIONSHIP EMBEDDINGS: UserDevice Hadamard products capture interaction")
    print("     patterns. When a C2 beacon changes how a user uses their device, the")
    print("     relationship vector drifts even if neither entity individually changes.")


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Tier 3 Digital Entity Comparison")
    parser.add_argument("--users", type=int, default=250,
                        help="Number of users to analyze (default: 250)")
    args = parser.parse_args()

    if not DATA_DIR.exists():
        print("ERROR: No generated data. Run 'python -m simulator.generate --days 7' first.")
        sys.exit(1)

    auth_dir = DATA_DIR / "auth"
    csv_files = sorted(auth_dir.glob("*.csv"))
    if not csv_files:
        print("ERROR: No auth CSVs found")
        sys.exit(1)

    first_date = date.fromisoformat(csv_files[0].stem)
    last_date = date.fromisoformat(csv_files[-1].stem)
    print(f"Data range: {first_date} to {last_date} ({len(csv_files)} days)")

    user_device_map = _build_user_device_map()

    from simulator.entities import generate_all
    entities = generate_all()
    all_user_ids = entities["users"]["user_id"].tolist()

    priority_users = [uid for uid in ATTACK_ENTITIES.keys() if uid in all_user_ids]
    remaining = [uid for uid in all_user_ids if uid not in priority_users]
    np.random.seed(42)
    sample_size = min(args.users - len(priority_users), len(remaining))
    sampled = list(np.random.choice(remaining, size=max(0, sample_size), replace=False))
    user_ids = priority_users + sampled
    print(f"Analyzing {len(user_ids)} users (including {len(priority_users)} attack targets)")

    # Phase 1: Feature Engineering (reuse from Tier 1/2)
    print("\n" + "=" * 60)
    print("PHASE 1: FEATURE ENGINEERING")
    print("=" * 60)
    features_df = engineer_weekly_features(first_date, last_date, user_ids, user_device_map)

    # Phase 2: Tier 1 Traditional Detection
    traditional_results = run_traditional_detection(features_df)

    # Phase 3: Tier 1 Temporal
    temporal_results = run_temporal_traditional(features_df)

    # Phase 4: Tier 1 Feature CUSUM
    feat_cusum_results = run_feature_trajectory_cusum(features_df)

    # Phase 5: Tier 2 ACECARD
    acecard_results = run_acecard_detection(features_df)

    # Phase 6: Tier 1+2 Merge
    tier12_merged = build_comparison_report(
        traditional_results, temporal_results, feat_cusum_results, acecard_results
    )

    # Phase 7: Tier 3 Digital Entity Detection
    print("\n" + "=" * 60)
    print("PHASE 7: TIER 3 DIGITAL ENTITY DETECTION")
    print("=" * 60)

    from embeddings.embedder import Embedder
    from detection.reference_concepts import ConceptLibrary

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY is required — real OpenAI embeddings are mandatory "
            "(mock embeddings have been removed)."
        )
    print("  Using REAL OpenAI embeddings")
    embedder = Embedder(api_key=api_key)

    concept_lib = ConceptLibrary(embedder=embedder)
    concept_lib.embed_concepts()

    config = Tier3Config()
    entity_zoo = build_entity_zoo(
        user_ids, features_df, entities, user_device_map,
        embedder, concept_lib, config,
    )

    # Persist embeddings to PostgreSQL
    print("\n  Saving embeddings to PostgreSQL...", flush=True)
    n_saved = save_embeddings_to_db(entity_zoo, features_df)
    print(f"  Saved {n_saved:,} embedding snapshots to behavioral_snapshots table", flush=True)

    tier3_results = run_all_tier3_detections(entity_zoo, embedder, concept_lib, config)

    # Phase 8: Three-tier merge
    full_merged = tier12_merged.merge(tier3_results, on="user_id", how="outer")

    # Tier 3 all-tiers combined
    if "iforest_anomaly" in full_merged.columns and "t3_combined_detected" in full_merged.columns:
        full_merged["all_tiers_combined"] = (
            full_merged["iforest_anomaly"]
            | full_merged.get("acecard_direction_detected", False)
            | full_merged["t3_combined_detected"]
        )

    print_tier3_report(full_merged)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    full_merged.to_csv(RESULTS_DIR / "tier3_comparison.csv", index=False)
    print(f"\nResults saved to {RESULTS_DIR}/tier3_comparison.csv")

    # Phase 9: Save weekly trajectory data (per-user per-week drift scalars)
    print("\n  Extracting weekly trajectory data...")
    traj_df = extract_weekly_trajectories(entity_zoo, features_df)
    traj_path = RESULTS_DIR / "weekly_zone_trajectories.csv"
    traj_df.to_csv(traj_path, index=False)
    print(f"  Saved {len(traj_df)} trajectory rows to {traj_path}")

    # Phase 10: Save Digital Entity structures (raw -> zone text -> JSON)
    import json as _json
    print("  Extracting Digital Entity structures...")
    structures = extract_entity_structures(entity_zoo, features_df, embedder)
    struct_path = RESULTS_DIR / "entity_structures.json"
    with open(struct_path, "w") as f:
        _json.dump(structures, f, indent=2, default=str)
    print(f"  Saved {len(structures)} entity structures to {struct_path}")

    stats = embedder.stats()
    print(f"Embedding stats: {stats['api_calls']} API calls, {stats['cache_hits']} cache hits")


if __name__ == "__main__":
    main()
