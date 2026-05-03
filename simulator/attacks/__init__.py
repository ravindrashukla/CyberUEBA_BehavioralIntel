"""Attack injection scenarios for UEBA synthetic data simulation."""

from .base import AttackScenario
from .brute_force import BruteForceAttack
from .apt_slow import APTSlowAttack
from .insider_threat import InsiderThreatAttack
from .credential_theft import CredentialTheftLateral
from .ransomware import Ransomware
from .supply_chain import SupplyChainCompromise

__all__ = [
    "AttackScenario",
    "BruteForceAttack",
    "APTSlowAttack",
    "InsiderThreatAttack",
    "CredentialTheftLateral",
    "Ransomware",
    "SupplyChainCompromise",
]
