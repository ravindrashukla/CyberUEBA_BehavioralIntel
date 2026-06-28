# Invention Disclosure for Provisional Patent Application

**FOR ATTORNEY REVIEW — NOT LEGAL ADVICE.** This is an inventor's technical disclosure prepared to support the drafting and filing of a U.S. provisional patent application. Counsel should refine claims, run a formal patentability / freedom-to-operate (FTO) search, and confirm inventorship and ownership before filing.

---

## 0. Filing Metadata (to be completed)

| Field | Value |
|---|---|
| Proposed title | Behavioral Entity Intelligence: Anomaly Detection by the Direction of Behavioral Drift in a Unified Cross-Domain Semantic Embedding Space |
| Inventor(s) | _[full legal name(s), address(es)] — TO COMPLETE_ |
| Assignee / applicant | 22nd Century Technologies, Inc. _(confirm)_ |
| Earliest conception / reduction-to-practice date | _[date(s)] — TO COMPLETE; attach lab notebook / commit history as evidence_ |
| Related disclosures | V-Intelligence UEBA program; DLA EDM Demand Forecast MVP; companion technical whitepapers |
| Prior public disclosure? | _[Confirm whether any public demo/whitepaper/RFI response has occurred — affects the 12-month U.S. statutory bar and foreign rights] — TO CONFIRM_ |

> **Action for counsel:** Provisional applications are not examined and do not require formal claims, but the draft claims in §9 are included to anchor the eventual non-provisional. Confirm the §0 metadata and the public-disclosure timeline (important for the on-sale / public-use bar).

---

## 1. Field of the Invention

The invention relates to machine-learning systems for anomaly and risk detection over the behavior of monitored entities. More particularly, it relates to representing heterogeneous entities (e.g., users, devices, network segments, applications, suppliers, inventory items, accounts) as time-evolving points in a unified semantic vector space derived from natural-language serialization of behavior, and to detecting anomalies by the **direction** of behavioral change projected onto named reference concepts — applied across multiple operational domains including cybersecurity behavior analytics and supply-chain demand forecasting.

---

## 2. Background

### 2.1 The problem
The most consequential anomalies — insider threats, slow advanced-persistent-threat (APT) campaigns, living-off-the-land intrusions, gradual supply-chain sourcing shifts, demand regime changes — are engineered or evolve to remain within normal statistical ranges on every individual metric. The damaging signal is in the **direction** and **accumulation** of change ("what is the entity becoming"), not in the **magnitude** of any single metric exceeding a threshold.

### 2.2 Limitations of existing approaches
Conventional systems measure magnitude or rarity on numeric feature vectors:
- **Behavioral security analytics** typically baseline entities statistically (p-value tests, histogram/profile deviation, isolation forests, one-class methods) and group peers by count- or membership-based heuristics; recent generative-AI additions function as analyst assistants rather than the detection mechanism.
- **Demand/supply-chain forecasting** typically uses statistical models and gradient-boosted/deep tabular models over numeric features, with uncertainty bands whose shape is fixed (all quantiles scaled by one ratio), and with generative-AI used as a conversational layer.
- **Foundation time-series models** tokenize numeric series directly rather than representing behavior as language.

None of these (a) represent heterogeneous entities and multiple domains in one semantic space, (b) detect by the **direction** of drift projected onto named natural-language concepts, or (c) adjust forecasts/uncertainty by that direction.

> A structured competitive/literature review (see §10) confirms each constituent technique exists individually in prior art, but the integrated combination disclosed here was not found in any commercial product or single published system (scoped to publicly described methodology).

---

## 3. Summary of the Invention

A computer-implemented system and method that:

1. **Serializes behavior to language.** For each entity and observation period, aggregates raw observational metrics into a set of **behavioral zones**, and renders each zone's state as a natural-language description (optionally "interpretive" — expressing each metric relative to population baseline, the entity's own baseline, and recent trend).

