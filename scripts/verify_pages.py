# -*- coding: utf-8 -*-
"""Drive every nav page in the live app and check the DOM for st exceptions / errors."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs"))
from capture_all_pages import make_driver, select_section, click_page, GROUPS, URL
from selenium.webdriver.common.by import By

d = make_driver(); d.set_window_size(1680, 2200); d.get(URL); time.sleep(6)
errors = []
for section, pages in GROUPS.items():
    try:
        select_section(d, section)
    except Exception as e:
        print("  section '%s' select failed: %s" % (section, e))
    for page in pages:
        try:
            click_page(d, page); time.sleep(2.5)
            excs = d.find_elements(By.CSS_SELECTOR, '[data-testid="stException"]')
            body = d.find_element(By.TAG_NAME, "body").text
            has_tb = "Traceback" in body or "is out-of-bounds" in body or "KeyError" in body or "NameError" in body
            bad = bool(excs) or has_tb
            print("  [%-5s] %-32s%s" % ("ERROR" if bad else "ok", page,
                  "  (%d stException)" % len(excs) if excs else ("  (traceback in text)" if has_tb else "")))
            if bad:
                errors.append(page)
        except Exception as e:
            print("  [FAIL ] %-32s %s" % (page, e)); errors.append(page)
d.quit()
print("\n" + ("ALL 16 PAGES CLEAN" if not errors else "ERRORS on: " + ", ".join(errors)))
