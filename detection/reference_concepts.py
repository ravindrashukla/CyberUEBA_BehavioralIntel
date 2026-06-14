"""Reference concepts for drift direction analysis.

Each concept is a natural-language description of a behavioral pattern.
When embedded, these become reference vectors in the same 1536-d space.
Drift vectors are projected onto concepts to answer: "what is this entity BECOMING?"
"""
import numpy as np
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ReferenceConcept",
    "THREAT_CONCEPTS",
    "BENIGN_CONCEPTS",
    "ALL_CONCEPTS",
    "ConceptLibrary",
]


@dataclass
class ReferenceConcept:
    name: str
    category: str  # "threat" or "benign"
    description: str  # natural language description (embedded to create vector)
    mitre_techniques: list[str]  # associated MITRE ATT&CK IDs
    severity: str  # "critical", "high", "medium", "low"


# ---------------------------------------------------------------------------
# Threat concepts (drift toward these = alert)
# ---------------------------------------------------------------------------

THREAT_CONCEPTS = [
    ReferenceConcept(
        name="compromised_endpoint",
        category="threat",
        description=(
            "A device showing signs of compromise: unusual process execution "
            "including encoded PowerShell commands, connection to known C2 "
            "infrastructure, registry modifications for persistence, and defense "
            "evasion through disabling security tools. Network beaconing at regular "
            "intervals to external IPs not seen before. Behavioral metrics show "
            "endpoint_suspicious_ratio increasing from baseline, endpoint_max_risk "
            "exceeding historical maximum, and new unique processes appearing that "
            "were never seen in the entity's prior behavioral window."
        ),
        mitre_techniques=["T1059", "T1547", "T1562", "T1071"],
        severity="critical",
    ),
    ReferenceConcept(
        name="data_exfiltration",
        category="threat",
        description=(
            "An entity systematically collecting and transferring sensitive data "
            "outside the organization. Large file copies from restricted shares to "
            "staging directories, followed by compression and upload to external "
            "cloud storage or email to personal accounts. Data volume increasing "
            "exponentially over days. Behavioral metrics show file_total_bytes "
            "spiking 5-10x above baseline, file_restricted_ratio and "
            "file_confidential_ratio increasing sharply, file_write_ratio elevated "
            "from staging activity, and net_bytes_out increasing with asymmetric "
            "outbound-heavy traffic patterns."
        ),
        mitre_techniques=["T1005", "T1074", "T1048", "T1567"],
        severity="critical",
    ),
    ReferenceConcept(
        name="privilege_escalation",
        category="threat",
        description=(
            "A user or process progressively gaining higher access levels. Initial "
            "standard access followed by requests for elevated permissions, "
            "exploitation of misconfigurations to access admin functions, or token "
            "manipulation. Access scope expanding from department-level to "
            "organization-wide. Behavioral metrics show auth_unique_dests increasing "
            "as new systems are accessed, auth_methods_used expanding with new "
            "authentication types, and file_restricted_ratio rising as the entity "
            "accesses increasingly classified resources beyond their normal scope."
        ),
        mitre_techniques=["T1078", "T1068", "T1134", "T1548"],
        severity="high",
    ),
    ReferenceConcept(
        name="lateral_movement",
        category="threat",
        description=(
            "An entity moving systematically across the network from system to "
            "system. Authentication to devices outside normal scope, SMB/WinRM/RDP "
            "connections to multiple hosts in sequence, credential reuse across "
            "systems, and accessing administrative shares on remote hosts."
        ),
        mitre_techniques=["T1021", "T1570", "T1550", "T1072"],
        severity="high",
    ),
    ReferenceConcept(
        name="insider_threat_slow",
        category="threat",
        description=(
            "A trusted user whose behavior is gradually shifting toward data theft. "
            "Slowly expanding file access scope, increasing off-hours activity, "
            "accessing documents outside their role, subtle privilege accumulation. "
            "Changes are individually innocuous but directionally concerning when "
            "viewed over months. Behavioral metrics show file_unique_paths gradually "
            "increasing week over week, file_restricted_ratio trending upward from "
            "near-zero, auth_off_hours_ratio creeping higher, and file_total_bytes "
            "growing steadily as data collection expands."
        ),
        mitre_techniques=["T1078", "T1083", "T1005", "T1052"],
        severity="high",
    ),
    ReferenceConcept(
        name="insider_threat_fast",
        category="threat",
        description=(
            "A user rapidly collecting and exfiltrating sensitive data, likely "
            "triggered by imminent termination or grievance. Sudden spike in file "
            "downloads, bulk access to restricted documents, USB device usage, large "
            "email attachments to personal addresses, all within days. Behavioral "
            "metrics show file_total spiking dramatically, file_restricted_ratio "
            "and file_confidential_ratio jumping to high values, file_write_ratio "
            "elevated from local staging, file_total_bytes orders of magnitude above "
            "baseline, and auth_off_hours_ratio suddenly elevated."
        ),
        mitre_techniques=["T1005", "T1052", "T1048", "T1567"],
        severity="critical",
    ),
    ReferenceConcept(
        name="credential_stuffing",
        category="threat",
        description=(
            "Mass authentication attempts against multiple user accounts from "
            "external IPs. High failure rate across many accounts in a short window, "
            "automated patterns with consistent timing, originating from known "
            "proxy/VPN/botnet infrastructure. Some accounts eventually compromised."
        ),
        mitre_techniques=["T1110", "T1078"],
        severity="high",
    ),
    ReferenceConcept(
        name="c2_beacon",
        category="threat",
        description=(
            "A device establishing covert command-and-control communication. Regular "
            "periodic connections to external infrastructure with consistent "
            "intervals (with jitter), small packet sizes, DNS-based or HTTP-based "
            "tunneling, and connections to newly-registered domains or cloud services "
            "not previously seen. Behavioral metrics show dns_unique_domains "
            "increasing with new previously-unseen domains, net_external_ratio "
            "elevated above baseline, net_unique_dsts growing with new external "
            "destinations, and dns_nxdomain_ratio elevated from domain generation "
            "algorithm probing."
        ),
        mitre_techniques=["T1071", "T1573", "T1568", "T1102"],
        severity="critical",
    ),
    ReferenceConcept(
        name="reconnaissance",
        category="threat",
        description=(
            "Systematic discovery and mapping of network resources, user accounts, "
            "and system configurations. Port scanning, LDAP enumeration, share "
            "discovery, account enumeration, and DNS zone transfer attempts. "
            "Methodical progression through network segments."
        ),
        mitre_techniques=["T1046", "T1018", "T1087", "T1135"],
        severity="medium",
    ),
    ReferenceConcept(
        name="supply_chain_compromise",
        category="threat",
        description=(
            "A trusted application exhibiting new suspicious behaviors after an "
            "update. Unexpected network connections to unfamiliar domains, new "
            "process spawning patterns, access to data stores not previously "
            "touched, and subtle changes in API call patterns that deviate from the "
            "application's historical baseline."
        ),
        mitre_techniques=["T1195", "T1059", "T1071"],
        severity="critical",
    ),
    ReferenceConcept(
        name="living_off_the_land",
        category="threat",
        description=(
            "An entity using only built-in operating system tools for malicious "
            "purposes with no malware deployed. Execution of certutil for downloads, "
            "wmic for remote process execution, netsh for port forwarding, schtasks "
            "for persistence, and PowerShell with obfuscated commands. Network "
            "connections to internal admin ports only. Blends with legitimate admin "
            "activity but exhibits systematic progression through network segments "
            "using native tools. Behavioral metrics show endpoint_unique_processes "
            "increasing with new LOLBin usage, endpoint_suspicious_ratio elevated "
            "from tool repurposing, auth_unique_dests expanding across systems, "
            "net_unique_dsts growing with lateral movement, and data_behavior plus "
            "network_footprint drifting simultaneously."
        ),
        mitre_techniques=["T1218", "T1053", "T1059.001", "T1036"],
        severity="critical",
    ),
    ReferenceConcept(
        name="telecom_infrastructure_pivot",
        category="threat",
        description=(
            "An entity targeting telecommunications infrastructure for surveillance. "
            "Access to call detail record databases, CDR metadata harvesting, "
            "lawful intercept system manipulation, router and switch configuration "
            "access, and cross-segment network flows to restricted management zones. "
            "Behavioral metrics show file_total and file_total_bytes increasing "
            "dramatically from CDR bulk reads, file_restricted_ratio spiking from "
            "classified telecom database access, net_unique_dsts expanding across "
            "restricted network segments, auth_unique_dests increasing as new "
            "infrastructure systems are accessed, and auth_off_hours_ratio elevated "
            "from covert off-hours operations."
        ),
        mitre_techniques=["T1557", "T1040", "T1005", "T1556"],
        severity="critical",
    ),
    ReferenceConcept(
        name="dns_tunneling_exfil",
        category="threat",
        description=(
            "An entity using DNS queries as a covert data exfiltration channel. "
            "High-entropy subdomain labels encoding stolen data, elevated TXT and "
            "MX record queries to attacker-controlled domains, persistent low-"
            "throughput data channel disguised as legitimate DNS resolution. "
            "Behavioral metrics show dns_unique_domains increasing significantly "
            "with newly-seen tunnel domains, dns_nxdomain_ratio elevated from "
            "probing queries, net_bytes_out showing persistent low-volume outbound "
            "traffic, and net_external_ratio increasing with external tunnel "
            "communication."
        ),
        mitre_techniques=["T1071.004", "T1048.003", "T1041"],
        severity="critical",
    ),
    ReferenceConcept(
        name="credential_harvesting_slow",
        category="threat",
        description=(
            "An entity systematically collecting credentials through native tools "
            "over an extended campaign. LSASS memory access, SAM database dumps via "
            "reg.exe, Kerberoasting service ticket requests, and gradual credential "
            "accumulation distinct from brute-force attacks. Behavioral metrics show "
            "auth_methods_used expanding with new authentication protocols, "
            "auth_fail_rate showing periodic spikes from credential testing, "
            "auth_unique_dests increasing as harvested credentials are validated "
            "across systems, and endpoint_suspicious_ratio elevated from credential "
            "tool execution."
        ),
        mitre_techniques=["T1003", "T1558", "T1110.002", "T1555"],
        severity="high",
    ),
]

