"""Tier 3 Zone Embedding Pipeline & Concept Alignment Deep Trace.

Traces exactly what happens for each attack user in the Tier 3 pipeline:
1. Exact zone text comparison (flat vs interpretive) at weeks 0, 9, 18
2. Zone drift vectors from pre-computed results
3. Concept alignment trace -- why drift aligns with "seasonal_variation"
4. Weekly trajectory data per attack user
5. Population comparison (p50/p90/p95/p99) for drift metrics

NO OpenAI API calls. Uses only cached data and pre-computed results.

Usage: python scripts/audit_round3_tier3_trace.py
"""
import sys
import os
import json
from pathlib import Path
from datetime import date, timedelta

import numpy as np
import pandas as pd

# Ensure project root on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from comparison.run_comparison import (
    DATA_DIR, ATTACK_ENTITIES, FEATURE_COLS,
    _build_user_device_map, engineer_weekly_features, load_week_csvs,
)
from models.hierarchical_zones import (
    CYBER_ZONES, USER_ZONE_ORDER,
    serialize_zone, serialize_zone_interpretive, BehavioralContext,
)
from detection.reference_concepts import (
    THREAT_CONCEPTS, BENIGN_CONCEPTS, ALL_CONCEPTS,
)
from embeddings.embedder import MockEmbedder
from embeddings.composer import cosine_similarity, drift_magnitude, drift_vector

RESULTS_DIR = ROOT / "data" / "tier3_results"
ATTACK_USERS = list(ATTACK_ENTITIES.keys())

SEPARATOR = "=" * 100
SUBSEP = "-" * 100


def load_precomputed():
    """Load pre-computed tier3 results."""
    traj_path = RESULTS_DIR / "weekly_zone_trajectories.csv"
    struct_path = RESULTS_DIR / "entity_structures.json"
    comp_path = RESULTS_DIR / "tier3_comparison.csv"

    traj_df = pd.read_csv(traj_path)
    with open(struct_path) as f:
        structures = json.load(f)
    comp_df = pd.read_csv(comp_path)

    return traj_df, structures, comp_df


def build_features_for_attack_users():
    """Recompute weekly features for attack users only (fast, no API calls)."""
    auth_dir = DATA_DIR / "auth"
    csv_files = sorted(auth_dir.glob("*.csv"))
    first_date = date.fromisoformat(csv_files[0].stem)
    last_date = date.fromisoformat(csv_files[-1].stem)

    user_device_map = _build_user_device_map()

    features_df = engineer_weekly_features(
        first_date, last_date, ATTACK_USERS, user_device_map
    )
    return features_df


def get_user_profile(uid):
    """Get user profile from entity generator."""
    from simulator.entities import generate_all
    entities = generate_all()
    users = entities["users"]
    row = users[users["user_id"] == uid]
    if row.empty:
        return {"user_id": uid}
    return row.iloc[0].to_dict()


def compute_population_stats(features_df):
    """Compute pop mean/std across ALL weeks of the provided features."""
    pop_mean = {}
    pop_std = {}
    for col in FEATURE_COLS:
        if col in features_df.columns:
            pop_mean[col] = float(features_df[col].mean())
            pop_std[col] = float(features_df[col].std())
            if pop_std[col] < 1e-10:
                pop_std[col] = 1.0
    return pop_mean, pop_std


def compute_user_baseline(user_weeks, baseline_n=8):
    """Mean of first N weeks as user baseline."""
    baseline = user_weeks.head(baseline_n)
    result = {}
    for col in FEATURE_COLS:
        if col in baseline.columns:
            result[col] = float(baseline[col].mean())
    return result


# ============================================================================
# SECTION 1: Exact zone text comparison
# ============================================================================

