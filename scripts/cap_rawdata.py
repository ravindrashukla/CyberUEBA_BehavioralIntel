# -*- coding: utf-8 -*-
"""Expand the new Raw-telemetry section on Detection Comparison and confirm it renders."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
from capture_all_pages import make_driver, select_section, click_page, URL
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
d = make_driver(); d.set_window_size(1720, 2400); d.get(URL)
WebDriverWait(d, 60).until(EC.presence_of_element_located(
    (By.CSS_SELECTOR, 'section[data-testid="stSidebar"] div[data-baseweb="select"]')))
time.sleep(4)
select_section(d, "The Detection Story"); time.sleep(1.5)
click_page(d, "Detection Comparison"); time.sleep(5)
# find + click the raw-telemetry expander
exps = d.find_elements(By.CSS_SELECTOR, '[data-testid="stExpander"] summary, details summary, [role="button"]')
clicked = False
for e in exps:
    if "the 23 features we derive" in (e.text or ""):
        d.execute_script("arguments[0].scrollIntoView({block:'center'});", e); time.sleep(0.5)
        e.click(); clicked = True; break
time.sleep(2)
body = d.find_element(By.TAG_NAME, "body").text
excs = len(d.find_elements(By.CSS_SELECTOR, '[data-testid="stException"]'))
print("expander clicked:", clicked)
print("has 'Raw event streams' tab:", "Raw event streams" in body)
print("has 'Derived features' tab:", "Derived features" in body)
print("shows a feature name (auth_off_hours_ratio):", "auth_off_hours_ratio" in body)
print("stException:", excs)
d.save_screenshot(os.path.join(OUT, "raw_data_section.png"))
d.quit()
