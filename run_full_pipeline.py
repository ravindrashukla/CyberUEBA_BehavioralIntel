"""Run the full ACECARD pipeline with real OpenAI embeddings.

Steps:
  1. behavioral_snapshots (interpretive serialization + real embeddings)
  2. trajectory_snapshots (velocity/acceleration/regime)
  3. embedding_history (SCD2 ledger)

Usage:
    python run_full_pipeline.py
    python run_full_pipeline.py --start 2025-01-01 --end 2025-03-31
    python run_full_pipeline.py --skip-embeddings  # skip step 1, run 2+3 only
"""

import argparse
import sys
import time

def main():
    parser = argparse.ArgumentParser(description="Run full ACECARD pipeline")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--skip-embeddings", action="store_true",
                        help="Skip behavioral snapshots (step 1)")
    args = parser.parse_args()

    date_args = []
    if args.start:
        date_args.extend(["--start", args.start])
    if args.end:
        date_args.extend(["--end", args.end])

    t0 = time.time()

    if not args.skip_embeddings:
        print("=" * 60)
        print("STEP 1: Behavioral Snapshots (real OpenAI embeddings)")
        print("=" * 60, flush=True)
        sys.argv = ["behavioral_snapshots", "--embedder", "openai"] + date_args
        from pipeline.behavioral_snapshots import main as bs_main
        bs_main()
        print(f"\nStep 1 complete in {time.time() - t0:.0f}s\n", flush=True)

    t1 = time.time()
    print("=" * 60)
    print("STEP 2: Trajectory Snapshots")
    print("=" * 60, flush=True)
    sys.argv = ["trajectory_snapshots"] + date_args
    from pipeline.trajectory_snapshots import main as ts_main
    ts_main()
    print(f"\nStep 2 complete in {time.time() - t1:.0f}s\n", flush=True)

    t2 = time.time()
    print("=" * 60)
    print("STEP 3: Embedding History (SCD2)")
    print("=" * 60, flush=True)
    sys.argv = ["embedding_history"] + date_args
    from pipeline.embedding_history import main as eh_main
    eh_main()
    print(f"\nStep 3 complete in {time.time() - t2:.0f}s\n", flush=True)

    total = time.time() - t0
    print("=" * 60)
    print(f"PIPELINE COMPLETE in {total:.0f}s ({total/60:.1f} min)")
    print("=" * 60)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    main()
