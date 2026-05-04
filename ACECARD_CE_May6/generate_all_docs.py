"""Generate all documents for ACECARD CE May 6, 2026 event."""
import os
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

OUT_DIR = os.path.dirname(__file__)


def _style(doc):
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    style.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
    for level in range(1, 4):
        hs = doc.styles[f"Heading {level}"]
        hs.font.color.rgb = RGBColor(0x00, 0x2B, 0x5C)
        hs.font.name = "Calibri"


def _bold_para(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    return p


def _bullet(doc, text, bold_prefix=None):
    p = doc.add_paragraph(style="List Bullet")
    if bold_prefix:
        run = p.add_run(bold_prefix)
        run.bold = True
        p.add_run(" -- " + text)
    else:
        p.add_run(text)


# ═══════════════════════════════════════════════════════════════
# DOCUMENT 1: SOLUTION BRIEF (1-2 pages)
# ═══════════════════════════════════════════════════════════════
def build_solution_brief():
    doc = Document()
    _style(doc)

    # Header
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("ACECARD CE -- Solution Brief")
    run.font.size = Pt(22)
    run.bold = True
    run.font.color.rgb = RGBColor(0x00, 0x2B, 0x5C)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(
        "Preemptive Cyber Defense + Behavioral Trajectory Intelligence\n"
        "A Containerized, Cloud-Native Prototype for Gabriel Nimbus"
    )
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(0x4A, 0x55, 0x68)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("22nd Century Technologies (TSCTI)  |  Rigor AI Inc.")
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    # ── PROBLEM STATEMENT ──
    doc.add_heading("Problem Statement", level=1)
    doc.add_paragraph(
        "SOC analysts spend 60-80% of their time on manual context reassembly -- "
        "pulling data from siloed log tables, correlating identities across AD/AAD/"
        "Okta/AWS/K8s, and triaging anomaly alerts that say 'something is weird' "
        "without saying WHAT or WHY. Meanwhile, nation-state adversaries (Volt "
        "Typhoon, Salt Typhoon) use Living-off-the-Land tradecraft that never "
        "triggers threshold-based alerts. Current tools cannot answer the critical "
        "question: 'What is this entity BECOMING?'"
    )

    doc.add_heading("Four Challenges This Solution Addresses", level=2)

    table = doc.add_table(rows=5, cols=2)
    table.style = "Light Grid Accent 1"
    table.columns[0].width = Inches(2.5)
    table.columns[1].width = Inches(4.0)
    table.rows[0].cells[0].text = "Challenge"
    table.rows[0].cells[1].text = "How We Solve It"
    data = [
        ("Manual context reassembly across data tables",
         "Unified 1536-d behavioral embedding fuses ALL log sources into one vector per entity. "
         "No manual joins. One API call returns drift, direction, health, and MITRE mapping."),
        ("Inconsistent analytics from siloed log architecture",
         "Five signal serializers (auth, process, network, file, identity) normalize events "
         "from any source (ECS/OCSF/STIX) into a single coherent pipeline."),
        ("Scalability constraints",
         "Containerized (Iron Bank-compatible), K8s-deployed. <3 seconds per entity window. "
         "10,000 entities/hour on 4-vCPU. Horizontal scaling via replicas."),
        ("Operational inefficiency from manual data wrangling",
         "Fully automated pipeline: ingest -> normalize -> serialize -> embed -> analyze -> "
         "alert -> enforce. Zero manual work. ABAC trust loop auto-restricts access."),
    ]
    for i, (challenge, solution) in enumerate(data):
        row = table.rows[i + 1]
        row.cells[0].text = challenge
        row.cells[1].text = solution

    # ── SOLUTION ARCHITECTURE ──
    doc.add_heading("Solution Architecture: Two Layers", level=1)

    doc.add_heading("Layer 1: Rigor AI -- Preemptive Defense", level=2)
    doc.add_paragraph(
        "Builds a formal mathematical model of every NGFW, IPS, IdP, SASE, and WAF "
        "configuration. Uses symbolic reasoning (not sampling) to mathematically PROVE "
        "which attack paths exist across the entire 2^8000 configuration state space. "
        "Closes paths before exploitation."
    )
    _bullet(doc, "Formal verification of firewall/segmentation configs against MITRE ATT&CK TTP graphs")
    _bullet(doc, "Continuous re-verification on every config change (hourly or per-change)")
    _bullet(doc, "Risk-prioritized remediation with vendor-specific fix instructions")
    _bullet(doc, "Covers: T1190 (edge exploit), T1133 (remote services), T1556 (auth modification)")

    doc.add_heading("Layer 2: ACECARD UEBA -- Behavioral Detection", level=2)
    doc.add_paragraph(
        "Tracks every user, device, and network segment as a 1536-dimensional behavioral "
        "embedding. Detects structural drift over time using CUSUM change-point detection. "
        "Explains WHAT the entity is drifting toward via cosine projection onto 8 MITRE-mapped "
        "threat concepts."
    )
    _bullet(doc, "5 behavioral signals: auth, process, network, file, identity")
    _bullet(doc, "CUSUM catches slow drift (APT dwell) that never crosses fixed thresholds")
    _bullet(doc, "Drift direction: 'drifting toward lateral_movement (T1021) at 0.78 projection score'")
    _bullet(doc, "Peer cohort z-score comparison (role/OU/group context)")
    _bullet(doc, "ABAC trust loop: auto-enforces step-up MFA, restrict, or block based on health score")

    doc.add_heading("Why Both Layers Are Required", level=2)
    doc.add_paragraph(
        "Rigor prevents what CAN be prevented (misconfiguration, known TTP paths). "
        "ACECARD detects what CANNOT be prevented (zero-days, stolen credentials, "
        "insider threats, LOtL tradecraft). Neither alone is sufficient. Together "
        "they cover the complete attack lifecycle."
    )

    # ── PROOF IT WORKS ──
    doc.add_heading("Proof: Working Prototype", level=1)
    _bullet(doc, "Docker-compose prototype running NOW: PostgreSQL+pgvector, FastAPI API, background worker")
    _bullet(doc, "270 days of synthetic event data with 6 injected attack scenarios (including Volt/Salt Typhoon TTPs)")
    _bullet(doc, "Mock embedding pipeline: 5 signals -> 1536-d vectors -> CUSUM -> drift direction -> alerts")
    _bullet(doc, "7-chart Plotly dashboard: drift timeline, velocity/acceleration, change-points, health gauge, radar, signal decomposition, peer scatter")
    _bullet(doc, "Kill-chain reconstruction linking multi-phase attacks into MITRE-sequenced narratives")
    _bullet(doc, "Proven foundation: E-11 Temporal Trajectory Intelligence running at DLA with 500+ entities")

    # ── DEPLOYMENT ──
    doc.add_heading("Deployment Readiness", level=1)
    _bullet(doc, "Containerized (OCI-compliant, Iron Bank-compatible base images)")
    _bullet(doc, "Gabriel Nimbus ready: cloud-native, K8s Helm chart, cATO-aligned CI/CD")
    _bullet(doc, "Multi-enclave: IL5 (NIPR) / IL6 (SIPR) / JWICS -- local SLM for air-gapped embedding")
    _bullet(doc, "Auth: Bearer token (dev) / CAC/PIV mTLS (production)")
    _bullet(doc, "Schema: ECS, OCSF, STIX 2.1 normalized input")
    _bullet(doc, "Observability: Prometheus metrics, OpenTelemetry traces, structured JSON logs")

    # ── TEAM ──
    doc.add_heading("Team Credentials", level=1)
    doc.add_paragraph(
        "22nd Century Technologies (TSCTI): $90M U.S. Army SOC/MDR contract "
        "(800+ cleared analysts), USAF $108M, FBI TSC $56M, NAVAIR/USMC $145M."
    )
    doc.add_paragraph(
        "Rigor AI Inc.: 20+ design partners across F500, federal, critical "
        "infrastructure, MSSPs, and nation states. Formal verification engine "
        "with production findings in financial services, telecom, and government."
    )

    return doc


# ═══════════════════════════════════════════════════════════════
# DOCUMENT 2: BREAKOUT SESSION TALKING POINTS
# ═══════════════════════════════════════════════════════════════
def build_breakout_points():
    doc = Document()
    _style(doc)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Breakout Session Talking Points")
    run.font.size = Pt(22)
    run.bold = True
    run.font.color.rgb = RGBColor(0x00, 0x2B, 0x5C)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("ACECARD CE  |  06 MAY 2026  |  Internal Preparation")
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    # ── SESSION 1: LIMITING FACTORS ──
    doc.add_heading("Session: Current Limitations (0925-1020)", level=1)
    doc.add_paragraph(
        "Goal: Demonstrate deep understanding of WHY current tools fail. "
        "Establish credibility. Do not pitch -- diagnose."
    )

    doc.add_heading("Limitation 1: Manual Context Reassembly", level=2)
    _bullet(doc, "An analyst investigating one alert touches 6-12 data tables (auth logs, process logs, network flows, file audit, identity changes, threat intel)")
    _bullet(doc, "Each table has different schema, different timestamps, different entity ID formats")
    _bullet(doc, "Correlation is manual: copy entity ID, paste into next query, wait, repeat")
    _bullet(doc, "Average triage time: 30-45 minutes per alert. At 500 alerts/day, most are never investigated")
    _bullet(doc, "Volt Typhoon exploited this: each action was 'normal' in its own silo. Only the cross-table pattern revealed the attack")

    doc.add_heading("Limitation 2: Siloed Log Architecture Fragments Identity", level=2)
    _bullet(doc, "A single user has identities in AD, Azure AD, Okta, AWS IAM, K8s, VPN, and email")
    _bullet(doc, "Each system logs independently with different identifiers (SAMAccountName, UPN, email, ARN, service account)")
    _bullet(doc, "Lateral movement across 5 systems reads as 5 separate 'normal' logins -- not 1 attack chain")
    _bullet(doc, "Salt Typhoon used stolen TACACS+ credentials on routers + AD credentials on servers -- two identity silos, one attacker")
    _bullet(doc, "No commercial product fuses these into a single behavioral trajectory per real-world entity")

    doc.add_heading("Limitation 3: Threshold-Based Detection Cannot See LOtL", level=2)
    _bullet(doc, "Every tool Volt Typhoon used (wmic, ntdsutil, netsh, rundll32, vssadmin) is a legitimate Microsoft binary")
    _bullet(doc, "Sigma/YARA rules exist but PRC actors test against them pre-campaign -- detection coverage decays monthly")
    _bullet(doc, "No threshold catches 'a finance analyst running wmic for the first time' -- the event is individually normal")
    _bullet(doc, "The signal is in the TRAJECTORY: behavior changing slowly over weeks, not in any single event")
    _bullet(doc, "Current UEBA gives 'anomaly score 87%' -- no hypothesis, no MITRE mapping, no direction. Triage time explodes")

    doc.add_heading("Limitation 4: Scalability of Current Approaches", level=2)
    _bullet(doc, "Manual correlation does not scale past ~50 entities under active investigation")
    _bullet(doc, "Rule-based SIEM detection requires constant rule maintenance (1000+ rules, each needs updating)")
    _bullet(doc, "ASM/BAS can only sample a tiny fraction of the 2^8000 config state space")
    _bullet(doc, "Current architecture requires separate analytics for each log source -- N sources = N analytics pipelines")
    _bullet(doc, "Gabriel Nimbus scale: potentially 100K+ entities across Army Cyber. Current tools cannot keep up")

    # ── SESSION 2: WAYS TO OVERCOME ──
    doc.add_heading("Session: Ways to Overcome Limiting Factors (1040-1140)", level=1)
    doc.add_paragraph(
        "Goal: Introduce the solution architecture. Be specific about HOW. "
        "Not 'we should use AI' -- show the actual pipeline."
    )

    doc.add_heading("Overcome 1: Unified Behavioral Embedding Eliminates Manual Reassembly", level=2)
    _bullet(doc, "All 5 log types (auth, process, network, file, identity) feed into one embedding per entity per time window")
    _bullet(doc, "The embedding IS the fused context -- no manual joins needed")
    _bullet(doc, "One API call: GET /api/trajectory/{entity}/dashboard returns drift, velocity, CUSUM, health, top-3 threat concepts, MITRE technique IDs, peer z-score")
    _bullet(doc, "Analyst goes from 'investigate this alert' to 'full context' in <3 seconds, not 30-45 minutes")

    doc.add_heading("Overcome 2: Cross-Identity Fusion via Composite Digital Signature", level=2)
    _bullet(doc, "Entity resolution layer maps AD/AAD/Okta/AWS/K8s identities to a single entity_uuid")
    _bullet(doc, "All signals from all identity systems contribute to ONE behavioral embedding")
    _bullet(doc, "Lateral movement across 5 systems is ONE strong signal, not 5 weak signals")
    _bullet(doc, "Hash entity IDs before embedding (SHA-256) -- no PII sent to embedding provider")

    doc.add_heading("Overcome 3: Behavioral Trajectory Catches LOtL Without Thresholds", level=2)
    _bullet(doc, "Instead of 'is this event bad?' --> 'is this entity BECOMING something different?'")
    _bullet(doc, "CUSUM (Cumulative Sum) catches sustained small drift that accumulates over weeks/months")
    _bullet(doc, "Drift direction: cosine projection onto 8 MITRE-mapped threat concepts")
    _bullet(doc, "Output: 'Entity drifting toward lateral_movement (T1021, score 0.78)' -- actionable, directional, MITRE-mapped")
    _bullet(doc, "Per-signal decomposition: analyst sees which signal is driving drift (auth? process? network?)")

    doc.add_heading("Overcome 4: Cloud-Native Architecture Scales to Gabriel Nimbus", level=2)
    _bullet(doc, "Containerized: Iron Bank base images, OCI-compliant, K8s Helm chart")
    _bullet(doc, "10,000 entities/hour on 4-vCPU node; horizontal scaling via replicas")
    _bullet(doc, "Unified pipeline: 1 pipeline handles ALL log types (not N separate pipelines)")
    _bullet(doc, "Schema normalization (ECS/OCSF/STIX 2.1) means new log sources plug in without code changes")
    _bullet(doc, "Multi-enclave: IL5/IL6/JWICS with local SLM fallback for air-gapped embedding")

    doc.add_heading("Overcome 5: Preemptive Layer (Rigor AI) Closes the Config Gap", level=2)
    _bullet(doc, "Formal mathematical model of ALL defensive controls (NGFW, IdP, IPS, SASE, WAF)")
    _bullet(doc, "Exhaustive analysis of 2^8000 state space -- not sampling, PROVING")
    _bullet(doc, "Continuous re-verification on every config change")
    _bullet(doc, "Closes attack paths BEFORE exploitation -- the 99% misconfiguration problem solved")
    _bullet(doc, "Integration: Rigor's verified coverage map adjusts ACECARD's sensitivity thresholds")

    # ── SESSION 3: SOLUTION BRIEF PREP ──
    doc.add_heading("Session: Problem Statement & Solution Brief (1305-1405)", level=1)
    doc.add_paragraph(
        "Goal: Develop the formal problem statement and solution brief for "
        "the presentation slot. Use the Solution Brief document."
    )

    doc.add_heading("Problem Statement (Draft)", level=2)
    p = doc.add_paragraph()
    run = p.add_run(
        "Current SOC tooling cannot detect Living-off-the-Land cyber operations "
        "because: (1) threshold-based detection misses legitimate-tool abuse, "
        "(2) siloed log analytics fragment identity across systems, "
        "(3) anomaly scores lack direction and MITRE mapping, and "
        "(4) manual context reassembly consumes analyst capacity. "
        "A containerized, cloud-native solution is needed that automatically "
        "fuses behavioral signals from all log sources into a unified trajectory "
        "per entity, detects structural behavioral drift using statistical "
        "change-point detection, and explains drift direction with MITRE ATT&CK "
        "mapping -- while operating at Gabriel Nimbus scale."
    )
    run.italic = True

    doc.add_heading("Key Differentiators to Emphasize", level=2)
    _bullet(doc, "NOT anomaly detection -- behavioral TRAJECTORY (time-series shape)")
    _bullet(doc, "NOT threshold alerts -- CUSUM cumulative change-point detection")
    _bullet(doc, "NOT 'something is weird' -- drift DIRECTION with MITRE technique IDs")
    _bullet(doc, "NOT a concept -- working Docker prototype with synthetic Volt/Salt Typhoon scenarios")
    _bullet(doc, "NOT just detection -- preemptive config verification (Rigor) + behavioral detection (ACECARD)")
    _bullet(doc, "Proven: E-11 Temporal Trajectory Intelligence running at DLA with 500+ entities")

    # ── PRESENTATION TIPS ──
    doc.add_heading("Presentation Slot (1420-1535)", level=1)
    doc.add_paragraph(
        "Multiple teams present. Keep it tight. Lead with the problem, show the "
        "solution, prove it works."
    )

    doc.add_heading("Suggested Structure (10-12 minutes)", level=2)
    _bullet(doc, "Minutes 1-2: Problem statement (the 4 challenges from the event page)")
    _bullet(doc, "Minutes 3-4: Why current tools structurally cannot solve this (8 gaps -- 4 preemptive, 4 behavioral)")
    _bullet(doc, "Minutes 5-7: The two-layer solution (Rigor preempts, ACECARD detects)")
    _bullet(doc, "Minutes 8-9: Proof -- working prototype, E-11 lineage, team credentials")
    _bullet(doc, "Minutes 10-11: Gabriel Nimbus deployment readiness (containerized, multi-enclave, cATO)")
    _bullet(doc, "Minute 12: 'We have a working solution. We can demo it today if there is time.'")

    doc.add_heading("Things NOT to Do", level=2)
    _bullet(doc, "Do NOT lead with marketing or company credentials -- lead with the PROBLEM")
    _bullet(doc, "Do NOT compare to specific competitors -- focus on structural capability gaps")
    _bullet(doc, "Do NOT use jargon without explaining it -- the room has mixed technical levels")
    _bullet(doc, "Do NOT oversell -- be honest about what the prototype does and does not do")
    _bullet(doc, "Do NOT read slides -- speak to the solution from understanding")

    return doc


# ═══════════════════════════════════════════════════════════════
# DOCUMENT 3: ONE-PAGE LEAVE-BEHIND
# ═══════════════════════════════════════════════════════════════
def build_leave_behind():
    doc = Document()
    _style(doc)

    # Compact margins
    for section in doc.sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.6)
        section.right_margin = Inches(0.6)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("ACECARD UEBA + Rigor AI")
    run.font.size = Pt(20)
    run.bold = True
    run.font.color.rgb = RGBColor(0x00, 0x2B, 0x5C)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(
        "Behavioral Anomaly Detection + Preemptive Cyber Defense  |  "
        "Containerized for Gabriel Nimbus"
    )
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x4A, 0x55, 0x68)

    doc.add_heading("The Problem", level=2)
    p = doc.add_paragraph(
        "Nation-state adversaries (Volt Typhoon, Salt Typhoon) used "
        "Living-off-the-Land tradecraft to dwell 5+ years inside U.S. critical "
        "infrastructure -- undetected by billions of dollars in existing security tools. "
        "Current SOC tooling fails because: threshold scoring misses legitimate-tool "
        "abuse, siloed analytics fragment identity, static rules decay monthly, "
        "and anomaly scores lack direction."
    )
    p.paragraph_format.space_after = Pt(4)

    doc.add_heading("The Solution: Two Layers", level=2)

    table = doc.add_table(rows=2, cols=2)
    table.style = "Light Grid Accent 1"
    table.columns[0].width = Inches(3.4)
    table.columns[1].width = Inches(3.4)

    c = table.rows[0].cells[0]
    c.text = "LAYER 1: Rigor AI (Preemptive)"
    for r in c.paragraphs[0].runs:
        r.bold = True
    c = table.rows[1].cells[0]
    c.text = (
        "Formal mathematical model of ALL security controls. "
        "Exhaustively verifies the 2^8000 config state space. "
        "PROVES attack paths are closed -- not samples. "
        "Continuous re-verification on every config change. "
        "Covers: edge CVEs, segmentation, ACL integrity."
    )

    c = table.rows[0].cells[1]
    c.text = "LAYER 2: ACECARD UEBA (Behavioral)"
    for r in c.paragraphs[0].runs:
        r.bold = True
    c = table.rows[1].cells[1]
    c.text = (
        "1536-d behavioral embedding per entity per hour. "
        "5 signals: auth, process, network, file, identity. "
        "CUSUM detects slow drift over weeks/months. "
        "Drift direction: 8 MITRE-mapped threat concepts. "
        "ABAC trust loop auto-enforces proportional response."
    )

    doc.add_heading("How It Solves the Four CFIC Challenges", level=2)

    table2 = doc.add_table(rows=5, cols=2)
    table2.style = "Light Grid Accent 1"
    table2.columns[0].width = Inches(2.8)
    table2.columns[1].width = Inches(4.0)
    table2.rows[0].cells[0].text = "Challenge"
    table2.rows[0].cells[1].text = "Solution"
    for r in table2.rows[0].cells[0].paragraphs[0].runs:
        r.bold = True
    for r in table2.rows[0].cells[1].paragraphs[0].runs:
        r.bold = True
    items = [
        ("Manual context reassembly", "Unified embedding fuses all logs into 1 vector. One API call = full context."),
        ("Inconsistent siloed analytics", "5 signal serializers normalize any source (ECS/OCSF/STIX) into 1 pipeline."),
        ("Scalability constraints", "Containerized K8s. 10K entities/hr on 4-vCPU. Horizontal scaling."),
        ("Operational inefficiency", "Automated pipeline. ABAC auto-enforces. Zero manual data wrangling."),
    ]
    for i, (ch, sol) in enumerate(items):
        table2.rows[i+1].cells[0].text = ch
        table2.rows[i+1].cells[1].text = sol

    doc.add_heading("Proof", level=2)
    p = doc.add_paragraph(
        "Working Docker prototype with 270 days of synthetic data, 6 attack "
        "scenarios, CUSUM detection, drift direction with MITRE mapping, and "
        "7-chart SOC dashboard. Foundation proven at DLA (E-11 Temporal "
        "Trajectory Intelligence, 500+ entities, 23 monthly snapshots)."
    )
    p.paragraph_format.space_after = Pt(4)

    doc.add_heading("Deployment", level=2)
    p = doc.add_paragraph(
        "Iron Bank containers | Big Bang Helm | IL5/IL6/JWICS | CAC/PIV mTLS | "
        "cATO-aligned CI/CD | Local SLM for air-gapped embedding | Gabriel Nimbus ready"
    )
    p.paragraph_format.space_after = Pt(4)

    doc.add_heading("Team", level=2)
    p = doc.add_paragraph(
        "22nd Century Technologies: $90M Army SOC/MDR (800+ analysts), "
        "USAF $108M, FBI TSC $56M, NAVAIR/USMC $145M. "
        "Rigor AI: 20+ design partners, F500/federal/CI production deployments."
    )
    p.paragraph_format.space_after = Pt(2)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Contact: Ravindra Shukla  |  ravindra.shukla@gmail.com")
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x00, 0x2B, 0x5C)

    return doc


