# V-Intelligence UEBA — Live Demo Walkthrough

A click-by-click script to **walk a prospect through the app**. ~15–20 min for the core path;
add the optional deep-dives for a technical audience.

---

## 0. Before you start (2 min, off-screen)

- Bring up the stack and app:
  ```bash
  docker-compose -f docker-compose.enhanced.yml up -d
  DATABASE_URL_HOST='postgresql://cyber_ueba:password@127.0.0.1:5438/cyber_ueba' DB_HOST='127.0.0.1' DB_PORT='5438' \
  python -m streamlit run streamlit_app.py --server.port 8502 --server.headless true
  ```
  Open **http://localhost:8502** and confirm the left nav loads (5 sections).
- Left nav: pick a **Section** from the dropdown, then a page from the radio list.
- The numbers you'll quote (all computed live from the DB):
  - 250 users · 485 days · 4 hidden attack campaigns.
  - Detection ladder: **Traditional 0/4 → Z-score 1/4 → Composite 4/4 at 10.6% FP → Threat-Profile 4/4 at 0 FP.**
  - The 4 attackers: **USR-118** Salt Typhoon (#1, 51.7) · **USR-156** insider (#2, 46.2) · **USR-234** slow APT (#7, 20.0) · **USR-042** Volt Typhoon LOTL (#30, 12.9).

**One-sentence thesis (say this up front):**
> "The most dangerous attackers don't break in — they log in. They never trip a threshold. We read the
> *same logs you already collect* as behavioral entities and catch all four — and the primary detector does it
> with zero false positives."

---

## ACT 1 — The problem (Start Here → **Story Mode**) · 3 min

**Click:** Section *Start Here* → *Story Mode*.

**Say:** "250 users, 485 days, four real attack campaigns hidden inside. Here's the raw telemetry your SOC
already sees — auth, file, network, DNS." Scroll the sample logs.

**Click down to "Weekly Activity: All 250 Users" (the scatter).**
**Say:** "Each dot is one user's week. *Can you spot the attacker?* You can't — and neither can a threshold."

**Scroll to "Same Data — Now With Attackers Highlighted."**
**Say:** "Here are the four, color-coded. They sit **inside the normal cloud** — their aggregate stats look
ordinary. That's the whole problem: nothing is individually abnormal."
**Point at** the box plots below: "On every single feature, the attackers fall inside the normal range."

> Transition: "So how do we catch what looks normal? We layer detection."

---

## ACT 2 — The approach (The Detection Story → **Detection Pipeline**) · 2 min

**Click:** Section *The Detection Story* → *Detection Pipeline*.

**Say:** "We don't run one detector — we run layers, cheap-and-fast first, expensive-and-deep last.
- **Layer 1** known-bad signatures — catches the obvious ones the instant their fingerprint appears.
- **Layer 2** peer comparison — odd-one-out vs the team.
- **Layer 3** single-signal drift — one loud number climbing.
- **Layer 4** the fused 'Composite Scoring' lens for the subtle ones."

**Point at** the bottom banner: "Result: all 4 caught — the known-bad layer at **0 false positives**, the fused
score at **10.6%**. Each attacker caught at its earliest, cheapest point."

---

## ACT 3 — The money slide (The Detection Story → **Detection Comparison**) · 4 min

**Click:** *Detection Comparison*. Scroll to **"What Your SOC Analyst Sees."**

**Say, pointing left to right across the four columns:**
- "**Traditional SIEM** — Isolation Forest, SVM, LOF: **0 of 4**. Every attacker reads NORMAL."
- "**Z-score** — catches **1 of 4** (the LOTL spike) but alarms on normals too. Cheap, noisy — but hey, one's caught."
- "**Composite Scoring** — **4 of 4**, but the two stealth attacks rank low, so catching them costs **10.6%** false positives."
- "**Threat-Profile Detector** — **4 of 4 at 0% false positives**, and *every alert is named by its technique*."

**Point at** the aligned **conclusion band**: "Same data, same users — four very different verdicts. That last
column is the product."

> Transition: "Let me show you why the fused score buries two of them — and why that's fine."

---

## ACT 4 — The scores (The Detection Story → **Three-Tier Detection**) · 2 min

**Click:** *Three-Tier Detection*. Scroll to **"Attack Campaign Composite Scores."**

**Say:** "The fused score ranks every user. **USR-118 (#1) and USR-156 (#2)** separate cleanly. But the slow APT
**USR-234 is #7** and the LOTL **USR-042 is #30** — buried among normal users. No magnitude method cleanly
separates the stealth pair. *That's expected* — and it's exactly why we have a detector that doesn't rely on
magnitude."

---

## ACT 5 — The payoff (Operations → **Threat Profiles**) · 3 min

**Click:** Section *Operations* → *Threat Profiles*.

**Say:** "This is the primary detector. **4 entities flagged, 4 known attacks caught, 0 false positives, 100%
precision.** And it isn't a black-box score — each flag carries the **measured technique**:
- USR-156 insider — mass collection + contacts a destination no peer uses.
- USR-234 slow APT — C2 beacon (robotic schedule) + DGA domains.
- USR-042 Volt Typhoon — living-off-the-land process abuse.
- USR-118 Salt Typhoon — network fan-out."

**Say:** "Notice these compare each entity **to its own role-group peers** — so 'unusual' means unusual *for that
job*, not for the company."

---

## ACT 6 — What the SOC actually works (Operations → **Alerts** → **Kill Chains**) · 2 min

**Click:** *Alerts*.
**Say:** "An analyst opens this and sees **four confirmed intruders, zero false positives**, each in plain English —
not 25,000 noisy alerts. 'USR-234 calls home to one fixed server on a robotic schedule.' That's actionable."

**Click:** *Kill Chains*.
**Say:** "And we reconstruct each intruder's progression in MITRE ATT&CK order — recon → C2 → exfil — built from
the techniques that actually fired, not guesswork."

---

## ACT 7 — How it works (Investigate an Entity → **Digital Entity**) · 2 min

**Click:** Section *Investigate an Entity* → *Digital Entity*. Default is USR-042; expand **Stage 3**.

**Say:** "Here's the engine. Each entity's raw metrics become **prose per behavioral zone** — identity, access,
data, network, risk — then a 1536-d embedding. Watch the network zone: *'Outbound traffic very high: 448 MB,
70 destinations, 0 DNS domains'* — that's the tell, in language. We track how that meaning **drifts over time**."

---

## ACT 8 — Credibility (Methods & Proof → **Proof of Realism**) · 2 min

**Click:** Section *Methods & Proof* → *Proof of Realism*.

**Say:** "Fair question: is the data rigged? No. Pick the slow APT vs a normal user. On aggregate stats it's
**'elevated, not extreme' — 96th–97th percentile, never the outlier**, and *lower* than normal on some features.
Scroll to the raw logs: its C2 beacons are **tiny 120–487-byte packets** buried among normal traffic where one
web request is 200,000 bytes. It genuinely hides — and we still catch it."

---

## Close · 1 min

> "Same logs you already collect. Four nation-state-grade campaigns that every traditional tool missed — caught,
> **4 of 4 at zero false positives**, each named by technique and mapped to MITRE. Deployable in your enclave.
> That's behavioral intelligence the perimeter can't give you."

---

## Optional deep-dives (technical audience)

- **Behavioral Drift** — "Top drifters are *not* the intruders (they rank #49–#130). Raw drift magnitude misses
  stealth — which is the point."
- **Behavioral Profile** (USR-234) — per-signal, self-relative; "this is why drift alone misses the slow APT."
- **Drift Trajectory** — one entity vs its cohort band over 70 weeks.
- **Telemetry Explorer** — browse raw logs; toggle "attack-labeled rows only."
- **Traditional vs V-Intelligence UEBA** — the full detection matrix + honesty callout (removed the methods that
  "detected everything" only by flagging ~100% of users).

## Likely questions (have answers ready)

- *"Z-score already caught USR-042 — why bother?"* → "Great — defense in depth. Each attacker only needs **one**
  layer. USR-042 is caught by z-score *and* the threat-profile. The point is the **other three** that z-score misses."
- *"Why does the fancy composite rank USR-042 lower than z-score flags it?"* → "Different questions. Z-score asks
  'any single feature past 3σ?' — and it flags 24 normal users alongside it. Composite asks 'has the whole,
  cohort-relative pattern shifted?' — USR-042's narrow LOTL spike doesn't, so it ranks low. Neither magnitude
  method is the clean catch — the **technique-based** detector is."
- *"Is this real data?"* → Proof of Realism page; real OpenAI embeddings are mandatory; bronze logs are real CSVs.
- *"False positives in production?"* → "The primary detector is 0 FP here because it matches **measurable
  known-bad techniques** in role-group context, not thresholds."

> Numbers are computed live from the database; if a score moved after a data change, the app reflects it —
> never quote a frozen figure that contradicts the screen.
