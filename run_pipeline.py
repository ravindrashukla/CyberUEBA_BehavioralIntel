"""Run the full UEBA pipeline: embed → detect → alert → kill-chain.

Usage: python run_pipeline.py [--months N]
Requires OPENAI_API_KEY — real OpenAI embeddings are mandatory.
"""
import os
import sys
import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from embeddings.embedder import Embedder
from embeddings.composer import compose, drift_magnitude
from embeddings.signals import user_signals, device_signals
from detection.cusum import cusum_scan_entity, CUSUMResult
from detection.reference_concepts import ConceptLibrary
from detection.drift_direction import analyze_entity_drift
from detection.alert_generator import AlertGenerator
from detection.kill_chain import KillChainReconstructor


def load_logs_for_window(data_dir: Path, start: date, end: date) -> dict:
    """Load CSV logs for a date window into DataFrames."""
    logs = {}
    log_types = ["auth", "network", "dns", "endpoint", "file_access", "app", "privilege"]

    for log_type in log_types:
        log_dir = data_dir / log_type
        if not log_dir.exists():
            logs[log_type] = pd.DataFrame()
            continue

        frames = []
        current = start
        while current < end:
            csv_path = log_dir / f"{current.isoformat()}.csv"
            if csv_path.exists():
                frames.append(pd.read_csv(csv_path))
            current += timedelta(days=1)

        if frames:
            combined = pd.concat(frames, ignore_index=True)
            if "timestamp" in combined.columns:
                combined["timestamp"] = pd.to_datetime(combined["timestamp"])
            logs[log_type] = combined
        else:
            logs[log_type] = pd.DataFrame()

    return logs


def build_monthly_snapshots(data_dir: Path, embedder, months: list[tuple[date, date]]):
    """Build behavioral snapshots for users across multiple months."""
    from simulator.entities import generate_all

    entities = generate_all()
    users_df = entities["users"]
    user_ids = users_df["user_id"].tolist()[:50]  # Top 50 for speed

    all_snapshots = {}  # user_id -> list of composite vectors

    for month_start, month_end in months:
        print(f"  Loading logs for {month_start} to {month_end}...")
        logs = load_logs_for_window(data_dir, month_start, month_end)

        if logs["auth"].empty and logs["file_access"].empty:
            print(f"    No data available for this window, skipping")
            continue

        print(f"    Embedding {len(user_ids)} users...")
        for uid in user_ids:
            # Generate 5 behavioral signal texts
            signals = {
                "auth": user_signals.auth_signal(uid, logs, month_start, month_end),
                "privilege": user_signals.privilege_signal(uid, logs, month_start, month_end),
                "data_access": user_signals.data_access_signal(uid, logs, month_start, month_end),
                "network": user_signals.network_signal(uid, logs, month_start, month_end),
                "communication": user_signals.communication_signal(uid, logs, month_start, month_end),
            }

            # Embed each signal
            signal_vectors = {}
            for sig_name, text in signals.items():
                signal_vectors[sig_name] = embedder.embed_text(text)

            # Compose into single vector
            composite = compose(signal_vectors, "user")

            if uid not in all_snapshots:
                all_snapshots[uid] = []
            all_snapshots[uid].append({
                "cutoff_date": month_end,
                "composite": composite,
                "signal_vectors": signal_vectors,
            })

        print(f"    Done: {len(user_ids)} users embedded for {month_start}")

    return all_snapshots


def run_detection(snapshots: dict, concept_lib, alert_gen, chain_recon):
    """Run CUSUM + drift direction on all entity trajectories."""
    detections = []

    for uid, snaps in snapshots.items():
        if len(snaps) < 2:
            continue

        # Extract composite vectors as sequence
        vectors = [s["composite"] for s in snaps]

        # CUSUM scan
        cusum_result = cusum_scan_entity(vectors, threshold=0.05)

        # Drift analysis (compare first vs last)
        analysis = analyze_entity_drift(
            "user", uid, vectors[0], vectors[-1], concept_lib, alignment_threshold=0.2
        )

        # Generate alerts
        alert = alert_gen.from_drift_analysis(analysis)
        if alert:
            detections.append(alert)
            chain_recon.ingest_alert(alert)

        if cusum_result.change_detected:
            cusum_alert = alert_gen.from_cusum_result("user", uid, cusum_result, analysis)
            if cusum_alert:
                detections.append(cusum_alert)
                chain_recon.ingest_alert(cusum_alert)

    return detections


