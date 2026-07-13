# -*- coding: utf-8 -*-
"""Backfill the demo attacker USR-EVA into the two stores the Streamlit app reads
per-DAY, so EVA shows up on the **Digital Entity** and (after the trajectory re-run)
**Behavioral Drift** pages — WITHOUT disturbing the 250 canonical users.

WHAT THIS DOES
--------------
EVA only exists as 70 *weekly* feature rows (data/eva_features.csv).  The app's
per-day stores are:

  1. behavioral_snapshots (DB, port 5438) — entity x DAY grain, 181 cutoff_dates
     from 2025-01-01 -> 2026-04-29 (45,250 rows = 250 users x 181 dates).  EVA has
     0 rows there.  We *forward-fill* EVA: every cutoff_date is mapped to EVA's
     containing week's embeddings (week_idx = (cutoff - 2025-01-01).days // 7).

  2. data/tier3_results/entity_structures.json — the file the Digital Entity page
     falls back to when the DB is unavailable (USE_DB == False).  We append one
     USR-EVA record in the exact schema extract_entity_structures() emits.

EVA's zone / composite embeddings are produced with the *identical* pipeline the
250 go through (interpretive serialization -> OpenAI text-embedding-3-small (1536-d)
-> context-adaptive composition), by reusing scripts/integrate_eva.py's setup and
comparison/run_tier3.build_entity_zoo().  Population statistics are FROZEN to the
original 250 (exactly as integrate_eva does) so EVA's z-scored text — and therefore
its embeddings — line up with everyone else and the 250 stay byte-identical.

WHAT THIS DELIBERATELY DOES NOT TOUCH
-------------------------------------
  * trajectory_snapshots — DERIVED from behavioral_snapshots by
    pipeline/trajectory_snapshots.py.  A separate re-run of that module (after this
    backfill) computes EVA's velocity/drift and is what makes EVA appear on the
    Behavioral Drift page.  This script never writes trajectory_snapshots, so it
    cannot collide with a concurrent trajectory re-run.
  * The 250 canonical users — every write is scoped to entity_id = 'USR-EVA'
    (DB rows) or the single EVA element of the JSON list.  Idempotent: EVA rows /
    record are removed first, then re-created.

DRY_RUN
-------
DRY_RUN = True (default, like integrate_eva.py): computes everything and prints a
summary but writes NOTHING (no DB rows, no JSON).  NOTE: exactly like
integrate_eva.py, DRY_RUN still performs the OpenAI embedding call for EVA (so you
can preview the computed vectors/summary); only the *persistence* is gated.  Flip
DRY_RUN = False to actually write.

Run:  DB env + OPENAI_API_KEY (.env)
      DATABASE_URL_HOST='postgresql://cyber_ueba:password@127.0.0.1:5438/cyber_ueba' \
      DB_HOST='127.0.0.1' DB_PORT='5438' python scripts/backfill_eva_daily.py

After a real (DRY_RUN=False) run, re-derive EVA's trajectory:
      python -m pipeline.trajectory_snapshots        # picks up EVA from behavioral_snapshots
"""
import os
import sys
import json
from datetime import date, timedelta

# Make both the repo root and the scripts/ dir importable (integrate_eva lives in
# scripts/ and itself inserts the repo root on sys.path).
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv
load_dotenv()

import numpy as np
import pandas as pd

# ── Reuse integrate_eva.py verbatim (constants + EVA's qualitative synthesis) ──
# integrate_eva imports cleanly (no work at import time; main() is __main__-guarded),
# so its functions/constants are directly reusable.
import integrate_eva as eva_mod
from integrate_eva import (
    synth_qual, EVA, EVA_DEV, BASIS, RAMP_START, RAMP_END,
)

# ── The identical building blocks the 250 (and integrate_eva) use ──
from comparison.run_comparison import (
    DATA_DIR, FEATURE_COLS, _build_user_device_map, engineer_weekly_features,
)
import comparison.run_tier3 as rt3
from comparison.run_tier3 import (
    build_entity_zoo, extract_entity_structures,
    _compute_population_stats, _compute_user_baseline,
)
from models.cyber_entity import Tier3Config
from models.hierarchical_zones import (
    serialize_zone_interpretive, BehavioralContext,
    USER_ZONE_ORDER, ALL_CONTEXTS,
)
from detection.novelty_features import annotate_qualitative_features
from simulator.entities import generate_all
from embeddings.embedder import Embedder
from detection.reference_concepts import ConceptLibrary
from run_tier3_250 import ROLE_TO_GROUP

