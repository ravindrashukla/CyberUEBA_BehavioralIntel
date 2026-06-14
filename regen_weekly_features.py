"""Regenerate weekly_features.csv over the FULL telemetry horizon (embedding-free).

Runs ONLY Phase 1 (feature engineering) of run_comparison — the 23 scalar
metrics computed directly from raw logs. Does NOT touch the embedding/ACECARD
phase, so there are no OpenAI calls. Replaces the stale 19-week feature CSV with
the full ~69-week table so it matches weekly_trajectories.
"""
from datetime import date

import numpy as np

from comparison.run_comparison import (
    ATTACK_ENTITIES,
    DATA_DIR,
    RESULTS_DIR,
    _build_user_device_map,
    engineer_weekly_features,
)


def main():
    auth_dir = DATA_DIR / "auth"
    csv_files = sorted(auth_dir.glob("*.csv"))
    first_date = date.fromisoformat(csv_files[0].stem)
    last_date = date.fromisoformat(csv_files[-1].stem)
    print(f"Telemetry range: {first_date} -> {last_date} ({len(csv_files)} days)")

    user_device_map = _build_user_device_map()

    from simulator.entities import generate_all
    entities = generate_all()
    all_user_ids = entities["users"]["user_id"].tolist()

    # Same user selection as run_comparison.main(): attack targets + seeded sample
    priority_users = [uid for uid in ATTACK_ENTITIES.keys() if uid in all_user_ids]
    remaining = [uid for uid in all_user_ids if uid not in priority_users]
    np.random.seed(42)
    sample_size = min(250 - len(priority_users), len(remaining))
    sampled = list(np.random.choice(remaining, size=max(0, sample_size), replace=False))
    user_ids = priority_users + sampled
    print(f"Users: {len(user_ids)} ({len(priority_users)} attack targets + {len(sampled)} sampled)")

    features_df = engineer_weekly_features(first_date, last_date, user_ids, user_device_map)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "weekly_features.csv"
    features_df.to_csv(out, index=False)
    print(f"\nWrote {out}")
    print(f"  rows={len(features_df)}  users={features_df.user_id.nunique()}  "
          f"weeks={features_df.week_idx.min()}..{features_df.week_idx.max()}  "
          f"feature_cols={len([c for c in features_df.columns if c not in {'user_id','week_idx','week_start','week_end'}])}")


if __name__ == "__main__":
    main()
