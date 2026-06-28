"""Evidence layer — explains a composite verdict in raw-log terms.

This does NOT score or detect. The composite scorer (detection/composite_scorer.py)
remains the detector. This layer takes a user the composite already ranked and
builds the evidence chain that ties the verdict back to raw data:

    verdict (composite + rank)
      -> raw-log primitives that fired (peer-relative, with actual numbers)
        -> the specific weeks whose raw rows back each primitive
          -> the named attack profile those primitives compose

Every primitive is computed straight from weekly_features / novelty_metrics —
no embedding drift, no z-of-drift. A primitive "fires" only when the raw value
clears its role-peer bar, so each firing carries a number an analyst can verify
against the underlying log rows.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from detection.composite_scorer import ROLE_TO_GROUP

# ── primitive catalog ──────────────────────────────────────────────────────
# Each primitive is a raw-log computation over weekly_features. `agg` says how
# the per-week column collapses to one per-user number; `raw` is the underlying
# log column an analyst drills into; `fmt` renders the value for humans.
LATE = "late"        # mean over the second half of weeks
TREND = "trend"      # late-half mean minus early-half mean
PEAK = "peak"        # max over all weeks

PRIMITIVES = [
    # name, raw column, agg, human label, fmt
    ("restricted_access",   "file_restricted_ratio",     LATE,  "Restricted-file access rate",        "pct"),
    ("confidential_access", "file_confidential_ratio",   LATE,  "Confidential-file access rate",      "pct"),
    ("sensitivity_escalation", "_sensitivity",           TREND, "Sensitivity rising over time",       "ppt"),
    ("off_hours_auth",      "auth_off_hours_ratio",      LATE,  "Off-hours authentication rate",      "pct"),
    ("off_hours_trend",     "auth_off_hours_ratio",      TREND, "Off-hours shift over time",          "ppt"),
    ("lateral_fanout",      "auth_unique_dests",         TREND, "Auth destination fan-out (lateral)", "num"),
    ("external_pull",       "net_external_ratio",        LATE,  "External network ratio",             "pct"),
    ("dns_dga",             "dns_nxdomain_ratio",        LATE,  "NXDOMAIN rate (DGA/tunnel tell)",     "pct"),
    ("dns_breadth",         "dns_unique_domains",        LATE,  "Unique DNS domains",                 "num"),
    ("endpoint_risk",       "endpoint_suspicious_ratio", LATE,  "Suspicious endpoint-process rate",   "pct"),
]

# profiles: which primitives co-occur for each known attack pattern
PROFILES = {
    "Insider exfiltration": ["restricted_access", "confidential_access",
                             "sensitivity_escalation", "off_hours_auth", "volume_steady"],
    "C2 / slow APT": ["novel_ip_persistence", "dns_dga", "external_pull", "dns_breadth"],
    "Living-off-the-land lateral": ["off_hours_auth", "off_hours_trend",
                                    "lateral_fanout", "endpoint_risk", "external_pull"],
    "Telecom collection": ["restricted_access", "external_pull",
                           "dns_breadth", "lateral_fanout"],
}

ATTACK_NAMES = {
    "USR-042": "Volt Typhoon", "USR-118": "Salt Typhoon",
    "USR-156": "Insider", "USR-234": "Slow APT",
}


def _agg(values: np.ndarray, how: str) -> float:
    v = np.asarray(values, dtype=float)
    if len(v) == 0:
        return 0.0
    h = len(v) // 2
    if how == LATE:
        return float(np.mean(v[h:]))
    if how == TREND:
        early = float(np.mean(v[:h])) if h else 0.0
        return float(np.mean(v[h:]) - early)
    if how == PEAK:
        return float(np.max(v))
    return 0.0


def build_primitive_table(weekly_feats: pd.DataFrame,
                          novelty_df: pd.DataFrame,
                          scores_df: pd.DataFrame) -> pd.DataFrame:
    """One row per user: every primitive's raw value + grp/is_attack context."""
    grp_of = dict(zip(scores_df.uid, scores_df.grp))
    att_of = dict(zip(scores_df.uid, scores_df.is_attack))
    nov = {r["uid"]: r for _, r in novelty_df.iterrows()} if not novelty_df.empty else {}

    rows = []
    for uid, u in weekly_feats.sort_values("week_idx").groupby("user_id"):
        # synthesize the composite "_sensitivity" column for trend primitives
        sens = (u.get("file_restricted_ratio", 0).fillna(0)
                + u.get("file_confidential_ratio", 0).fillna(0)).values
        rec = {"uid": uid, "grp": grp_of.get(uid, "unknown"),
               "is_attack": bool(att_of.get(uid, False))}
        for name, col, how, _, _ in PRIMITIVES:
            series = sens if col == "_sensitivity" else (
                u[col].values if col in u.columns else np.zeros(len(u)))
            rec[name] = _agg(series, how)
        # volume-steady: file_total trend small relative to its early level (insider tell)
        ft = u["file_total"].values if "file_total" in u.columns else np.zeros(len(u))
        h = len(ft) // 2
        early_ft = float(np.mean(ft[:h])) if h else 0.0
        trend_ft = float(np.mean(ft[h:]) - early_ft) if h else 0.0
        rec["volume_steady"] = 1.0 if abs(trend_ft) < 0.15 * max(early_ft, 1.0) else 0.0
        # novelty primitive straight from novelty_metrics (already raw-derived)
        nr = nov.get(uid, {})
        rec["novel_ip_persistence"] = float(nr.get("novel_ip_max_persistence", 0) if len(nr) else 0)
        rec["_novel_frac"] = float(nr.get("novel_ip_weeks_frac", 0) if len(nr) else 0)
        rec["_persistent_novel"] = float(nr.get("persistent_novel_ips", 0) if len(nr) else 0)
        rows.append(rec)
    return pd.DataFrame(rows)


