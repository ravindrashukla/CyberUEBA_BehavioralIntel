"""Simulation orchestration engine for synthetic UEBA log generation."""

import os
import warnings
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

from simulator.config import SIM_START, SIM_END, ATTACK_SCENARIOS
from simulator.entities import generate_all, generate_role_profiles

# Log generator registry: module_name -> (function_name, required_args_keys)
# Each generator is called with a subset of: users_df, devices_df, segments_df,
# applications_df, role_profiles, current_date, rng
_GENERATOR_REGISTRY = {
    "auth": ("simulator.log_generators.auth_logs", "generate_auth_logs",
             ["users_df", "devices_df", "role_profiles", "current_date", "rng"]),
    "network": ("simulator.log_generators.network_flows", "generate_network_flows",
                ["devices_df", "segments_df", "current_date", "rng"]),
    "dns": ("simulator.log_generators.dns_logs", "generate_dns_queries",
            ["devices_df", "segments_df", "current_date", "rng"]),
    "endpoint": ("simulator.log_generators.endpoint_telemetry", "generate_endpoint_events",
                 ["devices_df", "users_df", "current_date", "rng"]),
    "app": ("simulator.log_generators.app_logs", "generate_app_events",
            ["users_df", "applications_df", "current_date", "rng"]),
    "privilege": ("simulator.log_generators.privilege_ops", "generate_privilege_ops",
                  ["users_df", "current_date", "rng"]),
    "file_access": ("simulator.log_generators.file_access", "generate_file_access",
                    ["users_df", "current_date", "rng"]),
}

# Attack type -> (module_path, class_name)
_ATTACK_REGISTRY = {
    "brute_force": ("simulator.attacks.brute_force", "BruteForceAttack"),
    "apt_slow": ("simulator.attacks.apt_slow", "APTSlowAttack"),
    "insider_threat": ("simulator.attacks.insider_threat", "InsiderThreatAttack"),
    "credential_theft_lateral": ("simulator.attacks.credential_theft", "CredentialTheftLateral"),
    "ransomware": ("simulator.attacks.ransomware", "Ransomware"),
    "supply_chain": ("simulator.attacks.supply_chain", "SupplyChainCompromise"),
}


def _try_import(module_path, attr_name):
    """Import a module attribute, returning None on failure."""
    try:
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, attr_name)
    except (ImportError, AttributeError) as e:
        return None