# ---------------------------------------------------------------------------
# Benign concepts (drift toward these = suppress alert)
# ---------------------------------------------------------------------------

BENIGN_CONCEPTS = [
    ReferenceConcept(
        name="normal_role_change",
        category="benign",
        description=(
            "A user whose behavior is shifting due to legitimate organizational "
            "change. New application access corresponding to role transfer, "
            "different work hours matching new team timezone, new peer group "
            "communication patterns. Changes align with HR records of role change "
            "or promotion."
        ),
        mitre_techniques=[],
        severity="low",
    ),
    ReferenceConcept(
        name="seasonal_variation",
        category="benign",
        description=(
            "Entity behavior fluctuating with business cycles. End-of-quarter "
            "spikes in finance system usage, annual audit-driven access pattern "
            "changes, holiday-period reduced activity, or project-deadline-driven "
            "temporary increases in off-hours work."
        ),
        mitre_techniques=[],
        severity="low",
    ),
]

ALL_CONCEPTS = THREAT_CONCEPTS + BENIGN_CONCEPTS


class ConceptLibrary:
    """Manages reference concepts and their embeddings.

    Usage:
        lib = ConceptLibrary(embedder=my_embedder)
        lib.embed_concepts()  # generates vectors from descriptions
        lib.save()            # persist to disk

        # Later:
        lib = ConceptLibrary()
        lib.load()            # load from disk (no embedder needed)
        vectors = lib.all_threat_vectors()
    """

    def __init__(self, embedder=None):
        self.concepts = ALL_CONCEPTS
        self._embeddings: dict[str, np.ndarray] = {}
        self._embedder = embedder

    def embed_concepts(self):
        """Embed all concept descriptions to create reference vectors.

        Requires an Embedder instance.
        """
        if self._embedder is None:
            raise RuntimeError(
                "No embedder provided. Pass an embedder to ConceptLibrary() "
                "or use load() to restore pre-computed embeddings."
            )

        descriptions = [c.description for c in self.concepts]
        vectors = self._embedder.embed_batch(descriptions)

        for concept, vector in zip(self.concepts, vectors):
            self._embeddings[concept.name] = vector

    def get_vector(self, concept_name: str) -> np.ndarray:
        """Get the embedding vector for a concept.

        Raises:
            KeyError: if concept has not been embedded or loaded
        """
        if concept_name not in self._embeddings:
            raise KeyError(
                f"No embedding for concept '{concept_name}'. "
                f"Call embed_concepts() or load() first."
            )
        return self._embeddings[concept_name]

    def all_threat_vectors(self) -> dict[str, np.ndarray]:
        """Return all threat concept name->vector pairs."""
        return {
            c.name: self._embeddings[c.name]
            for c in THREAT_CONCEPTS
            if c.name in self._embeddings
        }

    def all_benign_vectors(self) -> dict[str, np.ndarray]:
        """Return all benign concept name->vector pairs."""
        return {
            c.name: self._embeddings[c.name]
            for c in BENIGN_CONCEPTS
            if c.name in self._embeddings
        }

    def get_concept(self, name: str) -> ReferenceConcept:
        """Look up concept metadata by name."""
        for c in self.concepts:
            if c.name == name:
                return c
        raise KeyError(f"Unknown concept: '{name}'")

    def filter_concepts(self, concept_names: list[str]) -> "ConceptLibrary":
        """Return a new ConceptLibrary containing only the named concepts.

        Used for zone-specific concept filtering so each behavioral zone
        is only compared against semantically relevant concepts.
        """
        filtered = ConceptLibrary.__new__(ConceptLibrary)
        filtered.concepts = [c for c in self.concepts if c.name in concept_names]
        filtered._embeddings = {
            k: v for k, v in self._embeddings.items() if k in concept_names
        }
        filtered._embedder = self._embedder
        return filtered

    def save(self, path: str = "data/concept_embeddings.npz"):
        """Persist concept embeddings to disk."""
        save_path = Path(path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(str(save_path), **self._embeddings)

    def load(self, path: str = "data/concept_embeddings.npz"):
        """Load persisted concept embeddings from disk.

        Raises:
            FileNotFoundError: if the embeddings file does not exist
        """
        load_path = Path(path)
        if not load_path.exists():
            raise FileNotFoundError(
                f"Concept embeddings not found at '{load_path}'. "
                f"Run embed_concepts() + save() first."
            )
        data = np.load(str(load_path))
        self._embeddings = {key: data[key] for key in data.files}
