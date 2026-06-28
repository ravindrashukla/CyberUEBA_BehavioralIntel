"""Sixth pass: build the three Section-2 call-out boxes (mirroring previous_final's
formatting) into the CURRENT version, populated with GROUNDED numbers. Implemented as
shaded, bordered single-cell tables inserted as tracked changes (row marked inserted,
all runs wrapped in w:ins).
"""
import os
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

REV = "WP DLA/Decision_Intelligence_for_Defense_Logistics_White_Paper_ACADEMIC_final_REV_v2.docx"
AUTHOR = "ReviewPanel"; DATE = "2026-06-19T17:00:00Z"
FILL = "DCE6F1"; TITLE = "1F3864"; BORDER = "1F3864"; BLACK = "000000"
d = Document(REV)
_id = [15000]
def nid():
    _id[0] += 1; return str(_id[0])
def insmark():
    e = OxmlElement('w:ins'); e.set(qn('w:id'), nid()); e.set(qn('w:author'), AUTHOR); e.set(qn('w:date'), DATE); return e

def _run(text, bold=False, color=BLACK, sz='21'):
    r = OxmlElement('w:r'); rPr = OxmlElement('w:rPr')
    if bold: rPr.append(OxmlElement('w:b'))
    c = OxmlElement('w:color'); c.set(qn('w:val'), color); rPr.append(c)
    s = OxmlElement('w:sz'); s.set(qn('w:val'), sz); rPr.append(s)
    rf = OxmlElement('w:rFonts'); rf.set(qn('w:ascii'), 'Calibri'); rf.set(qn('w:hAnsi'), 'Calibri'); rPr.append(rf)
    r.append(rPr)
    t = OxmlElement('w:t'); t.set(qn('xml:space'), 'preserve'); t.text = text; r.append(t)
    return r
def ins_wrap(run):
    e = insmark(); e.append(run); return e

def cell_para(parts, bullet=False, after=4, before=0):
    p = OxmlElement('w:p'); pPr = OxmlElement('w:pPr')
    if bullet:
        ind = OxmlElement('w:ind'); ind.set(qn('w:left'), '260'); ind.set(qn('w:hanging'), '160'); pPr.append(ind)
    sp = OxmlElement('w:spacing'); sp.set(qn('w:after'), str(after * 20)); sp.set(qn('w:before'), str(before * 20)); pPr.append(sp)
    rPr = OxmlElement('w:rPr'); rPr.append(insmark()); pPr.append(rPr)
    p.append(pPr)
    if bullet:
        p.append(ins_wrap(_run('•  ', bold=False, color=TITLE)))
    for (txt, b, color) in parts:
        p.append(ins_wrap(_run(txt, bold=b, color=color)))
    return p

def callout(anchor_text, title, intro, bullets):
    anchor = next(p for p in d.paragraphs
                  if anchor_text in "".join(x.text or "" for x in p._p.iter(qn('w:t'))))
    tbl = OxmlElement('w:tbl')
    tblPr = OxmlElement('w:tblPr')
    w = OxmlElement('w:tblW'); w.set(qn('w:w'), '5000'); w.set(qn('w:type'), 'pct'); tblPr.append(w)
    borders = OxmlElement('w:tblBorders')
    for edge in ('top', 'left', 'bottom', 'right'):
        b = OxmlElement('w:' + edge); b.set(qn('w:val'), 'single'); b.set(qn('w:sz'), '8')
        b.set(qn('w:space'), '0'); b.set(qn('w:color'), BORDER); borders.append(b)
    tblPr.append(borders)
    mar = OxmlElement('w:tblCellMar')
    for edge, v in (('top', '90'), ('bottom', '90'), ('left', '130'), ('right', '130')):
        m = OxmlElement('w:' + edge); m.set(qn('w:w'), v); m.set(qn('w:type'), 'dxa'); mar.append(m)
    tblPr.append(mar)
    tbl.append(tblPr)
    grid = OxmlElement('w:tblGrid'); gc = OxmlElement('w:gridCol'); gc.set(qn('w:w'), '9360'); grid.append(gc); tbl.append(grid)
    tr = OxmlElement('w:tr')
    trPr = OxmlElement('w:trPr'); trPr.append(insmark()); tr.append(trPr)   # row marked inserted
    tc = OxmlElement('w:tc'); tcPr = OxmlElement('w:tcPr')
    tcw = OxmlElement('w:tcW'); tcw.set(qn('w:w'), '5000'); tcw.set(qn('w:type'), 'pct'); tcPr.append(tcw)
    shd = OxmlElement('w:shd'); shd.set(qn('w:val'), 'clear'); shd.set(qn('w:fill'), FILL); tcPr.append(shd)
    tc.append(tcPr)
    tc.append(cell_para([(title, True, TITLE)], after=4))
    tc.append(cell_para([(intro, False, BLACK)], after=4))
    for bt in bullets:
        tc.append(cell_para([(bt, False, BLACK)], bullet=True, after=3))
    tr.append(tc); tbl.append(tr)
    anchor._p.addnext(tbl)

