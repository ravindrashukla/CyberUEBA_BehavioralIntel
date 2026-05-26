"""In-memory data store for demo API.

Loads pipeline results (alerts, kill-chains, drift series, tier3 comparison)
when available, fills remaining data with synthetic generation.
Replace with PostgreSQL for production.
"""
import csv
import json
import uuid
import numpy as np
from datetime import datetime, date, timedelta
from functools import lru_cache
from pathlib import Path

from detection.reference_concepts import ALL_CONCEPTS, THREAT_CONCEPTS, BENIGN_CONCEPTS
from embeddings.composer import cosine_similarity, drift_magnitude

_RNG = np.random.default_rng(42)
_RESULTS_DIR = Path(__file__).parent.parent / "data" / "pipeline_results"
_TIER3_DIR = Path(__file__).parent.parent / "data" / "tier3_results"

# Signal names per entity type (matches schema column naming)
SIGNAL_NAMES = {
    "user": ["authentication", "privilege", "data_access", "network", "communication"],
    "device": ["process", "network_traffic", "resource", "authentication", "configuration"],
    "segment": ["traffic_volume", "connections", "protocols", "threat_indicators", "service_exposure"],
    "app": ["access_patterns", "query_behavior", "error_rates", "performance", "configuration"],
    "session": ["activity", "risk_accum", "data_movement", "lateral", "temporal"],
}

# Entity counts for demo
ENTITY_COUNTS = {"user": 50, "device": 80, "segment": 10, "app": 20, "session": 30}

# Number of monthly snapshots per entity
N_SNAPSHOTS = 12


def _random_embedding(dim: int = 1536) -> np.ndarray:
    """Generate a random unit-normalized embedding."""
    v = _RNG.standard_normal(dim).astype(np.float32)
    v /= np.linalg.norm(v)
    return v


def _drift_embedding(base: np.ndarray, magnitude: float) -> np.ndarray:
    """Create a new embedding drifted from base by approximately `magnitude` cosine distance."""
    noise = _RNG.standard_normal(base.shape).astype(np.float32)
    noise /= np.linalg.norm(noise)
    # Mix base with noise to achieve target drift
    alpha = min(magnitude, 0.95)
    new = (1 - alpha) * base + alpha * noise
    new /= np.linalg.norm(new)
    return new


