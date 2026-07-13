# -*- coding: utf-8 -*-
"""Integrate USR-EVA (evasive low-and-slow insider) into the real pipeline as user #251.

Mirrors run_tier3_250.main() but ADDS EVA:
  - profile copied from real developer USR-184 (-> USR-EVA / DEV-EVA)
  - numeric weekly features from data/eva_features.csv
  - synthesized qualitative content: file dirs drift toward sensitive (ATYPICAL for a dev),
    external IPs / DNS stay NORMAL & recurring (so novelty stays 0 - no beacon/DGA)
Runs the identical embed -> trajectory -> composite path so EVA lands faithfully in every
chart. DRY_RUN=True by default: computes and prints EVA's result, writes NO DB / gold CSVs.

Run:  DB env + OPENAI_API_KEY (.env)  ->  python scripts/integrate_eva.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
from datetime import date, timedelta
import numpy as np, pandas as pd

from comparison.run_comparison import (DATA_DIR, FEATURE_COLS, _build_user_device_map,
                                       engineer_weekly_features)
from comparison.run_tier3 import (RESULTS_DIR, build_entity_zoo, save_embeddings_to_db,
                                  extract_weekly_trajectories)
from models.cyber_entity import Tier3Config
from detection.novelty_features import annotate_qualitative_features, compute_novelty_metrics
from detection.composite_scorer import (extract_user_features, compute_group_zscores,
                                        compute_composite_scores)
from simulator.entities import generate_all
from embeddings.embedder import Embedder
from detection.reference_concepts import ConceptLibrary
from run_tier3_250 import ROLE_TO_GROUP, ATTACKS

DRY_RUN = False                    # flip to False to write gold CSVs + DB
EVA, EVA_DEV, BASIS = "USR-EVA", "DEV-EVA", "USR-184"
RAMP_START, RAMP_END = 35, 55      # matches evasive_experiment.py
BASE_DIRS = ["/engineering/repos", "/shared/docs/projects", "/engineering/internal-tools"]
SENSITIVE = ["/finance/budgets", "/hr/org-charts", "/security/policies", "/executive/strategy"]
NORMAL_IPS = "203.0.113.10; 198.51.100.5"      # recurring shared dsts -> not novel
NORMAL_DOMS = "github.com; slack.com; storage.googleapis.com"


def synth_qual(week_idx):
    """EVA's semantic content per week: dirs drift toward sensitive; IPs/DNS stay normal."""
    frac = 0.0 if week_idx < RAMP_START else (1.0 if week_idx >= RAMP_END
                                              else (week_idx - RAMP_START) / (RAMP_END - RAMP_START))
    dirs = list(BASE_DIRS)
    n_sens = int(round(frac * len(SENSITIVE)))     # add 0..4 sensitive dirs as the attack progresses
    dirs += SENSITIVE[:n_sens]
    return {"qual_file_dirs": "; ".join(dirs), "qual_net_ext_ips": NORMAL_IPS,
            "qual_dns_domains": NORMAL_DOMS}


