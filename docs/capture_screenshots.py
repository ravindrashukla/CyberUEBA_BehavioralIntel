#!/usr/bin/env python3
"""Capture full-page screenshots from Streamlit by expanding all containers."""

import os
import time
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By

OUT_DIR = "docs/screenshots"
os.makedirs(OUT_DIR, exist_ok=True)
BASE_URL = "http://localhost:8505"
WIDTH = 1920

EXPAND_JS = """
document.querySelectorAll(
    "section.main, [data-testid='stAppViewContainer'], [data-testid='stMain'], " +
    "[data-testid='stMainBlockContainer'], .block-container, .appview-container, " +
    "[data-testid='stVerticalBlock'], [data-testid='stAppViewBlockContainer']"
).forEach(function(el) {
    el.style.overflow = "visible";
    el.style.maxHeight = "none";
    el.style.height = "auto";
});
// Also fix the stApp root
var app = document.querySelector('[data-testid="stApp"]');
if (app) { app.style.overflow = "visible"; app.style.maxHeight = "none"; app.style.height = "auto"; }
return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
"""


def setup_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument(f"--window-size={WIDTH},1080")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--force-device-scale-factor=1")
    return webdriver.Edge(options=opts)


def click_page(driver, page_text):
    time.sleep(2)
    labels = driver.find_elements(By.CSS_SELECTOR, ".stRadio label")
    for label in labels:
        if page_text.lower() in label.text.strip().lower():
            label.click()
            time.sleep(10)
            return True
    return False


def capture_full(driver, filename):
    """Expand all containers, resize window to full content height, capture."""
    # First pass: expand overflow
    h1 = driver.execute_script(EXPAND_JS)
    time.sleep(2)

    # Second pass after DOM reflows
    h2 = driver.execute_script(EXPAND_JS)
    time.sleep(1)

    h = max(h1 or 1080, h2 or 1080)
    capped = min(h + 300, 20000)

    driver.set_window_size(WIDTH, capped)
    time.sleep(3)

    # Third pass at new window size
    h3 = driver.execute_script(EXPAND_JS)
    time.sleep(1)
    if h3 and h3 > capped:
        capped = min(h3 + 300, 20000)
        driver.set_window_size(WIDTH, capped)
        time.sleep(2)

    driver.execute_script("window.scrollTo(0, 0)")
    time.sleep(1)

    path = os.path.join(OUT_DIR, filename)
    driver.save_screenshot(path)
    print(f"  {filename} — {capped}px tall")

    # Reset window
    driver.set_window_size(WIDTH, 1080)
    time.sleep(1)
    return capped


def crop_sections(filename, total_h, section_h=1080):
    """Use PIL to crop the full screenshot into sections for the deck."""
    try:
        from PIL import Image
        img = Image.open(os.path.join(OUT_DIR, filename))
        w, h = img.size
        prefix = filename.replace("_full.png", "")
        idx = 0
        y = 0
        while y < h:
            bottom = min(y + section_h, h)
            crop = img.crop((0, y, w, bottom))
            section_name = f"{prefix}_sec_{idx:02d}.png"
            crop.save(os.path.join(OUT_DIR, section_name))
            print(f"    Cropped: {section_name} (y={y}-{bottom})")
            y += section_h - 50  # slight overlap
            idx += 1
        return idx
    except Exception as e:
        print(f"    Crop failed: {e}")
        return 0


def main():
    print("Capturing screenshots...")
    driver = setup_driver()

    try:
        driver.get(BASE_URL)
        time.sleep(8)

        pages = [
            ("traditional vs v-intelligence", "trad_full.png"),
            ("three-tier", "tier3_full.png"),
            ("detection comparison", "comp_full.png"),
        ]

        for page_text, fname in pages:
            print(f"\n=== {page_text} ===")
            driver.set_window_size(WIDTH, 1080)
            click_page(driver, page_text)
            h = capture_full(driver, fname)
            n = crop_sections(fname, h)
            print(f"  Done: {n} sections")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        driver.quit()

    print("\nAll done! Screenshots in docs/screenshots/")


if __name__ == "__main__":
    main()
