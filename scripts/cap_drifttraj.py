# -*- coding: utf-8 -*-
"""Screenshot the per-user Drift Trajectory chart + confirm the 246-normal band renders."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
from capture_all_pages import make_driver, select_section, click_page, URL
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
d = make_driver(); d.set_window_size(1720, 1250); d.get(URL)
WebDriverWait(d, 60).until(EC.presence_of_element_located(
    (By.CSS_SELECTOR, 'section[data-testid="stSidebar"] div[data-baseweb="select"]')))
time.sleep(4)
select_section(d, "The Detection Story"); time.sleep(1.5)
click_page(d, "Detection Comparison"); time.sleep(6)
els = d.find_elements(By.XPATH, "//*[contains(text(),'Drift Trajectory: Feature Space vs Semantic Space')]")
if els:
    d.execute_script("arguments[0].scrollIntoView({block:'start'});", els[0]); time.sleep(3)
excs = d.find_elements(By.CSS_SELECTOR, '[data-testid="stException"]')
legend = [t.text for t in d.find_elements(By.CSS_SELECTOR, "g.legend text") if t.text]
print("stException:", len(excs))
print("legend labels:", sorted(set(legend)))
print("band present:", any("Normal range" in x for x in legend), "| median present:", any("median" in x.lower() for x in legend))
d.save_screenshot(os.path.join(OUT, "cap_drifttraj.png"))
d.quit()
