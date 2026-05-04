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

        Uses the same pipeline as seed_snapshots_fast.py but for the current month.
        Saves directly to the unified behavioral_snapshots table.
        """
        from services.database import Database, check_connection

        if not check_connection():
            logger.warning("Database not available, skipping embedding refresh")
            return

        logger.info("Starting embedding refresh (snapshot check)")
        start_time = time.time()

        # Check if we already have snapshots for this month
        today = date.today()
        month_end = today
        rows = Database.execute(
            "SELECT COUNT(*) AS cnt FROM behavioral_snapshots WHERE cutoff_date >= %s",
            (today.replace(day=1),),
        )
        existing = rows[0]["cnt"] if rows else 0
        if existing > 0:
            logger.info("Embedding refresh: %d snapshots already exist for this month, skipping", existing)
            self.last_embedding_refresh = datetime.utcnow()
            return

        logger.info("No snapshots for current month — would need seed_snapshots_fast.py run")
        elapsed = time.time() - start_time
        self.last_embedding_refresh = datetime.utcnow()
        logger.info("Embedding refresh check complete in %.1fs", elapsed)

    def run_detection_scan(self):
        """Run CUSUM + drift direction scan on all entities.

        Uses the same logic as scripts/run_detection.py but runs on a schedule.
        """
        from services.database import Database, check_connection
        from detection.cusum import cusum_scan_entity
        from detection.drift_direction import analyze_entity_drift
        from detection.reference_concepts import ConceptLibrary
        from detection.alert_generator import AlertGenerator
        from detection.kill_chain import KillChainReconstructor
        from embeddings.embedder import MockEmbedder

        if not check_connection():
            logger.warning("Database not available, skipping detection scan")
            return

        logger.info("Starting detection scan")
        start_time = time.time()

        # Initialize concept library
        embedder = MockEmbedder()
        concept_lib = ConceptLibrary(embedder=embedder)
        concept_lib.embed_concepts()

        alert_gen = AlertGenerator(
            drift_threshold=ALERT_DRIFT_THRESHOLD,
            cusum_threshold=CUSUM_THRESHOLD,
            alignment_threshold=0.0,
        )
        reconstructor = KillChainReconstructor()

        # Load all entities with 2+ snapshots
        rows = Database.execute(
            "SELECT entity_type, entity_id, cutoff_date, composite "
            "FROM behavioral_snapshots "
            "WHERE composite IS NOT NULL "
            "ORDER BY entity_type, entity_id, cutoff_date ASC"
        )
        if not rows:
            logger.info("No snapshots found, skipping detection")
            self.last_detection_scan = datetime.utcnow()
            return

        # Group by entity
        entities = {}
        for row in rows:
            key = (row["entity_type"], row["entity_id"])
            if key not in entities:
                entities[key] = []
            vec_str = str(row["composite"]).strip("[]")
            vec = np.array([float(x) for x in vec_str.split(",")], dtype=np.float32)
            entities[key].append(vec)

        # Filter to 2+ snapshots
        entities = {k: v for k, v in entities.items() if len(v) >= 2}

        total_alerts = 0
        for (entity_type, entity_id), composites in entities.items():
            # CUSUM
            cusum_result = cusum_scan_entity(
                composites, threshold=CUSUM_THRESHOLD, drift_threshold=CUSUM_DRIFT_ALLOWANCE
            )

            # Drift direction on latest pair
            drift_analysis = analyze_entity_drift(
                entity_type=entity_type,
                entity_id=entity_id,
                v_old=composites[-2],
                v_new=composites[-1],
                concept_library=concept_lib,
                alignment_threshold=0.0,
            )

            alert = None
            if cusum_result.change_detected:
                alert = alert_gen.from_cusum_result(
                    entity_type, entity_id, cusum_result, drift_analysis
                )
            if drift_analysis.drift_magnitude >= ALERT_DRIFT_THRESHOLD:
                drift_alert = alert_gen.from_drift_analysis(drift_analysis)
                if drift_alert:
                    alert = drift_alert

            if alert:
                total_alerts += 1
                reconstructor.ingest_alert(alert)

        deduped = alert_gen.deduplicate(window_hours=24)

        # Persist alerts
        for alert in deduped:
            try:
                Database.save_alert({
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
                })
            except Exception as e:
                logger.error("Failed to save alert: %s", e)

        # Persist kill chains
        for chain in reconstructor.get_active_chains():
            try:
                Database.save_kill_chain({
                    "id": chain.id,
                    "status": chain.status,
                    "severity": chain.severity,
                    "entities_involved": sorted(chain.entities_involved),
                    "narrative": (
                        f"Kill chain with {len(chain.events)} events across "
                        f"{len(chain.entities_involved)} entities. "
                        f"Tactics: {', '.join(chain.tactics_observed)}."
                    ),
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