def _peer_bars(prim_tbl: pd.DataFrame, prim_cols: list[str]) -> dict:
    """For each (group, primitive): median + 90th pct over NORMAL peers."""
    bars = {}
    for grp in prim_tbl.grp.unique():
        normals = prim_tbl[(prim_tbl.grp == grp) & (~prim_tbl.is_attack)]
        for c in prim_cols:
            vals = normals[c].values
            med = float(np.median(vals)) if len(vals) else 0.0
            p90 = float(np.percentile(vals, 90)) if len(vals) else 0.0
            bars[(grp, c)] = (med, p90)
    return bars


def _fmt(value: float, kind: str) -> str:
    if kind == "pct":
        return f"{value*100:.1f}%"
    if kind == "ppt":
        return f"{value*100:+.1f} pts"
    return f"{value:.1f}"


def build_evidence_chain(uid: str,
                         weekly_feats: pd.DataFrame,
                         novelty_df: pd.DataFrame,
                         scores_df: pd.DataFrame,
                         prim_tbl: pd.DataFrame | None = None,
                         bars: dict | None = None) -> dict:
    """Return the full verdict -> primitives -> raw-weeks -> profile chain for one user."""
    fmt_of = {name: f for name, _, _, _, f in PRIMITIVES}
    label_of = {name: lbl for name, _, _, lbl, _ in PRIMITIVES}
    col_of = {name: col for name, col, _, _, _ in PRIMITIVES}
    label_of["volume_steady"] = "Data volume held steady (no bulk spike)"
    label_of["novel_ip_persistence"] = "Recurring never-before-seen external IP"
    col_of["volume_steady"] = "file_total"
    col_of["novel_ip_persistence"] = "qual_net_ext_ips"

    if prim_tbl is None:
        prim_tbl = build_primitive_table(weekly_feats, novelty_df, scores_df)
    prim_cols = [c for c in prim_tbl.columns
                 if c not in ("uid", "grp", "is_attack") and not c.startswith("_")]
    if bars is None:
        bars = _peer_bars(prim_tbl, [c for c in prim_cols if c not in
                                     ("volume_steady", "novel_ip_persistence")])

    prow = prim_tbl[prim_tbl.uid == uid].iloc[0]
    grp = prow.grp
    srow = scores_df[scores_df.uid == uid].iloc[0]
    rank = int(scores_df.reset_index(drop=True).index[scores_df.reset_index(drop=True).uid == uid][0]) + 1

    # which raw-log primitives fire (value clears the role-peer 90th percentile)
    fired = []
    for name in prim_cols:
        val = float(prow[name])
        if name == "volume_steady":
            continue  # contextual flag, only meaningful alongside sensitivity (added below)
        if name == "novel_ip_persistence":
            if val > 10 or prow["_novel_frac"] > 0.5:
                fired.append(_make_fire(uid, name, val, None, None, label_of, fmt_of,
                                        col_of, weekly_feats,
                                        extra=f"persists {int(val)} wks, "
                                              f"{prow['_novel_frac']*100:.0f}% of weeks"))
            continue
        med, p90 = bars.get((grp, name), (0.0, 0.0))
        bar = max(p90, med * 1.5, 1e-9)
        if val > bar and val > med:
            fired.append(_make_fire(uid, name, val, med, p90, label_of, fmt_of,
                                    col_of, weekly_feats))

    # volume_steady fires only as an insider corroborator (sensitivity also firing)
    sens_firing = any(f["name"] in ("restricted_access", "confidential_access",
                                    "sensitivity_escalation") for f in fired)
    if prow["volume_steady"] >= 1.0 and sens_firing:
        fired.append({"name": "volume_steady", "label": label_of["volume_steady"],
                      "value_str": "flat", "peer_str": "—", "severity": 0.5,
                      "raw_col": "file_total", "weeks": []})

    fired.sort(key=lambda f: f["severity"], reverse=True)

    # best-matching profile: severity-weighted, not a raw count. A single strong
    # anchor (e.g. novel-IP persistence for C2) must outweigh two weak corroborators.
    sev_of = {f["name"]: f["severity"] for f in fired}
    fired_names = set(sev_of)
    profile, coverage, best_weight = None, 0.0, 0.0
    matches = {}
    for pname, members in PROFILES.items():
        hit = fired_names & set(members)
        weight = sum(sev_of[n] for n in hit)
        matches[pname] = (len(hit), len(members), round(weight, 1), sorted(hit))
        # qualify on either 2+ corroborating primitives or one strong anchor —
        # a single weak primitive must not earn a profile label (FP guard).
        strong_anchor = max((sev_of[n] for n in hit), default=0.0) >= 2.5
        if hit and weight > best_weight and (len(hit) >= 2 or strong_anchor):
            profile, best_weight, coverage = pname, weight, len(hit) / len(members)

    # which detector phases carried the score (the abstraction side)
    phase_contrib = {
        "Signal strength": srow.signal_strength * 1.0,
        "Breadth": srow.breadth_15 * 0.5,
        "Sustained": srow.sustained_signal * 0.3,
        "Context divergence": max(srow.ctx_spread_z, 0) * 0.5 + max(srow.ctx_max_z, 0) * 0.3,
        "Novelty persistence": srow.novelty_score * 1.0,
    }
    top_phases = sorted(phase_contrib.items(), key=lambda x: x[1], reverse=True)

    return {
        "uid": uid,
        "rank": rank,
        "n_users": len(scores_df),
        "grp": grp,
        "role": srow.role,
        "composite": float(srow.composite),
        "is_attack": bool(srow.is_attack),
        "top_phases": top_phases,
        "fired": fired,
        "profile": profile,
        "profile_coverage": coverage,
        "profile_matches": matches,
    }


