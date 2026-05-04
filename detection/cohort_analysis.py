"""Cohort analysis: detect co-drifting entity clusters.

Core idea: if multiple entities drift in the same direction at the same time,
they may be part of a coordinated attack (botnet, worm propagation, or
compromised supply-chain update affecting many devices).

Method: compute pairwise cosine similarity of drift vectors within a time window.
Cluster entities whose drift vectors align above a threshold — these form a cohort.
"""
import numpy as np
from dataclasses import dataclass, field
from datetime import date

from embeddings.composer import cosine_similarity, drift_vector, drift_magnitude

__all__ = [
    "CohortMember",
    "Cohort",
    "detect_cohorts",
    "detect_cohorts_from_db",
]


@dataclass
class CohortMember:
    entity_type: str
    entity_id: str
    drift_magnitude: float
    drift_direction: np.ndarray


@dataclass
class Cohort:
    cohort_id: int
    members: list[CohortMember] = field(default_factory=list)
    mean_drift_direction: np.ndarray = field(default_factory=lambda: np.zeros(0))
    mean_drift_magnitude: float = 0.0
    coherence: float = 0.0  # avg pairwise similarity of drift vectors

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def entity_ids(self) -> list[str]:
        return [f"{m.entity_type}:{m.entity_id}" for m in self.members]

    def to_dict(self) -> dict:
        return {
            "cohort_id": self.cohort_id,
            "size": self.size,
            "mean_drift_magnitude": self.mean_drift_magnitude,
            "coherence": self.coherence,
            "members": [
                {
                    "entity_type": m.entity_type,
                    "entity_id": m.entity_id,
                    "drift_magnitude": m.drift_magnitude,
                }
                for m in self.members
            ],
        }


def detect_cohorts(
    entity_drifts: list[CohortMember],
    similarity_threshold: float = 0.5,
    min_cluster_size: int = 3,
) -> list[Cohort]:
    """Detect co-drifting cohorts using greedy agglomerative clustering.

    Args:
        entity_drifts: list of CohortMember with drift vectors
        similarity_threshold: min cosine similarity of drift vectors to be in same cohort
        min_cluster_size: minimum members to report a cohort

    Returns:
        List of Cohort objects with 3+ co-drifting members.
    """
    if len(entity_drifts) < min_cluster_size:
        return []

    # Filter out zero-drift entities
    active = [m for m in entity_drifts if m.drift_magnitude > 0.01]
    if len(active) < min_cluster_size:
        return []

    # Greedy single-linkage clustering on drift direction similarity
    assigned = set()
    cohorts = []
    cohort_id = 0

    for i, anchor in enumerate(active):
        if i in assigned:
            continue

        cluster_indices = [i]
        assigned.add(i)

        for j in range(i + 1, len(active)):
            if j in assigned:
                continue
            sim = cosine_similarity(anchor.drift_direction, active[j].drift_direction)
            if sim >= similarity_threshold:
                cluster_indices.append(j)
                assigned.add(j)

        if len(cluster_indices) >= min_cluster_size:
            members = [active[idx] for idx in cluster_indices]
            directions = np.array([m.drift_direction for m in members])
            mean_dir = directions.mean(axis=0)
            norm = np.linalg.norm(mean_dir)
            if norm > 0:
                mean_dir = mean_dir / norm

            # Compute coherence: average pairwise cosine similarity
            n = len(members)
            pair_sims = []
            for a in range(n):
                for b in range(a + 1, n):
                    pair_sims.append(
                        cosine_similarity(members[a].drift_direction, members[b].drift_direction)
                    )
            coherence = float(np.mean(pair_sims)) if pair_sims else 0.0

            cohort = Cohort(
                cohort_id=cohort_id,
                members=members,
                mean_drift_direction=mean_dir,
                mean_drift_magnitude=float(np.mean([m.drift_magnitude for m in members])),
                coherence=coherence,
            )
            cohorts.append(cohort)
            cohort_id += 1

    cohorts.sort(key=lambda c: c.size, reverse=True)
    return cohorts


def detect_cohorts_from_db(
    entity_type: str = None,
    similarity_threshold: float = 0.5,
    min_cluster_size: int = 3,
) -> list[Cohort]:
    """Run cohort detection on the latest pair of snapshots per entity from the DB.

    Loads the two most recent snapshots per entity, computes drift vectors,
    then clusters by drift direction similarity.

    Args:
        entity_type: filter to specific type (None = all types)
        similarity_threshold: cosine sim threshold for clustering
        min_cluster_size: minimum cohort size to report

    Returns:
        List of detected Cohort objects.
    """
    from services.database import Database

    # Get entities with 2+ snapshots
    type_filter = ""
    params = []
    if entity_type:
        type_filter = "WHERE entity_type = %s"
        params = [entity_type]

    rows = Database.execute(
        f"SELECT entity_type, entity_id, COUNT(*) as cnt "
        f"FROM behavioral_snapshots {type_filter} "
        f"GROUP BY entity_type, entity_id HAVING COUNT(*) >= 2",
        params or None,
    )
    if not rows:
        return []

    # For each entity, get last 2 snapshots and compute drift vector
    entity_drifts = []
    for row in rows:
        etype = row["entity_type"]
        eid = row["entity_id"]
        snaps = Database.execute(
            "SELECT composite FROM behavioral_snapshots "
            "WHERE entity_type = %s AND entity_id = %s AND composite IS NOT NULL "
            "ORDER BY cutoff_date DESC LIMIT 2",
            (etype, eid),
        )
        if not snaps or len(snaps) < 2:
            continue

        # snaps[0] is newest, snaps[1] is second-newest
        def parse_vec(val):
            s = str(val).strip("[]")
            return np.array([float(x) for x in s.split(",")], dtype=np.float32)

        v_new = parse_vec(snaps[0]["composite"])
        v_old = parse_vec(snaps[1]["composite"])

        mag = drift_magnitude(v_old, v_new)
        if mag < 0.01:
            continue

        dvec = drift_vector(v_old, v_new)
        entity_drifts.append(CohortMember(
            entity_type=etype,
            entity_id=eid,
            drift_magnitude=float(mag),
            drift_direction=dvec,
        ))

    return detect_cohorts(entity_drifts, similarity_threshold, min_cluster_size)
