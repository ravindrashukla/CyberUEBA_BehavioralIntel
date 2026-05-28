# ACECARD Three-Tier Detection Logic

## Internal Technical Reference — Detection Architecture, Algorithms, and Results

**Date**: May 2026
**Version**: 1.0 — Post-dampened attack calibration
**Dataset**: 250 users, 133 days, 3.58M events, 4 embedded attack campaigns

---

## 1. Overview

ACECARD uses a three-tier detection architecture. Each tier adds analytical
capability that the previous tier cannot replicate:

| Tier | Approach | Input Representation | What It Can Tell You |
|------|----------|----------------------|----------------------|
| 1 | Traditional ML | 23 scalar features per user per week | "This user is anomalous" |
| 2 | ACECARD Basic | 1536-d composite embedding (5 signals averaged) | "This user is drifting" + magnitude CUSUM |
| 3 | Digital Entity | 5 zone embeddings × 4 contexts × velocity vectors × relationship vectors | "Identity STABLE, data_behavior DRIFTING toward insider_threat" |

---

## 2. Feature Engineering (Shared Across All Tiers)

All tiers consume the same 23 scalar features, engineered weekly from raw
log CSVs (auth, file_access, endpoint, network, dns).

### 2.1 Feature List

| Category | Features | Source Logs |
|----------|----------|-------------|
| Authentication | `auth_total`, `auth_fail_rate`, `auth_off_hours_ratio`, `auth_unique_sources`, `auth_unique_dests`, `auth_methods_used` | auth.csv |
| File Access | `file_total`, `file_restricted_ratio`, `file_confidential_ratio`, `file_write_ratio`, `file_unique_paths`, `file_total_bytes` | file_access.csv |
| Network | `net_bytes_out`, `net_unique_dsts`, `net_external_ratio` | network.csv |
| DNS | `dns_unique_domains`, `dns_nxdomain_ratio` | dns.csv |
| Endpoint | `endpoint_total`, `endpoint_suspicious_ratio`, `endpoint_max_risk`, `endpoint_mean_risk`, `endpoint_unique_processes` | endpoint.csv |

### 2.2 Temporal Structure

- **19 weeks** of data (133 days, Jan 1 – May 13 2025)
- **Baseline period**: Weeks 0–8 (training/reference)
- **Monitoring period**: Weeks 9–18 (detection/test)
- Feature vectors: 250 users × 19 weeks = 4,750 total

---

## 3. Tier 1: Traditional Anomaly Detection

Six statistical/ML algorithms operating on the 23 scalar features.

### 3.1 Isolation Forest

- **Algorithm**: Ensemble of random trees. Anomalies require fewer random
  splits to isolate, yielding shorter average path lengths.
- **Training**: `fit()` on baseline weeks (0–8) mean-aggregated features.
  `predict()` on monitoring weeks (9–18) mean-aggregated features.
- **Threshold**: Sklearn default contamination. Outlier = predicted label -1.
- **Strengths**: Good at detecting multivariate outliers without assumptions
  about feature distributions. Catches sudden changes in multiple features.
- **Weaknesses**: Cannot detect gradual drift when each individual week looks
  normal. No directional information — "anomalous" but not "how" or "toward what."

### 3.2 One-Class SVM

- **Algorithm**: Fits a hypersphere around baseline data in kernel space.
  Points outside the boundary are anomalous.
- **Training**: `fit()` on baseline weeks, `predict()` on monitoring weeks.
- **Kernel**: RBF (default).
- **Strengths**: Theoretically sound for novelty detection.
- **Weaknesses**: Highly sensitive to kernel/nu parameters. In our tests,
  produces 30.8% FP — nearly 1/3 of all users flagged.

### 3.3 Local Outlier Factor (LOF)

- **Algorithm**: Density-based. Compares the local density of a point to its
  neighbors. Points with substantially lower density are outliers.
- **Training**: Novelty mode — fit on baseline, predict on monitoring.
- **Threshold**: Default contamination.
- **Strengths**: Catches local anomalies that global methods miss. Our best
  Tier 1 performer at 3.3% FP.
- **Weaknesses**: Same as IForest — no direction or zone-level insight.

### 3.4 Z-Score Threshold

- **Algorithm**: For each user, compute mean features during monitoring period.
  Flag if any feature exceeds |z| > 3 relative to population mean/std.
