"""Detection runner: scan stored behavioral snapshots, produce alerts and kill-chains."""
import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from embeddings.embedder import Embedder, MockEmbedder
from detection.cusum import cusum_scan_entity
from detection.drift_direction import analyze_entity_drift
from detection.reference_concepts import ConceptLibrary
from detection.alert_generator import AlertGenerator, AlertSeverity
from detection.kill_chain import KillChainReconstructor
from services.database import Database


def load_entity_snapshots():
    """Load all entities with 2+ snapshots from DB, grouped by (entity_type, entity_id)."""
    rows = Database.execute(
        "SELECT entity_type, entity_id, cutoff_date, composite "
        "FROM behavioral_snapshots "
        "WHERE composite IS NOT NULL "
        "ORDER BY entity_type, entity_id, cutoff_date ASC"
    )
    if not rows:
        return {}

    entities = {}
    for row in rows:
        key = (row["entity_type"], row["entity_id"])
        if key not in entities:
            entities[key] = []
        # Parse vector from pgvector string
        vec_str = str(row["composite"]).strip("[]")
        vec = np.array([float(x) for x in vec_str.split(",")], dtype=np.float32)
        entities[key].append({
            "cutoff_date": row["cutoff_date"],
            "composite": vec,
        })

    # Filter to entities with 2+ snapshots
    return {k: v for k, v in entities.items() if len(v) >= 2}


