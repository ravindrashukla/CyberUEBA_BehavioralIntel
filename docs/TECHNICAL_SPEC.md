# V-Intelligence UEBA — Technical Specification

**Read this before changing the Streamlit app, the pipeline, or any narrative/number.**
This is the single source of truth for how the system is wired, what the canonical numbers are,
and the conventions that every page must respect. It complements (does not replace)
[CLAUDE.md](../CLAUDE.md) and [docs/APP_REFERENCE.md](APP_REFERENCE.md).

Last updated: 2026-07-12.

---

## 1. What this is

A "Behavioral Digital Twin" UEBA product (Layer 2 of a 5-layer 360° cyber-defense platform),
targeting a **Pentagon / DoD technical audience**. It ingests entity telemetry, builds a behavioral
digital twin per entity (weekly grain), and detects intruders that use valid credentials and
legitimate tools — the ones traditional SIEM/point-anomaly tools miss.

The demo dataset hides a handful of stealth attacks among a normal population and shows, page by
page, how layered detection catches what single methods miss.

---

## 2. Architecture

- **Stack:** `docker-compose.enhanced.yml` — PostgreSQL+pgvector on **port 5438**, FastAPI on 8003, a worker.
  The Streamlit app runs against this **enhanced** stack (NOT the base 5433/8000 stack).
- **DB is the single source of truth.** Port **5438**. Bronze logs are the only CSVs the pipeline reads;
  everything downstream reads the DB. Gold CSVs under `data/tier3_results/` are a mirror/fallback only.
- **Embeddings:** ALL 1536-d, OpenAI `text-embedding-3-small`, one unified space. `OPENAI_API_KEY`
  is loaded from `.env` via `load_dotenv()`. Every pipeline hard-fails without it (no mock embeddings).
- **Run the app** (bare `streamlit` is not on PATH):
  ```bash
  docker-compose -f docker-compose.enhanced.yml up -d
  DATABASE_URL_HOST='postgresql://cyber_ueba:password@127.0.0.1:5438/cyber_ueba' DB_HOST='127.0.0.1' DB_PORT='5438' \
  python -m streamlit run streamlit_app.py --server.port 8502 --server.headless true   # -> http://localhost:8502/
  ```
  The app's DB loaders (`pipeline/dashboard_db.py`, `pipeline/streamlit_db.py`) read **`DATABASE_URL_HOST`**;
  if it is unset they fall back to `DB_HOST`/`DB_PORT` (default port 5437!) and then to gold CSVs. Always set
  `DATABASE_URL_HOST` when launching or the app silently serves stale/partial CSV data.

---

## 3. The dataset and the attackers (CANONICAL — do not mislabel)

**250 canonical users** over **70 weeks / 485 days** (week 0 = 2025-01-01, week 69 = 2026-04-29),
17,500 weekly rows. Plus **USR-EVA**, a 251st **demo overlay attacker** (see §7).

Four real injected attackers + one demo. **Their scenarios are canonical — mislabeling them is a defect
(we have already had to fix "volume flood" and "credential compromise" mislabels):**

