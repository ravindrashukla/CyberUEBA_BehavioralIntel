#!/usr/bin/env python3
"""V-Intelligence UEBA demo video — LAYERED approach (v2).

Reuses the frame builders from build_demo_video.py and defines the new 17-scene
layered sequence + narration (docs/demo_video_script_layered.md).

Usage:
  python docs/build_demo_video_v2.py --frames-only     # step 2: render frames for review
  python docs/build_demo_video_v2.py --render --voice nova   # step 3: TTS + full MP4
"""
import sys, os, argparse, hashlib
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_demo_video import (
    create_title_frame, create_text_frame, create_screenshot_frame,
    create_detection_results_frame, create_verdict_frame, create_stat_frame,
    WIDTH, HEIGHT, FPS, OUT_DIR, RED, GREEN, GOLD,
)

FRAMES_DIR = os.path.join(OUT_DIR, "demo_frames_v2")
AUDIO_DIR = os.path.join(OUT_DIR, "narration_audio_v2")
OUT_MP4 = os.path.join(OUT_DIR, "V_Intelligence_UEBA_Demo_Layered.mp4")

# Narration text (step 3 TTS). Index aligns with build_frames() scene order.
NARRATIONS = [
    # 0 Title
    "Detecting the undetectable. How nation-state attackers hide for years — and how a layered behavioral approach changes the outcome.",
    # 1 Problem
    "Modern attackers don't break in — they blend in. They use legitimate credentials, standard protocols, and built-in system tools. They look exactly like your employees. The result: the average breach goes undetected for 287 days, costing nearly five million dollars.",
    # 2 Salt Typhoon
    "Salt Typhoon — a Chinese state-sponsored group — penetrated nine US telecom providers including AT&T, Verizon, and T-Mobile, beginning around 2019. They accessed lawful-intercept wiretap systems and harvested call metadata of over a million users, including senior US officials. No deployed tool detected them. The FBI and CISA found it from the outside in September 2024 — after more than five years.",
    # 3 Volt Typhoon
    "Volt Typhoon pre-positioned inside US critical infrastructure — energy, water, telecom, transportation — for over five years. Zero malware; only built-in tools like PowerShell and WMI. They authenticated with stolen valid credentials. No brute force, no anomalous behavior. Microsoft researchers found them in 2023 — not any deployed security system.",
    # 4 Four blind spots
    "These are not isolated incidents. Four distinct attack types each exploit a different blind spot: nation-state campaigns that persist for years, insiders who quietly escalate over months, living-off-the-land intrusions that use only trusted tools, and slow campaigns spread across weeks to stay under every alert. No single method covers them all.",
    # 5 Why one method can't win
    "Why does every single method fail? Signature detection looks for malware — there is none. Rule-based SIEM triggers on thresholds — the attacker stays below every one. Statistical anomaly tools flag individual outliers — no single metric is abnormal. Every one of these asks the same question: is this one number, right now, past a line? The stealth attacker keeps every number normal. The signal is never in one metric — it's in the accumulation, the combination, and the direction of change.",
    # 6 The innovation: a layered approach
    "Our innovation isn't a single trick — it's how we combine the evidence and apply it in layers. A traditional tool judges one signal, at one moment, against a fixed line. We measure magnitude and direction — how far a behavior moves, and what kind of change it is — accumulated over time and weighed against a user's peers, then fused in layers so each layer catches what the last one missed. Cheap, fast signals catch the loud attacks early. An AI lens that reads the meaning of behavior catches the subtle ones. A fused score ranks the rest. And a set of known-bad profiles flags adversary techniques with zero noise. No commercial tool combines all of this. Same data — read in layers.",
    # 7 Layer 1 baseline
    "Layer one is what most agencies run today: point-anomaly tools that score each user against a threshold. On four real campaigns embedded across 250 users over 70 weeks, these tools — Isolation Forest, One-Class SVM, and LOF — detect zero of four. A simple z-score catches one, the living-off-the-land case — but alarms on nearly everyone. Three attackers, including Salt Typhoon, stay invisible.",
    # 8 Layer 2 behavioral entities
    "Layer two reads the same logs as living behavioral entities, tracked over time. On any given week the attacker still looks normal — the stealth APT sits inside the normal range 97 percent of the time. But behavior accumulates. Watch the same small drift add up week after week, and the slow movers separate from the crowd.",
    # 9 Signal separation
    "Two lenses make this concrete. A raw-magnitude lens measures how far each user moves from their own past — it flags the noisy, high-volume attack first, even before the AI. A semantic lens measures how far behavior drifts in meaning — it flags the subtle insider and stealth hacker roughly 30 weeks earlier. Each lens has a blind spot, and the slow APT crosses neither on drift alone — which is exactly why the next layers matter.",
    # 10 USR-234 hard case (NEW)
    "Zoom in on the hardest case — the slow APT. On the raw-magnitude lens, and on the AI semantic lens, its cumulative drift never separates from the normal pack. It looks like an ordinary user on both. Drift alone will never catch it — and that is exactly the gap the next layers close.",
    # 11 Layer 3 radar
    "Layer three asks five behavioral questions at once — signal strength, breadth, how long the change persisted, how far it diverged from the user's peers, and whether new connections keep recurring. Normal users cluster in a tight shape at the center. Each attacker pushes far past them on a different phase. No normal user is extreme on every front at once — and that is the fingerprint.",
    # 12 Layer 4 composite
    "Layer four fuses those five phases into a single ranked score. Now all four campaigns rise above the line that catches all four — including the two stealth movers that hid in the crowd a moment ago. The cost: catching all four this way flags about 8 percent of normal users for review.",
    # 13 Layer 5 known-bad profiles
    "Layer five removes that noise. Instead of asking only how far a user has drifted, it asks whether their behavior matches a measurable known-bad profile — a beacon's robotic timing, an algorithmically generated domain, a destination no peer ever contacts. On the same data, this layer flags all four campaigns at zero false positives — each alert named by the technique that fired.",
    # 14 Verdict
    "The verdict, layer by layer. Traditional tools: zero of four. Intermediate statistics: one of four. The fused behavioral score: four of four. The known-bad profiles: four of four — at zero false positives. Same data. Same users. A fundamentally different understanding of behavior.",
    # 15 Results summary
    "V-Intelligence delivers measurable results. Four of four campaigns detected. Zero false positives on the profile match. A single ranked priority list. No threshold tuning. And every alert explainable, mapped to MITRE ATT&CK.",
    # 16 Federal alignment
    "V-Intelligence is purpose-built for the federal and critical-infrastructure mission. It aligns with the Executive Order on Improving Cybersecurity, NIST continuous monitoring, and Zero Trust, and directly addresses CISA's guidance on living-off-the-land techniques — the behavioral intelligence layer perimeter and endpoint tools cannot deliver.",
    # 17 Closing
    "V-Intelligence. A layered behavioral approach to the threats traditional tools cannot see. 22nd Century Technologies.",
]


