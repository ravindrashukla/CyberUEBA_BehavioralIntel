# -*- coding: utf-8 -*-
"""Derive the light-locked, auto-fitting in-app embed of the Behavioral Digital Twin
pipeline diagram from the standalone artifact HTML.

Source (standalone, theme-aware):  CyberUEBA_Whitepapers/docs/twin_pipeline_diagram.html
Output (app embed, light-only):     assets/twin_pipeline_embed.html

The Streamlit app is a light theme, so we strip the dark-theme CSS and lock to light,
blend the page background to the app's LGRAY, drop the dotted grid, and add a same-origin
auto-fit script so components.html renders the whole diagram inline (no nested scroll).
Re-run whenever the source diagram changes.
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "CyberUEBA_Whitepapers" / "docs" / "twin_pipeline_diagram.html"
OUT = Path(__file__).resolve().parent / "twin_pipeline_embed.html"

html = SRC.read_text(encoding="utf-8")

# 1. Drop the standalone <title> (not needed inside an iframe).
html = re.sub(r"<title>.*?</title>\s*", "", html, flags=re.DOTALL)

# 2. Remove the dark-theme blocks so the light :root governs unconditionally.
#    (a) the prefers-color-scheme media query wrapping a single :root{...}
html = re.sub(r"@media \(prefers-color-scheme:dark\)\{\s*:root\{[^}]*\}\s*\}\s*", "", html)
#    (b) the explicit dark data-theme override
html = re.sub(r':root\[data-theme="dark"\]\{[^}]*\}\s*', "", html)

# 3. Blend into the app: LGRAY page bg + no dotted grid.
html = html.replace("--bg:#EAEFF5;", "--bg:#F7F8FA;")
html = html.replace(
    "background-image:radial-gradient(circle at 1px 1px, var(--line) 1px, transparent 0);",
    "background-image:none;",
)

# 4. Same-origin auto-fit: grow the host iframe to full content height (no inner scroll).
AUTOFIT = """
<script>
(function(){
  function fit(){
    var h = Math.ceil(document.body.getBoundingClientRect().height) + 4;
    try{
      var host = window.frameElement;              // the <iframe> in the parent doc (same origin)
      if(!host) return;
      host.style.height = h + "px";
      host.setAttribute("height", h);
      // Streamlit clamps the wrapping element container to the fallback height;
      // grow the ancestors so the full diagram shows inline (no overlap, no nested scroll).
      var el = host.parentElement, i = 0;
      while(el && i < 5){
        if(el.style){ el.style.height = h + "px"; el.style.maxHeight = "none"; }
        el = el.parentElement; i++;
      }
    }catch(e){}
  }
  window.addEventListener("load", fit);
  window.addEventListener("resize", fit);
  if(window.ResizeObserver){ new ResizeObserver(fit).observe(document.body); }
  [120, 400, 900, 1800].forEach(function(t){ setTimeout(fit, t); });
})();
</script>
"""
html = html.rstrip() + "\n" + AUTOFIT + "\n"

OUT.write_text(html, encoding="utf-8")
print(f"wrote {OUT}  ({len(html):,} bytes)")
# sanity: no dark-theme residue should remain
for bad in ("prefers-color-scheme:dark", 'data-theme="dark"{'):
    assert bad not in html, f"residual dark-theme css: {bad}"
print("light-lock verified: no dark-theme residue")
