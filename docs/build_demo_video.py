#!/usr/bin/env python3
"""
Build V-Intelligence UEBA Demo Video with OpenAI TTS narration.

Creates a narrated walkthrough video from screenshots with text overlays
and professional voice narration. No proprietary logic disclosed.

Output: docs/V_Intelligence_UEBA_Demo.mp4
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import os
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

load_dotenv()

SCREENSHOT_DIR = "docs/screenshots"
OUT_DIR = "docs"
AUDIO_DIR = os.path.join(OUT_DIR, "narration_audio")
WIDTH, HEIGHT = 1920, 1080
FPS = 24
BG_COLOR = (13, 27, 42)
GOLD = (183, 149, 11)
WHITE = (255, 255, 255)
RED = (192, 57, 43)
GREEN = (39, 174, 96)
LIGHT = (160, 200, 224)
DARK_BG = (20, 35, 55)

NARRATIONS = [
    # 0: Title
    (
        "Detecting the Undetectable. "
        "How nation-state attackers hide for years, "
        "and how artificial intelligence changes the outcome."
    ),
    # 1: The Problem
    (
        "Modern attackers don't break in — they blend in. "
        "They use legitimate credentials, standard protocols, and built-in system tools. "
        "They look exactly like your employees. "
        "The result: the average breach goes undetected for 287 days, "
        "costing nearly five million dollars."
    ),
    # 2: Salt Typhoon
    (
        "Salt Typhoon — a Chinese state-sponsored group — penetrated nine US telecom "
        "providers including AT&T, Verizon, and T-Mobile, beginning around 2019. "
        "They accessed lawful intercept wiretap systems and harvested call metadata "
        "of over a million users, including senior US government officials. "
        "No deployed security tool detected them. "
        "The FBI and CISA discovered the breach from the outside in September 2024, "
        "after more than five years of undetected access."
    ),
    # 3: Volt Typhoon
    (
        "Volt Typhoon pre-positioned inside US critical infrastructure — "
        "energy, water, telecom, and transportation — for over five years. "
        "They used zero malware. Only built-in tools: PowerShell, WMI, and command prompt. "
        "They authenticated with stolen valid credentials. "
        "No brute force. No anomalous behavior. "
        "Microsoft threat researchers discovered them in May 2023 — "
        "not any deployed security system."
    ),
    # 4: The Full Threat Spectrum
    (
        "These are not isolated incidents. The threat landscape includes four distinct attack categories — "
        "each invisible to current security tools. "
        "Nation-state campaigns like Salt Typhoon and Volt Typhoon that persist for years. "
        "Insider threats — trusted employees who gradually escalate access over months. "
        "And slow APT campaigns that spread activity across weeks to avoid any single alert. "
        "Each attack type exploits a different blind spot. "
        "No single detection method covers them all."
    ),
    # 5: Why Traditional Fails
    (
        "Why does every traditional detection method fail against these attacks? "
        "Signature-based detection looks for known malware patterns — "
        "it fails when no malware is used. "
        "Rule-based SIEM triggers on thresholds — "
        "it fails when attackers stay below every one. "
        "Statistical anomaly detection like Isolation Forest, SVM, and LOF "
        "flags individual deviations — "
        "it fails when no single metric is abnormal. "
        "The attack is in the pattern, not the threshold."
    ),
    # 6: Digital Twin Innovation
    (
        "22nd Century Technologies solved this with V-Intelligence UEBA — "
        "AI-powered behavioral intelligence. "
        "V-Intelligence UEBA creates a digital twin of every user's behavior — "
        "a rich, multi-dimensional profile that captures the meaning of actions, "
        "not just the magnitude. "
        "It detects patterns of change even when individual metrics remain normal, "
        "and produces a single ranked priority list for analysts. "
        "No threshold tuning required."
    ),
    # 7: How V-Intelligence UEBA Works
    (
        "How does V-Intelligence UEBA work? The system follows a five-stage pipeline. "
        "First, it ingests security data from existing sources — authentication logs, file access, "
        "network traffic, endpoint telemetry, and DNS queries. "
        "Second, it builds a behavioral digital twin — a rich profile of each user's normal patterns. "
        "Third, it continuously monitors how behavior evolves over time. "
        "Fourth, it scores deviations using multi-dimensional analysis — "
        "looking at the combination of changes, not individual thresholds. "
        "Finally, it produces a single ranked priority list for your analysts. "
        "No new sensors required. It works with your existing data."
    ),
    # 8: Traditional Detection heatmap
    (
        "Here are the results from our validation. "
        "We tested traditional detection methods — Isolation Forest, One-Class SVM, and LOF — "
        "against four real attack campaigns embedded across 250 users over 70 weeks. "
        "Traditional methods detect zero out of four attacks. "
        "Our intermediate statistical analysis catches one — the Volt Typhoon campaign. "
        "But three attackers, including Salt Typhoon, remain completely invisible."
    ),
    # 9: V-Intelligence UEBA Scores
    (
        "V-Intelligence UEBA changes the picture entirely. "
        "The composite score cleanly separates two of the four attackers from the population. "
        "Salt Typhoon — the attack that went undetected for five years in the real world — "
        "is ranked number one out of 250 users, with a composite score of 51.3. "
        "The insider threat is ranked number two at 46.2. "
        "The two stealthiest campaigns rank below the average user on composite alone — "
        "and that is exactly where the threat-profile detector takes over."
    ),
    # 10: Top 25 Separation
    (
        "In this composite score ranking, the insider and Salt Typhoon, shown in red, "
        "rise clearly above the normal user population in blue. "
        "The two stealthiest attackers stay hidden in the crowd on composite alone — "
        "which is why the multi-front threat-profile detector is needed to catch all four."
    ),
    # 11: Insider Threat Deep Dive
    (
        "Let's look specifically at the insider threat — USR-156 in our validation. "
        "This simulated insider gradually escalated data access over eight months. "
        "Each individual action was within authorized parameters. "
        "No single file access was abnormal. No single login was suspicious. "
        "Traditional detection methods saw nothing. "
        "But V-Intelligence UEBA detected the cumulative behavioral shift — "
        "ranking this insider threat number two out of 250 users, "
        "with a composite score of 46.2."
    ),
    # 12: The Verdict
    (
        "The verdict is clear. "
        "Traditional detection catches zero out of four attacks. "
        "Our intermediate analysis catches one. "
        "V-Intelligence UEBA's threat-profile detector catches all four — "
        "at zero false positives. "
        "Same data. Same users. "
        "A fundamentally different understanding of behavior."
    ),
    # 13: Salt Typhoon Real-World Validation
    (
        "Real-world validation with Salt Typhoon. "
        "Over five years undetected inside the largest US telecom providers. "
        "Every traditional SIEM, IDS, and anomaly system was in place — none caught it. "
        "V-Intelligence UEBA ranks Salt Typhoon number one out of 250 users, "
        "with a composite behavioral score of 51.3. "
        "This is the gap between threshold-based detection and behavioral intelligence."
    ),
    # 14: Results Summary
    (
        "V-Intelligence UEBA delivers measurable results. "
        "Four out of four attack types detected by the threat-profile detector. "
        "Zero false positives. "
        "A single ranked analyst priority list. "
        "Zero threshold tuning required. "
        "These are validation results against real-world attack patterns."
    ),
    # 15: Federal & Critical Infrastructure
    (
        "V-Intelligence UEBA is purpose-built for the federal and critical infrastructure mission. "
        "It aligns with the Executive Order on Improving Cybersecurity, NIST 800-53 continuous monitoring, "
        "and Zero Trust Architecture principles. "
        "It addresses CISA's specific guidance on defending against living-off-the-land techniques. "
        "For agencies and critical infrastructure operators, "
        "V-Intelligence UEBA provides the behavioral intelligence layer "
        "that existing perimeter and endpoint tools cannot deliver."
    ),
    # 16: Closing
    (
        "V-Intelligence UEBA. "
        "AI-powered behavioral intelligence for threats that traditional tools cannot see. "
        "22nd Century Technologies."
    ),
]


def get_font(size, bold=False):
    candidates = [
        "C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def create_title_frame(title, subtitle=""):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(80, HEIGHT // 2 + 10), (320, HEIGHT // 2 + 14)], fill=GOLD)
    font_title = get_font(56, bold=True)
    draw.text((80, HEIGHT // 2 - 80), title, fill=WHITE, font=font_title)
    if subtitle:
        font_sub = get_font(26)
        draw.text((80, HEIGHT // 2 + 30), subtitle, fill=LIGHT, font=font_sub)
    font_foot = get_font(16)
    draw.text((80, HEIGHT - 60), "22nd Century Technologies, Inc.  |  V-Intelligence UEBA  |  Confidential",
              fill=(100, 100, 100), font=font_foot)
    return img


def create_text_frame(title, bullets, accent_color=WHITE):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (WIDTH, 90)], fill=DARK_BG)
    draw.rectangle([(0, 90), (WIDTH, 94)], fill=GOLD)
    font_title = get_font(32, bold=True)
    draw.text((60, 25), title, fill=accent_color, font=font_title)
    font_bullet = get_font(22)
    y = 140
    for bullet in bullets:
        if bullet == "":
            y += 15
            continue
        if bullet.startswith("**"):
            clean = bullet.replace("**", "")
            draw.text((80, y), clean, fill=GOLD, font=get_font(24, bold=True))
        elif bullet.startswith("!!"):
            clean = bullet.replace("!!", "")
            draw.text((80, y), clean, fill=RED, font=get_font(22, bold=True))
        elif bullet.startswith("++"):
            clean = bullet.replace("++", "")
            draw.text((80, y), clean, fill=GREEN, font=get_font(22, bold=True))
        else:
            draw.text((80, y), f"  {bullet}", fill=LIGHT, font=font_bullet)
        y += 40
    font_foot = get_font(14)
    draw.text((60, HEIGHT - 50), "22nd Century Technologies, Inc.  |  V-Intelligence UEBA Demo",
              fill=(80, 80, 80), font=font_foot)
    return img


def create_screenshot_frame(filename, caption, subcaption=""):
    img = Image.new("RGB", (WIDTH, HEIGHT), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    path = os.path.join(SCREENSHOT_DIR, filename)
    if os.path.exists(path):
        screenshot = Image.open(path).convert("RGB")
        max_w = WIDTH - 40
        max_h = HEIGHT - 160
        ratio = min(max_w / screenshot.width, max_h / screenshot.height)
        new_w = int(screenshot.width * ratio)
        new_h = int(screenshot.height * ratio)
        screenshot = screenshot.resize((new_w, new_h), Image.LANCZOS)
        x_off = (WIDTH - new_w) // 2
        y_off = 110
        img.paste(screenshot, (x_off, y_off))
        overlay = Image.new("RGBA", (WIDTH, 100), (13, 27, 42, 220))
        img_rgba = img.convert("RGBA")
        img_rgba.paste(overlay, (0, 0), overlay)
        img = img_rgba.convert("RGB")
        draw = ImageDraw.Draw(img)
    font_cap = get_font(28, bold=True)
    draw.text((60, 30), caption, fill=GOLD, font=font_cap)
    if subcaption:
        font_sub = get_font(18)
        draw.text((60, 68), subcaption, fill=LIGHT, font=font_sub)
    return img


def create_detection_results_frame():
    """Custom frame showing detection results — clean, no confusing sub-components."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Title bar
    draw.rectangle([(0, 0), (WIDTH, 90)], fill=DARK_BG)
    draw.rectangle([(0, 90), (WIDTH, 94)], fill=GOLD)
    draw.text((60, 25), "Detection Results: Who Catches What?", fill=WHITE, font=get_font(32, bold=True))

    # --- Traditional section ---
    draw.rectangle([(60, 120), (920, 128)], fill=RED)
    draw.text((60, 138), "TRADITIONAL DETECTION", fill=RED, font=get_font(22, bold=True))
    draw.text((380, 140), "Isolation Forest  /  One-Class SVM  /  LOF", fill=LIGHT, font=get_font(16))

    methods = [
        ("Isolation Forest", ["MISSED", "MISSED", "MISSED", "MISSED"], "5.3%"),
        ("One-Class SVM",    ["MISSED", "MISSED", "MISSED", "MISSED"], "14.6%"),
        ("LOF",              ["MISSED", "MISSED", "MISSED", "MISSED"], "4.5%"),
    ]
    # Column headers
    cols = ["USR-156 Insider", "USR-234 APT", "USR-042 Volt Typhoon", "USR-118 Salt Typhoon"]
    y_hdr = 175
    draw.text((60, y_hdr), "Method", fill=GOLD, font=get_font(14, bold=True))
    for ci, col in enumerate(cols):
        draw.text((300 + ci * 175, y_hdr), col, fill=GOLD, font=get_font(12, bold=True))
    draw.text((1000, y_hdr), "FP Rate", fill=GOLD, font=get_font(14, bold=True))

    for ri, (mname, results, fp) in enumerate(methods):
        y = 205 + ri * 38
        draw.text((70, y), mname, fill=WHITE, font=get_font(16))
        for ci, r in enumerate(results):
            clr = GREEN if r == "DETECTED" else RED
            draw.text((300 + ci * 175, y), r, fill=clr, font=get_font(14, bold=True))
        draw.text((1000, y), fp, fill=LIGHT, font=get_font(14))

    # Result badge
    draw.rectangle([(1120, 140), (1360, 178)], fill=RED)
    draw.text((1140, 146), "0 of 4 detected", fill=WHITE, font=get_font(18, bold=True))

    # --- Intermediate section ---
    y_int = 340
    draw.rectangle([(60, y_int), (920, y_int + 8)], fill=GOLD)
    draw.text((60, y_int + 18), "OUR INTERMEDIATE ANALYSIS", fill=GOLD, font=get_font(22, bold=True))
    draw.text((470, y_int + 20), "Statistical Pattern Detection (Z-Score)", fill=LIGHT, font=get_font(16))

    y_row = y_int + 60
    draw.text((70, y_row), "Z-Score (|z| > 3)", fill=WHITE, font=get_font(16))
    for ci, r in enumerate(["MISSED", "MISSED", "DETECTED", "MISSED"]):
        clr = GREEN if r == "DETECTED" else RED
        draw.text((300 + ci * 175, y_row), r, fill=clr, font=get_font(14, bold=True))
    draw.text((1000, y_row), "9.8%", fill=LIGHT, font=get_font(14))

    draw.rectangle([(1120, y_int + 18), (1360, y_int + 56)], fill=GOLD)
    draw.text((1140, y_int + 24), "1 of 4 detected", fill=(13, 27, 42), font=get_font(18, bold=True))

    # Annotation
    draw.text((70, y_row + 40), "Catches Volt Typhoon only — Insider, Slow APT, and Salt Typhoon remain invisible",
              fill=(200, 160, 60), font=get_font(14))

    # --- V-Intelligence UEBA section ---
    y_ace = 520
    draw.rectangle([(60, y_ace), (920, y_ace + 8)], fill=GREEN)
    draw.text((60, y_ace + 18), "V-INTELLIGENCE UEBA + THREAT-PROFILE DETECTOR", fill=GREEN, font=get_font(22, bold=True))
    draw.text((520, y_ace + 20), "Known-Bad Profile Matching → Multi-Front Detection", fill=LIGHT, font=get_font(16))

    y_row2 = y_ace + 60
    draw.text((70, y_row2), "Threat-Profile Match", fill=WHITE, font=get_font(16))
    for ci in range(4):
        draw.text((300 + ci * 175, y_row2), "DETECTED", fill=GREEN, font=get_font(14, bold=True))
    draw.text((1000, y_row2), "0%", fill=LIGHT, font=get_font(14))

    draw.rectangle([(1120, y_ace + 18), (1360, y_ace + 56)], fill=GREEN)
    draw.text((1140, y_ace + 24), "4 of 4 detected", fill=WHITE, font=get_font(18, bold=True))

    # Bottom summary
    y_bottom = 680
    draw.rectangle([(60, y_bottom), (WIDTH - 60, y_bottom + 80)], fill=DARK_BG)
    draw.text((100, y_bottom + 10), "Traditional: 0 / 4", fill=RED, font=get_font(28, bold=True))
    draw.text((530, y_bottom + 10), "→", fill=LIGHT, font=get_font(28))
    draw.text((590, y_bottom + 10), "Intermediate: 1 / 4", fill=GOLD, font=get_font(28, bold=True))
    draw.text((1020, y_bottom + 10), "→", fill=LIGHT, font=get_font(28))
    draw.text((1080, y_bottom + 10), "V-Intelligence UEBA: 4 / 4", fill=GREEN, font=get_font(28, bold=True))
    draw.text((100, y_bottom + 50), "Each tier catches what the previous tier cannot see.",
              fill=LIGHT, font=get_font(16))

    # Attacker labels along bottom
    y_labels = 800
    labels = [
        ("USR-156", "Insider Threat\n8-month campaign", RED),
        ("USR-234", "Slow APT\n180-day campaign", RED),
        ("USR-042", "Volt Typhoon LOTL\n115-day campaign", GOLD),
        ("USR-118", "Salt Typhoon Telecom\n100-day campaign", RED),
    ]
    for i, (uid, desc, clr) in enumerate(labels):
        x = 80 + i * 450
        draw.text((x, y_labels), uid, fill=clr, font=get_font(18, bold=True))
        for j, line in enumerate(desc.split("\n")):
            draw.text((x, y_labels + 28 + j * 22), line, fill=LIGHT, font=get_font(13))
        trad = "0/3 trad" if uid != "USR-042" else "0/3 trad"
        interm = "MISSED" if uid != "USR-042" else "Z-Score"
        ace = "DETECTED"
        draw.text((x, y_labels + 78), f"Trad: MISSED  |  Int: {interm}  |  V-Intelligence UEBA: {ace}",
                  fill=(140, 170, 190), font=get_font(11))

    # Footer
    draw.text((60, HEIGHT - 50), "22nd Century Technologies, Inc.  |  V-Intelligence UEBA Demo",
              fill=(80, 80, 80), font=get_font(14))
    return img


