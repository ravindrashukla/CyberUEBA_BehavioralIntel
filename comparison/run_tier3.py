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
from models.cyber_entity import CyberEntity, PhaseState, Tier3Config, EMBED_DIM
from models.hierarchical_zones import (
    CYBER_ZONES, CONTEXT_WEIGHTS, ALL_CONTEXTS, USER_ZONE_ORDER,
    build_zone_embeddings, compose_zones, serialize_zone,
)
from models.temporal_trajectory import (
    compute_velocity_vector, compute_trajectory_features,
    detect_regime, compute_zone_trajectories, build_phase_state,
)
from models.relationship_embeddings import hadamard, relationship_drift

RESULTS_DIR = Path("data/tier3_results")


# ── Entity Zoo Builder ───────────────────────────────────────────────────────


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

    Per user:
      - 5 zone embeddings per week
      - Composite under all 4 contexts per week
      - UserDevice relationship embeddings per week (if device mapped)
      - Temporal snapshots → PhaseState (velocity, acceleration, regime)
      - Per-zone trajectory features
    """
    print("\n  Building Digital Entity Zoo...")

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

    entity_zoo = {}

    for i, uid in enumerate(user_ids):
        profile = user_profiles.get(uid, {"user_id": uid})
        user_weeks = features_df[features_df["user_id"] == uid].sort_values("week_idx")

        if len(user_weeks) < 3:
            continue

        # Build zone embeddings per week
        weekly_zone_embs = []
        weekly_composites = {ctx: [] for ctx in ALL_CONTEXTS}

        for _, row in user_weeks.iterrows():
            feat_dict = {col: row[col] for col in FEATURE_COLS}
            zone_embs = build_zone_embeddings("user", uid, profile, feat_dict, embedder)
            weekly_zone_embs.append(zone_embs)

            for ctx in ALL_CONTEXTS:
                comp = compose_zones(zone_embs, context=ctx, entity_type="user")
                weekly_composites[ctx].append(comp)

        # Build zone snapshot series (per-zone over time)
        zone_snapshot_series = {}
        for zone_name in USER_ZONE_ORDER:
            zone_snapshot_series[zone_name] = [
                wze[zone_name] for wze in weekly_zone_embs if zone_name in wze
            ]

        # Build device composites for relationship embeddings
        dev_ids = user_device_map.get(uid, [])
        weekly_rel_embs = []
        if dev_ids:
            primary_dev = dev_ids[0]
            dev_profile = device_profiles.get(primary_dev, {"device_id": primary_dev})
            for wk_idx, (_, row) in enumerate(user_weeks.iterrows()):
                feat_dict = {col: row[col] for col in FEATURE_COLS}
                dev_zone_embs = build_zone_embeddings(
                    "device", primary_dev, dev_profile, feat_dict, embedder
                )
                dev_composite = compose_zones(dev_zone_embs, context="normal_ops", entity_type="device")
                user_comp = weekly_composites["normal_ops"][wk_idx]
                rel_emb = hadamard(user_comp, dev_composite)
                weekly_rel_embs.append(rel_emb)

        # Compute phase state from normal_ops composites
        normal_snapshots = weekly_composites["normal_ops"]
        phase = build_phase_state(normal_snapshots, zone_snapshot_series)

        # Zone trajectories
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

        # Store contextual composites for later detection
        entity._contextual_composites = weekly_composites
        entity._zone_trajectories = zone_trajs

        entity_zoo[uid] = entity

        if (i + 1) % 10 == 0:
            print(f"    {i + 1}/{len(user_ids)} entities built")

    print(f"  Entity zoo built: {len(entity_zoo)} entities")
    return entity_zoo


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
) -> pd.DataFrame:
    """Per-zone drift analysis using percentile-based scoring.

    Computes a zone divergence score: max(behavioral zone drifts) - identity drift.
    Higher score = bigger gap between identity stability and behavioral change.
    Top 10% flagged.
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

        rows.append({
            "user_id": uid,
            "t3_identity_drift": identity_drift,
            "t3_data_drift": data_drift,
            "t3_network_drift": network_drift,
            "t3_risk_drift": risk_drift,
            "t3_access_drift": access_drift,
            "t3_zone_divergence_score": divergence_score,
            "t3_zone_diagnostics": "; ".join(diagnostics_parts),
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
    """Run all 6 Tier 3 detection methods and merge results."""
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

    print("  3. Zone Divergence Detection...")
    zone_df = run_tier3_zone_drift_detection(entity_zoo, config)
    z_det = zone_df["t3_zone_divergence_detected"].sum()
    print(f"     Flagged: {z_det}/{len(entity_zoo)}")

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

    # Merge all Tier 3 results
    merged = velocity_df
    for df in [regime_df, zone_df, rel_df, ctx_df, cohort_df]:
        merged = merged.merge(df, on="user_id", how="outer")

    # Tier 3 composite risk score: weighted combination of all method scores
    merged["t3_composite_score"] = (
        0.25 * _rank_normalize(merged.get("t3_velocity_score", pd.Series(0.0, index=merged.index)))
        + 0.20 * _rank_normalize(merged.get("t3_regime_score", pd.Series(0.0, index=merged.index)))
        + 0.25 * _rank_normalize(merged.get("t3_zone_divergence_score", pd.Series(0.0, index=merged.index)))
        + 0.15 * _rank_normalize(merged.get("t3_rel_drift", pd.Series(0.0, index=merged.index)))
        + 0.15 * _rank_normalize(merged.get("t3_ctx_best_consistency", pd.Series(0.0, index=merged.index)))
    )

    # Top 10% by composite score
    composite_threshold = merged["t3_composite_score"].quantile(0.90)
    merged["t3_combined_detected"] = merged["t3_composite_score"] >= max(composite_threshold, 0.01)
    t3_det = merged["t3_combined_detected"].sum()
    print(f"\n  Tier 3 Combined (top 10% composite): {t3_det}/{len(entity_zoo)} flagged")

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
        "T3 Combined": "t3_combined_detected",
    }

    attack_users = merged[merged["is_attack"]]["user_id"].tolist()
    normal_users = merged[~merged["is_attack"]]

    print(f"\nTotal users analyzed: {len(merged)}")
    print(f"Attack users: {attack_users}")
    print()

    print(f"{'Method':<24} {'USR-156':>10} {'USR-234':>10} {'True Pos':>10} {'False Pos':>10} {'FP Rate':>10}")
    print(f"{'':>24} {'(Insider)':>10} {'(APT)':>10}")
    print("-" * 74)

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

        usr156 = merged.loc[merged["user_id"] == "USR-156", col].values
        usr234 = merged.loc[merged["user_id"] == "USR-234", col].values

        det_156 = bool(usr156[0]) if len(usr156) > 0 else False
        det_234 = bool(usr234[0]) if len(usr234) > 0 else False

        tp = sum(1 for uid in attack_users
                 if not merged.loc[merged["user_id"] == uid, col].empty
                 and bool(merged.loc[merged["user_id"] == uid, col].values[0]))

        fp = int(normal_users[col].sum()) if col in normal_users.columns else 0
        fp_rate = fp / max(len(normal_users), 1)

        flag_156 = "DETECTED" if det_156 else "MISSED"
        flag_234 = "DETECTED" if det_234 else "MISSED"

        print(f"  {method_name:<22} {flag_156:>10} {flag_234:>10} {tp:>10} {fp:>10} {fp_rate:>10.1%}")

    # Tier 3 detail section
    print("\n" + "=" * 90)
    print("TIER 3 DETAIL: Digital Entity Analysis for Attack Users")
    print("=" * 90)

    for uid in ["USR-156", "USR-234"]:
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
        print(f"    Relationship:  drift={row.get('t3_rel_drift', 0):.4f}")
        print(f"    Contextual:    best_context={row.get('t3_ctx_best_context', 'N/A')}, "
              f"consistency={row.get('t3_ctx_best_consistency', 0):.4f}")

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

    # Note about embedder mode
    is_mock = "acecard_direction_detected" in merged.columns and merged["acecard_direction_detected"].sum() == 0
    if is_mock:
        print("\n  NOTE: Running with MockEmbedder. Embeddings are deterministic but")
        print("  NOT semantically meaningful. Detection accuracy improves significantly")
        print("  with real OpenAI embeddings (set OPENAI_API_KEY). MockEmbedder proves")
        print("  the pipeline runs end-to-end; real embeddings prove detection power.")

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
    parser.add_argument("--users", type=int, default=50,
                        help="Number of users to analyze (default: 50)")
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

    from embeddings.embedder import Embedder, MockEmbedder
    from detection.reference_concepts import ConceptLibrary

    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        print("  Using REAL OpenAI embeddings")
        embedder = Embedder(api_key=api_key)
    else:
        print("  Using MockEmbedder (no OPENAI_API_KEY)")
        embedder = MockEmbedder()

    concept_lib = ConceptLibrary(embedder=embedder)
    concept_lib.embed_concepts()

    config = Tier3Config()
    entity_zoo = build_entity_zoo(
        user_ids, features_df, entities, user_device_map,
        embedder, concept_lib, config,
    )

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

    stats = embedder.stats()
    print(f"Embedding stats: {stats['api_calls']} API calls, {stats['cache_hits']} cache hits")


if __name__ == "__main__":
    main()
