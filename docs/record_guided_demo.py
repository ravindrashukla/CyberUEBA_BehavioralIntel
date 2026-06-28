#!/usr/bin/env python3
"""Drive the live Guided Demo page (headless browser) and record a click-through MP4.
Captures each of the 9 steps as a full-frame screenshot, then assembles a video
holding each step long enough to read. The app must be running on :8502.
Output: docs/Guided_Demo_Recording.mp4
"""
import sys, os, time, glob, base64, math
sys.stdout.reconfigure(encoding="utf-8")
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
from selenium import webdriver
from selenium.webdriver.common.by import By


def full_page_png(d, path, cap=1500):
    """Full-page screenshot via CDP (captures the whole step, not just viewport)."""
    m = d.execute_cdp_cmd("Page.getLayoutMetrics", {})
    w = math.ceil(m["cssContentSize"]["width"])
    h = min(math.ceil(m["cssContentSize"]["height"]), cap)
    res = d.execute_cdp_cmd("Page.captureScreenshot", {
        "clip": {"x": 0, "y": 0, "width": w, "height": h, "scale": 1},
        "captureBeyondViewport": True,
    })
    with open(path, "wb") as f:
        f.write(base64.b64decode(res["data"]))

URL = "http://localhost:8502/"
W, H = 1680, 1400  # tall window so each step's full content (incl. charts) is visible
FR = "docs/demo_record_frames"
OUT = "docs/Guided_Demo_Recording.mp4"
N_STEPS = 9
HOLD = [6, 7, 7, 8, 8, 7, 7, 7, 8]  # seconds per step

PW_CHROME = os.path.expanduser(
    "~/AppData/Local/ms-playwright/chromium-1223/chrome-win/chrome.exe")


def make_driver():
    errs = []
    # 1) Chrome (system or Playwright's chromium binary)
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
            errs.append(f"chrome({binloc}): {e}")
    # 2) Edge (always on Win11)
    try:
        o = webdriver.EdgeOptions()
        o.add_argument("--headless=new"); o.add_argument(f"--window-size={W},{H}")
        o.add_argument("--hide-scrollbars"); o.add_argument("--force-device-scale-factor=1")
        return webdriver.Edge(options=o)
    except Exception as e:
        errs.append(f"edge: {e}")
    raise SystemExit("No browser driver available:\n  " + "\n  ".join(errs))


def record():
    os.makedirs(FR, exist_ok=True)
    for f in glob.glob(FR + "/*.png"):
        os.remove(f)
    d = make_driver()
    d.set_window_size(W, H)
    d.get(URL)
    time.sleep(6)  # initial Streamlit load

    # Select the "Guided Demo" radio in the sidebar
    lbl = d.find_element(By.XPATH, "//div[@role='radiogroup']//label[contains(., 'Guided Demo')]")
    d.execute_script("arguments[0].scrollIntoView({block:'center'});", lbl)
    time.sleep(0.5)
    d.execute_script("arguments[0].click();", lbl)

    # Wait for the Guided Walkthrough header
    for _ in range(30):
        if "Guided Walkthrough" in d.page_source:
            break
        time.sleep(0.5)
    time.sleep(2)

    for i in range(N_STEPS):
        time.sleep(3.2)  # let charts/plotly render
        d.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.4)
        full_page_png(d, f"{FR}/step_{i:02d}.png")
        print(f"  captured step {i + 1}/{N_STEPS}")
        if i < N_STEPS - 1:
            nxt = d.find_element(By.XPATH, "//button[contains(., 'Next')]")
            d.execute_script("arguments[0].scrollIntoView({block:'center'});", nxt)
            time.sleep(0.3)
            d.execute_script("arguments[0].click();", nxt)
    d.quit()
    frames = sorted(glob.glob(FR + "/*.png"))
    print(f"captured {len(frames)} frames")
    return frames


def assemble(frames):
    import numpy as np
    from PIL import Image
    try:
        from moviepy import ImageClip, concatenate_videoclips
    except ImportError:
        from moviepy.editor import ImageClip, concatenate_videoclips
    # Pad every (variable-height) full-page frame onto one uniform white canvas,
    # top-aligned, so nothing is cropped and all clips share a size.
    ims = [Image.open(fp).convert("RGB") for fp in frames]
    cw = max(im.width for im in ims)
    ch = max(im.height for im in ims)
    clips = []
    for i, im in enumerate(ims):
        canvas = Image.new("RGB", (cw, ch), (255, 255, 255))
        canvas.paste(im, (0, 0))
        dur = HOLD[i] if i < len(HOLD) else 6
        clips.append(ImageClip(np.array(canvas), duration=dur))
    target = (cw, ch)
    video = concatenate_videoclips(clips, method="compose")
    video.write_videofile(OUT, fps=24, codec="libx264", audio=False, logger="bar")
    print(f"\nSaved {OUT}  ({sum(HOLD[:len(frames)])}s, {target[0]}x{target[1]})")