class SimulationEngine:
    """Orchestrates day-by-day synthetic log generation."""

    def __init__(self, output_dir: str = "data/generated"):
        self.output_dir = Path(output_dir)
        self.rng = np.random.default_rng(42)

        # Generate entities
        print("Generating entities...")
        self.entities = generate_all()
        self.role_profiles = generate_role_profiles()

        # Load available log generators
        self._generators = self._load_generators()

        # Load attack scenarios
        self._attacks = self._load_attacks()

        # Stats tracking
        self._stats = {key: 0 for key in self._generators}
        self._attack_events = 0

    def _load_generators(self) -> dict:
        """Load all available log generators, skip missing ones with warning."""
        generators = {}
        for log_type, (module_path, func_name, _arg_keys) in _GENERATOR_REGISTRY.items():
            func = _try_import(module_path, func_name)
            if func is not None:
                generators[log_type] = func
            else:
                warnings.warn(f"Log generator not found: {module_path}.{func_name} — skipping '{log_type}'")
        return generators

    def _load_attacks(self) -> list:
        """Instantiate attack scenarios from config, skip missing implementations."""
        attacks = []
        for scenario_cfg in ATTACK_SCENARIOS:
            attack_type = scenario_cfg["type"]
            entry = _ATTACK_REGISTRY.get(attack_type)
            if entry is None:
                warnings.warn(f"No registry entry for attack type '{attack_type}' — skipping")
                continue
            module_path, class_name = entry
            cls = _try_import(module_path, class_name)
            if cls is not None:
                attacks.append(cls(scenario_cfg))
            else:
                warnings.warn(f"Attack class not found: {module_path}.{class_name} — skipping '{scenario_cfg['id']}'")
        return attacks

    def run(self, start_date: date = None, end_date: date = None):
        """Run the simulation day-by-day from start_date to end_date."""
        start = start_date or SIM_START
        end = end_date or SIM_END
        total_days = (end - start).days

        if total_days <= 0:
            raise ValueError(f"end_date ({end}) must be after start_date ({start})")

        # Ensure output directories exist
        self._setup_output_dirs()

        # Write entity CSVs
        self._write_entities()

        print(f"Simulating {total_days} days ({start} to {end})...")
        print(f"Active generators: {list(self._generators.keys())}")
        print(f"Loaded attacks: {[a.id for a in self._attacks]}")
        print()

        for day_offset in tqdm(range(total_days), desc="Generating logs", unit="day"):
            current_date = start + timedelta(days=day_offset)
            daily_logs = self._generate_day(current_date)
            self._write_daily_output(current_date, daily_logs)

        # Print summary
        self._print_summary()

    def _generate_day(self, current_date: date) -> dict[str, list[dict]]:
        """Generate all log events for a single day."""
        daily_logs = {log_type: [] for log_type in self._generators}

        # Generate normal logs for the full day (generators produce a full day at once)
        day_logs = self._generate_day_logs(current_date)
        for log_type, events in day_logs.items():
            daily_logs[log_type].extend(events)

        # Apply attack injections
        self._apply_attacks(daily_logs, current_date)

        # Update stats
        for log_type, events in daily_logs.items():
            self._stats[log_type] += len(events)

        return daily_logs

    def _generate_day_logs(self, current_date: date) -> dict[str, list[dict]]:
        """Call each log generator for this day."""
        logs = {}
        arg_pool = {
            "users_df": self.entities["users"],
            "devices_df": self.entities["devices"],
            "segments_df": self.entities["segments"],
            "applications_df": self.entities["applications"],
            "role_profiles": self.role_profiles,
            "current_date": current_date,
            "rng": self.rng,
        }

        for log_type, gen_func in self._generators.items():
            _, _, arg_keys = _GENERATOR_REGISTRY[log_type]
            kwargs = {k: arg_pool[k] for k in arg_keys}
            try:
                events = gen_func(**kwargs)
                logs[log_type] = events if events else []
            except Exception as e:
                warnings.warn(f"Generator '{log_type}' failed on {current_date}: {e}")
                logs[log_type] = []

        return logs

    def _apply_attacks(self, daily_logs: dict, current_date: date):
        """Let each active attack inject events into the daily logs."""
        # Normalize attack log-type keys to match generator registry
        _KEY_MAP = {"file": "file_access"}

        for attack in self._attacks:
            if not attack.is_active(current_date):
                continue
            try:
                injected = attack.inject_events(current_date, self.rng)
                if injected:
                    for log_type, events in injected.items():
                        mapped = _KEY_MAP.get(log_type, log_type)
                        if mapped in daily_logs:
                            daily_logs[mapped].extend(events)
                        else:
                            daily_logs[mapped] = events
                        self._attack_events += len(events)
            except Exception as e:
                warnings.warn(f"Attack '{attack.id}' failed on {current_date}: {e}")

    def _setup_output_dirs(self):
        """Create output directory structure."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "entities").mkdir(exist_ok=True)
        for log_type in list(self._generators.keys()) + ["file_access"]:
            (self.output_dir / log_type).mkdir(exist_ok=True)

    def _write_entities(self):
        """Write entity DataFrames as CSVs."""
        entities_dir = self.output_dir / "entities"
        for name, df in self.entities.items():
            # Convert list columns to string for CSV compatibility
            df_out = df.copy()
            for col in df_out.columns:
                if df_out[col].apply(lambda x: isinstance(x, list)).any():
                    df_out[col] = df_out[col].apply(
                        lambda x: "|".join(x) if isinstance(x, list) else x
                    )
            df_out.to_csv(entities_dir / f"{name}.csv", index=False)
        print(f"Entities written to {entities_dir}/")

    def _write_daily_output(self, current_date: date, daily_logs: dict):
        """Write each log type's events to a daily CSV."""
        date_str = current_date.isoformat()
        for log_type, events in daily_logs.items():
            if not events:
                continue
            out_dir = self.output_dir / log_type
            out_dir.mkdir(exist_ok=True)
            df = pd.DataFrame(events)
            df.to_csv(out_dir / f"{date_str}.csv", index=False)

    def _print_summary(self):
        """Print generation summary statistics."""
        print("\n" + "=" * 60)
        print("SIMULATION COMPLETE")
        print("=" * 60)
        total = 0
        for log_type, count in sorted(self._stats.items()):
            print(f"  {log_type:20s}: {count:>12,} events")
            total += count
        print(f"  {'TOTAL':20s}: {total:>12,} events")
        print(f"  {'attack-injected':20s}: {self._attack_events:>12,} events")
        print(f"\nOutput directory: {self.output_dir.resolve()}")
        print("=" * 60)
