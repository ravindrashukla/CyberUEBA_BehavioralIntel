"""Kill-chain reconstruction: link related alerts into attack narratives."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import uuid

__all__ = [
    "KillChainEvent",
    "KillChain",
    "KillChainReconstructor",
]


@dataclass
class KillChainEvent:
    alert_id: str
    entity_type: str
    entity_id: str
    timestamp: datetime
    tactic: str  # MITRE tactic (e.g., "Initial Access", "Lateral Movement")
    techniques: list[str]
    description: str
    confidence: float


@dataclass
class KillChain:
    id: str
    created_at: datetime
    events: list[KillChainEvent] = field(default_factory=list)
    entities_involved: set = field(default_factory=set)
    status: str = "active"  # active, complete, stale

    @property
    def duration(self) -> timedelta:
        if len(self.events) < 2:
            return timedelta(0)
        return self.events[-1].timestamp - self.events[0].timestamp

    @property
    def tactics_observed(self) -> list[str]:
        return list(dict.fromkeys(e.tactic for e in self.events))

    @property
    def severity(self) -> str:
        """Escalate severity based on kill-chain progression."""
        n_tactics = len(self.tactics_observed)
        if n_tactics >= 5:
            return "critical"
        elif n_tactics >= 3:
            return "high"
        elif n_tactics >= 2:
            return "medium"
        return "low"

    def add_event(self, event: KillChainEvent):
        self.events.append(event)
        self.events.sort(key=lambda e: e.timestamp)
        self.entities_involved.add(f"{event.entity_type}:{event.entity_id}")


class KillChainReconstructor:
    """Reconstruct attack kill-chains from correlated alerts.

    Alerts are linked into a chain when they share entities (or entities within
    a configurable hop distance) and fall within a temporal correlation window.
    """

    MITRE_TACTICS_ORDER = [
        "Reconnaissance",
        "Resource Development",
        "Initial Access",
        "Execution",
        "Persistence",
        "Privilege Escalation",
        "Defense Evasion",
        "Credential Access",
        "Discovery",
        "Lateral Movement",
        "Collection",
        "Command and Control",
        "Exfiltration",
        "Impact",
    ]

    # Maps common technique ID prefixes to tactics for quick lookup.
    # This covers the most common UEBA-relevant techniques; the full
    # mapping lives in mitre_mapper.TECHNIQUE_DB.
    _TECHNIQUE_TACTIC_MAP = {
        "T1110": "Credential Access",
        "T1078": "Defense Evasion",
        "T1059": "Execution",
        "T1547": "Persistence",
        "T1562": "Defense Evasion",
        "T1071": "Command and Control",
        "T1005": "Collection",
        "T1074": "Collection",
        "T1048": "Exfiltration",
        "T1567": "Exfiltration",
        "T1068": "Privilege Escalation",
        "T1134": "Privilege Escalation",
        "T1548": "Privilege Escalation",
        "T1021": "Lateral Movement",
        "T1570": "Lateral Movement",
        "T1550": "Lateral Movement",
        "T1046": "Discovery",
        "T1018": "Discovery",
        "T1087": "Discovery",
        "T1135": "Discovery",
        "T1195": "Initial Access",
        "T1573": "Command and Control",
        "T1568": "Command and Control",
        "T1102": "Command and Control",
        "T1083": "Discovery",
        "T1039": "Collection",
        "T1052": "Exfiltration",
        "T1486": "Impact",
        "T1490": "Impact",
        "T1566": "Initial Access",
        "T1003": "Credential Access",
        "T1072": "Lateral Movement",
    }

    def __init__(self, correlation_window_hours: int = 72, entity_link_hops: int = 2):
        self.correlation_window = timedelta(hours=correlation_window_hours)
        self.entity_link_hops = entity_link_hops
        self._chains: list[KillChain] = []

    def ingest_alert(self, alert) -> KillChain | None:
        """Process a new alert and either add to existing chain or start new one.

        Args:
            alert: Alert object with id, timestamp, entity_type, entity_id,
                   mitre_techniques, description, confidence, related_entities

        Returns:
            The KillChain the alert was added to (new or existing), or None if
            the alert has no MITRE technique mapping.
        """
        event = self._create_event_from_alert(alert)

        chain = self._find_matching_chain(alert)
        if chain is not None:
            chain.add_event(event)
            # Mark the alert with its kill-chain ID if the alert supports it
            if hasattr(alert, "kill_chain_id"):
                alert.kill_chain_id = chain.id
            return chain

        # Start a new chain
        chain = KillChain(
            id=str(uuid.uuid4()),
            created_at=alert.timestamp,
        )
        chain.add_event(event)
        self._chains.append(chain)

        if hasattr(alert, "kill_chain_id"):
            alert.kill_chain_id = chain.id
        return chain

    def _find_matching_chain(self, alert) -> KillChain | None:
        """Find a chain that this alert correlates with (time + entity linkage).

        Correlation requires:
        1. The alert timestamp falls within the correlation window of the chain's
           latest event.
        2. At least one entity overlap: the alert's entity (or one of its
           related entities) appears in the chain's entity set.
        """
        alert_entity_key = f"{alert.entity_type}:{alert.entity_id}"
        alert_entities = {alert_entity_key}
        if hasattr(alert, "related_entities") and alert.related_entities:
            alert_entities.update(alert.related_entities)

        best_chain = None
        best_overlap = 0

        for chain in self._chains:
            if chain.status == "stale":
                continue

            # Check temporal correlation
            if chain.events:
                latest = chain.events[-1].timestamp
                if abs(alert.timestamp - latest) > self.correlation_window:
                    continue

            # Check entity overlap
            overlap = len(alert_entities & chain.entities_involved)
            if overlap > best_overlap:
                best_overlap = overlap
                best_chain = chain

        return best_chain

    def _create_event_from_alert(self, alert) -> KillChainEvent:
        """Convert alert to kill-chain event with tactic classification."""
        tactic = "Unknown"
        techniques = alert.mitre_techniques if alert.mitre_techniques else []

        # Derive tactic from the first mapped technique
        for tech in techniques:
            mapped = self._technique_to_tactic(tech)
            if mapped != "Unknown":
                tactic = mapped
                break

        return KillChainEvent(
            alert_id=alert.id,
            entity_type=alert.entity_type,
            entity_id=alert.entity_id,
            timestamp=alert.timestamp,
            tactic=tactic,
            techniques=techniques,
            description=alert.description,
            confidence=alert.confidence,
        )

    def _technique_to_tactic(self, technique_id: str) -> str:
        """Map MITRE technique ID to its parent tactic."""
        # Try exact match first
        tactic = self._TECHNIQUE_TACTIC_MAP.get(technique_id)
        if tactic:
            return tactic

        # Try base technique (strip sub-technique: T1059.001 -> T1059)
        base_id = technique_id.split(".")[0]
        return self._TECHNIQUE_TACTIC_MAP.get(base_id, "Unknown")

    def get_active_chains(self) -> list[KillChain]:
        """Return all active (non-stale) kill chains."""
        return [c for c in self._chains if c.status != "stale"]

    def mark_stale(self, max_age: timedelta | None = None) -> int:
        """Mark chains as stale if their latest event exceeds max_age.

        Args:
            max_age: maximum age from latest event to now. Defaults to
                     2x the correlation window.

        Returns:
            Number of chains marked stale.
        """
        if max_age is None:
            max_age = self.correlation_window * 2
        now = datetime.utcnow()
        count = 0
        for chain in self._chains:
            if chain.status == "stale":
                continue
            if chain.events:
                latest = chain.events[-1].timestamp
                if (now - latest) > max_age:
                    chain.status = "stale"
                    count += 1
        return count

    def to_dicts(self) -> list[dict]:
        """Serialize chains for API/storage."""
        return [
            {
                "id": c.id,
                "created_at": c.created_at.isoformat(),
                "status": c.status,
                "severity": c.severity,
                "duration_seconds": c.duration.total_seconds(),
                "tactics_observed": c.tactics_observed,
                "entities_involved": sorted(c.entities_involved),
                "events": [
                    {
                        "alert_id": e.alert_id,
                        "entity_type": e.entity_type,
                        "entity_id": e.entity_id,
                        "timestamp": e.timestamp.isoformat(),
                        "tactic": e.tactic,
                        "techniques": e.techniques,
                        "description": e.description,
                        "confidence": e.confidence,
                    }
                    for e in c.events
                ],
            }
            for c in self._chains
        ]
