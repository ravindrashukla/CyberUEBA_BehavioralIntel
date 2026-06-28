# Supplier Risk POC — Build Spec & To-Do

**Status:** Planned (build slowly, phase by phase).
**Goal:** Reproduce the UEBA behavioral-drift method for *supplier risk*, so the
Supplier Risk SCM whitepaper can carry **real numbers** (like the cyber PoC does) instead
of illustrative scenarios. Core idea: segment suppliers into **peer cohorts** (what they
supply / where located / criticality), build a **cohort baseline**, and flag suppliers that
drift away from their cohort and/or their own history.

This mirrors the proven cyber pipeline. Where possible, **reuse existing modules** rather
than rewrite.

---

## 0. IMPORTANT — a real MVP already exists; reuse it

`C:\Users\shuklar\ClaudeCode\DLA_MVP_Impproved_DemandForecast` already implements much of this
with **measured results on synthetic data** (re-validate on real DLA data before any production
claim). Prefer adapting these over building from scratch:

| Need | Reuse from DLA_MVP | Notes |
|---|---|---|
| Supplier risk model | `models/supplier_risk.py` | XGBoost (P(failure≤90d), SHAP, monotone constraints) + Random Survival Forest (P(OK at T), 30/60/90d). Walk-forward 90d labels. Debarment + CAGE-change guardrails. |
| Supplier behavioral embeddings | `models/behavioral_embeddings.py` | 5 supplier zones: delivery, portfolio, capacity, stability, network → text → 1536-d. |
| Peer cohorts | `models/cohort_transfer.py` | behavioral-neighbor cohorts (top-k cosine) + similarity-weighted cohort stats. Adapt items→suppliers for peer-cohort z-scores. |
| Drift / anomaly / regime | `models/drift_detector.py`, `models/anomaly_detector.py`, `models/regime_router.py` | centroid drift, LOF/isolation, Syntetos-Boylan regime. |
| Eval / calibration | `evaluation/metrics.py` | pinball, WAPE, ECE, Brier, C-index. |
| Data model + synthetic gen | `simulator/`, `db/migrations/`, `simulator/data/*.csv` | 200 suppliers, 500 NSNs, 4 depots, 24 months; suppliers table has tier, geo_region, financial_risk_score, critical/sole_source counts, embedding. |

**Measured (synthetic) supplier-risk results now cited in the whitepaper §7.3 / §8.10:**
XGBoost AUC 0.7709 (V2 0.7780), Avg Precision 0.4918, Brier 0.1588, ECE 0.1019; RSF C-index
0.7935; survival ECE 30/60/90d = 0.084/0.090/0.129. Top SHAP: quality_incidents, order_count_90d,
ontime_rate_90d, worst_delay_90d, critical_nsn_count. Source:
`reports/model_scorecard_synthetic.md`, `reports/calibration_v1_supplier_risk_synthetic.md`.

**Revised POC framing:** the gap this POC fills on top of DLA_MVP is the **peer-cohort drift**
angle — cohort-relative z-scores (commodity/geography/criticality) + self-baseline CUSUM as the
*detection* complement to the MVP's *predictive* XGBoost/RSF scoring. Build = adapt + add, not
greenfield.

---

## 1. Success criteria

- Synthetic supplier dataset (≈200 suppliers, 24 months) with a handful of injected
  "risk campaigns" that stay within per-metric thresholds.
- Traditional baseline (per-metric thresholds + isolation forest) detects ~0 of N campaigns
  at an acceptable false-positive rate.
- BEI cohort + self-baseline drift detects all/most campaigns and ranks them near the top.
- Output CSVs that `docs/build_supplier_risk_whitepaper.py` can read (like
  `build_innovation_whitepaper.py` reads `composite_scores.csv`).

---

## 2. UEBA → Supplier analogy (the mapping that makes this work)