def _make_fire(uid, name, val, med, p90, label_of, fmt_of, col_of,
               weekly_feats, extra=None):
    kind = fmt_of.get(name, "num")
    raw_col = col_of.get(name)
    # severity = how far past the peer 90th, median-anchored (validated normalization)
    if med is not None and p90 is not None:
        rng = p90 - med
        sev = float(np.clip((val - med) / rng, 0, 5)) if rng > 1e-9 else 2.0
        peer_str = f"peer median {_fmt(med, kind)}, 90th {_fmt(p90, kind)}"
    else:
        sev = 3.0
        peer_str = extra or "—"
    # the weeks whose raw rows back this primitive (user's own top-quartile weeks)
    weeks = []
    if raw_col and raw_col in weekly_feats.columns:
        u = weekly_feats[weekly_feats.user_id == uid].sort_values("week_idx")
        if len(u):
            thr = u[raw_col].quantile(0.75)
            weeks = [int(w) for w in u[u[raw_col] >= thr]["week_idx"].tolist()[-4:]]
    return {"name": name, "label": label_of.get(name, name),
            "value_str": _fmt(val, kind), "peer_str": peer_str,
            "severity": sev, "raw_col": raw_col, "weeks": weeks,
            "extra": extra}


def _print_chain(c: dict):
    tag = f"  [{ATTACK_NAMES[c['uid']]}]" if c["uid"] in ATTACK_NAMES else ""
    print(f"\n{'='*78}")
    print(f"{c['uid']}{tag}  —  {c['role']} ({c['grp']})")
    print(f"  Verdict: composite {c['composite']:.2f}, rank #{c['rank']}/{c['n_users']}")
    tp = ", ".join(f"{n} {v:.1f}" for n, v in c["top_phases"][:3] if v > 0.1)
    print(f"  Detector drivers: {tp or 'none significant'}")
    if c["profile"]:
        print(f"  >> PROFILE: {c['profile']}  ({c['profile_coverage']*100:.0f}% of its primitives present)")
    else:
        print(f"  >> PROFILE: no co-occurrence match (<2 primitives)")
    if not c["fired"]:
        print("  Raw-log primitives fired: NONE  (clean — no peer-relative exceedance)")
        return
    print(f"  Raw-log primitives fired ({len(c['fired'])}):")
    for f in c["fired"]:
        wk = f" | weeks {f['weeks']}" if f["weeks"] else ""
        print(f"    - {f['label']}: {f['value_str']}  ({f['peer_str']})  "
              f"sev={f['severity']:.1f}{wk}")
        if f.get("raw_col"):
            print(f"        drill -> {f['raw_col']}")


