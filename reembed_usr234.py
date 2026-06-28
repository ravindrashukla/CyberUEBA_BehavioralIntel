"""Re-embed only USR-234 after patching attack events."""
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

TARGET = ["USR-234"]


def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set.")
        sys.exit(1)

    from embeddings.embedder import Embedder
    from detection.reference_concepts import ConceptLibrary

    embedder = Embedder(api_key=api_key)
    print("Using REAL OpenAI embeddings (text-embedding-3-small)")

    existing_traj_path = RESULTS_DIR / "weekly_zone_trajectories.csv"
    existing_traj = pd.read_csv(existing_traj_path)
    print(f"Existing trajectories: {len(existing_traj)} rows")

    auth_dir = DATA_DIR / "auth"
    csv_files = sorted(auth_dir.glob("*.csv"))
    first_date = date.fromisoformat(csv_files[0].stem)
    last_date = date.fromisoformat(csv_files[-1].stem)
    print(f"Data range: {first_date} to {last_date}")

    user_device_map = _build_user_device_map()

    from simulator.entities import generate_all
    entities = generate_all()

    all_user_ids = entities["users"]["user_id"].tolist()
    print(f"\nPhase 1: Feature engineering for all {len(all_user_ids)} users...")
    features_df = engineer_weekly_features(first_date, last_date, all_user_ids, user_device_map)
    print(f"  {len(features_df)} feature rows computed")

    print(f"\nPhase 2: Embedding USR-234 only")
    concept_lib = ConceptLibrary(embedder=embedder)
    concept_lib.embed_concepts()

    config = Tier3Config()
    target_features = features_df[features_df["user_id"].isin(TARGET)]
    print(f"  {len(target_features)} feature rows for USR-234")

    entity_zoo = build_entity_zoo(
        TARGET, features_df, entities, user_device_map,
        embedder, concept_lib, config,
    )

    print(f"\nPhase 3: Extracting trajectories...")
    new_traj = extract_weekly_trajectories(entity_zoo, features_df)
    print(f"  {len(new_traj)} new trajectory rows")

    # Merge: keep everything except USR-234, replace with new
    other_traj = existing_traj[~existing_traj.user_id.isin(TARGET)]
    merged = pd.concat([other_traj, new_traj], ignore_index=True)
    merged = merged.sort_values(["user_id", "week_idx"]).reset_index(drop=True)

    backup_path = RESULTS_DIR / "weekly_zone_trajectories_pre234.csv"
    existing_traj.to_csv(backup_path, index=False)
    print(f"\nBacked up to {backup_path}")

    merged.to_csv(existing_traj_path, index=False)
    print(f"Saved: {len(merged)} rows to {existing_traj_path}")

    stats = embedder.stats()
    print(f"\nEmbedding stats: {stats['api_calls']} API calls, {stats['cache_hits']} cache hits")


if __name__ == "__main__":
    main()