def build_frames():
    frames, durations = [], []

    def add(img, fallback=6):
        frames.append(img); durations.append(fallback)

    # 0 Title
    add(create_title_frame(
        "Detecting the Undetectable",
        "How Nation-State Attackers Hide for Years — and How a Layered Behavioral Approach Changes the Outcome",
    ), 8)

    # 1 Problem
    add(create_text_frame("The Problem: Attackers Don't Break In — They Blend In", [
        "**The New Threat Landscape**", "",
        "  Modern attackers use legitimate credentials and built-in system tools.",
        "  They look exactly like your employees.", "",
        "  Average breach goes undetected for 287 days (IBM 2024).",
        "  Cost: $4.88M per breach on average.", "",
        "!!It is not hypothetical — it happened to the largest US telecom providers.",
    ]), 11)

    # 2 Salt Typhoon
    add(create_text_frame("Salt Typhoon: 5 Years Inside US Telecom", [
        "**What Happened**", "",
        "  Chinese state-sponsored group penetrated US telecom ~2019",
        "  AT&T, Verizon, T-Mobile, Lumen, Charter — 9 providers total",
        "  Accessed CALEA lawful-intercept / wiretap systems",
        "  Harvested call metadata of 1M+ users including senior US officials", "",
        "!!Discovered by FBI and CISA from the outside, Sept 2024 — not by any deployed tool.",
    ]), 15)

    # 3 Volt Typhoon
    add(create_text_frame("Volt Typhoon: 5 Years in Critical Infrastructure", [
        "**What Happened**", "",
        "  Pre-positioned in US energy, water, telecom, transportation",
        "  CISA confirmed at least 5 years of persistent access", "",
        "**Why It Was Undetectable: \"Living Off the Land\"**", "",
        "  Zero malware — only PowerShell, WMI, cmd (built-in tools)",
        "  Stolen valid credentials — no brute force",
        "!!Discovered by Microsoft researchers — not by any deployed security tool.",
    ]), 15)

    # 4 Four blind spots
    add(create_text_frame("Four Attack Types — Four Different Blind Spots", [
        "**Nation-State Campaigns (Salt / Volt Typhoon)** — persist for years on legitimate access",
        "**Insider Threats** — trusted employees escalate gradually over months",
        "**Living off the Land** — only trusted, built-in tools; no malware",
        "**Slow APT** — activity spread across weeks; no single day triggers an alert", "",
        "!!Each exploits a different blind spot. No single method covers them all.",
    ]), 14)

    # 5 Why one method can't win
    add(create_text_frame("Why Every Single Method Fails", [
        "**Signature-Based (IDS / AV / EDR)** — looks for known malware. None is used.",
        "**Rule-Based SIEM** — triggers on thresholds. The attacker stays below every one.",
        "**Statistical Anomaly (Isolation Forest / SVM / LOF)** — flags single outliers. No metric is abnormal.", "",
        "!!Every one asks the same question: is this ONE number, right now, past a line?",
        "!!The stealth attacker keeps every number normal.", "",
        "++The signal is in the accumulation, the combination, and the direction of change.",
    ]), 13)

    # 6 The innovation: layered approach
    add(create_text_frame("The Innovation: A Layered Behavioral Approach", [
        "++We measure magnitude AND direction — accumulated over time, weighed against peers.",
        "++Applied in layers, so each layer catches what the last one missed.", "",
        "**Layer 1** — Point-anomaly baseline (what most tools do today)",
        "**Layer 2** — Behavioral entities: drift accumulates the slow signal",
        "**Layer 3** — Multi-phase fingerprint vs. the user's peers",
        "**Layer 4** — Fused composite score: one ranked verdict",
        "**Layer 5** — Known-bad profiles: named adversary techniques, zero noise", "",
        "!!No commercial tool combines all of this.",
    ]), 14)

    # 7 Layer 1 baseline
    add(create_detection_results_frame(), 13)

    # 8 Layer 2 behavioral entities
    add(create_screenshot_frame("drift_layered.png",
        "Layer 2 — Behavioral Entities: Drift Accumulates the Slow Signal",
        subcaption="Per-week the attacker looks normal (USR-234 in-band 97% of weeks)  ·  cumulative drift reveals the slow movers"), 12)

    # 9 Signal separation
    add(create_screenshot_frame("signal_separation.png",
        "Signal Separation — Two Lenses, Different Attacks Caught First",
        subcaption="Raw magnitude flags the volume attack first  ·  the AI semantic lens flags subtle attacks ~30 weeks earlier  ·  the slow APT crosses neither"), 12)

    # 10 USR-234 hard case (NEW)
    add(create_screenshot_frame("usr234_escapes.png",
        "The Hard Case — The Slow APT Hides From Both Drift Lenses",
        subcaption="USR-234 never separates from the normal pack on raw-magnitude OR semantic drift — it needs the multi-front threat-profile detector"), 14)

    # 11 Layer 3 radar
    add(create_screenshot_frame("radar.png",
        "Layer 3 — Multi-Phase Fingerprint",
        subcaption="Normals cluster at the center; each attacker is extreme on a different phase. No normal user is extreme on every front at once."), 12)

    # 12 Layer 4 composite
    add(create_screenshot_frame("composite_rank.png",
        "Layer 4 — Fused Composite: All Four Above the Line",
        subcaption="All 4 campaigns rank above the catch-all-four line — at ~8% false positives. The two stealth movers surface from the crowd."), 12)

    # 13 Layer 5 known-bad profiles
    add(create_text_frame("Layer 5 — Known-Bad Profiles: 4 of 4 at Zero False Positives", [
        "**Instead of \"how far has it drifted?\"  →  \"does it match a known-bad profile?\"**", "",
        "  USR-156  Insider               →  Mass collection + cohort-rare destinations",
        "  USR-234  Slow APT              →  C2-beacon rhythm + DGA-DNS domains",
        "  USR-042  Volt Typhoon (LOTL)   →  Living-off-the-land process profile",
        "  USR-118  Salt Typhoon          →  Cohort-relative reconnaissance fan-out", "",
        "++4 of 4 caught at 0 false positives — each alert named by the technique that fired.",
    ]), 13)

    # 14 Verdict
    add(create_verdict_frame(), 12)

    # 15 Results summary
    add(create_stat_frame([
        ("4 / 4", "attack campaigns\ndetected", GREEN),
        ("0%", "false positives\non profile match", GOLD),
        ("Ranked", "single analyst\npriority list", GREEN),
        ("Zero", "threshold tuning\nrequired", GOLD),
    ], title="V-Intelligence UEBA — Results Summary"), 11)

    # 16 Federal alignment
    add(create_text_frame("Federal & Critical Infrastructure Relevance", [
        "**Executive Order 14028: Improving Cybersecurity** — enhanced detection & continuous monitoring",
        "**NIST 800-53: Continuous Monitoring** — behavioral analytics for insider & APT detection",
        "**Zero Trust (NIST 800-207)** — continuous behavioral verification",
        "**CISA Living off the Land Guidance** — directly addresses Salt / Volt Typhoon TTPs", "",
        "++V-Intelligence provides the missing behavioral intelligence layer.",
    ]), 12)

    # 17 Closing
    add(create_title_frame(
        "V-Intelligence UEBA",
        "A Layered Behavioral Approach to the Threats Traditional Tools Cannot See\n\n22nd Century Technologies, Inc.",
    ), 7)

    return frames, durations