# Guaranteed-identical pgvector text format ("[%.8f,%.8f,...]") — the same helper
# pipeline/behavioral_snapshots.py uses to write the 250.
from pipeline.behavioral_snapshots import _vec_to_pgvector
from pipeline.db_connect import get_connection


DRY_RUN = False   # flip to False to write EVA into behavioral_snapshots + the JSON

STRUCT_JSON = os.path.join(_ROOT, "data", "tier3_results", "entity_structures.json")

# Column mapping user-zone -> behavioral_snapshots column (matches entity_materialize).
ZONE_TO_COL = {
    "identity": "zone_identity",
    "access_pattern": "zone_access_pattern",
    "data_behavior": "zone_data_behavior",
    "network_footprint": "zone_network_footprint",
    "risk_posture": "zone_risk_posture",
}

# Exact 14-column upsert used by pipeline/behavioral_snapshots.py.  We DELETE EVA
# first (idempotent), but keep ON CONFLICT so a re-run is always safe.
INSERT_SQL = """
    INSERT INTO behavioral_snapshots (
        entity_type, entity_id, cutoff_date,
        zone_identity, zone_access_pattern, zone_data_behavior,
        zone_network_footprint, zone_risk_posture,
        composite,
        composite_normal_ops, composite_insider_inv,
        composite_apt_hunt, composite_privilege_audit,
        zone_texts
    ) VALUES (
        %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s,
        %s, %s, %s, %s,
        %s::jsonb
    ) ON CONFLICT (entity_type, entity_id, cutoff_date) DO UPDATE SET
        zone_identity = EXCLUDED.zone_identity,
        zone_access_pattern = EXCLUDED.zone_access_pattern,
        zone_data_behavior = EXCLUDED.zone_data_behavior,
        zone_network_footprint = EXCLUDED.zone_network_footprint,
        zone_risk_posture = EXCLUDED.zone_risk_posture,
        composite = EXCLUDED.composite,
        composite_normal_ops = EXCLUDED.composite_normal_ops,
        composite_insider_inv = EXCLUDED.composite_insider_inv,
        composite_apt_hunt = EXCLUDED.composite_apt_hunt,
        composite_privilege_audit = EXCLUDED.composite_privilege_audit,
        zone_texts = EXCLUDED.zone_texts,
        computed_at = now()
"""