| Cyber concept | File (reuse/mirror) | Supplier equivalent |
|---|---|---|
| User entity | `simulator/entities.py` | Supplier entity |
| Role group (admin/security/dev/business/exec) | `detection/composite_scorer.py` `ROLE_GROUPS` | Supplier cohort (commodity / geography / criticality / tier) |
| 5 behavioral zones (identity, access, data, network, risk) | `models/hierarchical_zones.py` | 5 supplier zones (identity, performance, geographic, network position, risk) |
| Weekly behavioral snapshot → text → embedding | `embeddings/snapshot_builder.py`, `embeddings/embedder.py` | Monthly supplier snapshot → text → embedding |
| Self-baseline drift via CUSUM | `detection/cusum.py` | Same — supplier drifts from own history |
| Peer-relative z-score (Phase 2) | `composite_scorer.py` `compute_group_zscores()` | Cohort-relative z-score (supplier vs. its cohort) |
| Multi-phase composite | `composite_scorer.py` `compute_composite_scores()` | Same 5 phases, supplier features |
| Attack scenarios (insider, APT, etc.) | `simulator/attacks/*`, `simulator/config.py` `ATTACK_SCENARIOS` | Risk campaigns (sourcing shift, counterfeit, concentration, distress) |
| `composite_scores.csv` | `data/tier3_results/` | `data/supplier_results/supplier_scores.csv` |

---

## 3. Cohort taxonomy (the segmentation)

Segment each supplier by stable identity attributes, then score drift **within** cohort.

- **What they supply** — Federal Supply Class / commodity group:
  `electronics, fasteners_hardware, textiles, chemicals, subsistence, aviation_spares, IT_software`.
- **Where located** — `domestic, allied_foreign, high_risk_foreign` (proximity to adversary-nation manufacturing).
- **Criticality** — `routine, mission_essential, sole_source`.
- **Tier / size** — `prime, distributor, sub_tier` × `small_business, large_business`.

Primary cohort key for v1 = (commodity_group, geography_band). Keep criticality/tier as
features that also feed scoring. Mirror the `ROLE_GROUPS` / `ROLE_TO_GROUP` pattern.

---

## 4. Supplier behavioral zones (matches whitepaper §3.2)

Each zone → a few numeric features → serialized to a prose sentence → embedded.

1. **Identity** — CAGE/SAM status, certifications currency, tier, small-business flag.
2. **Performance Trajectory** — on-time-delivery rate, lead-time mean/var, quality reject rate.
3. **Geographic / Sourcing Risk** — country-of-origin distribution, % adversary-nation,
   manufacturing-site diversity.  ← primary drift axis for the sourcing campaign.
4. **Network Position** — # depots served, # NSNs supplied, customer concentration index,
   sole-source count.
5. **Risk / Financial** — Altman-Z-style score, bond/insurance status, expiring-contract %.

---

## 5. Synthetic data generator (mirror `simulator/`)

`supplier_sim/generate.py`:
- Generate ≈200 suppliers assigned to cohorts with cohort-typical baseline feature
  distributions (e.g., electronics suppliers naturally have more foreign sourcing than
  fasteners).
- 24 monthly snapshots per supplier. Normal suppliers vary within cohort noise.
- Cohort baselines differ — this is the whole point (a value normal for one cohort is
  anomalous for another).

### Injected risk campaigns (the "attacks", slow & within-threshold)
| ID | Campaign | Behavioral signature | Detector that should catch it |
|---|---|---|---|
| SUP-A | Adversary-nation sourcing drift | Geographic zone drifts up over 12 mo; performance flat | Self-CUSUM + cohort z-score on geographic zone |
| SUP-B | Counterfeit / quality | Quality reject rate diverges for one cohort peer; supplier×NSN | Cohort z-score on performance zone |
| SUP-C | Hidden concentration / co-drift | 3+ "independent" suppliers in a cohort drift together | Cohort-correlation / co-drift (mirror `cohort_analysis.py`) |
| SUP-D | Financial distress → quality | Risk zone + performance zone drift concurrently | Multi-zone breadth + sustained |

Keep each per-month change tiny so per-metric thresholds never trip.

---

## 6. Detection pipeline (reuse cyber modules)

1. **Serialize + embed** each monthly supplier snapshot — reuse `embeddings/embedder.py`
   (`MockEmbedder`, no API key) + a supplier `snapshot_builder` mirroring the cyber one.