def dump_frames():
    frames, _ = build_frames()
    os.makedirs(FRAMES_DIR, exist_ok=True)
    for i, im in enumerate(frames):
        im.save(os.path.join(FRAMES_DIR, f"frame_{i:02d}.png"))
    print(f"Saved {len(frames)} frames to {FRAMES_DIR}/")
    assert len(frames) == len(NARRATIONS), f"frame/narration mismatch: {len(frames)} vs {len(NARRATIONS)}"
    print("frame count matches narration count:", len(frames))


def generate_narration(voice="nova", force=False):
    """OpenAI TTS for each narration; cached as mp3 unless force=True."""
    from openai import OpenAI
    client = OpenAI()
    os.makedirs(AUDIO_DIR, exist_ok=True)
    files = []
    for i, text in enumerate(NARRATIONS):
        # Content-addressed cache: only changed/new narration text re-calls TTS.
        key = hashlib.md5(text.encode("utf-8")).hexdigest()[:10]
        path = os.path.join(AUDIO_DIR, f"n_{key}.mp3")
        if os.path.exists(path) and not force:
            print(f"  narration {i:02d}: cached"); files.append(path); continue
        print(f"  TTS {i + 1}/{len(NARRATIONS)} (voice={voice})...")
        resp = client.audio.speech.create(model="tts-1-hd", voice=voice, input=text, response_format="mp3")
        if hasattr(resp, "write_to_file"):
            resp.write_to_file(path)
        elif hasattr(resp, "stream_to_file"):
            resp.stream_to_file(path)
        else:
            with open(path, "wb") as f:
                f.write(resp.content)
        files.append(path)
    return files


