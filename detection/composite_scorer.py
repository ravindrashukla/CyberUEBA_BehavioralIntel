"""Multi-phase composite anomaly scoring.

Phase 1: Sustained Baseline Deviation — per-zone drift from self-baseline,
         averaged over late observation period. Catches persistent anomalies.
Phase 2: Peer-Relative Outlier — group-relative z-scores on multiple features.
         Catches users who deviate from their role group.
Phase 3: Multi-Signal Fusion — combines phases with breadth weighting.
         Users anomalous across multiple dimensions score higher.
"""
import numpy as np
import pandas as pd


DRIFT_ZONES = [
    "access_pattern_drift", "data_behavior_drift",
    "network_footprint_drift", "risk_posture_drift",
]
CONTEXT_COLS = [
    "composite_drift_normal_ops", "composite_drift_insider_investigation",
    "composite_drift_apt_hunt", "composite_drift_privilege_audit",
]

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
for _grp, _roles in ROLE_GROUPS.items():
    for _role in _roles:
        ROLE_TO_GROUP[_role] = _grp


def extract_user_features(traj_df: pd.DataFrame) -> pd.DataFrame:
    """Extract per-user aggregate features from trajectory data."""
    records = []
    for uid in traj_df.user_id.unique():
        u = traj_df[traj_df.user_id == uid].sort_values("week_idx")
        n = len(u)
        half = n // 2
        q3 = 3 * n // 4
        is_attack = bool(u["is_attack"].iloc[0])
        role = u["role"].iloc[0]
        grp = ROLE_TO_GROUP.get(role, "unknown")

        feats = {"uid": uid, "is_attack": is_attack, "grp": grp, "role": role}

        # Phase 1: Sustained baseline deviation per zone
        for z in DRIFT_ZONES:
            zn = z.replace("_drift", "")
            v = u[z].values
            feats[f"{zn}_sustained"] = float(np.mean(v[half:]))
            feats[f"{zn}_late_q4"] = float(np.mean(v[q3:]))
            feats[f"{zn}_peak"] = float(np.max(v))
            feats[f"{zn}_trend"] = float(np.mean(v[-10:]) - np.mean(v[:10]))
            feats[f"{zn}_volatility"] = float(np.std(v))

        # Composite drift
        feats["composite_sustained"] = float(np.mean(u["composite_drift"].values[half:]))
        feats["composite_peak"] = float(u["composite_drift"].max())

        # Context-specific composites (late-stage mean)
        ctx_lates = []
        for c in CONTEXT_COLS:
            if c in u.columns:
                late_val = float(np.mean(u[c].values[half:]))
                ctx_lates.append(late_val)
                cname = c.replace("composite_drift_", "ctx_")
                feats[cname] = late_val
        feats["ctx_max"] = max(ctx_lates) if ctx_lates else 0.0
        feats["ctx_spread"] = (max(ctx_lates) - min(ctx_lates)) if len(ctx_lates) > 1 else 0.0

        # Relationship and zone divergence
        if "relationship_drift" in u.columns:
            feats["rel_sustained"] = float(np.mean(u["relationship_drift"].values[half:]))
            feats["rel_peak"] = float(u["relationship_drift"].max())
        if "zone_divergence" in u.columns:
            feats["zdiv_sustained"] = float(np.mean(u["zone_divergence"].values[half:]))

        # Velocity
        if "velocity" in u.columns:
            feats["vel_peak"] = float(u["velocity"].max())

        records.append(feats)

    return pd.DataFrame(records)


def compute_group_zscores(user_feats: pd.DataFrame) -> pd.DataFrame:
    """Compute z-scores relative to each user's role group (normals only)."""
    df = user_feats.copy()
    feat_cols = [c for c in df.columns if c not in ["uid", "is_attack", "grp", "role"]]

    for col in feat_cols:
        zcol = f"z_{col}"
        df[zcol] = 0.0
        for grp in df.grp.unique():
            normal_mask = (df.grp == grp) & (~df.is_attack)
            grp_mask = df.grp == grp
            mu = df.loc[normal_mask, col].mean()
            sigma = df.loc[normal_mask, col].std()
            if sigma > 1e-10:
                df.loc[grp_mask, zcol] = (df.loc[grp_mask, col] - mu) / sigma
            else:
                df.loc[grp_mask, zcol] = 0.0

    return df


