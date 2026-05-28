"""Deep audit of every detection algorithm's inputs, logic, and per-user results."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
load_dotenv()

import numpy as np
import pandas as pd
from datetime import date, timedelta
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import IsolationForest
from sklearn.svm import OneClassSVM
from sklearn.neighbors import LocalOutlierFactor
from comparison.run_comparison import (
    DATA_DIR, ATTACK_ENTITIES, FEATURE_COLS,
    _build_user_device_map, engineer_weekly_features,
)

# --- Feature Engineering ---
log_dir = DATA_DIR / "auth"
csv_files = sorted(log_dir.glob("*.csv"))
start = date.fromisoformat(csv_files[0].stem)
end = date.fromisoformat(csv_files[-1].stem) + timedelta(days=1)

user_device_map = _build_user_device_map()
from simulator.entities import generate_all
entities = generate_all()
user_ids = entities["users"]["user_id"].tolist()[:250]
features_df = engineer_weekly_features(start, end, user_ids, user_device_map)

n_weeks = int(features_df["week_idx"].max()) + 1
split_week = n_weeks // 2

baseline = features_df[features_df["week_idx"] < split_week]
test = features_df[features_df["week_idx"] >= split_week]

baseline_agg = baseline.groupby("user_id")[FEATURE_COLS].mean().reindex(user_ids).fillna(0)
test_agg = test.groupby("user_id")[FEATURE_COLS].mean().reindex(user_ids).fillna(0)

scaler = StandardScaler()
X_baseline = scaler.fit_transform(baseline_agg.values)
X_test = scaler.transform(test_agg.values)

user_idx_map = {uid: i for i, uid in enumerate(user_ids)}

# ============================================================
# Z-SCORE DEEP AUDIT
# ============================================================
print("=" * 100)
print("Z-SCORE ANALYSIS: EACH ATTACK USER vs BASELINE POPULATION")
print("=" * 100)

for uid in ATTACK_ENTITIES:
    idx = user_idx_map[uid]
    z_vals = X_test[idx]
    abs_z = np.abs(z_vals)
    max_z = abs_z.max()
    max_feat = FEATURE_COLS[int(abs_z.argmax())]

    attack_info = ATTACK_ENTITIES[uid]
    print(f"\n--- {uid} ({attack_info['name']}) ---")
    print(f"  Max |z|: {max_z:.3f} on feature: {max_feat}")
    print(f"  Features with |z| > 3: {int((abs_z > 3).sum())}")
    print(f"  Features with |z| > 2: {int((abs_z > 2).sum())}")
    print(f"  Features with |z| > 1: {int((abs_z > 1).sum())}")

    sorted_idx = np.argsort(-abs_z)
    header = f"  {'Feature':<30} {'BL Mean':>12} {'BL Std':>12} {'Test Val':>12} {'Z-Score':>10}"
    print(header)
    for fi in sorted_idx:
        feat = FEATURE_COLS[fi]
        bl_mean = scaler.mean_[fi]
        bl_std = np.sqrt(scaler.var_[fi])
        test_val = float(test_agg.iloc[idx][feat])
        z = z_vals[fi]
        marker = " ***" if abs(z) > 3 else (" **" if abs(z) > 2 else "")
        print(f"  {feat:<30} {bl_mean:>12.4f} {bl_std:>12.4f} {test_val:>12.4f} {z:>10.3f}{marker}")

# Normal users z-score distribution
normal_mask = np.array([uid not in ATTACK_ENTITIES for uid in user_ids])
normal_max_z = np.abs(X_test[normal_mask]).max(axis=1)
normal_flagged = int((normal_max_z > 3).sum())
total_normal = int(normal_mask.sum())
print(f"\n--- NORMAL USER Z-SCORE DISTRIBUTION ---")
print(f"  Normal users with max |z| > 3: {normal_flagged}/{total_normal} ({100*normal_flagged/total_normal:.1f}%)")
pcts = [50, 75, 90, 95, 99]
for p in pcts:
    print(f"  p{p}: {np.percentile(normal_max_z, p):.3f}")
print(f"  Max across all normal users: {normal_max_z.max():.3f}")

# ============================================================
# IFOREST / LOF / OCSVM DEEP AUDIT
# ============================================================
print("\n" + "=" * 100)
print("IFOREST / LOF / OCSVM: ALGORITHM AUDIT")
print("=" * 100)

# IForest
iso = IsolationForest(contamination=0.05, random_state=42, n_estimators=200)
iso.fit(X_baseline)
iso_pred = iso.predict(X_test)
iso_scores = iso.score_samples(X_test)

print("\n--- Isolation Forest ---")
print(f"  Threshold (auto from 5% contamination on baseline): {iso.offset_:.4f}")
for uid in ATTACK_ENTITIES:
    idx = user_idx_map[uid]
    pred = iso_pred[idx]
    score = iso_scores[idx]
    det = "DETECTED" if pred == -1 else "MISSED"
    print(f"  {uid}: score={score:.4f}, threshold={iso.offset_:.4f}, {det}")

iso_normal_flagged = int((iso_pred[normal_mask] == -1).sum())
print(f"  Normal users flagged: {iso_normal_flagged}/{total_normal} ({100*iso_normal_flagged/total_normal:.1f}%)")

# LOF
lof = LocalOutlierFactor(n_neighbors=20, contamination=0.05, novelty=True)
lof.fit(X_baseline)
lof_pred = lof.predict(X_test)
lof_scores = lof.score_samples(X_test)

print("\n--- Local Outlier Factor ---")
print(f"  Threshold (auto from 5% contamination on baseline): {lof.offset_:.4f}")
for uid in ATTACK_ENTITIES:
    idx = user_idx_map[uid]
    pred = lof_pred[idx]
    score = lof_scores[idx]
    det = "DETECTED" if pred == -1 else "MISSED"
    print(f"  {uid}: score={score:.4f}, threshold={lof.offset_:.4f}, {det}")

lof_normal_flagged = int((lof_pred[normal_mask] == -1).sum())
print(f"  Normal users flagged: {lof_normal_flagged}/{total_normal} ({100*lof_normal_flagged/total_normal:.1f}%)")

# OCSVM
svm = OneClassSVM(kernel="rbf", gamma="scale", nu=0.05)
svm.fit(X_baseline)
svm_pred = svm.predict(X_test)
svm_scores = svm.decision_function(X_test)

print("\n--- One-Class SVM ---")
for uid in ATTACK_ENTITIES:
    idx = user_idx_map[uid]
    pred = svm_pred[idx]
    score = svm_scores[idx]
    det = "DETECTED" if pred == -1 else "MISSED"
    print(f"  {uid}: decision_fn={score:.4f}, {det}")

svm_normal_flagged = int((svm_pred[normal_mask] == -1).sum())
print(f"  Normal users flagged: {svm_normal_flagged}/{total_normal} ({100*svm_normal_flagged/total_normal:.1f}%)")

# ============================================================
# TEMPORAL Z-SCORE AUDIT
# ============================================================
print("\n" + "=" * 100)
print("TEMPORAL Z-SCORE: PER-USER SELF-BASELINE")
print("=" * 100)

train_weeks = n_weeks // 2
train_data = features_df[features_df["week_idx"] < train_weeks]
test_data = features_df[features_df["week_idx"] >= train_weeks]

for uid in ATTACK_ENTITIES:
    user_train = train_data[train_data["user_id"] == uid][FEATURE_COLS].fillna(0)
    user_test = test_data[test_data["user_id"] == uid][FEATURE_COLS].fillna(0)

    if user_train.empty or user_test.empty:
        print(f"\n  {uid}: no data in train or test!")
        continue

    train_mean = user_train.mean()
    train_std = user_train.std().replace(0, 1)
    test_z = ((user_test - train_mean) / train_std).abs()
    max_z_val = float(test_z.max().max())
    max_feat = test_z.max().idxmax()

    print(f"\n--- {uid} ({ATTACK_ENTITIES[uid]['name']}) ---")
    print(f"  Self-baseline max |z|: {max_z_val:.3f} on {max_feat}")
    print(f"  Train weeks: {len(user_train)}, Test weeks: {len(user_test)}")

    # Show top features by max z across test weeks
    feat_max_z = test_z.max()
    top_feats = feat_max_z.sort_values(ascending=False).head(10)
    print(f"  {'Feature':<30} {'Max |z|':>10} {'Train Mean':>12} {'Train Std':>12}")
    for feat, z in top_feats.items():
        print(f"  {feat:<30} {z:>10.3f} {train_mean[feat]:>12.4f} {train_std[feat]:>12.4f}")

# How many normal users have temporal max |z| > 3?
temporal_normal_flagged = 0
for uid in user_ids:
    if uid in ATTACK_ENTITIES:
        continue
    ut = train_data[train_data["user_id"] == uid][FEATURE_COLS].fillna(0)
    ue = test_data[test_data["user_id"] == uid][FEATURE_COLS].fillna(0)
    if ut.empty or ue.empty:
        continue
    tm = ut.mean()
    ts = ut.std().replace(0, 1)
    tz = ((ue - tm) / ts).abs()
    if float(tz.max().max()) > 3.0:
        temporal_normal_flagged += 1

print(f"\n  Normal users with temporal max |z| > 3: {temporal_normal_flagged}/{total_normal} ({100*temporal_normal_flagged/total_normal:.1f}%)")

# ============================================================
# RAW FEATURE COMPARISON: BASELINE vs TEST for ATTACK USERS
# ============================================================
print("\n" + "=" * 100)
print("RAW FEATURE VALUES: BASELINE vs TEST for ATTACK USERS")
print("=" * 100)

for uid in ATTACK_ENTITIES:
    bl_feats = baseline[baseline["user_id"] == uid][FEATURE_COLS].mean()
    test_feats = test[test["user_id"] == uid][FEATURE_COLS].mean()
    print(f"\n--- {uid} ({ATTACK_ENTITIES[uid]['name']}) ---")
    print(f"  {'Feature':<30} {'Baseline':>12} {'Test':>12} {'Change':>12} {'% Change':>10}")
    for feat in FEATURE_COLS:
        bl_val = float(bl_feats[feat])
        test_val = float(test_feats[feat])
        change = test_val - bl_val
        pct = (change / max(abs(bl_val), 0.0001)) * 100
        marker = " <<" if abs(pct) > 50 else ""
        print(f"  {feat:<30} {bl_val:>12.4f} {test_val:>12.4f} {change:>12.4f} {pct:>9.1f}%{marker}")

# ============================================================
# POPULATION STATS for reference
# ============================================================
print("\n" + "=" * 100)
print("POPULATION BASELINE MEAN/STD (StandardScaler fit on baseline_agg)")
print("=" * 100)
print(f"  {'Feature':<30} {'Mean':>12} {'Std':>12} {'Min':>12} {'Max':>12}")
for i, feat in enumerate(FEATURE_COLS):
    bl_mean = scaler.mean_[i]
    bl_std = np.sqrt(scaler.var_[i])
    bl_min = float(baseline_agg[feat].min())
    bl_max = float(baseline_agg[feat].max())
    print(f"  {feat:<30} {bl_mean:>12.4f} {bl_std:>12.4f} {bl_min:>12.4f} {bl_max:>12.4f}")
