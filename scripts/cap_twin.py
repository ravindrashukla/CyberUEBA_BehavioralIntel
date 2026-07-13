# -*- coding: utf-8 -*-
"""Screenshot the Digital Entity twin-pipeline embed to confirm EVA is in the ranking/stat tables."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
from capture_all_pages import make_driver, select_section, click_page, URL
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
d = make_driver(); d.set_window_size(1720, 3000); d.get(URL)
WebDriverWait(d, 60).until(EC.presence_of_element_located(
    (By.CSS_SELECTOR, 'section[data-testid="stSidebar"] div[data-baseweb="select"]')))
time.sleep(4)
select_section(d, "Investigate an Entity"); time.sleep(1.5)
click_page(d, "Digital Entity"); time.sleep(6)
# the twin embed is an iframe (components.html); read its body text for EVA references
frames = d.find_elements(By.TAG_NAME, "iframe")
hits = 0
for fr in frames:
    try:
        d.switch_to.frame(fr)
        t = d.find_element(By.TAG_NAME, "body").text
        if "USR-EVA" in t or "Evasive" in t:
            hits += t.count("USR-EVA") + t.count("Evasive")
            print("  twin embed EVA mentions:", t.count("USR-EVA") + t.count("Evasive"),
                  "| 5/5:", "5/5" in t, "| catch-all-five:", "catch-all-five" in t)
        d.switch_to.default_content()
    except Exception:
        d.switch_to.default_content()
d.save_screenshot(os.path.join(OUT, "twin_embed_eva.png"))
d.quit()
print("RESULT:", "EVA in twin embed" if hits else "EVA NOT found in twin embed")