def compute_composite_scores(df: pd.DataFrame,
                             novelty_df: pd.DataFrame = None) -> pd.DataFrame:
    """Multi-phase composite scoring."""
    z_cols = [c for c in df.columns if c.startswith("z_")]

    novelty_lookup = {}
    if novelty_df is not None:
        for _, nr in novelty_df.iterrows():
            novelty_lookup[nr["uid"]] = nr

    scores = []
    for _, row in df.iterrows():
        z_vals = sorted([row[c] for c in z_cols], reverse=True)

        # Phase 1: Signal strength — sum of top-3 z-scores
        signal_strength = sum(z_vals[:3])

        # Phase 2: Signal breadth — how many features are elevated
        breadth_15 = sum(1 for v in z_vals if v > 1.5)
        breadth_20 = sum(1 for v in z_vals if v > 2.0)

        # Phase 3: Zone-specific sustained deviation
        zone_sustained_zs = []
        for z in DRIFT_ZONES:
            zn = z.replace("_drift", "")
            zcol = f"z_{zn}_sustained"
            if zcol in df.columns:
                zone_sustained_zs.append(row[zcol])
        sustained_signal = sum(sorted(zone_sustained_zs, reverse=True)[:2])

        # Phase 4: Context divergence (attack-specific context scores high)
        ctx_z = row.get("z_ctx_spread", 0)
        ctx_max_z = row.get("z_ctx_max", 0)

        # Phase 5: Novelty persistence (C2 beacon detection)
        novelty_score = 0.0
        nov = novelty_lookup.get(row["uid"])
        if nov is not None:
            persistence = nov.get("novel_ip_max_persistence", 0)
            novel_frac = nov.get("novel_ip_weeks_frac", 0)
            persistent_count = nov.get("persistent_novel_ips", 0)
            if persistence > 10:
                novelty_score = min(persistence / 5.0, 10.0)
            if novel_frac > 0.5:
                novelty_score += novel_frac * 3.0

        # Composite: weighted combination
        composite = (
            signal_strength * 1.0
            + breadth_15 * 0.5
            + sustained_signal * 0.3
            + max(ctx_z, 0) * 0.5
            + max(ctx_max_z, 0) * 0.3
            + novelty_score * 1.0
        )

        scores.append({
            "uid": row["uid"],
            "is_attack": row["is_attack"],
            "grp": row["grp"],
            "role": row["role"],
            "signal_strength": signal_strength,
            "breadth_15": breadth_15,
            "breadth_20": breadth_20,
            "sustained_signal": sustained_signal,
            "ctx_spread_z": ctx_z,
            "ctx_max_z": ctx_max_z,
            "novelty_score": novelty_score,
            "composite": composite,
        })

    return pd.DataFrame(scores).sort_values("composite", ascending=False).reset_index(drop=True)


def threshold_sweep(scores_df: pd.DataFrame, score_col: str = "composite",
                    attack_set: set = None):
    """Run threshold sweep and print detection metrics."""
    if attack_set is None:
        attack_set = set(scores_df[scores_df.is_attack]["uid"])

    n_normal = len(scores_df[~scores_df.is_attack])
    n_attack = len(attack_set)

    thresholds = sorted(scores_df[score_col].quantile(
        [0.50, 0.75, 0.80, 0.85, 0.90, 0.92, 0.95, 0.96, 0.97, 0.98, 0.99]
    ).unique())

    print(f"\n{'='*80}")
    print(f"COMPOSITE THRESHOLD SWEEP ({score_col})")
    print(f"{'='*80}")
    print(f"  {'Threshold':>10} {'Pctile':>7} {'TP':>3}/{n_attack} {'FP':>4} "
          f"{'FP%':>6} {'Prec':>6} {'Recall':>7}")
    print(f"  {'-'*55}")

    for thresh in thresholds:
        flagged = scores_df[scores_df[score_col] >= thresh]
        tp = len(flagged[flagged.is_attack])
        fp = len(flagged[~flagged.is_attack])
        fp_rate = fp / n_normal * 100
        prec = tp / max(tp + fp, 1) * 100
        recall = tp / n_attack * 100
        pctile = (scores_df[score_col] < thresh).sum() / len(scores_df) * 100
        marker = " <-- ALL" if tp == n_attack else ""
        print(f"  {thresh:>10.2f} {pctile:>6.0f}% {tp:>3}/{n_attack} {fp:>4} "
              f"{fp_rate:>5.1f}% {prec:>5.1f}% {recall:>6.1f}%{marker}")


