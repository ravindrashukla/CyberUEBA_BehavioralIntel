"""Swap the five corrected figures into the Word doc by replacing the embedded image
content (and matching the display extent to the new aspect). Image-content swaps are not
Word-trackable; all text edits in the doc remain tracked.
  Figure 1  -> _fig1_new.png   (MVP -> pilot)
  Figure 4  -> _fig4_new.png   (grounded 379/225/$460K)
  Figure 5  -> _fig5_new.png   (corrected slide 7, MVP -> pilot)
  Figure 10 -> _fig10_new.png  (grounded; supplier qualitative; no WAPE/AUC)
  Figure 11 -> _fig11_new.png  (Bounded Pilot)
"""
import os
from docx import Document
from docx.oxml.ns import qn
from PIL import Image

REV = "WP DLA/Decision_Intelligence_for_Defense_Logistics_White_Paper_ACADEMIC_final_REV_v2.docx"
SWAPS = {
    "Figure 1 - From Metrics to Mission": "docs/_fig1_new.png",
    "Figure 4 - Demand Forecasting": "docs/_fig4_new.png",
    "Figure 5 - Legacy Approach": "docs/_fig5_new.png",
    "Figure 10 - Technical Evidence Summary": "docs/_fig10_new.png",
    "Figure 11 - Bounded Pilot": "docs/_fig11_new.png",
}
d = Document(REV)
def acc(p): return "".join(x.text or "" for x in p._p.iter(qn('w:t')))
paras = d.paragraphs

def find_blip_para(cap_idx):
    # the image paragraph is at or just before the caption
    for j in range(cap_idx, max(0, cap_idx - 4), -1):
        bls = paras[j]._p.findall('.//' + qn('a:blip'))
        if bls:
            return paras[j], bls[0]
    return None, None

done = 0
for cap_key, png in SWAPS.items():
    cap_idx = next((i for i, p in enumerate(paras) if acc(p).strip().startswith(cap_key)), None)
    if cap_idx is None:
        print("CAPTION NOT FOUND:", cap_key); continue
    ppar, blip = find_blip_para(cap_idx)
    if blip is None:
        print("NO BLIP for:", cap_key); continue
    rid = blip.get(qn('r:embed'))
    part = d.part.related_parts[rid]
    newbytes = open(png, 'rb').read()
    part._blob = newbytes
    # update display extent to new aspect (keep cx, set cy)
    nw, nh = Image.open(png).size
    for ext in ppar._p.findall('.//' + qn('wp:extent')):
        if ext.get('cx'):
            cx = int(ext.get('cx')); ext.set('cy', str(round(cx * nh / nw)))
    for aext in ppar._p.findall('.//' + qn('a:ext')):
        if aext.get('cx'):
            cx = int(aext.get('cx')); aext.set('cy', str(round(cx * nh / nw)))
    print(f"swapped {cap_key[:34]:34s} <- {os.path.basename(png)} ({nw}x{nh})")
    done += 1

o = REV; k = 3
while True:
    try:
        d.save(o); break
    except PermissionError:
        root, ext = os.path.splitext(REV); o = f"{root.replace('_v2','')}_v{k}{ext}"; k += 1
print("swapped", done, "figures | saved:", o)