2. **Embeds into a unified semantic space.** Encodes each zone description with a text-embedding model into fixed-dimensional vectors occupying **one common semantic space shared across all entity types and across multiple operational domains** (e.g., cybersecurity and supply chain).

3. **Composes an entity embedding** from the zone embeddings (weighted average and/or context-adaptive attention), producing per-period entity vectors and, optionally, multiple context-specific composites.

4. **Tracks a trajectory.** Stores successive entity embeddings as a time series of snapshots, forming a behavioral trajectory.

5. **Detects by direction of drift.** Computes a drift vector between snapshots and **projects it (cosine similarity) onto a library of pre-embedded natural-language reference concepts** (e.g., threat concepts mapped to MITRE ATT&CK techniques; supply-chain concepts such as demand surge / supply disruption), thereby determining *what the entity is becoming*, not merely how much it changed.

6. **Accumulates slow drift** via a cumulative-sum (CUSUM) change-point procedure to surface sustained, sub-threshold drift.

7. **Scores relative to peers** by standardizing features against a **cohort** of comparable entities (z-scores vs. cohort, not the whole population).

8. **Fuses multiple phases** (signal strength, breadth, sustained deviation, context divergence, novelty persistence) into a single ranked verdict; optionally models **pairwise relationships** as element-wise (Hadamard) products of entity embeddings.

9. **Drift-augments forecasts (forecasting embodiment).** Converts the named concept and drift dynamics into a bounded plan adjustment and **dynamic, asymmetric uncertainty bands** (band widths that widen or narrow per concept, independently of the median), improving probabilistic forecasts and right-sizing safety stock.

10. **Is domain-portable.** The identical architecture instantiates across domains by changing only the serialization templates and zone definitions.

---

## 4. Brief Description of the Drawings

(Figures available from the companion whitepaper builders; to be re-rendered for filing as formal patent drawings.)

- **FIG. 1** — End-to-end pipeline: raw metrics → zone serialization to language → embedding into unified space → composition → trajectory → drift + concept projection → composite scoring → ranked, explained output.
- **FIG. 2** — Data flow / layered data model (bronze → silver → gold features + vector store → models → output).
- **FIG. 3** — System architecture (ingestion; vector database with bi-temporal history and approximate-nearest-neighbor index; model services; serving).
- **FIG. 4** — Entity digital model: zones (dimensions) → sub-dimensions → per-period embedding → temporal snapshot stack.
- **FIG. 5** — Drift in semantic space: trajectory of snapshots; drift vector; cosine projection onto named concept vectors.
- **FIG. 6** — Multi-phase composite scoring fusing independent phases into one ranked verdict.
- **FIG. 7** — Forecasting embodiment: legacy frozen-shape bands vs. drift-augmented dynamic bands.

---

## 5. Detailed Description

### 5.1 Entity digital model and behavioral zones
Each monitored entity of any type is modeled as a structured, multi-dimensional record ("entity snapshot" / "demand envelope"). Top-level slots are **dimensions** (behavioral zones); each holds **sub-dimensions** (features). Example (cyber user) zones: identity (static profile), access pattern, data behavior, network footprint, risk posture. Example (supplier/item) zones: identity, performance, geographic/sourcing, network position, risk/financial. The record is captured as a **time series of snapshots** (e.g., weekly or monthly).

### 5.2 Natural-language serialization
For each zone and period, the raw metrics are serialized into a natural-language description. In a preferred ("interpretive") embodiment, each metric is expressed relative to (i) the population (e.g., a z-score / percentile descriptor), (ii) the entity's own historical baseline (ratio), and (iii) recent trend — so the description encodes analyst-relevant context, and qualitative tokens (e.g., directory names, IP addresses, domain names, country-of-origin) are preserved rather than discarded.

> *Example serialized zone (illustrative):* "User U accesses 30 files this week, 15% restricted (≈12× the user's own baseline, trend rising), shifting from public toward restricted/confidential material."

