#!/usr/bin/env python3
"""Build Supplier Risk SCM Whitepaper (Word Document).

Whitepaper on using Behavioral Entity Intelligence (BEI) for Supplier Risk
Management in Defense Supply Chains.  Targets DLA leadership.

Does NOT disclose proprietary implementation details (no embedding dimensions,
no exact formulas, no cosine similarity math).  Highlights approach, results,
and business value.

Output: docs/Supplier_Risk_SCM_Whitepaper.docx
"""

import os
from docx import Document
from docx.shared import Inches, Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml

NAVY = RGBColor(0x0D, 0x1B, 0x2A)
BLUE = RGBColor(0x1B, 0x4F, 0x72)
TEAL = RGBColor(0x0E, 0x6B, 0x8A)
GOLD = RGBColor(0xB7, 0x95, 0x0B)
RED_ACCENT = RGBColor(0xC0, 0x39, 0x2B)
GREEN_ACCENT = RGBColor(0x1E, 0x8A, 0x49)
BLACK = RGBColor(0x00, 0x00, 0x00)
DARK_GRAY = RGBColor(0x44, 0x44, 0x44)

OUTPUT_PATH = os.path.join(os.path.dirname(__file__),
                           "Supplier_Risk_SCM_Whitepaper.docx")


# ── Helper functions (same pattern as build_tech_spec.py / build_ueba_whitepaper.py) ──

def set_cell_shading(cell, color_hex):
    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
    cell._tc.get_or_add_tcPr().append(shading)


def add_section_heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = NAVY if level == 1 else BLUE
    return h


def add_body_text(doc, text, bold=False, space_after=6):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(10.5)
    run.font.color.rgb = BLACK
    p.paragraph_format.space_after = Pt(space_after)
    return p


def add_bullet(doc, text, bold_prefix=None, level=0):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.left_indent = Pt(18 + level * 18)
    if bold_prefix:
        r = p.add_run(bold_prefix)
        r.bold = True
        r.font.size = Pt(10.5)
    r = p.add_run(text)
    r.font.size = Pt(10.5)
    return p


def add_callout(doc, text, border_color_hex="0E6B8A"):
    p = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        f'  <w:left w:val="single" w:sz="24" w:space="12" w:color="{border_color_hex}"/>'
        f'</w:pBdr>'
    )
    pPr.append(pBdr)
    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="EAF4F7" w:val="clear"/>')
    pPr.append(shading)
    run = p.add_run(text)
    run.font.size = Pt(10.5)
    run.font.color.rgb = NAVY
    run.bold = True
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(8)
    return p


