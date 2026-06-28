"""Regenerate only USR-234 (ATK-003) attack events in existing daily CSVs.

Replaces ATK-003 events with new attack config (more frequent staging,
more files, higher DGA probability). Does NOT re-run the full simulator.
Normal events for all users remain unchanged.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from simulator.config import ATTACK_SCENARIOS, SIM_START, SIM_END
from simulator.attacks.apt_slow import APTSlowAttack
from simulator.entities import generate_all

DATA_DIR = Path("data/generated")
ATTACK_ID = "ATK-003"

def main():
    # Get ATK-003 config
    atk_cfg = next(s for s in ATTACK_SCENARIOS if s["id"] == ATTACK_ID)

    # Build user->device map from entities
    entities = generate_all()
    user_device_map = dict(
        zip(entities["users"]["user_id"], entities["users"]["primary_device_id"])
    )
    enriched_cfg = dict(atk_cfg)
    enriched_cfg["_user_device_map"] = user_device_map

    attack = APTSlowAttack(enriched_cfg)
    print(f"APT config: staging_interval={attack.staging_interval_days}d, "
          f"files={attack.staging_file_min}-{attack.staging_file_max-1}, "
          f"dga_prob={attack.dga_probability}")
    print(f"Attack window: {attack._start_date} to {attack._end_date}")
    print(f"Target: {attack.target_user} / {attack.target_device}")

    rng = np.random.default_rng(9999)

    total_days = (SIM_END - SIM_START).days
    days_modified = 0
    events_removed = 0
    events_added = 0

    for day_offset in tqdm(range(total_days), desc="Patching CSVs"):
        current_date = SIM_START + timedelta(days=day_offset)

        if not attack.is_active(current_date):
            continue

        days_modified += 1

        # Generate new attack events for this day
        injected = attack.inject_events(current_date, rng)
        auth_mods = []

        # Check if auth events need modification
        auth_path = DATA_DIR / "auth" / f"{current_date}.csv"
        if auth_path.exists():
            auth_df = pd.read_csv(auth_path)
            old_atk = auth_df[auth_df.get("attack_id", pd.Series()) == ATTACK_ID] if "attack_id" in auth_df.columns else pd.DataFrame()
            events_removed += len(old_atk)
            if "attack_id" in auth_df.columns:
                auth_df = auth_df[auth_df["attack_id"] != ATTACK_ID]
            # Generate modified auth events
            dummy_auth = auth_df[auth_df["user_id"] == attack.target_user].to_dict("records")
            modified = attack.modify_auth_events(attack.target_user, dummy_auth, current_date, rng)
            new_atk_auth = [e for e in modified if e.get("attack_id") == ATTACK_ID]
            if new_atk_auth:
                new_auth_df = pd.DataFrame(new_atk_auth)
                auth_df = pd.concat([auth_df, new_auth_df], ignore_index=True)
                events_added += len(new_atk_auth)
            auth_df.to_csv(auth_path, index=False)

        # Patch network CSV
        KEY_MAP = {"file": "file_access"}
        for log_type, events in (injected or {}).items():
            mapped = KEY_MAP.get(log_type, log_type)
            csv_path = DATA_DIR / mapped / f"{current_date}.csv"
            if not csv_path.exists():
                continue

            df = pd.read_csv(csv_path)
            # Remove old ATK-003 events
            if "attack_id" in df.columns:
                old_count = len(df[df["attack_id"] == ATTACK_ID])
                events_removed += old_count
                df = df[df["attack_id"] != ATTACK_ID]

            # Add new events
            if events:
                new_df = pd.DataFrame(events)
                df = pd.concat([df, new_df], ignore_index=True)
                events_added += len(events)

            df.to_csv(csv_path, index=False)

    print(f"\nDone: {days_modified} days patched")
    print(f"  Events removed: {events_removed}")
    print(f"  Events added: {events_added}")
    print(f"  Net change: {events_added - events_removed:+d}")


if __name__ == "__main__":
    main()
