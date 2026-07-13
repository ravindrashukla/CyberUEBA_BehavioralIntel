# -*- coding: utf-8 -*-
"""Screenshot the Signal Separation panels to confirm the median-normal baseline renders."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
from capture_all_pages import make_driver, select_section, click_page, URL
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
d = make_driver(); d.set_window_size(1720, 1200); d.get(URL)
WebDriverWait(d, 60).until(EC.presence_of_element_located(
    (By.CSS_SELECTOR, 'section[data-testid="stSidebar"] div[data-baseweb="select"]')))
time.sleep(4)
select_section(d, "The Detection Story"); time.sleep(1.5)
click_page(d, "Detection Comparison"); time.sleep(6)
# find the Signal Separation heading and scroll it into view
els = d.find_elements(By.XPATH, "//*[contains(text(),'All Attack Users: Signal Separation')]")
if els:
    d.execute_script("arguments[0].scrollIntoView({block:'start'});", els[0]); time.sleep(3)
legend = [t.text for t in d.find_elements(By.CSS_SELECTOR, "g.legend text") if t.text]
print("legend labels found:", sorted(set(legend)))
print("median baseline present:", any("Typical normal user" in x for x in legend))
d.save_screenshot(os.path.join(OUT, "cap_sigsep.png"))
d.quit()