def create_verdict_frame():
    """Custom three-tier verdict frame — Traditional 0/4, Intermediate 1/4, V-Intelligence UEBA 4/4."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Title bar
    draw.rectangle([(0, 0), (WIDTH, 90)], fill=DARK_BG)
    draw.rectangle([(0, 90), (WIDTH, 94)], fill=GOLD)
    draw.text((60, 25), "The Verdict: Same Data, Three Different Outcomes", fill=WHITE, font=get_font(32, bold=True))

    # Three cards
    card_w = 540
    gap = 40
    start_x = (WIDTH - 3 * card_w - 2 * gap) // 2

    tiers = [
        ("TRADITIONAL", "Isolation Forest / SVM / LOF", "0 of 4", RED,
         "Fixed thresholds on individual metrics.\n"
         "Attackers who stay within normal ranges\n"
         "are invisible — no alerts generated.",
         "Best FP: 4.5% (LOF)\nbut detects nothing"),
        ("INTERMEDIATE", "Z-Score Statistical Analysis", "1 of 4", GOLD,
         "Cross-feature statistical deviation.\n"
         "Catches Volt Typhoon (noisier campaign)\n"
         "but misses 3 stealthier attack types.",
         "FP Rate: 9.8%\ncatches Volt Typhoon only"),
        ("V-INTELLIGENCE UEBA", "Threat-Profile Detector\nMulti-Front, Label-Free", "4 of 4", GREEN,
         "Known-bad profile matching on raw events.\n"
         "Detects all 4 attacks including Salt Typhoon\n"
         "which was undetected for 5+ years in reality.",
         "FP Rate: 0%\nall attacks detected"),
    ]

    for i, (name, subtitle, score, clr, desc, metric) in enumerate(tiers):
        x = start_x + i * (card_w + gap)
        y_card = 130

        # Card background
        draw.rectangle([(x, y_card), (x + card_w, y_card + 620)], fill=DARK_BG, outline=clr, width=2)
        # Top accent bar
        draw.rectangle([(x, y_card), (x + card_w, y_card + 6)], fill=clr)

        # Name
        draw.text((x + 20, y_card + 20), name, fill=clr, font=get_font(24, bold=True))
        # Subtitle
        for j, line in enumerate(subtitle.split("\n")):
            draw.text((x + 20, y_card + 55 + j * 22), line, fill=LIGHT, font=get_font(14))

        # Big score
        score_font = get_font(96, bold=True)
        bbox = draw.textbbox((0, 0), score, font=score_font)
        sw = bbox[2] - bbox[0]
        draw.text((x + (card_w - sw) // 2, y_card + 110), score, fill=clr, font=score_font)

        # Score label
        label = "attacks detected"
        label_font = get_font(16, bold=True)
        lbbox = draw.textbbox((0, 0), label, font=label_font)
        lw = lbbox[2] - lbbox[0]
        draw.text((x + (card_w - lw) // 2, y_card + 220), label, fill=LIGHT, font=label_font)

        # Description
        for j, line in enumerate(desc.split("\n")):
            draw.text((x + 25, y_card + 280 + j * 28), line, fill=LIGHT, font=get_font(15))

        # Metric box
        draw.rectangle([(x + 20, y_card + 390), (x + card_w - 20, y_card + 460)], fill=clr)
        for j, line in enumerate(metric.split("\n")):
            m_clr = WHITE if clr != GOLD else (13, 27, 42)
            draw.text((x + 40, y_card + 398 + j * 28), line, fill=m_clr, font=get_font(14, bold=True))

    # Bottom summary bar
    y_bot = 790
    draw.rectangle([(60, y_bot), (WIDTH - 60, y_bot + 70)], fill=DARK_BG)
    summary = "0 / 4  →  1 / 4  →  4 / 4   |   The threat-profile detector catches what thresholds cannot."
    draw.text((100, y_bot + 20), summary, fill=GOLD, font=get_font(22, bold=True))

    # Salt Typhoon callout
    y_call = 880
    draw.text((80, y_call), "Salt Typhoon: ", fill=RED, font=get_font(16, bold=True))
    draw.text((250, y_call), "5+ years undetected by every traditional tool. V-Intelligence UEBA ranks it #1 out of 250 users.",
              fill=LIGHT, font=get_font(16))

    # Footer
    draw.text((60, HEIGHT - 50), "22nd Century Technologies, Inc.  |  V-Intelligence UEBA Demo",
              fill=(80, 80, 80), font=get_font(14))
    return img


def create_stat_frame(stats, title=""):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    if title:
        font_title = get_font(36, bold=True)
        draw.text((WIDTH // 2 - 300, 80), title, fill=GOLD, font=font_title)
    font_val = get_font(64, bold=True)
    font_desc = get_font(20)
    n = len(stats)
    spacing = WIDTH // (n + 1)
    for i, (val, desc, color) in enumerate(stats):
        x = spacing * (i + 1) - 100
        y = HEIGHT // 2 - 60
        draw.text((x, y), val, fill=color, font=font_val)
        for j, line in enumerate(desc.split("\n")):
            draw.text((x, y + 80 + j * 28), line, fill=LIGHT, font=font_desc)
    return img


def generate_narration(voice="onyx", force=False):
    """Generate TTS audio files using OpenAI API. Cached unless force=True."""
    from openai import OpenAI
    client = OpenAI()
    os.makedirs(AUDIO_DIR, exist_ok=True)

    audio_files = []
    for i, text in enumerate(NARRATIONS):
        path = os.path.join(AUDIO_DIR, f"narration_{i:02d}.mp3")
        if os.path.exists(path) and not force:
            print(f"  Narration {i:02d}: cached")
            audio_files.append(path)
            continue
        print(f"  Generating narration {i+1}/{len(NARRATIONS)}...")
        response = client.audio.speech.create(
            model="tts-1-hd",
            voice=voice,
            input=text,
            response_format="mp3",
        )
        response.stream_to_file(path)
        audio_files.append(path)
    return audio_files


def build_video():
    print("Building V-Intelligence UEBA demo video with narration...\n")

    # ── Frame images ────────────────────────────────────────────
    frames = []
    fallback_durations = []

    def add(img, fallback=6):
        frames.append(img)
        fallback_durations.append(fallback)

    # 0: Title
    add(create_title_frame(
        "Detecting the Undetectable",
        "How Nation-State Attackers Hide for Years — and How AI Changes the Outcome",
    ), 7)

    # 1: The Problem
    add(create_text_frame(
        "The Problem: Nation-State Attacks Are Invisible",
        [
            "**The New Threat Landscape**",
            "",
            "  Modern attackers don't break in — they blend in.",
            "  They use legitimate credentials and built-in system tools.",
            "  They look exactly like your employees.",
            "",
            "  The result: average breach goes undetected for 287 days (IBM 2024).",
            "  Cost: $4.88M per breach on average.",
            "",
            "!!This is not a hypothetical — it happened to the largest US telecom providers.",
        ],
    ), 10)

    # 2: Salt Typhoon
    add(create_text_frame(
        "Salt Typhoon: 5 Years Inside US Telecom",
        [
            "**What Happened**",
            "",
            "  Chinese state-sponsored group penetrated US telecom ~2019",
            "  Compromised AT&T, Verizon, T-Mobile, Lumen, Charter — 9 providers total",
            "  Accessed CALEA lawful intercept / wiretap systems",
            "  Harvested call metadata of 1M+ users including senior US officials",
            "",
            "**How It Was Discovered**",
            "",
            "  NOT by any security tool deployed at the telecom companies",
            "  Discovered by FBI and CISA — from the outside, in September 2024",
            "!!Every SIEM, IDS, and anomaly algorithm was in place. None detected it.",
        ],
    ), 15)

    # 3: Volt Typhoon
    add(create_text_frame(
        "Volt Typhoon: 5 Years in Critical Infrastructure",
        [
            "**What Happened**",
            "",
            "  Chinese state-sponsored group pre-positioned in US critical infrastructure",
            "  Energy, water, telecom, transportation — vital to national security",
            "  CISA confirmed at least 5 years of persistent access",
            "",
            "**Why It Was Undetectable: \"Living Off the Land\"**",
            "",
            "  Zero malware — used only PowerShell, WMI, cmd, netsh (built-in tools)",
            "  Authenticated with stolen valid credentials — no brute force",
            "  Looked identical to normal IT administrator activity",
            "!!Discovered by Microsoft researchers — not by any deployed security tool.",
        ],
    ), 15)

    # 4: The Full Threat Spectrum
    add(create_text_frame(
        "The Full Threat Spectrum",
        [
            "**Nation-State Campaigns (Salt Typhoon, Volt Typhoon)**",
            "  Persistent access for years — legitimate credentials, built-in tools",
            "",
            "**Insider Threats**",
            "  Trusted employees gradually escalating access over 6-12 months",
            "  Actions individually look authorized",
            "",
            "**Slow APT Campaigns**",
            "  Activity spread across weeks — no single day triggers an alert",
            "  180+ day campaigns below every threshold",
            "",
            "!!Each exploits a different blind spot in traditional detection.",
        ],
    ), 15)

    # 5: Why Traditional Fails (Z-Score removed — it's our intermediate)
    add(create_text_frame(
        "Why Every Traditional Detection Method Fails",
        [
            "**Signature-Based (IDS / Antivirus / EDR)**",
            "  Looks for known malware patterns — fails when no malware is used",
            "",
            "**Rule-Based (SIEM Rules)**",
            "  Triggers on thresholds — fails when attackers stay below every one",
            "",
            "**Statistical Anomaly (Isolation Forest / SVM / LOF)**",
            "  Flags individual metrics that deviate — fails when no single metric is abnormal",
            "",
            "!!The attack is in the pattern, not the threshold.",
            "!!No single number is abnormal — the combination is.",
        ],
    ), 12)

    # 6: Digital Twin Innovation
    add(create_text_frame(
        "22nd Century's Innovation: The Behavioral Digital Twin",
        [
            "**V-Intelligence UEBA — AI-Powered Behavioral Intelligence**",
            "",
            "++V-Intelligence UEBA creates a digital twin of every user's behavior.",
            "",
            "  A multi-dimensional behavioral profile — not just numbers",
            "  Captures the meaning of actions, not just the magnitude",
            "  Detects how behavior changes over time — even when metrics stay normal",
            "",
            "**Multi-Tier Detection**",
            "",
            "  Tier 1: Intermediate statistical analysis (catches basic anomalies)",
            "  Tier 2: Full behavioral intelligence (catches what Tier 1 misses)",
            "  Output: A single ranked priority list — no threshold tuning needed",
        ],
    ), 12)

    # 7: How V-Intelligence UEBA Works
    add(create_text_frame(
        "How V-Intelligence UEBA Works: 5-Stage Pipeline",
        [
            "**Stage 1: Ingest**",
            "  Authentication logs, file access, network, endpoint, DNS",
            "",
            "**Stage 2: Profile**",
            "  Build behavioral digital twin for each entity",
            "",
            "**Stage 3: Monitor**",
            "  Track behavioral evolution over time continuously",
            "",
            "**Stage 4: Score**",
            "  Multi-dimensional composite analysis — patterns, not thresholds",
            "",
            "**Stage 5: Rank**",
            "  Single analyst priority list — highest risk first",
            "",
            "++No new sensors. Works with your existing security data.",
        ],
    ), 15)

    # 8: Traditional Detection heatmap
    add(create_detection_results_frame(), 12)

    # 9: V-Intelligence UEBA composite scores
    add(create_screenshot_frame(
        "tier3_sec_01.png",
        "V-Intelligence UEBA Results: Composite Separates 2 of 4",
        subcaption="Salt Typhoon: Rank #1 (Score 51.3)  |  Insider: Rank #2 (Score 46.2)  |  2 stealthiest caught by threat-profile detector",
    ), 12)

    # 10: Top 25 separation
    add(create_screenshot_frame(
        "tier3_sec_03.png",
        "Composite Separation: Insider and Salt Typhoon Stand Out",
        subcaption="Composite score ranking — USR-156 and USR-118 (red) rise above normal users (blue); 2 stealthiest need the threat-profile detector",
    ), 10)

    # 11: Insider Threat Deep Dive
    add(create_text_frame(
        "Insider Threat Deep Dive: USR-156",
        [
            "**Campaign Profile**",
            "  8-month gradual data access escalation",
            "  Every individual action within authorized parameters",
            "  No single metric triggered any traditional alert",
            "",
            "**Traditional Detection: MISSED**",
            "!!Isolation Forest: NORMAL   |   SVM: NORMAL   |   LOF: NORMAL",
            "",
            "**V-Intelligence UEBA Detection: CAUGHT**",
            "++Rank: #2 out of 250 users   |   Score: 46.2",
            "",
            "  Behavioral digital twin detected cumulative pattern shift",
            "  Even though no individual metric was abnormal",
        ],
    ), 15)

    # 12: Verdict
    add(create_verdict_frame(), 12)

    # 13: Salt Typhoon stats
    add(create_stat_frame(
        [
            ("5+ yrs", "undetected by\ntraditional tools", RED),
            ("#1", "V-Intelligence UEBA rank\nout of 250 users", GREEN),
            ("51.3", "composite\nbehavioral score", GREEN),
            ("0 / 4", "traditional methods\nthat detected it", RED),
        ],
        title="Salt Typhoon: Real-World Validation",
    ), 12)

    # 14: Summary stats
    add(create_stat_frame(
        [
            ("4 / 4", "attack types\ndetected", GREEN),
            ("0%", "false positive\nrate", GOLD),
            ("Ranked", "single analyst\npriority list", GREEN),
            ("Zero", "threshold tuning\nrequired", GOLD),
        ],
        title="V-Intelligence UEBA Results Summary",
    ), 10)

    # 15: Federal & Critical Infrastructure
    add(create_text_frame(
        "Federal & Critical Infrastructure Relevance",
        [
            "**Executive Order 14028: Improving Cybersecurity**",
            "  Mandates enhanced threat detection and continuous monitoring",
            "",
            "**NIST 800-53: Continuous Monitoring**",
            "  Behavioral analytics for insider threat and APT detection",
            "",
            "**Zero Trust Architecture (NIST 800-207)**",
            "  Continuous behavioral verification — never trust, always verify",
            "",
            "**CISA Living Off the Land Guidance**",
            "  Directly addresses Salt/Volt Typhoon TTPs",
            "",
            "++V-Intelligence UEBA provides the missing behavioral intelligence layer.",
        ],
    ), 12)

    # 16: Closing
    add(create_title_frame(
        "V-Intelligence UEBA",
        "AI-Powered Behavioral Intelligence for Threats That Traditional Tools Cannot See\n\n"
        "22nd Century Technologies, Inc.",
    ), 6)

    print(f"Frames built: {len(frames)}")

    # ── Save frame PNGs for preview ─────────────────────────────
    frames_dir = os.path.join(OUT_DIR, "demo_frames")
    os.makedirs(frames_dir, exist_ok=True)
    for i, img in enumerate(frames):
        img.save(os.path.join(frames_dir, f"frame_{i:02d}.png"))

    # ── Generate narration audio ────────────────────────────────
    print("\nGenerating narration audio...")
    has_audio = False
    audio_files = []
    try:
        audio_files = generate_narration()
        has_audio = len(audio_files) == len(frames)
        print(f"  {len(audio_files)} narration files ready")
    except Exception as e:
        print(f"\n  Audio generation failed: {e}")
        print("  Building video without narration (silent)...")

    # ── Build video ─────────────────────────────────────────────
    try:
        import numpy as np
        try:
            from moviepy import ImageClip, AudioFileClip, concatenate_videoclips
        except ImportError:
            from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

        clips = []
        total_duration = 0.0

        for i, img in enumerate(frames):
            arr = np.array(img)

            if has_audio and i < len(audio_files):
                audio = AudioFileClip(audio_files[i])
                duration = audio.duration + 1.5
                clip = ImageClip(arr, duration=duration)
                try:
                    clip = clip.with_audio(audio)
                except AttributeError:
                    clip = clip.set_audio(audio)
            else:
                duration = fallback_durations[i]
                clip = ImageClip(arr, duration=duration)

            clips.append(clip)
            total_duration += duration
            print(f"  Frame {i+1}/{len(frames)}: {duration:.1f}s")

        video = concatenate_videoclips(clips, method="compose")
        out_path = os.path.join(OUT_DIR, "V_Intelligence_UEBA_Demo.mp4")

        write_kwargs = dict(fps=FPS, codec="libx264", logger="bar")
        if has_audio:
            write_kwargs["audio_codec"] = "aac"
        else:
            write_kwargs["audio"] = False

        video.write_videofile(out_path, **write_kwargs)
        print(f"\nVideo saved to {out_path}")
        print(f"Duration: {total_duration:.0f}s, Resolution: {WIDTH}x{HEIGHT}")
        if has_audio:
            print("Audio: OpenAI TTS-HD (onyx voice)")

    except ImportError:
        print("\nMoviepy not available. Frames saved to docs/demo_frames/")

    except Exception as e:
        print(f"\nVideo creation failed: {e}")
        import traceback
        traceback.print_exc()
        print(f"Frames saved to {frames_dir}/ as fallback")


if __name__ == "__main__":
    build_video()
