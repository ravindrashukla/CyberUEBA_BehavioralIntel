"""Role-group anomaly detection: Percentile + Group-Relative Direction.

Step 1: For each user, compute per-zone drift relative to their role group.
        Flag if ANY zone exceeds 90th percentile for that group.
Step 2: For flagged users, compare their drift DIRECTION against the group's
        mean drift direction. Flag only if their direction is unusual for
        their group (deviation from group mean direction above threshold).

Also runs z-score, IForest, and concept-only for comparison/documentation.
"""
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest

# ── Role Group Definitions ──────────────────────────────────────────────────

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

ATTACKS = ['USR-042', 'USR-118', 'USR-156', 'USR-234']
ATTACK_NAMES = {
    'USR-042': 'Volt Typhoon LOTL',
    'USR-118': 'Salt Typhoon Telecom',
    'USR-156': 'Insider Threat',
    'USR-234': 'Slow APT 180-day',
}

DRIFT_ZONES = ['access_pattern_drift', 'data_behavior_drift',
               'network_footprint_drift', 'risk_posture_drift']


def load_data():
    users = pd.read_csv('data/generated/entities/users.csv')
    users['role_group'] = users['role'].map(ROLE_TO_GROUP)
    traj = pd.read_csv('data/tier3_results/weekly_zone_trajectories.csv')
    traj = traj.merge(users[['user_id', 'role', 'role_group']], on='user_id', how='left',
                      suffixes=('', '_usr'))
    grp_col = 'role_group_usr' if 'role_group_usr' in traj.columns else 'role_group'
    role_col = 'role_usr' if 'role_usr' in traj.columns else 'role'
    t3 = pd.read_csv('data/tier3_results/tier3_comparison.csv')
    return users, traj, t3, grp_col, role_col


def compute_user_drift_profiles(traj, grp_col):
    """Compute per-user drift profiles using a 4-week rolling window across ALL weeks.

    For each user, returns the peak (worst) 4-week window across the entire
    observation period. This simulates continuous monitoring — we detect
    anomalies whenever they occur, not just in a fixed late window.
    """
    profiles_list = []
    for uid in traj.user_id.unique():
        u_data = traj[traj.user_id == uid].sort_values('week_idx')
        grp = u_data[grp_col].iloc[0]

        # 4-week rolling mean per zone
        rolling = u_data[DRIFT_ZONES].rolling(window=4, min_periods=2).mean()

        # Peak (max) rolling value per zone
        peak_vals = rolling.max()
        peak_week_idx = int(rolling.sum(axis=1).idxmax())
        peak_week = int(u_data.loc[peak_week_idx, 'week_idx']) if peak_week_idx in u_data.index else -1

        row = {'user_id': uid, 'role_group': grp, 'peak_week': peak_week}
        for zone in DRIFT_ZONES:
            row[zone] = peak_vals[zone]
        profiles_list.append(row)

    profiles = pd.DataFrame(profiles_list)
    profiles['is_attack'] = profiles['user_id'].isin(ATTACKS)
    return profiles


# ── Method 1: Z-Score ────────────────────────────────────────────────────────

def detect_zscore(profiles, z_threshold=2.0):
    results = []
    for _, row in profiles.iterrows():
        uid = row['user_id']
        group = row['role_group']
        group_normal = profiles[(profiles.role_group == group) & (~profiles.is_attack)]
        max_z = 0
        max_zone = ""
        zone_zscores = {}
        for zone in DRIFT_ZONES:
            g_mean = group_normal[zone].mean()
            g_std = max(group_normal[zone].std(), 1e-10)
            z = (row[zone] - g_mean) / g_std
            zone_zscores[zone] = z
            if z > max_z:
                max_z = z
                max_zone = zone
        results.append({
            'user_id': uid, 'role_group': group, 'is_attack': row['is_attack'],
            'max_z': max_z, 'max_zone': max_zone, 'detected': max_z >= z_threshold,
            **{f'z_{z}': zone_zscores[z] for z in DRIFT_ZONES},
        })
    return pd.DataFrame(results)


# ── Method 2: Percentile Only ────────────────────────────────────────────────

