# V-Intelligence UEBA — Demo Walkthrough (PhD + Policy audience)

Goal: **explain the idea clearly**, then *show* it. No time limit — depth is fine, but every section
leads with plain language and only then adds the rigor. Two reader lenses are flagged throughout:
🎓 **(rigor)** for the researchers, 🏛 **(mission)** for the policy side.

---

## Part A — The one idea (whiteboard this before touching the app, ~5 min)

**The problem, in one sentence.** The attackers that matter most don't break in — they *log in*. Insiders
and nation-state actors use valid credentials and built-in tools, so on any single metric they look normal.
Every classical detector asks the same question — *"is this one number, right now, past a line?"* — and a
patient attacker simply keeps every number under the line.

**The shift.** Stop asking "is this value abnormal?" Ask two different questions:
1. **Has this entity's *behavior* changed — versus its own past?** (self-relative drift)
2. **Is this entity behaving unlike its *peers* — others with the same role?** (cohort-relative)

And read behavior as **meaning**, not magnitude.

**How we read "meaning."** For each entity, each week, we take its raw metrics and write them as **prose**,
one paragraph per behavioral zone (identity, access, data, network, risk). For example:
*"SOC Operator in Security: outbound traffic very high — 448 MB to 70 destinations, 0 DNS domains."*
We embed that prose into a **1536-dimensional vector** with a language model, so behaviors that *mean* the
same thing land near each other. Then we measure how that meaning **moves over time** and **stands against
peers**, and we fuse that with a handful of **measurable known-bad technique signatures** (a beacon's robotic
timing, algorithmically-generated domains, living-off-the-land process abuse).

**The payoff.** On four real-world campaign types hidden in 250 users over 485 days: classical tools catch
**0–1 of 4**; our fused score catches **4 of 4** (at a false-positive cost); and the technique-based detector
catches **4 of 4 with zero false positives**, each alert *named by the technique that fired* and mapped to
MITRE ATT&CK.

🎓 **(rigor)** Note the honesty up front: the prose we embed *deliberately includes derived signals*
(population z-scores, baseline ratios, an interpretive reading). That's feature engineering, not leakage —
the value is that the embedding captures the **combined** picture and we measure **drift** and **cohort
position** in that space, neither of which is a single threshold. Limitations are stated in Part C.

🏛 **(mission)** This matters because the campaigns we model are not hypothetical — **Salt Typhoon** sat in US
telecom for 5+ years; **Volt Typhoon** pre-positioned in critical infrastructure using only built-in tools.
No deployed tool found either; outside parties did. This is the gap behavioral intelligence is built to close.

---

## Part B — The guided walkthrough

Run the app (see Part D setup). Left nav: pick a **Section**, then a page.

### Act 1 — "You can't see it" (Section *Data* → *Raw Data*) · 4 min
**Say:** "250 users, 485 days, four hidden campaigns. This is the raw telemetry your SOC already collects."
Scroll the population table and sample logs (auth / file / network / DNS).

Scroll to **"Weekly Activity: All 250 Users."**
**Say:** "Each dot is one user's week. *Which four are the attackers?*" — pause — "You can't tell. The point
isn't a trick; it's that **no single metric is abnormal**."

Scroll to **"Same Data — Now With Attackers Highlighted."**
**Say:** "Here are the four. They sit **inside** the cloud." Point at the box plots: "On every feature, they
fall within the normal range."
🎓 **(rigor)** "These are per-entity aggregates; the attackers are 96th–97th percentile on a couple of volume
features and *below* normal on others — never the extreme outlier. That's by design and we prove it later."

### Act 2 — "Catch cheap, escalate smart" (Section *The Detection Story* → *Detection Pipeline*) · 3 min
**Say:** "We run detection in layers — cheap and fast first, deep and expensive last. Layer 1 known-bad
signatures, Layer 2 peer comparison, Layer 3 single-signal drift, Layer 4 the fused 'Composite Scoring' lens."
Point at the bottom banner: "All four caught — the known-bad layer at **0 false positives**, the fused score
at **10.6%** — each at its earliest, cheapest point."
🏛 **(mission)** "This is operationally important: an analyst's scarcest resource is attention. Cheap layers
clear the easy cases so the deep lens is spent only on the genuinely subtle."

