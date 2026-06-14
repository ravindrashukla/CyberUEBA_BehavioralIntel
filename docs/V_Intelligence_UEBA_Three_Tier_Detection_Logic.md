# V-Intelligence UEBA Three-Tier Detection Logic

## Internal Technical Reference — Detection Architecture, Algorithms, and Results

**Date**: May 2026
**Version**: 3.0 — Multi-phase composite scoring (2-of-4 clean) + multi-front threat-profile detector (4-of-4 at 0 FP)
**Dataset**: 250 users, 485 days (70 weeks), 4 embedded attack campaigns

---

## 1. Overview

V-Intelligence UEBA uses a three-tier detection architecture. Each tier adds analytical
capability that the previous tier cannot replicate:

| Tier | Approach | Input Representation | What It Can Tell You |
|------|----------|----------------------|----------------------|
| 1 | Traditional ML | 23 scalar features per user per week | "This user is anomalous" |
| 2 | V-Intelligence UEBA Basic | 1536-d composite embedding (5 signals averaged) | "This user is drifting" + magnitude CUSUM |
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

- **70 weeks** of data (485 days, Jan 1 2025 – Apr 30 2026)
- **Baseline period**: Weeks 0–9 (training/reference)
- **Monitoring period**: Weeks 10–69 (detection/test)
- Feature vectors: 250 users × 70 weeks = 17,500 total

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

## 4. Tier 2: V-Intelligence UEBA Basic (Embedding Drift)

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

**Result**: 0/4 attack users detected. V-Intelligence UEBA Direction is broken with
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

For each entity, 70 weekly snapshots form a trajectory in 1536-d space.
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

**Current result**: 0/4 detected at 10.2% FP as a top-10% flag. Its value is in
EARLINESS, and that value is **attack-dependent, not universal**: embedding CUSUM
surfaces the insider (USR-156) and LOTL (USR-042) drift roughly 30 weeks earlier than
threshold methods, fires LATER than thresholds for the volume-driven Salt Typhoon
(USR-118), and never separates the slow-APT (USR-234). It is a per-attack early-warning
signal, not a stand-alone detector and not attributable as an across-the-board embedding win.

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

## 7. Multi-Phase Composite Scoring (v3.0)

Replaced CUSUM-only and corroboration-based detection with a 5-phase
composite anomaly scoring system that uses group-relative z-scores and
novelty persistence metrics.

### 7.1 Role Group Normalization

Users are grouped by role for peer-relative z-scoring:
- **admin** (44 users): IT Admin, SysAdmin, DBA, Network Engineer, Cloud Architect, DevOps Engineer, SRE
- **security** (27 users): SOC Operator, Security Analyst, CISO
- **developer** (62 users): Software Engineer, Senior Engineer, Staff Engineer, ML Engineer, Data Scientist, QA Engineer, Test Lead
- **business** (81 users): Accountant, Analyst, Account Manager, Financial Analyst, Sales Rep, HR Manager, HR Specialist, Recruiter, General Counsel
- **executive** (36 users): CEO, CFO, COO, CTO, VP Sales

Z-scores are computed using only normal users within each group as the
reference population. This ensures a developer is compared to other
developers, not executives with fundamentally different baselines.

### 7.2 Feature Extraction

Per-user aggregate features from the 70-week trajectory:
- **Per zone** (access_pattern, data_behavior, network_footprint, risk_posture):
  sustained (mean of late half), late_q4 (mean of last quarter), peak, trend
  (last 10 − first 10 weeks), volatility
- **Composite**: sustained, peak
- **Context-specific**: late-stage mean for each of 4 investigation contexts,
  plus max and spread across contexts
- **Relationship**: sustained, peak
- **Zone divergence**: sustained

### 7.3 Five Detection Phases

**Phase 1 — Signal Strength**: Sum of top-3 group-relative z-scores.
Catches users with a few strongly anomalous features.

**Phase 2 — Signal Breadth**: Count of features with z > 1.5.
Catches users anomalous across multiple dimensions simultaneously.