def render(voice="nova"):
    import numpy as np
    try:
        from moviepy import ImageClip, AudioFileClip, concatenate_videoclips
    except ImportError:
        from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

    frames, durations = build_frames()
    os.makedirs(FRAMES_DIR, exist_ok=True)
    for i, im in enumerate(frames):
        im.save(os.path.join(FRAMES_DIR, f"frame_{i:02d}.png"))

    print(f"\nGenerating narration ({len(NARRATIONS)} clips)...")
    audio_files = generate_narration(voice=voice)
    has_audio = len(audio_files) == len(frames)

    clips, total = [], 0.0
    for i, im in enumerate(frames):
        arr = np.array(im)
        if has_audio:
            a = AudioFileClip(audio_files[i])
            dur = a.duration + 1.2
            clip = ImageClip(arr, duration=dur)
            try:
                clip = clip.with_audio(a)
            except AttributeError:
                clip = clip.set_audio(a)
        else:
            dur = durations[i]
            clip = ImageClip(arr, duration=dur)
        clips.append(clip); total += dur
        print(f"  frame {i + 1}/{len(frames)}: {dur:.1f}s")

    video = concatenate_videoclips(clips, method="compose")
    kw = dict(fps=FPS, codec="libx264", logger="bar")
    if has_audio:
        kw["audio_codec"] = "aac"
    else:
        kw["audio"] = False
    video.write_videofile(OUT_MP4, **kw)
    print(f"\nSaved {OUT_MP4}  ({total:.0f}s, {WIDTH}x{HEIGHT}, voice={voice})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-only", action="store_true", help="render frame PNGs only (no TTS/video)")
    ap.add_argument("--render", action="store_true", help="full TTS + MP4 (step 3)")
    ap.add_argument("--voice", default="nova")
    args = ap.parse_args()
    if args.render:
        render(voice=args.voice)
    else:
        dump_frames()


if __name__ == "__main__":
    main()
