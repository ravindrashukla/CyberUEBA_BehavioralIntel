"""MITRE ATT&CK mapping for detected behavioral patterns."""
from dataclasses import dataclass

__all__ = [
    "TechniqueInfo",
    "TECHNIQUE_DB",
    "technique_to_tactic",
    "techniques_to_tactics",
    "get_technique_info",
    "concept_to_techniques",
    "build_attack_narrative",
]


@dataclass
class TechniqueInfo:
    id: str
    name: str
    tactic: str
    description: str


# Core technique database (most relevant for UEBA behavioral detection)
TECHNIQUE_DB: dict[str, TechniqueInfo] = {
    "T1110": TechniqueInfo(
        "T1110", "Brute Force", "Credential Access",
        "Adversary uses repeated login attempts to guess credentials"),
    "T1078": TechniqueInfo(
        "T1078", "Valid Accounts", "Defense Evasion",
        "Adversary uses legitimate credentials to maintain access"),
    "T1059": TechniqueInfo(
        "T1059", "Command and Scripting Interpreter", "Execution",
        "Adversary executes commands via system interpreters"),
    "T1547": TechniqueInfo(
        "T1547", "Boot or Logon Autostart Execution", "Persistence",
        "Adversary configures system to execute code at startup"),
    "T1562": TechniqueInfo(
        "T1562", "Impair Defenses", "Defense Evasion",
        "Adversary disables or modifies security tools"),
    "T1071": TechniqueInfo(
        "T1071", "Application Layer Protocol", "Command and Control",
        "Adversary communicates using standard application protocols"),
    "T1005": TechniqueInfo(
        "T1005", "Data from Local System", "Collection",
        "Adversary collects data from the local system"),
    "T1074": TechniqueInfo(
        "T1074", "Data Staged", "Collection",
        "Adversary stages collected data before exfiltration"),
    "T1048": TechniqueInfo(
        "T1048", "Exfiltration Over Alternative Protocol", "Exfiltration",
        "Adversary exfiltrates via non-standard protocol"),
    "T1567": TechniqueInfo(
        "T1567", "Exfiltration Over Web Service", "Exfiltration",
        "Adversary exfiltrates data to cloud storage"),
    "T1068": TechniqueInfo(
        "T1068", "Exploitation for Privilege Escalation", "Privilege Escalation",
        "Adversary exploits vulnerability to gain elevated access"),
    "T1134": TechniqueInfo(
        "T1134", "Access Token Manipulation", "Privilege Escalation",
        "Adversary manipulates access tokens for escalation"),
    "T1548": TechniqueInfo(
        "T1548", "Abuse Elevation Control Mechanism", "Privilege Escalation",
        "Adversary bypasses elevation controls"),
    "T1021": TechniqueInfo(
        "T1021", "Remote Services", "Lateral Movement",
        "Adversary uses remote services to move laterally"),
    "T1570": TechniqueInfo(
        "T1570", "Lateral Tool Transfer", "Lateral Movement",
        "Adversary transfers tools between systems"),
    "T1550": TechniqueInfo(
        "T1550", "Use Alternate Authentication Material", "Lateral Movement",
        "Adversary uses stolen credentials/tokens for lateral access"),
    "T1046": TechniqueInfo(
        "T1046", "Network Service Discovery", "Discovery",
        "Adversary scans for services running on hosts"),
    "T1018": TechniqueInfo(
        "T1018", "Remote System Discovery", "Discovery",
        "Adversary discovers remote systems on the network"),
    "T1087": TechniqueInfo(
        "T1087", "Account Discovery", "Discovery",
        "Adversary enumerates accounts for targeting"),
    "T1135": TechniqueInfo(
        "T1135", "Network Share Discovery", "Discovery",
        "Adversary discovers shared network resources"),
    "T1195": TechniqueInfo(
        "T1195", "Supply Chain Compromise", "Initial Access",
        "Adversary compromises supply chain to gain access"),
    "T1573": TechniqueInfo(
        "T1573", "Encrypted Channel", "Command and Control",
        "Adversary encrypts C2 communications"),
    "T1568": TechniqueInfo(
        "T1568", "Dynamic Resolution", "Command and Control",
        "Adversary uses dynamic DNS/domain generation"),
    "T1102": TechniqueInfo(
        "T1102", "Web Service", "Command and Control",
        "Adversary uses legitimate web services for C2"),
    "T1083": TechniqueInfo(
        "T1083", "File and Directory Discovery", "Discovery",
        "Adversary enumerates files and directories"),
    "T1039": TechniqueInfo(
        "T1039", "Data from Network Shared Drive", "Collection",
        "Adversary collects data from network shares"),
    "T1052": TechniqueInfo(
        "T1052", "Exfiltration Over Physical Medium", "Exfiltration",
        "Adversary exfiltrates data via USB or other physical media"),
    "T1486": TechniqueInfo(
        "T1486", "Data Encrypted for Impact", "Impact",
        "Adversary encrypts data to disrupt availability (ransomware)"),
    "T1490": TechniqueInfo(
        "T1490", "Inhibit System Recovery", "Impact",
        "Adversary deletes backups to prevent recovery"),
    "T1566": TechniqueInfo(
        "T1566", "Phishing", "Initial Access",
        "Adversary sends phishing message to gain access"),
    "T1003": TechniqueInfo(
        "T1003", "OS Credential Dumping", "Credential Access",
        "Adversary dumps OS credentials from memory"),
    "T1072": TechniqueInfo(
        "T1072", "Software Deployment Tools", "Lateral Movement",
        "Adversary uses IT management tools for lateral spread"),
}