def main():
    from pipeline.dashboard_db import (load_weekly_features, load_novelty_metrics,
                                       load_composite_scores)
    wf = load_weekly_features()
    nm = load_novelty_metrics()
    sc = load_composite_scores().reset_index(drop=True)
    print(f"Loaded {wf.user_id.nunique()} users, {len(sc)} scored.")

    prim = build_primitive_table(wf, nm, sc)
    prim_cols = [c for c in prim.columns if c not in ("uid", "grp", "is_attack")
                 and not c.startswith("_") and c not in ("volume_steady", "novel_ip_persistence")]
    bars = _peer_bars(prim, prim_cols)

    print("\n" + "#"*78 + "\n# ATTACKERS — evidence chains\n" + "#"*78)
    for uid in ATTACK_NAMES:
        if (sc.uid == uid).any():
            _print_chain(build_evidence_chain(uid, wf, nm, sc, prim, bars))

    # sanity: top-3 normals by composite should stay relatively quiet
    normals = sc[~sc.is_attack].head(3)
    print("\n" + "#"*78 + "\n# TOP-3 NORMALS — should fire few/coherent primitives\n" + "#"*78)
    for uid in normals.uid:
        _print_chain(build_evidence_chain(uid, wf, nm, sc, prim, bars))


if __name__ == "__main__":
    main()