def main():
    parser = argparse.ArgumentParser(description="Run UEBA detection pipeline")
    parser.add_argument("--months", type=int, default=0,
                        help="Number of months to process (0 = auto-detect from available data)")
    args = parser.parse_args()

    data_dir = Path("data/generated")
    if not data_dir.exists():
        print("ERROR: No generated data. Run 'python -m simulator.generate' first.")
        sys.exit(1)

    # Determine available date range
    auth_dir = data_dir / "auth"
    if auth_dir.exists():
        csv_files = sorted(auth_dir.glob("*.csv"))
        if csv_files:
            first_date = date.fromisoformat(csv_files[0].stem)
            last_date = date.fromisoformat(csv_files[-1].stem)
            print(f"Available data: {first_date} to {last_date} ({len(csv_files)} days)")
        else:
            print("ERROR: No auth log CSVs found")
            sys.exit(1)
    else:
        print("ERROR: No auth log directory")
        sys.exit(1)

    # Build monthly windows from available data
    months = []
    current = first_date.replace(day=1)
    while current < last_date:
        month_end = (current.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        month_end = min(month_end, last_date)
        months.append((current, month_end))
        # Advance to first day of next month (from current, not month_end)
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    if args.months > 0:
        months = months[:args.months]

    print(f"Processing {len(months)} monthly windows")
    print()

    # Phase 1: Embed
    print("=" * 60)
    print("PHASE 1: BEHAVIORAL EMBEDDING")
    print("=" * 60)
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit(
            "OPENAI_API_KEY is required — real OpenAI embeddings are mandatory "
            "(mock embeddings have been removed)."
        )
    embedder = Embedder()
    snapshots = build_monthly_snapshots(data_dir, embedder, months)
    print(f"\nSnapshots built: {sum(len(v) for v in snapshots.values())} total")
    print(f"Embedder stats: {embedder.stats()}")
    print()

    # Phase 2: Detect
    print("=" * 60)
    print("PHASE 2: DETECTION SCAN")
    print("=" * 60)
    concept_lib = ConceptLibrary(embedder=embedder)
    concept_lib.embed_concepts()
    print(f"Concept library: {len(concept_lib._embeddings)} concepts embedded")

    alert_gen = AlertGenerator(
        drift_threshold=0.15,
        cusum_threshold=0.05,
        alignment_threshold=0.2,
    )
    chain_recon = KillChainReconstructor(correlation_window_hours=168)

    detections = run_detection(snapshots, concept_lib, alert_gen, chain_recon)
    print(f"\nAlerts generated: {len(detections)}")
    print(f"Kill chains: {len(chain_recon.get_active_chains())}")

    # Summary
    print()
    print("=" * 60)
    print("DETECTION RESULTS")
    print("=" * 60)
    if detections:
        by_severity = {}
        for a in detections:
            sev = a.severity.value if hasattr(a.severity, 'value') else str(a.severity)
            by_severity[sev] = by_severity.get(sev, 0) + 1
        print(f"  Alerts by severity: {by_severity}")
        print(f"  Kill chains: {len(chain_recon.get_active_chains())}")
        print()
        print("  Top 5 alerts:")
        for a in sorted(detections, key=lambda x: x.drift_magnitude, reverse=True)[:5]:
            print(f"    [{a.severity.value}] {a.entity_id}: {a.title} (drift={a.drift_magnitude:.4f})")
    else:
        print("  No alerts generated (drift below threshold).")
        print()
        print("  Real OpenAI embeddings should surface measurable concept alignment")
        print("  for attack scenarios (e.g., insider_threat_slow for USR-156)")

    # Save results
    results_dir = Path("data/pipeline_results")
    results_dir.mkdir(parents=True, exist_ok=True)

    # Save snapshots as parquet
    rows = []
    for uid, snaps in snapshots.items():
        for s in snaps:
            rows.append({
                "entity_type": "user",
                "entity_id": uid,
                "cutoff_date": s["cutoff_date"],
                "drift_from_first": float(drift_magnitude(snapshots[uid][0]["composite"], s["composite"])),
            })
    if rows:
        df = pd.DataFrame(rows)
        df.to_csv(results_dir / "drift_series.csv", index=False)
        print(f"\n  Drift series saved: {results_dir / 'drift_series.csv'}")

    print("\nPipeline complete.")


if __name__ == "__main__":
    main()