# ══════════════════════════════════════════════════════════════════════════════
#  Phase A — build EVA through the real pipeline (mirrors integrate_eva.main())
# ══════════════════════════════════════════════════════════════════════════════
def build_eva():
    """Run the identical embed pipeline for EVA as #251 and return everything the
    two backfills need.

    Returns dict with:
        entity        : the EVA CyberEntity (weekly zone/composite series + phase)
        features_df   : full annotated 251-user feature frame (EVA rows included)
        embedder      : the Embedder (for extract_entity_structures)
        pop_mean/std  : the FROZEN 250 population stats (for faithful text reproduction)
        week_to_pos   : {week_idx -> position in EVA's weekly series lists}
        zone_texts    : list[dict] EVA's per-week interpretive zone texts (see note)
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    assert api_key, "OPENAI_API_KEY not set (real embeddings are mandatory)."
    embedder = Embedder(api_key=api_key)

    entities = generate_all()
    users_df, devices_df = entities["users"], entities["devices"]
    user_device_map = _build_user_device_map()

    auth_dir = DATA_DIR / "auth"
    files = sorted(auth_dir.glob("*.csv"))
    first_date = date.fromisoformat(files[0].stem)
    last_date = date.fromisoformat(files[-1].stem)

    user_ids = users_df["user_id"].tolist()
    user_role_map = {u["user_id"]: ROLE_TO_GROUP.get(u.get("role", "unknown"), "unknown")
                     for _, u in users_df.iterrows()}

    # ---- Phase 1: the real 250 features (from telemetry) ----
    print("Phase 1: engineering weekly features for the 250 ...", flush=True)
    features_df = engineer_weekly_features(
        first_date, last_date, user_ids, user_device_map, user_role_groups=user_role_map)

    # ---- FREEZE population stats to the ORIGINAL 250 (before EVA is injected) so
    #      the 250's texts/embeddings are byte-identical and EVA is z-scored against
    #      the same reference the 250 saw.  build_entity_zoo() calls
    #      rt3._compute_population_stats() internally -> it now returns these. ----
    _frozen_pop = rt3._compute_population_stats(features_df, FEATURE_COLS)
    rt3._compute_population_stats = lambda *a, **k: _frozen_pop
    pop_mean, pop_std = _frozen_pop
    # Flag EVA as an attacker so it is excluded from group-normal stats AND so
    # extract_entity_structures() marks is_attack=True.  (Same op as integrate_eva.)
    rt3.ATTACK_ENTITIES = set(rt3.ATTACK_ENTITIES) | {EVA}
    print("  Frozen 250 population stats + flagged EVA as attacker.", flush=True)

    # ---- Inject EVA as #251 (profile from USR-184; numeric from csv; synth qual) ----
    print("Injecting USR-EVA (basis %s) ..." % BASIS, flush=True)
    eva_num = pd.read_csv(os.path.join(_ROOT, "data", "eva_features.csv"))
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
        if "week_start" in features_df.columns:
            r["week_start"] = wk_start[w]
        if "week_end" in features_df.columns:
            r["week_end"] = (first_date + timedelta(weeks=w, days=6)).isoformat()
        for c in features_df.columns:      # carry template cols (role_group etc.)
            if c not in r:
                r[c] = tmpl[c].iloc[0] if (len(tmpl) and c in tmpl.columns) else None
        eva_rows.append(r)
    features_df = pd.concat([features_df, pd.DataFrame(eva_rows)], ignore_index=True)
    user_role_map[EVA] = "developer"

    # add EVA profile + device so build_entity_zoo can find them
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

    # ---- Identical pipeline over the 251 (250 are cache hits; EVA embeds fresh) ----
    features_df = annotate_qualitative_features(features_df, user_role_map)
    concept_lib = ConceptLibrary(embedder=embedder)
    concept_lib.embed_concepts()
    print("Phase 2: build_entity_zoo (250 cached; EVA embeds fresh) ...", flush=True)
    zoo = build_entity_zoo(user_ids, features_df, entities, user_device_map,
                           embedder, concept_lib, Tier3Config())
    entity = zoo[EVA]

    # position map: EVA's weekly series lists are ordered by sorted week_idx
    eva_weeks_sorted = sorted(int(w) for w in
                              features_df[features_df.user_id == EVA].week_idx.unique())
    week_to_pos = {w: i for i, w in enumerate(eva_weeks_sorted)}

    # ---- EVA's per-week INTERPRETIVE zone texts (for behavioral_snapshots.zone_texts) ----
    # build_entity_zoo() embeds these texts but does not retain them, so we
    # reproduce them here using the *same* inputs (frozen pop stats, EVA's baseline,
    # rolling 3-week history) -> the text is identical to what was embedded.
    zone_texts = _reproduce_eva_zone_texts(features_df, eva_profile, pop_mean, pop_std)

    return {
        "entity": entity,
        "features_df": features_df,
        "embedder": embedder,
        "pop_mean": pop_mean,
        "pop_std": pop_std,
        "week_to_pos": week_to_pos,
        "eva_weeks_sorted": eva_weeks_sorted,
        "zone_texts": zone_texts,
    }


def _reproduce_eva_zone_texts(features_df, eva_profile, pop_mean, pop_std):
    """Reproduce EVA's per-week interpretive zone texts, byte-for-byte matching the
    inner serialization loop of comparison/run_tier3.build_entity_zoo().

    Returns list[dict{zone_name: text}] ordered by EVA's sorted week_idx.
    """
    eva_weeks = features_df[features_df.user_id == EVA].sort_values("week_idx")
    user_baseline = _compute_user_baseline(eva_weeks, FEATURE_COLS)   # default 8 wk baseline
    texts_per_week = []
    recent_history = []
    for row_idx, (_, row) in enumerate(eva_weeks.iterrows()):
        feat_dict = {col: row[col] for col in FEATURE_COLS}
        for qcol in ["qual_file_dirs", "qual_net_ext_ips", "qual_dns_domains"]:
            if qcol in row.index:
                feat_dict[qcol] = row[qcol]
        bctx = BehavioralContext(
            pop_mean=pop_mean, pop_std=pop_std,
            user_baseline=user_baseline, week_idx=row_idx,
            recent_history=list(recent_history[-3:]),
        )
        wk_texts = {}
        for zone_name in USER_ZONE_ORDER:
            wk_texts[zone_name] = serialize_zone_interpretive(
                "user", zone_name, eva_profile, feat_dict, bctx)
        texts_per_week.append(wk_texts)
        recent_history.append(feat_dict)
    return texts_per_week


# ══════════════════════════════════════════════════════════════════════════════
#  Phase B — forward-fill EVA into behavioral_snapshots (all 181 cutoff_dates)
# ══════════════════════════════════════════════════════════════════════════════
def _fetch_cutoff_dates(conn):
    """The exact set of user cutoff_dates already in behavioral_snapshots (181)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT cutoff_date FROM behavioral_snapshots "
            "WHERE entity_type='user' ORDER BY cutoff_date")
        return [r[0] for r in cur.fetchall()]


