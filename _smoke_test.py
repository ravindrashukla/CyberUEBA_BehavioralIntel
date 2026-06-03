"""Pre-demo smoke test — validates all dashboard data and detection."""
import time
import subprocess
from pathlib import Path
import pandas as pd

print("=== V-INTELLIGENCE UEBA — PRE-DEMO SMOKE TEST ===")
print()

from pipeline.streamlit_db import db_available
from pipeline.dashboard_db import (
    load_composite_scores, load_detection_results, load_novelty_metrics,
    load_zscored_features, load_weekly_trajectories, load_weekly_features,
    load_alerts, load_kill_chains, load_log_stats, load_drift_series,
    load_user_roster,
)
from pipeline.streamlit_db import (
    load_dashboard_stats, load_drift_heatmap, load_all_user_ids,
    load_entity_structure, load_trajectory_events,
)

issues = []

# 1. DB
t0 = time.time()
db_ok = db_available()
print(f"1. DB Connection: {'PASS' if db_ok else 'FAIL'} ({time.time()-t0:.2f}s)")
if not db_ok:
    issues.append("Database not reachable")

# 2. All data loaders
print()
print("2. Data Loaders:")
loaders = [
    ("Alerts", load_alerts),
    ("Kill Chains", load_kill_chains),
    ("Drift Series", load_drift_series),
    ("Log Stats", load_log_stats),
    ("User Roster", load_user_roster),
    ("Weekly Features", load_weekly_features),
    ("Composite Scores", load_composite_scores),
    ("Detection Results", load_detection_results),
    ("Novelty Metrics", load_novelty_metrics),
    ("Z-Scored Features", load_zscored_features),
    ("Weekly Trajectories", load_weekly_trajectories),
    ("Dashboard Stats", load_dashboard_stats),
    ("Drift Heatmap", load_drift_heatmap),
    ("All User IDs", load_all_user_ids),
]

for name, fn in loaders:
    try:
        t = time.time()
        result = fn()
        if isinstance(result, dict):
            rows = len(result)
        elif hasattr(result, "__len__"):
            rows = len(result)
        else:
            rows = "?"
        elapsed = time.time() - t
        if rows == 0:
            print(f"   WARN  {name}: empty ({elapsed:.2f}s)")
            issues.append(f"{name} returned empty")
        else:
            print(f"   PASS  {name}: {rows} rows ({elapsed:.2f}s)")
    except Exception as e:
        print(f"   FAIL  {name}: {e}")
        issues.append(f"{name} failed: {e}")

# 3. Attack detection verification
print()
print("3. Attack Detection (4/4 required):")
cs = load_composite_scores()
if not cs.empty:
    attack_uids = ["USR-042", "USR-118", "USR-156", "USR-234"]
    attack_names = {
        "USR-042": "Volt Typhoon",
        "USR-118": "Salt Typhoon",
        "USR-156": "Insider Threat",
        "USR-234": "Slow APT",
    }
    thresh = cs["composite"].quantile(0.90)
    flagged = cs[cs["composite"] >= thresh]
    fp = len(flagged[~flagged["is_attack"]])
    n_normal = len(cs[~cs["is_attack"]])
    fp_rate = 100 * fp / n_normal if n_normal > 0 else 0

    for uid in attack_uids:
        row = cs[cs["uid"] == uid]
        if not row.empty:
            r = row.iloc[0]
            rank = cs.index[cs["uid"] == uid][0] + 1
            detected = r["composite"] >= thresh
            status = "PASS" if detected else "FAIL"
            print(f"   {status}  {uid} ({attack_names[uid]}): score={r['composite']:.1f}, rank #{rank}/{len(cs)}")
            if not detected:
                issues.append(f"{uid} NOT detected")
        else:
            print(f"   FAIL  {uid}: not in composite scores")
            issues.append(f"{uid} missing from scores")

    print(f"   FP Rate: {fp_rate:.1f}% ({fp} FP / {n_normal} normal users)")
    if fp_rate > 15:
        issues.append(f"FP rate too high: {fp_rate:.1f}%")
else:
    print("   FAIL  No composite scores available")
    issues.append("No composite scores")

# 4. CSV telemetry
print()
print("4. Telemetry CSVs:")
gen = Path("data/generated")
for sub in ["auth", "file_access", "network", "dns"]:
    csvs = sorted((gen / sub).glob("*.csv"))
    if csvs:
        df = pd.read_csv(csvs[-1])
        print(f"   PASS  {sub}: {len(csvs)} files, {len(df):,} rows in latest")
    else:
        print(f"   FAIL  {sub}: no CSV files")
        issues.append(f"No {sub} CSV files")

# 5. Docker
print()
print("5. Docker Containers:")
result = subprocess.run(
    ["docker-compose", "ps"],
    capture_output=True, text=True, cwd="."
)
for line in result.stdout.strip().split("\n"):
    if line.strip():
        print(f"   {line.strip()}")

# 6. Streamlit
print()
print("6. Streamlit App:")
try:
    import urllib.request
    r = urllib.request.urlopen("http://localhost:8501/_stcore/health", timeout=5)
    print(f"   PASS  http://localhost:8501 — {r.read().decode()}")
except Exception as e:
    print(f"   FAIL  {e}")
    issues.append("Streamlit not responding")

# Summary
print()
print("=" * 55)
if issues:
    print(f"ISSUES FOUND ({len(issues)}):")
    for iss in issues:
        print(f"  - {iss}")
else:
    print("ALL SYSTEMS GO — Ready for demo")
print("=" * 55)
