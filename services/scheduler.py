"""Background scheduler for periodic UEBA processing tasks."""
import os
import time
import logging
from datetime import date, datetime, timedelta
from threading import Thread, Event

import numpy as np

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_HOURS = int(os.environ.get("REFRESH_INTERVAL_HOURS", "24"))
CUSUM_THRESHOLD = float(os.environ.get("CUSUM_THRESHOLD", "0.05"))
CUSUM_DRIFT_ALLOWANCE = float(os.environ.get("CUSUM_DRIFT_ALLOWANCE", "0.02"))
ALERT_DRIFT_THRESHOLD = float(os.environ.get("ALERT_DRIFT_THRESHOLD", "0.15"))
SNAPSHOT_INTERVAL_DAYS = int(os.environ.get("SNAPSHOT_INTERVAL_DAYS", "30"))


class UEBAScheduler:
    """Background scheduler for behavioral analysis tasks."""

    def __init__(self):
        self._running = False
        self._thread = None
        self._stop_event = Event()
        self.last_embedding_refresh = None
        self.last_detection_scan = None
        self._errors = []

    def start(self):
        """Start the background scheduler thread."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        self._stop_event.clear()
        self._thread = Thread(target=self._run_loop, daemon=True, name="ueba-scheduler")
        self._thread.start()
        logger.info(
            "UEBA scheduler started (refresh interval: %dh)", REFRESH_INTERVAL_HOURS
        )

    def stop(self):
        """Stop the scheduler."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info("UEBA scheduler stopped")

    def _run_loop(self):
        """Main scheduler loop."""
        # Run an initial scan on startup after a brief delay
        self._stop_event.wait(timeout=5)
        if not self._running:
            return

        logger.info("Scheduler performing initial embedding refresh + detection scan")
        self._safe_run(self.refresh_embeddings)
        self._safe_run(self.run_detection_scan)

        interval_seconds = REFRESH_INTERVAL_HOURS * 3600
        while self._running:
            # Wait for the configured interval (interruptible)
            if self._stop_event.wait(timeout=interval_seconds):
                break  # Stop event was set

            if not self._running:
                break

            logger.info("Scheduler tick: starting periodic refresh cycle")
            self._safe_run(self.refresh_embeddings)
            self._safe_run(self.run_detection_scan)

    def _safe_run(self, func):
        """Execute a function with error handling and logging."""
        try:
            func()
        except Exception as e:
            error_msg = f"{func.__name__} failed: {e}"
            logger.error(error_msg, exc_info=True)
            self._errors.append({
                "timestamp": datetime.utcnow().isoformat(),
                "function": func.__name__,
                "error": str(e),
            })
            # Keep only last 50 errors
            if len(self._errors) > 50:
                self._errors = self._errors[-50:]

    def refresh_embeddings(self):
        """Recompute behavioral embeddings for all entities using latest logs.

        Steps:
        1. Determine current month window
        2. Build snapshots using SnapshotBuilder
        3. For each entity: save signal vectors + composite to DB
        """
        from services.database import Database, check_connection
        from embeddings.snapshot_builder import SnapshotBuilder

        if not check_connection():
            logger.warning("Database not available, skipping embedding refresh")
            return

        logger.info("Starting embedding refresh")
        start_time = time.time()

        # Determine current period (current month)
        today = date.today()
        month_start = today.replace(day=1)
        month_end = today

        # Build snapshots for current month
        builder = SnapshotBuilder()
        entity_types = ["user", "device", "segment", "app"]
        total_saved = 0

        for etype in entity_types:
            try:
                if etype == "user":
                    snapshots = builder.build_user_snapshots(month_start, month_end)
                elif etype == "device":
                    snapshots = builder.build_device_snapshots(month_start, month_end)
                elif etype == "segment":
                    snapshots = builder.build_segment_snapshots(month_start, month_end)
                elif etype == "app":
                    snapshots = builder.build_app_snapshots(month_start, month_end)
                else:
                    continue

                for snap in snapshots:
                    # Save current embedding to the live embedding table
                    Database.save_behavioral_embedding(
                        entity_type=snap["entity_type"],
                        entity_id=snap["entity_id"],
                        signal_vectors=snap["signal_vectors"],
                        composite=snap["composite"],
                    )
                    # Save as a trajectory snapshot
                    Database.save_snapshot(
                        entity_type=snap["entity_type"],
                        entity_id=snap["entity_id"],
                        cutoff_date=snap["cutoff_date"],
                        signal_vectors=snap["signal_vectors"],
                        composite=snap["composite"],
                    )
                    total_saved += 1

            except Exception as e:
                logger.error("Failed to refresh embeddings for %s: %s", etype, e)

        elapsed = time.time() - start_time
        self.last_embedding_refresh = datetime.utcnow()
        logger.info(
            "Embedding refresh complete: %d entities updated in %.1fs",
            total_saved, elapsed,
        )

    def run_detection_scan(self):
        """Run CUSUM + drift direction scan on all entities.

        Steps:
        1. Load trajectory snapshots (need at least 2 per entity)
        2. Run batch CUSUM scan
        3. Run batch drift analysis
        4. Generate alerts for detections
        5. Update kill-chains with new alerts
        """
        from services.database import Database, check_connection
        from detection.cusum import batch_cusum_scan, cusum_scan_entity
        from detection.drift_direction import analyze_entity_drift, batch_drift_analysis
        from detection.reference_concepts import ConceptLibrary
        from detection.alert_generator import AlertGenerator
        from detection.kill_chain import KillChainReconstructor

        if not check_connection():
            logger.warning("Database not available, skipping detection scan")
            return

        logger.info("Starting detection scan")
        start_time = time.time()

        alert_gen = AlertGenerator(
            drift_threshold=ALERT_DRIFT_THRESHOLD,
            cusum_threshold=CUSUM_THRESHOLD,
        )
        reconstructor = KillChainReconstructor()
        concept_library = ConceptLibrary()

        entity_types = ["user", "device", "segment", "app"]
        total_alerts = 0

        for etype in entity_types:
            try:
                # Get all entities of this type that have snapshots
                entities = Database.get_entities(entity_type=etype, limit=1000)
                if not entities:
                    continue

                # Identify the ID column for this entity type
                from services.database import _ENTITY_TABLES
                _, id_col = _ENTITY_TABLES[etype]

                # Collect snapshots per entity for CUSUM
                cusum_input = {}  # entity_id -> list of composite vectors
                drift_input = {}  # entity_id -> (v_old, v_new)

                for entity in entities:
                    eid = str(entity[id_col])
                    snapshots = Database.get_trajectory_snapshots(etype, eid)
                    if len(snapshots) < 2:
                        continue

                    composites = [
                        s["composite"] for s in snapshots
                        if s["composite"] is not None
                    ]
                    if len(composites) < 2:
                        continue

                    cusum_input[eid] = composites
                    # For drift direction: compare last two snapshots
                    drift_input[eid] = (composites[-2], composites[-1])

                # --- CUSUM scan ---
                cusum_results = batch_cusum_scan(cusum_input, threshold=CUSUM_THRESHOLD)

                # --- Drift direction analysis ---
                drift_results = batch_drift_analysis(
                    entity_snapshots=drift_input,
                    entity_type=etype,
                    concept_library=concept_library,
                    alignment_threshold=0.3,
                    min_drift_magnitude=0.01,
                )

                # Index drift results by entity_id for enrichment
                drift_by_entity = {d.entity_id: d for d in drift_results}

                # --- Generate alerts from CUSUM ---
                for eid, cusum_result in cusum_results.items():
                    drift_analysis = drift_by_entity.get(eid)
                    alert = alert_gen.from_cusum_result(
                        entity_type=etype,
                        entity_id=eid,
                        cusum_result=cusum_result,
                        drift_analysis=drift_analysis,
                    )
                    if alert:
                        total_alerts += 1

                # --- Generate alerts from drift direction ---
                for analysis in drift_results:
                    alert = alert_gen.from_drift_analysis(analysis)
                    if alert:
                        total_alerts += 1

            except Exception as e:
                logger.error("Detection scan failed for %s: %s", etype, e)

        # Deduplicate alerts
        deduped = alert_gen.deduplicate(window_hours=24)

        # Persist alerts and build kill chains
        for alert_dict in alert_gen.to_dicts():
            try:
                Database.save_alert({
                    "entity_type": alert_dict["entity_type"],
                    "entity_id": alert_dict["entity_id"],
                    "event_date": alert_dict["timestamp"],
                    "event_type": alert_dict["detection_method"],
                    "severity": alert_dict["severity"],
                    "magnitude": alert_dict["drift_magnitude"],
                    "drift_concept": (
                        alert_dict["concept_alignments"][0]["concept"]
                        if alert_dict["concept_alignments"] else None
                    ),
                    "concept_alignment": (
                        alert_dict["concept_alignments"][0]["similarity"]
                        if alert_dict["concept_alignments"] else None
                    ),
                    "contributing_signals": alert_dict["concept_alignments"],
                    "mitre_techniques": alert_dict["mitre_techniques"] or None,
                    "kill_chain_id": alert_dict.get("kill_chain_id"),
                })
            except Exception as e:
                logger.error("Failed to save alert: %s", e)

        # Ingest alerts into kill chain reconstructor
        for alert in alert_gen.get_alerts():
            try:
                reconstructor.ingest_alert(alert)
            except Exception as e:
                logger.error("Failed to process alert for kill chain: %s", e)

        # Persist active kill chains
        reconstructor.mark_stale()
        for chain_dict in reconstructor.to_dicts():
            if chain_dict["status"] == "stale":
                continue
            try:
                Database.save_kill_chain({
                    "chain_id": chain_dict["id"],
                    "chain_name": f"Chain-{chain_dict['id'][:8]}",
                    "start_time": chain_dict["created_at"],
                    "end_time": None,
                    "status": chain_dict["status"],
                    "confidence": None,
                    "involved_users": [
                        e.split(":")[1] for e in chain_dict["entities_involved"]
                        if e.startswith("user:")
                    ] or None,
                    "involved_devices": [
                        e.split(":")[1] for e in chain_dict["entities_involved"]
                        if e.startswith("device:")
                    ] or None,
                    "involved_segments": [
                        e.split(":")[1] for e in chain_dict["entities_involved"]
                        if e.startswith("segment:")
                    ] or None,
                    "attack_narrative": None,
                    "mitre_tactics": chain_dict.get("tactics_observed"),
                })
            except Exception as e:
                logger.error("Failed to save kill chain: %s", e)

        elapsed = time.time() - start_time
        self.last_detection_scan = datetime.utcnow()
        logger.info(
            "Detection scan complete: %d alerts generated (%d after dedup) in %.1fs",
            total_alerts, len(deduped), elapsed,
        )

    def status(self) -> dict:
        """Return scheduler status for health endpoint."""
        return {
            "running": self._running,
            "refresh_interval_hours": REFRESH_INTERVAL_HOURS,
            "last_embedding_refresh": (
                self.last_embedding_refresh.isoformat()
                if self.last_embedding_refresh else None
            ),
            "last_detection_scan": (
                self.last_detection_scan.isoformat()
                if self.last_detection_scan else None
            ),
            "recent_errors": self._errors[-5:] if self._errors else [],
        }


# Module-level singleton
scheduler = UEBAScheduler()


if __name__ == "__main__":
    # Allow running as standalone worker: python -m services.scheduler
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting UEBA scheduler as standalone worker")

    from services.database import init_db, check_connection

    # Wait for database to be ready
    retries = 0
    while retries < 30:
        if check_connection():
            break
        logger.info("Waiting for database... (attempt %d/30)", retries + 1)
        time.sleep(2)
        retries += 1

    if not check_connection():
        logger.error("Could not connect to database after 30 attempts, exiting")
        raise SystemExit(1)

    init_db()
    scheduler.start()

    # Keep main thread alive
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Shutting down scheduler")
        scheduler.stop()
