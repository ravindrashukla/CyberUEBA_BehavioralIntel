# -*- coding: utf-8 -*-
"""Embedding path for the evasive attacker (complete pipeline: serialize -> embed ->
compose -> cosine drift -> CUSUM). Answers: does the PRODUCT'S embedding drift also
catch EVA, the low-and-slow attacker the threat-profile detector missed?

Uses the real functions: serialize_zone_interpretive, Embedder (OpenAI text-embedding
-3-small, disk-cached), compose_zones (attention-weighted, identity excluded), cosine.
Weekly grain, all users through the identical computation -> apples-to-apples band.
Run scripts/evasive_experiment.py first (writes data/eva_features.csv).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
import numpy as np, pandas as pd
from pipeline.dashboard_db import load_weekly_features, load_composite_scores
from models.hierarchical_zones import serialize_zone_interpretive, BehavioralContext, compose_zones
from embeddings.embedder import Embedder
from embeddings.composer import cosine_similarity

DYN_ZONES = ["access_pattern", "data_behavior", "network_footprint", "risk_posture"]  # identity is static/excluded
PROFILE = {"role": "developer", "department": "engineering", "clearance": "standard",
           "tenure_days": 800, "user_type": "employee"}
ATT = ["USR-156", "USR-118", "USR-042", "USR-234"]

f = load_weekly_features()
grp = load_composite_scores().set_index("uid")["grp"].to_dict()
FC = [c for c in f.columns if c not in ["user_id", "week_idx", "week_start", "week_end"]]
weeks = sorted(int(w) for w in f.week_idx.unique())
eva = pd.read_csv("data/eva_features.csv")
pop_mean = f[FC].mean().to_dict()
pop_std = f[FC].std().replace(0, 1.0).to_dict()

norm_devs = [u for u in f.user_id.unique() if grp.get(u) == "developer" and u not in ATT][:10]
USERS = ["USR-EVA"] + norm_devs + ATT
src = {u: (eva if u == "USR-EVA" else f[f.user_id == u]).sort_values("week_idx") for u in USERS}

# ---- collect all zone texts, then batch-embed (disk cache dedups identical "normal" texts) ----
print("Serializing %d users x %d weeks x %d zones ..." % (len(USERS), len(weeks), len(DYN_ZONES)))
tasks = []  # (user, week, zone, text)
for u in USERS:
    ud = src[u]; n = len(ud)
    baseline = ud[FC].iloc[:n // 2].mean().to_dict()
    hist = []
    for _, row in ud.iterrows():
        feats = {c: float(row[c]) for c in FC}
        prof = dict(PROFILE, user_id=u)
        ctx = BehavioralContext(pop_mean=pop_mean, pop_std=pop_std, user_baseline=baseline,
                                week_idx=int(row["week_idx"]), recent_history=hist[-4:])
        for z in DYN_ZONES:
            tasks.append((u, int(row["week_idx"]), z, serialize_zone_interpretive("user", z, prof, feats, ctx)))
        hist.append(feats)

texts = [t for *_, t in tasks]
uniq = list(dict.fromkeys(texts))
print("  %d zone-texts, %d unique -> embedding (cache handles repeats) ..." % (len(texts), len(uniq)))
emb = Embedder()
vecs = emb.embed_batch(uniq)
tvec = {t: v for t, v in zip(uniq, vecs)}
print("  embedded (api_calls=%s, cache_hits=%s)" % (getattr(emb, "_api_calls", "?"), getattr(emb, "_cache_hits", "?")))

# ---- compose weekly composite vectors, then week-to-week cosine drift + CUSUM ----
zvec = {}  # (user,week) -> {zone: vec}
for (u, w, z, t) in tasks:
    zvec.setdefault((u, w), {})[z] = tvec[t]
CS_ww, CS_fb, COMPS = {}, {}, {}   # week-to-week vs from-baseline; keep composites for direction
for u in USERS:
    comps = [compose_zones(zvec[(u, w)], context="normal_ops", entity_type="user") for w in weeks]
    COMPS[u] = np.array(comps)
    base = np.mean(comps[:len(comps) // 2], axis=0)
    d_ww = [0.0] + [float(1.0 - cosine_similarity(comps[i], comps[i - 1])) for i in range(1, len(comps))]
    d_fb = [float(1.0 - cosine_similarity(comps[i], base)) for i in range(len(comps))]
    CS_ww[u] = pd.Series(np.cumsum(d_ww), index=weeks)
    CS_fb[u] = pd.Series(np.cumsum(d_fb), index=weeks)

def report(CS, label):
    band = pd.DataFrame({u: CS[u] for u in norm_devs}).T
    p95 = band.quantile(0.95)
    eva = CS["USR-EVA"]
    above = (eva.reindex(weeks) > p95.reindex(weeks)).values
    cross = next((weeks[i] for i in range(len(above)) if above[i] and above[i:i + 3].all()), None)
    print("\n=== EMBEDDING CUSUM - %s ===" % label)
    print("  normal band p95 (final):  %.3f     USR-EVA (final): %.3f" %
          (p95.reindex(weeks).iloc[-1], eva.reindex(weeks).iloc[-1]))
    print("  EVA vs real attackers (final): " + ", ".join("%s=%.2f" % (a, CS[a].reindex(weeks).iloc[-1]) for a in ATT))
    print("  first sustained crossing:  %s" % (("WEEK %d  -> EMBEDDING CATCHES" % cross) if cross is not None else "NEVER (misses)"))
    return cross, p95, eva

print("\nMeaning was created (text goes normal -> CRITICAL). Which drift metric sees it?")
c_ww, _, _ = report(CS_ww, "week-to-week (path length; penalizes smooth drift)")
c_fb, p95_fb, eva_fb = report(CS_fb, "from-baseline (distance from own normal, accumulated = your idea)")

print("\n=== VERDICT (embedding lens) ===")
print("  Threat-profile: SILENT.  Feature-CUSUM: CATCHES.")
print("  Embedding week-to-week:  %s" % ("CATCHES wk %d" % c_ww if c_ww else "misses (wrong metric for smooth low-and-slow)"))
print("  Embedding from-baseline: %s" % ("CATCHES wk %d -> meaning + right metric = embedding catches it too" % c_fb
                                         if c_fb else "still misses"))
cross, p95, eva_cs = c_fb, p95_fb, eva_fb   # for the chart below

# ============ CONCEPT-DIRECTION: what named threat is the meaning rotating toward? ============
from detection.reference_concepts import THREAT_CONCEPTS, BENIGN_CONCEPTS
concepts = THREAT_CONCEPTS + BENIGN_CONCEPTS
cvec = {c.name: emb.embed_text(c.description) for c in concepts}
cmeta = {c.name: c for c in concepts}
def direction(u):
    C = COMPS[u]; base = C[:len(C) // 2].mean(0); late = C[3 * len(C) // 4:].mean(0)
    dv = late - base
    return sorted(((float(cosine_similarity(dv, cvec[n])), n) for n in cvec), reverse=True)
print("\n=== CONCEPT-DIRECTION: what is the entity BECOMING? (drift vector projected onto named concepts) ===")
for u in ["USR-EVA", norm_devs[0], "USR-156"]:
    al = direction(u); s, n = al[0]; c = cmeta[n]
    tag = {"USR-EVA": "evasive insider", "USR-156": "real insider"}.get(u, "normal developer")
    print("  %-9s (%-16s) -> top: %-20s align=%.3f  [%s%s]"
          % (u, tag, n, s, c.category, ", MITRE " + ",".join(c.mitre_techniques[:2]) if c.category == "threat" else ""))
al = direction("USR-EVA"); top_threat = next(n for s, n in al if cmeta[n].category == "threat")
C = COMPS["USR-EVA"]; base = C[:len(C) // 2].mean(0)
dseries = [float(cosine_similarity(C[i] - base, cvec[top_threat])) for i in range(len(C))]
early = float(np.mean(dseries[:len(dseries) // 4])); late = float(np.mean(dseries[3 * len(dseries) // 4:]))
print("  EVA rotation toward '%s' (MITRE %s):  early=%.3f -> late=%.3f   GAP=%.3f"
      % (top_threat, ",".join(cmeta[top_threat].mitre_techniques[:2]), early, late, late - early))
print("  -> the behavior's MEANING moved from normal to '%s' - the gap + the named direction, not just magnitude" % top_threat)

try:
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4), dpi=140)
    a1.fill_between(weeks, 0, p95.reindex(weeks).values, color="#BDC3C7", alpha=0.4, label="Normal band (p95)")
    a1.plot(weeks, eva_cs.reindex(weeks).values, color="#1E8449", lw=2.6, label="USR-EVA")
    a1.set_title("Embedding from-baseline CUSUM", fontsize=9.5); a1.set_xlabel("Week"); a1.legend(fontsize=8)
    ndev_dir = [float(cosine_similarity(COMPS[norm_devs[0]][i] - COMPS[norm_devs[0]][:35].mean(0), cvec[top_threat])) for i in range(len(weeks))]
    a2.axhline(0, color="#999", lw=0.8)
    a2.plot(weeks, dseries, color="#C0392B", lw=2.4, label="USR-EVA -> %s" % top_threat)
    a2.plot(weeks, ndev_dir, color="#7F8C8D", lw=1.3, ls="--", label="normal developer")
    a2.set_title("Direction: rotation toward '%s' (MITRE %s)" % (top_threat, ",".join(cmeta[top_threat].mitre_techniques[:2])), fontsize=9.5)
    a2.set_xlabel("Week"); a2.set_ylabel("cosine(drift, threat concept)"); a2.legend(fontsize=8)
    fig.tight_layout(); fig.savefig("data/evasive_direction.png"); print("\nchart -> data/evasive_direction.png")
except Exception as e:
    print("chart skipped:", e)

try:
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8.4, 4.2), dpi=140)
    ax.fill_between(weeks, 0, p95.reindex(weeks).values, color="#BDC3C7", alpha=0.4, label="Normal band (p95)")
    ax.plot(weeks, eva_cs.reindex(weeks).values, color="#1E8449", lw=2.6, label="USR-EVA (embedding, from-baseline)")
    for a in ATT:
        ax.plot(weeks, CS_fb[a].reindex(weeks).values, lw=1, alpha=0.5, label=a)
    ax.set_title("Embedding from-baseline CUSUM: meaningful low-and-slow attacker clears the band", fontsize=9.5)
    ax.set_xlabel("Week"); ax.set_ylabel("Embedding-space CUSUM (cosine)"); ax.legend(fontsize=8); fig.tight_layout()
    fig.savefig("data/evasive_embedding.png"); print("\nchart -> data/evasive_embedding.png")
except Exception as e:
    print("chart skipped:", e)
