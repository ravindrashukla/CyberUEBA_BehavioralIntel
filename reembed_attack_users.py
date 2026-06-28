"""Re-embed only the 4 attack users after extending attack durations.

Reuses existing trajectory data for 246 normal users.
Only recomputes features + embeddings + drift for attack users.
Requires OPENAI_API_KEY in .env.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
from dotenv import load_dotenv
load_dotenv()

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from comparison.run_comparison import (
    DATA_DIR, ATTACK_ENTITIES, FEATURE_COLS,
    _build_user_device_map, engineer_weekly_features,
)
from comparison.run_tier3 import (
    RESULTS_DIR, build_entity_zoo, extract_weekly_trajectories,
)
from models.cyber_entity import Tier3Config

ATTACK_USERS = list(ATTACK_ENTITIES.keys())


def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set. Cannot use MockEmbedder.")
        sys.exit(1)

    from embeddings.embedder import Embedder
    from detection.reference_concepts import ConceptLibrary

    embedder = Embedder(api_key=api_key)
    print(f"Using REAL OpenAI embeddings (text-embedding-3-small)")

    # Load existing trajectory data
    existing_traj_path = RESULTS_DIR / "weekly_zone_trajectories.csv"
    existing_traj = pd.read_csv(existing_traj_path)
    n_normal = len(existing_traj[~existing_traj.user_id.isin(ATTACK_USERS)])
    print(f"Existing trajectories: {len(existing_traj)} rows ({n_normal} normal user rows to keep)")

    # Find date range from regenerated data
    auth_dir = DATA_DIR / "auth"
    csv_files = sorted(auth_dir.glob("*.csv"))
    first_date = date.fromisoformat(csv_files[0].stem)
    last_date = date.fromisoformat(csv_files[-1].stem)
    print(f"Data range: {first_date} to {last_date} ({len(csv_files)} days)")

    user_device_map = _build_user_device_map()

    from simulator.entities import generate_all
    entities = generate_all()

    # Feature engineering for ALL users (needed for population stats)
    # but we only embed the 4 attack users
    all_user_ids = entities["users"]["user_id"].tolist()
    print(f"\nPhase 1: Feature engineering for all {len(all_user_ids)} users...")
    features_df = engineer_weekly_features(first_date, last_date, all_user_ids, user_device_map)
    print(f"  {len(features_df)} feature rows computed")

    # Embed only attack users
    print(f"\nPhase 2: Embedding only {len(ATTACK_USERS)} attack users: {ATTACK_USERS}")
    concept_lib = ConceptLibrary(embedder=embedder)
    concept_lib.embed_concepts()

    config = Tier3Config()
    attack_features = features_df[features_df["user_id"].isin(ATTACK_USERS)]
    print(f"  {len(attack_features)} feature rows for attack users")

    entity_zoo = build_entity_zoo(
        ATTACK_USERS, features_df, entities, user_device_map,
        embedder, concept_lib, config,
    )

    # Extract trajectories for attack users
    print(f"\nPhase 3: Extracting trajectories for attack users...")
    new_attack_traj = extract_weekly_trajectories(entity_zoo, features_df)
    print(f"  {len(new_attack_traj)} new trajectory rows for attack users")

    # Merge: keep normal users from existing, replace attack users with new
    normal_traj = existing_traj[~existing_traj.user_id.isin(ATTACK_USERS)]
    merged = pd.concat([normal_traj, new_attack_traj], ignore_index=True)
    merged = merged.sort_values(["user_id", "week_idx"]).reset_index(drop=True)

    # Save
    backup_path = RESULTS_DIR / "weekly_zone_trajectories_backup.csv"
    existing_traj.to_csv(backup_path, index=False)
    print(f"\nBacked up existing trajectories to {backup_path}")

    merged.to_csv(existing_traj_path, index=False)
    print(f"Saved merged trajectories: {len(merged)} rows to {existing_traj_path}")

    # Verify
    n_attack_rows = len(merged[merged.user_id.isin(ATTACK_USERS)])
    n_normal_rows = len(merged[~merged.user_id.isin(ATTACK_USERS)])
    print(f"\nVerification:")
    print(f"  Normal user rows: {n_normal_rows} (unchanged)")
    print(f"  Attack user rows: {n_attack_rows} (re-embedded)")
    print(f"  Total: {len(merged)}")

    stats = embedder.stats()
    print(f"\nEmbedding stats: {stats['api_calls']} API calls, {stats['cache_hits']} cache hits")


if __name__ == "__main__":
    main()