2. **Self-baseline drift** — cosine distance between consecutive monthly embeddings →
   `detection/cusum.py` (reuse directly).
3. **Cohort baseline scoring** — mirror `compute_group_zscores()`: for each feature, compute
   mean/std from *normal suppliers in the same cohort*, z-score every supplier.
4. **Composite** — mirror `compute_composite_scores()` 5 phases: signal strength, breadth,
   sustained, cohort/context divergence, novelty persistence (novelty = new country-of-origin
   or new sub-tier manufacturer recurring).
5. **Co-drift** — mirror `detection/cohort_analysis.py` for SUP-C.

---

## 7. Baseline comparison (to prove the gap)

Mirror `comparison/run_comparison.py`: run Isolation Forest / One-Class SVM / LOF / per-metric
thresholds on the raw supplier features → expect ~0 campaigns caught at acceptable FP. This is
the "traditional supplier monitoring fails" evidence table for the whitepaper.

---

## 8. Outputs (feed the whitepaper)

Write to `data/supplier_results/`:
- `supplier_scores.csv` — uid, cohort, is_campaign, campaign_name, signal_strength, breadth,
  sustained, cohort_divergence, novelty, composite, rank.
- `supplier_comparison.csv` — per-method detection table (traditional vs BEI).
- `cohort_baselines.csv` — per-cohort feature mean/std (for the "cohort baseline" exhibit).

Then add a loader to `build_supplier_risk_whitepaper.py` (pattern: `load_results()` in
`build_innovation_whitepaper.py`) so §7.3 / §5 carry real numbers; fall back to the current
illustrative scenarios when the CSVs are absent.

---

## 9. Proposed module layout

```
supplier_sim/
  __init__.py
  config.py          # cohorts, campaign assignments, sim window (mirror simulator/config.py)
  entities.py        # supplier generation per cohort
  generate.py        # monthly snapshots + injected campaigns
  campaigns.py       # SUP-A..D behavioral modulation
supplier_detection/
  zones.py           # 5 supplier zones + features
  snapshot.py        # serialize -> embed (reuse embeddings/embedder.py)
  score.py           # cohort z-scores + multi-phase composite (mirror composite_scorer.py)
comparison/
  run_supplier.py    # traditional vs BEI, writes data/supplier_results/*.csv
```

---

## 10. Build checklist (slow build — tackle one box at a time)

- [ ] Phase 0 — Confirm cohort taxonomy & campaign list (this doc) with stakeholder.
- [ ] Phase 1 — `supplier_sim/config.py` + `entities.py`: suppliers in cohorts, baseline distributions.
- [ ] Phase 2 — `generate.py`: 24-month normal snapshots; verify cohort separation.
- [ ] Phase 3 — `campaigns.py`: inject SUP-A..D within-threshold.
- [ ] Phase 4 — `zones.py` + `snapshot.py`: serialize + embed (MockEmbedder).
- [ ] Phase 5 — `score.py`: cohort z-scores + composite; reuse `cusum.py`.
- [ ] Phase 6 — `comparison/run_supplier.py`: traditional baseline + output CSVs.
- [ ] Phase 7 — Wire `build_supplier_risk_whitepaper.py` to read `data/supplier_results/`.
- [ ] Phase 8 — Optional: co-drift (SUP-C) via `cohort_analysis.py`; relationship embeddings.

---

## 11. Open decisions (resolve when building)

- Real embeddings vs MockEmbedder for the PoC (Mock is fine to prove the method; note in paper).
- Monthly vs weekly cadence (whitepaper says weekly/monthly; 24 monthly is simplest).
- Whether to model NSN/Location/Manufacturer entities now or keep supplier-only for v1
  (recommend supplier-only first; relationships are Phase 8).
- Disclosure: supplier whitepaper currently discloses no formulas — keep PoC numbers as
  results only, no math, unless an NDA edition is requested.

---

*Linked context: `docs/build_supplier_risk_whitepaper.py` §3.5 (peer-cohort), the cyber proof in
`detection/composite_scorer.py` Phase 2, and the disclosure-controlled
`docs/build_innovation_whitepaper.py` results loader as the wiring pattern.*