def run_composite_detection(traj_path: str = "data/tier3_results/all250_trajectories.csv"):
    """Full composite detection pipeline."""
    traj_df = pd.read_csv(traj_path)
    attack_names = {
        "USR-042": "Volt Typhoon", "USR-118": "Salt Typhoon",
        "USR-156": "Insider", "USR-234": "Slow APT",
    }
    attacks = set(attack_names.keys())

    print(f"Loaded {len(traj_df)} trajectory rows, "
          f"{traj_df.user_id.nunique()} users, {traj_df.week_idx.nunique()} weeks")

    # Extract features
    user_feats = extract_user_features(traj_df)
    print(f"Extracted {len(user_feats.columns) - 4} features per user")

    # Z-scores
    zscored = compute_group_zscores(user_feats)

    # Composite scores
    scores = compute_composite_scores(zscored)

    # Print attack user details
    print(f"\n{'='*80}")
    print("ATTACK USER COMPOSITE SCORES")
    print(f"{'='*80}")
    for uid in sorted(attacks):
        row = scores[scores.uid == uid].iloc[0]
        rank = scores.index[scores.uid == uid][0] + 1
        print(f"\n  {uid} ({attack_names[uid]}) — Rank #{rank}/{len(scores)}, "
              f"Group: {row.grp}")
        print(f"    Composite:        {row.composite:>8.2f}")
        print(f"    Signal Strength:  {row.signal_strength:>8.2f} (top-3 z-scores)")
        print(f"    Breadth (z>1.5):  {int(row.breadth_15):>8d}")
        print(f"    Breadth (z>2.0):  {int(row.breadth_20):>8d}")
        print(f"    Sustained Signal: {row.sustained_signal:>8.2f}")
        print(f"    Ctx Spread z:     {row.ctx_spread_z:>8.2f}")
        print(f"    Ctx Max z:        {row.ctx_max_z:>8.2f}")

    # Top 30 ranking
    print(f"\n{'='*80}")
    print(f"TOP 30 BY COMPOSITE SCORE")
    print(f"{'='*80}")
    for i, (_, r) in enumerate(scores.head(30).iterrows(), 1):
        tag = f" <-- {attack_names[r.uid]}" if r.uid in attacks else ""
        print(f"  {i:>3}. {r.uid:<10} {r.grp:<12} comp={r.composite:>7.2f} "
              f"(str={r.signal_strength:.1f} br={int(r.breadth_15)} "
              f"sus={r.sustained_signal:.1f} ctx={r.ctx_max_z:.1f}){tag}")

    # Threshold sweep
    threshold_sweep(scores, attack_set=attacks)

    # Per-zone z-score details for attackers
    print(f"\n{'='*80}")
    print("ATTACKER Z-SCORE PROFILES")
    print(f"{'='*80}")
    z_cols = [c for c in zscored.columns if c.startswith("z_")]
    for uid in sorted(attacks):
        row = zscored[zscored.uid == uid].iloc[0]
        print(f"\n  {uid} ({attack_names[uid]}, {row.grp}):")
        top_z = sorted(z_cols, key=lambda c: abs(row[c]), reverse=True)[:10]
        for c in top_z:
            print(f"    {c:40s} z={row[c]:+.2f}")

    return scores