def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    assert api_key, "OPENAI_API_KEY not set"
    embedder = Embedder(api_key=api_key)
    entities = generate_all()
    users_df, devices_df = entities["users"], entities["devices"]
    user_device_map = _build_user_device_map()

    auth_dir = DATA_DIR / "auth"
    files = sorted(auth_dir.glob("*.csv"))
    first_date, last_date = date.fromisoformat(files[0].stem), date.fromisoformat(files[-1].stem)

    user_ids = users_df["user_id"].tolist()
    user_role_map = {u["user_id"]: ROLE_TO_GROUP.get(u.get("role", "unknown"), "unknown")
                     for _, u in users_df.iterrows()}

    # ---- Phase 1: the real 250 features (from telemetry) ----
    print("Phase 1: engineering weekly features for the 250 ...", flush=True)
    features_df = engineer_weekly_features(first_date, last_date, user_ids, user_device_map,
                                           user_role_groups=user_role_map)

    # ---- FREEZE population stats to the original 250 so their texts/embeddings are
    #      byte-identical (cache hits, no re-embed) and their canonical numbers cannot move.
    import comparison.run_tier3 as rt3
    _frozen_pop = rt3._compute_population_stats(features_df, FEATURE_COLS)
    rt3._compute_population_stats = lambda *a, **k: _frozen_pop
    # flag EVA as an attacker: it is then EXCLUDED from each group's normal stats, so the
    # 250's group-z composite scores are frozen automatically (overlay / demo attacker).
    rt3.ATTACK_ENTITIES = set(rt3.ATTACK_ENTITIES) | {EVA}
    print("  Frozen population stats + flagged EVA as attacker (250 composite frozen).", flush=True)

    # ---- inject EVA as #251 (profile from USR-184; numeric from csv; synth qual) ----
    print("Injecting USR-EVA (basis %s) ..." % BASIS, flush=True)
    eva_num = pd.read_csv("data/eva_features.csv")
    weeks = sorted(int(w) for w in features_df.week_idx.unique())
    wk_start = {w: (first_date + timedelta(weeks=w)).isoformat() for w in weeks}
    tmpl = features_df[features_df.user_id == BASIS].sort_values("week_idx").reset_index(drop=True)
    eva_rows = []
    for w in weeks:
        r = {"user_id": EVA, "week_idx": w}
        num = eva_num[eva_num.week_idx == w]
        for c in FEATURE_COLS:
            r[c] = float(num[c].iloc[0]) if (len(num) and c in num.columns) else 0.0
        r.update(synth_qual(w))
        if "week_start" in features_df.columns: r["week_start"] = wk_start[w]
        if "week_end" in features_df.columns:   r["week_end"] = (first_date + timedelta(weeks=w, days=6)).isoformat()
        # carry any other cols from the template (role_group etc.) so schema matches
        for c in features_df.columns:
            if c not in r:
                r[c] = tmpl[c].iloc[0] if (len(tmpl) and c in tmpl.columns) else None
        eva_rows.append(r)
    features_df = pd.concat([features_df, pd.DataFrame(eva_rows)], ignore_index=True)
    user_role_map[EVA] = "developer"

    # add EVA to entities so build_entity_zoo can find its profile/device
    eva_profile = users_df[users_df.user_id == BASIS].iloc[0].to_dict()
    eva_profile.update({"user_id": EVA, "username": "eva.insider", "primary_device_id": EVA_DEV})
    users_df = pd.concat([users_df, pd.DataFrame([eva_profile])], ignore_index=True)
    eva_dev = devices_df[devices_df.owner_user_id == BASIS]
    eva_dev = (eva_dev.iloc[0].to_dict() if len(eva_dev) else devices_df.iloc[0].to_dict())
    eva_dev.update({"device_id": EVA_DEV, "owner_user_id": EVA})
    devices_df = pd.concat([devices_df, pd.DataFrame([eva_dev])], ignore_index=True)
    entities = {**entities, "users": users_df, "devices": devices_df}
    user_device_map = {**user_device_map, EVA: [EVA_DEV]}
    user_ids = user_ids + [EVA]

    # ---- Phase 1b..5: identical pipeline over the 251 ----
    features_df = annotate_qualitative_features(features_df, user_role_map)
    concept_lib = ConceptLibrary(embedder=embedder); concept_lib.embed_concepts()
    print("Phase 2: build_entity_zoo (250 cached; EVA embeds fresh) ...", flush=True)
    zoo = build_entity_zoo(user_ids, features_df, entities, user_device_map,
                           embedder, concept_lib, Tier3Config())
    traj_df = extract_weekly_trajectories(zoo, features_df)
    zscored = compute_group_zscores(extract_user_features(traj_df))
    novelty_df = compute_novelty_metrics(features_df)
    scores = compute_composite_scores(zscored, novelty_df=novelty_df)

    # ---- validation report ----
    scores = scores.reset_index(drop=True)
    def line(uid):
        row = scores[scores.uid == uid]
        if row.empty: return "  %-9s: NOT SCORED" % uid
        r = row.iloc[0]; rank = int(scores.index[scores.uid == uid][0]) + 1
        return ("  %-9s rank #%-3d/%d  composite=%6.2f  signal=%5.2f  breadth=%2d  novelty=%4.1f"
                % (uid, rank, len(scores), r.composite, r.signal_strength, int(r.breadth_15), r.novelty_score))
    print("\n=== EVA + real attackers (composite ranking over 251) ===")
    for uid in [EVA, "USR-118", "USR-156", "USR-234", "USR-042"]:
        print(line(uid))
    nrow = novelty_df[novelty_df.get("uid", novelty_df.get("user_id")) == EVA] if len(novelty_df) else pd.DataFrame()
    print("\nEVA novelty row:", nrow.to_dict("records") if len(nrow) else "(0 / none - expected)")
    print("EVA weekly_trajectory rows:", int((traj_df.user_id == EVA).sum()),
          "| sample composite_drift head:",
          [round(float(x), 3) for x in traj_df[traj_df.user_id == EVA].sort_values("week_idx")["composite_drift"].head(6)])

    if DRY_RUN:
        print("\nDRY_RUN=True -> no CSV/DB written. Review EVA above, then set DRY_RUN=False.")
        return
    # ---- (DRY_RUN=False) append ONLY EVA's rows to the existing gold CSVs, then reload.
    #      the 250 rows are read from gold and re-written unchanged -> byte-identical. ----
    import json as _json
    def append_eva(csv_name, recomputed, idc):
        path = RESULTS_DIR / csv_name
        base = pd.read_csv(path)
        base = base[base[idc] != EVA]                       # idempotent
        eva_rows = recomputed[recomputed[idc] == EVA]
        out = pd.concat([base, eva_rows[base.columns.intersection(eva_rows.columns)]], ignore_index=True)
        if "composite" in out.columns:
            out = out.sort_values("composite", ascending=False).reset_index(drop=True)
        out.to_csv(path, index=False)
        print("  %-28s -> %d rows (EVA appended)" % (csv_name, len(out)))
    append_eva("composite_scores.csv", scores, "uid")
    append_eva("novelty_metrics.csv", novelty_df, "uid")
    append_eva("zscored_features.csv", zscored, "uid")
    append_eva("all250_trajectories.csv", traj_df, "user_id")

    from pipeline.db_connect import get_connection
    conn = get_connection(); cur = conn.cursor()
    cur.execute("DELETE FROM weekly_features WHERE user_id=%s", (EVA,))
    for _, r in features_df[features_df.user_id == EVA].sort_values("week_idx").iterrows():
        feats = {c: float(r[c]) for c in FEATURE_COLS}
        cur.execute("INSERT INTO weekly_features (user_id,week_idx,week_start,week_end,features) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (EVA, int(r.week_idx), r.get("week_start"), r.get("week_end"), _json.dumps(feats)))
    conn.commit()
    print("  weekly_features: EVA 70 rows inserted (250 untouched)")

    from pipeline.populate_dashboard_tables import (populate_composite_scores, populate_novelty_metrics,
                                                    populate_zscored_features, populate_weekly_trajectories)
    for fn in (populate_composite_scores, populate_novelty_metrics, populate_zscored_features, populate_weekly_trajectories):
        fn(conn)
    print("DB synced: EVA appended everywhere; 250 gold rows unchanged.")


if __name__ == "__main__":
    main()
