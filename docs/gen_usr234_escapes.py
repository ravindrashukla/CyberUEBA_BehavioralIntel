"""USR-234 (slow APT) escapes BOTH drift lenses — for the layered demo video.
Left: Feature-Space CUSUM (raw magnitude). Right: V-Intelligence Semantic CUSUM
(embedding drift). USR-234 (orange) never separates from the normal pack on either
lens -> motivates the multi-front threat-profile detector. Run with DB env set.
Writes docs/screenshots/usr234_escapes.png.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pipeline.dashboard_db import load_weekly_features, load_weekly_trajectories

NAVY, GREY, ORANGE, RED, GREEN = "#0D1B2A", "#BBBBBB", "#E67E22", "#C0392B", "#1E8449"
ATT = ["USR-156", "USR-234", "USR-042", "USR-118"]
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": "#CCCCCC", "axes.linewidth": 0.8})

# Feature-space CUSUM (validated formula = streamlit_app.compute_feature_drift)
wf = load_weekly_features()
FCOLS = [c for c in wf.columns if c not in ["user_id", "week_idx", "week_start", "week_end"]]
weeks = np.array(sorted(wf.week_idx.unique()))
feat = {}
for u in wf.user_id.unique():
    uw = wf[wf.user_id == u].sort_values("week_idx"); X = uw[FCOLS].fillna(0).values; n = len(X)
    bm, bs = X[:n // 2].mean(0), X[:n // 2].std(0); bs[bs == 0] = 1.0
    wd = np.abs((X - bm) / bs).mean(1)
    feat[u] = np.insert(np.cumsum(np.maximum(wd[1:] - 0.5, 0)), 0, 0.0)

# Semantic / embedding CUSUM = cumsum(composite_drift)
wt = load_weekly_trajectories()
piv = wt.pivot_table(index="week_idx", columns="user_id", values="composite_drift", aggfunc="first").sort_index()
sem = piv.cumsum()
sweeks = sem.index.values

normals = [u for u in wf.user_id.unique() if u not in ATT]
fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 5.2), dpi=170)

# Left — feature CUSUM
for u in normals:
    axL.plot(weeks, feat[u], color=GREY, lw=0.7, alpha=0.30, zorder=1)
axL.plot(weeks, feat["USR-234"], color=ORANGE, lw=3.0, marker="o", ms=3.5, zorder=5, label="USR-234 (ATTACK)")
axL.set_title("Feature-Space CUSUM  —  raw magnitude (too noisy to use)", color=RED, fontsize=13, fontweight="bold", loc="left", pad=10)
axL.set_xlabel("Week", color=GREY); axL.set_ylabel("Cumulative drift (CUSUM)", color=GREY)
axL.legend(loc="upper left", frameon=False, fontsize=10)

# Right — semantic CUSUM
for u in [c for c in sem.columns if c not in ATT]:
    axR.plot(sweeks, sem[u].values, color=GREY, lw=0.7, alpha=0.30, zorder=1)
axR.plot(sweeks, sem["USR-234"].values, color=ORANGE, lw=3.0, marker="o", ms=3.5, zorder=5, label="USR-234 (ATTACK)")
axR.set_title("V-Intelligence Semantic CUSUM  —  embedding drift", color=GREEN, fontsize=13, fontweight="bold", loc="left", pad=10)
axR.set_xlabel("Week", color=GREY); axR.set_ylabel("Semantic drift (CUSUM)", color=GREY)
axR.legend(loc="upper left", frameon=False, fontsize=10)

for ax in (axL, axR):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=GREY); ax.margins(x=0.01)

fig.suptitle("The Hard Case — USR-234 (slow APT) never separates on either drift lens",
             color=NAVY, fontsize=15, fontweight="bold", y=0.99)
fig.text(0.5, 0.015,
         "Neither feature nor embedding CUSUM separates this attacker — it needs the multi-front threat-profile detector.",
         ha="center", color=ORANGE, fontsize=12.5, fontweight="bold")
fig.tight_layout(rect=[0, 0.05, 1, 0.94])
fig.savefig("docs/screenshots/usr234_escapes.png", facecolor="white")
print("wrote docs/screenshots/usr234_escapes.png", fig.get_size_inches())