def detect_percentile(profiles, pct_threshold=90):
    results = []
    for _, row in profiles.iterrows():
        uid = row['user_id']
        group = row['role_group']
        group_normal = profiles[(profiles.role_group == group) & (~profiles.is_attack)]
        max_pct = 0
        max_zone = ""
        zone_pcts = {}
        for zone in DRIFT_ZONES:
            pct = (group_normal[zone] < row[zone]).sum() / len(group_normal) * 100
            zone_pcts[zone] = pct
            if pct > max_pct:
                max_pct = pct
                max_zone = zone
        results.append({
            'user_id': uid, 'role_group': group, 'is_attack': row['is_attack'],
            'max_pct': max_pct, 'max_zone': max_zone, 'detected': max_pct >= pct_threshold,
            **{f'pct_{z}': zone_pcts[z] for z in DRIFT_ZONES},
        })
    return pd.DataFrame(results)


# ── PRIMARY: Self-Drift (CUSUM) + Group Deviation ───────────────────────────

def compute_behavioral_profile(traj, grp_col, window=4, elevated_threshold=85):
    """Per-user per-zone behavioral profiling within role group.

    Uses MEDIAN percentile as self-baseline (robust across all weeks).
    Computes deviation from own median, peak level, and persistence.
    """
    all_users = traj.user_id.unique()
    user_grp = {uid: traj[traj.user_id == uid][grp_col].iloc[0] for uid in all_users}
    weeks = sorted(traj.week_idx.unique())
    n_weeks = len(weeks)

    # Pre-compute rolling means per user per zone (vectorized)
    pivot = {}
    for zone in DRIFT_ZONES:
        pv = traj.pivot_table(index='week_idx', columns='user_id', values=zone, aggfunc='mean')
        pv = pv.reindex(weeks)
        pivot[zone] = pv.rolling(window=window, min_periods=1).mean()

    results = {}
    for uid in all_users:
        grp = user_grp[uid]
        normal_uids = [u for u in all_users if user_grp[u] == grp and u not in ATTACKS]
        user_result = {'role_group': grp, 'is_attack': uid in ATTACKS, 'zones': {}}

        for zone in DRIFT_ZONES:
            pv = pivot[zone]
            normal_cols = [u for u in normal_uids if u in pv.columns]
            if uid not in pv.columns or len(normal_cols) == 0:
                user_result['zones'][zone] = {
                    'median_pct': 50, 'peak_pct': 50, 'self_change': 0,
                    'elevated_fraction': 0, 'max_consecutive': 0, 'peak_week': -1,
                }
                continue

            user_vals = pv[uid].values
            normal_vals = pv[normal_cols].values

            # Per-week percentile within group
            pcts = (normal_vals < user_vals[:, None]).sum(axis=1) / len(normal_cols) * 100

            median_pct = float(np.median(pcts))
            peak_pct = float(pcts.max())
            peak_week = int(weeks[pcts.argmax()])
            self_change = peak_pct - median_pct

            # Persistence: fraction of weeks elevated + max consecutive
            elevated = pcts >= elevated_threshold
            elevated_fraction = float(elevated.sum()) / n_weeks
            max_consec = 0
            cur = 0
            for e in elevated:
                if e:
                    cur += 1
                    max_consec = max(max_consec, cur)
                else:
                    cur = 0

            user_result['zones'][zone] = {
                'median_pct': median_pct,
                'peak_pct': peak_pct,
                'peak_week': peak_week,
                'self_change': self_change,
                'elevated_fraction': elevated_fraction,
                'max_consecutive': max_consec,
            }
        results[uid] = user_result
    return results


