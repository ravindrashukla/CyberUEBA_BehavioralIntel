"""Tracked insertion: restore the warfighter-readiness / U.S. military superiority sentence
into the Conclusion's first paragraph (before 'This is the decision environment...')."""
import os, copy
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

REV = "WP DLA/Decision_Intelligence_for_Defense_Logistics_White_Paper_ACADEMIC_final_REV_v2.docx"
AUTHOR = "ReviewPanel"; DATE = "2026-06-19T23:00:00Z"
d = Document(REV)
_id = [27000]
def nid():
    _id[0] += 1; return str(_id[0])
def acc(p): return "".join(x.text or "" for x in p._p.iter(qn('w:t')))
def _run(text, rpr=None):
    r = OxmlElement('w:r')
    if rpr is not None: r.append(copy.deepcopy(rpr))
    t = OxmlElement('w:t'); t.set(qn('xml:space'), 'preserve'); t.text = text; r.append(t); return r
def _ins(run):
    e = OxmlElement('w:ins'); e.set(qn('w:id'), nid()); e.set(qn('w:author'), AUTHOR); e.set(qn('w:date'), DATE)
    e.append(run); return e

NEW = ("For DLA, adapting faster, resolving supply-chain friction earlier, and preserving decision time are directly "
       "tied to warfighter readiness, mission assurance, operational resiliency, and U.S. military superiority. ")
MARK = "This is the decision environment"

done = False
# locate the Conclusion paragraph (has 'breached. This is the decision environment')
for p in d.paragraphs:
    if not done and 'thresholds are breached. ' + MARK in acc(p):
        run = next((r for r in p.runs if r.text and MARK in r.text), None)
        if run is None:
            runs = p.runs; full = "".join(r.text for r in runs)
            for t in runs[0]._r.findall(qn('w:t')): t.text = full
            for r in runs[1:]:
                for t in r._r.findall(qn('w:t')): t.text = ""
            run = runs[0]
        full = run.text; i = full.index(MARK)
        before, after = full[:i], full[i:]
        rpr = run._r.find(qn('w:rPr'))
        for t in run._r.findall(qn('w:t')): t.text = before
        run._r.addnext(_run(after, rpr))
        run._r.addnext(_ins(_run(NEW, rpr)))
        done = True

o = REV; k = 3
while True:
    try:
        d.save(o); break
    except PermissionError:
        root, ext = os.path.splitext(REV); o = f"{root.replace('_v2','')}_v{k}{ext}"; k += 1
print("superiority sentence restored in Conclusion:", done, "| saved:", o)