### 5.3 Unified cross-domain embedding
Each serialized description is embedded by a text-embedding model into a vector of fixed dimensionality D (e.g., D = 1536) occupying **one semantic space common to all entity types and all domains**. Embeddings may be cached by content hash and stored in a vector database supporting approximate-nearest-neighbor search and bi-temporal (valid-time / knowledge-time) versioning for leak-free, point-in-time retrieval.

### 5.4 Composition
Zone embeddings are composed into an entity embedding. In one embodiment, a weighted average:
```
V = normalize( Σ_z  w_z · e_z )
```
In a preferred embodiment, **context-adaptive attention** sets the weights by a softmax over zone salience biased by an analytical context c:
```
α_z = softmax_z( ||e_z|| · b_z(c) ) ;   V = normalize( Σ_z α_z · e_z )
```
yielding multiple context-specific composites (e.g., routine, insider-investigation, APT-hunt).

### 5.5 Drift: magnitude and direction
Between consecutive (or baseline-vs-recent) snapshots:
```
drift magnitude:   d_t = 1 − cos( V_{t−1}, V_t )
drift direction:   u_t = ( V_t − V_{t−1} ) / || V_t − V_{t−1} ||
```

### 5.6 Concept projection (the direction-of-drift detector)
A library of **reference concepts** is pre-embedded in the same space from natural-language concept descriptions (e.g., data_exfiltration, lateral_movement, c2_beacon, living_off_the_land; demand_surge, supply_disruption, critical_shortage, excess_inventory). The entity's drift direction is projected onto each concept:
```
align_k = cos( u_t , Embed(concept_k) )
```
The highest-magnitude alignment names *what the entity is becoming*, and is mapped to a taxonomy (e.g., MITRE ATT&CK techniques for the security embodiment), producing an explainable, analyst-actionable output rather than an opaque score.

### 5.7 Slow-drift accumulation (CUSUM)
To catch sustained sub-threshold drift:
```
S_0 = 0 ;   S_t = max( 0, S_{t−1} + (d_t − k) ) ;   alarm when S_t ≥ h for ≥ r consecutive periods
```
(k = allowable per-period drift; h = decision threshold; r = run length.)

### 5.8 Peer-cohort relative scoring
Each entity is assigned to a **cohort** of comparable entities (by stable identity attributes — e.g., role group for users; commodity/geography/criticality/tier for suppliers). Features are standardized against the normal members of the cohort:
```
z[i,f] = ( x[i,f] − μ_cohort[f] ) / σ_cohort[f]
```
so an entity is flagged for diverging from *its peers*, not the whole population.

### 5.9 Relationship embeddings
Pairwise interactions are represented as the element-wise (Hadamard) product of two entity embeddings, normalized:
```
R[a×b] = normalize( V_a ⊙ V_b )
```
Drift in R surfaces interaction-level change even when each entity individually appears stable; clusters of co-drifting entities indicate shared dependencies / coordinated behavior.

### 5.10 Multi-phase composite scoring
A final verdict fuses independent phases — e.g., signal strength (peak cohort-relative deviation), breadth (count of elevated features), sustained deviation, context divergence, and novelty persistence (recurring never-before-seen entities/infrastructure) — into one ranked score, so no single evasion technique defeats detection.

### 5.11 Forecasting embodiment — drift-augmented dynamic bands
In the forecasting domain, a baseline probabilistic forecaster (e.g., a two-stage occurrence-classifier + quantile-regressor "hurdle" model over engineered features, optionally enriched with the embedding features above) is **augmented** by the drift layer: the named concept yields a bounded plan adjustment α and a band multiplier β:
```
α = clamp( direction(concept) · alignment · drift_norm , −A, +A )
adj_P50 = max(0, P50 · (1 + α))
adj_P90 = adj_P50 + (P90 − P50) · β        # bands widen/narrow INDEPENDENTLY of the median
```
with safety gates (zero/attenuate α when alignment or trajectory consistency is weak). This produces **dynamic, asymmetric** uncertainty bands — unlike conventional methods whose band shape is fixed — improving safety-stock right-sizing.