AUDIO_DIR_GD = "docs/narration_audio_guided"
GD_NARRATIONS = [
    # 0 Welcome
    "Same data — four stealth attacks hidden among 250 users over 70 weeks. We layer five detection methods on the same logs; each layer catches what the last one missed. Here are the four hidden attacks.",
    # 1 Layer 1 traditional
    "Layer one is what most agencies run today: point-anomaly tools that score each user against a threshold. They catch zero of four. A simple z-score catches one — the living-off-the-land case — but alarms on nearly everyone. Three attackers, including Salt Typhoon, stay invisible.",
    # 2 Layer 2 drift
    "Layer two reads the same logs as behavioral entities, tracked over time. On any given week the attacker looks normal — the stealth APT sits inside the normal band ninety-seven percent of the time. But behavior accumulates: watch the cumulative drift, and the slow movers climb out of the normal range.",
    # 3 Signal separation
    "Two lenses make this concrete. The raw-magnitude lens flags the noisy volume attack first, even before the AI. The semantic lens flags the subtle insider and stealth hacker about thirty weeks earlier. The stars mark first clear detection. Neither lens catches the slow APT on its own.",
    # 4 The hard case
    "Zoom in on the hardest case. Isolate the slow APT against the normal pack. On the raw-magnitude lens, and on the semantic lens, its drift never separates — it looks like an ordinary user on both. Drift alone will never catch it; it needs the threat-profile detector.",
    # 5 Layer 3 radar
    "Layer three asks five behavioral questions at once: signal strength, breadth, how long it persisted, how unlike its peers it became, and whether new connections keep recurring. Normal users cluster in the center; each attacker is extreme on a different phase. The slow APT spikes on novelty persistence — its C2 beacon.",
    # 6 Layer 4 composite
    "Layer four fuses the five phases into a single ranked score. Now all four campaigns rise above the line that catches all four — including the two stealth movers that hid in the crowd. The honest cost: catching all four flags about eight percent of normal users for review.",
    # 7 Layer 5 known-bad
    "Layer five removes that noise. Instead of only how far a user has drifted, it asks whether the behavior matches a measurable known-bad profile — a beacon's robotic timing, an algorithmically generated domain, a destination no peer contacts. All four campaigns match; no normal entity does. Four of four at zero false positives.",
    # 8 Verdict
    "The verdict, layer by layer. Traditional: zero of four. Intermediate statistics: one of four. The fused composite: four of four. The known-bad profiles: four of four, at zero false positives. Same data, same users — a fundamentally different understanding of behavior.",
]


def gd_tts(voice="nova"):
    import hashlib
    from openai import OpenAI
    client = OpenAI()
    os.makedirs(AUDIO_DIR_GD, exist_ok=True)
    files = []
    for i, text in enumerate(GD_NARRATIONS):
        key = hashlib.md5(text.encode("utf-8")).hexdigest()[:10]
        path = os.path.join(AUDIO_DIR_GD, f"n_{key}.mp3")
        if not os.path.exists(path):
            print(f"  TTS {i + 1}/{len(GD_NARRATIONS)} (voice={voice})...")
            resp = client.audio.speech.create(model="tts-1-hd", voice=voice, input=text, response_format="mp3")
            if hasattr(resp, "write_to_file"):
                resp.write_to_file(path)
            elif hasattr(resp, "stream_to_file"):
                resp.stream_to_file(path)
            else:
                with open(path, "wb") as f:
                    f.write(resp.content)
        else:
            print(f"  narration {i:02d}: cached")
        files.append(path)
    return files


def assemble_narrated(frames, voice="nova"):
    import numpy as np
    from PIL import Image
    try:
        from moviepy import ImageClip, AudioFileClip, concatenate_videoclips
    except ImportError:
        from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
    audio = gd_tts(voice)
    ims = [Image.open(fp).convert("RGB") for fp in frames]
    cw = max(im.width for im in ims); ch = max(im.height for im in ims)
    clips, total = [], 0.0
    for i, im in enumerate(ims):
        canvas = Image.new("RGB", (cw, ch), (255, 255, 255)); canvas.paste(im, (0, 0))
        a = AudioFileClip(audio[i]); dur = a.duration + 1.3
        clip = ImageClip(np.array(canvas), duration=dur)
        try:
            clip = clip.with_audio(a)
        except AttributeError:
            clip = clip.set_audio(a)
        clips.append(clip); total += dur
    video = concatenate_videoclips(clips, method="compose")
    video.write_videofile(OUT, fps=24, codec="libx264", audio_codec="aac", logger="bar")
    print(f"\nSaved NARRATED {OUT}  ({total:.0f}s, {cw}x{ch}, voice={voice})")


if __name__ == "__main__":
    narrate = "--narrate" in sys.argv
    have = sorted(glob.glob(FR + "/*.png"))
    rerecord = ("--rerecord" in sys.argv) or not have
    frames = record() if rerecord else have
    if not frames:
        raise SystemExit("No frames captured.")
    if narrate:
        assemble_narrated(frames)
    else:
        assemble(frames)
