"""Analyze actual feature values for attack users vs normal users.

Loads weekly feature data, computes z-scores, and prints detailed comparison tables.
If USR-042 is missing from the cached weekly_features.csv, re-engineers its features
from raw CSV data and adds it.

Usage: python scripts/analyze_attack_features.py
"""
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from pathlib import Path
from datetime import date, timedelta

# Import feature engineering from comparison module
from comparison.run_comparison import (
    engineer_weekly_features, FEATURE_COLS, load_week_csvs, _user_features,
    ATTACK_ENTITIES,
)

DATA_DIR = Path("data/generated")
RESULTS_DIR = Path("data/comparison_results")

# All 5 potential attack users
ALL_ATTACK_USERS = {
    "USR-042": {"attack": "ATK-007", "name": "Volt Typhoon LOTL (115-day)", "start": date(2025, 1, 15)},
    "USR-087": {"attack": "ATK-002", "name": "Credential Theft (5-day)", "start": date(2026, 2, 1)},
    "USR-118": {"attack": "ATK-008", "name": "Salt Typhoon Telecom (100-day)", "start": date(2025, 1, 20)},
    "USR-156": {"attack": "ATK-004", "name": "Insider Threat (8-month)", "start": date(2025, 1, 1)},
    "USR-234": {"attack": "ATK-003", "name": "Slow APT (180-day)", "start": date(2025, 4, 1)},
}


def load_or_build_features():
    """Load cached weekly features, adding missing attack users if needed."""
    cached_path = RESULTS_DIR / "weekly_features.csv"

    if cached_path.exists():
        print(f"Loading cached features from {cached_path}")
        df = pd.read_csv(cached_path, low_memory=False)
        print(f"  Loaded: {df.shape[0]} rows, {df['user_id'].nunique()} users, "
              f"weeks {df['week_idx'].min()}-{df['week_idx'].max()}")

        # Check which attack users are missing
        present = set(df["user_id"].unique())
        missing_attacks = [u for u in ALL_ATTACK_USERS if u not in present]

        if missing_attacks:
            print(f"\n  Missing attack users: {missing_attacks}")
            print("  Re-engineering features for missing users...")

            # Get date range from existing data
            auth_dir = DATA_DIR / "auth"
            csv_files = sorted(auth_dir.glob("*.csv"))
            first_date = date.fromisoformat(csv_files[0].stem)
            last_date = date.fromisoformat(csv_files[-1].stem)

            # Build user-device map
            from simulator.entities import generate_all
            entities = generate_all()
            users_df = entities["users"]
            devices_df = entities["devices"]
            user_device_map = {}
            for _, u in users_df.iterrows():
                uid = u["user_id"]
                devs = set()
                if pd.notna(u.get("primary_device_id")):
                    devs.add(u["primary_device_id"])
                if "owner_id" in devices_df.columns:
                    owned = devices_df[devices_df["owner_id"] == uid]["device_id"].tolist()
                    devs.update(owned)
                user_device_map[uid] = list(devs) if devs else []

            for uid in missing_attacks:
                devs = user_device_map.get(uid, [])
                print(f"    {uid} -> devices: {devs}")

            # Engineer features for missing users
            new_features = engineer_weekly_features(
                first_date, last_date + timedelta(days=1),
                missing_attacks, user_device_map
            )
            df = pd.concat([df, new_features], ignore_index=True)
            print(f"  Combined: {df.shape[0]} rows, {df['user_id'].nunique()} users")
    else:
        print("No cached features found. Engineering from scratch (all 250 users)...")
        from simulator.entities import generate_all
        entities = generate_all()
        all_user_ids = entities["users"]["user_id"].tolist()

        auth_dir = DATA_DIR / "auth"
        csv_files = sorted(auth_dir.glob("*.csv"))
        first_date = date.fromisoformat(csv_files[0].stem)
        last_date = date.fromisoformat(csv_files[-1].stem)

        users_df = entities["users"]
        devices_df = entities["devices"]
        user_device_map = {}
        for _, u in users_df.iterrows():
            uid = u["user_id"]
            devs = set()
            if pd.notna(u.get("primary_device_id")):
                devs.add(u["primary_device_id"])
            if "owner_id" in devices_df.columns:
                owned = devices_df[devices_df["owner_id"] == uid]["device_id"].tolist()
                devs.update(owned)
            user_device_map[uid] = list(devs) if devs else []

        df = engineer_weekly_features(first_date, last_date + timedelta(days=1),
                                       all_user_ids, user_device_map)

    return df


