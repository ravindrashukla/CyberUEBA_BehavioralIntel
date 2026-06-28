#!/usr/bin/env python3
"""Consolidate to FINAL: strip all review comments from v6 and save a clean file.
v6 already carries every content fix (de-slop, §4.4 explainer+diagram, baseline/
cohort, Figure 3 titles, #5/#7/#9/#17/#19/#20/#25/#26, etc.)."""
import os, zipfile
from lxml import etree

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, "UEBA_Behavioral_Intelligence_Business_Friendly_v6.docx")
DST = os.path.join(HERE, "UEBA_Behavioral_Intelligence_Business_Friendly_FINAL.docx")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"

with zipfile.ZipFile(SRC) as z:
    data = {n: z.read(n) for n in z.namelist()}

# parts to drop (comment machinery)
drop = {n for n in data if n.split("/")[-1] in (
    "comments.xml", "commentsExtended.xml", "commentsIds.xml",
    "commentsExtensible.xml", "people.xml")}

# strip comment markers from document.xml
root = etree.fromstring(data["word/document.xml"])
n_start = n_end = n_ref = 0
for tag in ("commentRangeStart", "commentRangeEnd"):
    for el in list(root.iter(W + tag)):
        el.getparent().remove(el)
        if tag.endswith("Start"): n_start += 1
        else: n_end += 1
for ref in list(root.iter(W + "commentReference")):
    run = ref.getparent()                    # the w:r wrapping the reference
    if run is not None and run.getparent() is not None:
        run.getparent().remove(run)
        n_ref += 1
data["word/document.xml"] = etree.tostring(root, xml_declaration=True,
                                           encoding="UTF-8", standalone=True)

# strip comment relationships
rels = "word/_rels/document.xml.rels"
rroot = etree.fromstring(data[rels])
for rel in list(rroot):
    if any(k in rel.get("Target", "") or k in rel.get("Type", "")
           for k in ("comments", "people")):
        rroot.remove(rel)
data[rels] = etree.tostring(rroot, xml_declaration=True, encoding="UTF-8", standalone=True)

# strip content-type overrides
croot = etree.fromstring(data["[Content_Types].xml"])
for ov in list(croot):
    if any(k in ov.get("PartName", "") for k in ("comments", "people")):
        croot.remove(ov)
data["[Content_Types].xml"] = etree.tostring(croot, xml_declaration=True,
                                             encoding="UTF-8", standalone=True)

with zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED) as z:
    for n, b in data.items():
        if n not in drop:
            z.writestr(n, b)

print(f"removed: {n_start} ranges, {n_ref} references; dropped parts: {sorted(p.split('/')[-1] for p in drop)}")
print(f"Saved: {os.path.basename(DST)}")
