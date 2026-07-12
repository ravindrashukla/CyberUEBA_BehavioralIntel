# -*- coding: utf-8 -*-
"""Evasive low-and-slow attacker: caught by TEMPORAL feature-CUSUM, missed by the
point-in-time threat-profile detector. Pure feature space (no embeddings).

Faithful construction: take a REAL normal developer's actual 70-week telemetry
(real week-to-week variability) and inject a gradual sustained drift on top, scaled
so every feature's settled robust-z stays < 4.5 (front_A silent) with no beacon/DGA
(front_B silent) - yet the self-referential CUSUM accumulates past the normal band.
Includes skeptic diagnostics: normal-user robust-z ceiling, baseline realism, and
EVA vs the 4 real attackers.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from pipeline.dashboard_db import load_weekly_features, load_composite_scores

rng = np.random.default_rng(7)
COHORT_THR = 4.5
GROUP = "developer"
RAMP_START, RAMP_END = 35, 55
# Coherent INSIDER story, built on features that CARRY MEANING in the serialization.
# Per-feature settled cohort-robust-z target (all < 4.5 so the profile stays silent),
# chosen high on the meaningful ratios so their POPULATION-z clears ~1.5 -> the prose
# flips to anomaly language -> the embedding gets a fair chance to drift.
RAMP_Z = {
    "file_confidential_ratio": 4.0,   # quietly collecting confidential material  (meaning: data staging)
    "file_restricted_ratio": 2.6,     # a little restricted too (kept low so insider_collection AND stays < 4.5)
    "auth_off_hours_ratio": 4.0,      # drifting to off-hours                       (meaning: after-hours access)
    "endpoint_suspicious_ratio": 3.6, # touching riskier tools                      (meaning: risk posture)
    "net_external_ratio": 3.6,        # more external egress                        (meaning: network footprint)
    "file_total": 3.2, "file_unique_paths": 3.2,   # more files (breadth), still < 4.5
    "net_unique_dsts": 3.0, "endpoint_unique_processes": 3.0, "endpoint_total": 3.0,
}
RAMP = list(RAMP_Z)

f = load_weekly_features()
grp = load_composite_scores().set_index("uid")["grp"].to_dict()
FC = [c for c in f.columns if c not in ["user_id", "week_idx", "week_start", "week_end"]]
weeks = sorted(int(w) for w in f.week_idx.unique()); NW = len(weeks)
ATT = {"USR-156", "USR-234", "USR-042", "USR-118"}
gstd = f[FC].std(ddof=0).replace(0, 1e-9)

def settled_frame(df):
    L = {}
    for u in df.user_id.unique():
        ud = df[df.user_id == u].sort_values("week_idx"); n = len(ud)
        L[u] = ud[FC].iloc[3 * n // 4:].mean()
    L = pd.DataFrame(L).T; L["grp"] = [grp.get(u, "?") for u in L.index]; return L
L = settled_frame(f)
gIQR = {c: max(L[c].quantile(.75) - L[c].quantile(.25), 1e-9) for c in FC}
devs = L[L.grp == GROUP]
dev_med = devs[FC].median()
denom = {c: max(devs[c].quantile(.75) - devs[c].quantile(.25), 0.25 * gIQR[c]) for c in FC}
def robz(vec):  # robust-z of a settled feature vector vs developer peers
    return {c: (vec[c] - dev_med[c]) / denom[c] for c in FC}

# ---- pick a real, typical normal developer as the host ----
norm_devs = [u for u in devs.index if u not in ATT]
host = min(norm_devs, key=lambda u: float(np.mean([abs(robz(L.loc[u])[c]) for c in RAMP])))
host_w = f[f.user_id == host].sort_values("week_idx").set_index("week_idx")
host_settled = L.loc[host]
plateau = {c: (dev_med[c] + RAMP_Z[c] * denom[c]) - host_settled[c] for c in RAMP}

# ---- craft USR-EVA = host telemetry + injected sustained ramp ----
rows = []
for w in weeks:
    frac = 0.0 if w < RAMP_START else (1.0 if w >= RAMP_END else (w - RAMP_START) / (RAMP_END - RAMP_START))
    row = {"user_id": "USR-EVA", "week_idx": w}
    for c in FC:
        v = float(host_w.loc[w, c]) if w in host_w.index else float(host_settled[c])
        if c in RAMP: v += frac * plateau[c]
        if c.endswith("_ratio"): v = min(max(v, 0.0), 0.95)
        row[c] = max(v, 0.0)
    rows.append(row)
eva = pd.DataFrame(rows)

print("HOST (real normal developer): %s   |   injected features: %d of 23" % (host, len(RAMP)))
eva.to_csv("data/eva_features.csv", index=False)   # shared with the embedding run

# ================= DETECTOR 1: threat-profile (point-in-time, vs peers) =================
eva_settled = eva.sort_values("week_idx")[FC].iloc[3 * NW // 4:].mean()
z_eva = robz(eva_settled)
eva_early = eva.sort_values("week_idx")[FC].iloc[:NW // 4].mean(); z_early = robz(eva_early)
PROFILES = {
    "insider_collection": ["file_restricted_ratio", "file_confidential_ratio"],
    "mass_collection": ["file_unique_paths", "file_total"], "ransomware": ["file_write_ratio", "file_total"],
    "recon_fanout": ["net_unique_dsts"], "dns_malicious": ["dns_nxdomain_ratio", "dns_unique_domains"],
    "lotl_process": ["endpoint_unique_processes", "endpoint_total"],
    "highrisk_endpoint": ["endpoint_suspicious_ratio", "endpoint_max_risk"],
    "brute_force": ["auth_failed", "auth_fail_rate"], "lateral_movement": ["auth_unique_dests"],
    "off_hours_auth": ["auth_off_hours_ratio"], "auth_source_spray": ["auth_unique_sources"],
}
fired = [(n, min(z_eva[c] for c in fs)) for n, fs in PROFILES.items() if min(z_eva[c] for c in fs) >= COHORT_THR]
print("\n=== DETECTOR 1: THREAT-PROFILE (cohort robust-z, fire >= %.1f) ===" % COHORT_THR)
print("  EVA early-weeks max robust-z:  %.2f  (looks normal at the start)" % max(z_early.values()))
print("  EVA settled  max robust-z:     %.2f  on '%s'  (below 4.5)" % (max(z_eva.values()), max(z_eva, key=z_eva.get)))
print("  profiles fired: %s" % (fired or "NONE  ->  THREAT-PROFILE IS SILENT"))
# skeptic check: is EVA inside the normal-looking zone? compare to normal devs' max robust-z
nz = sorted(max(abs(v) for v in robz(L.loc[u]).values()) for u in norm_devs)
print("  normal developers' max robust-z ceiling:  p50=%.1f  p90=%.1f  p99=%.1f  max=%.1f"
      % (np.percentile(nz, 50), np.percentile(nz, 90), np.percentile(nz, 99), max(nz)))
print("  -> a threshold low enough to catch EVA (%.1f) would fire on normal users up to %.1f = false positives"
      % (max(z_eva.values()), max(nz)))
# MEANING check: population-z of the story features (>=1.5 flips the serialization to anomaly language)
pop_mean = f[FC].mean(); pop_std = f[FC].std().replace(0, 1.0)
pz = {c: (eva_settled[c] - pop_mean[c]) / pop_std[c] for c in FC}
print("  MEANING check (population-z of the insider-story features; >=1.5 flips the prose, still cohort-z<4.5):")
for c in ["file_confidential_ratio", "auth_off_hours_ratio", "endpoint_suspicious_ratio",
          "net_external_ratio", "file_restricted_ratio"]:
    print("     %-26s pop-z=%.2f   cohort-robust-z=%.2f" % (c, pz[c], z_eva[c]))
# show the serialized text actually drifting (meaning created), grain-independent
from models.hierarchical_zones import serialize_zone_interpretive, BehavioralContext
_prof = {"user_id": "USR-EVA", "role": "developer", "department": "engineering",
         "clearance": "standard", "tenure_days": 800, "user_type": "employee"}
_bl = eva.sort_values("week_idx")[FC].iloc[:NW // 2].mean().to_dict()
def _ztext(wk, zone):
    row = eva[eva.week_idx == wk].iloc[0]; feats = {c: float(row[c]) for c in FC}
    ctx = BehavioralContext(pop_mean=pop_mean.to_dict(), pop_std=pop_std.to_dict(),
                            user_baseline=_bl, week_idx=wk, recent_history=[])
    return serialize_zone_interpretive("user", zone, _prof, feats, ctx)
print("\n=== MEANING CREATED (the serialized text the embedding sees, drifting over time) ===")
for zone in ["data_behavior", "access_pattern"]:
    print("  [%s] wk08:" % zone, _ztext(8, zone)[:160])
    print("  [%s] wk62:" % zone, _ztext(62, zone)[:160])

# ================= DETECTOR 2: feature-space CUSUM (temporal, vs own baseline) =================
def feat_cusum(df):
    out = {}
    for uid in df.user_id.unique():
        uw = df[df.user_id == uid].sort_values("week_idx"); X = uw[FC].fillna(0).values; n = len(X)
        bm, bs = X[:n // 2].mean(0), X[:n // 2].std(0); bs[bs == 0] = 1.0
        wd = np.abs((X - bm) / bs).mean(1)
        out[uid] = pd.Series(np.insert(np.cumsum(np.maximum(wd[1:] - 0.5, 0)), 0, 0.0),
                             index=[int(w) for w in uw.week_idx])
    return out
CS = feat_cusum(pd.concat([f, eva], ignore_index=True))
normal_ids = [u for u in f.user_id.unique() if u not in ATT]
band = pd.DataFrame({u: CS[u] for u in normal_ids}).T
p95 = band.quantile(0.95); p50 = band.median()
eva_cs = CS["USR-EVA"]
above = (eva_cs.reindex(weeks) > p95.reindex(weeks)).values
cross = next((weeks[i] for i in range(len(above)) if above[i] and above[i:i + 3].all()), None)
print("\n=== DETECTOR 2: FEATURE-SPACE CUSUM (temporal, vs own baseline) ===")
print("  normal band p95 (final week):  %.1f" % p95.reindex(weeks).iloc[-1])
print("  USR-EVA CUSUM   (final week):   %.1f" % eva_cs.reindex(weeks).iloc[-1])
print("  first sustained crossing:  %s" % (("WEEK %d" % cross) if cross is not None else "NEVER"))
# skeptic check: baseline realism (EVA first-half variability vs real devs) + EVA vs real attackers
def cv_firsthalf(uid, df):
    uw = df[df.user_id == uid].sort_values("week_idx")[FC].values; h = uw[:len(uw)//2]
    m = h.mean(0); s = h.std(0); return float(np.median(s[m > 0] / m[m > 0]))
print("  baseline realism: EVA first-half CV=%.2f  vs  normal-dev median CV=%.2f (similar = not a tight-baseline artifact)"
      % (cv_firsthalf("USR-EVA", pd.concat([f, eva], ignore_index=True)),
         float(np.median([cv_firsthalf(u, f) for u in norm_devs]))))
print("  EVA final CUSUM vs real attackers: " + ", ".join(
    "%s=%.0f" % (a, CS[a].reindex(weeks).iloc[-1]) for a in ["USR-156", "USR-118", "USR-042", "USR-234"])
    + "  | EVA=%.0f" % eva_cs.reindex(weeks).iloc[-1])

print("\n=== HEAD-TO-HEAD ===")
print("  Threat-profile comparison:  %s" % ("CAUGHT %s" % fired if fired else "NORMAL / SILENT"))
print("  Temporal feature-CUSUM:     %s" % (("CAUGHT at week %d" % cross) if cross is not None else "MISSED"))

# ---- export for the app demo page ----
import json
demo = {
    "weeks": weeks, "host": host,
    "profile": {
        "max_cohort_z": round(max(z_eva.values()), 2), "fire_line": COHORT_THR,
        "silent": len(fired) == 0,
        "normal_p90": round(float(np.percentile(nz, 90)), 1),
        "story_features": [{"name": c, "pop_z": round(pz[c], 2), "cohort_z": round(z_eva[c], 2)}
                           for c in ["file_confidential_ratio", "file_restricted_ratio",
                                     "auth_off_hours_ratio", "net_external_ratio", "endpoint_suspicious_ratio"]],
    },
    "feature_cusum": {
        "eva": [round(float(eva_cs.get(w, 0)), 2) for w in weeks],
        "band_p95": [round(float(p95.get(w, 0)), 2) for w in weeks],
        "cross_week": cross,
        "eva_final": round(float(eva_cs.reindex(weeks).iloc[-1]), 1),
        "band_final": round(float(p95.reindex(weeks).iloc[-1]), 1),
        "attackers": {a: {"series": [round(float(CS[a].get(w, 0)), 2) for w in weeks],
                          "final": round(float(CS[a].reindex(weeks).iloc[-1]), 1)}
                      for a in ["USR-156", "USR-118", "USR-042", "USR-234"]},
    },
    "text_evolution": {z: {"early": _ztext(8, z), "late": _ztext(62, z)}
                       for z in ["data_behavior", "access_pattern"]},
}
json.dump(demo, open("data/evasive_demo_features.json", "w"), indent=1)
print("wrote data/evasive_demo_features.json")

try:
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8.4, 4.2), dpi=140)
    ax.fill_between(weeks, 0, p95.reindex(weeks).values, color="#BDC3C7", alpha=0.4, label="Normal band (p95)")
    ax.plot(weeks, p50.reindex(weeks).values, "--", color="#7F8C8D", lw=1, label="Normal median")
    ax.plot(weeks, eva_cs.reindex(weeks).values, color="#C0392B", lw=2.6, label="USR-EVA (low-and-slow)")
    if cross is not None:
        ax.scatter([cross], [eva_cs.get(cross)], color="#C0392B", s=110, marker="*", zorder=5, label="caught wk %d" % cross)
    ax.set_title("Temporal CUSUM catches the low-and-slow attacker the threat-profile misses\n"
                 "(every feature's robust-z peaks at %.1f, below the 4.5 fire line -> profile silent)" % max(z_eva.values()),
                 fontsize=9.5)
    ax.set_xlabel("Week"); ax.set_ylabel("Feature-space CUSUM"); ax.legend(fontsize=8); fig.tight_layout()
    fig.savefig("data/evasive_experiment.png"); print("\nchart -> data/evasive_experiment.png")
except Exception as e:
    print("chart skipped:", e)
