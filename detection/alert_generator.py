"""Generate alerts from CUSUM detections and drift direction analysis."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import uuid

__all__ = [
    "AlertSeverity",
    "AlertStatus",
    "Alert",
    "AlertGenerator",
]


class AlertSeverity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AlertStatus(Enum):
    NEW = "new"
    INVESTIGATING = "investigating"
    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"
    RESOLVED = "resolved"


@dataclass
class Alert:
    id: str
    timestamp: datetime
    entity_type: str
    entity_id: str
    severity: AlertSeverity
    title: str
    description: str
    detection_method: str  # "cusum", "threshold", "drift_direction", "cohort"
    drift_magnitude: float
    concept_alignments: list[dict]  # top concept alignment results
    mitre_techniques: list[str]
    confidence: float
    status: AlertStatus = AlertStatus.NEW
    kill_chain_id: str | None = None
    related_entities: list[str] = field(default_factory=list)


class AlertGenerator:
    """Generate alerts from detection pipeline results.

    Accepts outputs from the detection pipeline (drift analysis, CUSUM results,
    threshold breaches) and converts them into structured Alert objects with
    severity classification, MITRE technique mapping, and deduplication.
    """

    # Severity thresholds based on drift magnitude
    _SEVERITY_THRESHOLDS = [
        (0.50, AlertSeverity.CRITICAL),
        (0.35, AlertSeverity.HIGH),
        (0.20, AlertSeverity.MEDIUM),
        (0.10, AlertSeverity.LOW),
        (0.00, AlertSeverity.INFO),
    ]

    def __init__(
        self,
        drift_threshold: float = 0.15,
        cusum_threshold: float = 0.05,
        alignment_threshold: float = 0.3,
    ):
        self.drift_threshold = drift_threshold
        self.cusum_threshold = cusum_threshold
        self.alignment_threshold = alignment_threshold
        self._alerts: list[Alert] = []

    def from_drift_analysis(self, drift_analysis, timestamp: datetime = None) -> Alert | None:
        """Create alert from a DriftAnalysis result if thresholds exceeded.

        Args:
            drift_analysis: DriftAnalysis from detection/drift_direction.py
                (has entity_type, entity_id, drift_magnitude, top_alignments,
                 primary_direction, is_threat, confidence)
            timestamp: when the drift was observed (defaults to now)
        """
        if drift_analysis.drift_magnitude < self.drift_threshold:
            return None

        # Convert ConceptAlignment objects to dicts for alert storage
        alignments = [
            {
                "concept": a.concept_name,
                "similarity": a.alignment_score,
                "category": a.category,
                "severity": a.severity,
                "mitre_techniques": a.mitre_techniques,
            }
            for a in drift_analysis.top_alignments
            if a.alignment_score >= self.alignment_threshold
        ]

        # Collect MITRE techniques from aligned concepts
        techniques = []
        for a in alignments:
            techniques.extend(a.get("mitre_techniques", []))
        techniques = list(dict.fromkeys(techniques))  # dedupe, preserve order

        severity = self._classify_severity(drift_analysis.drift_magnitude, len(alignments))
        confidence = self._compute_confidence(
            drift_analysis.drift_magnitude, alignments, detection_method="drift_direction"
        )

        title = (
            f"Behavioral drift detected: {drift_analysis.entity_type}"
            f":{drift_analysis.entity_id}"
        )
        description = self._build_description(
            drift_analysis.drift_magnitude, alignments, techniques, "drift_direction"
        )

        alert = Alert(
            id=str(uuid.uuid4()),
            timestamp=timestamp or datetime.utcnow(),
            entity_type=drift_analysis.entity_type,
            entity_id=drift_analysis.entity_id,
            severity=severity,
            title=title,
            description=description,
            detection_method="drift_direction",
            drift_magnitude=drift_analysis.drift_magnitude,
            concept_alignments=alignments,
            mitre_techniques=techniques,
            confidence=confidence,
        )
        self._alerts.append(alert)
        return alert

    def from_cusum_result(
        self, entity_type: str, entity_id: str, cusum_result, drift_analysis=None
    ) -> Alert | None:
        """Create alert from CUSUM detection (slow drift accumulation).

        Args:
            entity_type: type of entity (user, device, segment, app, session)
            entity_id: unique entity identifier
            cusum_result: CUSUMResult from detection/cusum.py
            drift_analysis: optional DriftAnalysis for enrichment
        """
        if not cusum_result.change_detected:
            return None

        alignments = []
        techniques = []
        magnitude = cusum_result.cumulative_sum

        if drift_analysis is not None:
            alignments = [
                {
                    "concept": a.concept_name,
                    "similarity": a.alignment_score,
                    "category": a.category,
                    "severity": a.severity,
                    "mitre_techniques": a.mitre_techniques,
                }
                for a in drift_analysis.top_alignments
                if a.alignment_score >= self.alignment_threshold
            ]
            for a in alignments:
                techniques.extend(a.get("mitre_techniques", []))
            techniques = list(dict.fromkeys(techniques))
            magnitude = max(magnitude, drift_analysis.drift_magnitude)

        severity = self._classify_severity(magnitude, len(alignments))
        # CUSUM detections of slow drift get a confidence boost (they accumulate evidence)
        confidence = min(
            1.0,
            self._compute_confidence(magnitude, alignments, "cusum")
            + 0.1 * cusum_result.run_length,
        )

        title = (
            f"Sustained behavioral drift (CUSUM): {entity_type}:{entity_id}"
        )
        description = (
            f"CUSUM detected sustained drift over {cusum_result.run_length} periods. "
            f"Cumulative sum: {cusum_result.cumulative_sum:.4f} "
            f"(threshold: {cusum_result.threshold:.4f}). "
            f"Change point at index {cusum_result.change_point_idx}."
        )

        alert = Alert(
            id=str(uuid.uuid4()),
            timestamp=datetime.utcnow(),
            entity_type=entity_type,
            entity_id=entity_id,
            severity=severity,
            title=title,
            description=description,
            detection_method="cusum",
            drift_magnitude=magnitude,
            concept_alignments=alignments,
            mitre_techniques=techniques,
            confidence=confidence,
        )
        self._alerts.append(alert)
        return alert

    def from_threshold_breach(
        self,
        entity_type: str,
        entity_id: str,
        drift_magnitude: float,
        concept_alignments: list,
    ) -> Alert | None:
        """Create alert from simple threshold breach.

        Args:
            entity_type: type of entity
            entity_id: unique entity identifier
            drift_magnitude: cosine distance that triggered the breach
            concept_alignments: list of dicts with 'concept', 'similarity', 'mitre_techniques'
        """
        if drift_magnitude < self.drift_threshold:
            return None

        alignments = [
            a for a in concept_alignments
            if a.get("similarity", 0) >= self.alignment_threshold
        ]
        techniques = []
        for a in alignments:
            techniques.extend(a.get("mitre_techniques", []))
        techniques = list(dict.fromkeys(techniques))  # dedupe, preserve order

        severity = self._classify_severity(drift_magnitude, len(alignments))
        confidence = self._compute_confidence(drift_magnitude, alignments, "threshold")

        title = f"Drift threshold breach: {entity_type}:{entity_id}"
        description = self._build_description(
            drift_magnitude, alignments, techniques, "threshold"
        )

        alert = Alert(
            id=str(uuid.uuid4()),
            timestamp=datetime.utcnow(),
            entity_type=entity_type,
            entity_id=entity_id,
            severity=severity,
            title=title,
            description=description,
            detection_method="threshold",
            drift_magnitude=drift_magnitude,
            concept_alignments=alignments,
            mitre_techniques=techniques,
            confidence=confidence,
        )
        self._alerts.append(alert)
        return alert

    def deduplicate(self, window_hours: int = 24) -> list[Alert]:
        """Remove duplicate alerts for same entity within time window.

        Keeps the highest-severity alert for each (entity_type, entity_id) pair
        within each time window.
        """
        window = timedelta(hours=window_hours)
        seen: dict[tuple[str, str], Alert] = {}
        deduped: list[Alert] = []

        for alert in sorted(self._alerts, key=lambda a: a.timestamp):
            key = (alert.entity_type, alert.entity_id)
            if key in seen:
                prev = seen[key]
                # Same entity within window — keep higher severity
                if (alert.timestamp - prev.timestamp) <= window:
                    if self._severity_rank(alert.severity) < self._severity_rank(prev.severity):
                        # New alert is more severe, replace
                        deduped.remove(prev)
                        deduped.append(alert)
                        seen[key] = alert
                    # Otherwise discard the new (lower severity) alert
                    continue

            seen[key] = alert
            deduped.append(alert)

        self._alerts = deduped
        return deduped

    def get_alerts(self, severity_min: AlertSeverity = None) -> list[Alert]:
        """Get all alerts, optionally filtered by minimum severity."""
        if severity_min is None:
            return list(self._alerts)

        min_rank = self._severity_rank(severity_min)
        return [a for a in self._alerts if self._severity_rank(a.severity) <= min_rank]

    def to_dicts(self) -> list[dict]:
        """Serialize all alerts to dicts for API/storage."""
        return [
            {
                "id": a.id,
                "timestamp": a.timestamp.isoformat(),
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "severity": a.severity.value,
                "title": a.title,
                "description": a.description,
                "detection_method": a.detection_method,
                "drift_magnitude": a.drift_magnitude,
                "concept_alignments": a.concept_alignments,
                "mitre_techniques": a.mitre_techniques,
                "confidence": a.confidence,
                "status": a.status.value,
                "kill_chain_id": a.kill_chain_id,
                "related_entities": a.related_entities,
            }
            for a in self._alerts
        ]

    # --- Private helpers ---

    def _classify_severity(self, magnitude: float, n_alignments: int) -> AlertSeverity:
        """Classify alert severity based on drift magnitude and concept alignment count."""
        # More concept alignments = more specific threat signal, boost severity
        boost = 0.05 * n_alignments

        effective_magnitude = magnitude + boost
        for threshold, severity in self._SEVERITY_THRESHOLDS:
            if effective_magnitude >= threshold:
                return severity
        return AlertSeverity.INFO

    def _compute_confidence(
        self, magnitude: float, alignments: list[dict], detection_method: str
    ) -> float:
        """Compute confidence score [0, 1] based on evidence strength."""
        # Base confidence from magnitude (capped at 0.6)
        base = min(0.6, magnitude / 0.5)

        # Alignment boost (up to 0.3)
        if alignments:
            avg_sim = sum(a.get("similarity", 0) for a in alignments) / len(alignments)
            align_boost = min(0.3, avg_sim * 0.4)
        else:
            align_boost = 0.0

        # Method boost: CUSUM and drift_direction are more reliable than raw threshold
        method_boost = {"cusum": 0.1, "drift_direction": 0.08, "threshold": 0.0, "cohort": 0.05}
        m_boost = method_boost.get(detection_method, 0.0)

        return min(1.0, base + align_boost + m_boost)

    @staticmethod
    def _severity_rank(severity: AlertSeverity) -> int:
        """Lower rank = more severe."""
        order = [
            AlertSeverity.CRITICAL,
            AlertSeverity.HIGH,
            AlertSeverity.MEDIUM,
            AlertSeverity.LOW,
            AlertSeverity.INFO,
        ]
        return order.index(severity)

    def _build_description(
        self,
        magnitude: float,
        alignments: list[dict],
        techniques: list[str],
        method: str,
    ) -> str:
        """Build human-readable alert description."""
        parts = [f"Detection method: {method}. Drift magnitude: {magnitude:.4f}."]

        if alignments:
            top = alignments[0]
            parts.append(
                f"Top concept alignment: {top.get('concept', 'unknown')} "
                f"(similarity: {top.get('similarity', 0):.3f})."
            )

        if techniques:
            parts.append(f"MITRE techniques: {', '.join(techniques)}.")

        return " ".join(parts)