- **Strengths**: Simple, interpretable, catches individual extreme features.
- **Weaknesses**: Only catches features that are individually extreme. A user
  with 5 features each at z=2.5 (collectively very anomalous) would be missed.

### 3.5 Temporal Z-Score

- **Algorithm**: Compare each user's monitoring-period mean to their own
  baseline-period mean. Flag if change exceeds threshold.
- **Strengths**: Detects change relative to user's own history.
- **Weaknesses**: In practice, 88.6% FP — nearly useless because normal
  weekly variation triggers it for most users.

### 3.6 Feature Trajectory CUSUM

- **Algorithm**: CUSUM (Cumulative Sum) on scalar feature trajectories.
  Accumulates small deviations from baseline mean. Detects slow drift
  that individual-week thresholds miss.
- **Top 10% rule**: Flag users with CUSUM score ≥ 90th percentile.
- **Strengths**: Designed for slow drift detection.
- **Weaknesses**: Operates on scalar features — cannot detect drift
  direction or zone-specific patterns.

### 3.7 Tier 1 Results (Dampened Attacks)

| Method | USR-156 (Insider) | USR-234 (APT) | USR-042 (Volt) | USR-118 (Salt) | FP Rate |
|--------|:-:|:-:|:-:|:-:|------:|
| LOF | DET | — | DET | DET | 3.3% |
| Z-Score | DET | DET | DET | DET | 4.9% |
| IForest | DET | — | DET | DET | 7.3% |
| OCSVM | DET | DET | DET | DET | 29.7% |
| Temporal Z | DET | DET | DET | DET | 88.6% |
| Feat CUSUM | — | — | DET | — | 9.8% |

**Key finding**: Z-Score detects all 4 attacks at 4.9% FP. Traditional
methods are effective because attacks still produce detectable scalar
feature anomalies, even after dampening. However, they provide no
explanatory power — they say "anomalous" but not "insider vs. APT."

---

## 4. Tier 2: ACECARD Basic (Embedding Drift)

Converts scalar features to text, embeds via OpenAI text-embedding-3-small
(1536-d), then measures drift between baseline and monitoring periods.

### 4.1 Text Serialization

Each user-week is serialized into 5 signal texts:

```
Auth:   "User USR-156 auth: 320 events, 0.03 fail rate, 0.15 off-hours, 4 sources, 8 destinations"
Priv:   "User USR-156 privilege: 3 methods, 4.2 max risk"
Data:   "User USR-156 files: 180 accesses, 0.08 restricted, 0.04 confidential, 45 paths, 500000 bytes"
Net:    "User USR-156 network: 120000 bytes out, 12 destinations"
Endpt:  "User USR-156 endpoint: 95 events, 0.003 suspicious, 14 processes"
```

### 4.2 Composition

5 signal embeddings → weighted average → 1536-d composite:

```python
composite = compose(signals, "user")
# weights: auth=0.25, privilege=0.15, data_access=0.25, network=0.20, communication=0.15
```

### 4.3 Magnitude CUSUM

CUSUM on cosine distances between consecutive weekly composites. Accumulates
small drift magnitudes over time.

**Result**: 250/250 detections — all users flagged (too sensitive).

### 4.4 Direction Detection (Concept Alignment)

Drift vector (baseline → recent) projected onto 12 reference concept
embeddings (10 threat, 2 benign) via cosine similarity.

**Reference concepts**: compromised_endpoint, data_exfiltration,
privilege_escalation, lateral_movement, c2_beacon, insider_threat_slow,
insider_threat_fast, reconnaissance, credential_stuffing,
supply_chain_compromise, seasonal_variation, normal_role_change.