# --- Box 1: demand / forecasting (grounded numbers) ---
callout("These are per-item results on synthetic data",
    "EDM Turns Forecasting into Planning Intelligence",
    "EDM models each item-location as a behavioral entity and uses demand, supply, inventory, volatility, and context "
    "signals to adjust the P10 to P90 planning interval.",
    ["Reads 16 to 23 monthly snapshots and measures behavioral drift",
     "Aligns drift to supply-chain concepts and produces calibrated planning ranges for procurement and early warning",
     "Adapter plate: 8-week P90 buy cut from 379 to 225 units, about $460,000 less over-procurement, while still "
     "covering realized demand",
     "Needle bearing: 1,184 to 545 units, about $48,000 less; valve train kit: 0 to 95 units, catching demand legacy "
     "reports as zero",
     "Worked examples on synthetic data; to be re-validated on DLA data"])

# --- Box 2: supplier risk (qualitative, no AUC/C-index) ---
callout("where the approach adds the most for supplier risk",
    "BEI Converts Supplier Risk into Behavioral Intelligence",
    "BEI models supplier risk across connected behavioral entities, including suppliers, NSNs, locations, routes, "
    "manufacturers, countries of origin, contracts, and sub-tier relationships.",
    ["Surfaces interpretable drivers: quality incidents, recent order volume, on-time rate, worst delay, and "
     "critical-NSN count",
     "Estimates how risk develops over 30, 60, and 90-day horizons, alongside a point-in-time view",
     "Monotonic constraints keep the logic interpretable: stronger on-time performance lowers risk; quality "
     "incidents, sole-source exposure, and severe delays raise it",
     "Presented as a qualitative proof of concept requiring real-data validation"])

# --- Box 3: network early warning (with caveat / detection principle) ---
callout("prioritization, and readiness-focused response",
    "BEI Detects Mission Risk Before Thresholds Are Breached",
    "BEI provides a cross-domain early-warning framework that analyzes entities, relationships, and networks over time.",
    ["Describes each entity along nine behavioral dimensions and applies three analytical layers (entity, "
     "relationship, network)",
     "In a synthetic cybersecurity proof of concept, identified all four embedded long-duration attack campaigns at an "
     "8.1% false-positive rate, where conventional anomaly methods caught at most one",
     "Offered as a transferable detection principle, that slow, persistent, sub-threshold signals are discoverable, "
     "and a hypothesis to validate on DLA data; the 8.1% operating point was ground-truth-selected, a reporting "
     "benchmark not a deployable threshold",
     "Relevant to DLA because supply-chain and readiness risks may stay within nominal thresholds while their "
     "behavioral direction changes"])

o = REV; k = 3
while True:
    try:
        d.save(o); break
    except PermissionError:
        root, ext = os.path.splitext(REV); o = f"{root.replace('_v2','')}_v{k}{ext}"; k += 1
print("Saved:", o)
print("callout boxes inserted: 3")