def backfill_behavioral_snapshots(built):
    """Write one EVA row per existing cutoff_date, using the containing week's
    embeddings.  Idempotent (deletes EVA rows first).  Never touches the 250."""
    entity = built["entity"]
    week_to_pos = built["week_to_pos"]
    eva_weeks_sorted = built["eva_weeks_sorted"]
    zone_texts = built["zone_texts"]
    max_week = eva_weeks_sorted[-1]

    zone_series = entity.zone_snapshot_series               # {zone: [wk0, wk1, ...]}
    ctx_composites = getattr(entity, "_contextual_composites", {})  # {ctx: [wk0, ...]}

    conn = get_connection()
    try:
        dates = _fetch_cutoff_dates(conn)
        if not dates:
            print("  No behavioral_snapshots cutoff_dates found — is the DB seeded?")
            return 0
        base_date = dates[0]                                # 2025-01-01 (week 0 start)
        if base_date != date(2025, 1, 1):
            print(f"  WARNING: earliest cutoff_date is {base_date}, expected 2025-01-01; "
                  "week mapping keys off this date.")

        rows = []
        for cutoff in dates:
            # week_idx of the containing week; clamp into EVA's available range
            wk = (cutoff - base_date).days // 7
            wk = max(0, min(wk, max_week))
            pos = week_to_pos[wk]

            zvecs = {z: zone_series[z][pos] for z in USER_ZONE_ORDER}
            comp_normal = ctx_composites["normal_ops"][pos]
            comp_insider = ctx_composites["insider_investigation"][pos]
            comp_apt = ctx_composites["apt_hunt"][pos]
            comp_priv = ctx_composites["privilege_audit"][pos]

            rows.append((
                "user", EVA, cutoff,
                _vec_to_pgvector(zvecs["identity"]),
                _vec_to_pgvector(zvecs["access_pattern"]),
                _vec_to_pgvector(zvecs["data_behavior"]),
                _vec_to_pgvector(zvecs["network_footprint"]),
                _vec_to_pgvector(zvecs["risk_posture"]),
                _vec_to_pgvector(comp_normal),          # composite  == normal_ops (matches the 250)
                _vec_to_pgvector(comp_normal),          # composite_normal_ops
                _vec_to_pgvector(comp_insider),         # composite_insider_inv
                _vec_to_pgvector(comp_apt),             # composite_apt_hunt
                _vec_to_pgvector(comp_priv),            # composite_privilege_audit
                json.dumps(zone_texts[pos]),            # zone_texts (interpretive, jsonb)
            ))

        print(f"\nbehavioral_snapshots: prepared {len(rows)} EVA rows across "
              f"{len(dates)} cutoff_dates ({dates[0]} -> {dates[-1]}).")
        print(f"  week span: {eva_weeks_sorted[0]}..{max_week} | "
              f"sample date->week: {dates[0]}->{(dates[0]-base_date).days//7}, "
              f"{dates[-1]}->{(dates[-1]-base_date).days//7}")

        if DRY_RUN:
            print("  DRY_RUN=True -> not writing behavioral_snapshots.")
            return len(rows)

        from psycopg2.extras import execute_batch
        with conn.cursor() as cur:
            cur.execute("DELETE FROM behavioral_snapshots WHERE entity_id=%s", (EVA,))
            deleted = cur.rowcount
            execute_batch(cur, INSERT_SQL, rows, page_size=100)
        conn.commit()
        print(f"  Deleted {deleted} old EVA rows; inserted {len(rows)} (250 untouched).")
        return len(rows)
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  Phase C — append EVA to entity_structures.json (Digital Entity fallback store)
# ══════════════════════════════════════════════════════════════════════════════
def backfill_entity_structures_json(built):
    """Append one USR-EVA record in extract_entity_structures()'s exact schema.
    Idempotent (removes any existing EVA record first).  Never touches the 250."""
    entity = built["entity"]
    features_df = built["features_df"]
    embedder = built["embedder"]

    # Reuse the canonical extractor for a guaranteed schema match (is_attack comes
    # out True because EVA is in rt3.ATTACK_ENTITIES).
    records = extract_entity_structures({EVA: entity}, features_df, embedder)
    if not records:
        print("\nentity_structures.json: extractor produced no EVA record (skipped).")
        return 0
    eva_record = records[0]

    if not os.path.exists(STRUCT_JSON):
        print(f"\nentity_structures.json: {STRUCT_JSON} missing — nothing to append to.")
        return 0

    with open(STRUCT_JSON) as f:
        structures = json.load(f)
    before = len(structures)
    structures = [s for s in structures if s.get("entity_id") != EVA]   # idempotent
    structures.append(eva_record)

    print(f"\nentity_structures.json: {before} records -> {len(structures)} "
          f"(EVA is_attack={eva_record.get('is_attack')}, week_idx={eva_record.get('week_idx')}).")
    zt = eva_record.get("zone_serialized_text", {})
    print("  EVA identity zone text:", str(zt.get("identity", ""))[:120])

    if DRY_RUN:
        print("  DRY_RUN=True -> not writing entity_structures.json.")
        return 1

    with open(STRUCT_JSON, "w") as f:
        json.dump(structures, f, indent=2, default=str)
    print(f"  Wrote {STRUCT_JSON} ({len(structures)} records).")
    return 1


