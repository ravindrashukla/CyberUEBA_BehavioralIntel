# V-Intelligence UEBA — Application Reference

Developer/enhancement reference for the Streamlit app and its surrounding artifacts.
Read this first before enhancing the application. Last updated 2026-06 (nav regroup +
FP standardization + Guided Demo + layered demo video).

---

## 1. How to run

The Streamlit app is **not** in Docker; it runs on the host against the Dockerized DB.

```bash
# 1) Bring up the enhanced Docker stack (db 5438, api 8003, worker)
docker-compose -f docker-compose.enhanced.yml up -d

# 2) Start the app (NOTE: bare `streamlit` is not on PATH here — use python -m)
DATABASE_URL_HOST='postgresql://cyber_ueba:password@127.0.0.1:5438/cyber_ueba' \
DB_HOST='127.0.0.1' DB_PORT='5438' \
python -m streamlit run streamlit_app.py --server.port 8502 --server.headless true
# → http://localhost:8502/   (health: http://localhost:8502/_stcore/health)
```

Docker services (`docker-compose.enhanced.yml`): `cyber-ueba-db-enhanced` (pgvector/pg16,
5438:5432), `cyber-ueba-api-enhanced` (8003:8000), `cyber-ueba-worker-enhanced`. Data persists
in volume `pgdata_enhanced`. First load is slow (Docker healthcheck wait + cold Python imports +
first DB connect); subsequent loads are cached.

`OPENAI_API_KEY` comes from `.env` via `load_dotenv()` — required for TTS (video/demo narration)
and for any embedding regeneration. The app's pages read pre-computed data from the DB; they do
not call OpenAI at render time.

---

## 2. Data model & loaders

All page data comes from `pipeline/dashboard_db.py`, imported in `streamlit_app.py` as:
`db_load_composite_scores`, `db_load_detection_results`, `db_load_weekly_features`,
`db_load_weekly_trajectories`, `db_load_novelty_metrics`, `db_load_zscored_features`,
`db_load_alerts`, `db_load_kill_chains`, `db_load_log_stats`.

`_get_engine()` reads the DB connection from env (`DATABASE_URL_HOST` / `DB_HOST` / `DB_PORT`);
**falls back to CSVs in `data/tier3_results/`** when the DB is down (e.g.
`tier3_comparison.csv` → detection_results, `composite_scores.csv`, `weekly_*`). Keep the
fallback CSVs in sync with the DB.

Dataset: **250 users, 70 weeks (week_idx 0–69), 485 days telemetry, 17,500 weekly-feature rows**
(250×70). 246 normal + 4 attackers. (Never "19 weeks / 4,750" — that was stale.)

---

## 3. The four injected attackers (ground truth)

| uid | Campaign | Composite rank / score | Caught by |
|-----|----------|------------------------|-----------|
| USR-118 | Salt Typhoon (telecom recon) | #1 / 51.3 | feature CUSUM (loud), composite, profile (recon fan-out) |
| USR-156 | 8-month insider | #2 / 46.2 | embedding CUSUM (early), composite, profile (mass collection + cohort-rare dst) |
| USR-234 | 417-day slow APT | #7 / 19.4 | **only** profile (C2 beacon + DGA) + novelty persistence — escapes BOTH drift lenses |
| USR-042 | Volt Typhoon (LOTL) | #24 / 13.7 | z-score (single spike), composite, profile (LOTL process) |

CUSUM first-clear-detection weeks — feature: 156=39, 042=47, 118=36, 234=never;
embedding: 156=4, 042=15, 118=60, 234=never. USR-234 in-band 97% of weeks per-week.

---

## 4. Canonical numbers & the FP convention (KEEP CONSISTENT)

The detection story, in order — **every page must agree with these**:

| Layer / method | Result |
|----------------|--------|
| Traditional point-anomaly (IsolationForest / SVM / LOF) | **0 of 4** |
| Intermediate Z-score | **1 of 4** (USR-042 only); fires on ~98% of normals |
| Composite scoring (5-phase fused) | **4 of 4**, but cleanly separates only **2 of 4** (USR-118, USR-156); FP cost below |
| Threat-Profile detector (multi-front known-bad) | **4 of 4 at 0 false positives** |

**FP convention — standardized to "catch-all-four" = 8.1%.** The headline FP for "catches all 4"
is computed at the **lowest attacker composite score (USR-042 = 13.70)** → 20 of 246 normals =
**8.1%**. Do NOT use `composite.quantile(0.90)` (13.49 → 21/246 = 8.5%) for a "catch all 4"
sentence — that's a different operating point and was the source of an 8.1/8.5 inconsistency
(fixed 2026-06 in Story Mode, the Three-Tier composite hero, and the verdict/comparison helpers).
Use: `cs[cs.is_attack]["composite"].min()` as the threshold. "~8%" is an acceptable hedge.

The 5 composite phases (radar / breakdown): Signal Strength (`signal_strength`),
Breadth (`breadth_15`), Sustained Deviation (`sustained_signal`), Context Divergence (`ctx_max_z`),
Novelty Persistence (`novelty_score`). Radar scaling is median-anchored min-max (0 = normal median,
100 = max observed). Threat-profile alerts: `data/threat_profile_alerts.csv` (4 rows, 0 FP);
detector source `threat_profile_detector.py` (label-free; fronts: cohort-relative IQR-z,
C2-beacon rhythm CV<0.65, DGA entropy+rare-IP, cohort-rare destination).

---