def detect_self_ratio_group(traj, grp_col, ratio_threshold=5.0, group_pct_threshold=80):
    """Self-ratio + group deviation detection.

    Self-ratio: max(weekly_drift) / median(weekly_drift) per zone.
    Captures how much a user's behavior CHANGED from their own norm.
    Attackers show 10-85x ratios; normal users show 1-3x.

    Group deviation: the user's max drift exceeds group's Nth percentile
    of max drift values, confirming the elevated behavior is unusual for peers.

    A user is flagged when BOTH hold in the same zone:
      1. self_ratio >= ratio_threshold (user changed from own baseline)
      2. max_drift >= group's pct_threshold percentile of max drift (unusual vs group)
    """
    all_users = traj.user_id.unique()
    user_grp = {uid: traj[traj.user_id == uid][grp_col].iloc[0] for uid in all_users}

    # Compute per-user per-zone stats from raw weekly drift
    user_stats = {}
    for uid in all_users:
        u_data = traj[traj.user_id == uid].sort_values('week_idx')
        zones = {}
        for zone in DRIFT_ZONES:
            vals = u_data[zone].values
            vals = vals[~np.isnan(vals)]
            if len(vals) == 0:
                zones[zone] = {'median': 0, 'max': 0, 'self_ratio': 1.0, 'peak_week': -1}
                continue
            med = float(np.median(vals))
            mx = float(vals.max())
            peak_wk = int(u_data.iloc[vals.argmax()]['week_idx'])
            ratio = mx / max(med, 1e-6)
            zones[zone] = {'median': med, 'max': mx, 'self_ratio': ratio, 'peak_week': peak_wk}
        user_stats[uid] = zones

    # Compute group-level max drift distribution (normal users only)
    group_max_pcts = {}
    for grp in set(user_grp.values()):
        normal_uids = [u for u in all_users if user_grp[u] == grp and u not in ATTACKS]
        pcts = {}
        for zone in DRIFT_ZONES:
            normal_maxes = [user_stats[u][zone]['max'] for u in normal_uids]
            pcts[zone] = np.array(normal_maxes)
        group_max_pcts[grp] = pcts

    results = []
    for uid in all_users:
        grp = user_grp[uid]
        is_attack = uid in ATTACKS

        flagged_zones = []
        max_ratio = 0.0
        max_ratio_zone = ""

        for zone in DRIFT_ZONES:
            zs = user_stats[uid][zone]
            if zs['self_ratio'] > max_ratio:
                max_ratio = zs['self_ratio']
                max_ratio_zone = zone

            # Self-ratio check
            if zs['self_ratio'] < ratio_threshold:
                continue

            # Group deviation check: is this max drift unusual for the group?
            normal_maxes = group_max_pcts[grp][zone]
            grp_pct = float((normal_maxes < zs['max']).sum()) / len(normal_maxes) * 100

            if grp_pct >= group_pct_threshold:
                flagged_zones.append(zone)

        detected = len(flagged_zones) > 0

        results.append({
            'user_id': uid,
            'role_group': grp,
            'is_attack': is_attack,
            'detected': detected,
            'max_ratio': max_ratio,
            'max_ratio_zone': max_ratio_zone,
            'n_flagged_zones': len(flagged_zones),
            'flagged_zones': flagged_zones,
            **{f'ratio_{z}': user_stats[uid][z]['self_ratio'] for z in DRIFT_ZONES},
            **{f'median_{z}': user_stats[uid][z]['median'] for z in DRIFT_ZONES},
            **{f'max_{z}': user_stats[uid][z]['max'] for z in DRIFT_ZONES},
            **{f'peak_wk_{z}': user_stats[uid][z]['peak_week'] for z in DRIFT_ZONES},
        })
    return pd.DataFrame(results)


# ── Method 4: Per-Group Isolation Forest ──────────────────────────────────────

def detect_iforest(profiles, contamination=0.05):
    results = []
    for group in profiles.role_group.unique():
        group_data = profiles[profiles.role_group == group]
        group_normal = group_data[~group_data.is_attack]
        if len(group_normal) < 5:
            for _, row in group_data.iterrows():
                results.append({
                    'user_id': row['user_id'], 'role_group': group,
                    'is_attack': row['is_attack'], 'iforest_score': 0.0, 'detected': False,
                })
            continue
        X_train = group_normal[DRIFT_ZONES].values
        X_all = group_data[DRIFT_ZONES].values
        clf = IsolationForest(contamination=contamination, random_state=42, n_estimators=200)
        clf.fit(X_train)
        scores = clf.decision_function(X_all)
        preds = clf.predict(X_all)
        for i, (_, row) in enumerate(group_data.iterrows()):
            results.append({
                'user_id': row['user_id'], 'role_group': group,
                'is_attack': row['is_attack'], 'iforest_score': -scores[i],
                'detected': preds[i] == -1,
            })
    return pd.DataFrame(results)


