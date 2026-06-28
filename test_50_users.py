"""Test qualitative embedding approach on 50 users including all 4 attackers."""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
from dotenv import load_dotenv
load_dotenv()

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from comparison.run_comparison import (
    DATA_DIR, FEATURE_COLS, _build_user_device_map, engineer_weekly_features,
)
from comparison.run_tier3 import (
    RESULTS_DIR, build_entity_zoo, extract_weekly_trajectories,
)
from models.cyber_entity import Tier3Config
from simulator.entities import generate_all

ATTACKS = {"USR-042", "USR-118", "USR-156", "USR-234"}
ATTACK_NAMES = {
    "USR-042": "Volt Typhoon", "USR-118": "Salt Typhoon",
    "USR-156": "Insider", "USR-234": "Slow APT",
}
DRIFT_ZONES = [
    "access_pattern_drift", "data_behavior_drift",
    "network_footprint_drift", "risk_posture_drift",
]


def select_50_users(entities):
    """Pick 50 users: all 4 attackers + sampled normals from each group."""
    users_df = entities["users"]
    rng = np.random.default_rng(42)

    # Group users by role category
    groups = {}
    for _, row in users_df.iterrows():
        uid = row["user_id"]
        role_cat = row.get("role_category", "unknown")
        groups.setdefault(role_cat, []).append(uid)

    selected = set(ATTACKS)
    target = 50

    # Sample proportionally from each group, excluding attackers
    remaining = target - len(selected)
    group_names = sorted(groups.keys())
    normal_per_group = {}
    for g in group_names:
        normal_per_group[g] = [u for u in groups[g] if u not in ATTACKS]

    total_normal = sum(len(v) for v in normal_per_group.values())
    for g in group_names:
        n = max(3, int(remaining * len(normal_per_group[g]) / total_normal))
        sampled = rng.choice(normal_per_group[g], size=min(n, len(normal_per_group[g])), replace=False)
        selected.update(sampled)

    # Trim to 50 if over
    selected = list(selected)[:target]
    print(f"Selected {len(selected)} users:")
    for g in group_names:
        g_users = [u for u in selected if u in groups.get(g, [])]
        atk = [u for u in g_users if u in ATTACKS]
        print(f"  {g}: {len(g_users)} users ({len(atk)} attackers: {atk})")

    return selected


