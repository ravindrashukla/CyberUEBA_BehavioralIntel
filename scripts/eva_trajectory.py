# -*- coding: utf-8 -*-
"""Derive USR-EVA's trajectory_snapshots (scoped to EVA only — does NOT re-run the 250).

Prereq: EVA must already be in behavioral_snapshots (scripts/backfill_eva_daily.py).
Reuses pipeline.trajectory_snapshots.process_day for byte-identical methodology.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
from pipeline.trajectory_snapshots import _available_dates, process_day, WINDOW_DAYS
from pipeline.db_connect import get_connection

conn = get_connection()
dates = _available_dates(conn)
print(f"{len(dates)} cutoff dates ({dates[0]} -> {dates[-1]}); scoping to USR-EVA only")
tot = 0
for i, d in enumerate(dates):
    n, _ev = process_day(conn, d, ["USR-EVA"], WINDOW_DAYS)
    tot += n
    if (i + 1) % 30 == 0 or i == len(dates) - 1:
        print(f"  [{i+1}/{len(dates)}] {d} — EVA rows so far {tot}", flush=True)
conn.close()
print(f"Done. EVA trajectory_snapshots rows written: {tot}")
