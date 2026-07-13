# -*- coding: utf-8 -*-
"""Forward-fill USR-EVA into daily_features so Digital Entity Stage-1/2 populate.

daily_features covers 130 daily dates (Jan-May 2025 = weeks 0-18) for all 250 users.
EVA has only 70 weekly rows; we map each daily date to EVA's containing week and copy
that week's feature values. 21 of the 31 feature columns exist in EVA's weekly set;
the other 10 (app_*, priv_*, auth_success, auth_methods) EVA never had -> 0.0.
Idempotent (deletes EVA rows first). Never touches the 250. No embeddings.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
from pipeline.db_connect import get_connection

conn = get_connection(); cur = conn.cursor()
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='daily_features' ORDER BY ordinal_position")
allcols = [r[0] for r in cur.fetchall()]
featcols = [c for c in allcols if c not in ("id", "user_id", "feature_date", "computed_at")]

cur.execute("SELECT DISTINCT feature_date FROM daily_features ORDER BY feature_date")
dates = [r[0] for r in cur.fetchall()]

cur.execute("SELECT week_idx, features FROM weekly_features WHERE user_id='USR-EVA' ORDER BY week_idx")
wf = {int(w): (f if isinstance(f, dict) else json.loads(f)) for w, f in cur.fetchall()}
assert wf, "USR-EVA has no weekly_features"
max_wk = max(wf)
base = dates[0]
print(f"daily_features: {len(dates)} dates ({dates[0]} -> {dates[-1]}); {len(featcols)} feature cols; EVA weeks 0..{max_wk}")

cur.execute("DELETE FROM daily_features WHERE user_id='USR-EVA'")
deleted = cur.rowcount
cols_sql = ",".join(["user_id", "feature_date"] + featcols)
ph = ",".join(["%s"] * (2 + len(featcols)))
ins = f"INSERT INTO daily_features ({cols_sql}) VALUES ({ph})"
n = 0
for d in dates:
    wk = max(0, min((d - base).days // 7, max_wk))
    feats = wf[wk]
    vals = [float(feats.get(c, 0.0)) for c in featcols]
    cur.execute(ins, ["USR-EVA", d] + vals)
    n += 1
conn.commit()
print(f"Deleted {deleted} old EVA rows; inserted {n} daily_features rows (250 untouched).")
conn.close()
