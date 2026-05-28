"""Attack injection scenarios for UEBA synthetic data simulation."""

from .base import AttackScenario
from .brute_force import BruteForceAttack
from .apt_slow import APTSlowAttack
from .insider_threat import InsiderThreatAttack
from .credential_theft import CredentialTheftLateral
from .ransomware import Ransomware
from .supply_chain import SupplyChainCompromise
from .volt_typhoon import VoltTyphoonAttack
from .salt_typhoon import SaltTyphoonAttack

__all__ = [
    "AttackScenario",
    "BruteForceAttack",
    "APTSlowAttack",
    "InsiderThreatAttack",
    "CredentialTheftLateral",
    "Ransomware",
    "SupplyChainCompromise",
    "VoltTyphoonAttack",
    "SaltTyphoonAttack",
]