# ═══════════════════════════════════════════════════════════════
# DOCUMENT 4: QUICK REFERENCE CARD (Pocket-sized key facts)
# ═══════════════════════════════════════════════════════════════
def build_quick_reference():
    doc = Document()
    _style(doc)

    for section in doc.sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.6)
        section.right_margin = Inches(0.6)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Quick Reference -- Key Numbers & Facts")
    run.font.size = Pt(18)
    run.bold = True
    run.font.color.rgb = RGBColor(0x00, 0x2B, 0x5C)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Keep in pocket for breakout sessions and Q&A")
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    doc.add_heading("The Threat (Facts to Cite)", level=2)
    _bullet(doc, "Volt Typhoon: 5+ year dwell in U.S. critical infrastructure (CISA AA24-038A)", "DWELL")
    _bullet(doc, "Salt Typhoon: 4+ years inside AT&T, Verizon, T-Mobile, Lumen (CISA AA25-239A)", "DWELL")
    _bullet(doc, "99% of firewall breaches caused by MISCONFIGURATION, not firewall flaws (Gartner 2019)", "STAT")
    _bullet(doc, "KEV patching covers only ~20% of attack vectors; 80% exploit config weaknesses", "STAT")
    _bullet(doc, "Config state space = 2^8000 possible states; ASM/BAS sample a vanishing fraction", "STAT")
    _bullet(doc, "PRC actors test against published Sigma/YARA rules before campaigns", "FACT")

    doc.add_heading("Our Solution (Key Numbers)", level=2)
    _bullet(doc, "Embedding dimensions: 1,536 (OpenAI text-embedding-3-small)", "TECH")
    _bullet(doc, "Behavioral signals per entity: 5 (auth, process, network, file, identity)", "TECH")
    _bullet(doc, "Threat concepts: 8 (credential_dumping, lateral_movement, exfiltration, c2_beaconing, lotl_execution, priv_esc, defense_evasion, insider_hoarding)", "TECH")
    _bullet(doc, "CUSUM threshold: 4-sigma (false positive rate < 0.003%)", "TECH")
    _bullet(doc, "Health score: 0-100 (Critical <40, High <70, Normal 70+)", "TECH")
    _bullet(doc, "Performance: <3 seconds per entity window; 10K entities/hour on 4-vCPU", "PERF")
    _bullet(doc, "Prototype: Docker-compose running NOW with 270 days synthetic data, 6 attack scenarios", "PROOF")
    _bullet(doc, "Lineage: E-11 Temporal Trajectory Intelligence at DLA, 500+ entities, 23 monthly snapshots", "PROOF")

    doc.add_heading("Deployment (Key Facts)", level=2)
    _bullet(doc, "Container: Iron Bank-compatible, OCI-compliant, Big Bang Helm chart", "DEPLOY")
    _bullet(doc, "Classification: IL5 (NIPR) / IL6 (SIPR) / JWICS", "DEPLOY")
    _bullet(doc, "Air-gapped embedding: Local SLM (Phi-4 / Mistral) -- no external API needed", "DEPLOY")
    _bullet(doc, "Auth: CAC/PIV via mTLS in production", "DEPLOY")
    _bullet(doc, "cATO: DoD CIO Feb 2022 reference design; FluxCD GitOps CI/CD", "DEPLOY")

    doc.add_heading("Team Credentials (Key Contracts)", level=2)
    _bullet(doc, "22CT: U.S. Army SOC/MDR $90M, 800+ cleared analysts")
    _bullet(doc, "22CT: USAF $108M cybersecurity operations")
    _bullet(doc, "22CT: FBI TSC $56M")
    _bullet(doc, "22CT: NAVAIR/USMC $145M")
    _bullet(doc, "Rigor AI: 20+ design partners -- F500, federal, CI, MSSPs, nation states")

    doc.add_heading("Anticipated Questions & Answers", level=2)

    qa = [
        ("How is this different from Exabeam/Securonix/Sentinel UEBA?",
         "Those use threshold-based anomaly scoring without trajectory or direction. "
         "We use continuous 1536-d embeddings with CUSUM change-point detection and "
         "cosine projection onto MITRE-mapped threat concepts. They say 'weird.' "
         "We say 'drifting toward lateral_movement (T1021) at 0.78.'"),
        ("Can this run on JWICS (air-gapped)?",
         "Yes. Embedding provider is swapped via environment variable. "
         "Local SLM (Phi-4, Mistral, sentence-transformers) produces same 1536-d "
         "vectors without any external API call."),
        ("What log sources do you need?",
         "Any source that produces ECS, OCSF, or STIX 2.1 formatted events. "
         "In practice: Windows EventLog, Sysmon, EDR (CrowdStrike/Defender), "
         "NetFlow/Zeek, Okta/Azure AD, CloudTrail, K8s audit."),
        ("How long to establish baseline?",
         "30-day rolling window for behavioral baseline. During ramp-up, "
         "cold-start priors based on entity role/type provide initial context."),
        ("What about false positives?",
         "Three layers reduce FP: (1) CUSUM 4-sigma threshold, (2) peer cohort "
         "z-score comparison, (3) analyst TP/FP feedback loop that auto-tunes "
         "thresholds per entity/role combination."),
        ("What does Rigor AI add that a vulnerability scanner doesn't?",
         "Vuln scanners find individual CVEs. Rigor models the ENTIRE config "
         "state space and proves whether attack PATHS exist through combinations "
         "of controls. A CVE on a device that's properly segmented is low risk. "
         "A misconfigured allow rule on a patched device is high risk. "
         "Rigor sees the path, not just the node."),
    ]
    for q, a in qa:
        p = doc.add_paragraph()
        run = p.add_run("Q: " + q)
        run.bold = True
        run.font.color.rgb = RGBColor(0x00, 0x2B, 0x5C)
        p = doc.add_paragraph("A: " + a)

    return doc


# ═══════════════════════════════════════════════════════════════
# GENERATE ALL
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    docs = [
        ("01_Solution_Brief.docx", build_solution_brief),
        ("02_Breakout_Talking_Points.docx", build_breakout_points),
        ("03_One_Page_Leave_Behind.docx", build_leave_behind),
        ("04_Quick_Reference_Card.docx", build_quick_reference),
    ]
    for filename, builder in docs:
        d = builder()
        path = os.path.join(OUT_DIR, filename)
        d.save(path)
        size = os.path.getsize(path) / 1024
        print(f"  {filename}: {size:.1f} KB")
    print(f"\nAll {len(docs)} documents saved to: {OUT_DIR}")
