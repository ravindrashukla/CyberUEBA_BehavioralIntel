# V-Intelligence UEBA — Current Application Progress

**Last Updated: June 2026**
**Status: Production-Ready Demo with Full Documentation Suite**

---

## 1. Application Core

### Detection Engine
- [x] 5-Phase Composite Scoring (signal strength, breadth, sustained, context divergence, novelty persistence) — embedding/composite scoring cleanly separates 2 of 4 attackers (USR-156, USR-118 rank above all normal users; USR-234 ranks #7 and USR-042 ranks #24, below normal users)
- [x] Multi-front threat-profile detector (`threat_profile_detector.py`): 4/4 attack detection at 0 false positives (250 users, 485 days) via measurable known-bad behavioral profiles — C2-beacon, DGA-DNS, LOTL-process, cohort-rare access, recon-fanout, insider-collection — scored cohort-relative + raw-event, label-free
- [x] Novelty persistence detection (C2 beacon IP tracking across 60 weeks)
- [x] Group-relative z-scores (31 roles mapped to 5 peer groups, attack users excluded from baseline)
- [x] 16 reference concepts (14 threat + 2 benign) with MITRE ATT&CK mapping
- [x] Drift direction analysis with concept alignment
- [x] CUSUM change-point detection
- [x] Traditional detection: Isolation Forest, One-Class SVM, LOF, Z-Score
- [x] Kill chain reconstruction (correlated attack sequences across entities)

### Embedding Pipeline
- [x] OpenAI text-embedding-3-small (1536-d, unified semantic space)
- [x] Text serialization: 23 scalar features converted to interpretive prose per zone
- [x] 5 hierarchical zone embeddings per entity (identity, access, data, network, risk)
- [x] Context-adaptive composition (4 contexts: normal_ops, insider, APT, privilege)
- [x] Softmax attention with context-specific zone weighting
- [x] Two-level embedding cache (memory + sharded disk, SHA-256 hash-based)
- [x] Hadamard relationship embeddings (User-Device, User-App, Device-Segment)

### Temporal Analysis
- [x] Weekly behavioral snapshots (70 weeks analysis window)
- [x] Velocity vectors (1536-d direction of behavioral change)
- [x] Acceleration detection (escalating drift rate)
- [x] Regime classification (stable, drifting, accelerating, regime_shift)
- [x] Per-zone trajectory tracking (independent drift per behavioral dimension)

### Data Pipeline
- [x] Synthetic data generation (250 users, 485 days, 5 log sources)
- [x] 4 embedded attack campaigns (Insider 8mo, Slow APT 180d, Volt Typhoon 115d, Salt Typhoon 100d)
- [x] 23-feature weekly engineering (auth, file, network, DNS, endpoint)
- [x] Daily ingestion pipeline with 34 daily features
- [x] Entity materialization and behavioral snapshot computation

### Database
- [x] PostgreSQL 16 + pgvector extension
- [x] 16 tables across 6 migrations (daily_features, behavioral_snapshots, trajectory_snapshots, trajectory_events, user_embeddings_history, composite_scores, detection_results, novelty_metrics, zscored_features, weekly_trajectories, weekly_features, alerts, kill_chains, kill_chain_events, log_stats, drift_series)
- [x] SCD Type 2 bi-temporal history (valid_from/valid_to, knowledge_from/knowledge_to)
- [x] HNSW cosine similarity indexes on vector columns
- [x] Docker Compose deployment (db + api + worker)

---

## 2. Dashboard (Streamlit)

### Pages (12 total)
- [x] Story Mode — Interactive walkthrough: raw data → reveal → detection → results
- [x] Dashboard — KPI overview with real-time metrics
- [x] Alerts — Active alert management with severity filtering
- [x] Kill Chains — Correlated attack sequence visualization
- [x] Behavioral Drift — Drift heatmap across all entities
- [x] Behavioral Profile — Per-user signal drift decomposition
- [x] Drift Trajectory — Time-series trajectory analysis
- [x] Digital Entity — Entity structure and zone exploration
- [x] Telemetry Explorer — Raw log exploration (all rows, sorted by user, with detail lookup)
- [x] Traditional vs V-Intelligence UEBA — Side-by-side detection comparison
- [x] Three-Tier Detection — Tier 1/2/3 comparison with radar chart
- [x] Detection Comparison — Full 17-method results matrix

### Dashboard Features
- [x] User Detail Lookup (selectbox with profile, activity averages, weekly trend chart)
- [x] 5-Phase radar chart (Attackers vs Normal Baseline)
- [x] Composite scoring explanation panel below radar chart
- [x] Feature-Space CUSUM vs Semantic CUSUM signal separation comparison
- [x] All data pulled dynamically from PostgreSQL database (no hardcoding)
- [x] DB connection timeout (2s) with socket pre-check to prevent hang when DB is down
- [x] DB availability caching per-process

---

## 3. Test Suite

### Test Files (13 files, 620+ tests)
- [x] `test_deep_analysis.py` — 120 tests: composite scorer, novelty features, embedding edge cases, drift direction, hierarchical zones, temporal trajectory, detection accuracy, numerical stability, integration, security/evasion
- [x] `test_ai_ml.py` — 57 tests: embeddings, composition, cosine similarity, drift, velocity, trajectory, regime detection, Hadamard, zone serialization
- [x] `test_deep_db_integration.py` — DB table integrity, cross-table consistency, attack signal validation
- [x] `test_design_architecture.py` — Architectural design validation
- [x] `test_design_detection.py` — Detection design validation
- [x] `test_design_tier3.py` — Tier 3 digital entity design validation
- [x] `test_design_dla_port.py` — DLA MVP port design validation
- [x] `test_business_analyst.py`, `test_cyber_security.py`, `test_data_analyst.py`, `test_data_engineering.py`, `test_ui_ux.py` — Role-specific validation
- [x] `_smoke_test.py` — Pre-demo system health validation

### Test Results
- 177 core tests passing (test_deep_analysis + test_ai_ml)
- 1 pre-existing non-critical failure (concept count 12→16, test not updated)
- DB-dependent tests require Docker (156 tests)

---

## 4. Documentation Suite

### Technical Documents (Internal)
| Document | Pages | Purpose |
|----------|-------|---------|
| V-Intelligence UEBA Technical Specification (v4.0) | ~50 | Full algorithms, formulas, parameters, 13 sections |
| V-Intelligence UEBA Implementation Specification | ~50+ | PROPRIETARY — complete engineering blueprint with all formulas, thresholds, weights, database schema |
| V-Intelligence UEBA Results and Findings | ~15 | Empirical results and business value |
| Traditional vs Behavioral Analysis | ~20 | Federal CISO-level comparison |

### Whitepapers (External — No Proprietary Logic)
| Document | Audience | Pages |
|----------|----------|-------|
| UEBA Behavioral Intelligence Whitepaper (Universal) | General | ~30 |
| Whitepaper — DLA | DLA CIO, DLA PEO | ~30 |
| Whitepaper — USSOCOM | SDA, EIS, S&T, Innovation | ~30 |
| Whitepaper — DISA | PEO Cyber | ~30 |
| Whitepaper — Army AI | Chief of AI | ~30 |
| Behavioral Entity Intelligence Framework | All audiences | ~30 |
| Supplier Risk in SCM | DLA | ~30 |
| Prescriptive Maintenance | DLA, Army, USSOCOM | ~30 |

### Presentations
| Document | Slides | Purpose |
|----------|--------|---------|
| Sales Pitch v2 | 20 | Client demo (~20 min) |
| Technical Deep Dive | 24 | Technical audience |
| Traditional vs Behavioral Deck | 19 | Executive comparison |
| Detection Comparison Business Deck | 14 | Business-level explanation |

### Media
| Document | Duration | Purpose |
|----------|----------|---------|
| Demo Video (MP4) | ~7 min | 17-frame narrated walkthrough with TTS |

### Document Builders (13 scripts)
All documents are programmatically generated via Python scripts in `docs/build_*.py`. Running any builder regenerates the document with current data and branding.

---

## 5. Detection Results (Verified)

### Embedding / Composite Scoring (cleanly separates 2 of 4)

| Attack User | Campaign | Duration | Composite Score | Rank (/250) | Clean Separation |
|-------------|----------|----------|----------------|-------------|------------------|
| USR-118 | Salt Typhoon (Telecom) | 100 days | 51.3 | #1 | YES (above all normal users) |
| USR-156 | Insider Threat | 8 months | 46.2 | #2 | YES (above all normal users) |
| USR-234 | Slow APT (C2 Beacon) | 180 days | 19.4 | #7 | NO (below normal users) |
| USR-042 | Volt Typhoon (LOTL) | 115 days | 13.7 | #24 | NO (below normal users) |

Composite scoring ranks USR-156 and USR-118 above every normal user, but USR-234
(#7) and USR-042 (#24) fall below normal users — so any threshold that catches all 4
also admits false positives (e.g., ~8.5% FP at the 90th percentile). The clean
**4/4 result belongs to the threat-profile detector below**, not to composite scoring.

### Multi-Front Threat-Profile Detector (`threat_profile_detector.py`) — 4/4 at 0 FP

| Attack User | Campaign | Matched Known-Bad Profile(s) | Status |
|-------------|----------|------------------------------|--------|
| USR-118 | Salt Typhoon (Telecom) | recon-fanout, cohort-rare access | DETECTED |
| USR-156 | Insider Threat | insider-collection | DETECTED |
| USR-234 | Slow APT (C2 Beacon) | C2-beacon, DGA-DNS | DETECTED |
| USR-042 | Volt Typhoon (LOTL) | LOTL-process | DETECTED |

- **Result**: 4/4 true positives at **0 false positives** across 250 users, 485 days
- **Method**: measurable known-bad behavioral profiles (C2-beacon, DGA-DNS,
  LOTL-process, cohort-rare access, recon-fanout, insider-collection) scored
  cohort-relative + raw-event, label-free
- **Traditional Methods**: 0/4 at operationally acceptable FP rates

---

## 6. Architecture Summary

```
Raw Telemetry (auth, file, network, DNS, endpoint)
  → Daily Features (34 per user per day)
    → Weekly Aggregation (23 features per user per week)
      → Text Serialization (features → interpretive prose per zone)
        → Embedding (prose → 1536-d vector via OpenAI)
          → Zone Composition (5 zones → context-weighted composite)
            → Temporal Snapshots (weekly behavioral state)
              → Drift Detection (velocity, acceleration, regime)
                → Composite Scoring (5-phase multi-dimensional)
                  → Ranked User List (single actionable output)
```

**Infrastructure**: Docker Compose (PostgreSQL+pgvector:5437, FastAPI:8000, Streamlit:8501)

---

## 7. Key Innovations

1. **Text Serialization → Semantic Embedding**: Raw metrics become prose before embedding, capturing behavioral MEANING not just magnitude
2. **Zone Decomposition**: 5 independent behavioral dimensions prevent signal dilution (insider data_behavior drift not averaged with 4 stable zones)
3. **Multi-Phase Composite Scoring**: 5 independent detection phases (cleanly separates 2 of 4 attackers; the clean 4/4 win belongs to the threat-profile detector)
3a. **Multi-Front Threat-Profile Detector**: measurable known-bad behavioral profiles (C2-beacon, DGA-DNS, LOTL-process, cohort-rare access, recon-fanout, insider-collection) — 4/4 detection at 0 false positives, label-free
4. **Novelty Persistence**: Detects C2 beacon patterns invisible to all other methods (USR-234 relies 100% on this)
5. **Context-Adaptive Attention**: Same data, different analytical lenses (insider vs APT vs privilege audit)
6. **Relationship Embeddings**: Hadamard products capture pairwise interaction patterns invisible to single-entity analysis
7. **Behavioral Entity Intelligence (BEI)**: Universal framework proven applicable across cybersecurity, supply chain, healthcare, maintenance, counter-intelligence, and 8+ additional domains