## 5. Navigation (regrouped 2026-06)

Nav is defined in `streamlit_app.py` near the top (`NAV_GROUPS` dict + a `st.selectbox` "Section"
→ `st.radio` of pages). **All 16 pages kept**; page names are unchanged so the downstream
`if/elif page == "<name>":` blocks are untouched. To find a page's code: search `elif page == "<name>":`.

| Group | Pages | Audience |
|-------|-------|----------|
| Start Here | Story Mode · Guided Demo | Exec/Buyer |
| The Detection Story | Detection Pipeline · Traditional vs V-Intelligence UEBA · Three-Tier Detection · Detection Comparison | Exec + Technical |
| Operations | Dashboard · Alerts · Threat Profiles · Kill Chains | SOC Analyst |
| Investigate an Entity | Behavioral Drift · Drift Trajectory · Behavioral Profile · Digital Entity | Technical |
| Methods & Proof | Proof of Realism · Telemetry Explorer | Technical |

**Known redundancy (deferred, not yet merged — see future cleanup):** the "traditional vs us"
comparison is told 4× (Detection Pipeline is the canonical/honest one; Three-Tier + Detection
Comparison + Traditional-vs-UEBA overlap). The drift trio (Behavioral Drift / Drift Trajectory /
Behavioral Profile) are near-identical time-series views and could merge into one with a
view-selector. Alerts and Threat Profiles share `threat_profile_alerts.csv`. The user chose
"regroup only" for now (keep all 16); merging is a future option.

### Guided Demo page (the in-app walkthrough)
Appended at the end of `streamlit_app.py` (`elif page == "Guided Demo":`). A 9-step stepper
(session_state `gd_step`, Back/Restart/Next) with **live Plotly** charts computed from the DB via
cached `_gd_prep()`. Steps: Welcome → Layer 1 (0/4) → Layer 2 drift → signal separation →
USR-234 hard case → Layer 3 radar → Layer 4 composite (8.1% FP) → Layer 5 known-bad (0 FP) →
verdict. Chart builders inline: `_gd_cusum`, `_gd_radar`, `_gd_composite`.

---

## 6. Key code locations

- Nav + colors/constants: top of `streamlit_app.py` (NAVY/BLUE/GOLD/RED/TEAL ~L44-48; `NAV_GROUPS`).
- Feature CUSUM formula: `compute_feature_drift` inside Detection Comparison block
  (`cumsum(max(mean|z vs first-half baseline| - 0.5, 0))`).
- Embedding/semantic CUSUM: `load_real_drift` = `cumsum(composite_drift)` from weekly_trajectories.
- Signal Separation + radar: Detection Comparison block (search "All Attack Users: Signal Separation",
  "5-Phase Percentile").
- Threat-profile detector: `threat_profile_detector.py` → writes `data/threat_profile_alerts.csv`.

---

## 7. External artifacts (decks, whitepaper, videos)

In `DLA 25/` (sales/exec collateral, built from the demand-forecast template):
- `Legacy_vs_EDM_UEBA_Detection_Example-ver1/ver2.pptx`, `..._2slide.pptx`,
  `UEBA_VectorIntelligence_Explainer.pptx`, `UEBA_VectorIntelligence_Executive_Brief.pptx`
- Builders: `build_ueba_example.py`, `build_ueba_2slide.py`, `build_explainer.py`, `build_executive.py`
- Crisp figures (live-data): `feature_cusum.png`, `embedding_cusum.png`, `radar.png`,
  `composite_rank.png`, `per_week_drift.png`, `cumulative_drift.png` (gen: `gen_explainer_figs.py`,
  `generate_figs.py` — need DB env)
- PCA whitepaper: `UEBA_Whitepaper_Army_PrincipalCyberAdvisor_2026-06.docx` (also in `docs/`).
  Source builder: `CyberUEBA_Whitepapers/docs/build_innovation_whitepaper.py` (multi-audience:
  DLA/USSOCOM/DISA/Army_AI; `Army_AI` targets the Army Principal Cyber Advisor, Brandon Pugh).

In `docs/`:
- Demo video (layered, narrated): `V_Intelligence_UEBA_Demo_Layered.mp4` (18 scenes, nova voice).
  Builder `build_demo_video_v2.py`; script `demo_video_script_layered.md`; frames `demo_frames_v2/`;
  TTS cache `narration_audio_v2/` (content-addressed `n_<hash>.mp3`).
- Guided-demo screen recording (narrated): `Guided_Demo_Recording.mp4`. Recorder
  `record_guided_demo.py` (Selenium drives the live app; `--narrate` / `--rerecord` flags;
  needs the app running on 8502).
- Tech spec / results docs builders: `build_tech_spec.py`, `build_ueba_whitepaper.py`,
  `build_results_doc.py`, etc. (NOTE: editing a builder does NOT regenerate its .docx/.pptx output —
  must re-run the builder.)

---

## 8. Hard-won lessons (verify before claiming)

- Numbers must be re-derived from the live DB, not asserted. Test the null/circular case.
- The threat-profile detector is **label-free** — `ATT` appears only in `main()` for counting/printing,
  never in a detection threshold. Don't reintroduce label leakage.
- Use robust stats (median/IQR/percentile) to avoid near-zero-variance z-score blowups.
- USR-234 is the acid test: it escapes both drift lenses; only the known-bad profile + novelty
  persistence catch it. Any "drift catches all 4" claim is wrong.
- Editing a doc/deck builder does not update its rendered output — re-run the builder.
