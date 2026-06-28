"""Generate composite score CSVs from existing trajectory data for Streamlit UI."""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detection.composite_scorer import (
    extract_user_features, compute_group_zscores, compute_composite_scores,
)
from detection.novelty_features import compute_novelty_metrics

RESULTS_DIR = Path("data/tier3_results")
ATTACKS = {"USR-042", "USR-118", "USR-156", "USR-234"}

traj_path = RESULTS_DIR / "all250_trajectories.csv"
traj_df = pd.read_csv(traj_path)
print(f"Loaded {len(traj_df)} trajectory rows")

user_feats = extract_user_features(traj_df)
zscored = compute_group_zscores(user_feats)

from dotenv import load_dotenv
load_dotenv()
from comparison.run_comparison import DATA_DIR, _build_user_device_map, engineer_weekly_features
from simulator.entities import generate_all
from datetime import date

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

entities = generate_all()
user_role_map = {}
for _, u in entities["users"].iterrows():
    role = u.get("role", "unknown")
    user_role_map[u["user_id"]] = ROLE_TO_GROUP.get(role, "unknown")

user_ids = entities["users"]["user_id"].tolist()
user_device_map = _build_user_device_map()
auth_dir = DATA_DIR / "auth"
csv_files = sorted(auth_dir.glob("*.csv"))
first_date = date.fromisoformat(csv_files[0].stem)
last_date = date.fromisoformat(csv_files[-1].stem)

print("Engineering features for novelty metrics...")
features_df = engineer_weekly_features(
    first_date, last_date, user_ids, user_device_map,
    user_role_groups=user_role_map,
)

from detection.novelty_features import annotate_qualitative_features
features_df = annotate_qualitative_features(features_df, user_role_map)

print("Computing novelty metrics...")
novelty_df = compute_novelty_metrics(features_df)
scores = compute_composite_scores(zscored, novelty_df=novelty_df)

scores.to_csv(RESULTS_DIR / "composite_scores.csv", index=False)
novelty_df.to_csv(RESULTS_DIR / "novelty_metrics.csv", index=False)
zscored.to_csv(RESULTS_DIR / "zscored_features.csv", index=False)

print(f"Saved composite_scores.csv ({len(scores)} rows)")
print(f"Saved novelty_metrics.csv ({len(novelty_df)} rows)")
print(f"Saved zscored_features.csv ({len(zscored)} rows)")

for uid in sorted(ATTACKS):
    row = scores[scores.uid == uid].iloc[0]
    rank = scores.index[scores.uid == uid][0] + 1
    print(f"  {uid}: Rank #{rank}, Composite={row.composite:.2f}, Novelty={row.novelty_score:.1f}")