### Act 3 — The comparison (Section *The Detection Story* → *Detection Comparison*) · 5 min
Scroll to **"What Your SOC Analyst Sees."** Read across the four columns, then the aligned conclusion band:
- **Traditional SIEM** (Isolation Forest / SVM / LOF): **0 of 4**.
- **Z-score**: **1 of 4** (the LOTL spike) — and it alarms on normals too.
- **Composite Scoring**: **4 of 4**, but the two stealth attacks rank low, so catching them costs **10.6%** FP.
- **Threat-Profile Detector**: **4 of 4 at 0% FP**, each named by technique.

🎓 **(rigor)** "Z-score 'catching' USR-042 is one feature at 3.04σ — *and* 24 normal users trip the same rule.
The composite asks a different question (cohort-relative, multi-phase), so USR-042's narrow spike ranks low.
Neither magnitude method is the *clean* catch — the technique detector is."
🏛 **(mission)** "Four tools, same data, four verdicts. The right-most column is the capability you don't have today."

### Act 4 — Why the stealth pair ranks low (Section *The Detection Story* → *Three-Tier Detection*) · 3 min
Scroll to **"Attack Campaign Composite Scores."**
**Say:** "USR-118 (#1) and USR-156 (#2) separate cleanly. The slow APT **USR-234 is #7**; the LOTL **USR-042 is
#30** — buried among normal users. No magnitude method cleanly separates the stealth pair. That's *expected*,
and it's exactly why we don't rely on magnitude alone."

### Act 5 — The primary detector (Section *Operations* → *Threat Profiles*) · 4 min
**Say:** "**4 flagged, 4/4 caught, 0 false positives, 100% precision** — and not a black-box number. Each flag
carries the measured technique: insider → mass collection + a destination no peer touches; slow APT → C2 beacon
+ DGA; Volt Typhoon → living-off-the-land; Salt Typhoon → network fan-out."
🎓 **(rigor)** "Every comparison is **within the entity's role-group cohort** — 'unusual' means unusual *for that
job*, computed with robust median/IQR so small or quiet cohorts don't blow up the statistics."

### Act 6 — What an analyst actually works (Section *Operations* → *Alerts*, then *Kill Chains*) · 3 min
**Alerts:** "Four confirmed intruders, zero false positives, each in plain English — not 25,000 noisy alerts."
**Kill Chains:** "Each intruder's progression in MITRE order — recon → C2 → exfil — assembled from the
techniques that fired."
🏛 **(mission)** "Explainability is a procurement and oversight requirement, not a nicety. Every alert here is
auditable and maps to a recognized framework."

### Act 7 — How the 'digital twin' is built (Section *Investigate an Entity* → *Digital Entity*) · 4 min
Default USR-042; expand **Stage 3: Text Serialization**.
**Say:** "This is the engine, end to end: raw features → prose per zone → 1536-d embedding → tracked over time.
Look at the network zone — *'outbound traffic very high: 448 MB, 70 destinations, 0 DNS domains.'* That's the
tell, expressed as language, which is what lets the model place it near other exfiltration-like behavior."
🎓 **(rigor)** "Five zones are embedded separately and composed by context-adaptive attention (identity is kept
as a static reference, not averaged in). The composite is built from week-to-week **drift** in that space, then
z-scored within the role group."

### Act 8 — Is the data honest? (Section *Methods & Proof* → *Proof of Realism*) · 4 min
**Say:** "Pick the slow APT vs a normal user. On aggregate stats it's **'elevated, not extreme' — 96th–97th
percentile** and *lower* than normal on some features. Scroll to the raw logs: its C2 beacons are **120–487-byte
packets** buried in traffic where one web request exceeds 200,000 bytes. It genuinely hides — and we still catch it."
🎓 **(rigor)** "This is the falsification check: if the synthetic attackers were obvious outliers, the result
would be meaningless. They aren't, so the catch is meaningful."

---

## Part C — Methodology & honest limitations (🎓 for the researchers) · as long as they want

**Data layers (medallion).** Bronze = raw per-day log CSVs (auth, network, dns, endpoint, app, privilege,
file). Silver = `daily_features` (one row/user/day). Gold = `behavioral_snapshots` (the 1536-d zone embeddings
+ drift). Detection outputs live in the database; the app reads the DB as the single source of truth.

**The digital entity.** `models/hierarchical_zones.py` serializes each zone to interpretive prose;
`embeddings/` embeds (OpenAI `text-embedding-3-small`, 1536-d, disk-cached) and composes zones by attention.
Drift = `1 − cosine similarity` vs the entity's own first-weeks baseline.

