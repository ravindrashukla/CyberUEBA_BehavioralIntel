"""Run detection on 50-user test trajectories (already embedded)."""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
import pandas as pd

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

ATTACKS = {"USR-042", "USR-118", "USR-156", "USR-234"}
ATTACK_NAMES = {
    "USR-042": "Volt Typhoon", "USR-118": "Salt Typhoon",
    "USR-156": "Insider", "USR-234": "Slow APT",
}
DRIFT_ZONES = [
    "access_pattern_drift", "data_behavior_drift",
    "network_footprint_drift", "risk_posture_drift",
]

# Load trajectories and assign role groups
traj = pd.read_csv("data/tier3_results/test50_trajectories.csv")
traj["role_group"] = traj["role"].map(ROLE_TO_GROUP)

all_users = traj.user_id.unique()
user_grp = {uid: traj[traj.user_id == uid]["role_group"].iloc[0] for uid in all_users}
weeks = sorted(traj.week_idx.unique())

print(f"Users: {len(all_users)}, Weeks: {len(weeks)}")
print(f"Groups: {pd.Series(user_grp).value_counts().to_dict()}")

# Pivot + rolling
pivot = {}
for zone in DRIFT_ZONES:
    pv = traj.pivot_table(index='week_idx', columns='user_id', values=zone, aggfunc='mean')
    pv = pv.reindex(weeks)
    pivot[zone] = pv.rolling(window=4, min_periods=1).mean()

n_normal = sum(1 for u in all_users if u not in ATTACKS)

results = {}
for uid in all_users:
    grp = user_grp[uid]
    normal_uids = [u for u in all_users if user_grp.get(u) == grp and u not in ATTACKS]
    is_attack = uid in ATTACKS
    zones = {}

    for zone in DRIFT_ZONES:
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

        # CUSUM with first-quarter baseline
        q1 = pcts[:len(weeks) // 4]
        bl = float(np.mean(q1)) if len(q1) > 0 else med_pct
        cs, pk = 0.0, 0.0
        for p in pcts:
            cs = max(0.0, cs + (p - bl - 10))
            pk = max(pk, cs)

        # Self-ratio
        raw = traj[traj.user_id == uid].sort_values("week_idx")[zone].values
        med_r = float(np.median(raw))
        mx_r = float(np.max(raw))
        ratio = mx_r / med_r if med_r > 0.001 else mx_r / 0.001

        zones[zone] = {
            "pct_median": med_pct, "pct_peak": peak_pct,
            "self_change": peak_pct - med_pct,
            "cusum": pk, "ratio": ratio,
        }

    results[uid] = {"grp": grp, "is_attack": is_attack, "zones": zones}

# Show attack users
print("\n" + "=" * 90)
print("ATTACK USER DETECTION RESULTS (with qualitative embeddings)")
print("=" * 90)
for uid in sorted(ATTACKS):
    r = results[uid]
    print(f"\n{uid} ({ATTACK_NAMES[uid]}) - group: {r['grp']}")
    print(f"  {'Zone':<25} {'MedPct':>7} {'PeakPct':>8} {'SelfChg':>8} {'CUSUM':>8} {'Ratio':>8}")
    print(f"  {'-'*68}")
    for zone in DRIFT_ZONES:
        zn = zone.replace('_drift', '')
        z = r['zones'][zone]
        print(f"  {zn:<25} {z['pct_median']:>6.1f}% {z['pct_peak']:>7.1f}% {z['self_change']:>+7.1f} {z['cusum']:>8.1f} {z['ratio']:>7.1f}x")

# Ranking by max CUSUM
print(f"\n{'='*80}")
print(f"RANKING BY MAX CUSUM")
print(f"{'='*80}")
ranked = sorted(results.items(),
                key=lambda x: max((v['cusum'] for v in x[1]['zones'].values()), default=0),
                reverse=True)
for i, (uid, r) in enumerate(ranked[:30], 1):
    max_cusum = max((v['cusum'] for v in r['zones'].values()), default=0)
    best_zone = max(r['zones'], key=lambda z: r['zones'][z]['cusum']).replace('_drift','')
    status = f"<-- {ATTACK_NAMES[uid]}" if uid in ATTACKS else ""
    print(f"  {i:>3}. {uid:<10} {r['grp']:<12} cusum={max_cusum:>8.1f} ({best_zone})  {status}")

# Ranking by max self-change
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

# Threshold sweep for CUSUM
print(f"\n{'='*80}")
print(f"CUSUM THRESHOLD SWEEP")
print(f"{'='*80}")
for thresh in [50, 100, 150, 200, 300, 400, 500, 600, 800, 1000]:
    tp = sum(1 for u in ATTACKS if max((results[u]['zones'][z]['cusum'] for z in DRIFT_ZONES), default=0) >= thresh)
    fp = sum(1 for u in all_users if u not in ATTACKS and max((results[u]['zones'][z]['cusum'] for z in DRIFT_ZONES), default=0) >= thresh)
    fp_rate = fp / n_normal * 100
    prec = tp / max(tp + fp, 1) * 100
    marker = ' <-- ALL 4' if tp == 4 else (' <--' if tp >= 3 else '')
    print(f"  thresh={thresh:>5}: TP={tp} FP={fp:>3} FP%={fp_rate:>5.1f}% Prec={prec:>5.1f}%{marker}")
