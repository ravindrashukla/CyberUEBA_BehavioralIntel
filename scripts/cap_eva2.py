# -*- coding: utf-8 -*-
"""Verify EVA on the canonical pages + capture screenshots; flag any stException."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
from capture_all_pages import make_driver, select_section, click_page, URL
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
d = make_driver(); d.set_window_size(1720, 4200); d.get(URL)
WebDriverWait(d, 60).until(EC.presence_of_element_located(
    (By.CSS_SELECTOR, 'section[data-testid="stSidebar"] div[data-baseweb="select"]')))
time.sleep(4)

targets = [
    ("The Detection Story", "Traditional vs V-Intelligence UEBA", "eva_trad.png"),
    ("The Detection Story", "Three-Tier Detection", "eva_tier3.png"),
    ("Operations", "Threat Profiles", "eva_threatprofiles.png"),
    ("Data", "Guided Demo", "eva_guided0.png"),
]
for section, page, fname in targets:
    try:
        select_section(d, section); time.sleep(1.5)
        click_page(d, page); time.sleep(4)
        excs = d.find_elements(By.CSS_SELECTOR, '[data-testid="stException"]')
        body = d.find_element(By.TAG_NAME, "body").text
        n_eva = body.count("USR-EVA") + body.count("EVA")
        n_of5 = body.count("of 5") + body.count("/ 5") + body.count("5 / 5") + body.count("5/5")
        d.save_screenshot(os.path.join(OUT, fname))
        print(f"[{page[:28]:28}] EVA={n_eva:2d}  of-5 hits={n_of5:2d}  stException={len(excs)} -> {fname}")
    except Exception as e:
        print(f"[{page[:28]:28}] ERROR {e}")
d.quit()