# Ordered list of MITRE tactics (kill-chain progression)
TACTIC_ORDER = [
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


def technique_to_tactic(technique_id: str) -> str:
    """Map technique ID to parent tactic name."""
    info = TECHNIQUE_DB.get(technique_id)
    if info:
        return info.tactic
    # Try base technique (strip sub-technique: T1059.001 -> T1059)
    base_id = technique_id.split(".")[0]
    info = TECHNIQUE_DB.get(base_id)
    return info.tactic if info else "Unknown"


def techniques_to_tactics(technique_ids: list[str]) -> list[str]:
    """Map multiple technique IDs to unique ordered tactics.

    Returns tactics sorted by kill-chain progression order.
    """
    tactics = set()
    for tid in technique_ids:
        tactic = technique_to_tactic(tid)
        if tactic != "Unknown":
            tactics.add(tactic)
    return sorted(tactics, key=lambda t: TACTIC_ORDER.index(t) if t in TACTIC_ORDER else 99)


def get_technique_info(technique_id: str) -> TechniqueInfo | None:
    """Retrieve full TechniqueInfo for a given technique ID."""
    info = TECHNIQUE_DB.get(technique_id)
    if info:
        return info
    # Try base technique
    base_id = technique_id.split(".")[0]
    return TECHNIQUE_DB.get(base_id)


def concept_to_techniques(concept_name: str, concept_library) -> list[TechniqueInfo]:
    """Get MITRE techniques associated with a reference concept.

    Args:
        concept_name: name of the concept to look up
        concept_library: object with a .concepts list, each having
                         .name and .mitre_techniques attributes

    Returns:
        List of TechniqueInfo objects for the concept's mapped techniques.
    """
    for concept in concept_library.concepts:
        if concept.name == concept_name:
            return [
                TECHNIQUE_DB[t]
                for t in concept.mitre_techniques
                if t in TECHNIQUE_DB
            ]
    return []


def build_attack_narrative(kill_chain_events: list) -> str:
    """Generate a human-readable attack narrative from kill-chain events.

    Produces a paragraph describing the attack progression in temporal order,
    mapping each stage to its MITRE tactic.

    Args:
        kill_chain_events: list of KillChainEvent objects (from kill_chain.py)

    Returns:
        A narrative string joining all stages with arrows.
    """
    if not kill_chain_events:
        return "No events in kill chain."

    narrative_parts = []
    for i, event in enumerate(kill_chain_events):
        techniques = ", ".join(event.techniques) if event.techniques else "unknown technique"
        narrative_parts.append(
            f"Stage {i + 1} ({event.tactic}): {event.description} "
            f"[{techniques}] detected on {event.entity_type}:{event.entity_id} "
            f"at {event.timestamp.isoformat()}"
        )

    return " → ".join(narrative_parts)