### 5.12 Cross-domain portability
The same pipeline (serialize → embed → compose → trajectory → drift → concept-project → cohort/fuse) instantiates in a new domain by changing only the serialization templates, zone definitions, and concept library. Disclosed embodiments include (a) user-and-entity behavior analytics for cybersecurity and (b) demand forecasting / supplier-risk for defense logistics — both operating in the same unified embedding space.

---

## 6. Advantages

- Detects constant-volume, direction-only changes that magnitude/threshold methods miss.
- Explainable output (named concept + taxonomy mapping) instead of an opaque anomaly score.
- One unified space enables cross-entity similarity, cohort cold-start transfer, and relationship/co-drift analysis.
- Domain-portable architecture (cyber + supply chain demonstrated) reduces re-engineering.
- Dynamic, asymmetric forecast bands improve probabilistic decision support (e.g., safety-stock right-sizing).

---

## 7. Reduction to Practice (synthetic validation — summary)

> All figures are from SYNTHETIC datasets and are illustrative of operability; they are not performance claims for real-world deployment.

- **Security embodiment:** 250 entities × ~485 days; 4 embedded long-duration campaigns (insider, slow APT, living-off-the-land, infrastructure pivot). Multi-phase composite surfaced all 4 in the top tier at ~8.1% false-positive operating point; point-in-time outlier detectors surfaced none at an acceptable rate. Occurrence/quantile components calibrated (e.g., occurrence ECE ≈ 0.03).
- **Forecasting embodiment:** 500 items × 200 suppliers × 4 depots × 24 months. Calibrated two-stage forecaster (occurrence ECE ≈ 0.03; near-nominal P10–P90 coverage); drift-augmented dynamic bands right-size procurement (illustrative single-item over-order avoidance vs. a moving-average baseline). Supplier-risk model AUC ≈ 0.77, survival C-index ≈ 0.79.

---

## 8. Glossary
Zone, serialization, embedding, composite, drift vector/magnitude/direction, reference concept, concept projection/alignment, CUSUM, cohort, multi-phase composite, relationship (Hadamard) embedding, drift-augmented forecast, dynamic bands, bi-temporal store. (Definitions per §5.)

---

## 9. Draft Claims (illustrative — for attorney refinement)

**Independent claim 1 (method).** A computer-implemented method for detecting behavioral anomalies, comprising: for each entity of a plurality of entities spanning two or more entity types: (a) aggregating observational metrics for the entity over an observation period into a plurality of behavioral zones; (b) generating, for each zone, a natural-language description of the zone's state; (c) encoding each natural-language description, using a text-embedding model, into a vector occupying a semantic vector space that is common to all of said entity types; (d) composing the zone vectors into an entity vector; (e) repeating (a)–(d) over successive observation periods to form a time series of entity vectors; (f) computing a drift vector from at least two of the entity vectors; (g) computing a similarity between the drift vector and each of a plurality of pre-embedded natural-language concept vectors residing in said semantic vector space; and (h) producing a detection output identifying a concept based on said similarity and indicating a direction of behavioral change of the entity.

**Claim 2.** The method of claim 1, wherein the plurality of entities spans two or more operational domains, and the semantic vector space is common across said domains.

**Claim 3.** The method of claim 1, wherein generating the natural-language description expresses each metric relative to one or more of: a population baseline, the entity's own historical baseline, and a recent trend.

**Claim 4.** The method of claim 1, further comprising accumulating drift magnitude over successive periods with a cumulative-sum procedure and signaling a change point when the accumulated value exceeds a threshold for a minimum run length.

**Claim 5.** The method of claim 1, wherein composing comprises a context-adaptive attention weighting over zones determined by a softmax of zone-vector magnitudes biased by an analytical context.

**Claim 6.** The method of claim 1, further comprising standardizing entity features against statistics of a cohort of comparable entities and scoring the entity relative to said cohort.

