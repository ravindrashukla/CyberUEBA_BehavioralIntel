"""Round 2 Distribution Audit: Deep analysis of feature distributions in the CyberUEBA simulator.

Analyses:
  1. Feature distribution shapes (mean, std, skewness, kurtosis, unique values, etc.)
  2. Bimodality detection for endpoint features (DEV-001 shared vs unique devices)
  3. Feature correlation with attack status in the test period
  4. IsolationForest decision analysis with feature-level contribution
  5. LOF neighborhood analysis with nearest-neighbor inspection

Usage: python scripts/audit_round2_distributions.py
"""
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from datetime import date, timedelta
from pathlib import Path
from scipy import stats as sp_stats
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from scipy.spatial.distance import cdist

from comparison.run_comparison import (
    DATA_DIR,
    ATTACK_ENTITIES,
    FEATURE_COLS,
    _build_user_device_map,
    engineer_weekly_features,
)
from simulator.entities import generate_all

# ---------------------------------------------------------------------------
# Setup: load or build features
# ---------------------------------------------------------------------------
RESULTS_DIR = Path("data/comparison_results")
CACHED_FEATURES = RESULTS_DIR / "weekly_features.csv"


def load_features(n_users: int = 250) -> pd.DataFrame:
    """Load cached weekly features or engineer from scratch.

    If the cached file has fewer than n_users, re-engineer from scratch
    to get the full population.
    """
    need_rebuild = True
    if CACHED_FEATURES.exists():
        df = pd.read_csv(CACHED_FEATURES, low_memory=False)
        existing_users = df["user_id"].nunique()
        missing_attacks = [u for u in ATTACK_ENTITIES if u not in df["user_id"].values]
        print(f"Cached features: {df.shape[0]} rows, {existing_users} users, "
              f"weeks 0-{int(df['week_idx'].max())}")
        if existing_users >= n_users and not missing_attacks:
            print(f"  Cached data has >= {n_users} users and all attack users. Using as-is.")
            return df
        else:
            print(f"  Need {n_users} users (have {existing_users}), "
                  f"missing attacks: {missing_attacks}")
            print(f"  Re-engineering from scratch...")

    entities = generate_all()
    all_user_ids = entities["users"]["user_id"].tolist()

    # Ensure attack users are included and at the front
    priority = [u for u in ATTACK_ENTITIES if u in all_user_ids]
    remaining = [u for u in all_user_ids if u not in priority]
    np.random.seed(42)
    sample_size = min(n_users - len(priority), len(remaining))
    sampled = list(np.random.choice(remaining, size=max(0, sample_size), replace=False))
    user_ids = priority + sampled
    print(f"  Selected {len(user_ids)} users ({len(priority)} attack + {len(sampled)} normal)")

    auth_dir = DATA_DIR / "auth"
    csv_files = sorted(auth_dir.glob("*.csv"))
    first_date = date.fromisoformat(csv_files[0].stem)
    last_date = date.fromisoformat(csv_files[-1].stem)
    udm = _build_user_device_map()

    df = engineer_weekly_features(first_date, last_date + timedelta(days=1),
                                   user_ids, udm)

    # Cache for next time
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(CACHED_FEATURES, index=False)
    print(f"  Cached to {CACHED_FEATURES}")
    return df