def analyze():
    """Main analysis: z-scores, distributions, comparison tables."""
    df = load_or_build_features()

    n_weeks = df["week_idx"].max() + 1
    baseline_end = 9  # weeks 0-8
    monitoring_start = 9  # weeks 9-18

    print(f"\n{'='*100}")
    print(f"FEATURE ANALYSIS: ATTACK USERS vs POPULATION")
    print(f"{'='*100}")
    print(f"Total weeks: {n_weeks} (0-{n_weeks-1})")
    print(f"Baseline period: weeks 0-{baseline_end-1}")
    print(f"Monitoring period: weeks {monitoring_start}-{n_weeks-1}")

    # Identify which attack users are in data and which are active during data window
    attack_users_in_data = [u for u in ALL_ATTACK_USERS if u in df["user_id"].values]
    all_users = df["user_id"].unique()
    normal_users = [u for u in all_users if u not in ALL_ATTACK_USERS]

    print(f"\nAttack users in data: {attack_users_in_data}")
    print(f"Normal users: {len(normal_users)}")

    # Check data window vs attack start dates
    print("\nAttack timing vs data window:")
    for uid in attack_users_in_data:
        info = ALL_ATTACK_USERS[uid]
        print(f"  {uid} ({info['name']}): attack starts {info['start']}, "
              f"{'WITHIN' if info['start'] <= date(2025, 5, 13) else 'OUTSIDE'} data window")

    # =========================================================================
    # SECTION 1: Population distribution during monitoring period
    # =========================================================================
    print(f"\n{'='*100}")
    print("SECTION 1: POPULATION DISTRIBUTION (Monitoring Period, weeks 9-18)")
    print(f"{'='*100}")

    monitoring = df[df["week_idx"] >= monitoring_start]
    baseline = df[df["week_idx"] < baseline_end]

    # Aggregate: mean feature values per user during monitoring period
    user_monitoring_means = monitoring.groupby("user_id")[FEATURE_COLS].mean()
    user_baseline_means = baseline.groupby("user_id")[FEATURE_COLS].mean()

    # Population stats (ALL users during monitoring)
    pop_mean = user_monitoring_means.mean()
    pop_std = user_monitoring_means.std()
    pop_std_safe = pop_std.replace(0, 1e-10)  # avoid division by zero

    print(f"\n{'Feature':<30} {'Mean':>12} {'Std':>12} {'Min':>12} {'P25':>12} "
          f"{'P50':>12} {'P75':>12} {'P95':>12} {'P99':>12} {'Max':>12}")
    print("-" * 150)

    for feat in FEATURE_COLS:
        vals = user_monitoring_means[feat]
        print(f"{feat:<30} {vals.mean():>12.2f} {vals.std():>12.2f} {vals.min():>12.2f} "
              f"{vals.quantile(0.25):>12.2f} {vals.quantile(0.50):>12.2f} "
              f"{vals.quantile(0.75):>12.2f} {vals.quantile(0.95):>12.2f} "
              f"{vals.quantile(0.99):>12.2f} {vals.max():>12.2f}")

    # =========================================================================
    # SECTION 2: Baseline vs Monitoring comparison for each attack user
    # =========================================================================
    print(f"\n{'='*100}")
    print("SECTION 2: ATTACK USER BASELINE vs MONITORING PERIOD COMPARISON")
    print(f"{'='*100}")

    for uid in attack_users_in_data:
        info = ALL_ATTACK_USERS[uid]
        print(f"\n--- {uid}: {info['name']} (attack starts {info['start']}) ---")

        if uid not in user_baseline_means.index or uid not in user_monitoring_means.index:
            print(f"  WARNING: User {uid} missing from baseline or monitoring data")
            continue

        b = user_baseline_means.loc[uid]
        m = user_monitoring_means.loc[uid]

        print(f"\n{'Feature':<30} {'Baseline':>12} {'Monitoring':>12} {'Delta':>12} {'%Change':>12}")
        print("-" * 78)

        for feat in FEATURE_COLS:
            bv = b[feat]
            mv = m[feat]
            delta = mv - bv
            pct = (delta / max(abs(bv), 1e-6)) * 100
            marker = " ***" if abs(pct) > 50 else (" **" if abs(pct) > 25 else "")
            print(f"{feat:<30} {bv:>12.4f} {mv:>12.4f} {delta:>+12.4f} {pct:>+11.1f}%{marker}")

    # =========================================================================
    # SECTION 3: Z-scores of attack users relative to population
    # =========================================================================
    print(f"\n{'='*100}")
    print("SECTION 3: Z-SCORES OF ATTACK USERS vs POPULATION (Monitoring Period)")
    print(f"{'='*100}")
    print("Z-score = (user_monitoring_mean - population_mean) / population_std")
    print("Population includes ALL users (attack + normal) to simulate real-world conditions\n")

    # Compute z-scores for ALL users
    all_zscores = (user_monitoring_means - pop_mean) / pop_std_safe

    # Print comparison table for attack users
    header = f"{'Feature':<30}"
    for uid in attack_users_in_data:
        header += f" {uid:>12}"
    header += f" {'Pop Mean':>12} {'Pop Std':>12}"
    print(header)
    print("-" * (30 + 14 * len(attack_users_in_data) + 26))

    for feat in FEATURE_COLS:
        line = f"{feat:<30}"
        for uid in attack_users_in_data:
            if uid in user_monitoring_means.index:
                val = user_monitoring_means.loc[uid, feat]
                z = all_zscores.loc[uid, feat]
                # Show value and z-score
                if abs(z) > 3:
                    marker = "!!!"
                elif abs(z) > 2:
                    marker = "** "
                else:
                    marker = "   "
                line += f" {val:>8.2f}({z:>+.1f}){marker}"
            else:
                line += f" {'N/A':>12}"
        line += f" {pop_mean[feat]:>12.2f} {pop_std[feat]:>12.2f}"
        print(line)

    # =========================================================================
    # SECTION 4: Summary per attack user - max z-scores and flagged features
    # =========================================================================
    print(f"\n{'='*100}")
    print("SECTION 4: ATTACK USER Z-SCORE SUMMARY")
    print(f"{'='*100}")

    for uid in attack_users_in_data:
        if uid not in all_zscores.index:
            continue

        info = ALL_ATTACK_USERS[uid]
        z_row = all_zscores.loc[uid]

        print(f"\n{'='*80}")
        print(f"{uid}: {info['name']}")
        print(f"Attack: {info['attack']}, starts {info['start']}")
        print(f"{'='*80}")

        # Sort features by |z-score|
        sorted_features = z_row.abs().sort_values(ascending=False)
        max_abs_z = sorted_features.iloc[0]
        max_feat = sorted_features.index[0]

        print(f"  Max |z-score|: {max_abs_z:.3f} (feature: {max_feat})")

        z_gt3 = [(f, z_row[f]) for f in sorted_features.index if abs(z_row[f]) > 3]
        z_gt2 = [(f, z_row[f]) for f in sorted_features.index if 2 < abs(z_row[f]) <= 3]
        z_gt1 = [(f, z_row[f]) for f in sorted_features.index if 1 < abs(z_row[f]) <= 2]

        print(f"\n  Features with |z| > 3 ({len(z_gt3)}):")
        if z_gt3:
            for f, z in z_gt3:
                val = user_monitoring_means.loc[uid, f]
                pm = pop_mean[f]
                ps = pop_std[f]
                print(f"    {f:<30} z={z:>+7.3f}  value={val:>12.4f}  pop_mean={pm:>12.4f}  pop_std={ps:>12.4f}")
        else:
            print(f"    NONE")

        print(f"\n  Features with 2 < |z| <= 3 ({len(z_gt2)}):")
        if z_gt2:
            for f, z in z_gt2:
                val = user_monitoring_means.loc[uid, f]
                pm = pop_mean[f]
                ps = pop_std[f]
                print(f"    {f:<30} z={z:>+7.3f}  value={val:>12.4f}  pop_mean={pm:>12.4f}  pop_std={ps:>12.4f}")
        else:
            print(f"    NONE")

        print(f"\n  Features with 1 < |z| <= 2 ({len(z_gt1)}):")
        if z_gt1:
            for f, z in z_gt1:
                val = user_monitoring_means.loc[uid, f]
                print(f"    {f:<30} z={z:>+7.3f}  value={val:>12.4f}")
        else:
            print(f"    NONE")

    # =========================================================================
    # SECTION 5: Would Z-Score method detect these users at |z| > 3 threshold?
    # =========================================================================
    print(f"\n{'='*100}")
    print("SECTION 5: Z-SCORE DETECTION ANALYSIS")
    print(f"{'='*100}")

    # For each user, check if ANY feature has |z| > 3
    max_z_per_user = all_zscores.abs().max(axis=1)
    detected_z3 = max_z_per_user[max_z_per_user > 3].index.tolist()
    detected_z2 = max_z_per_user[max_z_per_user > 2].index.tolist()

    print(f"\nUsers with max |z| > 3: {len(detected_z3)} / {len(max_z_per_user)}")
    print(f"Users with max |z| > 2: {len(detected_z2)} / {len(max_z_per_user)}")

    # Classification breakdown
    attack_set = set(ALL_ATTACK_USERS.keys())
    tp_z3 = [u for u in detected_z3 if u in attack_set]
    fp_z3 = [u for u in detected_z3 if u not in attack_set]
    fn_z3 = [u for u in attack_users_in_data if u not in detected_z3]

    print(f"\n  At |z| > 3 threshold:")
    print(f"    True Positives  (attack, detected):    {len(tp_z3)} -> {tp_z3}")
    print(f"    False Positives (normal, detected):    {len(fp_z3)} -> {fp_z3}")
    print(f"    False Negatives (attack, missed):      {len(fn_z3)} -> {fn_z3}")
    print(f"    True Negatives  (normal, not detected): {len(normal_users) - len(fp_z3)}")
    total_normal = len([u for u in all_users if u not in attack_set])
    fp_rate = len(fp_z3) / max(total_normal, 1)
    print(f"    FP Rate: {fp_rate:.1%} ({len(fp_z3)}/{total_normal})")

    tp_z2 = [u for u in detected_z2 if u in attack_set]
    fp_z2 = [u for u in detected_z2 if u not in attack_set]
    fn_z2 = [u for u in attack_users_in_data if u not in detected_z2]

    print(f"\n  At |z| > 2 threshold:")
    print(f"    True Positives  (attack, detected):    {len(tp_z2)} -> {tp_z2}")
    print(f"    False Positives (normal, detected):    {len(fp_z2)} -> {fp_z2}")
    print(f"    False Negatives (attack, missed):      {len(fn_z2)} -> {fn_z2}")
    fp_rate2 = len(fp_z2) / max(total_normal, 1)
    print(f"    FP Rate: {fp_rate2:.1%} ({len(fp_z2)}/{total_normal})")

    # =========================================================================
    # SECTION 6: All users ranked by max |z-score|
    # =========================================================================
    print(f"\n{'='*100}")
    print("SECTION 6: ALL USERS RANKED BY MAX |Z-SCORE| (Top 25)")
    print(f"{'='*100}")

    ranked = max_z_per_user.sort_values(ascending=False)
    print(f"\n{'Rank':>5} {'User':>10} {'Max|Z|':>10} {'Is Attack':>10} {'Top Feature':>30} {'Value':>12} {'Pop Mean':>12}")
    print("-" * 95)

    for i, (uid, mz) in enumerate(ranked.head(25).items()):
        is_atk = "ATTACK" if uid in attack_set else ""
        top_feat = all_zscores.loc[uid].abs().idxmax()
        top_val = user_monitoring_means.loc[uid, top_feat]
        pm = pop_mean[top_feat]
        atk_name = ""
        if uid in ALL_ATTACK_USERS:
            atk_name = f" ({ALL_ATTACK_USERS[uid]['name'][:25]})"
        print(f"{i+1:>5} {uid:>10} {mz:>10.3f} {is_atk:>10} {top_feat:>30} {top_val:>12.2f} {pm:>12.2f}{atk_name}")

    # =========================================================================
    # SECTION 7: Temporal Z-Score (self-baseline) for attack users
    # =========================================================================
    print(f"\n{'='*100}")
    print("SECTION 7: SELF-BASELINE Z-SCORES (User's own monitoring vs baseline)")
    print(f"{'='*100}")
    print("This shows how each user's monitoring behavior deviates from their OWN baseline.\n")

    for uid in attack_users_in_data:
        if uid not in user_baseline_means.index or uid not in user_monitoring_means.index:
            continue

        info = ALL_ATTACK_USERS[uid]
        b_mean = user_baseline_means.loc[uid]
        b_vals = baseline[baseline["user_id"] == uid][FEATURE_COLS]
        b_std = b_vals.std().replace(0, 1e-6)
        m_mean = user_monitoring_means.loc[uid]

        self_z = (m_mean - b_mean) / b_std

        print(f"\n--- {uid}: {info['name']} ---")
        sorted_self = self_z.abs().sort_values(ascending=False)
        print(f"  Max self-|z|: {sorted_self.iloc[0]:.3f} ({sorted_self.index[0]})")

        print(f"\n  {'Feature':<30} {'Baseline':>12} {'Monitoring':>12} {'Self Z':>10}")
        print(f"  {'-'*66}")

        for feat in sorted_self.index:
            sz = self_z[feat]
            marker = " !!!" if abs(sz) > 3 else (" ** " if abs(sz) > 2 else "")
            print(f"  {feat:<30} {b_mean[feat]:>12.4f} {m_mean[feat]:>12.4f} {sz:>+10.3f}{marker}")

    # =========================================================================
    # SECTION 8: Week-by-week trajectory for attack users on their top features
    # =========================================================================
    print(f"\n{'='*100}")
    print("SECTION 8: WEEKLY TRAJECTORY FOR TOP FEATURES (Attack Users)")
    print(f"{'='*100}")

    for uid in attack_users_in_data:
        if uid not in all_zscores.index:
            continue

        info = ALL_ATTACK_USERS[uid]
        z_row = all_zscores.loc[uid]
        top_feats = z_row.abs().sort_values(ascending=False).head(5).index.tolist()

        user_weeks = df[df["user_id"] == uid].sort_values("week_idx")

        print(f"\n--- {uid}: {info['name']} ---")
        print(f"  Top 5 features by population |z-score|:")

        header = f"  {'Week':>5}"
        for f in top_feats:
            short = f[:18]
            print(f"    {f}: z={z_row[f]:+.3f}")
            header += f" {short:>18}"
        print()
        print(header)
        print(f"  {'-'*(5 + 19*len(top_feats))}")

        for _, row in user_weeks.iterrows():
            wi = int(row["week_idx"])
            marker = " <-- monitoring" if wi == monitoring_start else ""
            line = f"  {wi:>5}"
            for f in top_feats:
                line += f" {row[f]:>18.4f}"
            line += marker
            print(line)

    # =========================================================================
    # SECTION 9: Cross-feature correlation analysis
    # =========================================================================
    print(f"\n{'='*100}")
    print("SECTION 9: MULTI-FEATURE ANOMALY (Mahalanobis-like)")
    print(f"{'='*100}")
    print("Composite z-score = sqrt(mean(z^2)) across all features (RMS z-score)\n")

    rms_z = np.sqrt((all_zscores ** 2).mean(axis=1))
    rms_ranked = rms_z.sort_values(ascending=False)

    print(f"{'Rank':>5} {'User':>10} {'RMS Z':>10} {'Max|Z|':>10} {'Is Attack':>10}")
    print("-" * 50)
    for i, (uid, rz) in enumerate(rms_ranked.head(25).items()):
        mz = max_z_per_user[uid]
        is_atk = "ATTACK" if uid in attack_set else ""
        print(f"{i+1:>5} {uid:>10} {rz:>10.3f} {mz:>10.3f} {is_atk:>10}")

    print(f"\n\n{'='*100}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*100}")


if __name__ == "__main__":
    analyze()