**Detection fronts.** (1) Cohort-relative IQR-z of late-period features *within role group* (recon fan-out,
mass collection, LOTL process, cohort-rare destination …). (2) Raw-event technique signatures (C2-beacon
timing regularity, DGA entropy) — label-free, no peer baseline. (3) Self-drift as supporting corroboration.
Composite scoring fuses five phases (signal strength, breadth, sustained deviation, context divergence,
novelty persistence), z-scored within the role group against normals only.

**The catch-all-four false-positive rate (10.6%)** is the % of normal users scoring at or above the *lowest*
attacker composite — i.e., the cost of a threshold low enough to catch all four. It's computed live; never a
frozen number.

**Honest limitations — say these unprompted to a PhD audience:**
- **Statistical power.** One synthetic enterprise, fixed seed, **four** positives. Every rate/rank is
  *indicative, not powered*. The contribution is the *method and the honest comparison*, not a benchmark.
- **The embedding encodes derived signals.** The serialized prose contains z-scores and an interpretive reading,
  so the "semantic lens" is partly reading signals the pipeline computed. This is intentional feature
  engineering (combine everything into one representation; measure drift/cohort position there) — but it means
  the embedding is *not* an independent re-derivation, and we don't claim it is.
- **Role/department is part of the model, on purpose.** Detection is cohort-relative, so an entity's role
  *defines its peer set* and its identity is legitimate context. A label change can move a score — that's the
  model correctly responding to changed context, not a bug.
- **Known engineering notes.** Two telemetry streams (privilege, app) are not yet per-user-profile-driven; a
  couple of attack injectors hardcode source IPs; the legacy `db/schema.sql` is superseded by migrations.
  None affect the detection story; all are documented.

---

## Part D — Mission & policy framing (🏛 for the policy folks)

**The threat is current and proven.** Salt Typhoon (PRC) — 5+ years inside US telecom, lawful-intercept
systems, call metadata of senior officials; found from the outside in 2024. Volt Typhoon — pre-positioned in
energy/water/transport using only living-off-the-land techniques; found by researchers, not deployed defenses.
Both are exactly the "looks normal, never trips a threshold" pattern this system targets.

**Why behavioral intelligence, for government.**
- **Same data you already collect** — no new sensors; reads existing DODIN/enterprise logs.
- **Explainable & auditable** — every alert names the technique and maps to MITRE ATT&CK; no black-box score.
- **Low-and-slow coverage** — catches insiders and APTs that stay inside every threshold for months.
- **Deployable where you operate** — containerized; on-prem or in an enclave; no data egress required.

**Alignment.** Supports continuous monitoring and Zero Trust (behavior-based, not perimeter), the spirit of
EO 14028 / NIST CSF continuous monitoring, and CISA's living-off-the-land guidance — the behavioral layer that
perimeter and endpoint tools cannot provide.

**Setup (off-screen).**
```bash
docker-compose -f docker-compose.enhanced.yml up -d
DATABASE_URL_HOST='postgresql://cyber_ueba:password@127.0.0.1:5438/cyber_ueba' DB_HOST='127.0.0.1' DB_PORT='5438' \
python -m streamlit run streamlit_app.py --server.port 8502 --server.headless true
# → http://localhost:8502
```

---

## Part E — Anticipated questions

- *"Z-score already caught USR-042 — why the rest of this?"* → "Defense in depth: each attacker needs only
  **one** layer. USR-042 is caught by z-score *and* the technique detector. The value is the **other three**
  that z-score misses — and that z-score's one catch comes with 24 false alarms."
- *"Why does the sophisticated score rank USR-042 below where z-score flags it?"* → "Different questions.
  Z-score: any single feature past 3σ. Composite: has the whole, cohort-relative pattern shifted? USR-042's
  narrow LOTL spike doesn't, so it ranks low. Neither magnitude method is the clean catch — the technique
  detector is."
- *"Is the AI just re-detecting your own z-scores?"* → "Partly, and we say so (Part C). The embedding's job is
  to combine many signals into one representation and let us measure *drift* and *cohort position* there — not
  to independently rediscover a threshold."
- *"How would this do on real data / at scale?"* → "This is a controlled synthetic study (4 positives, one
  seed) — indicative, not powered. The architecture is data-agnostic; the honest next step is a labeled
  real-world pilot."
- *"False positives in production?"* → "The primary detector is 0 FP here because it matches **measurable
  known-bad techniques in role-group context**, not thresholds. Real-world FP is an empirical question for a pilot."
