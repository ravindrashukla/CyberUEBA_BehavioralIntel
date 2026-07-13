# -*- coding: utf-8 -*-
"""Thorough verify of Detection Comparison: long wait, scroll to force full render, count cards, catch stException."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
from capture_all_pages import make_driver, select_section, click_page, URL
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
d = make_driver(); d.set_window_size(1720, 2200); d.get(URL)
WebDriverWait(d, 60).until(EC.presence_of_element_located(
    (By.CSS_SELECTOR, 'section[data-testid="stSidebar"] div[data-baseweb="select"]')))
time.sleep(4)
select_section(d, "The Detection Story"); time.sleep(1.5)
click_page(d, "Detection Comparison"); time.sleep(6)
# force full render: scroll to bottom in steps, wait for the running spinner to clear
for _ in range(12):
    d.execute_script("window.scrollTo(0, document.body.scrollHeight);"); time.sleep(1.2)
# wait until no stStatusWidget "Running"
for _ in range(20):
    running = d.find_elements(By.CSS_SELECTOR, '[data-testid="stStatusWidget"]')
    if not running or all("Running" not in (r.text or "") for r in running):
        break
    time.sleep(1)
time.sleep(2)
excs = d.find_elements(By.CSS_SELECTOR, '[data-testid="stException"]')
body = d.find_element(By.TAG_NAME, "body").text
has_tb = any(k in body for k in ["Traceback", "IndexError", "KeyError", "out of range", "out-of-bounds"])
# count per-attacker breakdown cards: look for the "Composite Score:" card marker
n_cards = body.count("Composite Score:")
n_eva = body.count("USR-EVA") + body.count("EVA")
print("stException elements:", len(excs))
print("traceback/error text present:", has_tb)
print("per-attacker cards (Composite Score: markers):", n_cards)
print("EVA mentions:", n_eva)
d.save_screenshot(os.path.join(OUT, "verify_detcomp.png"))
d.quit()
print("RESULT:", "FAIL" if (excs or has_tb) else "CLEAN")
