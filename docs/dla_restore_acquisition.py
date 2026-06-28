"""Tracked edit: restore the acquisition-pathway detail in Section 10, reworded to avoid
the 'pilot ... pilot' redundancy."""
import os, copy
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

REV = "WP DLA/Decision_Intelligence_for_Defense_Logistics_White_Paper_ACADEMIC_final_REV_v2.docx"
AUTHOR = "ReviewPanel"; DATE = "2026-06-19T22:30:00Z"
d = Document(REV)
_id = [26000]
def nid():
    _id[0] += 1; return str(_id[0])
def acc(p): return "".join(x.text or "" for x in p._p.iter(qn('w:t')))
def _run(text, rpr=None):
    r = OxmlElement('w:r')
    if rpr is not None: r.append(copy.deepcopy(rpr))
    t = OxmlElement('w:t'); t.set(qn('xml:space'), 'preserve'); t.text = text; r.append(t); return r
def _wrap(tag, run):
    e = OxmlElement(tag); e.set(qn('w:id'), nid()); e.set(qn('w:author'), AUTHOR); e.set(qn('w:date'), DATE)
    e.append(run); return e

OLD = "how the pilot could be pursued."
NEW = ("how it could be pursued through an appropriate task order, Commercial Solutions Opening (CSO), or other "
       "contractual vehicle selected by DLA and its contracting office.")

done = False
for p in d.paragraphs:
    if not done and OLD in acc(p):
        run = next((r for r in p.runs if r.text and OLD in r.text), None)
        if run is None:  # merge runs of this paragraph
            runs = p.runs; full = "".join(r.text for r in runs)
            if OLD not in full: continue
            for t in runs[0]._r.findall(qn('w:t')): t.text = full
            for r in runs[1:]:
                for t in r._r.findall(qn('w:t')): t.text = ""
            run = runs[0]
        full = run.text; i = full.index(OLD)
        before, after = full[:i], full[i + len(OLD):]
        rpr = run._r.find(qn('w:rPr'))
        for t in run._r.findall(qn('w:t')): t.text = before
        delrun = _run(OLD, rpr)
        for t in list(delrun.iter(qn('w:t'))):
            dt = OxmlElement('w:delText'); dt.set(qn('xml:space'), 'preserve'); dt.text = t.text
            t.getparent().replace(t, dt)
        run._r.addnext(_run(after, rpr))
        run._r.addnext(_wrap('w:ins', _run(NEW, rpr)))
        run._r.addnext(_wrap('w:del', delrun))
        done = True

o = REV; k = 3
while True:
    try:
        d.save(o); break
    except PermissionError:
        root, ext = os.path.splitext(REV); o = f"{root.replace('_v2','')}_v{k}{ext}"; k += 1
print("acquisition sentence restored:", done, "| saved:", o)
