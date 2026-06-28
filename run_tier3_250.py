"""Run Tier 3 qualitative embedding pipeline for all 250 users.

Skips Tier 1/2 detection (already run and saved).
Embeds all users in batch, saves to PostgreSQL, runs detection.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
from dotenv import load_dotenv
load_dotenv()

from datetime import date
from pathlib import Path
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from comparison.run_comparison import (
    DATA_DIR, FEATURE_COLS, _build_user_device_map, engineer_weekly_features,
)
from comparison.run_tier3 import (
    RESULTS_DIR, build_entity_zoo, save_embeddings_to_db,
    extract_weekly_trajectories,
)
from models.cyber_entity import Tier3Config
from detection.novelty_features import annotate_qualitative_features, compute_novelty_metrics
from simulator.entities import generate_all

ATTACKS = {"USR-042", "USR-118", "USR-156", "USR-234"}
ATTACK_NAMES = {
    "USR-042": "Volt Typhoon", "USR-118": "Salt Typhoon",
    "USR-156": "Insider", "USR-234": "Slow APT",
}

ROLE_GROUPS = {
    "admin": ["IT Admin", "SysAdmin", "DBA", "Network Engineer",
              "Cloud Architect", "DevOps Engineer", "SRE"],
    "security": ["SOC Operator", "Security Analyst", "CISO"],
    "developer": ["Software Engineer", "Senior Engineer", "Staff Engineer",
                  "ML Engineer", "Data Scientist", "QA Engineer", "Test Lead"],
    "business": ["Accountant", "Analyst", "Account Manager", "Financial Analyst",
                 "Sales Rep", "HR Manager", "HR Specialist", "Recruiter",
                 "General Counsel"],
    "executive": ["CEO", "CFO", "COO", "CTO", "VP Sales"],
}
ROLE_TO_GROUP = {}
for group, roles in ROLE_GROUPS.items():
    for role in roles:
        ROLE_TO_GROUP[role] = group

DRIFT_ZONES = [
    "access_pattern_drift", "data_behavior_drift",
    "network_footprint_drift", "risk_posture_drift",
]


def run_detection(traj_df):
    """Run group-relative detection on trajectory data."""
    traj_df["role_group"] = traj_df["role"].map(ROLE_TO_GROUP)
    all_users = traj_df.user_id.unique()
    user_grp = {uid: traj_df[traj_df.user_id == uid]["role_group"].iloc[0] for uid in all_users}
    weeks = sorted(traj_df.week_idx.unique())

    pivot = {}
    for zone in DRIFT_ZONES:
        if zone not in traj_df.columns:
            continue
        pv = traj_df.pivot_table(index='week_idx', columns='user_id', values=zone, aggfunc='mean')
        pv = pv.reindex(weeks)
        pivot[zone] = pv.rolling(window=4, min_periods=1).mean()

    n_normal = sum(1 for u in all_users if u not in ATTACKS)

    results = {}
    for uid in all_users:
        grp = user_grp.get(uid, "unknown")
        normal_uids = [u for u in all_users if user_grp.get(u) == grp and u not in ATTACKS]
        is_attack = uid in ATTACKS
        zones = {}

        for zone in DRIFT_ZONES:
            if zone not in pivot:
                continue
            pv = pivot[zone]
            nc = [u for u in normal_uids if u in pv.columns]
            if uid not in pv.columns or len(nc) < 2:
                zones[zone] = {"pct_median": 50, "pct_peak": 50, "self_change": 0,
                               "cusum": 0, "ratio": 1}
                continue

            uv = pv[uid].values
            nv = pv[nc].values
            pcts = (nv < uv[:, None]).sum(axis=1) / len(nc) * 100

            med_pct = float(np.median(pcts))
            peak_pct = float(np.max(pcts))

            q1 = pcts[:len(weeks) // 4]
            bl = float(np.mean(q1)) if len(q1) > 0 else med_pct
            cs, pk = 0.0, 0.0
            for p in pcts:
                cs = max(0.0, cs + (p - bl - 10))
                pk = max(pk, cs)

            raw = traj_df[traj_df.user_id == uid].sort_values("week_idx")[zone].values
            med_r = float(np.median(raw))
            mx_r = float(np.max(raw))
            ratio = mx_r / med_r if med_r > 0.001 else mx_r / 0.001

            zones[zone] = {
                "pct_median": med_pct, "pct_peak": peak_pct,
                "self_change": peak_pct - med_pct,
                "cusum": pk, "ratio": ratio,
            }

        results[uid] = {"grp": grp, "is_attack": is_attack, "zones": zones}

    return results


def main():
    t0 = time.time()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set.")
        sys.exit(1)

    from embeddings.embedder import Embedder
    from detection.reference_concepts import ConceptLibrary

    embedder = Embedder(api_key=api_key)
    print("Using REAL OpenAI embeddings (text-embedding-3-small)")

    # Load entities
    entities = generate_all()
    user_ids = entities["users"]["user_id"].tolist()
    user_device_map = _build_user_device_map()

    auth_dir = DATA_DIR / "auth"
    csv_files = sorted(auth_dir.glob("*.csv"))
    first_date = date.fromisoformat(csv_files[0].stem)
    last_date = date.fromisoformat(csv_files[-1].stem)

    # Build role group map from entities
    user_role_map = {}
    users_df = entities["users"]
    for _, u in users_df.iterrows():
        role = u.get("role", "unknown")
        grp = ROLE_TO_GROUP.get(role, "unknown")
        user_role_map[u["user_id"]] = grp

    # Phase 1: Feature engineering with role-aware qualitative extraction
    print(f"\nPhase 1: Feature engineering ({len(user_ids)} users)...")
    features_df = engineer_weekly_features(
        first_date, last_date, user_ids, user_device_map,
        user_role_groups=user_role_map,
    )
    print(f"  {len(features_df)} total feature rows, {features_df.week_idx.nunique()} weeks")

    # Phase 1b: Annotate qualitative features with novelty flags
    print(f"\nPhase 1b: Annotating qualitative features with novelty flags...")
    features_df = annotate_qualitative_features(features_df, user_role_map)
    print(f"  Annotated {len(features_df)} feature rows with novelty flags")

    # Phase 2: Build entity zoo with qualitative embeddings (BATCH)
    print(f"\nPhase 2: Building entity zoo ({len(user_ids)} users)...")
    concept_lib = ConceptLibrary(embedder=embedder)
    concept_lib.embed_concepts()
    config = Tier3Config()

    entity_zoo = build_entity_zoo(
        user_ids, features_df, entities, user_device_map,
        embedder, concept_lib, config,
    )

    # Phase 3: Persist to PostgreSQL
    print(f"\nPhase 3: Saving embeddings to PostgreSQL...")
    n_saved = save_embeddings_to_db(entity_zoo, features_df)
    print(f"  Saved {n_saved:,} embedding snapshots to behavioral_snapshots table")

    # Phase 4: Extract trajectories
    print(f"\nPhase 4: Extracting trajectories...")
    traj_df = extract_weekly_trajectories(entity_zoo, features_df)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    traj_path = RESULTS_DIR / "all250_trajectories.csv"
    traj_df.to_csv(traj_path, index=False)
    print(f"  {len(traj_df)} trajectory rows saved to {traj_path}")

    # Phase 5: Composite Detection
    print(f"\nPhase 5: Composite detection...")
    from detection.composite_scorer import (
        extract_user_features, compute_group_zscores,
        compute_composite_scores, threshold_sweep,
    )
    user_feats = extract_user_features(traj_df)
    zscored = compute_group_zscores(user_feats)

    # Compute novelty persistence metrics from qualitative features
    print(f"  Computing novelty persistence metrics...")
    novelty_df = compute_novelty_metrics(features_df)
    scores = compute_composite_scores(zscored, novelty_df=novelty_df)

    # Attack user details
    print("\n" + "=" * 90)
    print("ATTACK USER COMPOSITE SCORES (250 users, novelty-annotated embeddings)")
    print("=" * 90)
    for uid in sorted(ATTACKS):
        row = scores[scores.uid == uid].iloc[0]
        rank = scores.index[scores.uid == uid][0] + 1
        print(f"\n  {uid} ({ATTACK_NAMES[uid]}) — Rank #{rank}/{len(scores)}, Group: {row.grp}")
        print(f"    Composite:        {row.composite:>8.2f}")
        print(f"    Signal Strength:  {row.signal_strength:>8.2f}")
        print(f"    Breadth (z>1.5):  {int(row.breadth_15):>8d}")
        print(f"    Sustained Signal: {row.sustained_signal:>8.2f}")
        print(f"    Novelty Score:    {row.novelty_score:>8.2f}")

    # Top 40 ranking
    print(f"\n{'='*80}")
    print(f"TOP 40 BY COMPOSITE SCORE")
    print(f"{'='*80}")
    for i, (_, r) in enumerate(scores.head(40).iterrows(), 1):
        tag = f" <-- {ATTACK_NAMES[r.uid]}" if r.uid in ATTACKS else ""
        print(f"  {i:>3}. {r.uid:<10} {r.grp:<12} comp={r.composite:>7.2f} "
              f"(str={r.signal_strength:.1f} br={int(r.breadth_15)} "
              f"sus={r.sustained_signal:.1f} nov={r.novelty_score:.1f}){tag}")

    # Save composite scores for UI
    scores_path = RESULTS_DIR / "composite_scores.csv"
    scores.to_csv(scores_path, index=False)
    print(f"\n  Saved composite scores to {scores_path}")

    # Save novelty metrics for UI
    novelty_path = RESULTS_DIR / "novelty_metrics.csv"
    novelty_df.to_csv(novelty_path, index=False)

    # Save z-scored features for UI
    zscored_path = RESULTS_DIR / "zscored_features.csv"
    zscored.to_csv(zscored_path, index=False)

    # Threshold sweep
    threshold_sweep(scores, attack_set=ATTACKS)

    # Per-zone z-score details for attackers
    z_cols = [c for c in zscored.columns if c.startswith("z_")]
    print(f"\n{'='*80}")
    print("ATTACKER Z-SCORE PROFILES")
    print(f"{'='*80}")
    for uid in sorted(ATTACKS):
        row = zscored[zscored.uid == uid].iloc[0]
        print(f"\n  {uid} ({ATTACK_NAMES[uid]}, {row.grp}):")
        top_z = sorted(z_cols, key=lambda c: abs(row[c]), reverse=True)[:8]
        for c in top_z:
            print(f"    {c:40s} z={row[c]:+.2f}")

    elapsed = time.time() - t0
    stats = embedder.stats()
    print(f"\nTotal time: {elapsed:.1f}s")
    print(f"Embedding stats: {stats['api_calls']} API calls, {stats['cache_hits']} cache hits")
    print(f"DB: {n_saved:,} snapshots stored in PostgreSQL")


if __name__ == "__main__":
    main()