**Phase 3 — Sustained Baseline Deviation**: Sum of top-2 zone-specific
sustained z-scores (late-half drift from self-baseline).
Catches persistent, not transient, anomalies.

**Phase 4 — Context Divergence**: Z-scores on cross-context spread and
maximum context score. When a user scores high under `apt_hunt` but low
under `normal_ops`, the spread is elevated.

**Phase 5 — Novelty Persistence**: Direct numeric features from qualitative
data. Persistent novel external IPs (appearing in 5+ post-baseline weeks)
and novel IP week fraction. This bypasses the embedding layer entirely —
IP addresses are generic tokens to LLMs, so C2 beacons must be detected
through non-embedding features.

### 7.4 Composite Formula

```python
composite = (
    signal_strength × 1.0     # top-3 z-scores
  + breadth_15 × 0.5          # count of features with z > 1.5
  + sustained_signal × 0.3    # top-2 zone sustained z-scores
  + max(ctx_spread_z, 0) × 0.5
  + max(ctx_max_z, 0) × 0.3
  + novelty_score × 1.0       # C2 beacon persistence
)
```

Novelty score computation:
- If novel IP max persistence > 10 weeks: `min(persistence / 5.0, 10.0)`
- If novel IP week fraction > 0.5: add `fraction × 3.0`

### 7.5 Results (250 Users, 90th Percentile Threshold)

| User | Campaign | Rank | Composite | Signal | Breadth | Sustained | Novelty |
|------|----------|:----:|:---------:|:------:|:-------:|:---------:|:-------:|
| USR-118 | Salt Typhoon | #1 | 51.27 | 29.9 | 18 | 9.6 | 2.8 |
| USR-156 | Insider | #2 | 46.24 | 30.0 | 19 | 8.4 | 0.0 |
| USR-234 | Slow APT | #7 | 19.44 | 4.5 | 1 | 1.6 | 13.0 |
| USR-042 | Volt Typhoon | #24 | 13.70 | 6.4 | 11 | 3.8 | 0.0 |

