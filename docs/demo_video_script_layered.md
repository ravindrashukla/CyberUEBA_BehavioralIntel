# V-Intelligence UEBA — Demo Video Script (Layered Approach, v2)

18 scenes, ~7 min. Numbers are the session-verified set: traditional 0/4 · z-score 1/4 ·
composite 4/4 @ ~8% FP · known-bad profiles 4/4 @ 0 FP · slow APT in-band 97% of weeks.
Core thesis: **current methods ask "is this one number past a line?"; we measure the
DIRECTION of behavioral change, in layers — each layer catches what the last missed.**

---

**0 · Title** — *title card*
Detecting the undetectable. How nation-state attackers hide for years — and how a layered behavioral approach changes the outcome.

**1 · The problem** — *text*
Modern attackers don't break in — they blend in. They use legitimate credentials, standard protocols, and built-in system tools. They look exactly like your employees. The result: the average breach goes undetected for 287 days, costing nearly five million dollars.

**2 · Salt Typhoon** — *text*
Salt Typhoon — a Chinese state-sponsored group — penetrated nine US telecom providers including AT&T, Verizon, and T-Mobile, beginning around 2019. They accessed lawful-intercept wiretap systems and harvested call metadata of over a million users, including senior US officials. No deployed tool detected them. The FBI and CISA found it from the outside in September 2024 — after more than five years.

**3 · Volt Typhoon** — *text*
Volt Typhoon pre-positioned inside US critical infrastructure — energy, water, telecom, transportation — for over five years. Zero malware; only built-in tools like PowerShell and WMI. They authenticated with stolen valid credentials. No brute force, no anomalous behavior. Microsoft researchers found them in 2023 — not any deployed security system.

**4 · Four blind spots** — *text*
These are not isolated incidents. Four distinct attack types each exploit a different blind spot: nation-state campaigns that persist for years, insiders who quietly escalate over months, living-off-the-land intrusions that use only trusted tools, and slow campaigns spread across weeks to stay under every alert. No single method covers them all.

**5 · Why one method can't win** — *text*  *(edited: unifying root-cause line)*
Why does every single method fail? Signature detection looks for malware — there is none. Rule-based SIEM triggers on thresholds — the attacker stays below every one. Statistical anomaly tools flag individual outliers — no single metric is abnormal. Every one of these asks the same question: is this one number, right now, past a line? The stealth attacker keeps every number normal. The signal is never in one metric — it's in the accumulation, the combination, and the direction of change.

**6 · The innovation: a layered approach** — *text*  *(thesis + novelty line)*
Our innovation isn't a single trick — it's how we combine the evidence and apply it in layers. A traditional tool judges one signal, at one moment, against a fixed line. We measure magnitude AND direction — how far a behavior moves, and what kind of change it is — accumulated over time and weighed against a user's peers, then fused in layers so each layer catches what the last one missed. Cheap, fast signals catch the loud attacks early. An AI lens that reads the meaning of behavior catches the subtle ones. A fused score ranks the rest. And a set of known-bad profiles flags adversary techniques with zero noise. No commercial tool combines all of this. Same data — read in layers.

**7 · Layer 1 — point-anomaly baseline** — *detection-results heatmap*
Layer one is what most agencies run today: point-anomaly tools that score each user against a threshold. On four real campaigns embedded across 250 users over 70 weeks, these tools — Isolation Forest, One-Class SVM, and LOF — detect zero of four. A simple z-score catches one, the living-off-the-land case — but alarms on nearly everyone. Three attackers, including Salt Typhoon, stay invisible.

**8 · Layer 2 — behavioral entities** — *per-week → cumulative drift*
Layer two reads the same logs as living behavioral entities, tracked over time. On any given week the attacker still looks normal — the stealth APT sits inside the normal range 97% of the time. But behavior accumulates. Watch the same small drift add up week after week, and the slow movers separate from the crowd.

**9 · Signal separation — two lenses** — *feature + embedding CUSUM*
Two lenses make this concrete. A raw-magnitude lens measures how far each user moves from their own past — it flags the noisy, high-volume attack first, even before the AI. A semantic lens measures how far behavior drifts in meaning — it flags the subtle insider and stealth hacker roughly 30 weeks earlier. Each lens has a blind spot, and the slow APT crosses neither on drift alone — which is exactly why the next layers matter.

**10 · The hard case — the slow APT** — *USR-234 dual-CUSUM (NEW)*
Zoom in on the hardest case — the slow APT. On the raw-magnitude lens, and on the AI semantic lens, its cumulative drift never separates from the normal pack. It looks like an ordinary user on both. Drift alone will never catch it — and that is exactly the gap the next layers close.

**11 · Layer 3 — multi-phase fingerprint** — *radar*
Layer three asks five behavioral questions at once — signal strength, breadth, how long the change persisted, how far it diverged from the user's peers, and whether new connections keep recurring. Normal users cluster in a tight shape at the center. Each attacker pushes far past them on a different phase. No normal user is extreme on every front at once — and that is the fingerprint.

**12 · Layer 4 — fused composite** — *composite-by-rank*
Layer four fuses those five phases into a single ranked score. Now all four campaigns rise above the line that catches all four — including the two stealth movers that hid in the crowd a moment ago. The cost: catching all four this way flags about 8% of normal users for review.

**13 · Layer 5 — known-bad profiles** — *text*
Layer five removes that noise. Instead of asking only how far a user has drifted, it asks whether their behavior matches a measurable known-bad profile — a beacon's robotic timing, an algorithmically generated domain, a destination no peer ever contacts. On the same data, this layer flags all four campaigns at zero false positives — each alert named by the technique that fired.

**14 · The verdict** — *verdict frame*
The verdict, layer by layer. Traditional tools: zero of four. Intermediate statistics: one of four. The fused behavioral score: four of four. The known-bad profiles: four of four — at zero false positives. Same data. Same users. A fundamentally different understanding of behavior.

**15 · Results summary** — *stat frame*
V-Intelligence delivers measurable results. Four of four campaigns detected. Zero false positives on the profile match. A single ranked priority list. No threshold tuning. And every alert explainable, mapped to MITRE ATT&CK.

**16 · Federal alignment** — *text*
V-Intelligence is purpose-built for the federal and critical-infrastructure mission. It aligns with the Executive Order on Improving Cybersecurity, NIST continuous monitoring, and Zero Trust, and directly addresses CISA's guidance on living-off-the-land techniques — the behavioral intelligence layer perimeter and endpoint tools cannot deliver.

**17 · Closing** — *title card*
V-Intelligence. A layered behavioral approach to the threats traditional tools cannot see. 22nd Century Technologies.