| Entity | Scenario (exact) | Role group | start_week | How it is caught |
|---|---|---|---|---|
| **USR-156** | Insider Threat, 8-month | business | 8 | Composite (distributed drift) + threat-profile (mass-collection, cohort-rare-dst) |
| **USR-234** | Slow APT — C2 **beacon** + **DGA**, 180-day | developer | 13 | **Only** the threat-profile (c2_beacon + dga_dns). Clears **neither** drift band. |
| **USR-042** | Volt Typhoon **Living-off-the-Land** (abuses legit admin tools), 115-day | security | 2 | Threat-profile (lotl_process) at 0 FP. NOT credential-compromise, NOT lateral-movement. |
| **USR-118** | Salt Typhoon telecom **recon fan-out** (reaches far more destinations than peers), 100-day | developer | 4 | Threat-profile (recon_fanout) + cheap drift. It is a **fan-out (breadth of destinations)**, NOT a byte "volume flood". |
| **USR-EVA** | **Evasive insider**, low-and-slow **demo** (built on real dev USR-184; drift ramps wk 35→55) | developer | 35 | Composite (rank #1) only. **Evades every known-bad profile by design.** |

Never write "19 weeks / 4,750". Never call USR-118 a volume flood. Never call USR-042 credential compromise.

---

## 4. Ground truth (verified from the live DB; every number below is computed live in the app)

Composite ranking over 251 (catch-all threshold = lowest attacker composite):

| Entity | composite | rank | signal | breadth_15 | novelty | cleanly separated? |
|---|---|---|---|---|---|---|
| USR-EVA | 77.87 | **#1** | 50.61 | 24 | 0.0 | yes |
| USR-118 | 51.70 | **#2** | 30.59 | 17 | 2.8 | yes |
| USR-156 | 46.19 | **#3** | 30.00 | 19 | 0.0 | yes |
| USR-234 | 20.03 | **#8** | 4.50 | 2 | 13.0 | no (below normals) |
| USR-042 | 12.95 | **#31** | 6.24 | 10 | 0.0 | no (below normals) |

- **Catch-all threshold = 12.95** (USR-042's score). Flag everyone ≥ 12.95 → **FP = 26/246 = 10.6%**.
- **246 normal users** (250 canonical − 4 real attackers; EVA is `is_attack` and excluded from FP denominators).
- **Cleanly separated (rank above ALL normals): 3 of 5** — USR-118, USR-156, USR-EVA.
- **Per-detector over the 5 attackers:** traditional IF/SVM/LOF = **0/5**; z-score = **1/5** (USR-042 only, ~9.8% FP);
  composite = **5/5** at 10.6% FP; threat-profile = **4/5** at **0 FP** (misses USR-EVA by design).
- **First sustained band-crossings:** feature-CUSUM — 156:wk39, 042:wk47, 118:wk36, 234:never, EVA:wk40.
  Embedding-CUSUM — 156:wk4, 042:wk15, 118:wk60, 234:never, EVA:wk53.

**RULE: never hardcode any of these.** The 2026-06-28 re-embed shifted FP 8.1%→10.6% and broke every hardcoded
copy. Compute FP/ranks/counts live from the DB. The app exposes `FP_ALL4_TXT` for the live catch-all FP string.
Denominators over "all attackers" must use `len(ATTACK_USERS)` (=5), never a literal 4.

---

## 5. Two detectors, and THREE different "anomaly" measurements (the thing that confuses people)

There are two **detectors** and, separately, three **quantities** that are easy to conflate. They are not the same.

**Detectors**
1. **Composite scorer** (discovery) — one ranked list. Catches 5/5 but at 10.6% FP; cleanly separates only 3/5.
2. **Multi-front threat-profile detector** (`threat_profile_detector.py`, precision) — the **primary** detector.
   Cohort-relative robust-z ≥ 4.5 + raw-event fingerprints (c2_beacon, dga_dns, cohort_rare_dst, recon_fanout,
   mass_collection, insider_collection, lotl_process). Catches the 4 real attackers at **0 FP**, each named by technique.

**Three quantities — DO NOT conflate (this caused a real "how can 042 be caught wk15 but rank #31?" question):**
- **Feature-space CUSUM** = raw-magnitude **self-drift**: `cusum = Σ max(mean(|z vs own first-half baseline|) − 0.5, 0)`.
  Drift **above a per-entity noise floor**, accumulated. **This is OUR method, NOT a traditional baseline** — never list it
  among Isolation Forest / SVM / LOF / Z-Score.
- **Embedding CUSUM** = semantic **self-drift**: cumulative `weekly_trajectories.composite_drift` (movement of the
  entity's own embedding from its own baseline). A "band crossing" here means the entity moved from *its own* past.
- **Composite score** = a fused 5-phase score that is largely **group-relative** (z vs role-group peers) + breadth +
  novelty. This drives the **rank**.

A living-off-the-land attacker (USR-042) can **cross the self-drift band early** (embedding wk15) yet **rank low on the
composite** (#31) because it is loud against its own past but modest against its security-cohort peers. That divergence
is the whole point and is why the threat-profile detector is primary. The Signal Separation "Reading the panels" note
explains this in-app.

**CUSUM caveat (USR-234 acid test):** the slow APT escapes BOTH self-drift lenses AND the composite ranking. Only the
threat-profile (c2_beacon + dga_dns) catches it. Any "drift catches all attackers" claim is wrong.

---

## 6. Data model — which tables carry USR-EVA

The EVA overlay was written into the **6 weekly gold tables** but NOT the 2 daily-snapshot tables.

| Table | Grain | Rows | Entities | Has EVA? | Feeds |
|---|---|---|---|---|---|
| `composite_scores` | per-entity | 251 | 251 | **YES** | ranks, FP, all Detection Story pages |
| `weekly_features` | entity×week | 17,570 | 251 | **YES** | feature-space CUSUM, radar |
| `weekly_trajectories` | entity×week | 17,570 | 251 | **YES** | embedding CUSUM, Drift Trajectory |
| `novelty_metrics` | per-entity | 251 | 251 | **YES** | novelty persistence |
| `zscored_features` | per-entity | 251 | 251 | **YES** | z-score heatmap |
| `detection_results` | per-entity | 251 | 251 | **YES** | verdict matrix, per-method counts |
| `behavioral_snapshots` | entity×**day** | 45,250 | **250** | **no** | daily embeddings (full horizon to 2026-04-29) |
| `trajectory_snapshots` | entity×**day** | 32,250 | **250** | **no** | Behavioral Drift page — **STALE, see §11** |

**Consequence:** every page that reads the 6 weekly gold tables shows EVA. The **Behavioral Drift** page
(daily `trajectory_snapshots`) and the **Digital Entity** per-entity inspector (needs an entity structure EVA
doesn't have) do NOT show EVA yet — see Pending (§11).

---

## 7. The USR-EVA overlay (why it is safe)

EVA is a **demo overlay**, added so the app can show an attacker that the drift+composite layer catches but the
known-bad detector misses. It must never disturb the canonical 250 numbers. It stays safe because:

- EVA is flagged **`is_attack = True`**, so `compute_group_zscores` computes each group's mean/σ from **normals only**
  and excludes EVA. The 250's group-z composites are frozen automatically.
- Population stats are frozen to the original 250 (`_compute_population_stats` monkeypatched in `scripts/integrate_eva.py`)
  so the 250's texts/embeddings are byte-identical (cache hits, no re-embed).
- EVA's composite (77.87) is the **highest**, so it does not lower the catch-all threshold (still 12.95) and is excluded
  from the 246-normal FP denominator. **250 canonical numbers are byte-identical to the gold CSVs.**
- Rebuild EVA with `python scripts/integrate_eva.py` (DRY_RUN flag at top). It appends only EVA to the gold CSVs + DB.

Product decision (user, this session): **"add EVA everywhere (4→5)"** — every page that enumerates attackers or shows a
count should include EVA and read /5, EXCEPT the threat-profile which is legitimately **4 of 5** (EVA evades it by design).

---

## 8. The canonical detection story (keep EVERY page consistent)

`traditional 0/5 → z-score 1/5 (noisy) → composite 5/5 (cleanly separates only 3/5) at 10.6% FP → threat-profile 4/5 at 0 FP.`

(For the REAL 4-attacker framing without the demo, this is 0/4 → 1/4 → 4/4 (2/4 clean) → 4/4; both framings appear —
the demo pages say /5, statements specifically about the four profiled/known-bad attackers say 4.)

---

## 9. The 16 pages (5 nav groups via `NAV_GROUPS`)

Page names are unchanged; find a page's code with `elif page == "<name>":`.

| Group | Page | Primary source | EVA shown? |
|---|---|---|---|
| **Data** | Raw Data | weekly gold | yes |
| | Guided Demo | weekly gold + detection_results | yes (5 attackers, scripted) |
| **The Detection Story** | Detection Pipeline | static + threat_profile_alerts | yes |
| | Traditional vs V-Intelligence UEBA | detection_results + composite | yes (matrix column) |
| | Three-Tier Detection | composite + detection + zscored | yes |
| | Detection Comparison | 6 weekly gold tables | yes (everywhere) |
| **Operations** | Dashboard / Alerts / Threat Profiles / Kill Chains | alerts, kill_chains, threat_profile_alerts | Threat Profiles = 4/5 |
| **Investigate an Entity** | Behavioral Drift | daily `trajectory_snapshots` | **NO (stale table, §11)** |
| | Drift Trajectory | `weekly_trajectories` | yes (full horizon + EVA tab) |
| | Behavioral Profile | weekly gold | selectable |
| | Digital Entity | `entity_structures.json` + static twin embed | **NO (no EVA structure, §11)** |
| **Methods & Proof** | Proof of Realism | weekly gold | 4 real (realism proof) |
| | Telemetry Explorer | bronze logs | n/a |

---

## 10. Conventions & rules (violating these is a defect)

1. **Never hardcode canonical numbers** (FP, ranks, counts, thresholds). Compute live from the DB. Denominators use
   `len(ATTACK_USERS)`. The one FP convention: catch-all threshold = **lowest attacker composite**, NOT `quantile(0.90)`.
2. **Never mislabel a scenario** (§3). USR-118 = recon fan-out; USR-042 = LOTL; USR-EVA = evasive insider (start wk35).
3. **Feature-CUSUM is our method, not traditional.** Do not list it among IF/SVM/LOF/Z-Score.
4. **EVA labeling:** always "evasive insider (demo)"; color `#16A085`. It is `is_attack`, caught by composite (rank #1),
   missed by threat-profile.
5. **Pentagon decks:** NO em-dashes or en-dashes.
6. **Plain business language** in buyer-facing copy; full technical rigor for the Pentagon audience — clearer, never dumbed down.
7. **One `st.columns(N)` gotcha:** if you index a column list by an attacker loop, size it `st.columns(len(...))`, never a
   literal 4/5 — a 5th attacker into `columns(4)` throws IndexError (this crashed the per-attacker breakdown once).
8. Prefer a **single data-driven table** over N hand-built card columns for any per-attacker×per-detector matrix
   (the "What Your SOC Analyst Sees" verdict matrix is the pattern).

---

## 11. Known issues / pending

- **`trajectory_snapshots` is STALE** — it only spans 2025-01-02 → 2025-05-10 (week 0→18) for the 250, even though the
  source `behavioral_snapshots` goes to 2026-04-29. So the **Behavioral Drift** page's daily charts freeze at May 2025
  and miss every attack after week 18. Fix: re-run `python -m pipeline.trajectory_snapshots` (derives from
  behavioral_snapshots, cosine only, no embeddings; ~2.5–3 h for all 181 days). **A re-run was in progress at last edit.**
- **EVA not on Behavioral Drift / Digital Entity.** To add it: (a) insert EVA into `behavioral_snapshots` at the 181
  snapshot dates (forward-fill EVA's weekly embeddings — no fresh API calls) then re-run `trajectory_snapshots`;
  (b) persist EVA's entity structure to `entity_structures.json` for the Digital Entity inspector.
- **Non-Detection-Story hardcoded 4-attacker lists** still exist on: Proof of Realism (`_ATTACK_LABELS`), Behavioral
  Drift caption (`_att_ids`), Digital Entity selector (`ATTACK_IDS_DE`). These were out of the Detection Story audit
  scope and are partly blocked on the two backfills above.

---

## 12. Verifying changes

- **Regenerate ground truth:** query the 6 weekly gold tables (see §4). Confirm 51.70/46.19/20.03/12.95, threshold 12.95,
  FP 26/246 = 10.6%, EVA #1/77.87.
- **Render check every page:** `python scripts/verify_pages.py` drives all 16 nav pages, **scrolls to force below-the-fold
  render + waits for the "Running" spinner to clear**, then checks the DOM for `stException` / traceback text.
  *A short static wait false-negatives real crashes — always use the scroll+wait checker.*
- Focused checks: `scripts/verify_detcomp.py` (Detection Comparison deep check + card count), `scripts/cap_story.py`
  (full-height screenshots of the 4 Detection Story pages).
- **Verify by actually viewing the visuals**, not only by matching numbers. Number-matching missed a live IndexError, a
  "#1 vs #2" card, mislabeled scenarios, and a mischaracterized attack — a human reviewer caught all of them.

---

## 13. Change record — Detection Story hardening (2026-07-12)

Integrated USR-EVA across all pages, refactored the SOC verdict to a data-driven table, added a "typical normal user
(median)" baseline, removed two redundant/misleading charts (Detection Timeline; per-attacker Drift-Vector with generic
"credential compromise" phases). A 3-reviewer line-by-line audit then fixed: USR-118 rank #1→#2 (multiple spots),
USR-234 #7→#8, EVA omissions, two off-by-200 code citations, hardcoded FP/"250"/rank strings, a CSV-fallback IndexError,
Feature-CUSUM-as-traditional, and the USR-118 "volume flood" → "recon fan-out" mischaracterization. See git log for commits.