def run_detection(traj_df):
    """Run group-relative detection on trajectory data."""
    all_users = traj_df.user_id.unique()
    # Assign groups from trajectory
    user_grp = {}
    for uid in all_users:
        rows = traj_df[traj_df.user_id == uid]
        for col in ["ace_group", "role_group", "role_category"]:
            if col in rows.columns:
                user_grp[uid] = rows[col].iloc[0]
                grp_col = col
                break

    weeks = sorted(traj_df.week_idx.unique())

    # Pivot + rolling per zone
    pivot = {}
    for zone in DRIFT_ZONES:
        if zone not in traj_df.columns:
            continue
        pv = traj_df.pivot_table(index='week_idx', columns='user_id', values=zone, aggfunc='mean')
        pv = pv.reindex(weeks)
        pivot[zone] = pv.rolling(window=4, min_periods=1).mean()

    n_normal = sum(1 for u in all_users if u not in ATTACKS)

    # Per-user detection metrics
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
            if uid not in pv.columns or len(nc) == 0:
                zones[zone] = {"pct_median": 50, "pct_peak": 50, "self_change": 0,
                               "cusum": 0, "ratio": 1}
                continue

            uv = pv[uid].values
            nv = pv[nc].values
            pcts = (nv < uv[:, None]).sum(axis=1) / len(nc) * 100

            med_pct = float(np.median(pcts))
            peak_pct = float(np.max(pcts))

            # CUSUM with first-quarter baseline
            q1 = pcts[:len(weeks) // 4]
            bl = float(np.mean(q1)) if len(q1) > 0 else med_pct
            cs, pk = 0.0, 0.0
            for p in pcts:
                cs = max(0.0, cs + (p - bl - 10))
                pk = max(pk, cs)

            # Self-ratio
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
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set.")
        sys.exit(1)

    from embeddings.embedder import Embedder
    from detection.reference_concepts import ConceptLibrary

    embedder = Embedder(api_key=api_key)
    print("Using REAL OpenAI embeddings (text-embedding-3-small)")

    entities = generate_all()
    user_ids = select_50_users(entities)
    user_device_map = _build_user_device_map()

    auth_dir = DATA_DIR / "auth"
    csv_files = sorted(auth_dir.glob("*.csv"))
    first_date = date.fromisoformat(csv_files[0].stem)
    last_date = date.fromisoformat(csv_files[-1].stem)

    # Feature engineering for ALL users (needed for population z-scores)
    print(f"\nPhase 1: Feature engineering (all 250 users for population stats)...")
    all_user_ids = entities["users"]["user_id"].tolist()
    features_df = engineer_weekly_features(first_date, last_date, all_user_ids, user_device_map)
    print(f"  {len(features_df)} total feature rows")

    # Verify qualitative features exist
    sample = features_df[features_df.user_id == "USR-234"].iloc[15]
    print(f"\n  Sample USR-234 week 15 qualitative features:")
    print(f"    qual_file_dirs: {sample.get('qual_file_dirs', 'MISSING')}")
    print(f"    qual_net_ext_ips: {sample.get('qual_net_ext_ips', 'MISSING')}")
    print(f"    qual_dns_domains: {sample.get('qual_dns_domains', 'MISSING')}")

    # Show a normal developer for comparison
    normal_devs = [u for u in all_user_ids if u not in ATTACKS]
    sample_norm = features_df[features_df.user_id == normal_devs[10]].iloc[15]
    print(f"\n  Sample {normal_devs[10]} week 15 qualitative features:")
    print(f"    qual_file_dirs: {sample_norm.get('qual_file_dirs', 'MISSING')}")
    print(f"    qual_net_ext_ips: {sample_norm.get('qual_net_ext_ips', 'MISSING')}")
    print(f"    qual_dns_domains: {sample_norm.get('qual_dns_domains', 'MISSING')}")

    # Embed only the 50 selected users
    print(f"\nPhase 2: Embedding {len(user_ids)} users...")
    concept_lib = ConceptLibrary(embedder=embedder)
    concept_lib.embed_concepts()
    config = Tier3Config()

    entity_zoo = build_entity_zoo(
        user_ids, features_df, entities, user_device_map,
        embedder, concept_lib, config,
    )

    # Persist embeddings to PostgreSQL
    from comparison.run_tier3 import save_embeddings_to_db
    print(f"\nPhase 2b: Saving embeddings to PostgreSQL...", flush=True)
    n_saved = save_embeddings_to_db(entity_zoo, features_df)
    print(f"  Saved {n_saved:,} embedding snapshots to behavioral_snapshots table", flush=True)

    print(f"\nPhase 3: Extracting trajectories...")
    traj_df = extract_weekly_trajectories(entity_zoo, features_df)
    print(f"  {len(traj_df)} trajectory rows")

    # Save
    out_path = RESULTS_DIR / "test50_trajectories.csv"
    traj_df.to_csv(out_path, index=False)
    print(f"  Saved to {out_path}")

    # Run detection
    print(f"\nPhase 4: Detection...")
    results = run_detection(traj_df)

    # Show attack user results
    print("\n" + "=" * 90)
    print("ATTACK USER DETECTION RESULTS")
    print("=" * 90)
    for uid in sorted(ATTACKS):
        r = results[uid]
        print(f"\n{uid} ({ATTACK_NAMES[uid]}) - group: {r['grp']}")
        print(f"  {'Zone':<25} {'MedPct':>7} {'PeakPct':>8} {'SelfChg':>8} {'CUSUM':>8} {'Ratio':>8}")
        print(f"  {'-'*68}")
        for zone in DRIFT_ZONES:
            if zone not in r['zones']:
                continue
            zn = zone.replace('_drift', '')
            z = r['zones'][zone]
            print(f"  {zn:<25} {z['pct_median']:>6.1f}% {z['pct_peak']:>7.1f}% {z['self_change']:>+7.1f} {z['cusum']:>8.1f} {z['ratio']:>7.1f}x")

    # Ranking by max CUSUM
    print(f"\n{'='*80}")
    print(f"RANKING BY MAX CUSUM (all {len(results)} users)")
    print(f"{'='*80}")
    ranked = sorted(results.items(),
                    key=lambda x: max((v['cusum'] for v in x[1]['zones'].values()), default=0),
                    reverse=True)
    for i, (uid, r) in enumerate(ranked[:30], 1):
        max_cusum = max((v['cusum'] for v in r['zones'].values()), default=0)
        best_zone = max(r['zones'], key=lambda z: r['zones'][z]['cusum']).replace('_drift','')
        status = f"<-- {ATTACK_NAMES[uid]}" if uid in ATTACKS else ""
        print(f"  {i:>3}. {uid:<10} {r['grp']:<12} cusum={max_cusum:>8.1f} ({best_zone})  {status}")

    # Ranking by max self_change
    print(f"\n{'='*80}")
    print(f"RANKING BY MAX SELF-CHANGE")
    print(f"{'='*80}")
    ranked_sc = sorted(results.items(),
                       key=lambda x: max((v['self_change'] for v in x[1]['zones'].values()), default=0),
                       reverse=True)
    for i, (uid, r) in enumerate(ranked_sc[:30], 1):
        max_sc = max((v['self_change'] for v in r['zones'].values()), default=0)
        best_zone = max(r['zones'], key=lambda z: r['zones'][z]['self_change']).replace('_drift','')
        status = f"<-- {ATTACK_NAMES[uid]}" if uid in ATTACKS else ""
        print(f"  {i:>3}. {uid:<10} {r['grp']:<12} self_change={max_sc:>+7.1f} ({best_zone})  {status}")

    stats = embedder.stats()
    print(f"\nEmbedding stats: {stats['api_calls']} API calls, {stats['cache_hits']} cache hits")


if __name__ == "__main__":
    main()