def run_detection(
    cusum_threshold: float = 0.05,
    drift_threshold: float = 0.15,
    alignment_threshold: float = 0.3,
    min_severity: str = "low",
):
    """Run full detection pipeline against DB-stored snapshots."""
    print("=" * 60)
    print("DETECTION PIPELINE RUN")
    print(f"  CUSUM threshold: {cusum_threshold}")
    print(f"  Drift threshold: {drift_threshold}")
    print(f"  Alignment threshold: {alignment_threshold}")
    print(f"  Min severity for DB insert: {min_severity}")
    print("=" * 60)

    # Initialize concept library
    if os.environ.get("OPENAI_API_KEY"):
        embedder = Embedder()
        print("Using REAL OpenAI embeddings for concept vectors")
    else:
        embedder = MockEmbedder()
        print("Using MockEmbedder for concept vectors")
    concept_lib = ConceptLibrary(embedder=embedder)
    concept_lib.embed_concepts()
    print(f"\nConcept library: {len(concept_lib.all_threat_vectors())} threat + "
          f"{len(concept_lib.all_benign_vectors())} benign concepts embedded")

    # Load snapshots from DB
    print("\nLoading snapshots from database...")
    entities = load_entity_snapshots()
    print(f"  Entities with 2+ snapshots: {len(entities)}")

    type_counts = {}
    for (etype, _), _ in entities.items():
        type_counts[etype] = type_counts.get(etype, 0) + 1
    for etype, count in sorted(type_counts.items()):
        print(f"    {etype}: {count}")

    # Initialize detection components
    # Use alignment_threshold=0 so all concept alignments are stored (enrichment).
    # With MockEmbedder, random vectors have near-zero cosine similarity in 1536-d,
    # so a positive threshold would filter out all concept context.
    alert_gen = AlertGenerator(
        drift_threshold=drift_threshold,
        cusum_threshold=cusum_threshold,
        alignment_threshold=0.0,
    )
    reconstructor = KillChainReconstructor(correlation_window_hours=72)

    # Run detection on each entity
    cusum_detections = 0
    drift_detections = 0
    total_alerts = 0

    severity_filter = {
        "critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4
    }
    min_sev_rank = severity_filter.get(min_severity, 3)

    print("\nRunning detection...")
    for (entity_type, entity_id), snapshots in entities.items():
        composites = [s["composite"] for s in snapshots]

        # 1. CUSUM scan on full trajectory
        cusum_result = cusum_scan_entity(
            composites, threshold=cusum_threshold, drift_threshold=0.02
        )

        # 2. Drift direction on latest pair
        v_old = composites[-2]
        v_new = composites[-1]
        drift_analysis = analyze_entity_drift(
            entity_type=entity_type,
            entity_id=entity_id,
            v_old=v_old,
            v_new=v_new,
            concept_library=concept_lib,
            alignment_threshold=alignment_threshold,
        )

        # 3. Generate alerts
        alert = None

        # CUSUM alert (slow sustained drift)
        if cusum_result.change_detected:
            cusum_detections += 1
            alert = alert_gen.from_cusum_result(
                entity_type, entity_id, cusum_result, drift_analysis
            )

        # Drift direction alert (single-period significant drift)
        if drift_analysis.drift_magnitude >= drift_threshold:
            drift_detections += 1
            drift_alert = alert_gen.from_drift_analysis(
                drift_analysis,
                timestamp=datetime.utcnow(),
            )
            if drift_alert:
                alert = drift_alert  # prefer drift_direction alert (richer)

        if alert:
            total_alerts += 1
            reconstructor.ingest_alert(alert)

    # Deduplicate alerts
    deduped = alert_gen.deduplicate(window_hours=24)
    print(f"\n--- Results ---")
    print(f"  CUSUM detections: {cusum_detections}")
    print(f"  Drift direction detections: {drift_detections}")
    print(f"  Raw alerts: {total_alerts}")
    print(f"  After dedup: {len(deduped)}")

    # Kill chains
    chains = reconstructor.get_active_chains()
    print(f"  Kill chains reconstructed: {len(chains)}")

    # Severity breakdown
    sev_counts = {}
    for a in deduped:
        sev_counts[a.severity.value] = sev_counts.get(a.severity.value, 0) + 1
    print(f"\n  Severity breakdown:")
    for sev in ["critical", "high", "medium", "low", "info"]:
        if sev in sev_counts:
            print(f"    {sev}: {sev_counts[sev]}")

    # Persist to database
    print(f"\nPersisting to database...")
    alerts_saved = 0
    for alert in deduped:
        sev_rank = severity_filter.get(alert.severity.value, 4)
        if sev_rank > min_sev_rank:
            continue

        alert_dict = {
            "entity_type": alert.entity_type,
            "entity_id": alert.entity_id,
            "event_type": alert.detection_method,
            "severity": alert.severity.value,
            "drift_magnitude": alert.drift_magnitude,
            "concept_alignments": alert.concept_alignments,
            "mitre_techniques": alert.mitre_techniques,
            "description": alert.description,
            "status": "new",
            "kill_chain_id": alert.kill_chain_id,
        }
        try:
            Database.save_alert(alert_dict)
            alerts_saved += 1
        except Exception as e:
            print(f"  ERROR saving alert for {alert.entity_type}:{alert.entity_id}: {e}")

    chains_saved = 0
    for chain in chains:
        chain_dict = {
            "id": chain.id,
            "status": chain.status,
            "severity": chain.severity,
            "entities_involved": sorted(chain.entities_involved),
            "narrative": (
                f"Kill chain with {len(chain.events)} events across "
                f"{len(chain.entities_involved)} entities. "
                f"Tactics: {', '.join(chain.tactics_observed)}. "
                f"Duration: {chain.duration}."
            ),
        }
        try:
            Database.save_kill_chain(chain_dict)
            chains_saved += 1
        except Exception as e:
            print(f"  ERROR saving kill chain {chain.id}: {e}")

    print(f"  Alerts saved: {alerts_saved}")
    print(f"  Kill chains saved: {chains_saved}")
    print(f"\n{'='*60}")
    print("DETECTION RUN COMPLETE")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run detection pipeline on stored snapshots")
    parser.add_argument("--cusum-threshold", type=float, default=0.05)
    parser.add_argument("--drift-threshold", type=float, default=0.15)
    parser.add_argument("--alignment-threshold", type=float, default=0.3)
    parser.add_argument("--min-severity", default="low", choices=["critical", "high", "medium", "low", "info"])
    args = parser.parse_args()

    run_detection(
        cusum_threshold=args.cusum_threshold,
        drift_threshold=args.drift_threshold,
        alignment_threshold=args.alignment_threshold,
        min_severity=args.min_severity,
    )
