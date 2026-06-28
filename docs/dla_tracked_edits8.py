"""Eighth pass: de-duplication fixes in Sections 1-2 (tracked).
  A) S1 para 4: drop the repeated 40-54% / $460K result (kept in the lead + Section 2).
  B) S2 para 3: trim the duplicate 'large language models / transformer' line.
  C) Align the S1 pointer's section title punctuation to the actual heading (colon).
"""
import os, copy
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

REV = "WP DLA/Decision_Intelligence_for_Defense_Logistics_White_Paper_ACADEMIC_final_REV_v2.docx"
AUTHOR = "ReviewPanel"; DATE = "2026-06-19T19:00:00Z"
d = Document(REV)
_id = [19000]
def nid():
    _id[0] += 1; return str(_id[0])
def acc(p): return "".join(x.text or "" for x in p._p.iter(qn('w:t')))
def _run(text, rpr=None):
    r = OxmlElement('w:r')
    if rpr is not None: r.append(copy.deepcopy(rpr))
    t = OxmlElement('w:t'); t.set(qn('xml:space'), 'preserve'); t.text = text; r.append(t)
    return r
def _wrap(tag, run):
    e = OxmlElement(tag); e.set(qn('w:id'), nid()); e.set(qn('w:author'), AUTHOR); e.set(qn('w:date'), DATE)
    e.append(run); return e

def tracked_replace(old, new, label):
    # find paragraph containing old
    target = None
    for p in d.paragraphs:
        if old in acc(p): target = p; break
    if target is None:
        print(f"  [{label}] OLD NOT FOUND"); return False
    # find a single run containing old; merge runs if needed
    run = next((r for r in target.runs if r.text and old in r.text), None)
    if run is None:
        # merge all runs' text into the first run (uniform body text)
        runs = target.runs
        if not runs: print(f"  [{label}] no runs"); return False
        full = "".join(r.text for r in runs)
        if old not in full: print(f"  [{label}] old not contiguous"); return False
        for t in runs[0]._r.findall(qn('w:t')): t.text = full
        for r in runs[1:]:
            for t in r._r.findall(qn('w:t')): t.text = ""
        run = runs[0]
    full = run.text; i = full.index(old)
    before, after = full[:i], full[i + len(old):]
    rpr = run._r.find(qn('w:rPr'))
    for t in run._r.findall(qn('w:t')): t.text = before
    # del(old)
    delrun = _run(old, rpr)
    for t in list(delrun.iter(qn('w:t'))):
        dt = OxmlElement('w:delText'); dt.set(qn('xml:space'), 'preserve'); dt.text = t.text
        t.getparent().replace(t, dt)
    delw = _wrap('w:del', delrun)
    insw = _wrap('w:ins', _run(new, rpr))
    afterrun = _run(after, rpr)
    run._r.addnext(afterrun); run._r.addnext(insw); run._r.addnext(delw)
    print(f"  [{label}] applied")
    return True

# A) S1 para 4 number trim
tracked_replace(
    "On worked demand items it cut the 8-week planning buy by roughly 40 to 54 percent, about $460,000 less "
    "over-procurement on a single adapter plate, while also detecting demand that legacy methods report as zero, "
    "alongside capabilities legacy methods cannot provide such as calibrated uncertainty, early warning from "
    "behavioral drift, and forecasts for items with little or no history.",
    "It also provides capabilities legacy methods cannot, such as calibrated uncertainty, early warning from "
    "behavioral drift, and forecasts for items with little or no history.",
    "A: S1 number trim")

# B) S2 para 3 LLM line trim
tracked_replace(
    "Each item and depot is rebuilt as a digital twin using EDM Vector Intelligence, which brings the mathematics "
    "behind today's foundation models and large language models, transformer-style embeddings into a high-dimensional "
    "vector space, down to the application layer of defense logistics.",
    "Each item and depot is rebuilt as a digital twin using EDM Vector Intelligence, with its state embedded in a "
    "high-dimensional vector space.",
    "B: S2 LLM trim")

# C) section-title punctuation
tracked_replace("Proof of Concept - Decision-Value Evidence",
                "Proof of Concept: Decision-Value Evidence", "C: title punctuation")

o = REV; k = 3
while True:
    try:
        d.save(o); break
    except PermissionError:
        root, ext = os.path.splitext(REV); o = f"{root.replace('_v2','')}_v{k}{ext}"; k += 1
print("Saved:", o)
