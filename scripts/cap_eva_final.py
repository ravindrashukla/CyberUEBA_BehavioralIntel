# -*- coding: utf-8 -*-
"""Confirm USR-EVA appears on Behavioral Drift + Digital Entity (select it) with no errors."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
from capture_all_pages import make_driver, select_section, click_page, URL
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
d = make_driver(); d.set_window_size(1720, 2600); d.get(URL)
WebDriverWait(d, 60).until(EC.presence_of_element_located(
    (By.CSS_SELECTOR, 'section[data-testid="stSidebar"] div[data-baseweb="select"]')))
time.sleep(4)

# --- Behavioral Drift ---
select_section(d, "Investigate an Entity"); time.sleep(1.5)
click_page(d, "Behavioral Drift"); time.sleep(5)
body = d.find_element(By.TAG_NAME, "body").text
excs = len(d.find_elements(By.CSS_SELECTOR, '[data-testid="stException"]'))
print(f"[Behavioral Drift] EVA mentions={body.count('USR-EVA')}  stException={excs}")
d.save_screenshot(os.path.join(OUT, "eva_bdrift_final.png"))

# --- Digital Entity: select USR-EVA in the main selectbox ---
click_page(d, "Digital Entity"); time.sleep(5)
# the entity selectbox is the first stSelectbox in the main area
sel = d.find_elements(By.CSS_SELECTOR, 'section.main div[data-baseweb="select"], div[data-testid="stMainBlockContainer"] div[data-baseweb="select"]')
picked = False
if sel:
    sel[0].click(); time.sleep(1.2)
    opts = d.find_elements(By.CSS_SELECTOR, 'li[role="option"], div[data-baseweb="menu"] li')
    for o in opts:
        if "USR-EVA" in (o.text or ""):
            o.click(); picked = True; break
    if not picked and opts:
        # type to filter
        try:
            from selenium.webdriver.common.keys import Keys
            inp = d.switch_to.active_element; inp.send_keys("USR-EVA"); time.sleep(1)
            opts = d.find_elements(By.CSS_SELECTOR, 'li[role="option"]')
            for o in opts:
                if "USR-EVA" in (o.text or ""): o.click(); picked = True; break
        except Exception as e:
            print("  filter attempt:", e)
time.sleep(5)
body2 = d.find_element(By.TAG_NAME, "body").text
excs2 = len(d.find_elements(By.CSS_SELECTOR, '[data-testid="stException"]'))
has_struct = ("Text Serialization" in body2) or ("Behavioral regime" in body2) or ("Raw Telemetry" in body2)
print(f"[Digital Entity] picked_EVA={picked}  EVA mentions={body2.count('USR-EVA')}  structure_shown={has_struct}  stException={excs2}")
d.save_screenshot(os.path.join(OUT, "eva_digent_final.png"))
d.quit()
print("RESULT:", "OK" if (excs==0 and excs2==0 and body.count('USR-EVA')>0 and picked) else "CHECK")
