# -*- coding: utf-8 -*-
"""Full-height capture of the 4 Detection Story pages for a final detail audit."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
from capture_all_pages import make_driver, select_section, click_page, URL
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
d = make_driver(); d.set_window_size(1720, 5200); d.get(URL)
WebDriverWait(d, 60).until(EC.presence_of_element_located(
    (By.CSS_SELECTOR, 'section[data-testid="stSidebar"] div[data-baseweb="select"]')))
time.sleep(4)
select_section(d, "The Detection Story"); time.sleep(1.5)
for page, fname in [
    ("Detection Pipeline", "story_pipeline.png"),
    ("Traditional vs V-Intelligence UEBA", "story_trad.png"),
    ("Three-Tier Detection", "story_tier3.png"),
    ("Detection Comparison", "story_detcomp.png"),
]:
    click_page(d, page); time.sleep(4)
    excs = d.find_elements(By.CSS_SELECTOR, '[data-testid="stException"]')
    d.save_screenshot(os.path.join(OUT, fname))
    print(f"[{page[:30]:30}] stException={len(excs)} -> {fname}")
d.quit()