def detect_iforest_enriched(traj, grp_col, profiles, contamination=0.05,
                            drift_allowance=10, window=4):
    """IForest on enriched features: raw drift + self-change + zone CUSUM.

    12 features per user (4 zones × 3 feature types):
      - Raw zone drift (peak rolling window) — "how much did they drift?"
      - Self-change (peak_pct - median_pct) — "is this new behavior?"
      - Zone CUSUM — "is the shift sustained?"
    """
    beh_profile = compute_behavioral_profile(traj, grp_col, window=window)

    all_users = traj.user_id.unique()
    user_grp = {uid: traj[traj.user_id == uid][grp_col].iloc[0] for uid in all_users}
    weeks = sorted(traj.week_idx.unique())

    pivot = {}
    for zone in DRIFT_ZONES:
        pv = traj.pivot_table(index='week_idx', columns='user_id', values=zone, aggfunc='mean')
        pv = pv.reindex(weeks)
        pivot[zone] = pv.rolling(window=window, min_periods=1).mean()

    # Compute per-zone CUSUM for each user
    user_zone_cusum = {}
    for uid in all_users:
        grp = user_grp[uid]
        normal_uids = [u for u in all_users if user_grp[u] == grp and u not in ATTACKS]
        zone_cusums = {}
        for zone in DRIFT_ZONES:
            pv = pivot[zone]
            nc = [u for u in normal_uids if u in pv.columns]
            if uid not in pv.columns or len(nc) == 0:
                zone_cusums[zone] = 0.0
                continue
            uv = pv[uid].values
            nv = pv[nc].values
            pcts = (nv < uv[:, None]).sum(axis=1) / len(nc) * 100
            bl = float(np.median(pcts))
            cs = 0.0
            pk = 0.0
            for p in pcts:
                cs = max(0.0, cs + (p - bl - drift_allowance))
                pk = max(pk, cs)
            zone_cusums[zone] = pk
        user_zone_cusum[uid] = zone_cusums

    # Build enriched feature matrix per group
    enriched_cols = []
    for zone in DRIFT_ZONES:
        enriched_cols.extend([f'drift_{zone}', f'selfchg_{zone}', f'cusum_{zone}'])

    user_features = {}
    for uid in all_users:
        feats = []
        for zone in DRIFT_ZONES:
            # Raw drift value
            drift_val = profiles.loc[profiles.user_id == uid, zone].values[0] if uid in profiles.user_id.values else 0
            # Self-change
            self_chg = beh_profile[uid]['zones'][zone]['self_change'] if uid in beh_profile else 0
            # CUSUM
            cusum_val = user_zone_cusum.get(uid, {}).get(zone, 0)
            feats.extend([drift_val, self_chg, cusum_val])
        user_features[uid] = feats

    results = []
    for group in set(user_grp.values()):
        grp_users = [u for u in all_users if user_grp[u] == group]
        grp_normal = [u for u in grp_users if u not in ATTACKS]

        if len(grp_normal) < 5:
            for uid in grp_users:
                results.append({
                    'user_id': uid, 'role_group': group,
                    'is_attack': uid in ATTACKS, 'iforest_score': 0.0, 'detected': False,
                })
            continue

        X_train = np.array([user_features[u] for u in grp_normal])
        X_all = np.array([user_features[u] for u in grp_users])

        clf = IsolationForest(contamination=contamination, random_state=42, n_estimators=200)
        clf.fit(X_train)
        scores = clf.decision_function(X_all)
        preds = clf.predict(X_all)

        for i, uid in enumerate(grp_users):
            results.append({
                'user_id': uid, 'role_group': group,
                'is_attack': uid in ATTACKS,
                'iforest_score': -scores[i],
                'detected': preds[i] == -1,
            })

    return pd.DataFrame(results)


# ── PRIMARY: Percentile + Group-Relative Direction ────────────────────────────