**Clean separation is only 2 of 4.** USR-156 (#2) and USR-118 (#1) rank above
every normal user. USR-234 (#7) and USR-042 (#24) rank BELOW normal users — any
threshold low enough to catch them admits false positives. At the 90th percentile
the composite reaches 4/4 recall only by accepting 21 FP (8.5%). The clean
**4/4-at-0-FP result does NOT belong to composite scoring** — it belongs to the
multi-front threat-profile detector (`threat_profile_detector.py`), which matches
USR-156/234/042/118 against measurable known-bad profiles (C2-beacon, DGA-DNS,
LOTL-process, cohort-rare access, recon-fanout, insider-collection) scored
cohort-relative + raw-event, label-free, with zero false positives.

### 7.6 Threshold Sweep

| Threshold | Percentile | TP/4 | FP | FP% | Precision | Recall |
|:---------:|:----------:|:----:|:--:|:---:|:---------:|:------:|
| 5.53 | 50% | 4/4 | 121 | 49.2% | 3.2% | 100% |
| 8.85 | 75% | 4/4 | 59 | 24.0% | 6.3% | 100% |
| 11.27 | 85% | 4/4 | 34 | 13.8% | 10.5% | 100% |
| 13.49 | 90% | 4/4 | 21 | 8.5% | 16.0% | 100% |
| 14.08 | 92% | 3/4 | 17 | 6.9% | 15.0% | 75% |
| 19.29 | 97% | 3/4 | 5 | 2.0% | 37.5% | 75% |
| 21.28 | 99% | 2/4 | 1 | 0.4% | 66.7% | 50% |

### 7.7 Key Architectural Finding

Embedding models (text-embedding-3-small) treat IP addresses as generic
tokens. The C2 beacon IP (198.51.100.47) was present in qualitative features
throughout USR-234's attack period but produced insufficient embedding drift
because the embedder doesn't distinguish between benign and suspicious IPs.

The fix: compute novelty persistence directly from qualitative strings
before embedding. A novel IP appearing in 60/60 post-baseline weeks is
unambiguously suspicious regardless of what the embedding model produces.
This direct numeric feature boosted USR-234 from rank #99 (invisible) to
rank #7 — but #7 is still BELOW six normal users, so composite scoring does
not cleanly separate USR-234. Clean separation of USR-234 (and USR-042)
comes from the threat-profile detector's raw-event C2-beacon / DGA-DNS and
LOTL-process profiles, not from the embedding composite.

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

The central technical challenge: why V-Intelligence UEBA Direction (Tier 2) and several
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

### 9.3 Resolution: Hybrid Approach (v3.0)

For USR-234 (APT) and USR-042 (Volt Typhoon), features are elevated
but within 1-2σ of population (by design — dampened attacks). The
interpretive serializer classifies them as "normal" or "slightly elevated"
and produces unremarkable text.

**v3.0 solution**: Abandon reliance on concept alignment alone. The multi-phase
composite scorer (Section 7) combines embedding-derived signals (zone drift
z-scores, context divergence) with direct non-embedding features (novelty
persistence). For USR-234, the C2 beacon IP is invisible to embeddings but
trivially detectable as a novel IP persisting for 60/60 weeks. For USR-042,
the combination of multiple elevated-but-not-extreme z-scores across 11
features (breadth) plus sustained zone deviation is sufficient to rank it
at #24/250 (above the 90th percentile threshold)

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
| V-Intelligence UEBA Dir | — | — | — | — | 0 | 21 | 8.5% |
| IForest+V-Intelligence UEBA | ✓ | — | ✓ | ✓ | 3 | 38 | 15.4% |
| **Tier 3** | | | | | | | |
| Zone Divergence | ✓ | — | — | — | 1 | 24 | 9.8% |
| Regime Shift | ✓ | — | — | ✓ | 2 | 23 | 9.3% |
| Beh Progression | ✓ | ✓ | — | ✓ | 3 | 22 | 8.9% |
| Zone Threat Dir | ✓ | ✓ | — | ✓ | 3 | 190 | 77.2% |
| T3 Combined (v1) | ✓ | — | — | ✓ | 2 | 39 | 15.9% |
| Composite (v3.0) — embedding | ✓ (clean) | ✓ (#7, below normals) | ✓ (#24, below normals) | ✓ (clean) | 4 | 21 | 8.5% |
| **Threat-Profile Detector** | **✓** | **✓** | **✓** | **✓** | **4** | **0** | **0%** |

The embedding composite reaches 4/4 only at the 90th-percentile threshold and 8.5% FP,
and cleanly separates just 2 of 4 (USR-156, USR-118); USR-234 and USR-042 sit below
normal users. The **clean 4/4-at-0-FP win is the threat-profile detector**
(`threat_profile_detector.py`), which matches each attacker against a measurable
known-bad profile — C2-beacon, DGA-DNS, LOTL-process, cohort-rare access, recon-fanout,
insider-collection — scored cohort-relative + raw-event, label-free.

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
    │   23 features × 250 users × 70 weeks = 17,500 vectors
    │
    ├──▶ Tier 1: 6 traditional ML algorithms
    │       └─ IForest, OCSVM, LOF, Z-Score, Temporal-Z, Feature CUSUM
    │
    ├──▶ Tier 2: V-Intelligence UEBA Basic
    │       ├─ 5 signal texts per user per week → embed → compose
    │       ├─ Magnitude CUSUM on composite drift
    │       └─ Direction: drift_vector projected onto 12 concepts
    │
    └──▶ Tier 3: Digital Entity
            │
            ├─ Pass 1: Serialize 175,000 zone texts
            │     250 users × 70 weeks × 5 user zones
            │     + 250 users × 70 weeks × 5 device zones
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
            ├─ 9 Individual Detection Methods (velocity, regime, zone div, etc.)
            │
            └─ v3.0 Composite Scorer (replaces combined rule):
                │
                ├─ Phase 1: Signal Strength (top-3 z-scores)
                ├─ Phase 2: Signal Breadth (count z > 1.5)
                ├─ Phase 3: Sustained Deviation (zone z-scores)
                ├─ Phase 4: Context Divergence (cross-context spread)
                └─ Phase 5: Novelty Persistence (novel IP weeks)
                    │
                    ▼
                Composite Score → Percentile Threshold → 4/4 recall at 8.5% FP
                (clean separation only 2 of 4; USR-234/USR-042 below normals)

    Threat-Profile Detector (threat_profile_detector.py):
        Known-bad profiles (C2-beacon, DGA-DNS, LOTL-process, cohort-rare access,
        recon-fanout, insider-collection), cohort-relative + raw-event, label-free
                    │
                    ▼
                4/4 TP at 0 FP  ← the clean detection win
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
| `threat_consistency_threshold` | 0.40 | V-Intelligence UEBA direction detection |

---

## 13. Known Limitations and Next Steps

### 13.1 Concept Alignment Semantic Gap

**Status (v1.0)**: Partially resolved for extreme anomalies (|z| > 2.5) via
interpretive serialization. Still fails for moderate anomalies (1-2σ).

**Resolution (v3.0)**: The multi-phase composite scorer bypasses concept
alignment entirely. Detection uses group-relative z-scores on per-zone
drift features plus novelty persistence — neither requires concept
projection. Result: 4/4 recall at 8.5% FP, but clean separation of only
2 of 4 (USR-234 and USR-042 still rank below normal users). Clean 4/4
separation at 0 FP is achieved by the separate threat-profile detector.

### 13.2 Top-10% Ranking Floor — Resolved

**Status (v1.0)**: Most Tier 3 methods flag top 10% → ~10% FP floor.

**Resolution (v3.0)**: Composite scoring uses a continuous score with
percentile-based thresholds. At 90th percentile: 8.5% FP. At 85th: 13.8%.
At 75th: 24.0%. This achieves 100% recall below the 10% FP mark, but the
composite still does not cleanly separate USR-234 and USR-042 from normals
(they rank #7 and #24, below normal users). The label-free threat-profile
detector is what delivers clean 4/4 separation at 0 FP.

### 13.3 Embedding Model IP Limitation

**Status**: Text-embedding-3-small treats IP addresses as generic tokens.
The C2 beacon IP (198.51.100.47) produces the same kind of embedding as
any IP address, so its presence doesn't meaningfully shift the embedding.

**Workaround**: Novelty persistence metrics computed directly from
qualitative strings before embedding. A novel IP persisting for 60/60
post-baseline weeks is a direct numeric feature that doesn't rely on
the embedding model to understand IP semantics.

### 13.4 Volt Typhoon Marginal Detection

**Status**: USR-042 ranks #24/250 (composite=13.70), just above the
90th percentile threshold (13.49). Detection relies on the combination
of 11 mildly elevated features (breadth) rather than any single strong
signal.

**Risk**: Small changes in population composition could push USR-042
below threshold. Production deployment should use the 85th percentile
(13.8% FP) for higher recall confidence.

### 13.5 Qualitative Feature Scope

**Status**: The top-8-by-frequency directory selection in feature
engineering means low-frequency attack signals (C2 beacons at 2-3/day)
can be filtered out before reaching the embedder.

**Workaround (v3.0)**: Novelty persistence operates on the raw IP strings
before frequency filtering, capturing persistent novel IPs regardless
of their daily volume

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
| `detection/composite_scorer.py` | **v3.0** Multi-phase composite scoring (5 phases) |
| `detection/novelty_features.py` | **v3.0** Qualitative annotation + novelty persistence |
| `detection/drift_direction.py` | Concept alignment, zone drift analysis |
| `detection/reference_concepts.py` | 12 reference concept definitions |
| `detection/cusum.py` | CUSUM change-point detection |
| `detection/cohort_analysis.py` | Cross-entity clustering |
| `run_tier3_250.py` | **v3.0** Full 250-user pipeline with composite detection |
| `comparison/run_tier3.py` | Tier 3 pipeline: entity zoo + trajectory extraction |
| `comparison/run_comparison.py` | Tier 1 + Tier 2 pipeline + feature engineering |
| `simulator/attacks/` | 8 attack scenario implementations |
