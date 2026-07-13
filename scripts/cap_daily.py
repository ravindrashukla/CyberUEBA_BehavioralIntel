# -*- coding: utf-8 -*-
"""Capture the two daily-trajectory pages and report the x-axis extent actually rendered."""
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

for section, page, fname in [
    ("Investigate an Entity", "Behavioral Drift", "eva_bdrift.png"),
    ("Investigate an Entity", "Drift Trajectory", "eva_dtraj.png"),
]:
    select_section(d, section); time.sleep(1.5)
    click_page(d, page); time.sleep(5)
    # grab plotly x-axis tick labels (dates or week numbers)
    ticks = [t.text for t in d.find_elements(By.CSS_SELECTOR, "g.xaxislayer-above text") if t.text]
    d.save_screenshot(os.path.join(OUT, fname))
    print(f"[{page}] x-axis ticks: {ticks[:14]} -> {fname}")
d.quit()
