"""Round 4 Attack Injection Audit: traces exactly how many attack events get
injected and how they affect weekly features.

Answers:
  1. Attack event counts per user, log type, week
  2. Attack-to-normal event ratio (baseline vs test period)
  3. Feature impact: feature values WITH vs WITHOUT attack events
  4. Attack timing: which weeks each attack is active
  5. Auth methods breakdown for USR-042, USR-118 vs normal user
  6. Per-week feature trajectory for each attack user's top feature

Run from project root:
    python scripts/audit_round4_attack_injection.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from datetime import date, timedelta
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd

from comparison.run_comparison import (
    DATA_DIR,
    ATTACK_ENTITIES,
    FEATURE_COLS,
    _build_user_device_map,
    load_week_csvs,
)
from simulator.config import ATTACK_SCENARIOS, SIM_START

# ── Constants ────────────────────────────────────────────────────────────────

LOG_TYPES = ["auth", "file_access", "endpoint", "network", "dns"]

# User column name per log type
USER_COL = {
    "auth": "user_id",
    "file_access": "user_id",
    "endpoint": "user_id",
    "network": "device_id",  # linked via user_device_map
    "dns": "device_id",      # linked via user_device_map
}

ATTACK_USERS = list(ATTACK_ENTITIES.keys())  # USR-156, USR-234, USR-042, USR-118


# ── Helpers ──────────────────────────────────────────────────────────────────

def _discover_date_range() -> tuple[date, date, int]:
    auth_dir = DATA_DIR / "auth"
    csvs = sorted(auth_dir.glob("*.csv"))
    first = date.fromisoformat(csvs[0].stem)
    last = date.fromisoformat(csvs[-1].stem)
    return first, last, len(csvs)


def _load_all_csvs(log_type: str, first: date, last: date) -> pd.DataFrame:
    """Load all daily CSVs for a log type into one DataFrame."""
    log_dir = DATA_DIR / log_type
    if not log_dir.exists():
        return pd.DataFrame()
    frames = []
    d = first
    while d <= last:
        csv_path = log_dir / f"{d.isoformat()}.csv"
        if csv_path.exists():
            df = pd.read_csv(csv_path, low_memory=False)
            df["_date"] = d
            frames.append(df)
        d += timedelta(days=1)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _week_idx(d: date, first: date) -> int:
    return (d - first).days // 7


def _has_attack(df: pd.DataFrame) -> pd.Series:
    """Return boolean mask for rows that have a non-null attack_id."""
    if "attack_id" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["attack_id"].notna() & (df["attack_id"] != "")


def _filter_user_events(df: pd.DataFrame, uid: str, dev_ids: list[str],
                         log_type: str) -> pd.DataFrame:
    """Filter events belonging to a user (directly or via device mapping)."""
    if df.empty:
        return df
    col = USER_COL[log_type]
    if col not in df.columns:
        return pd.DataFrame()
    if log_type in ("network", "dns"):
        return df[df[col].isin(dev_ids)] if dev_ids else pd.DataFrame()
    return df[df[col] == uid]


# ── Section 1: Attack Event Counts ──────────────────────────────────────────

def section1_attack_counts(all_data: dict, user_device_map: dict, first: date):
    print("\n" + "=" * 90)
    print("SECTION 1: ATTACK EVENT COUNTS")
    print("  Total attack events vs total normal events per user per log type")
    print("=" * 90)

    for uid in ATTACK_USERS:
        dev_ids = user_device_map.get(uid, [])
        attack_info = ATTACK_ENTITIES[uid]
        print(f"\n  {uid} ({attack_info['name']})  devices={dev_ids}")
        print(f"  {'Log Type':<15} {'Total Events':>14} {'Attack Events':>14} {'Normal Events':>14} {'Attack %':>10}")
        print(f"  {'-'*15} {'-'*14} {'-'*14} {'-'*14} {'-'*10}")

        for lt in LOG_TYPES:
            df = all_data[lt]
            user_df = _filter_user_events(df, uid, dev_ids, lt)
            total = len(user_df)
            atk = int(_has_attack(user_df).sum())
            normal = total - atk
            pct = (100.0 * atk / total) if total > 0 else 0.0
            print(f"  {lt:<15} {total:>14,} {atk:>14,} {normal:>14,} {pct:>9.2f}%")

        # Per-week attack counts (top log type by attack events)
        print(f"\n  Per-week attack event counts (all log types combined):")
        print(f"  {'Week':>6}", end="")
        for lt in LOG_TYPES:
            print(f" {lt:>12}", end="")
        print(f" {'Total Atk':>12}")

        n_weeks = 19
        for wk in range(n_weeks + 1):
            line = f"  {wk:>6}"
            total_atk = 0
            for lt in LOG_TYPES:
                df = all_data[lt]
                user_df = _filter_user_events(df, uid, dev_ids, lt)
                if user_df.empty or "_date" not in user_df.columns:
                    line += f" {0:>12}"
                    continue
                wk_mask = user_df["_date"].apply(lambda d: _week_idx(d, first)) == wk
                wk_df = user_df[wk_mask]
                atk = int(_has_attack(wk_df).sum())
                total_atk += atk
                line += f" {atk:>12}"
            line += f" {total_atk:>12}"
            if total_atk > 0:
                print(line)


# ── Section 2: Attack Event Ratio (Baseline vs Test) ────────────────────────

def section2_attack_ratio(all_data: dict, user_device_map: dict, first: date):
    print("\n" + "=" * 90)
    print("SECTION 2: ATTACK EVENT RATIO (Baseline weeks 0-8 vs Test weeks 9-18)")
    print("  Attack events as % of total events per period")
    print("=" * 90)

    for uid in ATTACK_USERS:
        dev_ids = user_device_map.get(uid, [])
        attack_info = ATTACK_ENTITIES[uid]
        print(f"\n  {uid} ({attack_info['name']})")
        print(f"  {'Log Type':<14} | {'--- BASELINE (wk 0-8) ---':^38} | {'--- TEST (wk 9-18) ---':^38}")
        print(f"  {'':14} | {'Total':>10} {'AttackEvt':>10} {'Atk%':>8} {'Normal':>8} | {'Total':>10} {'AttackEvt':>10} {'Atk%':>8} {'Normal':>8}")
        print(f"  {'-'*14}-+-{'-'*38}-+-{'-'*38}")

        for lt in LOG_TYPES:
            df = all_data[lt]
            user_df = _filter_user_events(df, uid, dev_ids, lt)
            if user_df.empty or "_date" not in user_df.columns:
                print(f"  {lt:<14} | {'N/A':^38} | {'N/A':^38}")
                continue

            wk_col = user_df["_date"].apply(lambda d: _week_idx(d, first))
            is_atk = _has_attack(user_df)

            # Baseline: weeks 0-8
            bl_mask = wk_col <= 8
            bl_total = int(bl_mask.sum())
            bl_atk = int((bl_mask & is_atk).sum())
            bl_pct = (100.0 * bl_atk / bl_total) if bl_total > 0 else 0.0
            bl_normal = bl_total - bl_atk

            # Test: weeks 9-18
            test_mask = wk_col > 8
            t_total = int(test_mask.sum())
            t_atk = int((test_mask & is_atk).sum())
            t_pct = (100.0 * t_atk / t_total) if t_total > 0 else 0.0
            t_normal = t_total - t_atk

            print(f"  {lt:<14} | {bl_total:>10,} {bl_atk:>10,} {bl_pct:>7.2f}% {bl_normal:>8,} | "
                  f"{t_total:>10,} {t_atk:>10,} {t_pct:>7.2f}% {t_normal:>8,}")


# ── Section 3: Feature Impact Trace ─────────────────────────────────────────

def _compute_auth_features(df: pd.DataFrame) -> dict:
    """Compute auth-related features from a dataframe of auth events."""
    features = {}
    features["auth_total"] = len(df)
    features["auth_failed"] = int((df["success"] == False).sum()) if not df.empty and "success" in df.columns else 0
    features["auth_fail_rate"] = features["auth_failed"] / max(features["auth_total"], 1)
    features["auth_unique_sources"] = df["source_ip"].nunique() if not df.empty and "source_ip" in df.columns else 0
    features["auth_unique_dests"] = df["dest_system"].nunique() if not df.empty and "dest_system" in df.columns else 0
    if not df.empty and "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], errors="coerce")
        hours = ts.dt.hour
        features["auth_off_hours_ratio"] = float(((hours < 8) | (hours >= 18)).sum()) / max(len(df), 1)
    else:
        features["auth_off_hours_ratio"] = 0.0
    features["auth_methods_used"] = df["auth_method"].nunique() if not df.empty and "auth_method" in df.columns else 0
    return features


def _compute_file_features(df: pd.DataFrame) -> dict:
    """Compute file-access features."""
    features = {}
    features["file_total"] = len(df)
    features["file_unique_paths"] = df["file_path"].nunique() if not df.empty and "file_path" in df.columns else 0
    if not df.empty and "data_classification" in df.columns:
        total_f = max(len(df), 1)
        features["file_restricted_ratio"] = float((df["data_classification"] == "restricted").sum()) / total_f
        features["file_confidential_ratio"] = float((df["data_classification"] == "confidential").sum()) / total_f
    else:
        features["file_restricted_ratio"] = 0.0
        features["file_confidential_ratio"] = 0.0
    if not df.empty and "operation" in df.columns:
        features["file_write_ratio"] = float((df["operation"] == "write").sum()) / max(len(df), 1)
    else:
        features["file_write_ratio"] = 0.0
    features["file_total_bytes"] = float(df["file_size_bytes"].sum()) if not df.empty and "file_size_bytes" in df.columns else 0.0
    return features


def _compute_network_features(df: pd.DataFrame) -> dict:
    """Compute network features."""
    features = {}
    features["net_bytes_out"] = float(df["bytes_out"].sum()) if not df.empty and "bytes_out" in df.columns else 0.0
    features["net_unique_dsts"] = df["dst_ip"].nunique() if not df.empty and "dst_ip" in df.columns else 0
    if not df.empty and "dst_ip" in df.columns:
        external = df["dst_ip"].apply(lambda ip: not str(ip).startswith(("10.", "192.168.", "172.")))
        features["net_external_ratio"] = float(external.sum()) / max(len(df), 1)
    else:
        features["net_external_ratio"] = 0.0
    return features


def section3_feature_impact(all_data: dict, user_device_map: dict, first: date):
    print("\n" + "=" * 90)
    print("SECTION 3: FEATURE IMPACT TRACE")
    print("  Feature values WITH attack events vs WITHOUT (attack rows removed)")
    print("  Focus features: auth_methods_used, net_external_ratio, file_restricted_ratio")
    print("=" * 90)

    focus_features = [
        ("auth_methods_used", "auth", _compute_auth_features),
        ("auth_off_hours_ratio", "auth", _compute_auth_features),
        ("auth_fail_rate", "auth", _compute_auth_features),
        ("file_restricted_ratio", "file_access", _compute_file_features),
        ("file_confidential_ratio", "file_access", _compute_file_features),
        ("file_total", "file_access", _compute_file_features),
        ("net_external_ratio", "network", _compute_network_features),
        ("net_bytes_out", "network", _compute_network_features),
        ("net_unique_dsts", "network", _compute_network_features),
    ]

    for uid in ATTACK_USERS:
        dev_ids = user_device_map.get(uid, [])
        attack_info = ATTACK_ENTITIES[uid]
        print(f"\n  {uid} ({attack_info['name']})")
        print(f"  {'Feature':<25} {'Week':>5} {'With Attacks':>14} {'No Attacks':>14} {'Delta':>10} {'Delta%':>9}")
        print(f"  {'-'*25} {'-'*5} {'-'*14} {'-'*14} {'-'*10} {'-'*9}")

        for feat_name, lt, compute_fn in focus_features:
            df = all_data[lt]
            user_df = _filter_user_events(df, uid, dev_ids, lt)
            if user_df.empty:
                continue

            # Compute per-week, only show weeks with attack events
            wk_col = user_df["_date"].apply(lambda d: _week_idx(d, first))
            is_atk = _has_attack(user_df)

            for wk in sorted(wk_col.unique()):
                wk_mask = wk_col == wk
                wk_df = user_df[wk_mask]
                wk_atk = is_atk[wk_mask]

                if wk_atk.sum() == 0:
                    continue  # No attack events this week for this log type

                # Feature WITH attack events
                feat_with = compute_fn(wk_df)
                val_with = feat_with.get(feat_name, 0)

                # Feature WITHOUT attack events
                clean_df = wk_df[~wk_atk]
                if clean_df.empty:
                    val_without = 0
                else:
                    feat_without = compute_fn(clean_df)
                    val_without = feat_without.get(feat_name, 0)

                delta = val_with - val_without
                if val_without != 0:
                    delta_pct = 100.0 * delta / abs(val_without)
                elif val_with != 0:
                    delta_pct = float("inf")
                else:
                    delta_pct = 0.0

                if abs(delta) > 1e-6:
                    pct_str = f"{delta_pct:>8.1f}%" if abs(delta_pct) < 1e6 else "     inf%"
                    if isinstance(val_with, float) and abs(val_with) < 100:
                        print(f"  {feat_name:<25} {int(wk):>5} {val_with:>14.4f} {val_without:>14.4f} {delta:>+10.4f} {pct_str}")
                    else:
                        print(f"  {feat_name:<25} {int(wk):>5} {val_with:>14,.1f} {val_without:>14,.1f} {delta:>+10,.1f} {pct_str}")


# ── Section 4: Attack Timing ────────────────────────────────────────────────

def section4_attack_timing(first: date, last: date):
    print("\n" + "=" * 90)
    print("SECTION 4: ATTACK TIMING")
    print(f"  Data range: {first} to {last}")
    print(f"  Baseline period: weeks 0-8 ({first} to {first + timedelta(days=63)})")
    print(f"  Test period: weeks 9+ ({first + timedelta(days=63)} to {last})")
    print("=" * 90)

    n_weeks = (last - first).days // 7 + 1

    for scenario in ATTACK_SCENARIOS:
        atk_id = scenario["id"]
        atk_type = scenario["type"]
        atk_start = scenario.get("start")
        if not isinstance(atk_start, date):
            continue

        # Determine end date
        if "duration_days" in scenario:
            atk_end = atk_start + timedelta(days=scenario["duration_days"])
        elif "duration_hours" in scenario:
            atk_end = atk_start  # Same day
        elif "escalation_months" in scenario:
            atk_end = atk_start + timedelta(days=scenario["escalation_months"] * 30)
        elif "dormant_days" in scenario:
            atk_end = atk_start + timedelta(days=scenario["dormant_days"] + 30)
        else:
            atk_end = atk_start + timedelta(days=30)

        # Determine target user
        target = (scenario.get("target_user") or scenario.get("user")
                  or scenario.get("compromised_user") or "N/A")

        # Compute week indices relative to data start
        if atk_start < first:
            start_wk = f"before data (at {atk_start})"
            start_wk_idx = None
        else:
            start_wk_idx = _week_idx(atk_start, first)
            start_wk = f"week {start_wk_idx}"

        if atk_end > last:
            end_wk = f"after data ends (at {atk_end})"
            end_wk_idx = None
        else:
            end_wk_idx = _week_idx(atk_end, first)
            end_wk = f"week {end_wk_idx}"

        # Check if active during baseline
        baseline_end = first + timedelta(days=63)
        active_in_baseline = atk_start <= baseline_end
        active_in_test = atk_end >= first + timedelta(days=63)

        contamination = ""
        if active_in_baseline and target in ATTACK_ENTITIES:
            contamination = " ** BASELINE CONTAMINATED **"

        print(f"\n  {atk_id} ({atk_type})")
        print(f"    Target:        {target}")
        print(f"    Attack dates:  {atk_start} to {atk_end}")
        print(f"    Active weeks:  {start_wk} to {end_wk}")
        print(f"    In baseline?   {'YES' if active_in_baseline else 'no'}")
        print(f"    In test?       {'YES' if active_in_test else 'no'}{contamination}")

        # Draw a timeline
        if start_wk_idx is not None or end_wk_idx is not None:
            eff_start = max(start_wk_idx if start_wk_idx is not None else 0, 0)
            eff_end = min(end_wk_idx if end_wk_idx is not None else n_weeks, n_weeks)
            timeline = ["." for _ in range(n_weeks)]
            for w in range(eff_start, min(eff_end + 1, n_weeks)):
                timeline[w] = "X"
            # Mark baseline/test boundary
            print(f"    Timeline:      ", end="")
            for w in range(n_weeks):
                sep = "|" if w == 9 else ""
                print(f"{sep}{timeline[w]}", end="")
            print()
            print(f"    Legend:         {''.join(str(w % 10) for w in range(n_weeks))}")
            print(f"                    {'B' * 9}|{'T' * (n_weeks - 9)} (B=baseline, T=test)")


# ── Section 5: Auth Methods Breakdown ────────────────────────────────────────

def section5_auth_methods(all_data: dict, user_device_map: dict, first: date):
    print("\n" + "=" * 90)
    print("SECTION 5: AUTH METHODS BREAKDOWN")
    print("  Unique auth_method values per week for USR-042, USR-118, and a normal user")
    print("=" * 90)

    auth_df = all_data["auth"]
    if auth_df.empty or "auth_method" not in auth_df.columns:
        print("  No auth data with auth_method column found.")
        return

    # Pick a normal user for comparison (first user that is NOT an attack user)
    all_users = auth_df["user_id"].unique()
    normal_user = None
    for u in sorted(all_users):
        if u not in ATTACK_ENTITIES:
            normal_user = u
            break

    compare_users = ["USR-042", "USR-118"]
    if normal_user:
        compare_users.append(normal_user)

    for uid in compare_users:
        is_attack = uid in ATTACK_ENTITIES
        label = ATTACK_ENTITIES[uid]["name"] if is_attack else "Normal User"
        user_auth = auth_df[auth_df["user_id"] == uid].copy()
        if user_auth.empty:
            print(f"\n  {uid} ({label}): No auth events found")
            continue

        user_auth["_wk"] = user_auth["_date"].apply(lambda d: _week_idx(d, first))
        is_atk = _has_attack(user_auth)

        print(f"\n  {uid} ({label})")
        print(f"  {'Week':>6} {'Total':>7} {'Attack':>7} {'All Methods':<35} {'Attack-Only Methods':<30}")
        print(f"  {'-'*6} {'-'*7} {'-'*7} {'-'*35} {'-'*30}")

        for wk in sorted(user_auth["_wk"].unique()):
            wk_mask = user_auth["_wk"] == wk
            wk_df = user_auth[wk_mask]
            wk_atk = is_atk[wk_mask]

            total = len(wk_df)
            atk_count = int(wk_atk.sum())

            all_methods = sorted(wk_df["auth_method"].dropna().unique())
            # Methods used ONLY in attack events (not in normal events)
            if atk_count > 0:
                normal_methods = set(wk_df[~wk_atk]["auth_method"].dropna().unique())
                attack_methods = set(wk_df[wk_atk]["auth_method"].dropna().unique())
                attack_only = sorted(attack_methods - normal_methods)
            else:
                attack_only = []

            all_str = ", ".join(all_methods) if all_methods else "none"
            atk_only_str = ", ".join(attack_only) if attack_only else "-"

            print(f"  {int(wk):>6} {total:>7} {atk_count:>7} {all_str:<35} {atk_only_str:<30}")


# ── Section 6: Per-Week Feature Trajectory ───────────────────────────────────

def section6_feature_trajectory(all_data: dict, user_device_map: dict, first: date, last: date):
    print("\n" + "=" * 90)
    print("SECTION 6: PER-WEEK FEATURE TRAJECTORY (top detectable feature per attack user)")
    print("  Shows feature value for EVERY week 0-18 with ASCII sparkline")
    print("=" * 90)

    # For each attack user, identify their most detectable feature and compute it per week
    # Based on the comparison report, typical top features are:
    top_features = {
        "USR-156": [
            ("file_restricted_ratio", "file_access", _compute_file_features),
            ("file_confidential_ratio", "file_access", _compute_file_features),
            ("auth_off_hours_ratio", "auth", _compute_auth_features),
        ],
        "USR-234": [
            ("net_external_ratio", "network", _compute_network_features),
            ("net_unique_dsts", "network", _compute_network_features),
        ],
        "USR-042": [
            ("auth_methods_used", "auth", _compute_auth_features),
            ("auth_off_hours_ratio", "auth", _compute_auth_features),
            ("net_unique_dsts", "network", _compute_network_features),
        ],
        "USR-118": [
            ("auth_methods_used", "auth", _compute_auth_features),
            ("auth_off_hours_ratio", "auth", _compute_auth_features),
            ("net_external_ratio", "network", _compute_network_features),
            ("file_restricted_ratio", "file_access", _compute_file_features),
        ],
    }

    n_weeks = (last - first).days // 7 + 1

    # Also compute population stats for z-score context
    # Get list of all users appearing in auth data
    all_user_ids = all_data["auth"]["user_id"].unique() if not all_data["auth"].empty else []

    for uid in ATTACK_USERS:
        dev_ids = user_device_map.get(uid, [])
        attack_info = ATTACK_ENTITIES[uid]
        features_to_track = top_features.get(uid, [])
        if not features_to_track:
            continue

        print(f"\n  {uid} ({attack_info['name']})")
        print(f"  Attack starts: {attack_info.get('start', '?')}")

        for feat_name, lt, compute_fn in features_to_track:
            df = all_data[lt]
            user_df = _filter_user_events(df, uid, dev_ids, lt)
            if user_df.empty:
                continue

            wk_col = user_df["_date"].apply(lambda d: _week_idx(d, first))

            # Compute feature value per week
            weekly_vals = []
            weekly_vals_clean = []  # without attack events
            for wk in range(n_weeks):
                wk_df = user_df[wk_col == wk]
                if wk_df.empty:
                    weekly_vals.append(None)
                    weekly_vals_clean.append(None)
                    continue
                feat = compute_fn(wk_df)
                weekly_vals.append(feat.get(feat_name, 0))

                # Clean version
                is_atk = _has_attack(wk_df)
                clean_df = wk_df[~is_atk]
                if clean_df.empty:
                    weekly_vals_clean.append(0)
                else:
                    feat_c = compute_fn(clean_df)
                    weekly_vals_clean.append(feat_c.get(feat_name, 0))

            # Compute population mean per week (sample of 10 normal users for speed)
            pop_weekly = []
            sample_normals = [u for u in all_user_ids if u not in ATTACK_ENTITIES][:20]
            for wk in range(n_weeks):
                pop_vals = []
                for norm_uid in sample_normals:
                    norm_devs = user_device_map.get(norm_uid, [])
                    norm_df = _filter_user_events(df, norm_uid, norm_devs, lt)
                    if norm_df.empty:
                        continue
                    norm_wk_col = norm_df["_date"].apply(lambda d: _week_idx(d, first))
                    norm_wk_df = norm_df[norm_wk_col == wk]
                    if norm_wk_df.empty:
                        pop_vals.append(0)
                        continue
                    nfeat = compute_fn(norm_wk_df)
                    pop_vals.append(nfeat.get(feat_name, 0))
                if pop_vals:
                    pop_weekly.append(np.mean(pop_vals))
                else:
                    pop_weekly.append(0)

            # Compute baseline stats for z-score
            baseline_vals = [v for v in weekly_vals_clean[:9] if v is not None]
            if baseline_vals:
                bl_mean = np.mean(baseline_vals)
                bl_std = np.std(baseline_vals)
                if bl_std < 1e-10:
                    bl_std = 1.0
            else:
                bl_mean = 0
                bl_std = 1.0

            # Print table
            print(f"\n  Feature: {feat_name}")
            print(f"  Baseline mean={bl_mean:.4f}, std={bl_std:.4f}")
            is_float = isinstance(weekly_vals[0], float) if weekly_vals[0] is not None else True
            if is_float:
                print(f"  {'Wk':>4} {'Value':>10} {'Clean':>10} {'Delta':>10} {'PopMean':>10} {'Z-score':>8} {'Spark':<20}")
            else:
                print(f"  {'Wk':>4} {'Value':>10} {'Clean':>10} {'Delta':>10} {'PopMean':>10} {'Z-score':>8} {'Spark':<20}")
            print(f"  {'-'*4} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*8} {'-'*20}")

            # Sparkline chars
            spark_chars = " _.-:=+#@"

            for wk in range(n_weeks):
                val = weekly_vals[wk]
                val_c = weekly_vals_clean[wk]
                pop_m = pop_weekly[wk] if wk < len(pop_weekly) else 0

                if val is None:
                    print(f"  {wk:>4} {'N/A':>10}")
                    continue

                delta = val - val_c if val_c is not None else 0
                z = (val - bl_mean) / bl_std if bl_std > 1e-10 else 0.0

                # Sparkline based on z-score
                z_abs = min(abs(z), 8)
                spark_idx = int(z_abs)
                spark_idx = min(spark_idx, len(spark_chars) - 1)
                spark_bar = spark_chars[spark_idx] * (int(z_abs * 2) + 1)

                # Mark baseline/test boundary
                period = "BL" if wk <= 8 else "TS"

                if is_float and abs(val) < 100:
                    print(f"  {wk:>4} {val:>10.4f} {val_c:>10.4f} {delta:>+10.4f} {pop_m:>10.4f} {z:>+8.2f} {spark_bar:<20} {period}")
                else:
                    print(f"  {wk:>4} {val:>10,.1f} {val_c:>10,.1f} {delta:>+10,.1f} {pop_m:>10,.1f} {z:>+8.2f} {spark_bar:<20} {period}")


# ── Section 7: Summary ──────────────────────────────────────────────────────

def section7_summary(all_data: dict, user_device_map: dict, first: date):
    print("\n" + "=" * 90)
    print("SECTION 7: SUMMARY - Is Detection From Attack Injection or Random Variation?")
    print("=" * 90)

    for uid in ATTACK_USERS:
        dev_ids = user_device_map.get(uid, [])
        attack_info = ATTACK_ENTITIES[uid]

        # Compute total attack vs normal across all log types
        total_attack = 0
        total_normal = 0
        for lt in LOG_TYPES:
            df = all_data[lt]
            user_df = _filter_user_events(df, uid, dev_ids, lt)
            if user_df.empty:
                continue
            atk = int(_has_attack(user_df).sum())
            total_attack += atk
            total_normal += len(user_df) - atk

        grand_total = total_attack + total_normal
        overall_pct = (100.0 * total_attack / grand_total) if grand_total > 0 else 0.0

        print(f"\n  {uid} ({attack_info['name']})")
        print(f"    Total events: {grand_total:,}")
        print(f"    Attack events: {total_attack:,} ({overall_pct:.2f}%)")
        print(f"    Normal events: {total_normal:,}")

        if overall_pct < 1.0:
            print(f"    VERDICT: Attack injection is <1% of events. Feature deltas are tiny.")
            print(f"             If z-score detects this user, the signal is likely from random")
            print(f"             variation or baseline contamination, NOT the injection itself.")
        elif overall_pct < 5.0:
            print(f"    VERDICT: Attack injection is {overall_pct:.1f}% of events. Marginal signal.")
            print(f"             Some features may shift detectably, but it depends on which")
            print(f"             features are affected and whether baseline is contaminated.")
        else:
            print(f"    VERDICT: Attack injection is {overall_pct:.1f}% of events. Significant signal.")
            print(f"             Simple z-scores can likely detect this user based on")
            print(f"             raw event volume changes alone.")


# ── Section 8: Device Sharing Warning ─────────────────────────────────────────

def section8_device_sharing(user_device_map: dict):
    print("\n" + "=" * 90)
    print("SECTION 8: DEVICE SHARING WARNING")
    print("  Users sharing the same device get identical network/DNS features")
    print("=" * 90)

    # Invert the map: device -> [users]
    device_users = defaultdict(list)
    for uid in ATTACK_USERS:
        for dev in user_device_map.get(uid, []):
            device_users[dev].append(uid)

    # Check for non-attack users sharing devices with attack users
    all_users_with_devs = {}
    for uid, devs in user_device_map.items():
        for dev in devs:
            if dev not in all_users_with_devs:
                all_users_with_devs[dev] = []
            all_users_with_devs[dev].append(uid)

    found_sharing = False
    for dev, users in all_users_with_devs.items():
        attack_users_on_dev = [u for u in users if u in ATTACK_ENTITIES]
        if len(attack_users_on_dev) > 1:
            found_sharing = True
            print(f"\n  *** CRITICAL: Device {dev} is shared by MULTIPLE attack users: {attack_users_on_dev}")
            print(f"      All users on this device: {users}")
            print(f"      This means network/DNS features for these users are IDENTICAL.")
            print(f"      Attack events from one user's scenario contaminate the other user's")
            print(f"      network/DNS feature values. This is a simulator entity-generation bug.")
            print(f"      The net_external_ratio, net_bytes_out, net_unique_dsts values shown")
            print(f"      for these users include BOTH users' attack injections + normal traffic.")

    if not found_sharing:
        print("\n  No device sharing between attack users detected.")

    # Show device mapping for all attack users
    print(f"\n  Attack user device assignments:")
    for uid in ATTACK_USERS:
        devs = user_device_map.get(uid, [])
        n_users_sharing = 0
        for dev in devs:
            n_users_sharing = len(all_users_with_devs.get(dev, []))
        print(f"    {uid} -> {devs} (shared by {n_users_sharing} total users)")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 90)
    print("ROUND 4 ATTACK INJECTION AUDIT")
    print("Traces exactly how many attack events get injected and their feature impact")
    print("=" * 90)

    first, last, n_days = _discover_date_range()
    print(f"\nData range: {first} to {last} ({n_days} days, ~{n_days // 7} weeks)")

    user_device_map = _build_user_device_map()
    for uid in ATTACK_USERS:
        devs = user_device_map.get(uid, [])
        print(f"  {uid} -> devices: {devs}")

    # Load all data once
    print("\nLoading all CSV data (this may take a moment)...")
    all_data = {}
    for lt in LOG_TYPES:
        print(f"  Loading {lt}...", end=" ", flush=True)
        all_data[lt] = _load_all_csvs(lt, first, last)
        n = len(all_data[lt])
        atk_col = "attack_id" in all_data[lt].columns
        print(f"{n:,} rows (has attack_id: {atk_col})")

    section1_attack_counts(all_data, user_device_map, first)
    section2_attack_ratio(all_data, user_device_map, first)
    section3_feature_impact(all_data, user_device_map, first)
    section4_attack_timing(first, last)
    section5_auth_methods(all_data, user_device_map, first)
    section6_feature_trajectory(all_data, user_device_map, first, last)
    section7_summary(all_data, user_device_map, first)

    # Section 8: Device sharing warning
    section8_device_sharing(user_device_map)

    print("\n" + "=" * 90)
    print("AUDIT COMPLETE")
    print("=" * 90)


if __name__ == "__main__":
    main()