def section1_zone_text_comparison(features_all_users_df):
    """Print exact zone texts for weeks 0, 9, 18 for each attack user."""
    print(f"\n{SEPARATOR}")
    print("SECTION 1: EXACT ZONE TEXT COMPARISON")
    print(f"  Flat (serialize_zone) vs Interpretive (serialize_zone_interpretive)")
    print(f"  Weeks: 0 (first baseline), 9 (first test), 18 (last)")
    print(SEPARATOR)

    # For interpretive, we need population stats from the FULL 250-user run.
    # But we only loaded attack users. We'll compute pop stats from them for
    # the interpretive demonstration, noting this is a partial population.
    # The key insight is the TEXT itself, not exact z-scores.
    #
    # Actually, let's load the full features from the pre-computed trajectory
    # data to get population-level stats. We can reconstruct pop stats from
    # the full entity_structures.json raw_features (last week only though).
    #
    # Best approach: use attack user features and note the limitation.
    pop_mean, pop_std = compute_population_stats(features_all_users_df)

    target_weeks = [0, 9, 18]

    for uid in ATTACK_USERS:
        attack_info = ATTACK_ENTITIES[uid]
        profile = get_user_profile(uid)
        user_weeks = features_all_users_df[
            features_all_users_df["user_id"] == uid
        ].sort_values("week_idx").reset_index(drop=True)

        if user_weeks.empty:
            print(f"\n  WARNING: No data for {uid}")
            continue

        user_baseline = compute_user_baseline(user_weeks)
        n_weeks = len(user_weeks)
        available_weeks = [w for w in target_weeks if w < n_weeks]

        print(f"\n{SUBSEP}")
        print(f"  {uid} -- {attack_info['name']}")
        print(f"  Attack starts: {attack_info['start']}")
        print(f"  Profile: role={profile.get('role')}, dept={profile.get('department')}, "
              f"clearance={profile.get('clearance')}")
        print(f"  Total weeks: {n_weeks}, showing: {available_weeks}")
        print(SUBSEP)

        # Collect history for trend computation
        recent_history = []

        for wk_idx in range(n_weeks):
            row = user_weeks.iloc[wk_idx]
            feat_dict = {col: float(row[col]) for col in FEATURE_COLS if col in row.index}

            bctx = BehavioralContext(
                pop_mean=pop_mean, pop_std=pop_std,
                user_baseline=user_baseline, week_idx=wk_idx,
                recent_history=list(recent_history[-3:]),
            )

            if wk_idx in available_weeks:
                print(f"\n  --- Week {wk_idx} (dates: {row.get('week_start', '?')} to {row.get('week_end', '?')}) ---")

                for zone_name in USER_ZONE_ORDER:
                    flat_text = serialize_zone("user", zone_name, profile, feat_dict)
                    interp_text = serialize_zone_interpretive("user", zone_name, profile, feat_dict, bctx)

                    print(f"\n    Zone: {zone_name}")
                    print(f"      FLAT:   {flat_text}")
                    print(f"      INTERP: {interp_text}")

            recent_history.append(feat_dict)


# ============================================================================
# SECTION 2: Zone drift vectors from pre-computed data
# ============================================================================

def section2_zone_drift_vectors(traj_df, structures):
    """Show per-zone drift from pre-computed results."""
    print(f"\n\n{SEPARATOR}")
    print("SECTION 2: ZONE DRIFT VECTORS (from pre-computed results)")
    print(f"  Source: data/tier3_results/weekly_zone_trajectories.csv")
    print(f"  Source: data/tier3_results/entity_structures.json")
    print(SEPARATOR)

    # From entity_structures.json, get phase_state (total_drift, velocity, etc.)
    struct_by_id = {s["entity_id"]: s for s in structures}

    for uid in ATTACK_USERS:
        attack_info = ATTACK_ENTITIES[uid]
        user_traj = traj_df[traj_df["user_id"] == uid].sort_values("week_idx")

        print(f"\n{SUBSEP}")
        print(f"  {uid} -- {attack_info['name']}")
        print(SUBSEP)

        if uid in struct_by_id:
            s = struct_by_id[uid]
            ps = s["phase_state"]
            print(f"\n  Phase State (from entity_structures.json):")
            print(f"    velocity_magnitude: {ps['velocity_magnitude']:.6f}")
            print(f"    acceleration:       {ps['acceleration']:.6f}")
            print(f"    stability:          {ps['stability']:.6f}")
            print(f"    regime_shifts:      {ps['regime_shifts']}")
            print(f"    trend_consistency:  {ps['trend_consistency']:.6f}")
            print(f"    total_drift:        {ps['total_drift']:.6f}")
            print(f"    current_regime:     {ps['current_regime']}")

        if user_traj.empty:
            print(f"  WARNING: No trajectory data for {uid}")
            continue

        # First and last week drift values
        first = user_traj.iloc[0]
        last = user_traj.iloc[-1]

        drift_cols = ["identity_drift", "access_pattern_drift", "data_behavior_drift",
                      "network_footprint_drift", "risk_posture_drift", "composite_drift"]

        print(f"\n  Zone drifts (cosine distance from baseline):")
        print(f"    {'Zone':<28} {'Week 0':>12} {'Week {}'.format(int(last['week_idx'])):>12} {'Delta':>12}")
        print(f"    {'-'*28} {'-'*12} {'-'*12} {'-'*12}")
        for col in drift_cols:
            v0 = first.get(col, 0.0)
            vN = last.get(col, 0.0)
            delta = vN - v0
            label = col.replace("_drift", "")
            print(f"    {label:<28} {v0:>12.6f} {vN:>12.6f} {delta:>+12.6f}")

        # Now compute MockEmbedder-based cosine distance between week 0 and
        # last week zone texts, to quantify text-level drift
        print(f"\n  MockEmbedder cosine distance (week 0 text vs last week text):")
        embedder = MockEmbedder()
        if uid in struct_by_id:
            s = struct_by_id[uid]
            zone_texts_last = s.get("zone_serialized_text", {})
            # We'd need week 0 texts too -- those are NOT stored in entity_structures
            # (which only has last week). Note this limitation.
            print(f"    (entity_structures.json only stores LAST week zone texts)")
            print(f"    Last week texts stored:")
            for zname, text in zone_texts_last.items():
                print(f"      {zname}: {text[:120]}...")