def add_code_block(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = "Consolas"
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.left_indent = Pt(18)
    return p


def create_table(doc, headers, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Light Grid Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in p.runs:
                run.bold = True
                run.font.size = Pt(9)
        set_cell_shading(cell, "0D1B2A")
        for p in cell.paragraphs:
            for run in p.runs:
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    for r_idx, row in enumerate(rows):
        for c_idx, val in enumerate(row):
            cell = table.rows[r_idx + 1].cells[c_idx]
            cell.text = str(val)
            for p in cell.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(9)
            if r_idx % 2 == 1:
                set_cell_shading(cell, "EAF0F6")

    if col_widths:
        for i, w in enumerate(col_widths):
            for row in table.rows:
                row.cells[i].width = Inches(w)

    doc.add_paragraph()
    return table


def add_page_break(doc):
    doc.add_page_break()


# ==========================================================================
# DOCUMENT BUILDER
# ==========================================================================

def build():
    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    style.font.color.rgb = BLACK

    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)

    # ══════════════════════════════════════════════════════════════
    #  TITLE PAGE
    # ══════════════════════════════════════════════════════════════
    for _ in range(4):
        doc.add_paragraph()

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("Behavioral Entity Intelligence\nfor Supplier Risk Management")
    run.font.size = Pt(30)
    run.font.color.rgb = NAVY
    run.bold = True

    doc.add_paragraph()

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run(
        "Detecting Hidden Supply Chain Risks Through\n"
        "Entity Profiling, Relationship Dynamics, and Network Analysis"
    )
    run.font.size = Pt(15)
    run.font.color.rgb = BLUE

    for _ in range(4):
        doc.add_paragraph()

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = meta.add_run(
        "22nd Century Technologies, Inc.\n\n"
        "June 2026 — Version 1.0\n\n"
        "Prepared for: Defense Logistics Agency"
    )
    run.font.size = Pt(12)
    run.font.color.rgb = DARK_GRAY

    add_page_break(doc)

    # ══════════════════════════════════════════════════════════════
    #  TABLE OF CONTENTS
    # ══════════════════════════════════════════════════════════════
    add_section_heading(doc, "Table of Contents", level=1)

    toc_entries = [
        "1. Executive Summary",
        "2. The Supplier Risk Challenge",
        "   2.1. Why Traditional Supplier Monitoring Fails",
        "   2.2. Real-World Supply Chain Compromises",
        "   2.3. SCRM Regulatory Landscape",
        "3. Behavioral Entity Intelligence for Supply Chain",
        "   3.1. The Entity Model",
        "   3.2. Supplier Behavioral Zones",
        "   3.3. NSN Item Behavioral Zones",
        "   3.4. The Time Dimension",
        "4. Relationship-Level Risk Detection",
        "   4.1. Pairwise Relationships",
        "   4.2. Network-Level Risk",
        "   4.3. The What vs How Much Principle",
        "5. Detection Capabilities",
        "   5.1. Counterfeit Part Detection",
        "   5.2. Adversary-Nation Sourcing (SCRM)",
        "   5.3. Supplier Concentration Risk",
        "   5.4. Demand Diversion and Fraud",
        "   5.5. Contract and Financial Risk",
        "6. Operational Deployment",
        "   6.1. Data Requirements",
        "   6.2. Deployment Phases",
        "   6.3. Integration Points",
        "7. Proven Foundation: From Cybersecurity to Supply Chain",
        "   7.1. What Has Been Proven in Cybersecurity",
        "   7.2. Why the Proof Transfers",
        "   7.3. Supply Chain Proof of Concept",
        "   7.4. Illustrative Detection Scenarios",
        "8. Business Value",
        "9. Conclusion",
    ]
    for entry in toc_entries:
        p = doc.add_paragraph()
        run = p.add_run(entry)
        run.font.size = Pt(10.5)
        run.font.color.rgb = NAVY if not entry.startswith("   ") else BLUE
        p.paragraph_format.space_after = Pt(2)

    add_page_break(doc)

    # ══════════════════════════════════════════════════════════════
    #  1. EXECUTIVE SUMMARY
    # ══════════════════════════════════════════════════════════════
    add_section_heading(doc, "1. Executive Summary", level=1)

    add_body_text(doc, (
        "Defense supply chains face risks that are invisible to traditional monitoring. "
        "Suppliers gradually shift component sourcing to adversary nations. Counterfeit "
        "parts enter the supply chain through multi-tier intermediaries. Coordinated "
        "failures reveal hidden common dependencies that no single-supplier audit would "
        "uncover. These risks accumulate slowly, often over months, and become visible "
        "only after mission-critical systems are affected."
    ))

    add_body_text(doc, (
        "Traditional supplier monitoring checks individual metrics — on-time delivery "
        "rates, quality scores, pricing compliance — each against its own threshold. A "
        "supplier can pass every metric while systemic risks grow beneath the surface. "
        "The on-time rate stays within target. The quality score remains acceptable. The "
        "pricing stays within contract bounds. But the supplier has quietly shifted a "
        "substantial share of component sourcing from domestic manufacturers to facilities "
        "in an adversary nation. No single metric captures this."
    ))

    add_body_text(doc, (
        "Behavioral Entity Intelligence (BEI) detects these risks by tracking behavioral "
        "direction across three analytical layers: entity profiles that capture each "
        "supplier's multi-dimensional behavioral trajectory over time, pairwise "
        "relationships that reveal how specific supplier-part-location combinations are "
        "changing, and network graphs that expose hidden dependencies, single points of "
        "failure, and multi-hop adversary-nation connections."
    ))

    add_body_text(doc, (
        "This approach is not theoretical. The BEI framework has been proven in an "
        "operational cybersecurity deployment, where its multi-front threat-profile detector "
        "caught all four advanced, long-duration attack campaigns at zero false positives — "
        "an insider threat, a slow command-and-control campaign, and two nation-state "
        "intrusions — that traditional threshold-based detection missed entirely. Each "
        "attacker stayed within normal statistical ranges on every individual metric while "
        "shifting behavioral direction. The threat-profile detector caught the attacker-shaped "
        "pattern."
    ))

    add_body_text(doc, (
        "The framework has also been instantiated for the supply chain domain and "
        "exercised on a realistic synthetic dataset — 500 National Stock Numbers, 200 "
        "suppliers, 4 depots spanning the Indo-Pacific and CONUS, and 24 months of "
        "transaction history — demonstrating that the same behavioral profiling, regime "
        "detection, supplier risk grading, and relationship analysis operate directly on "
        "supply chain data. This whitepaper describes how that proven framework applies "
        "to defense supplier risk — and what it makes possible."
    ))

    add_callout(doc,
        "Key insight: The supplier changes WHAT it sources, not HOW MUCH it delivers. "
        "Traditional metrics measure magnitude. BEI measures behavioral direction. The "
        "same principle that exposed hidden cyber threats exposes hidden supply chain risk."
    )

    add_page_break(doc)

    # ══════════════════════════════════════════════════════════════
    #  2. THE SUPPLIER RISK CHALLENGE
    # ══════════════════════════════════════════════════════════════
    add_section_heading(doc, "2. The Supplier Risk Challenge", level=1)

    add_section_heading(doc, "2.1. Why Traditional Supplier Monitoring Fails", level=2)

    add_body_text(doc, (
        "Current supplier monitoring systems operate on a simple model: define a metric, "
        "set a threshold, and alert when the threshold is breached. This approach has four "
        "structural weaknesses that adversaries and market dynamics routinely exploit."
    ))

    add_body_text(doc, "Threshold Blindness", bold=True, space_after=2)
    add_body_text(doc, (
        "A supplier passes every individual threshold — on-time delivery, quality score, "
        "and pricing all within bounds — while simultaneously shifting component sourcing, "
        "reducing manufacturing oversight, and substituting materials. Each metric is "
        "within bounds. The composite behavioral trajectory tells a different story, but "
        "no system is watching the trajectory."
    ))

    add_body_text(doc, "Single-Entity Tunnel Vision", bold=True, space_after=2)
    add_body_text(doc, (
        "Traditional monitoring evaluates suppliers in isolation and parts in isolation. "
        "Supplier A looks fine. Part X looks fine. But the relationship between Supplier A "
        "and Part X has changed: the failure rate for this specific supplier-part "
        "combination has risen sharply while the supplier's overall quality score remains "
        "stable. The risk lives in the relationship, not in either entity."
    ))

    add_body_text(doc, "Static Risk Scores", bold=True, space_after=2)
    add_body_text(doc, (
        "Annual risk assessments produce a point-in-time snapshot. Between assessments, "
        "supplier behavior can drift significantly. A supplier assessed as low-risk in "
        "January may experience financial distress in March, begin substituting components "
        "in May, and deliver counterfeit parts in July — all before the next annual "
        "review. Continuous behavioral monitoring closes this gap."
    ))

    add_body_text(doc, "Tier-2/3 Opacity", bold=True, space_after=2)
    add_body_text(doc, (
        "Prime suppliers pass audits, but their sub-tier sourcing is effectively invisible. "
        "A Tier-1 supplier in good standing may source critical components from a Tier-2 "
        "distributor who sources from a Tier-3 manufacturer in an adversary nation. The "
        "prime supplier's metrics look clean because the risk is two hops away."
    ))

    add_section_heading(doc, "2.2. Real-World Supply Chain Compromises", level=2)

    add_body_text(doc, (
        "The following incidents illustrate the types of supply chain risks that "
        "traditional monitoring consistently fails to detect."
    ))

    add_body_text(doc, "Counterfeit Electronic Components in DoD Systems", bold=True, space_after=2)
    add_body_text(doc, (
        "The Senate Armed Services Committee investigation (2012) identified approximately "
        "1 million suspected counterfeit electronic parts in the Department of Defense "
        "supply chain. These counterfeits entered through multi-tier distribution networks "
        "where components were relabeled, remarked, or entirely fabricated. Many passed "
        "initial quality inspections because the counterfeits were functionally adequate "
        "for standard testing but failed under operational stress conditions."
    ))

    add_body_text(doc, "Section 889 Violations", bold=True, space_after=2)
    add_body_text(doc, (
        "Section 889 of the National Defense Authorization Act for Fiscal Year 2019 "
        "prohibits federal agencies from procuring telecommunications equipment from "
        "specified Chinese companies (Huawei, ZTE, and others). Despite the prohibition, "
        "components from these manufacturers have been found embedded in systems sold to "
        "federal agencies through multi-tier supply chains where the ultimate origin was "
        "obscured by intermediary distributors."
    ))

    add_body_text(doc, "SolarWinds Supply Chain Attack", bold=True, space_after=2)
    add_body_text(doc, (
        "The SolarWinds compromise (2020) demonstrated that software supply chains carry "
        "the same risks as physical supply chains. A compromised software build system "
        "injected malicious code into a legitimate software update, affecting approximately "
        "18,000 organizations including multiple federal agencies. The attack succeeded "
        "because the SBOM (Software Bill of Materials) was compromised at the build stage "
        "— the software appeared legitimate at every inspection point."
    ))

    add_body_text(doc, "COVID-19 Supply Chain Disruptions", bold=True, space_after=2)
    add_body_text(doc, (
        "The pandemic exposed hidden single points of failure across defense supply "
        "chains. Suppliers that appeared independent shared common sub-tier sources for "
        "raw materials, specialized components, or manufacturing capacity. When one "
        "facility shut down, multiple supposedly independent supply lines failed "
        "simultaneously, revealing concentration risks invisible to supplier-by-supplier "
        "monitoring."
    ))

    add_section_heading(doc, "2.3. SCRM Regulatory Landscape", level=2)

    add_body_text(doc, (
        "Defense supply chain risk management is governed by an expanding set of "
        "regulations, each addressing a specific dimension of supply chain risk. BEI "
        "provides the continuous monitoring capability that these regulations require "
        "but current systems struggle to deliver."
    ))

    create_table(doc,
        ["Regulation / Directive", "Scope", "BEI Relevance"],
        [
            ["DFARS 252.246-7008", "Counterfeit electronic parts\ndetection and avoidance",
             "BEI tracks supplier-part-manufacturer\nrelationship drift to detect sourcing\n"
             "changes indicative of counterfeit risk"],
            ["Section 889, NDAA FY2019", "Prohibition on Chinese telecom\ncomponents in federal systems",
             "BEI monitors country-of-origin\nrelationships continuously, not just\nat contract award"],
            ["Executive Order 14017", "Supply chain resilience\nacross critical sectors",
             "BEI identifies hidden concentration\nrisks and single points of failure\n"
             "through network analysis"],
            ["NIST SP 800-161 Rev 1", "Cybersecurity Supply Chain\nRisk Management (C-SCRM)",
             "BEI provides the continuous\nassessment and monitoring\n"
             "layer that C-SCRM frameworks require"],
            ["DLA SCRM Program", "DLA-specific supply chain\nrisk management processes",
             "BEI integrates with existing DLA\nSCRM workflows, adding behavioral\n"
             "intelligence to current risk scoring"],
        ],
        col_widths=[1.8, 2.2, 2.8],
    )

    add_page_break(doc)

    # ══════════════════════════════════════════════════════════════
    #  3. BEHAVIORAL ENTITY INTELLIGENCE FOR SUPPLY CHAIN
    # ══════════════════════════════════════════════════════════════
    add_section_heading(doc, "3. Behavioral Entity Intelligence for Supply Chain", level=1)

    add_section_heading(doc, "3.1. The Entity Model", level=2)

    add_body_text(doc, (
        "BEI models the defense supply chain as a network of interacting entities, each "
        "with a multi-dimensional behavioral profile that evolves over time. Four primary "
        "entity types capture the key actors and objects in the supply chain."
    ))

    create_table(doc,
        ["Entity Type", "Examples", "Behavioral Profile"],
        [
            ["Supplier", "Prime contractors, distributors,\nsmall businesses, foreign vendors",
             "Delivery performance, pricing behavior,\ngeographic sourcing patterns,\n"
             "financial health indicators"],
            ["NSN (Part)", "Consumables, repairables,\ncritical components, assemblies",
             "Demand patterns, failure rates,\nsupplier concentration,\n"
             "inventory position trajectories"],
            ["Location\n(Depot/Base)", "DLA depots, military installations,\n"
             "forward operating locations",
             "Demand composition, requisition urgency\npatterns, consumption velocity,\n"
             "seasonal profiles"],
            ["Manufacturer", "Original equipment manufacturers,\ncomponent fabricators,\n"
             "authorized distributors",
             "Production consistency, quality trends,\ncountry-of-origin stability,\n"
             "certification status"],
        ],
        col_widths=[1.2, 2.2, 3.0],
    )

    add_body_text(doc, (
        "Each entity maintains a behavioral profile composed of multiple independent "
        "dimensions — behavioral zones — that are tracked over time. The zones decompose "
        "entity activity into orthogonal dimensions so that a change in one dimension "
        "(e.g., geographic sourcing) is detected even when other dimensions (e.g., "
        "delivery timeliness) remain stable."
    ))

    add_section_heading(doc, "3.2. Supplier Behavioral Zones", level=2)

    add_body_text(doc, (
        "Each supplier's behavioral profile is decomposed into five zones that capture "
        "independent dimensions of supplier activity. This decomposition ensures that "
        "a change in sourcing geography is detected even if delivery performance "
        "remains exemplary."
    ))

    create_table(doc,
        ["Zone", "What It Captures", "Example Indicators"],
        [
            ["Identity", "Registration, certifications,\ncontract status, tier level",
             "CAGE code stability, SAM.gov status,\n"
             "ISO certification currency,\nsmall business classification"],
            ["Performance\nTrajectory", "Delivery timeliness trends,\nlead time consistency,\n"
             "quality scores over time",
             "On-time delivery rate trajectory,\naverage days early/late trend,\n"
             "quality rejection rate direction"],
            ["Location /\nGeographic Risk", "Sourcing geography,\ngeographic concentration,\n"
             "geopolitical risk exposure",
             "Country-of-origin distribution,\nmanufacturing site diversity,\n"
             "adversary-nation exposure percentage"],
            ["Network\nPosition", "How many depots served,\nhow many items supplied,\n"
             "supplier ecosystem role",
             "Customer concentration index,\nproduct breadth score,\n"
             "sole-source contract count"],
            ["Risk\nAssessment", "Composite risk indicators,\nfinancial health,\n"
             "contract urgency",
             "Altman Z-score trajectory,\ninsurance/bond status,\n"
             "expiring contract percentage"],
        ],
        col_widths=[1.2, 2.0, 3.2],
    )

    add_callout(doc,
        "Why zones matter: A supplier's on-time delivery stays strong (Performance zone "
        "stable) while sourcing shifts from domestic to adversary-nation origins "
        "(Geographic Risk zone drifting). Without zone decomposition, the stable "
        "performance masks the geographic risk."
    )

    add_section_heading(doc, "3.3. NSN Item Behavioral Zones", level=2)

    add_body_text(doc, (
        "Each National Stock Number (NSN) has its own behavioral profile decomposed into "
        "five zones. Tracking items independently from suppliers enables detection of risks "
        "that emerge from the item's lifecycle rather than from any single supplier."
    ))

    create_table(doc,
        ["Zone", "What It Captures", "Example Indicators"],
        [
            ["Identity", "Nomenclature, criticality,\nplatform, supply class",
             "Federal Supply Class, criticality code,\nweapon system association,\n"
             "shelf life classification"],
            ["Demand\nProfile", "Demand patterns, seasonality,\nexercise sensitivity",
             "Monthly demand trajectory,\nseasonal demand coefficients,\n"
             "exercise-driven demand spikes"],
            ["Supply\nNetwork", "Supplier count, sole source\nflag, supplier concentration",
             "Active supplier count trend,\nHerfindahl concentration index,\n"
             "new entrant / exit frequency"],
            ["Inventory\nPosition", "On-hand levels, safety stock\nratios, consumption velocity",
             "Days of supply trajectory,\nsafety stock adequacy ratio,\n"
             "stockout frequency trend"],
            ["Financial\nProfile", "Unit pricing, shelf life,\nsubstitutability",
             "Unit price trajectory,\nprice variance across suppliers,\n"
             "authorized substitute count"],
        ],
        col_widths=[1.2, 2.0, 3.2],
    )

    add_section_heading(doc, "3.4. The Time Dimension", level=2)

    add_body_text(doc, (
        "The critical distinction between BEI and traditional supplier monitoring is "
        "the treatment of time. Traditional systems evaluate each reporting period "
        "independently: is this month's delivery rate above threshold? BEI evaluates "
        "behavioral trajectory: is this month's delivery rate consistent with the "
        "supplier's established pattern, and if not, in which direction is it moving?"
    ))

    add_bullet(doc, "Weekly or monthly behavioral snapshots capture entity state over "
               "time, building a trajectory of behavioral evolution.",
               bold_prefix="Continuous Monitoring: ")
    add_bullet(doc, "Gradual changes invisible to point-in-time audits become visible "
               "when the system tracks cumulative behavioral displacement over weeks "
               "and months.",
               bold_prefix="Drift Detection: ")
    add_bullet(doc, "Each entity is classified into a behavioral regime — Stable, "
               "Drifting, or Critical — based on the velocity, acceleration, and "
               "direction of its behavioral trajectory.",
               bold_prefix="Regime Detection: ")

    add_body_text(doc, (
        "A supplier classified as Drifting in the Geographic Risk zone and Stable in all "
        "other zones is exhibiting the behavioral signature of gradual adversary-nation "
        "sourcing shift — precisely the pattern that annual audits miss."
    ))

    add_page_break(doc)

    # ══════════════════════════════════════════════════════════════
    #  4. RELATIONSHIP-LEVEL RISK DETECTION
    # ══════════════════════════════════════════════════════════════
    add_section_heading(doc, "4. Relationship-Level Risk Detection", level=1)

    add_body_text(doc, (
        "Entity-level monitoring — tracking each supplier or part independently — misses "
        "risks that live in the relationships between entities. BEI extends behavioral "
        "analysis to pairwise relationships and network-level structures."
    ))

    add_section_heading(doc, "4.1. Pairwise Relationships", level=2)

    add_body_text(doc, (
        "A pairwise relationship captures how two specific entities interact. The "
        "behavioral profile of the relationship can change even when both individual "
        "entity profiles appear normal."
    ))

    create_table(doc,
        ["Relationship", "What It Captures", "Risk Detected"],
        [
            ["Supplier x NSN", "How does THIS supplier perform\nfor THIS specific part?",
             "Quality drift for one part while\nstable for others = targeted\nsubstitution"],
            ["Supplier x\nCountry of Origin", "Where is THIS supplier sourcing\ncomponents?",
             "Gradual shift to adversary-nation\norigins = SCRM risk"],
            ["NSN x Location", "Demand patterns for THIS part\nat THIS depot",
             "Unusual demand composition at\nspecific locations = diversion"],
            ["NSN x Bill of\nMaterials", "Component composition\nchanges without notification",
             "SBOM drift = counterfeit or\nunauthorized substitution risk"],
            ["Supplier x\nSupplier", "Behavioral correlation between\n\"independent\" suppliers",
             "Hidden common sub-tier source\n= concentration risk"],
        ],
        col_widths=[1.3, 2.2, 2.8],
    )

    add_body_text(doc, (
        "Example: Supplier A's overall quality rate looks healthy. Part X's quality rate "
        "across all suppliers looks healthy. Both entities pass at the aggregate level. "
        "But Supplier A's quality specifically for Part X has been steadily degrading over "
        "months — a targeted degradation invisible at the entity level, visible only when "
        "the specific supplier-part relationship is tracked over time."
    ))

    add_body_text(doc, (
        "The Supplier-NSN and NSN-Location relationships are already built and demonstrated "
        "in the supply chain proof of concept (Section 7.3). The Supplier-Country, "
        "NSN-Bill-of-Materials, and Supplier-Supplier relationships use the identical "
        "relationship machinery and are added by introducing the corresponding entity "
        "profiles — country-of-origin, SBOM component, and supplier peer entities — making "
        "them direct, low-risk extensions rather than new research."
    ))

    add_section_heading(doc, "4.2. Network-Level Risk", level=2)

    add_body_text(doc, (
        "Beyond pairwise relationships, BEI analyzes the supply chain as a network graph "
        "to detect structural risks that no entity-level or pairwise analysis can reveal."
    ))

    add_body_text(doc, "Multi-Hop Risk Propagation", bold=True, space_after=2)
    add_body_text(doc, (
        "A Tier-1 supplier is fully compliant with all SCRM requirements. Its Tier-2 "
        "sub-supplier sources from an unknown Tier-3 manufacturer in an adversary nation. "
        "Entity-level monitoring of the Tier-1 supplier shows all green. Network analysis "
        "traces the supply path through multiple hops and identifies the adversary-nation "
        "connection."
    ))

    add_body_text(doc, "Hidden Single Points of Failure", bold=True, space_after=2)
    add_body_text(doc, (
        "Two suppliers appear independent: different CAGE codes, different locations, "
        "different contract vehicles. But both source a critical sub-component from the "
        "same Tier-2 manufacturer. If that manufacturer fails, both supply lines fail "
        "simultaneously. BEI detects this through behavioral correlation analysis — when "
        "two supposedly independent suppliers exhibit correlated behavioral changes, the "
        "system infers a hidden common dependency."
    ))

    add_body_text(doc, "Cascade Prediction", bold=True, space_after=2)
    add_body_text(doc, (
        "When one supplier fails, which depots are affected? Which missions are degraded? "
        "Network analysis propagates the impact of a supplier disruption through the "
        "supply graph, identifying every NSN, depot, and mission that depends on the "
        "failed supplier either directly or through sub-tier dependencies."
    ))

    add_section_heading(doc, "4.3. The What vs How Much Principle", level=2)

    add_body_text(doc, (
        "The foundational principle of BEI for supply chain risk is the distinction "
        "between what changed and how much changed."
    ))

    add_body_text(doc, (
        "Consider a supplier that delivers the same volume, at the same price, with the "
        "same on-time rate — but quietly shifts component sourcing from domestic origins "
        "to Chinese origins. Traditional metrics are all green: volume unchanged, price "
        "unchanged, delivery unchanged. Every threshold-based monitor shows a healthy "
        "supplier."
    ))

    add_body_text(doc, (
        "BEI relationship analysis detects the change: the Supplier x Country of Origin "
        "behavioral relationship has drifted. The supplier's Performance zone is stable. "
        "The Geographic Risk zone is changing direction. The system flags this as a "
        "SCRM risk — not because any magnitude threshold was crossed, but because the "
        "behavioral direction changed."
    ))

    add_callout(doc,
        "This is the supply chain equivalent of the insider threat: behavior changes "
        "WHAT, not HOW MUCH. The supplier looks the same by every traditional measure "
        "while fundamentally altering its sourcing strategy."
    )

    add_page_break(doc)

    # ══════════════════════════════════════════════════════════════
    #  5. DETECTION CAPABILITIES
    # ══════════════════════════════════════════════════════════════
    add_section_heading(doc, "5. Detection Capabilities", level=1)

    add_body_text(doc, (
        "BEI's multi-layer analysis — entity profiles, pairwise relationships, and "
        "network graphs — enables detection of five categories of supply chain risk that "
        "traditional monitoring consistently misses."
    ))

    add_section_heading(doc, "5.1. Counterfeit Part Detection", level=2)

    add_body_text(doc, (
        "Counterfeit parts enter the defense supply chain through sophisticated "
        "distribution networks where components are relabeled, remarked, or entirely "
        "fabricated. BEI detects counterfeit risk through three behavioral signatures."
    ))

    add_bullet(doc, "NSN failure rate diverges between locations receiving from different "
               "suppliers. When the same part fails markedly more often from one supplier "
               "than another, the NSN x Supplier relationship drift signals a sourcing "
               "quality difference that aggregate part-level statistics conceal.",
               bold_prefix="Failure Rate Divergence: ")
    add_bullet(doc, "The NSN x Manufacturer relationship changes — a different "
               "manufacturer of origin appears on inspection records while the label "
               "remains the same. BEI tracks this relationship continuously, not just "
               "at contract award.",
               bold_prefix="Manufacturer Relationship Drift: ")
    add_bullet(doc, "The component composition of a delivered assembly changes without "
               "engineering notification. BEI monitors SBOM behavioral profiles for "
               "drift in component identity, source, or specification.",
               bold_prefix="SBOM Composition Drift: ")

    add_section_heading(doc, "5.2. Adversary-Nation Sourcing (SCRM)", level=2)

    add_body_text(doc, (
        "Adversary-nation sourcing risk is the gradual shift of component origins to "
        "countries designated as supply chain risks. This shift typically occurs over "
        "months, making it invisible to annual audits."
    ))

    add_bullet(doc, "The Supplier x Country of Origin relationship drifts over "
               "months as sourcing geography shifts incrementally. Each monthly snapshot "
               "looks similar to the previous one; the cumulative trajectory reveals a "
               "fundamental change.",
               bold_prefix="Supplier x Country Drift: ")
    add_bullet(doc, "Network analysis traces supply paths through intermediaries "
               "to identify adversary-nation connections that are two or three hops "
               "removed from the prime supplier. A compliant Tier-1 supplier may "
               "unknowingly source from an adversary-nation Tier-3 manufacturer.",
               bold_prefix="Multi-Hop Network Analysis: ")
    add_bullet(doc, "BEI provides continuous behavioral monitoring of country-of-origin "
               "relationships, extending Section 889 compliance beyond the point-in-time "
               "assessment at contract award to ongoing operational monitoring.",
               bold_prefix="Section 889 Compliance: ")

    add_section_heading(doc, "5.3. Supplier Concentration Risk", level=2)

    add_body_text(doc, (
        "Concentration risk arises when the supply chain depends on fewer independent "
        "sources than it appears to have. BEI detects hidden concentration through "
        "behavioral correlation and network centrality analysis."
    ))

    add_bullet(doc, "When two supposedly independent suppliers exhibit correlated "
               "behavioral changes — simultaneous delivery delays, coordinated price "
               "increases, or synchronized quality shifts — BEI infers a hidden common "
               "dependency at the sub-tier level.",
               bold_prefix="Supplier Behavioral Correlation: ")
    add_bullet(doc, "Graph analysis identifies entities whose removal would "
               "disproportionately impact the supply network. A supplier that appears "
               "minor by contract value may be the sole source for a component used "
               "in 30 weapon systems.",
               bold_prefix="Network Centrality Analysis: ")
    add_bullet(doc, "If Supplier X fails, the system propagates the impact "
               "through the supply graph to identify every affected NSN, depot, and "
               "mission — including indirect impacts through sub-tier dependencies.",
               bold_prefix="Impact Propagation Modeling: ")

    add_section_heading(doc, "5.4. Demand Diversion and Fraud", level=2)

    add_body_text(doc, (
        "Demand diversion occurs when parts ordered for one purpose are redirected to "
        "unauthorized uses. BEI detects diversion through relationship-level anomalies."
    ))

    add_bullet(doc, "The same part is requisitioned by a different set of requestors "
               "with elevated urgency codes. The total volume looks normal; the "
               "requestor composition has changed.",
               bold_prefix="Requestor x NSN x Urgency Drift: ")
    add_bullet(doc, "Demand volume at a specific location remains within normal "
               "bounds, but the mix of items being demanded changes. BEI detects the "
               "composition shift through NSN x Location relationship analysis.",
               bold_prefix="Location Demand Composition: ")
    add_bullet(doc, "Orders that progress through acceptance without standard "
               "inspection steps create a behavioral sequence anomaly — the expected "
               "workflow pattern has changed.",
               bold_prefix="Sequence Anomaly Detection: ")

    add_section_heading(doc, "5.5. Contract and Financial Risk", level=2)

    add_body_text(doc, (
        "Supplier financial distress frequently precedes quality degradation and delivery "
        "failures. BEI correlates behavioral drift with financial health indicators to "
        "provide early warning."
    ))

    add_bullet(doc, "When a supplier's Performance Trajectory zone begins drifting "
               "concurrently with deterioration in its Risk Assessment zone, BEI "
               "flags the correlation as a financial distress indicator.",
               bold_prefix="Behavioral-Financial Correlation: ")
    add_bullet(doc, "Contracts approaching expiration combined with degrading "
               "delivery performance signal a supplier that may be disinvesting in "
               "the relationship — a flight risk for critical supply lines.",
               bold_prefix="Contract Expiry Risk: ")
    add_bullet(doc, "A supplier maintains stable pricing while failure rates "
               "increase. The cost per unit is unchanged, but the cost per "
               "functioning unit is rising. BEI detects this through the divergence "
               "between the financial and performance behavioral zones.",
               bold_prefix="Price-Quality Divergence: ")

    add_page_break(doc)

    # ══════════════════════════════════════════════════════════════
    #  6. OPERATIONAL DEPLOYMENT
    # ══════════════════════════════════════════════════════════════
    add_section_heading(doc, "6. Operational Deployment", level=1)

    add_section_heading(doc, "6.1. Data Requirements", level=2)

    add_body_text(doc, (
        "BEI integrates data from existing DLA and DoD systems. No new data collection "
        "is required — the system operates on transaction records, quality reports, and "
        "supplier profiles already maintained across the enterprise."
    ))

    create_table(doc,
        ["Data Source", "Description", "Cadence", "Integration"],
        [
            ["Procurement\nTransactions", "Purchase orders, delivery orders,\ncontract actions",
             "Daily", "Batch extract from\ncontracting systems"],
            ["Delivery\nRecords", "Receipt confirmations, delivery\ndates, quantity variances",
             "Daily", "Automated feed from\nwarehouse management"],
            ["Quality\nInspections", "Inspection results, rejection rates,\ndefect classifications",
             "Per event", "Quality system\nintegration"],
            ["Country-of-Origin\nDeclarations", "Manufacturer origin certifications,\ntrade compliance records",
             "Per shipment", "Customs and trade\ncompliance systems"],
            ["SBOM\nRegistries", "Software and hardware bills of\nmaterials, component lists",
             "Per delivery", "Engineering data\nmanagement systems"],
            ["Financial\nFilings", "Supplier financial health indicators,\nbond and insurance status",
             "Quarterly", "SAM.gov, D&B,\ncommercial sources"],
            ["GIDEP\nAlerts", "Government-Industry Data Exchange\nProgram notifications",
             "As issued", "GIDEP automated\nalert feed"],
        ],
        col_widths=[1.2, 2.2, 0.8, 1.8],
    )

    add_section_heading(doc, "6.2. Deployment Phases", level=2)

    add_body_text(doc, (
        "BEI deployment follows a four-phase approach designed to deliver initial value "
        "within 8 weeks while building toward full production capability."
    ))

    create_table(doc,
        ["Phase", "Duration", "Activities", "Deliverables"],
        [
            ["Phase 1:\nData Integration", "2-4 weeks",
             "Connect to procurement, delivery,\nquality, and supplier databases.\n"
             "Entity resolution across systems.\nData quality assessment.",
             "Integrated data pipeline\nEntity resolution map\nData quality report"],
            ["Phase 2:\nBaseline\nEstablishment", "4-6 weeks",
             "Ingest 4-6 weeks of historical data.\n"
             "Build behavioral profiles for all\nentities. Establish zone baselines.\n"
             "Calibrate drift detection thresholds.",
             "Entity behavioral profiles\nBaseline reference points\nCalibration report"],
            ["Phase 3:\nDetection\nDeployment", "2-4 weeks",
             "Deploy detection capabilities.\n"
             "Threshold tuning against known\nhistorical incidents. SOC analyst\n"
             "training on alert triage.",
             "Detection rules deployed\nAlert triage procedures\nAnalyst training complete"],
            ["Phase 4:\nProduction\nMonitoring", "Ongoing",
             "Continuous behavioral monitoring.\n"
             "Integration with acquisition and\nSOC workflows. Quarterly model\n"
             "recalibration.",
             "Operational dashboard\nWeekly risk reports\nAcquisition decision support"],
        ],
        col_widths=[1.0, 0.8, 2.5, 2.2],
    )

    add_section_heading(doc, "6.3. Integration Points", level=2)

    add_body_text(doc, (
        "BEI is designed to integrate with DLA's existing systems and workflows, "
        "augmenting current capabilities rather than replacing them."
    ))

    add_bullet(doc, "BEI's behavioral risk scores feed into DLA's existing SCRM "
               "risk assessments, providing continuous monitoring between annual reviews.",
               bold_prefix="DLA SCRM Program: ")
    add_bullet(doc, "GIDEP alerts are correlated with BEI behavioral detections. "
               "A GIDEP alert about a supplier coinciding with behavioral drift in "
               "that supplier's profile elevates the risk score and triggers "
               "accelerated investigation.",
               bold_prefix="GIDEP Integration: ")
    add_bullet(doc, "BEI cross-references entity profiles against CAGE and SAM.gov "
               "registrations. Changes in supplier registration status (new CAGE codes, "
               "SAM.gov exclusions, changed addresses) trigger behavioral profile updates.",
               bold_prefix="CAGE/SAM.gov Databases: ")
    add_bullet(doc, "Behavioral risk scores are presented to contracting officers at "
               "the point of contract award decision. A supplier with a drifting "
               "Geographic Risk zone is flagged before the award, not after delivery.",
               bold_prefix="Contracting Officer Workflow: ")
    add_bullet(doc, "Parts from suppliers with elevated behavioral risk scores are "
               "routed to priority inspection queues. Limited inspection resources are "
               "allocated based on behavioral intelligence rather than random sampling.",
               bold_prefix="Quality Assurance Routing: ")

    add_page_break(doc)

    # ══════════════════════════════════════════════════════════════
    #  7. VALIDATED RESULTS
    # ══════════════════════════════════════════════════════════════
    add_section_heading(doc, "7. Proven Foundation: From Cybersecurity to Supply Chain", level=1)

    add_section_heading(doc, "7.1. What Has Been Proven in Cybersecurity", level=2)

    add_body_text(doc, (
        "The behavioral detection concept described in this whitepaper is not a research "
        "proposal. It has been built, deployed, and proven in an operational cybersecurity "
        "setting. In that deployment, the BEI framework analyzed a large population of "
        "users over an extended period and was challenged with four advanced, "
        "long-duration attack campaigns deliberately designed to evade detection: a "
        "patient insider threat, a slow command-and-control intrusion, and two "
        "nation-state campaigns modeled on real-world adversary tradecraft."
    ))

    add_body_text(doc, (
        "Traditional detection methods — the statistical and threshold-based techniques "
        "that are the supply chain equivalent of on-time-rate and quality-score "
        "monitoring — detected none of these campaigns at operationally acceptable alert "
        "rates. Every attacker stayed within normal statistical ranges on every "
        "individual metric. BEI's multi-front threat-profile detector caught all four at zero "
        "false positives, while composite scoring alone cleanly separated two of the four "
        "above the normal population. The attackers were caught not because any single "
        "value crossed a threshold, but because their behavioral direction changed — "
        "exactly the failure mode that defeats traditional supplier monitoring."
    ))

    add_callout(doc,
        "The proof point is concrete: in cybersecurity, BEI detected every advanced "
        "campaign that traditional methods missed entirely. The detections came from "
        "behavioral direction, not metric magnitude — the same signal that exposes "
        "hidden supplier risk."
    )

    add_section_heading(doc, "7.2. Why the Proof Transfers", level=2)

    add_body_text(doc, (
        "The cybersecurity and supply chain problems are structurally identical. In both, "
        "the most damaging actors operate within authorized bounds — valid credentials in "
        "one case, compliant contracts in the other — while gradually shifting behavioral "
        "direction toward an objective. The BEI framework is domain-agnostic: the same "
        "analytical architecture that profiles a user profiles a supplier; the same "
        "relationship analysis that links a user to a device links a supplier to a part "
        "and a country of origin; the same temporal trajectory analysis that detects an "
        "escalating insider detects a supplier drifting toward distress."
    ))

    create_table(doc,
        ["Framework Element", "Proven In Cybersecurity", "Applied To Supplier Risk"],
        [
            ["Entity profile",
             "User, device, application behavioral baselines",
             "Supplier, NSN, location, manufacturer baselines"],
            ["Behavioral zones",
             "Identity, access, data, network, risk",
             "Identity, performance, geographic, network, risk"],
            ["Relationship analysis",
             "User-device, user-application interactions",
             "Supplier-part, supplier-country, part-SBOM interactions"],
            ["Temporal trajectory",
             "Detecting escalating insider over months",
             "Detecting supplier drift toward distress or substitution"],
            ["Directional detection",
             "Threat-profile detector caught all 4 advanced campaigns (0% FP) missed by traditional methods",
             "Designed to catch sourcing shifts, counterfeits, hidden concentration"],
        ],
        col_widths=[1.4, 2.5, 2.6],
    )

    add_body_text(doc, (
        "What changes between domains is the vocabulary of the entities and the data "
        "sources that feed them. What stays constant is the detection principle and the "
        "analytical machinery — both proven."
    ))

    add_section_heading(doc, "7.3. Supply Chain Proof of Concept", level=2)

    add_body_text(doc, (
        "The BEI framework has been instantiated for the supply chain domain and exercised "
        "on a realistic synthetic dataset. This proof of concept demonstrates that the "
        "framework's capabilities — entity profiling, zone decomposition, relationship "
        "analysis, temporal trajectory, and regime detection — operate on supply chain "
        "data exactly as they operate on cybersecurity data."
    ))

    create_table(doc,
        ["Parameter", "Value"],
        [
            ["National Stock Numbers (NSNs)", "500"],
            ["Suppliers", "200"],
            ["Depots", "4 (3 Indo-Pacific, 1 CONUS)"],
            ["Transaction History", "24 months"],
            ["Demand Components Modeled", "6 (baseline, exercise, seasonal,\n"
             "maintenance, combat, failure)"],
            ["Supplier Risk Grades", "A through F (composite behavioral +\n"
             "financial + performance)"],
        ],
        col_widths=[2.5, 4.0],
    )

    add_body_text(doc, "Demonstrated Capabilities", bold=True, space_after=2)

    add_bullet(doc, "The framework identifies items transitioning from STABLE to DEPLETING "
               "behavioral regimes before stockout occurs, providing actionable lead time "
               "for procurement intervention.",
               bold_prefix="Phase Space Regime Detection: ")
    add_bullet(doc, "Each supplier receives a composite health grade (A through F) "
               "incorporating behavioral trajectory, financial health indicators, and "
               "delivery performance trends. The grade reflects behavioral direction, "
               "not just current-period metrics.",
               bold_prefix="Supplier Risk Scoring: ")
    add_bullet(doc, "Demand for each NSN is decomposed into six independent components, "
               "enabling the system to distinguish exercise-driven demand spikes from "
               "baseline consumption changes and combat-related surges.",
               bold_prefix="Demand Decomposition: ")
    add_bullet(doc, "Four relationship types are built and operating: Supply "
               "(Supplier-NSN), Demand (NSN-Location), Transit (NSN-Route), and "
               "Fulfillment (Supplier-NSN-Location). The country-of-origin, "
               "bill-of-materials, and supplier-to-supplier relationships described in "
               "Section 4 are natural extensions of the same relationship machinery, "
               "added by introducing the corresponding entity profiles.",
               bold_prefix="Relationship Analysis: ")
    add_bullet(doc, "Analysts query the system in natural language — 'Which Indo-Pacific "
               "parts are at risk of stockout in the next 90 days?' — and receive "
               "answers contextualized with behavioral intelligence, not just inventory "
               "snapshots.",
               bold_prefix="LLM-Powered Decision Support: ")

    add_callout(doc,
        "The cybersecurity deployment proved detection efficacy quantitatively — every "
        "advanced campaign caught, traditional methods bypassed. The supply chain proof "
        "of concept proves the same capabilities are built and operating on supply chain "
        "data. Quantified detection benchmarking against injected supplier-risk campaigns "
        "is the natural next step on DLA production data."
    )

    add_section_heading(doc, "7.4. Illustrative Detection Scenarios", level=2)

    add_body_text(doc, (
        "The following scenarios illustrate what BEI is designed to surface when applied "
        "to defense supplier data. They describe the behavioral signal and the mechanism "
        "by which BEI exposes it — the same class of directional signal proven detectable "
        "in the cybersecurity deployment and demonstrated operationally in the supply "
        "chain proof of concept."
    ))

    create_table(doc,
        ["Scenario", "Behavioral Signal", "Traditional\nVisibility", "How BEI Surfaces It"],
        [
            ["Supplier sourcing shift\nto adversary nation",
             "Geographic Risk zone drifting\nwhile Performance zone stable",
             "Invisible until\nnext annual audit",
             "Continuous zone-level\ndrift detection flags the\ngeographic shift as it forms"],
            ["Hidden supplier\nconcentration",
             "Two suppliers show correlated\nbehavioral changes (delivery,\npricing, quality)",
             "Invisible —\nsuppliers appear\nindependent",
             "Network cohort analysis\nflags the correlated\nbehavior as a shared\ndependency"],
            ["NSN transitioning\nto stockout",
             "Inventory Position zone\naccelerating toward depletion\nregime",
             "Visible only when\nstockout occurs",
             "Regime detection flags\nthe STABLE-to-DEPLETING\ntransition before depletion"],
            ["Counterfeit part\nentry",
             "NSN failure rate diverges\nbetween supplier sources",
             "Detected only after\nfield failure",
             "Relationship analysis\nflags the supplier-part\nfailure divergence"],
            ["Supplier financial\ndistress",
             "Performance and Risk\nzones drift concurrently",
             "Detected at next\nquarterly review",
             "Multi-zone trajectory\nflags the concurrent drift\nas it develops"],
        ],
        col_widths=[1.4, 2.0, 1.4, 1.9],
    )

    add_page_break(doc)

    # ══════════════════════════════════════════════════════════════
    #  8. BUSINESS VALUE
    # ══════════════════════════════════════════════════════════════
    add_section_heading(doc, "8. Business Value", level=1)

    add_body_text(doc, (
        "BEI delivers measurable value across six dimensions of supply chain risk "
        "management, transforming reactive monitoring into proactive risk intelligence."
    ))

    add_body_text(doc, "Reduced Counterfeit Exposure", bold=True, space_after=2)
    add_body_text(doc, (
        "Continuous behavioral monitoring of supplier-part-manufacturer relationships "
        "detects counterfeit risk signals months before parts fail in the field. The "
        "Government Accountability Office estimates average counterfeit remediation "
        "costs at $1.8 million per incident, including recall, inspection, replacement, "
        "and mission impact assessment. BEI's early detection capability reduces both "
        "the frequency and severity of counterfeit incidents."
    ))

    add_body_text(doc, "Earlier Detection of SCRM Risks", bold=True, space_after=2)
    add_body_text(doc, (
        "Traditional SCRM assessments operate on annual review cycles. BEI monitors "
        "supplier behavior continuously, surfacing adversary-nation sourcing shifts as "
        "the behavioral change forms rather than at the next scheduled review. For "
        "slow-moving supply chain compromises that unfold over quarters, the difference "
        "between continuous detection and periodic review is the difference between "
        "prevention and remediation."
    ))

    add_body_text(doc, "Reduced Mission Impact from Supply Disruptions", bold=True, space_after=2)
    add_body_text(doc, (
        "Cascade prediction identifies the mission impact of supplier failures before "
        "they occur. When a supplier enters the Drifting regime, the system immediately "
        "identifies every depot, NSN, and mission that would be affected, enabling "
        "proactive sourcing decisions rather than reactive scrambling."
    ))

    add_body_text(doc, "Compliance Automation", bold=True, space_after=2)
    add_body_text(doc, (
        "Continuous monitoring of Section 889 and DFARS compliance replaces periodic "
        "manual audits. The system continuously tracks country-of-origin relationships "
        "and flags compliance deviations as they emerge, reducing both compliance risk "
        "and the labor cost of manual reviews."
    ))

    add_body_text(doc, "Acquisition Intelligence", bold=True, space_after=2)
    add_body_text(doc, (
        "Behavioral risk scores inform contract award decisions at the point of "
        "decision. A contracting officer evaluating two suppliers can see not just "
        "current performance metrics but behavioral trajectory: is this supplier's "
        "quality improving or degrading? Is its geographic sourcing stable or shifting? "
        "This intelligence transforms acquisition from a backward-looking assessment to "
        "a forward-looking prediction."
    ))

    add_body_text(doc, "The Scale of the Problem BEI Addresses", bold=True, space_after=2)
    add_body_text(doc, (
        "The following figures describe the documented cost of the supply chain risks "
        "that BEI is designed to detect earlier. They establish the scale of the problem, "
        "drawn from external sources; the value of earlier behavioral detection is "
        "proportional to these stakes."
    ))

    create_table(doc,
        ["Risk Category", "Documented Cost of the Problem", "Source", "Where BEI Helps"],
        [
            ["Counterfeit\nRemediation", "~$1.8M average per incident", "GAO reports",
             "Behavioral monitoring of\nsupplier-part-manufacturer\nrelationships surfaces\ncounterfeit risk signals"],
            ["Stockout /\nMission Impact", "Mission-dependent, can reach\ntens of millions per event",
             "DLA readiness\nassessments",
             "Regime detection flags\ndepletion trajectories\nbefore stockout"],
            ["SCRM Compliance\nViolation", "Significant remediation and\nreporting cost per finding",
             "DFARS enforcement\nhistory",
             "Continuous country-of-origin\nmonitoring replaces\nperiodic audits"],
            ["Supplier Failure\nCascade", "Scope-dependent, can be\nsubstantial across a portfolio",
             "COVID-19 supply\nchain analyses",
             "Network analysis exposes\nhidden concentration before\nit cascades"],
        ],
        col_widths=[1.3, 1.7, 1.3, 2.0],
    )

    add_page_break(doc)

    # ══════════════════════════════════════════════════════════════
    #  9. CONCLUSION
    # ══════════════════════════════════════════════════════════════
    add_section_heading(doc, "9. Conclusion", level=1)

    add_body_text(doc, (
        "Traditional supplier monitoring measures individual metrics at points in time. "
        "Each metric has a threshold. Each threshold is evaluated independently. A "
        "supplier that stays below every threshold is classified as low-risk, regardless "
        "of what is changing beneath the surface."
    ))

    add_body_text(doc, (
        "Behavioral Entity Intelligence measures behavioral direction across entity "
        "relationships continuously. It asks not 'Is this metric within bounds?' but "
        "'Is this entity behaving the same way it has historically?' and 'In which "
        "dimension is the behavior changing?' The decomposition into independent "
        "behavioral zones, the tracking of pairwise relationships, and the analysis "
        "of network structure together create a detection capability that addresses "
        "the four structural weaknesses of traditional monitoring: threshold blindness, "
        "single-entity tunnel vision, static risk scores, and sub-tier opacity."
    ))

    add_body_text(doc, (
        "The central insight applies to supply chains as it does to cybersecurity: "
        "the supplier changes WHAT it sources, not HOW MUCH it delivers. The delivery "
        "rate stays strong. The quality score stays acceptable. But the component origins "
        "shifted. The sub-tier manufacturing site changed. The SBOM composition drifted. "
        "These changes are invisible to traditional metrics and visible to behavioral "
        "intelligence — as proven when the same framework caught every advanced threat "
        "that traditional methods missed in the cybersecurity domain."
    ))

    add_callout(doc,
        "Next step: 22nd Century Technologies is prepared to conduct a 4-week proof "
        "of concept on DLA production data, demonstrating BEI detection capabilities "
        "against actual supply chain transaction history across a selected commodity "
        "group."
    )

    add_page_break(doc)

    # ══════════════════════════════════════════════════════════════
    #  END MATTER
    # ══════════════════════════════════════════════════════════════
    for _ in range(6):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("22nd Century Technologies, Inc.")
    run.font.size = Pt(16)
    run.font.color.rgb = NAVY
    run.bold = True

    doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("V-Intelligence UEBA Program — Supply Chain Risk Management")
    run.font.size = Pt(13)
    run.font.color.rgb = BLUE

    doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("June 2026")
    run.font.size = Pt(12)
    run.font.color.rgb = DARK_GRAY

    # ── Save ──
    doc.save(OUTPUT_PATH)
    print(f"Saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    build()