**Claim 7.** The method of claim 1, further comprising mapping the identified concept to a structured taxonomy (e.g., MITRE ATT&CK techniques) and emitting an explanation.

**Claim 8.** The method of claim 1, further comprising forming a relationship vector as a normalized element-wise product of two entity vectors and detecting drift of the relationship vector.

**Claim 9.** The method of claim 1, further comprising fusing a plurality of detection phases — including two or more of signal strength, breadth, sustained deviation, context divergence, and novelty persistence — into a single ranked score.

**Independent claim 10 (forecasting).** A computer-implemented method for generating a probabilistic forecast for an entity, comprising producing a baseline forecast having quantile bands; forming a time series of entity vectors per claim 1(a)–(e); determining a direction of behavioral drift by projecting a drift vector onto pre-embedded concept vectors; and adjusting the baseline forecast by (i) a bounded scalar adjustment to a central quantile and (ii) a per-concept band multiplier that widens or narrows the band spread independently of the central quantile.

**Independent claim 11 (system) / claim 12 (non-transitory computer-readable medium).** Corresponding system and CRM claims implementing claims 1–10.

*Dependent variations for counsel:* embedding dimensionality and model class; vector database with approximate-nearest-neighbor index and bi-temporal versioning; specific zone sets per domain; novelty-persistence definition; safety gates on the forecast adjustment; demand "hurdle" two-stage baseline.

---

## 10. Distinction Over Prior Art (source-verified)

A structured, adversarially-verified review (2024–2026) of commercial products and the literature found:
- **Commercial UEBA** (e.g., Exabeam, Securonix, Microsoft Sentinel UEBA): statistical/p-value profiling, ML baselines, rarity/magnitude scoring, count/TF-IDF peer grouping; generative-AI as analyst copilots — not embedding-direction detection.
- **Commercial demand/SCM** (e.g., SAP IBP, o9, Kinaxis): gradient-boosted/ML over tabular features on knowledge-graph data models; generative-AI as conversational layer.
- **Academic prior art (each individually established, all magnitude-based and/or single-domain):** LLM-embedding of serialized behavior for anomaly detection (e.g., APT-LLM, arXiv:2502.09385; LogBERT, arXiv:2103.04475); serialize-tabular-to-prose then embed (TabLLM family, arXiv:2502.11596); embed-then-detect benchmarks (TAD-Bench, arXiv:2501.11960); embedding drift via cosine (ZEDD, arXiv:2601.12359); embedding-similarity cohort transfer.

**What is asserted as novel (the integrated combination), scoped to publicly described methodology:** (i) a single unified semantic embedding space spanning multiple entity types **and** multiple operational domains; (ii) anomaly/forecast detection by the **direction** of behavioral drift projected onto pre-embedded **named** natural-language concept vectors (mapped to a taxonomy such as MITRE ATT&CK) — rather than magnitude/rarity; and (iii) the end-to-end stack combining prose serialization + unified cross-domain space + concept-direction drift + cohort scoring + zone decomposition + multi-phase fusion + drift-augmented dynamic forecast bands. The individual constituent techniques are conceded as prior art; novelty is claimed in the combination and the concept-direction paradigm.

> **Counsel action:** Confirm via formal patentability/FTO search; review the cited references and the two cited patents identified during the landscape review (US11258814B2; US12250239B2) for relevance.

---

## 11. Notes / To-Do Before Filing
- [ ] Complete §0 metadata (inventors, assignee, conception/RTP dates, public-disclosure timeline).
- [ ] Re-render FIG. 1–7 as formal patent drawings.
- [ ] Counsel: patentability + FTO search; confirm §101 eligibility framing (tie claims to a specific technical improvement / particular machine, not an abstract idea).
- [ ] Decide claim scope and which embodiments to emphasize (security vs. forecasting vs. both).
- [ ] Confirm whether any enabling public disclosure has occurred (statutory-bar clock).

*Prepared as an inventor's technical disclosure to accompany attorney drafting of a U.S. provisional patent application. Not legal advice.*
