"""Crisp, deck-styled recreations of the app's two signature views (+ composite),
from live DB data, for the standalone UEBA explainer deck.
Formulas mirror streamlit_app.py exactly:
  feature CUSUM  = cumsum(max(mean|z vs first-half baseline| - 0.5, 0))   (compute_feature_drift)
  embedding CUSUM= cumsum(composite_drift)                                 (load_real_drift)
  radar          = median-anchored min-max of 5 phase columns             (5-Phase Percentile)
Run with DB env (DATABASE_URL_HOST / DB_HOST / DB_PORT) set.
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from pipeline.dashboard_db import load_weekly_features, load_weekly_trajectories, load_composite_scores

NAVY, GREY = '#0D1B2A', '#5E6A75'
ATT = ['USR-156', 'USR-234', 'USR-042', 'USR-118']
COLOR = {'USR-156': '#C0392B', 'USR-234': '#E67E22', 'USR-042': '#8E44AD', 'USR-118': '#2980B9'}
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9,
                     'axes.edgecolor': '#CCCCCC', 'axes.linewidth': 0.8})


def _cusum_panel(drift, weeks, normals, title, subtitle, sub_color, fname):
    p05 = drift[normals].quantile(0.05, axis=1).values
    p95 = drift[normals].quantile(0.95, axis=1).values
    fig, ax = plt.subplots(figsize=(5.6, 3.5), dpi=200)
    ax.fill_between(weeks, p05, p95, color='#BDC3C7', alpha=0.35, lw=0, label='Normal range (5–95%)')
    crossings = {}
    for u in ATT:
        s = drift[u].values
        ax.plot(weeks, s, '-', color=COLOR[u], lw=2.3, label=u)
        above = s > p95
        cw = None
        for i in range(len(above)):
            if above[i] and above[i:i + 3].all():
                cw = weeks[i]; break
        crossings[u] = cw
        if cw is not None:
            ax.scatter([cw], [s[list(weeks).index(cw)]], marker='*', s=190,
                       color=COLOR[u], edgecolor='white', lw=0.8, zorder=6)
    ax.set_title(title, color=NAVY, fontweight='bold', fontsize=12.5, loc='left', pad=20)
    ax.text(0.0, 1.02, subtitle, transform=ax.transAxes, color=sub_color,
            fontsize=8.5, fontweight='bold')
    ax.set_xlabel('Week (Jan 2025 – Apr 2026)', color=GREY); ax.set_ylabel('Cumulative drift (CUSUM)', color=GREY)
    ax.margins(x=0.01)
    for sp in ('top', 'right'):
        ax.spines[sp].set_visible(False)
    ax.tick_params(colors=GREY, labelsize=8)
    ax.legend(loc='upper left', fontsize=7.5, frameon=False)
    fig.tight_layout(pad=0.7)
    fig.savefig(fname, facecolor='white'); plt.close(fig)
    return crossings


# ---- dual-lens CUSUM ----
wf = load_weekly_features()
FCOLS = [c for c in wf.columns if c not in ['user_id', 'week_idx', 'week_start', 'week_end']]
feat = {}
for u in wf.user_id.unique():
    uw = wf[wf.user_id == u].sort_values('week_idx'); X = uw[FCOLS].fillna(0).values; n = len(X)
    bm, bs = X[:n // 2].mean(0), X[:n // 2].std(0); bs[bs == 0] = 1.0
    wd = np.abs((X - bm) / bs).mean(1)
    feat[u] = np.insert(np.cumsum(np.maximum(wd[1:] - 0.5, 0)), 0, 0.0)
import pandas as pd
weeks_f = np.array(sorted(wf.week_idx.unique()))
featdf = pd.DataFrame(feat, index=weeks_f)
normals = [u for u in wf.user_id.unique() if u not in ATT]
cf = _cusum_panel(featdf, weeks_f, normals,
                  'Feature-Space CUSUM', 'Raw magnitude — first to flag the high-volume attack',
                  '#C0392B', 'feature_cusum.png')

wt = load_weekly_trajectories()
piv = wt.pivot_table(index='week_idx', columns='user_id', values='composite_drift', aggfunc='first').sort_index()
weeks_a = piv.index.values
embdf = piv.cumsum()
ca = _cusum_panel(embdf, weeks_a, [c for c in embdf.columns if c not in ATT],
                  'V-Intelligence Embedding Drift', 'AI “meaning” — flags subtle attacks ~30 weeks earlier',
                  '#1E8449', 'embedding_cusum.png')

# ---- radar (5-phase percentile, median-anchored) ----
cs = load_composite_scores()
PCOLS = ['signal_strength', 'breadth_15', 'sustained_signal', 'ctx_max_z', 'novelty_score']
PLAB = ['Signal\nStrength', 'Breadth', 'Sustained\nDeviation', 'Context\nDivergence', 'Novelty\nPersistence']
cn = cs[~cs.uid.isin(ATT)]
med = {c: float(np.median(cn[c].values)) for c in PCOLS}
top = {c: float(cs[c].max()) for c in PCOLS}


def mm(val, c):
    rng = top[c] - med[c]
    return 0.0 if rng <= 1e-9 else 100.0 * max(0.0, (val - med[c]) / rng)


ang = np.linspace(0, 2 * np.pi, 5, endpoint=False).tolist(); ang += ang[:1]
fig = plt.figure(figsize=(5.7, 5.0), dpi=200)
ax = plt.subplot(polar=True)
ax.set_theta_offset(np.pi / 2); ax.set_theta_direction(-1)


def radar_plot(vals, color, lw, ls, fillalpha, label):
    v = vals + vals[:1]
    ax.plot(ang, v, ls, color=color, lw=lw, label=label)
    if fillalpha:
        ax.fill(ang, v, color=color, alpha=fillalpha)


radar_plot([mm(float(cn[c].median()), c) for c in PCOLS], '#BDC3C7', 2, '--', 0.12, 'Normal median')
radar_plot([mm(float(cn[c].quantile(0.75)), c) for c in PCOLS], '#95A5A6', 1.5, ':', 0.06, 'Normal 75th pct')
for u in ATT:
    r = cs[cs.uid == u].iloc[0]
    radar_plot([mm(float(r[c]), c) for c in PCOLS], COLOR[u], 2.3, '-', 0.04, u)
ax.set_xticks(ang[:-1]); ax.set_xticklabels(PLAB, fontsize=9, color=NAVY)
ax.set_ylim(0, 100); ax.set_yticks([0, 50, 100])
ax.set_yticklabels(['Normal\nmedian', 'halfway', 'Most\nextreme'], fontsize=7, color=GREY)
ax.tick_params(pad=6)
ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.06), ncol=3, fontsize=8, frameon=False)
fig.tight_layout(pad=0.6)
fig.savefig('radar.png', facecolor='white'); plt.close(fig)

# ---- composite by rank (app colors) ----
csr = cs.sort_values('composite', ascending=False).reset_index(drop=True); csr['rank'] = csr.index + 1
thr = float(csr[csr.uid.isin(ATT)].composite.min())
fp = 100.0 * int((csr[~csr.uid.isin(ATT)].composite >= thr).sum()) / int((~csr.uid.isin(ATT)).sum())
fig, ax = plt.subplots(figsize=(6.0, 3.6), dpi=200)
nrm = csr[~csr.uid.isin(ATT)]
ax.bar(nrm['rank'], nrm['composite'], width=1.0, color=GREY, alpha=0.30, label='250 users')
ax.axhline(thr, color='#1B4F72', ls='--', lw=1.4)
ax.text(len(csr) * 0.40, thr + 2.6, 'Catch all 4 → %.0f%% false positives' % fp,
        color='#1B4F72', fontsize=8.5, fontweight='bold')
for u in ATT:
    r = csr[csr.uid == u].iloc[0]
    ax.scatter([r['rank']], [r['composite']], color=COLOR[u], s=46, zorder=5, edgecolor='white', lw=0.8)
    ax.annotate('%s #%d' % (u, int(r['rank'])), (r['rank'], r['composite']),
                textcoords='offset points', xytext=(7, 2), color=COLOR[u], fontsize=8.5, fontweight='bold')
ax.set_title('Composite score (all 5 phases fused)', color=NAVY, fontweight='bold', fontsize=12.5, loc='left', pad=8)
ax.set_xlabel('User rank (1 = highest risk)', color=GREY); ax.set_ylabel('Composite score', color=GREY)
ax.margins(x=0.01)
for sp in ('top', 'right'):
    ax.spines[sp].set_visible(False)
ax.tick_params(colors=GREY, labelsize=8)
ax.legend(loc='upper right', fontsize=8, frameon=False)
fig.tight_layout(pad=0.7)
fig.savefig('composite_rank.png', facecolor='white'); plt.close(fig)

print('feature crossings:', cf)
print('embedding crossings:', ca)
print('composite thr=%.1f FP=%.0f%%' % (thr, fp))
print('wrote feature_cusum.png, embedding_cusum.png, radar.png, composite_rank.png')