# ============================================================================
# SECTION 3: Concept alignment trace
# ============================================================================

def section3_concept_alignment_trace():
    """Print all 12 reference concepts and explain alignment failure."""
    print(f"\n\n{SEPARATOR}")
    print("SECTION 3: CONCEPT ALIGNMENT TRACE")
    print(f"  12 reference concepts (10 threat + 2 benign)")
    print(f"  + Analysis of WHY drift vectors align with seasonal_variation")
    print(SEPARATOR)

    print(f"\n  THREAT CONCEPTS ({len(THREAT_CONCEPTS)}):")
    print(f"  {'-'*90}")
    for i, c in enumerate(THREAT_CONCEPTS, 1):
        print(f"\n  [{i}] {c.name} (severity={c.severity})")
        print(f"      MITRE: {', '.join(c.mitre_techniques)}")
        # Wrap description
        desc = c.description
        while len(desc) > 80:
            split_at = desc[:80].rfind(" ")
            if split_at == -1:
                split_at = 80
            print(f"      {desc[:split_at]}")
            desc = desc[split_at:].strip()
        if desc:
            print(f"      {desc}")

    print(f"\n  BENIGN CONCEPTS ({len(BENIGN_CONCEPTS)}):")
    print(f"  {'-'*90}")
    for i, c in enumerate(BENIGN_CONCEPTS, 1):
        print(f"\n  [{i}] {c.name} (severity={c.severity})")
        desc = c.description
        while len(desc) > 80:
            split_at = desc[:80].rfind(" ")
            if split_at == -1:
                split_at = 80
            print(f"      {desc[:split_at]}")
            desc = desc[split_at:].strip()
        if desc:
            print(f"      {desc}")

    # Now demonstrate the core problem with MockEmbedder
    print(f"\n\n  {'='*90}")
    print(f"  ROOT CAUSE ANALYSIS: Why drift aligns with seasonal_variation")
    print(f"  {'='*90}")

    embedder = MockEmbedder()

    # Embed two example zone texts (week 0 vs week 18 for an attack user)
    text_baseline = (
        "User USR-234 data: file_accesses=72, restricted_ratio=0.0502, "
        "confidential_ratio=0.0333, write_ratio=0.2361, unique_paths=58, bytes=1234567890"
    )
    text_attack = (
        "User USR-234 data: file_accesses=70, restricted_ratio=0.0426, "
        "confidential_ratio=0.0314, write_ratio=0.2286, unique_paths=56, bytes=1200000000"
    )

    v_baseline = embedder.embed_text(text_baseline)
    v_attack = embedder.embed_text(text_attack)
    drift_vec = drift_vector(v_baseline, v_attack)
    drift_mag = drift_magnitude(v_baseline, v_attack)

    print(f"\n  Example: USR-234 data_behavior zone")
    print(f"    Baseline text: {text_baseline[:90]}...")
    print(f"    Attack text:   {text_attack[:90]}...")
    print(f"    Drift magnitude (cosine distance): {drift_mag:.6f}")

    # Embed all concepts and compute alignment
    print(f"\n  Drift vector alignment with all 12 concepts:")
    print(f"    {'Concept':<30} {'Category':<10} {'Alignment':>10}")
    print(f"    {'-'*30} {'-'*10} {'-'*10}")

    alignments = []
    for concept in ALL_CONCEPTS:
        concept_vec = embedder.embed_text(concept.description)
        alignment = cosine_similarity(drift_vec, concept_vec)
        alignments.append((concept.name, concept.category, alignment))

    alignments.sort(key=lambda x: x[2], reverse=True)
    for name, cat, score in alignments:
        marker = " <-- TOP" if score == max(a[2] for a in alignments) else ""
        print(f"    {name:<30} {cat:<10} {score:>10.6f}{marker}")

    print(f"\n  DIAGNOSIS:")
    print(f"  {'-'*90}")
    print(f"  The MockEmbedder hashes each text string with SHA256 and uses that to seed")
    print(f"  a random number generator, producing a pseudo-random unit vector in 1536-d.")
    print(f"")
    print(f"  KEY PROBLEM: MockEmbedder produces SEMANTICALLY MEANINGLESS vectors.")
    print(f"  Two texts that differ by a single character produce COMPLETELY DIFFERENT")
    print(f"  vectors (cosine similarity near 0). This means:")
    print(f"")
    print(f"    1. The drift vector (v_attack - v_baseline) is itself a random direction")
    print(f"       because v_attack and v_baseline are independent random unit vectors.")
    print(f"")
    print(f"    2. The concept vectors are ALSO random (seeded by their description text).")
    print(f"")
    print(f"    3. Cosine similarity between two random 1536-d unit vectors has mean ~0")
    print(f"       and std ~1/sqrt(1536) = ~0.026. So ALL alignment scores will be")
    print(f"       near-zero random noise, with no semantic meaning.")
    print(f"")
    print(f"    4. Whichever concept happens to get the highest random score 'wins',")
    print(f"       and that is often seasonal_variation or normal_role_change because")
    print(f"       they are just as likely as any threat concept to randomly align.")
    print(f"")
    print(f"  CONTRAST WITH REAL EMBEDDINGS:")
    print(f"    With OpenAI text-embedding-3-small, 'restricted_ratio=0.16' would embed")
    print(f"    NEAR 'accessing restricted and classified materials' in the data_exfiltration")
    print(f"    concept. The drift vector from normal restricted_ratio to elevated")
    print(f"    restricted_ratio would genuinely point toward the exfiltration concept.")
    print(f"")
    print(f"  ADDITIONAL PROBLEM -- FLAT SERIALIZATION:")
    print(f"    Even with real embeddings, the FLAT serialization format")
    print(f"    ('restricted_ratio=0.0502') is numerically dense but semantically sparse.")
    print(f"    The number '0.0502' vs '0.16' looks similar to an embedding model.")
    print(f"    The INTERPRETIVE serialization ('EXTREME level... pattern consistent with")
    print(f"    data exfiltration') provides the semantic bridge that real embeddings need.")

    # Now show the interpretive text alignment to prove the point
    print(f"\n  INTERPRETIVE SERIALIZATION COMPARISON:")
    print(f"  {'-'*90}")

    interp_normal = (
        "Analyst USR-234 in Engineering: data access activity within normal parameters. "
        "File operations 72, restricted ratio 0.0502, confidential ratio 0.0333, all unremarkable."
    )
    interp_attack = (
        "CRITICAL ANOMALY in data access for Analyst USR-234 in Engineering. "
        "Restricted file access at EXTREME level: ratio 0.1600 "
        "(4.2 standard deviations above population, 3.2x baseline (major escalation)). "
        "This user is accessing classified and restricted materials at a rate far exceeding "
        "normal organizational patterns. Pattern strongly consistent with active data exfiltration, "
        "insider threat data staging, or unauthorized access to sensitive intellectual property."
    )

    v_interp_normal = embedder.embed_text(interp_normal)
    v_interp_attack = embedder.embed_text(interp_attack)
    interp_drift = drift_vector(v_interp_normal, v_interp_attack)
    interp_mag = drift_magnitude(v_interp_normal, v_interp_attack)

    print(f"\n    Normal interp: {interp_normal[:100]}...")
    print(f"    Attack interp: {interp_attack[:100]}...")
    print(f"    Drift magnitude: {interp_mag:.6f}")

    print(f"\n    Alignment with concepts (interpretive drift vector):")
    print(f"    {'Concept':<30} {'Category':<10} {'Alignment':>10}")
    print(f"    {'-'*30} {'-'*10} {'-'*10}")

    interp_alignments = []
    for concept in ALL_CONCEPTS:
        concept_vec = embedder.embed_text(concept.description)
        alignment = cosine_similarity(interp_drift, concept_vec)
        interp_alignments.append((concept.name, concept.category, alignment))

    interp_alignments.sort(key=lambda x: x[2], reverse=True)
    for name, cat, score in interp_alignments:
        print(f"    {name:<30} {cat:<10} {score:>10.6f}")

    print(f"\n    NOTE: Even interpretive text alignment is random with MockEmbedder.")
    print(f"    With REAL embeddings, the interpretive text contains words like")
    print(f"    'data exfiltration', 'insider threat', 'sensitive intellectual property'")
    print(f"    that would embed near the data_exfiltration and insider_threat_slow")
    print(f"    concept descriptions, producing strong positive alignment scores.")