def build_device_groups(user_ids):
    """Classify users into DEV-001 (shared) vs unique-device groups."""
    entities = generate_all()
    users_df = entities["users"]
    devices_df = entities["devices"]

    # Reproduce the primary_device_id logic from entities.py
    # generate_all() already enriches users with primary_device_id
    uid_to_primary = {}
    primary_map = users_df.set_index("user_id")["primary_device_id"]
    for uid in user_ids:
        if uid in primary_map.index:
            uid_to_primary[uid] = primary_map[uid]
        else:
            uid_to_primary[uid] = devices_df["device_id"].iloc[0]  # DEV-001

    dev001_users = [u for u, d in uid_to_primary.items() if d == "DEV-001"]
    unique_users = [u for u, d in uid_to_primary.items() if d != "DEV-001"]
    return dev001_users, unique_users, uid_to_primary


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    features_df = load_features()
    user_ids = features_df["user_id"].unique().tolist()
    n_weeks = int(features_df["week_idx"].max()) + 1

    BASELINE_END = 9   # weeks 0-8
    TEST_START = 9      # weeks 9-18

    baseline_df = features_df[features_df["week_idx"] < BASELINE_END]
    test_df = features_df[features_df["week_idx"] >= TEST_START]

    # Per-user baseline means
    baseline_agg = baseline_df.groupby("user_id")[FEATURE_COLS].mean().reindex(user_ids).fillna(0)
    test_agg = test_df.groupby("user_id")[FEATURE_COLS].mean().reindex(user_ids).fillna(0)

    attack_uids = [u for u in ATTACK_ENTITIES if u in user_ids]
    normal_uids = [u for u in user_ids if u not in ATTACK_ENTITIES]

    print(f"\nDataset: {len(user_ids)} users, {n_weeks} weeks")
    print(f"Baseline: weeks 0-{BASELINE_END - 1}, Test: weeks {TEST_START}-{n_weeks - 1}")
    print(f"Attack users: {attack_uids}")
    print(f"Normal users: {len(normal_uids)}")

    # ===========================================================================
    # SECTION 1: FEATURE DISTRIBUTION SHAPES (Baseline period)
    # ===========================================================================
    print("\n" + "=" * 120)
    print("SECTION 1: FEATURE DISTRIBUTION SHAPES (Baseline period, mean-aggregated per user)")
    print("=" * 120)

    bl = baseline_agg  # shape: (n_users, 23)

    header = (f"{'Feature':<28} {'Mean':>8} {'Std':>8} {'Skew':>7} {'Kurt':>7} "
              f"{'Uniq':>5} {'%Modal':>7} {'#Zero':>6} "
              f"{'Min':>9} {'P5':>9} {'P25':>9} {'P50':>9} {'P75':>9} {'P95':>9} {'Max':>9}")
    print(header)
    print("-" * len(header))

    for feat in FEATURE_COLS:
        vals = bl[feat].values
        mean = np.mean(vals)
        std = np.std(vals, ddof=1)
        skew = float(sp_stats.skew(vals, nan_policy="omit"))
        kurt = float(sp_stats.kurtosis(vals, nan_policy="omit"))

        # Unique values (rounded to 4 decimals to handle floating point)
        rounded = np.round(vals, 4)
        n_unique = len(np.unique(rounded))

        # Modal value percentage
        from collections import Counter
        counts = Counter(rounded)
        modal_val, modal_count = counts.most_common(1)[0]
        pct_modal = 100.0 * modal_count / len(vals)

        # Zero count
        n_zero = int((np.abs(vals) < 1e-9).sum())

        pcts = np.percentile(vals, [0, 5, 25, 50, 75, 95, 100])

        print(f"{feat:<28} {mean:>8.3f} {std:>8.3f} {skew:>7.2f} {kurt:>7.2f} "
              f"{n_unique:>5d} {pct_modal:>6.1f}% {n_zero:>6d} "
              f"{pcts[0]:>9.3f} {pcts[1]:>9.3f} {pcts[2]:>9.3f} {pcts[3]:>9.3f} "
              f"{pcts[4]:>9.3f} {pcts[5]:>9.3f} {pcts[6]:>9.3f}")

    # Highlight problematic features
    print("\n--- FLAGGED FEATURES ---")
    for feat in FEATURE_COLS:
        vals = bl[feat].values
        std = np.std(vals, ddof=1)
        rounded = np.round(vals, 4)
        n_unique = len(np.unique(rounded))
        n_zero = int((np.abs(vals) < 1e-9).sum())
        pct_zero = 100.0 * n_zero / len(vals)

        flags = []
        if std < 0.5:
            flags.append(f"LOW_STD={std:.4f}")
        if n_unique <= 10:
            flags.append(f"PSEUDO_CATEGORICAL(uniq={n_unique})")
        if pct_zero > 40:
            flags.append(f"ZERO_INFLATED({pct_zero:.1f}%)")
        skew = float(sp_stats.skew(vals, nan_policy="omit"))
        if abs(skew) > 2:
            flags.append(f"HIGH_SKEW={skew:.2f}")

        if flags:
            print(f"  {feat:<28} {', '.join(flags)}")

    # ===========================================================================
    # SECTION 2: BIMODALITY DETECTION (endpoint features)
    # ===========================================================================
    print("\n" + "=" * 120)
    print("SECTION 2: BIMODALITY DETECTION -- DEV-001 users (shared device) vs unique-device users")
    print("=" * 120)

    dev001_users, unique_users, uid_to_primary = build_device_groups(user_ids)

    # Filter to only those in our user_ids set
    dev001_users = [u for u in dev001_users if u in baseline_agg.index]
    unique_users = [u for u in unique_users if u in baseline_agg.index]

    print(f"DEV-001 users: {len(dev001_users)}")
    print(f"Unique-device users: {len(unique_users)}")

    endpoint_features = [
        "endpoint_total", "endpoint_max_risk", "endpoint_mean_risk",
        "endpoint_unique_processes", "endpoint_suspicious_ratio",
    ]
    # Also check network/DNS features since they are device-linked
    device_linked = endpoint_features + [
        "net_bytes_out", "net_unique_dsts", "net_external_ratio",
        "dns_unique_domains", "dns_nxdomain_ratio",
    ]

    print(f"\n{'Feature':<28} | {'DEV-001 Group':^36} | {'Unique-Device Group':^36} | {'Bimodal?':>9}")
    print(f"{'':28} | {'Mean':>8} {'Std':>8} {'%Zero':>7} {'P50':>9} | {'Mean':>8} {'Std':>8} {'%Zero':>7} {'P50':>9} |")
    print("-" * 120)

    for feat in device_linked:
        v1 = bl.loc[dev001_users, feat].values if dev001_users else np.array([])
        v2 = bl.loc[unique_users, feat].values if unique_users else np.array([])

        def grp_stats(v):
            if len(v) == 0:
                return 0, 0, 0, 0
            return np.mean(v), np.std(v, ddof=1) if len(v) > 1 else 0, 100.0 * (np.abs(v) < 1e-9).sum() / len(v), np.median(v)

        m1, s1, z1, p1 = grp_stats(v1)
        m2, s2, z2, p2 = grp_stats(v2)

        # Bimodality test: means differ by > 1 combined std, or zero-rate differs by > 30pp
        combined_std = np.std(np.concatenate([v1, v2]), ddof=1) if len(v1) + len(v2) > 1 else 1
        bimodal = ""
        if combined_std > 1e-9 and abs(m1 - m2) > combined_std:
            bimodal = "YES"
        elif abs(z1 - z2) > 30:
            bimodal = "YES(zero)"

        print(f"{feat:<28} | {m1:>8.3f} {s1:>8.3f} {z1:>6.1f}% {p1:>9.3f} | "
              f"{m2:>8.3f} {s2:>8.3f} {z2:>6.1f}% {p2:>9.3f} | {bimodal:>9}")

    # Show which attack users are on DEV-001 vs unique devices
    print("\n--- Attack user device assignments ---")
    for uid in attack_uids:
        dev = uid_to_primary.get(uid, "UNKNOWN")
        group = "DEV-001 (shared)" if dev == "DEV-001" else f"{dev} (unique)"
        print(f"  {uid} ({ATTACK_ENTITIES[uid]['name']}): {group}")

    # ===========================================================================
    # SECTION 3: FEATURE CORRELATION WITH ATTACK STATUS (Test period)
    # ===========================================================================
    print("\n" + "=" * 120)
    print("SECTION 3: FEATURE CORRELATION WITH ATTACK STATUS (Test period, rank-biserial)")
    print("=" * 120)

    # Labels: 1 for attack, 0 for normal
    labels = np.array([1 if u in ATTACK_ENTITIES else 0 for u in test_agg.index])
    attack_mask = labels == 1
    normal_mask = labels == 0

    print(f"\nAttack users in test_agg: {int(attack_mask.sum())}")
    print(f"Normal users in test_agg: {int(normal_mask.sum())}")

    results = []
    for feat in FEATURE_COLS:
        vals = test_agg[feat].values
        atk_vals = vals[attack_mask]
        nrm_vals = vals[normal_mask]

        # Rank-biserial correlation via Mann-Whitney U
        if len(atk_vals) > 0 and len(nrm_vals) > 0 and not (np.std(atk_vals) == 0 and np.std(nrm_vals) == 0):
            u_stat, p_val = sp_stats.mannwhitneyu(atk_vals, nrm_vals, alternative="two-sided")
            # rank-biserial = 1 - 2U / (n1*n2)
            n1, n2 = len(atk_vals), len(nrm_vals)
            rbc = 1 - 2 * u_stat / (n1 * n2)
        else:
            u_stat, p_val, rbc = 0, 1.0, 0.0

        # Cohen's d effect size
        pooled_std = np.sqrt(
            ((len(nrm_vals) - 1) * np.var(nrm_vals, ddof=1) +
             (len(atk_vals) - 1) * np.var(atk_vals, ddof=1)) /
            max(len(nrm_vals) + len(atk_vals) - 2, 1)
        )
        cohens_d = (np.mean(atk_vals) - np.mean(nrm_vals)) / max(pooled_std, 1e-9)

        results.append({
            "feature": feat,
            "atk_mean": np.mean(atk_vals),
            "nrm_mean": np.mean(nrm_vals),
            "rbc": rbc,
            "cohens_d": cohens_d,
            "p_val": p_val,
        })

    results_df = pd.DataFrame(results).sort_values("cohens_d", key=abs, ascending=False)

    print(f"\n{'Feature':<28} {'Atk Mean':>10} {'Nrm Mean':>10} {'Cohen d':>9} {'Rank-Bis':>9} {'p-value':>10}")
    print("-" * 80)
    for _, row in results_df.iterrows():
        sig = "***" if row["p_val"] < 0.001 else ("**" if row["p_val"] < 0.01 else ("*" if row["p_val"] < 0.05 else ""))
        print(f"{row['feature']:<28} {row['atk_mean']:>10.4f} {row['nrm_mean']:>10.4f} "
              f"{row['cohens_d']:>+9.3f} {row['rbc']:>+9.3f} {row['p_val']:>10.4f} {sig}")

    print("\n--- Interpretation ---")
    print("  |Cohen's d| > 0.8 = large effect; > 0.5 = medium; > 0.2 = small")
    print("  Rank-biserial > 0 means attack users have HIGHER values")
    print("  NOTE: With only 4 attack users, p-values have limited statistical power")

    # ===========================================================================
    # SECTION 4: ISOLATION FOREST DECISION ANALYSIS
    # ===========================================================================
    print("\n" + "=" * 120)
    print("SECTION 4: ISOLATION FOREST DECISION ANALYSIS")
    print("=" * 120)

    scaler = StandardScaler()
    X_baseline = scaler.fit_transform(baseline_agg.values)
    X_test = scaler.transform(test_agg.values)

    iso = IsolationForest(contamination=0.05, random_state=42, n_estimators=200)
    iso.fit(X_baseline)
    iso_scores = iso.score_samples(X_test)
    iso_preds = iso.predict(X_test)

    user_idx = {u: i for i, u in enumerate(test_agg.index)}

    print(f"\nIForest threshold (offset): {iso.offset_:.6f}")
    print(f"Flagged as anomalous: {int((iso_preds == -1).sum())} / {len(iso_preds)}")

    # --- Feature contribution via path-length perturbation ---
    def iforest_feature_contributions(model, X_scaled, sample_idx, feature_names, n_top=5):
        """Estimate per-feature contribution by measuring score change when each feature
        is replaced by its population median (in scaled space)."""
        x = X_scaled[sample_idx].copy()
        base_score = model.score_samples(x.reshape(1, -1))[0]
        medians = np.median(X_scaled, axis=0)

        contributions = []
        for j in range(len(feature_names)):
            x_mod = x.copy()
            x_mod[j] = medians[j]
            mod_score = model.score_samples(x_mod.reshape(1, -1))[0]
            # Positive delta means replacing this feature made the user LESS anomalous
            delta = mod_score - base_score
            contributions.append((feature_names[j], delta, float(x[j])))

        contributions.sort(key=lambda t: t[1], reverse=True)
        return contributions[:n_top], base_score

    # --- Attack users ---
    print("\n--- ATTACK USERS ---")
    for uid in attack_uids:
        idx = user_idx[uid]
        score = iso_scores[idx]
        pred = "DETECTED" if iso_preds[idx] == -1 else "MISSED"
        info = ATTACK_ENTITIES[uid]

        print(f"\n  {uid} ({info['name']}) -- {pred}")
        print(f"    IForest score: {score:.6f} (threshold: {iso.offset_:.6f}, "
              f"margin: {score - iso.offset_:+.6f})")

        contribs, _ = iforest_feature_contributions(iso, X_test, idx, FEATURE_COLS, n_top=5)
        print(f"    Top 5 features driving anomaly (score delta when feature is neutralized):")
        for fname, delta, scaled_val in contribs:
            direction = "makes user LESS anomalous" if delta > 0 else "makes user MORE anomalous"
            raw_val = float(test_agg.iloc[idx][fname])
            bl_mean = float(baseline_agg[fname].mean())
            bl_std = float(baseline_agg[fname].std())
            z = (raw_val - bl_mean) / max(bl_std, 1e-9)
            print(f"      {fname:<28} delta={delta:+.6f} ({direction}) "
                  f"scaled={scaled_val:+.3f}  raw={raw_val:.4f}  pop_z={z:+.2f}")

        # Full z-score profile for the MISSED user (USR-234)
        if pred == "MISSED":
            print(f"\n    *** WHY {uid} IS MISSED ***")
            z_scores = X_test[idx]
            abs_z = np.abs(z_scores)
            sorted_feats = np.argsort(-abs_z)

            print(f"    Max |z| across all features: {abs_z.max():.3f}")
            print(f"    Features with |z| > 2: {int((abs_z > 2).sum())}")
            print(f"    Features with |z| > 1: {int((abs_z > 1).sum())}")
            print(f"    RMS z-score: {np.sqrt(np.mean(z_scores ** 2)):.3f}")

            print(f"\n    {'Feature':<28} {'z-score':>9} {'Test Val':>10} {'BL Pop Mean':>12} {'BL Pop Std':>12}")
            print(f"    {'-'*73}")
            for fi in sorted_feats[:10]:
                feat = FEATURE_COLS[fi]
                z = z_scores[fi]
                raw = float(test_agg.iloc[idx][feat])
                bl_m = float(scaler.mean_[fi])
                bl_s = float(np.sqrt(scaler.var_[fi]))
                marker = " <--" if abs(z) > 2 else ""
                print(f"    {feat:<28} {z:>+9.3f} {raw:>10.4f} {bl_m:>12.4f} {bl_s:>12.4f}{marker}")

            # Compare to a DETECTED attack user
            detected_uids = [u for u in attack_uids if iso_preds[user_idx[u]] == -1]
            if detected_uids:
                comp_uid = detected_uids[0]
                comp_idx = user_idx[comp_uid]
                comp_z = X_test[comp_idx]
                print(f"\n    Comparison with detected user {comp_uid}:")
                print(f"    {comp_uid} max |z|: {np.abs(comp_z).max():.3f}, "
                      f"RMS z: {np.sqrt(np.mean(comp_z**2)):.3f}")
                print(f"    {uid} max |z|: {abs_z.max():.3f}, "
                      f"RMS z: {np.sqrt(np.mean(z_scores**2)):.3f}")

                # Feature-by-feature comparison
                print(f"\n    {'Feature':<28} {uid + ' z':>10} {comp_uid + ' z':>10} {'Delta':>8}")
                print(f"    {'-'*58}")
                for fi in np.argsort(-np.abs(comp_z)):
                    feat = FEATURE_COLS[fi]
                    z1 = z_scores[fi]
                    z2 = comp_z[fi]
                    if abs(z2) > 1 or abs(z1) > 1:
                        print(f"    {feat:<28} {z1:>+10.3f} {z2:>+10.3f} {z1-z2:>+8.3f}")

    # --- Top 5 most anomalous NORMAL users ---
    print("\n--- TOP 5 MOST ANOMALOUS NORMAL USERS ---")
    normal_indices = [user_idx[u] for u in normal_uids if u in user_idx]
    normal_scores = [(u, iso_scores[user_idx[u]]) for u in normal_uids if u in user_idx]
    normal_scores.sort(key=lambda t: t[1])  # lower = more anomalous

    for rank, (uid, score) in enumerate(normal_scores[:5]):
        idx = user_idx[uid]
        pred = "FLAGGED" if iso_preds[idx] == -1 else "normal"
        dev = uid_to_primary.get(uid, "?")

        print(f"\n  #{rank+1} {uid} (device: {dev}) -- score: {score:.6f} [{pred}]")
        contribs, _ = iforest_feature_contributions(iso, X_test, idx, FEATURE_COLS, n_top=3)
        for fname, delta, scaled_val in contribs:
            raw_val = float(test_agg.iloc[idx][fname])
            print(f"    {fname:<28} delta={delta:+.6f}  scaled={scaled_val:+.3f}  raw={raw_val:.4f}")

    # IForest score distribution
    print("\n--- IFOREST SCORE DISTRIBUTION ---")
    normal_iso_scores = iso_scores[[user_idx[u] for u in normal_uids if u in user_idx]]
    pcts = np.percentile(normal_iso_scores, [1, 5, 10, 25, 50, 75, 90, 95, 99])
    print(f"  Normal users: mean={np.mean(normal_iso_scores):.6f}, std={np.std(normal_iso_scores):.6f}")
    print(f"  Percentiles: p1={pcts[0]:.6f} p5={pcts[1]:.6f} p10={pcts[2]:.6f} "
          f"p25={pcts[3]:.6f} p50={pcts[4]:.6f} p75={pcts[5]:.6f} "
          f"p90={pcts[6]:.6f} p95={pcts[7]:.6f} p99={pcts[8]:.6f}")
    for uid in attack_uids:
        s = iso_scores[user_idx[uid]]
        pctile = 100.0 * (normal_iso_scores < s).sum() / len(normal_iso_scores)
        print(f"  {uid}: {s:.6f} (percentile among normals: {pctile:.1f}%)")

    # ===========================================================================
    # SECTION 5: LOF NEIGHBORHOOD ANALYSIS
    # ===========================================================================
    print("\n" + "=" * 120)
    print("SECTION 5: LOF NEIGHBORHOOD ANALYSIS")
    print("=" * 120)

    lof = LocalOutlierFactor(n_neighbors=20, contamination=0.05, novelty=True)
    lof.fit(X_baseline)
    lof_scores = lof.score_samples(X_test)
    lof_preds = lof.predict(X_test)

    print(f"\nLOF threshold (offset): {lof.offset_:.6f}")
    print(f"Flagged as anomalous: {int((lof_preds == -1).sum())} / {len(lof_preds)}")

    # Pairwise distances in scaled test space
    test_user_list = list(test_agg.index)
    dist_matrix = cdist(X_test, X_test, metric="euclidean")

    print("\n--- ATTACK USER LOF ANALYSIS ---")
    for uid in attack_uids:
        idx = user_idx[uid]
        score = lof_scores[idx]
        pred = "DETECTED" if lof_preds[idx] == -1 else "MISSED"
        info = ATTACK_ENTITIES[uid]

        print(f"\n  {uid} ({info['name']}) -- {pred}")
        print(f"    LOF score: {score:.6f} (threshold: {lof.offset_:.6f}, "
              f"margin: {score - lof.offset_:+.6f})")

        # Find 3 nearest neighbors in test set (excluding self)
        dists = dist_matrix[idx].copy()
        dists[idx] = np.inf  # exclude self
        nn_indices = np.argsort(dists)[:3]

        print(f"    3 nearest neighbors in test set (euclidean in scaled space):")
        for rank, ni in enumerate(nn_indices):
            nn_uid = test_user_list[ni]
            nn_dist = dists[ni]
            nn_type = "ATTACK" if nn_uid in ATTACK_ENTITIES else "normal"
            nn_dev = uid_to_primary.get(nn_uid, "?")
            print(f"      #{rank+1} {nn_uid} (dist={nn_dist:.4f}, type={nn_type}, device={nn_dev})")

    # --- Are attack users near each other? ---
    print("\n--- INTER-ATTACK-USER DISTANCES ---")
    attack_indices = [user_idx[u] for u in attack_uids]
    print(f"  {'':>10}", end="")
    for u in attack_uids:
        print(f" {u:>10}", end="")
    print()
    for i, u1 in enumerate(attack_uids):
        print(f"  {u1:>10}", end="")
        for j, u2 in enumerate(attack_uids):
            d = dist_matrix[attack_indices[i], attack_indices[j]]
            print(f" {d:>10.4f}", end="")
        print()

    # Compare to typical inter-user distance
    n_sample = min(100, len(normal_uids))
    np.random.seed(42)
    sample_normals = np.random.choice([user_idx[u] for u in normal_uids if u in user_idx],
                                       size=n_sample, replace=False)
    normal_pairwise = dist_matrix[np.ix_(sample_normals, sample_normals)]
    # Upper triangle only
    triu_idx = np.triu_indices(n_sample, k=1)
    normal_dists = normal_pairwise[triu_idx]

    print(f"\n  Typical normal-normal distance: mean={np.mean(normal_dists):.4f}, "
          f"std={np.std(normal_dists):.4f}, median={np.median(normal_dists):.4f}")
    print(f"  Normal-normal distance percentiles: "
          f"p5={np.percentile(normal_dists, 5):.4f}, "
          f"p25={np.percentile(normal_dists, 25):.4f}, "
          f"p75={np.percentile(normal_dists, 75):.4f}, "
          f"p95={np.percentile(normal_dists, 95):.4f}")

    # Attack-to-nearest-normal distances
    print("\n  Attack-to-nearest-normal distances:")
    for uid in attack_uids:
        idx = user_idx[uid]
        dists_to_normals = [dist_matrix[idx, user_idx[u]] for u in normal_uids if u in user_idx]
        min_d = min(dists_to_normals)
        mean_d = np.mean(dists_to_normals)
        nn_uid = normal_uids[np.argmin(dists_to_normals)]
        print(f"    {uid}: nearest_normal={nn_uid} at dist={min_d:.4f}, "
              f"mean_dist_to_normals={mean_d:.4f}")

    # --- LOF score distribution ---
    print("\n--- LOF SCORE DISTRIBUTION ---")
    normal_lof_scores = lof_scores[[user_idx[u] for u in normal_uids if u in user_idx]]
    pcts = np.percentile(normal_lof_scores, [1, 5, 10, 25, 50, 75, 90, 95, 99])
    print(f"  Normal users: mean={np.mean(normal_lof_scores):.6f}, std={np.std(normal_lof_scores):.6f}")
    print(f"  Percentiles: p1={pcts[0]:.6f} p5={pcts[1]:.6f} p10={pcts[2]:.6f} "
          f"p25={pcts[3]:.6f} p50={pcts[4]:.6f} p75={pcts[5]:.6f} "
          f"p90={pcts[6]:.6f} p95={pcts[7]:.6f} p99={pcts[8]:.6f}")
    for uid in attack_uids:
        s = lof_scores[user_idx[uid]]
        pctile = 100.0 * (normal_lof_scores < s).sum() / len(normal_lof_scores)
        print(f"  {uid}: {s:.6f} (percentile among normals: {pctile:.1f}%)")

    # ===========================================================================
    # SECTION 6: SUMMARY FINDINGS
    # ===========================================================================
    print("\n" + "=" * 120)
    print("SECTION 6: SUMMARY FINDINGS")
    print("=" * 120)

    print("\n[1] Feature Distribution Issues:")
    for feat in FEATURE_COLS:
        vals = bl[feat].values
        std = np.std(vals, ddof=1)
        n_zero = int((np.abs(vals) < 1e-9).sum())
        pct_zero = 100.0 * n_zero / len(vals)
        rounded = np.round(vals, 4)
        n_unique = len(np.unique(rounded))

        issues = []
        if std < 0.5:
            issues.append(f"std={std:.4f} -- any small deviation looks extreme in z-score")
        if n_unique <= 5:
            issues.append(f"only {n_unique} unique values -- essentially categorical")
        if pct_zero > 40:
            issues.append(f"{pct_zero:.0f}% zeros -- bimodal (zero vs non-zero)")

        if issues:
            print(f"  {feat}: {'; '.join(issues)}")

    print("\n[2] Bimodality Impact:")
    print(f"  {len(dev001_users)} users share DEV-001 -> zero endpoint/network/DNS features")
    print(f"  This creates a bimodal distribution: {len(dev001_users)} at zero, "
          f"{len(unique_users)} with real values")
    print(f"  IForest/LOF may learn to separate these groups rather than detecting attacks")

    print("\n[3] Attack Detectability by Method:")
    for uid in attack_uids:
        idx = user_idx[uid]
        iso_det = "DETECTED" if iso_preds[idx] == -1 else "MISSED"
        lof_det = "DETECTED" if lof_preds[idx] == -1 else "MISSED"
        z = X_test[idx]
        max_z = np.abs(z).max()
        z_det = "DETECTED" if max_z > 3 else "MISSED"

        print(f"  {uid} ({ATTACK_ENTITIES[uid]['name']}):")
        print(f"    IForest: {iso_det} (score={iso_scores[idx]:.6f})")
        print(f"    LOF:     {lof_det} (score={lof_scores[idx]:.6f})")
        print(f"    Z>3:     {z_det} (max|z|={max_z:.3f})")

    print("\n" + "=" * 120)
    print("AUDIT COMPLETE")
    print("=" * 120)


if __name__ == "__main__":
    main()