class DemoStore:
    """In-memory store populated with synthetic demo data."""

    def __init__(self):
        self._entities: list[dict] = []
        self._entity_index: dict[tuple[str, str], dict] = {}
        self._embeddings: dict[tuple[str, str], dict] = {}
        self._trajectories: dict[tuple[str, str], list[dict]] = {}
        self._alerts: list[dict] = []
        self._alert_index: dict[str, dict] = {}
        self._kill_chains: list[dict] = []
        self._chain_index: dict[str, dict] = {}
        self._tier3_results: list[dict] = []
        self._tier3_index: dict[str, dict] = {}

        self._generate_entities()
        self._generate_embeddings()
        self._generate_trajectories()
        self._generate_alerts()
        self._generate_kill_chains()
        self._load_tier3_results()

    # --- Generation ---

    def _generate_entities(self):
        names = {
            "user": lambda i: f"user_{i:03d}",
            "device": lambda i: f"device_{i:03d}",
            "segment": lambda i: f"segment_{i:02d}",
            "app": lambda i: f"app_{i:02d}",
            "session": lambda i: f"session_{i:03d}",
        }
        metadata_templates = {
            "user": lambda i: {
                "department": _RNG.choice(["Engineering", "Finance", "HR", "Security", "Operations"]),
                "role": _RNG.choice(["analyst", "engineer", "manager", "admin"]),
                "clearance": _RNG.choice(["public", "internal", "confidential", "restricted"]),
            },
            "device": lambda i: {
                "device_type": _RNG.choice(["endpoint", "server", "network_appliance", "iot"]),
                "os_type": _RNG.choice(["Windows 11", "Ubuntu 22.04", "RHEL 9", "macOS 14"]),
            },
            "segment": lambda i: {
                "zone_type": _RNG.choice(["dmz", "internal", "restricted", "management", "guest"]),
                "trust_level": int(_RNG.integers(1, 6)),
            },
            "app": lambda i: {
                "app_type": _RNG.choice(["service", "database", "cloud_resource", "web_app", "api"]),
                "criticality": _RNG.choice(["high", "medium", "low"]),
            },
            "session": lambda i: {
                "auth_method": _RNG.choice(["password", "mfa", "certificate", "sso"]),
                "is_active": bool(_RNG.choice([True, False], p=[0.3, 0.7])),
            },
        }

        for etype, count in ENTITY_COUNTS.items():
            for i in range(count):
                eid = str(uuid.uuid4())
                entity = {
                    "entity_type": etype,
                    "entity_id": eid,
                    "name": names[etype](i),
                    "metadata": metadata_templates[etype](i),
                    "has_embeddings": True,
                    "computed_at": datetime.utcnow().isoformat(),
                }
                self._entities.append(entity)
                self._entity_index[(etype, eid)] = entity

    def _generate_embeddings(self):
        for key, entity in self._entity_index.items():
            etype = entity["entity_type"]
            signals = SIGNAL_NAMES[etype]
            emb_data = {
                "entity_type": etype,
                "entity_id": entity["entity_id"],
                "signals": [],
                "composite_norm": 1.0,
                "computed_at": entity["computed_at"],
            }
            vectors = {}
            for sig in signals:
                v = _random_embedding()
                vectors[sig] = v
                emb_data["signals"].append({
                    "signal_name": sig,
                    "dimensions": 1536,
                    "norm": float(np.linalg.norm(v)),
                })
            # Composite: simple average of signals, normalized
            composite = np.mean(list(vectors.values()), axis=0)
            composite /= np.linalg.norm(composite)
            emb_data["composite"] = composite
            emb_data["composite_norm"] = float(np.linalg.norm(composite))
            self._embeddings[key] = emb_data

    def _generate_trajectories(self):
        base_date = date(2025, 6, 1)
        for key, emb_data in self._embeddings.items():
            composite = emb_data["composite"]
            snapshots = []
            current = composite.copy()

            for month_offset in range(N_SNAPSHOTS):
                cutoff = base_date + timedelta(days=30 * month_offset)
                # Drift by a random amount (0.01 to 0.08 for most, occasional spike)
                mag = float(_RNG.exponential(0.03))
                new = _drift_embedding(current, mag)
                actual_drift = drift_magnitude(current, new)

                snapshots.append({
                    "cutoff_date": cutoff.isoformat(),
                    "drift_magnitude": float(actual_drift) if month_offset > 0 else None,
                    "features": {"snapshot_index": month_offset},
                    "velocity": {"mean_drift": float(actual_drift) if month_offset > 0 else 0.0},
                })
                current = new

            self._trajectories[key] = snapshots

    def _generate_alerts(self):
        alerts_file = _RESULTS_DIR / "alerts.json"
        if alerts_file.exists():
            with open(alerts_file) as f:
                loaded = json.load(f)
            for a in loaded:
                if "timestamp" not in a:
                    a["timestamp"] = a.get("detected_at", datetime.utcnow().isoformat())
                if "kill_chain_id" not in a:
                    a["kill_chain_id"] = None
                if "related_entities" not in a:
                    a["related_entities"] = []
                self._alerts.append(a)
                self._alert_index[a["id"]] = a
            return

        severities = ["critical", "high", "medium", "low"]
        methods = ["drift_direction", "cusum", "threshold"]
        statuses = ["new", "investigating", "confirmed", "false_positive", "resolved"]

        all_keys = list(self._entity_index.keys())
        indices = _RNG.choice(len(all_keys), size=min(40, len(all_keys)), replace=False)

        for idx in indices:
            key = all_keys[idx]
            entity = self._entity_index[key]
            n_alerts = int(_RNG.integers(1, 4))
            for _ in range(n_alerts):
                severity = _RNG.choice(severities, p=[0.1, 0.25, 0.4, 0.25])
                method = _RNG.choice(methods)
                mag = float(_RNG.uniform(0.15, 0.6))

                concept = _RNG.choice(THREAT_CONCEPTS)
                alignments = [
                    {
                        "concept": concept.name,
                        "similarity": float(_RNG.uniform(0.3, 0.8)),
                        "category": concept.category,
                        "severity": concept.severity,
                        "mitre_techniques": concept.mitre_techniques,
                    }
                ]

                alert_id = str(uuid.uuid4())
                alert = {
                    "id": alert_id,
                    "timestamp": (
                        datetime(2026, 4, 1) + timedelta(days=int(_RNG.integers(0, 30)))
                    ).isoformat(),
                    "entity_type": entity["entity_type"],
                    "entity_id": entity["entity_id"],
                    "severity": severity,
                    "title": f"Behavioral drift: {entity['name']}",
                    "description": (
                        f"Detection method: {method}. Drift magnitude: {mag:.4f}. "
                        f"Top concept: {concept.name} ({concept.severity})."
                    ),
                    "detection_method": method,
                    "drift_magnitude": mag,
                    "concept_alignments": alignments,
                    "mitre_techniques": concept.mitre_techniques,
                    "confidence": float(_RNG.uniform(0.4, 0.95)),
                    "status": _RNG.choice(statuses, p=[0.4, 0.2, 0.15, 0.1, 0.15]),
                    "kill_chain_id": None,
                    "related_entities": [],
                }
                self._alerts.append(alert)
                self._alert_index[alert_id] = alert

    def _generate_kill_chains(self):
        chains_file = _RESULTS_DIR / "kill_chains.json"
        if chains_file.exists():
            with open(chains_file) as f:
                loaded = json.load(f)
            for c in loaded:
                self._kill_chains.append(c)
                self._chain_index[c["id"]] = c
            return

        critical_alerts = [a for a in self._alerts if a["severity"] in ("critical", "high")]
        if len(critical_alerts) < 3:
            return

        n_chains = min(5, len(critical_alerts) // 2)
        _RNG.shuffle(critical_alerts)

        tactic_sequence = [
            "Reconnaissance", "Initial Access", "Execution",
            "Persistence", "Privilege Escalation", "Lateral Movement",
            "Collection", "Exfiltration",
        ]

        for i in range(n_chains):
            chain_id = str(uuid.uuid4())
            n_events = int(_RNG.integers(2, 6))
            chain_alerts = critical_alerts[i * 2 : i * 2 + n_events]

            events = []
            for j, alert in enumerate(chain_alerts):
                tactic = tactic_sequence[min(j, len(tactic_sequence) - 1)]
                events.append({
                    "alert_id": alert["id"],
                    "entity_type": alert["entity_type"],
                    "entity_id": alert["entity_id"],
                    "timestamp": alert["timestamp"],
                    "tactic": tactic,
                    "techniques": alert["mitre_techniques"],
                    "description": alert["description"],
                    "confidence": alert["confidence"],
                })
                alert["kill_chain_id"] = chain_id

            chain = {
                "id": chain_id,
                "created_at": events[0]["timestamp"] if events else datetime.utcnow().isoformat(),
                "status": _RNG.choice(["active", "resolved"], p=[0.7, 0.3]),
                "severity": "critical" if n_events >= 4 else "high",
                "duration_seconds": float(_RNG.uniform(3600, 86400 * 7)),
                "tactics_observed": list(dict.fromkeys(e["tactic"] for e in events)),
                "entities_involved": list(set(
                    f"{e['entity_type']}:{e['entity_id']}" for e in events
                )),
                "events": events,
                "event_count": len(events),
            }
            self._kill_chains.append(chain)
            self._chain_index[chain_id] = chain

    # --- Query methods ---

    def list_entities(self, entity_type: str = None) -> list[dict]:
        if entity_type:
            return [e for e in self._entities if e["entity_type"] == entity_type]
        return self._entities

    def get_entity(self, entity_type: str, entity_id: str) -> dict | None:
        return self._entity_index.get((entity_type, entity_id))

    def entity_stats(self) -> list[dict]:
        from collections import Counter
        counts = Counter(e["entity_type"] for e in self._entities)
        emb_counts = Counter(k[0] for k in self._embeddings)
        return [
            {"entity_type": et, "count": c, "with_embeddings": emb_counts.get(et, 0)}
            for et, c in sorted(counts.items())
        ]

    def get_entity_embeddings(self, entity_type: str, entity_id: str) -> dict | None:
        emb = self._embeddings.get((entity_type, entity_id))
        if emb is None:
            return None
        # Return without the raw numpy composite
        return {
            "entity_type": emb["entity_type"],
            "entity_id": emb["entity_id"],
            "signals": emb["signals"],
            "composite_norm": emb["composite_norm"],
            "computed_at": emb["computed_at"],
        }

    def find_similar(self, entity_type: str, entity_id: str, top_k: int = 10) -> list[dict]:
        source_emb = self._embeddings.get((entity_type, entity_id))
        if source_emb is None:
            return []

        source_composite = source_emb["composite"]
        similarities = []

        for key, emb in self._embeddings.items():
            if key == (entity_type, entity_id):
                continue
            if emb["entity_type"] != entity_type:
                continue
            sim = cosine_similarity(source_composite, emb["composite"])
            entity = self._entity_index[key]
            similarities.append({
                "entity_type": entity_type,
                "entity_id": key[1],
                "name": entity["name"],
                "similarity": float(sim),
            })

        similarities.sort(key=lambda x: x["similarity"], reverse=True)
        return similarities[:top_k]

    def get_trajectory(
        self, entity_type: str, entity_id: str,
        start_date: str = None, end_date: str = None,
    ) -> list[dict]:
        key = (entity_type, entity_id)
        snapshots = self._trajectories.get(key, [])

        if start_date:
            snapshots = [s for s in snapshots if s["cutoff_date"] >= start_date]
        if end_date:
            snapshots = [s for s in snapshots if s["cutoff_date"] <= end_date]

        return snapshots

    def get_drift_analysis(
        self, entity_type: str, entity_id: str,
        from_date: str = None, to_date: str = None,
    ) -> dict | None:
        key = (entity_type, entity_id)
        snapshots = self._trajectories.get(key, [])
        if len(snapshots) < 2:
            return None

        # Use first and last snapshots as from/to (or filter by date)
        if from_date and to_date:
            from_snaps = [s for s in snapshots if s["cutoff_date"] <= from_date]
            to_snaps = [s for s in snapshots if s["cutoff_date"] >= to_date]
            if not from_snaps or not to_snaps:
                from_snap = snapshots[0]
                to_snap = snapshots[-1]
            else:
                from_snap = from_snaps[-1]
                to_snap = to_snaps[0]
        else:
            from_snap = snapshots[0]
            to_snap = snapshots[-1]

        # Synthesize drift analysis
        mag = float(_RNG.uniform(0.05, 0.4))
        concept = _RNG.choice(THREAT_CONCEPTS)

        return {
            "from_date": from_snap["cutoff_date"],
            "to_date": to_snap["cutoff_date"],
            "drift_magnitude": mag,
            "primary_direction": concept.name,
            "is_threat": mag > 0.15,
            "confidence": float(_RNG.uniform(0.3, 0.85)),
            "top_alignments": [
                {
                    "concept_name": concept.name,
                    "category": concept.category,
                    "alignment_score": float(_RNG.uniform(0.3, 0.7)),
                    "severity": concept.severity,
                    "mitre_techniques": concept.mitre_techniques,
                }
            ],
        }

    def get_drift_series(self, entity_type: str, entity_id: str) -> list[dict]:
        key = (entity_type, entity_id)
        snapshots = self._trajectories.get(key, [])
        return [
            {"cutoff_date": s["cutoff_date"], "drift_magnitude": s["drift_magnitude"] or 0.0}
            for s in snapshots
        ]

    def scan_entities(self, entity_type: str = None, threshold: float = 0.15) -> dict:
        entities = self.list_entities(entity_type)
        results = []

        for entity in entities:
            key = (entity["entity_type"], entity["entity_id"])
            snapshots = self._trajectories.get(key, [])
            drifts = [s["drift_magnitude"] for s in snapshots if s["drift_magnitude"] is not None]

            if not drifts:
                continue

            # Simple CUSUM approximation
            cusum = 0.0
            change_idx = None
            for i, d in enumerate(drifts):
                cusum = max(0.0, cusum + d - 0.02)
                if cusum >= threshold and change_idx is None:
                    change_idx = i

            max_drift = max(drifts)
            if max_drift >= threshold or change_idx is not None:
                results.append({
                    "entity_type": entity["entity_type"],
                    "entity_id": entity["entity_id"],
                    "drift_magnitude": max_drift,
                    "cusum_value": cusum,
                    "change_detected": change_idx is not None,
                    "change_point_idx": change_idx,
                })

        results.sort(key=lambda r: r["drift_magnitude"], reverse=True)

        return {
            "entities_scanned": len(entities),
            "entities_flagged": len(results),
            "results": results,
        }

    def list_alerts(
        self, severity: str = None, entity_type: str = None,
        status: str = None, limit: int = 50,
    ) -> list[dict]:
        alerts = self._alerts

        if severity:
            alerts = [a for a in alerts if a["severity"] == severity]
        if entity_type:
            alerts = [a for a in alerts if a["entity_type"] == entity_type]
        if status:
            alerts = [a for a in alerts if a["status"] == status]

        # Sort by timestamp descending (most recent first)
        alerts = sorted(alerts, key=lambda a: a["timestamp"], reverse=True)

        return [
            {
                "id": a["id"],
                "timestamp": a["timestamp"],
                "entity_type": a["entity_type"],
                "entity_id": a["entity_id"],
                "severity": a["severity"],
                "title": a["title"],
                "detection_method": a["detection_method"],
                "drift_magnitude": a["drift_magnitude"],
                "status": a["status"],
            }
            for a in alerts[:limit]
        ]

    def get_alert(self, alert_id: str) -> dict | None:
        return self._alert_index.get(alert_id)

    def update_alert_status(self, alert_id: str, status: str) -> bool:
        alert = self._alert_index.get(alert_id)
        if alert is None:
            return False
        alert["status"] = status
        return True

    def list_kill_chains(self, status: str = None) -> list[dict]:
        chains = self._kill_chains
        if status:
            chains = [c for c in chains if c["status"] == status]

        return [
            {
                "id": c["id"],
                "created_at": c["created_at"],
                "status": c["status"],
                "severity": c["severity"],
                "duration_seconds": c["duration_seconds"],
                "tactics_observed": c["tactics_observed"],
                "entities_involved": c["entities_involved"],
                "event_count": c["event_count"],
            }
            for c in chains
        ]

    def get_kill_chain(self, chain_id: str) -> dict | None:
        return self._chain_index.get(chain_id)

    def dashboard_summary(self) -> dict:
        from collections import Counter

        entity_counts = Counter(e["entity_type"] for e in self._entities)
        severity_counts = Counter(
            a["severity"] for a in self._alerts if a["status"] not in ("resolved", "false_positive")
        )
        active_chains = sum(1 for c in self._kill_chains if c["status"] == "active")

        # Recent drift events: alerts in last 7 days (simulated)
        recent = sum(1 for a in self._alerts if a["status"] == "new")

        # Top threats: most common concepts in active alerts
        concept_counts = Counter()
        for a in self._alerts:
            if a["status"] in ("resolved", "false_positive"):
                continue
            for ca in a.get("concept_alignments", []):
                concept_counts[ca["concept"]] += 1

        top_threats = [
            {"concept": name, "count": count}
            for name, count in concept_counts.most_common(5)
        ]

        return {
            "entity_counts": dict(entity_counts),
            "alerts_by_severity": dict(severity_counts),
            "active_kill_chains": active_chains,
            "recent_drift_events": recent,
            "top_threats": top_threats,
        }

    # --- Tier 3 ---

    def _load_tier3_results(self):
        csv_file = _TIER3_DIR / "tier3_comparison.csv"
        if not csv_file.exists():
            return

        with open(csv_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                uid = row.get("user_id", "")
                if not uid:
                    continue

                def _float(key, default=0.0):
                    try:
                        return float(row.get(key, default))
                    except (ValueError, TypeError):
                        return default

                def _bool(key):
                    return row.get(key, "").strip().lower() == "true"

                def _str(key, default=""):
                    return row.get(key, default).strip()

                entry = {
                    "user_id": uid,
                    "is_attack": _bool("is_attack"),
                    "attack_name": _str("attack_name", "Normal"),
                    # Tier 1
                    "t1_iforest": _bool("iforest_anomaly"),
                    "t1_ocsvm": _bool("ocsvm_anomaly"),
                    "t1_lof": _bool("lof_anomaly"),
                    "t1_zscore": _bool("zscore_anomaly"),
                    "t1_temporal": _bool("temporal_anomaly"),
                    "t1_feat_cusum": _bool("feat_cusum_detected"),
                    "t1_feat_cusum_top10": _bool("feat_cusum_top10pct"),
                    "t1_top_feature": _str("feat_top_feature"),
                    "t1_top_feature_z": _float("feat_top_feature_z"),
                    # Tier 2
                    "t2_cusum_detected": _bool("acecard_cusum_detected"),
                    "t2_direction_detected": _bool("acecard_direction_detected"),
                    "t2_top10pct": _bool("acecard_top10pct"),
                    "t2_total_drift": _float("acecard_total_drift"),
                    "t2_threat_consistency": _float("acecard_threat_consistency"),
                    "t2_primary_threat": _str("acecard_primary_threat"),
                    "t2_max_weekly_threat": _float("acecard_max_weekly_threat"),
                    "combined_detected": _bool("combined_detected"),
                    # Tier 3 - Phase State
                    "t3_velocity_magnitude": _float("t3_velocity_magnitude"),
                    "t3_acceleration": _float("t3_acceleration"),
                    "t3_stability": _float("t3_stability"),
                    "t3_trend_consistency": _float("t3_trend_consistency"),
                    "t3_total_drift": _float("t3_total_drift"),
                    "t3_regime": _str("t3_regime"),
                    # Tier 3 - Detection Methods
                    "t3_velocity_score": _float("t3_velocity_score"),
                    "t3_velocity_detected": _bool("t3_velocity_detected"),
                    "t3_regime_shifts": _float("t3_regime_shifts"),
                    "t3_regime_score": _float("t3_regime_score"),
                    "t3_regime_detected": _bool("t3_regime_detected"),
                    # Tier 3 - Zone Drifts
                    "t3_identity_drift": _float("t3_identity_drift"),
                    "t3_data_drift": _float("t3_data_drift"),
                    "t3_network_drift": _float("t3_network_drift"),
                    "t3_risk_drift": _float("t3_risk_drift"),
                    "t3_access_drift": _float("t3_access_drift"),
                    "t3_zone_divergence_score": _float("t3_zone_divergence_score"),
                    "t3_zone_diagnostics": _str("t3_zone_diagnostics"),
                    "t3_zone_divergence_detected": _bool("t3_zone_divergence_detected"),
                    # Tier 3 - Relationship & Contextual
                    "t3_rel_drift": _float("t3_rel_drift"),
                    "t3_rel_detected": _bool("t3_rel_detected"),
                    "t3_ctx_best_context": _str("t3_ctx_best_context"),
                    "t3_ctx_best_consistency": _float("t3_ctx_best_consistency"),
                    "t3_ctx_detected": _bool("t3_ctx_detected"),
                    "t3_cohort_member": _bool("t3_cohort_member"),
                    # Tier 3 - Combined
                    "t3_composite_score": _float("t3_composite_score"),
                    "t3_combined_detected": _bool("t3_combined_detected"),
                    "all_tiers_combined": _bool("all_tiers_combined"),
                }
                self._tier3_results.append(entry)
                self._tier3_index[uid] = entry

    def get_tier3_comparison(self) -> list[dict]:
        return self._tier3_results

    def get_tier3_entity(self, user_id: str) -> dict | None:
        return self._tier3_index.get(user_id)

    def get_tier3_summary(self) -> dict:
        if not self._tier3_results:
            return {"loaded": False, "total_entities": 0}

        total = len(self._tier3_results)
        attacks = [r for r in self._tier3_results if r["is_attack"]]
        normals = [r for r in self._tier3_results if not r["is_attack"]]

        def _count(lst, key):
            return sum(1 for r in lst if r.get(key))

        def _fp_rate(key):
            flagged_normals = _count(normals, key)
            return flagged_normals / len(normals) if normals else 0.0

        attack_ids = [a["user_id"] for a in attacks]

        t1_methods = {
            "IForest": "t1_iforest",
            "OCSVM": "t1_ocsvm",
            "LOF": "t1_lof",
            "Z-Score": "t1_zscore",
            "Temporal Z": "t1_temporal",
            "Feature CUSUM": "t1_feat_cusum",
        }
        t3_methods = {
            "Velocity/Accel": "t3_velocity_detected",
            "Regime Shift": "t3_regime_detected",
            "Zone Divergence": "t3_zone_divergence_detected",
            "Relationship": "t3_rel_detected",
            "Contextual": "t3_ctx_detected",
        }

        tiers = []
        for name, key in t1_methods.items():
            detects = [a["user_id"] for a in attacks if a.get(key)]
            tiers.append({
                "tier": 1, "method": name,
                "detects_attacks": detects,
                "fp_rate": round(_fp_rate(key) * 100, 1),
                "total_flagged": _count(self._tier3_results, key),
            })
        # Tier 2
        for name, key in [("ACECARD Direction", "t2_direction_detected"), ("ACECARD Top-10%", "t2_top10pct")]:
            detects = [a["user_id"] for a in attacks if a.get(key)]
            tiers.append({
                "tier": 2, "method": name,
                "detects_attacks": detects,
                "fp_rate": round(_fp_rate(key) * 100, 1),
                "total_flagged": _count(self._tier3_results, key),
            })
        tiers.append({
            "tier": "1+2", "method": "Combined (T1 OR T2)",
            "detects_attacks": [a["user_id"] for a in attacks if a.get("combined_detected")],
            "fp_rate": round(_fp_rate("combined_detected") * 100, 1),
            "total_flagged": _count(self._tier3_results, "combined_detected"),
        })
        # Tier 3
        for name, key in t3_methods.items():
            detects = [a["user_id"] for a in attacks if a.get(key)]
            tiers.append({
                "tier": 3, "method": name,
                "detects_attacks": detects,
                "fp_rate": round(_fp_rate(key) * 100, 1),
                "total_flagged": _count(self._tier3_results, key),
            })
        tiers.append({
            "tier": 3, "method": "T3 Combined",
            "detects_attacks": [a["user_id"] for a in attacks if a.get("t3_combined_detected")],
            "fp_rate": round(_fp_rate("t3_combined_detected") * 100, 1),
            "total_flagged": _count(self._tier3_results, "t3_combined_detected"),
        })
        tiers.append({
            "tier": "All", "method": "All Tiers Combined",
            "detects_attacks": [a["user_id"] for a in attacks if a.get("all_tiers_combined")],
            "fp_rate": round(_fp_rate("all_tiers_combined") * 100, 1),
            "total_flagged": _count(self._tier3_results, "all_tiers_combined"),
        })

        return {
            "loaded": True,
            "total_entities": total,
            "attack_entities": [{"user_id": a["user_id"], "attack_name": a["attack_name"]} for a in attacks],
            "methods": tiers,
        }


# Singleton store instance
_store_instance: DemoStore | None = None


def get_store() -> DemoStore:
    """Get or create the singleton demo store."""
    global _store_instance
    if _store_instance is None:
        _store_instance = DemoStore()
    return _store_instance