def compute_user_drift_vectors(traj, grp_col):
    """Compute per-user drift DIRECTION vectors (4D: one value per zone).

    Uses each user's peak 4-week window (same as profiles) for direction.
    """
    user_vecs = {}

    for uid in traj.user_id.unique():
        u_data = traj[traj.user_id == uid].sort_values('week_idx')
        grp = u_data[grp_col].iloc[0]

        rolling = u_data[DRIFT_ZONES].rolling(window=4, min_periods=2).mean()
        peak_idx = rolling.sum(axis=1).idxmax()
        peak_vals = rolling.loc[peak_idx]

        vec = np.array([peak_vals[z] for z in DRIFT_ZONES])
        norm = np.linalg.norm(vec)
        vec_normed = vec / norm if norm > 1e-10 else vec

        user_vecs[uid] = {
            'raw_vec': vec,
            'direction': vec_normed,
            'role_group': grp,
            'is_attack': uid in ATTACKS,
        }
    return user_vecs


def compute_group_mean_directions(user_vecs):
    """Compute mean drift direction per role group (normal users only)."""
    from collections import defaultdict
    group_dirs = defaultdict(list)

    for uid, info in user_vecs.items():
        if not info['is_attack']:
            group_dirs[info['role_group']].append(info['direction'])

    group_means = {}
    group_stds = {}
    for group, dirs in group_dirs.items():
        dirs_arr = np.array(dirs)
        mean_dir = dirs_arr.mean(axis=0)
        norm = np.linalg.norm(mean_dir)
        if norm > 1e-10:
            mean_dir = mean_dir / norm
        group_means[group] = mean_dir

        cosines = [float(np.dot(d, mean_dir)) for d in dirs_arr]
        group_stds[group] = {
            'cosine_mean': np.mean(cosines),
            'cosine_std': np.std(cosines),
            'cosines': cosines,
        }

    return group_means, group_stds


def detect_percentile_plus_direction(profiles, traj, grp_col,
                                     extreme_pct=95, moderate_pct=88,
                                     direction_pct=85):
    """Tiered detection:
    Tier A: ANY zone > extreme_pct -> flag directly (extreme drift).
    Tier B: ANY zone > moderate_pct AND unusual direction -> flag.
    """
    user_vecs = compute_user_drift_vectors(traj, grp_col)
    group_means, group_stats = compute_group_mean_directions(user_vecs)

    results = []
    for _, row in profiles.iterrows():
        uid = row['user_id']
        group = row['role_group']
        group_normal = profiles[(profiles.role_group == group) & (~profiles.is_attack)]

        zone_pcts = {}
        max_pct = 0
        max_zone = ""
        extreme_zones = []
        moderate_zones = []
        for zone in DRIFT_ZONES:
            pct = (group_normal[zone] < row[zone]).sum() / len(group_normal) * 100
            zone_pcts[zone] = pct
            if pct > max_pct:
                max_pct = pct
                max_zone = zone
            if pct >= extreme_pct:
                extreme_zones.append(zone)
            elif pct >= moderate_pct:
                moderate_zones.append(zone)

        tier_a = len(extreme_zones) > 0

        direction_unusual = False
        cosine_to_group = 1.0
        direction_pctile = 0.0
        if uid in user_vecs and group in group_means:
            user_dir = user_vecs[uid]['direction']
            group_mean_dir = group_means[group]
            cosine_to_group = float(np.dot(user_dir, group_mean_dir))
            group_cosines = group_stats[group]['cosines']
            direction_pctile = (1 - (sum(1 for c in group_cosines if c < cosine_to_group)
                                     / max(len(group_cosines), 1))) * 100
            threshold_cosine = np.percentile(group_cosines, 100 - direction_pct)
            direction_unusual = cosine_to_group < threshold_cosine

        tier_b = len(moderate_zones + extreme_zones) > 0 and direction_unusual
        detected = tier_a or tier_b
        trigger = ""
        if tier_a:
            trigger = "extreme_pct"
        elif tier_b:
            trigger = "moderate+direction"

        results.append({
            'user_id': uid,
            'role_group': group,
            'is_attack': row['is_attack'],
            'max_pct': max_pct,
            'max_zone': max_zone,
            'n_extreme_zones': len(extreme_zones),
            'n_moderate_zones': len(moderate_zones),
            'cosine_to_group': cosine_to_group,
            'direction_deviation_pct': direction_pctile,
            'direction_unusual': direction_unusual,
            'detected': detected,
            'trigger': trigger,
            'peak_week': row.get('peak_week', -1),
            **{f'pct_{z}': zone_pcts[z] for z in DRIFT_ZONES},
        })
    return pd.DataFrame(results)


