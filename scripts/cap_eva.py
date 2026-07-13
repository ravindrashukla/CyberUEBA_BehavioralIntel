# -*- coding: utf-8 -*-
"""Capture the two EVA-fixed pages full-height and report whether 'USR-EVA' appears in the DOM."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
from capture_all_pages import make_driver, select_section, click_page, URL
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
d = make_driver(); d.set_window_size(1720, 3200); d.get(URL)
WebDriverWait(d, 60).until(EC.presence_of_element_located(
    (By.CSS_SELECTOR, 'section[data-testid="stSidebar"] div[data-baseweb="select"]')))
time.sleep(4)

targets = [
    ("The Detection Story", "Detection Comparison", "eva_detcomp.png"),
    ("The Detection Story", "Detection Pipeline", "eva_pipeline.png"),
]
for section, page, fname in targets:
    select_section(d, section); time.sleep(1.5)
    click_page(d, page); time.sleep(4)
    body = d.find_element(By.TAG_NAME, "body").text
    n_eva = body.count("USR-EVA") + body.count("EVA")
    # count plotly legend items mentioning EVA
    leg = d.find_elements(By.CSS_SELECTOR, "g.legend text")
    leg_eva = sum(1 for e in leg if "EVA" in (e.text or ""))
    d.set_window_size(1720, 3600); time.sleep(1)
    path = os.path.join(OUT, fname)
    d.find_element(By.TAG_NAME, "body").screenshot(path) if False else d.save_screenshot(path)
    print(f"[{page}] EVA text mentions={n_eva} | legend traces w/EVA={leg_eva} -> {fname}")
d.quit()