# ============================================================================
# SECTION 4: Weekly trajectory data
# ============================================================================

def section4_weekly_trajectories(traj_df):
    """Print per-week drift metrics for each attack user."""
    print(f"\n\n{SEPARATOR}")
    print("SECTION 4: WEEKLY TRAJECTORY DATA")
    print(f"  Per-week zone drifts, composite drift, velocity, acceleration")
    print(SEPARATOR)

    drift_cols = [
        "data_behavior_drift", "network_footprint_drift",
        "access_pattern_drift", "identity_drift",
    ]

    for uid in ATTACK_USERS:
        attack_info = ATTACK_ENTITIES[uid]
        user_traj = traj_df[traj_df["user_id"] == uid].sort_values("week_idx")

        print(f"\n{SUBSEP}")
        print(f"  {uid} -- {attack_info['name']} (attack start: {attack_info['start']})")
        print(SUBSEP)

        if user_traj.empty:
            print(f"  No trajectory data")
            continue

        # Header
        header = f"  {'Wk':>3} "
        for col in drift_cols:
            short = col.replace("_drift", "")[:12]
            header += f" {short:>12}"
        header += f" {'composite':>12} {'velocity':>12} {'accel':>12} {'zone_div':>12}"
        print(header)
        print(f"  {'---':>3} " + (" " + "-" * 12) * 7)

        for _, row in user_traj.iterrows():
            wk = int(row["week_idx"])
            line = f"  {wk:>3} "
            for col in drift_cols:
                val = row.get(col, 0.0)
                line += f" {val:>12.6f}"
            line += f" {row.get('composite_drift', 0.0):>12.6f}"
            line += f" {row.get('velocity', 0.0):>12.6f}"
            line += f" {row.get('acceleration', 0.0):>12.6f}"
            line += f" {row.get('zone_divergence', 0.0):>12.6f}"
            print(line)

        # Summary stats
        print(f"\n  Summary:")
        for col in drift_cols + ["composite_drift", "velocity", "acceleration"]:
            vals = user_traj[col].values
            label = col.replace("_drift", "")
            print(f"    {label:<24} min={vals.min():.6f}  max={vals.max():.6f}  "
                  f"mean={vals.mean():.6f}  std={vals.std():.6f}")

        # Temporal pattern analysis
        comp_drift = user_traj["composite_drift"].values
        n = len(comp_drift)
        baseline_mean = comp_drift[:min(4, n)].mean()
        test_mean = comp_drift[max(n // 2, 4):].mean() if n > 4 else 0.0
        escalation = test_mean / max(baseline_mean, 1e-10)

        print(f"\n  Temporal pattern:")
        print(f"    Baseline composite drift (wk 0-3 mean):  {baseline_mean:.6f}")
        print(f"    Test period composite drift (wk 9+ mean): {test_mean:.6f}")
        print(f"    Escalation ratio:                         {escalation:.2f}x")

        # Check which zones show monotonic increase
        for col in drift_cols:
            vals = user_traj[col].values
            if len(vals) >= 6:
                # Simple monotonicity check on last 6 values
                last6 = vals[-6:]
                increasing = all(last6[i] <= last6[i+1] for i in range(len(last6)-1))
                late_mean = vals[-4:].mean()
                early_mean = vals[:4].mean()
                trend = "MONOTONIC INCREASE" if increasing else "non-monotonic"
                ratio = late_mean / max(early_mean, 1e-10)
                label = col.replace("_drift", "")
                print(f"    {label:<24}: last-6 {trend}, late/early ratio={ratio:.2f}x")


# ============================================================================
# SECTION 5: Population comparison
# ============================================================================

def section5_population_comparison(traj_df):
    """Compare attack user drift metrics to normal population distribution."""
    print(f"\n\n{SEPARATOR}")
    print("SECTION 5: POPULATION COMPARISON")
    print(f"  Attack user drift at LAST week vs normal user distribution")
    print(SEPARATOR)

    # Get the last week for each user
    last_week_idx = traj_df["week_idx"].max()
    last_week = traj_df[traj_df["week_idx"] == last_week_idx].copy()

    normal = last_week[~last_week["is_attack"]]
    attack = last_week[last_week["is_attack"]]

    drift_cols = [
        "identity_drift", "access_pattern_drift", "data_behavior_drift",
        "network_footprint_drift", "risk_posture_drift",
        "composite_drift", "zone_divergence",
    ]

    # Compute percentiles for normal users
    print(f"\n  Normal user distribution at week {last_week_idx} (N={len(normal)}):")
    print(f"  {'Metric':<28} {'p50':>10} {'p90':>10} {'p95':>10} {'p99':>10} {'max':>10}")
    print(f"  {'-'*28} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")

    percentiles = {}
    for col in drift_cols:
        if col not in normal.columns:
            continue
        vals = normal[col].dropna()
        p50 = vals.quantile(0.50)
        p90 = vals.quantile(0.90)
        p95 = vals.quantile(0.95)
        p99 = vals.quantile(0.99)
        mx = vals.max()
        percentiles[col] = {"p50": p50, "p90": p90, "p95": p95, "p99": p99, "max": mx}
        label = col.replace("_drift", "")
        print(f"  {label:<28} {p50:>10.6f} {p90:>10.6f} {p95:>10.6f} {p99:>10.6f} {mx:>10.6f}")

    # Where do attack users fall?
    print(f"\n\n  ATTACK USER POSITIONING (week {last_week_idx}):")
    print(f"  {'-'*90}")

    for uid in ATTACK_USERS:
        attack_info = ATTACK_ENTITIES[uid]
        user_row = attack[attack["user_id"] == uid]
        if user_row.empty:
            print(f"\n  {uid}: No data at week {last_week_idx}")
            continue

        user_row = user_row.iloc[0]
        print(f"\n  {uid} -- {attack_info['name']}:")

        for col in drift_cols:
            if col not in user_row.index or col not in percentiles:
                continue
            val = user_row[col]
            p = percentiles[col]
            label = col.replace("_drift", "")

            # Determine percentile rank
            if col in normal.columns:
                rank = (normal[col] < val).sum() / max(len(normal), 1) * 100
            else:
                rank = 0.0

            if val >= p["p99"]:
                bucket = ">p99"
            elif val >= p["p95"]:
                bucket = "p95-p99"
            elif val >= p["p90"]:
                bucket = "p90-p95"
            elif val >= p["p50"]:
                bucket = "p50-p90"
            else:
                bucket = "<p50"

            print(f"    {label:<28} value={val:>10.6f}  percentile={rank:>5.1f}%  bucket={bucket}")

    # Also show velocity/acceleration comparison
    vel_cols = ["velocity", "acceleration"]
    print(f"\n\n  VELOCITY/ACCELERATION COMPARISON (week {last_week_idx}):")
    print(f"  {'-'*90}")
    print(f"\n  Normal distribution:")
    print(f"  {'Metric':<20} {'p50':>10} {'p90':>10} {'p95':>10} {'p99':>10}")
    print(f"  {'-'*20} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")
    for col in vel_cols:
        if col not in normal.columns:
            continue
        vals = normal[col].dropna()
        print(f"  {col:<20} {vals.quantile(0.50):>10.6f} {vals.quantile(0.90):>10.6f} "
              f"{vals.quantile(0.95):>10.6f} {vals.quantile(0.99):>10.6f}")

    print(f"\n  Attack users:")
    for uid in ATTACK_USERS:
        user_row = attack[attack["user_id"] == uid]
        if user_row.empty:
            continue
        user_row = user_row.iloc[0]
        attack_info = ATTACK_ENTITIES[uid]
        parts = [f"  {uid:<12} ({attack_info['name'][:20]:<20})"]
        for col in vel_cols:
            if col in user_row.index:
                parts.append(f"{col}={user_row[col]:>10.6f}")
        print("  ".join(parts))


# ============================================================================
# SECTION 6: Concept alignment with ACTUAL attack user zone texts
# ============================================================================

def section6_actual_concept_alignment(features_df):
    """Compute concept alignment using actual attack user zone texts."""
    print(f"\n\n{SEPARATOR}")
    print("SECTION 6: CONCEPT ALIGNMENT WITH ACTUAL ATTACK USER ZONE TEXTS")
    print(f"  Using MockEmbedder to show mechanical behavior of the pipeline")
    print(SEPARATOR)

    embedder = MockEmbedder()
    pop_mean, pop_std = compute_population_stats(features_df)

    for uid in ATTACK_USERS:
        attack_info = ATTACK_ENTITIES[uid]
        profile = get_user_profile(uid)
        user_weeks = features_df[
            features_df["user_id"] == uid
        ].sort_values("week_idx").reset_index(drop=True)

        if len(user_weeks) < 10:
            print(f"\n  {uid}: insufficient weeks ({len(user_weeks)})")
            continue

        user_baseline = compute_user_baseline(user_weeks)

        print(f"\n{SUBSEP}")
        print(f"  {uid} -- {attack_info['name']}")
        print(SUBSEP)

        # Get week 0 and last week features
        for wk_pair_name, wk_a_idx, wk_b_idx in [("Week 0 -> Week 18", 0, len(user_weeks)-1)]:
            row_a = user_weeks.iloc[wk_a_idx]
            row_b = user_weeks.iloc[wk_b_idx]
            feat_a = {col: float(row_a[col]) for col in FEATURE_COLS if col in row_a.index}
            feat_b = {col: float(row_b[col]) for col in FEATURE_COLS if col in row_b.index}

            bctx_a = BehavioralContext(
                pop_mean=pop_mean, pop_std=pop_std,
                user_baseline=user_baseline, week_idx=wk_a_idx,
                recent_history=[],
            )
            bctx_b = BehavioralContext(
                pop_mean=pop_mean, pop_std=pop_std,
                user_baseline=user_baseline, week_idx=wk_b_idx,
                recent_history=[],
            )

            print(f"\n  {wk_pair_name}:")

            for zone_name in ["data_behavior", "network_footprint", "access_pattern", "risk_posture"]:
                # FLAT serialization
                text_a_flat = serialize_zone("user", zone_name, profile, feat_a)
                text_b_flat = serialize_zone("user", zone_name, profile, feat_b)

                # INTERPRETIVE serialization
                text_a_interp = serialize_zone_interpretive("user", zone_name, profile, feat_a, bctx_a)
                text_b_interp = serialize_zone_interpretive("user", zone_name, profile, feat_b, bctx_b)

                # Compute embeddings and drift
                v_a_flat = embedder.embed_text(text_a_flat)
                v_b_flat = embedder.embed_text(text_b_flat)
                v_a_interp = embedder.embed_text(text_a_interp)
                v_b_interp = embedder.embed_text(text_b_interp)

                flat_drift_vec = drift_vector(v_a_flat, v_b_flat)
                interp_drift_vec = drift_vector(v_a_interp, v_b_interp)
                flat_mag = drift_magnitude(v_a_flat, v_b_flat)
                interp_mag = drift_magnitude(v_a_interp, v_b_interp)

                # Align with concepts
                flat_alignments = []
                interp_alignments = []
                for concept in ALL_CONCEPTS:
                    c_vec = embedder.embed_text(concept.description)
                    flat_score = cosine_similarity(flat_drift_vec, c_vec)
                    interp_score = cosine_similarity(interp_drift_vec, c_vec)
                    flat_alignments.append((concept.name, concept.category, flat_score))
                    interp_alignments.append((concept.name, concept.category, interp_score))

                flat_alignments.sort(key=lambda x: x[2], reverse=True)
                interp_alignments.sort(key=lambda x: x[2], reverse=True)

                flat_top = flat_alignments[0] if flat_alignments else ("none", "none", 0.0)
                interp_top = interp_alignments[0] if interp_alignments else ("none", "none", 0.0)

                # Max threat alignment
                flat_max_threat = max((a for a in flat_alignments if a[1] == "threat"),
                                      key=lambda x: x[2], default=("none", "threat", 0.0))
                interp_max_threat = max((a for a in interp_alignments if a[1] == "threat"),
                                         key=lambda x: x[2], default=("none", "threat", 0.0))

                print(f"\n    {zone_name}:")
                print(f"      Flat drift magnitude:   {flat_mag:.6f}")
                print(f"      Interp drift magnitude: {interp_mag:.6f}")
                print(f"      Flat top alignment:     {flat_top[0]} ({flat_top[1]}) = {flat_top[2]:.6f}")
                print(f"      Interp top alignment:   {interp_top[0]} ({interp_top[1]}) = {interp_top[2]:.6f}")
                print(f"      Flat max threat:        {flat_max_threat[0]} = {flat_max_threat[2]:.6f}")
                print(f"      Interp max threat:      {interp_max_threat[0]} = {interp_max_threat[2]:.6f}")

                # Show all alignment scores for the first attack user, first zone
                if uid == ATTACK_USERS[0] and zone_name == "data_behavior":
                    print(f"\n      Full alignment table (flat) for {uid} {zone_name}:")
                    print(f"      {'Concept':<30} {'Cat':<8} {'Score':>10}")
                    for name, cat, score in flat_alignments:
                        print(f"      {name:<30} {cat:<8} {score:>10.6f}")


# ============================================================================
# SECTION 7: Key numbers from tier3_comparison.csv
# ============================================================================

def section7_comparison_diagnostics(comp_df):
    """Pull key diagnostic values from the tier3_comparison results."""
    print(f"\n\n{SEPARATOR}")
    print("SECTION 7: TIER 3 COMPARISON DIAGNOSTICS (from tier3_comparison.csv)")
    print(SEPARATOR)

    for uid in ATTACK_USERS:
        row = comp_df[comp_df["user_id"] == uid]
        if row.empty:
            continue
        row = row.iloc[0]
        attack_info = ATTACK_ENTITIES[uid]

        print(f"\n  {uid} -- {attack_info['name']}:")

        # Concept alignment diagnostics
        concept_diag = row.get("t3_concept_zone_diagnostics", "")
        if not isinstance(concept_diag, str):
            concept_diag = str(concept_diag) if not pd.isna(concept_diag) else ""
        diverge_str = row.get("t3_concept_divergence_strings", "")
        if not isinstance(diverge_str, str):
            diverge_str = str(diverge_str) if not pd.isna(diverge_str) else ""
        threat_zone = row.get("t3_concept_primary_threat_zone", "")
        if not isinstance(threat_zone, str):
            threat_zone = str(threat_zone) if not pd.isna(threat_zone) else ""
        threat_conf = row.get("t3_concept_max_threat_confidence", 0.0)

        print(f"    Concept diagnostics: {concept_diag}")
        print(f"    Divergence strings:  {diverge_str[:200]}...")
        print(f"    Primary threat zone: {threat_zone} (confidence={threat_conf})")

        # Detection results
        det_cols = [
            "t3_velocity_detected", "t3_regime_detected", "t3_zone_divergence_detected",
            "t3_rel_detected", "t3_ctx_detected", "t3_cohort_member",
            "t3_cusum_detected", "t3_zone_threat_detected", "t3_prog_detected",
            "t3_combined_detected",
        ]
        detected = []
        missed = []
        for col in det_cols:
            if col in row.index:
                name = col.replace("t3_", "").replace("_detected", "").replace("_", " ")
                if row[col]:
                    detected.append(name)
                else:
                    missed.append(name)

        print(f"    Detected by: {', '.join(detected) if detected else 'NONE'}")
        print(f"    Missed by:   {', '.join(missed) if missed else 'NONE'}")

        # Key scores
        print(f"    t3_composite_score:       {row.get('t3_composite_score', 0):.4f}")
        print(f"    t3_anomaly_breadth:       {row.get('t3_anomaly_breadth', 0)}")
        print(f"    t3_cusum_max:             {row.get('t3_cusum_max', 0):.6f}")
        print(f"    t3_prog_best_tau:         {row.get('t3_prog_best_tau', 0):.4f}")
        print(f"    t3_zone_threat_best_score:{row.get('t3_zone_threat_best_score', 0):.4f}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    sys.stdout.reconfigure(encoding="utf-8")

    print(SEPARATOR)
    print("TIER 3 ZONE EMBEDDING PIPELINE & CONCEPT ALIGNMENT DEEP TRACE")
    print(f"Attack users: {ATTACK_USERS}")
    print(f"Results dir:  {RESULTS_DIR}")
    print(SEPARATOR)

    # Load pre-computed results
    print("\nLoading pre-computed results...")
    traj_df, structures, comp_df = load_precomputed()
    print(f"  Trajectories: {traj_df.shape}")
    print(f"  Structures:   {len(structures)} entities")
    print(f"  Comparison:   {comp_df.shape}")

    # Re-engineer features for attack users (needed for zone text generation)
    print("\nRe-engineering features for attack users (no API calls)...")
    features_df = build_features_for_attack_users()
    print(f"  Features: {features_df.shape}")

    # Run all sections
    section1_zone_text_comparison(features_df)
    section2_zone_drift_vectors(traj_df, structures)
    section3_concept_alignment_trace()
    section4_weekly_trajectories(traj_df)
    section5_population_comparison(traj_df)
    section6_actual_concept_alignment(features_df)
    section7_comparison_diagnostics(comp_df)

    # Final summary
    print(f"\n\n{SEPARATOR}")
    print("SUMMARY: WHY CONCEPT ALIGNMENT IS BROKEN")
    print(SEPARATOR)
    print("""
  1. MOCKEMBEDDER PRODUCES RANDOM VECTORS: The SHA256-seeded RNG creates
     deterministic but semantically meaningless 1536-d vectors. Any two
     different texts produce near-orthogonal vectors regardless of semantic
     similarity. Drift vectors are random directions in 1536-d space.

  2. RANDOM CONCEPT ALIGNMENT: With random drift vectors and random concept
     vectors, all cosine similarities cluster near 0.0 (expected value = 0,
     std = 1/sqrt(1536) ~ 0.026). The "winning" concept is determined by
     random chance, not semantic meaning. seasonal_variation wins as often
     as data_exfiltration.

  3. FLAT SERIALIZATION IS WEAK EVEN WITH REAL EMBEDDINGS: The flat format
     'restricted_ratio=0.0502' vs 'restricted_ratio=0.1600' looks like a
     minor numeric change to an embedding model. The semantic distance is
     tiny. The interpretive format explicitly states 'CRITICAL ANOMALY...
     pattern strongly consistent with active data exfiltration' -- this
     provides the semantic bridge that real embeddings can leverage.

  4. THE FIX REQUIRES BOTH:
     a) REAL EMBEDDINGS (OpenAI text-embedding-3-small) to create
        semantically meaningful vectors where similar concepts cluster.
     b) INTERPRETIVE SERIALIZATION to translate numeric anomalies into
        threat-language that aligns with concept descriptions.

     The pipeline already HAS interpretive serialization (serialize_zone_
     interpretive). The run_tier3 pipeline already USES it for zone text
     generation (see build_entity_zoo, line ~150). The missing ingredient
     is REAL embeddings via OPENAI_API_KEY.

  5. DETECTION STILL WORKS WITHOUT CONCEPT ALIGNMENT: The drift MAGNITUDE
     metrics (CUSUM, velocity, zone divergence scores) are geometry-based
     and work correctly even with MockEmbedder. They detect that something
     is changing, just not WHAT it is changing toward. This is why
     t3_cusum_detected, t3_velocity_detected, t3_zone_divergence_detected
     still catch attack users, while concept-direction methods do not.
""")


if __name__ == "__main__":
    main()