# ── Output ────────────────────────────────────────────────────────────────────

def print_all_results(cusum_group_df, pct_df, iforest_df, iforest_enriched_df,
                      combo_df, profiles, traj, grp_col):

    print("=" * 90)
    print("ROLE-GROUP ANOMALY DETECTION RESULTS")
    print("=" * 90)

    # ── All methods comparison ──
    print("\n" + "=" * 90)
    print("METHOD COMPARISON")
    print("=" * 90)

    all_methods = [
        ("Percentile (>90th)", pct_df),
        ("IForest (drift only)", iforest_df),
        ("IForest (enriched)", iforest_enriched_df),
        ("Tiered Pct+Direction", combo_df),
        ("SelfRatio+Group (PRIMARY)", cusum_group_df),
    ]

    header = f"\n  {'Method':<25}"
    for uid in ATTACKS:
        header += f" {uid:>10}"
    header += f" {'TP':>5} {'FP':>5} {'FP%':>7} {'Precision':>10}"
    print(header)
    print("  " + "-" * 95)

    for name, df in all_methods:
        normal_df = df[~df.is_attack]
        line = f"  {name:<25}"
        tp = 0
        for uid in ATTACKS:
            det = bool(df.loc[df.user_id == uid, 'detected'].values[0]) if uid in df.user_id.values else False
            if det:
                tp += 1
            line += f" {'DETECTED':>10}" if det else f" {'MISSED':>10}"
        fp = int(normal_df['detected'].sum())
        fp_rate = fp / len(normal_df) * 100
        precision = tp / max(tp + fp, 1) * 100
        line += f" {tp:>5} {fp:>5} {fp_rate:>6.1f}% {precision:>9.1f}%"
        print(line)

    # ── Self-Ratio + Group detail (PRIMARY) ──
    print("\n" + "=" * 90)
    print("PRIMARY: Self-Ratio (max/median of raw drift) + Group Deviation")
    print("=" * 90)
    print("  self_ratio = max(weekly_drift) / median(weekly_drift) per zone")
    print("  Flag if self_ratio >= threshold AND max_drift >= group's Nth percentile")

    for uid in ATTACKS:
        r = cusum_group_df[cusum_group_df.user_id == uid].iloc[0]
        flagged = r['flagged_zones']
        flag_str = ', '.join(z.replace('_drift', '') for z in flagged) if flagged else 'NONE'
        print(f"\n  {uid} ({ATTACK_NAMES[uid]}) -- group: {r['role_group']}")
        zn_hdr = f"    {'Zone':<25} {'Median':>8} {'Max':>8} {'Ratio':>7} {'PeakWk':>7} {'Flag':>5}"
        print(zn_hdr)
        print(f"    {'-'*65}")
        for zone in DRIFT_ZONES:
            zn = zone.replace('_drift', '')
            med = r[f'median_{zone}']
            mx = r[f'max_{zone}']
            ratio = r[f'ratio_{zone}']
            pw = r[f'peak_wk_{zone}']
            is_flagged = zone in flagged
            print(f"    {zn:<25} {med:>8.4f} {mx:>8.4f} {ratio:>6.1f}x {pw:>7} {'  *' if is_flagged else ''}")
        print(f"    Result: {'DETECTED' if r['detected'] else 'MISSED'}")

    # ── Self-Ratio Ranking ──
    print("\n" + "=" * 90)
    print("SELF-RATIO ANOMALY RANKING (top 25)")
    print("=" * 90)

    ranked = cusum_group_df.sort_values('max_ratio', ascending=False).head(25)
    print(f"\n  {'Rank':>4} {'User':<10} {'Group':<12} {'MaxRatio':>9} {'Zone':<22} {'#Flagged':>8} {'Status'}")
    print(f"  {'-'*72}")
    for rank, (_, r) in enumerate(ranked.iterrows(), 1):
        status = "ATTACK" if r['is_attack'] else ""
        zn = r['max_ratio_zone'].replace('_drift', '') if r['max_ratio_zone'] else ""
        print(f"  {rank:>4} {r['user_id']:<10} {r['role_group']:<12} {r['max_ratio']:>8.1f}x {zn:<22} {r['n_flagged_zones']:>8} {status}")

    # ── Threshold sweep ──
    print(f"\n  Threshold sweep (ratio_threshold, group_pct_threshold):")
    print(f"  {'Ratio':>7} {'GrpPct':>7} {'TP':>5} {'FP':>5} {'FP%':>7} {'Prec':>7}")
    print(f"  {'-'*45}")

    all_users = traj.user_id.unique()
    user_grp_map = {uid: traj[traj.user_id == uid][grp_col].iloc[0] for uid in all_users}
    n_normal = sum(1 for u in all_users if u not in ATTACKS)

    # Pre-compute per-user per-zone stats
    user_zone_stats = {}
    for uid in all_users:
        u_data = traj[traj.user_id == uid]
        zones = {}
        for zone in DRIFT_ZONES:
            vals = u_data[zone].dropna().values
            med = float(np.median(vals)) if len(vals) > 0 else 0
            mx = float(vals.max()) if len(vals) > 0 else 0
            ratio = mx / max(med, 1e-6)
            zones[zone] = {'median': med, 'max': mx, 'ratio': ratio}
        user_zone_stats[uid] = zones

    # Group max distributions (normal users only)
    grp_max_dist = {}
    for grp in set(user_grp_map.values()):
        normal_uids = [u for u in all_users if user_grp_map[u] == grp and u not in ATTACKS]
        pcts = {}
        for zone in DRIFT_ZONES:
            pcts[zone] = np.array([user_zone_stats[u][zone]['max'] for u in normal_uids])
        grp_max_dist[grp] = pcts

    for rt in [3, 5, 8, 10, 15, 20, 30, 50]:
        for gpt in [70, 80, 90]:
            tp = 0
            fp = 0
            for uid in all_users:
                is_atk = uid in ATTACKS
                grp = user_grp_map[uid]
                flagged = False
                for zone in DRIFT_ZONES:
                    zs = user_zone_stats[uid][zone]
                    if zs['ratio'] < rt:
                        continue
                    normal_maxes = grp_max_dist[grp][zone]
                    grp_pct = float((normal_maxes < zs['max']).sum()) / len(normal_maxes) * 100
                    if grp_pct >= gpt:
                        flagged = True
                        break
                if flagged:
                    if is_atk:
                        tp += 1
                    else:
                        fp += 1
            fp_rate = fp / n_normal * 100
            prec = tp / max(tp + fp, 1) * 100
            marker = " <--" if tp == 4 and fp_rate < 15 else ""
            print(f"  {rt:>6}x {gpt:>6}% {tp:>5} {fp:>5} {fp_rate:>6.1f}% {prec:>6.1f}%{marker}")


if __name__ == "__main__":
    users, traj, t3, grp_col, role_col = load_data()
    profiles = compute_user_drift_profiles(traj, grp_col)

    print(f"Total users: {len(profiles)} ({profiles.is_attack.sum()} attacks)\n")

    pct_df = detect_percentile(profiles, pct_threshold=90)
    iforest_df = detect_iforest(profiles, contamination=0.05)
    iforest_enriched_df = detect_iforest_enriched(traj, grp_col, profiles, contamination=0.05)
    combo_df = detect_percentile_plus_direction(profiles, traj, grp_col,
                                                extreme_pct=95, moderate_pct=88,
                                                direction_pct=85)
    cusum_group_df = detect_self_ratio_group(traj, grp_col, ratio_threshold=5.0, group_pct_threshold=80)

    print_all_results(cusum_group_df, pct_df, iforest_df, iforest_enriched_df,
                      combo_df, profiles, traj, grp_col)