# ══════════════════════════════════════════════════════════════════════════════
def main():
    print("=" * 78)
    print("USR-EVA daily backfill  (DRY_RUN=%s)" % DRY_RUN)
    print("  NOTE: EVA is embedded via OpenAI even under DRY_RUN (like integrate_eva);")
    print("        only DB / JSON persistence is gated by DRY_RUN.")
    print("=" * 78)

    built = build_eva()

    ps = built["entity"].phase_state
    print(f"\nEVA phase_state: regime={ps.current_regime} "
          f"total_drift={ps.total_drift:.4f} velocity={ps.velocity_magnitude:.4f} "
          f"stability={ps.stability:.4f}")

    n_snap = backfill_behavioral_snapshots(built)
    n_json = backfill_entity_structures_json(built)

    print("\n" + "=" * 78)
    print("SUMMARY")
    print(f"  behavioral_snapshots EVA rows : {n_snap}")
    print(f"  entity_structures.json EVA rec: {n_json}")
    if DRY_RUN:
        print("  DRY_RUN=True -> nothing written.  Review above, then set DRY_RUN=False.")
    else:
        print("  Written.  NEXT: re-derive EVA's trajectory so it shows on Behavioral Drift:")
        print("      python -m pipeline.trajectory_snapshots")
    print("=" * 78)


if __name__ == "__main__":
    main()
