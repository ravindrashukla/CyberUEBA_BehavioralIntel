"""Abstract base class for all attack scenarios."""

from abc import ABC, abstractmethod
from datetime import datetime, date


class AttackScenario(ABC):
    """Base class that all attack injection scenarios must implement."""

    def __init__(self, config: dict):
        self.config = config
        self.id = config["id"]
        self.start = config["start"]

    @abstractmethod
    def is_active(self, current_date: date) -> bool:
        """Return True if the attack is active on the given date."""
        ...

    @abstractmethod
    def modify_auth_events(
        self, user_id: str, events: list[dict], current_date: date, rng
    ) -> list[dict]:
        """Modify or inject authentication events for a user on a given date."""
        ...

    @abstractmethod
    def modify_network_flows(
        self, device_id: str, flows: list[dict], current_date: date, rng
    ) -> list[dict]:
        """Modify or inject network flow records for a device on a given date."""
        ...

    @abstractmethod
    def inject_events(self, current_date: date, rng) -> dict[str, list[dict]]:
        """Generate entirely new events keyed by event type (auth, network, file, etc.)."""
        ...

    @property
    @abstractmethod
    def mitre_techniques(self) -> list[str]:
        """MITRE ATT&CK technique IDs associated with this scenario."""
        ...

    @property
    @abstractmethod
    def involved_entities(self) -> dict[str, list[str]]:
        """Entities involved, keyed by type (users, devices, ips)."""
        ...