**Result**: 0/4 attack users detected. ACECARD Direction is broken with
real embeddings because feature-level text ("User USR-234 files: 123
accesses, 0.05 restricted...") and threat concept text ("data exfiltration:
systematically collecting and transferring sensitive data...") occupy
different semantic neighborhoods in the 1536-d space. The embedder
produces high-quality vectors for each, but the semantic distance between
numeric feature descriptions and behavioral narrative descriptions is too
large for meaningful cosine projection.

### 4.5 Tier 2 Results

| Method | USR-156 | USR-234 | USR-042 | USR-118 | FP Rate |
|--------|:-:|:-:|:-:|:-:|------:|
| Magnitude CUSUM | DET | DET | DET | DET | 100% |
| Direction | — | — | — | — | 8.5% |
| Combined | DET | — | DET | DET | 15.4% |

---

## 5. Tier 3: Digital Entity Detection

The core innovation. Instead of one composite embedding per entity, Tier 3
builds a multi-dimensional behavioral representation with 5 independent zone
embeddings, 4 investigation contexts, temporal velocity vectors, and
entity-pair relationship embeddings.

### 5.1 Hierarchical Zone Embeddings

Each user gets 5 independent zone embeddings per week:

| Zone | Features | What It Captures |
|------|----------|-----------------|
| `identity` | role, department, clearance, tenure, user_type | Role/org position (should be static) |
| `access_pattern` | auth_total, auth_fail_rate, auth_off_hours_ratio, auth_unique_sources/dests, auth_methods | Authentication behavior |
| `data_behavior` | file_total, file_restricted/confidential_ratio, file_write_ratio, file_unique_paths, file_total_bytes | Data access patterns |
| `network_footprint` | net_bytes_out, net_unique_dsts, net_external_ratio, dns_unique_domains, dns_nxdomain_ratio | Network/DNS behavior |
| `risk_posture` | endpoint_suspicious_ratio, endpoint_max/mean_risk, endpoint_unique_processes, endpoint_total | Endpoint risk indicators |

**Interpretive serialization**: Instead of flat numeric text, zone texts use
behavioral language with z-score assessments relative to population and
user's own baseline:

- Normal (|z| < 1.5): `"Analyst USR-042 in IT: network activity within normal parameters. Outbound 85000 bytes, external ratio 0.032, all unremarkable."`
- Elevated (1.5 < |z| < 2.5): `"Analyst USR-042 in IT network behavior: External ratio elevated at 0.089. Outbound traffic above average: 240000 bytes."`
- Critical (|z| > 2.5): `"CRITICAL ANOMALY in network behavior for Analyst USR-042 in IT. External connection ratio at EXTREME level: 0.156 (3.2 standard deviations above population, 2.8x baseline). Pattern strongly consistent with command and control beacon activity..."`

This bridges the semantic gap between feature text and threat concepts in the
embedding space.

### 5.2 Context-Adaptive Attention Composition

Zone embeddings are composed into a single 1536-d vector via softmax-weighted
attention, with weights that change based on investigation context:

| Context | identity | access | data | network | risk |
|---------|:--------:|:------:|:----:|:-------:|:----:|
| `normal_ops` | 0.20 | 0.20 | 0.20 | 0.20 | 0.20 |
| `insider_investigation` | 0.10 | 0.15 | **0.40** | 0.15 | 0.20 |
| `apt_hunt` | 0.05 | 0.15 | 0.10 | **0.40** | 0.30 |
| `privilege_audit` | 0.10 | 0.25 | 0.10 | 0.15 | **0.40** |

**Why this matters**: Under `normal_ops`, a C2 beacon signal in
network_footprint gets diluted by 4 normal zones (only 20% weight).
Under `apt_hunt`, network gets 40% weight and identity only 5% — the
C2 signal is amplified 4× relative to the stable identity zone.

```python
composite = compose_zones(zone_embeddings, context="apt_hunt", entity_type="user")
# Softmax over attention weights × zone vectors
```

### 5.3 Temporal Trajectory Analysis

For each entity, 19 weekly snapshots form a trajectory in 1536-d space.
Six trajectory features are computed:

| Feature | Definition | What It Detects |
|---------|-----------|----------------|
| `velocity_magnitude` | Mean L2 norm of consecutive week diffs | Speed of change |
| `acceleration` | Mean change in velocity over steps | Speeding up or slowing down |
| `stability` | Mean cosine similarity of consecutive snapshots | How consistent behavior is week-to-week |
| `regime_shifts` | Fraction of consecutive pairs with cosine < 0.7 | Fundamental behavioral phase changes |
| `trend_consistency` | Mean pairwise cosine of step direction vectors | Is entity drifting in a consistent direction? |
| `total_drift` | 1 − cosine_similarity(first_week, last_week) | Total distance traveled in embedding space |

**Velocity vector**: Full 1536-d unit vector pointing from first to last
snapshot. Captures not just HOW MUCH but WHICH DIRECTION the entity drifted.

**Regime detection**:
- `stable`: No regime shifts, low drift
- `drifting`: Total drift > 0.05, stability > 0.7
- `accelerating`: acceleration > 0.01 with consistent trend direction
- `regime_shift`: Any consecutive pair below 0.7 cosine similarity

### 5.4 Relationship Embeddings (Hadamard Product)

Entity-pair interaction patterns become first-class vectors:

```python
UserDevice(User, Device) = L2_normalize(user_composite ⊙ device_composite)
```

Element-wise (Hadamard) product captures HOW a user interacts with their
device. If a C2 beacon changes the user's device interaction pattern, the
relationship vector drifts even if neither entity individually changes
enough to trigger detection.

```python
def hadamard(a, b):
    product = a * b  # element-wise
    return product / ||product||  # L2 normalize
```

Drift in relationship embedding: cosine distance between first and last
week's UserDevice vector.

### 5.5 Per-Zone Drift Analysis with Concept Alignment

For each zone independently, compute the drift vector from first to last
week's zone embedding, then project onto reference concepts:

```python
zone_drift_vec = zone_new - zone_old  # 1536-d
zone_drift_vec /= ||zone_drift_vec||  # normalize

for concept in concepts:
    alignment = cosine_similarity(zone_drift_vec, concept.vector)
    if alignment > threshold:
        flag as threat-aligned
```

**Zone divergence detection**: Flag when identity zone is STABLE (drift < 0.02)
but a behavioral zone is DRIFTING (drift > 0.05). This is the signature
pattern of attacks — the person hasn't changed, but their behavior has.

Example output:
```
USR-156: identity STABLE (0.000), data_behavior DRIFTING (0.328) toward insider_threat_fast
USR-234: identity STABLE (0.000), data_behavior DRIFTING (0.168) + network_footprint DRIFTING (0.166)
USR-042: identity STABLE (0.000), network_footprint DRIFTING (0.201)
```

---

## 6. Tier 3 Detection Methods (9 Total)

### 6.1 Velocity/Acceleration Detection

**Logic**: Rank-normalize velocity_magnitude, acceleration, and total_drift.
Composite score = 0.4×velocity + 0.3×acceleration + 0.3×total_drift.
Flag top 10%.

**What it detects**: Entities whose behavioral velocity is accelerating —
increasing speed of change in embedding space.

**Current result**: 0/4 attack users detected (25 FP, 10.2%). With dampened
attacks, attack users don't have significantly higher velocity than
normal population variation.

### 6.2 Regime Shift Detection

**Logic**: Rank entities by stability (lower = more anomalous, inverted rank).
Flag top 10%.

**What it detects**: Fundamental phase changes — consecutive weeks where
behavior changes so much that cosine similarity drops below 0.7.

**Current result**: 2/4 detected (USR-156, USR-118) at 9.3% FP.

### 6.3 Zone Divergence Detection

**Logic**: For each user, compute per-zone total drift. Zone divergence score =
max(behavioral_zone_drifts) − identity_drift. Flag top 10%.

When concept library is available, also runs concept-aligned analysis:
each zone's drift vector is projected onto reference concepts to determine
what the zone is drifting TOWARD.

**What it detects**: Users whose identity is stable but a behavioral zone
is changing — the canonical attack signature.

**Current result**: 1/4 detected (USR-156 via concept-confirmed divergence)
at 9.8% FP. USR-234, USR-042, USR-118 have zone divergence but concept
alignment fails (aligns with "seasonal_variation" not threat concepts).

### 6.4 Relationship Drift Detection

**Logic**: Cosine distance between first and last UserDevice Hadamard vectors.
Flag top 10%.

**What it detects**: Changes in how a user interacts with their device,
even when neither entity individually drifts.

**Current result**: 0/4 detected at 10.2% FP. Attack user relationship
drifts (0.007–0.010) don't significantly exceed population variation.

### 6.5 Contextual (Multi-Context) Detection

**Logic**: For each of 4 contexts, compute weekly net threat alignment:
```
net_threat = max(cosine(drift_vec, threat_concepts)) - max(cosine(drift_vec, benign_concepts))
```
Count weeks where net_threat > 0.05. Consistency = threat_weeks / total_weeks.
Best consistency across all contexts. Flag top 10%.

**What it detects**: Sustained threat-aligned drift under any investigation
lens. APT should emerge under `apt_hunt`, insider under `insider_investigation`.

**Current result**: 0/4 detected at 11.8% FP. The concept alignment gap
(feature text ≠ concept text semantics) prevents meaningful weekly threat
scores.

### 6.6 Cross-Entity Correlation

**Logic**: Cluster users by similarity of their relationship drift vectors
using cosine similarity threshold (0.5) and minimum cluster size (3).
Flag users in any cluster.

**What it detects**: Coordinated attacks — multiple users drifting in the
same direction simultaneously (e.g., a worm spreading).

**Current result**: 54/250 flagged (21.6%). High FP because normal users
cluster by department patterns.

### 6.7 Embedding CUSUM

**Logic**: For each user, compute cosine distance of each week's composite
from baseline (mean of weeks 1–4). Apply CUSUM to the distance series.
Score = 0.6×max_cusum + 0.4×final_cusum. Flag top 10%.

**What it detects**: Cumulative small-but-consistent drift away from
baseline in embedding space. Different from feature CUSUM because it
operates on the full 1536-d vector, not individual scalars.

**Current result**: 0/4 detected at 10.2% FP.

### 6.8 Per-Zone Threat Direction

**Logic**: For each behavioral zone independently (data, network, access,
risk), compute drift from 4-week baseline, project onto relevant threat
concepts with 1.5× weight for zone-relevant concepts. Count threat-positive
weeks. Best zone score selected.

Zone-threat relevance map:
- data_behavior → data_exfiltration, insider_threat_slow, insider_threat_fast
- network_footprint → c2_beacon, lateral_movement, data_exfiltration
- access_pattern → credential_stuffing, reconnaissance, privilege_escalation
- risk_posture → compromised_endpoint, privilege_escalation, supply_chain_compromise

**Current result**: 3/4 detected (USR-156, USR-234, USR-118) but 77.2% FP.
Detects correctly but threshold is too loose — most normal users also show
some zone-level threat alignment by chance.

### 6.9 Behavioral Progression

**Logic**: For each zone, compute per-week threat alignment scores over
time. Apply Kendall tau correlation to check for monotonic increasing
trend. Score = 0.6×best_tau + 0.4×late_threat_mean. Flag top 10%.

**What it detects**: Progressive escalation — threat alignment scores
increasing over time, not just elevated at one point. Attack users show
steady ratcheting up; normal users show random fluctuation.

**Current result**: 3/4 detected (USR-156, USR-234, USR-118) at 8.9% FP.
Most promising Tier 3 method. Misses USR-042 (Volt Typhoon) because LOTL
tools create intermittent not progressively increasing signals.

---

## 7. Tier 3 Combined Scoring

### 7.1 Core Methods (Used for Corroboration Count)

Six methods with ~10% FP each are designated "core":
1. Velocity/Acceleration
2. Zone Divergence
3. Contextual
4. Embedding CUSUM
5. Behavioral Progression
6. Regime Shift

### 7.2 Composite Score

Geometric mean of rank-normalized core method scores:

```python
composite = exp(
    0.05 × log(velocity_pct)      # low weight — poor discriminator
  + 0.20 × log(zone_div_pct)      # medium — catches insider
  + 0.15 × log(contextual_pct)    # medium
  + 0.30 × log(cusum_pct)         # high — catches APT
  + 0.30 × log(progression_pct)   # high — best discriminator
)

final = 0.7 × rank_normalize(composite) + 0.3 × rank_normalize(breadth)
```

### 7.3 Combined Detection Rule

```
DETECTED if:
    (core_methods_detected >= 2)           # multi-method corroboration
    OR (zone_divergence_detected AND concept_threat_confidence > 0.10)  # concept-confirmed zone drift
    OR (composite_score >= 92nd percentile)  # top 8% composite
```

### 7.4 Combined Results

| Method | USR-156 | USR-234 | USR-042 | USR-118 | FP Rate |
|--------|:-:|:-:|:-:|:-:|------:|
| T3 Combined | DET | — | — | DET | 15.9% |

**Why USR-234 and USR-042 are missed**:
- USR-234: Only 1/6 core methods corroborate (regime shift). Zone divergence
  exists (data=0.168, network=0.166) but concept alignment maps to
  "seasonal_variation" (benign) not threat concepts.
- USR-042: 0/6 core methods corroborate. Network drift exists (0.201) but
  again aligns with "seasonal_variation" not threats.

---

## 8. Attack Campaign Details

### 8.1 USR-156 — Insider Threat (8-month)

**Scenario**: Gradual escalation of restricted/confidential file access,
off-hours activity, increasing data volume.

**Tier 3 zone signal**:
- `data_behavior` drift = **0.328** (strongest signal across all attacks)
- Concept alignment: `insider_threat_fast` with confidence **0.331** (THREAT)
- Zone divergence: identity STABLE (0.000), data_behavior DRIFTING (0.328)
- Behavioral progression tau = 0.415 (strong monotonic increase)

**Why Tier 3 adds value**: Traditional methods detect USR-156 as anomalous,
but Tier 3 tells the analyst "data access is the changing behavior, and
it's consistent with insider threat" — directly actionable.

### 8.2 USR-234 — Slow APT (180-day)

**Scenario**: C2 beacon (2-3/day, 25% skip days), DGA DNS queries,
data staging every ~17 days from progressively sensitive directories.

**Tier 3 zone signal**:
- `data_behavior` drift = 0.168, `network_footprint` drift = 0.166
- Both drifts are real and roughly equal (dual-zone attack)
- Concept alignment fails — mapped to "seasonal_variation" not threats
- Behavioral progression tau = 0.333 (moderate increasing trend)

**Why currently missed by T3 Combined**: Concept alignment gap. The drift
is detected quantitatively, but the direction can't be confirmed as
threat-aligned due to the semantic gap between feature text and concept
text in embedding space.

### 8.3 USR-042 — Volt Typhoon LOTL (115-day)

**Scenario**: Living-off-the-land using legitimate admin tools (PowerShell,
WMIC, certutil). Lateral movement via RDP/SMB/WMI. Minimal external traffic.

**Tier 3 zone signal**:
- `network_footprint` drift = **0.201** (internal lateral movement)
- `access_pattern` drift = 0.015 (subtle credential changes)
- Concept alignment: "seasonal_variation" (0.213) — wrong direction
- Behavioral progression tau = 0.228 (weak trend — intermittent activity)

**Why hardest to detect**: LOTL attacks use legitimate tools, producing
features within normal admin ranges. The signal is in the COMBINATION
of access_pattern + network_footprint changing together, but per-zone
concept alignment is insufficient.

### 8.4 USR-118 — Salt Typhoon Telecom (100-day)

**Scenario**: Edge device compromise, cross-segment traffic to restricted
zones, CDR database access, DNS tunneling, data staging/exfiltration.

**Tier 3 zone signal**:
- Very low zone drifts: data=0.007, network=0.006
- But concept alignment on data_behavior shows `privilege_escalation` (0.108)
- Regime shift and behavioral progression detect via temporal pattern
- Zone threat direction detects via risk_posture=1.000

**Why zone drifts are low**: Attack dampening reduced Salt Typhoon
daily probabilities significantly. The attack injects events on
~25-50% of active days, and the low event counts get averaged out
over weekly aggregation.

---

## 9. The Concept Alignment Gap

The central technical challenge: why ACECARD Direction (Tier 2) and several
Tier 3 methods produce 0 true positives despite having the right architecture.

### 9.1 The Problem

Feature-level text:
```
"User USR-234 data: file_accesses=45, restricted_ratio=0.0500,
confidential_ratio=0.0200, write_ratio=0.0100, unique_paths=22, bytes=340000"
```

Threat concept text:
```
"An entity systematically collecting and transferring sensitive data
outside the organization. Large file copies from restricted shares to
staging directories, followed by compression and upload to external
cloud storage. Data volume increasing exponentially over days."
```

These produce high-quality 1536-d vectors, but the vectors occupy different
semantic neighborhoods. The feature text is a structured data record; the
concept text is a behavioral narrative. Cosine similarity between the drift
vector (difference of two feature-text embeddings) and the concept vector
is near zero because the embedding model organizes them by text style,
not behavioral semantics.

### 9.2 Interpretive Serialization (Partial Fix)

Tier 3's `serialize_zone_interpretive()` bridges this gap by producing
behavioral narrative text from features:

```
"CRITICAL ANOMALY in data access for Analyst USR-156 in Finance.
Restricted file access at EXTREME level: ratio 0.0832 (3.1 standard
deviations above population, 2.4x baseline). This user is accessing
classified and restricted materials at a rate far exceeding normal
organizational patterns. Pattern strongly consistent with active data
exfiltration, insider threat data staging."
```

This text lives in the same semantic neighborhood as the threat concepts
because it uses the same behavioral vocabulary. The zone drift vector
between a normal-period text and this critical-period text points
TOWARD the concept vectors.

### 9.3 Where It Still Fails

For USR-234 (APT) and USR-042 (Volt Typhoon), features are elevated
but within 1-2σ of population (by design — dampened attacks). The
interpretive serializer classifies them as "normal" or "slightly elevated"
and produces unremarkable text. The zone drift vector between two
unremarkable texts doesn't align with threat concepts.

The fix requires either:
1. Lower the z-score thresholds for interpretive language (risk: increase FP)
2. Use relative-to-baseline assessment (detect 1.5x increase even if
   within population range)
3. Abandon concept alignment for direction detection and rely on
   zone drift magnitude + behavioral progression instead

---

## 10. Per-Attack Detection Matrix

### 10.1 Full Results Table

| Method | USR-156 | USR-234 | USR-042 | USR-118 | TP | FP | FP% |
|--------|:-:|:-:|:-:|:-:|:--:|:--:|-----:|
| **Tier 1** | | | | | | | |
| LOF | ✓ | — | ✓ | ✓ | 3 | 8 | 3.3% |
| Z-Score | ✓ | ✓ | ✓ | ✓ | 4 | 12 | 4.9% |
| IForest | ✓ | — | ✓ | ✓ | 3 | 18 | 7.3% |
| OCSVM | ✓ | ✓ | ✓ | ✓ | 4 | 73 | 29.7% |
| **Tier 2** | | | | | | | |
| ACECARD Dir | — | — | — | — | 0 | 21 | 8.5% |
| IForest+ACECARD | ✓ | — | ✓ | ✓ | 3 | 38 | 15.4% |
| **Tier 3** | | | | | | | |
| Zone Divergence | ✓ | — | — | — | 1 | 24 | 9.8% |
| Regime Shift | ✓ | — | — | ✓ | 2 | 23 | 9.3% |
| Beh Progression | ✓ | ✓ | — | ✓ | 3 | 22 | 8.9% |
| Zone Threat Dir | ✓ | ✓ | — | ✓ | 3 | 190 | 77.2% |
| T3 Combined | ✓ | — | — | ✓ | 2 | 39 | 15.9% |

### 10.2 Tier 3 Qualitative Analysis (Unique to Tier 3)

Even where Tier 3 doesn't beat Tier 1 quantitatively, it produces
analysis that Tier 1 cannot:

**USR-156**: "identity STABLE (0.000), data_behavior DRIFTING (0.328)
toward insider_threat_fast (confidence=0.331). Access_pattern STABLE,
risk_posture STABLE."
→ Analyst knows immediately: investigate data access, not auth or network.

**USR-234**: "data_behavior DRIFTING (0.168) + network_footprint
DRIFTING (0.166). Both zones changing while identity and risk STABLE."
→ Analyst knows: dual-channel attack affecting data and network together.

**USR-042**: "network_footprint DRIFTING (0.201) while identity,
data_behavior, risk_posture all STABLE."
→ Analyst knows: network-centric attack, check for lateral movement.

**USR-118**: "Regime shift detected. Behavioral progression increasing
in data_behavior zone (tau=0.368)."
→ Analyst knows: temporal escalation pattern, not static anomaly.

---

## 11. Scoring Pipeline Architecture

```
Raw Log CSVs (auth, file_access, network, dns, endpoint)
    │
    ▼
engineer_weekly_features()
    │   23 features × 250 users × 19 weeks = 4,750 vectors
    │
    ├──▶ Tier 1: 6 traditional ML algorithms
    │       └─ IForest, OCSVM, LOF, Z-Score, Temporal-Z, Feature CUSUM
    │
    ├──▶ Tier 2: ACECARD Basic
    │       ├─ 5 signal texts per user per week → embed → compose
    │       ├─ Magnitude CUSUM on composite drift
    │       └─ Direction: drift_vector projected onto 12 concepts
    │
    └──▶ Tier 3: Digital Entity
            │
            ├─ Pass 1: Serialize 47,500 zone texts
            │     250 users × 19 weeks × 5 user zones
            │     + 250 users × 19 weeks × 5 device zones
            │
            ├─ Pass 2: Batch embed all texts (100/batch via OpenAI API)
            │
            ├─ Pass 3: Assemble 250 CyberEntity objects
            │     Per entity:
            │       • 5 zone embedding series (19 snapshots each)
            │       • 4 contextual composites (one per investigation context)
            │       • Hadamard relationship vector series
            │       • PhaseState (velocity, acceleration, regime)
            │       • Zone trajectory features
            │
            └─ 9 Detection Methods:
                1. Velocity/Acceleration (top 10% composite)
                2. Regime Shift (top 10% instability)
                3. Zone Divergence (top 10% behavioral-identity gap)
                4. Relationship Drift (top 10% Hadamard distance)
                5. Contextual (top 10% best-context threat consistency)
                6. Cross-Entity Correlation (cohort clustering)
                7. Embedding CUSUM (top 10% cumulative drift)
                8. Per-Zone Threat Direction (top 10% zone threat score)
                9. Behavioral Progression (top 10% Kendall tau)
                    │
                    ▼
                Combined: ≥2 core OR concept-confirmed zone div OR top 8%
```

---

## 12. Configuration Parameters

All Tier 3 thresholds are defined in `Tier3Config`:

| Parameter | Default | Used By |
|-----------|---------|---------|
| `acceleration_threshold` | 0.01 | Regime detection (accelerating state) |
| `trend_consistency_min` | 0.5 | Regime detection |
| `regime_shift_threshold` | 0.7 | Consecutive cosine similarity floor |
| `zone_stable_threshold` | 0.02 | Zone divergence (identity stability) |
| `zone_drifting_threshold` | 0.05 | Zone divergence (behavioral drift) |
| `relationship_drift_threshold` | 0.05 | Relationship drift flagging |
| `contextual_threat_threshold` | 0.30 | Multi-context detection |
| `cohort_similarity` | 0.5 | Cross-entity clustering threshold |
| `cohort_min_size` | 3 | Minimum cluster size |
| `threat_consistency_threshold` | 0.40 | ACECARD direction detection |

---

## 13. Known Limitations and Next Steps

### 13.1 Concept Alignment Semantic Gap

**Status**: Partially resolved for extreme anomalies (|z| > 2.5) via
interpretive serialization. Still fails for moderate anomalies (1-2σ).

**Impact**: ACECARD Direction (Tier 2) and Tier 3 contextual/zone threat
methods depend on concept projection. 0 TP for Direction; 77% FP for
Zone Threat Direction.

**Path forward**: Evaluate whether zone drift magnitude + behavioral
progression (no concept alignment required) is sufficient, or whether
concept alignment needs further work.

### 13.2 Top-10% Ranking Floor

**Status**: Most Tier 3 methods flag the top 10% by design. With 250 users,
that's always 25 flagged regardless of whether real anomalies exist.

**Impact**: FP floor is ~10% per method. Cannot go below this without
absolute thresholds.

**Path forward**: Replace percentile-based thresholds with absolute
thresholds calibrated against known-clean populations.

### 13.3 Salt Typhoon Over-Dampening

**Status**: USR-118 zone drifts are 0.006-0.007, nearly invisible.
Detected via temporal pattern (progression, regime shift) not zone drift.

**Path forward**: Slightly increase Salt Typhoon daily probabilities
or event volumes to produce measurable zone-level drift.

### 13.4 Volt Typhoon LOTL Evasion

**Status**: USR-042 is the hardest case. LOTL tools produce features
within normal admin ranges. Network drift (0.201) is real but
concept alignment maps to benign.

**Path forward**: Volt Typhoon detection may require:
- Cross-feature correlation (access_pattern changing simultaneously
  with network_footprint)
- Time-of-day analysis (LOTL tools used at unusual hours)
- Destination diversity analysis (new internal targets each week)

---

## 14. File Reference

| File | Purpose |
|------|---------|
| `models/cyber_entity.py` | CyberEntity, PhaseState, Tier3Config dataclasses |
| `models/hierarchical_zones.py` | Zone definitions, context weights, serialization |
| `models/temporal_trajectory.py` | Velocity vectors, trajectory features, regime detection |
| `models/relationship_embeddings.py` | Hadamard product, relationship drift |
| `embeddings/embedder.py` | OpenAI embedder with disk cache, batch support |
| `embeddings/composer.py` | Weighted composition, cosine similarity, drift vectors |
| `detection/drift_direction.py` | Concept alignment, zone drift analysis |
| `detection/reference_concepts.py` | 12 reference concept definitions |
| `detection/cusum.py` | CUSUM change-point detection |
| `detection/cohort_analysis.py` | Cross-entity clustering |
| `comparison/run_tier3.py` | Full pipeline: feature eng → T1 → T2 → T3 → report |
| `comparison/run_comparison.py` | Tier 1 + Tier 2 pipeline |
| `simulator/attacks/` | 8 attack scenario implementations |
