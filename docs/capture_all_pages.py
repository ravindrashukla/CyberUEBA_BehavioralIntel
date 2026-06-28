#!/usr/bin/env python3
"""Full-page screenshot every nav page of the live app for a UI/UX audit.
App must be running on :8502. Writes docs/page_audit/NN_<page>.png.
"""
import sys, os, time, glob, base64, math
sys.stdout.reconfigure(encoding="utf-8")
from selenium import webdriver
from selenium.webdriver.common.by import By

URL = "http://localhost:8502/"
W, H = 1680, 1600
OUT = "docs/page_audit"
PW_CHROME = os.path.expanduser("~/AppData/Local/ms-playwright/chromium-1223/chrome-win/chrome.exe")

GROUPS = {
    "Start Here": ["Story Mode", "Guided Demo"],
    "The Detection Story": ["Detection Pipeline", "Traditional vs V-Intelligence UEBA",
                            "Three-Tier Detection", "Detection Comparison"],
    "Operations": ["Dashboard", "Alerts", "Threat Profiles", "Kill Chains"],
    "Investigate an Entity": ["Behavioral Drift", "Drift Trajectory",
                              "Behavioral Profile", "Digital Entity"],
    "Methods & Proof": ["Proof of Realism", "Telemetry Explorer"],
}


def make_driver():
    errs = []
    for binloc in (None, PW_CHROME):
        try:
            o = webdriver.ChromeOptions()
            o.add_argument("--headless=new"); o.add_argument(f"--window-size={W},{H}")
            o.add_argument("--hide-scrollbars"); o.add_argument("--force-device-scale-factor=1")
            o.add_argument("--no-sandbox"); o.add_argument("--disable-gpu")
            if binloc and os.path.exists(binloc):
                o.binary_location = binloc
            return webdriver.Chrome(options=o)
        except Exception as e:
            errs.append(str(e))
    try:
        o = webdriver.EdgeOptions()
        o.add_argument("--headless=new"); o.add_argument(f"--window-size={W},{H}")
        o.add_argument("--hide-scrollbars"); o.add_argument("--force-device-scale-factor=1")
        return webdriver.Edge(options=o)
    except Exception as e:
        errs.append(str(e))
    raise SystemExit("No browser:\n" + "\n".join(errs))


def full_png(d, path, cap=2600):
    m = d.execute_cdp_cmd("Page.getLayoutMetrics", {})
    w = math.ceil(m["cssContentSize"]["width"]); h = min(math.ceil(m["cssContentSize"]["height"]), cap)
    res = d.execute_cdp_cmd("Page.captureScreenshot",
                            {"clip": {"x": 0, "y": 0, "width": w, "height": h, "scale": 1},
                             "captureBeyondViewport": True})
    with open(path, "wb") as f:
        f.write(base64.b64decode(res["data"]))


def select_section(d, section):
    from selenium.webdriver.common.keys import Keys
    sb = d.find_element(By.CSS_SELECTOR, 'section[data-testid="stSidebar"] div[data-baseweb="select"]')
    d.execute_script("arguments[0].scrollIntoView({block:'center'});", sb)
    sb.click()  # native click — baseweb opens on real pointer events, not JS .click()
    time.sleep(1.0)
    opts = d.find_elements(By.CSS_SELECTOR, 'li[role="option"]')
    for o in opts:
        if o.text.strip() == section:
            o.click(); time.sleep(2.0); return
    # fallback: type to filter, then Enter
    try:
        inp = sb.find_element(By.CSS_SELECTOR, 'input')
        inp.send_keys(section); time.sleep(0.6); inp.send_keys(Keys.ENTER)
    except Exception:
        pass
    time.sleep(2.0)


def click_page(d, page):
    for l in d.find_elements(By.CSS_SELECTOR, 'section[data-testid="stSidebar"] div[role="radiogroup"] label'):
        if l.text.strip() == page:
            d.execute_script("arguments[0].scrollIntoView({block:'center'});", l)
            d.execute_script("arguments[0].click();", l); break
    time.sleep(3.0)


def main():
    os.makedirs(OUT, exist_ok=True)
    for f in glob.glob(OUT + "/*.png"):
        os.remove(f)
    d = make_driver(); d.set_window_size(W, H); d.get(URL); time.sleep(6)
    idx = 0
    for section, pages in GROUPS.items():
        try:
            select_section(d, section)
        except Exception as e:
            print(f"  section '{section}' select failed: {e}")
        for page in pages:
            try:
                click_page(d, page)
                d.execute_script("window.scrollTo(0,0);"); time.sleep(0.4)
                safe = page.replace(" ", "_").replace("/", "-")[:24]
                full_png(d, f"{OUT}/{idx:02d}_{safe}.png")
                print(f"  [{idx:02d}] {section} → {page}")
            except Exception as e:
                print(f"  [{idx:02d}] {page} FAILED: {e}")
            idx += 1
    d.quit()
    print(f"captured {len(glob.glob(OUT + '/*.png'))} pages to {OUT}/")


if __name__ == "__main__":
    main()
