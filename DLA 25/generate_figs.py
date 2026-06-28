"""Render three analytics figures (3-up) for the 2-slide UEBA deck, from live DB:
  per_week_drift.png    — raw per-week drift; attackers mostly sit inside the normal
                          band (USR-234 in-band 97% of weeks) -> look like common users.
  cumulative_drift.png  — accumulate that signal; the 3 slow movers separate, APT stays flat.
  composite_score.png   — fused composite by rank; all 4 above the 'catch all 4' (=8% FP) line.
Run with DB env (DATABASE_URL_HOST / DB_HOST / DB_PORT) set.
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from pipeline.dashboard_db import load_weekly_trajectories, load_composite_scores

NAVY, BLUE, ORANGE, TEAL, RED, GREY, PURP = (
    '#102A4C', '#1F5E9C', '#F36C21', '#118484', '#B4262C', '#5E6A75', '#8A6FB0')
ATT = ['USR-156', 'USR-234', 'USR-042', 'USR-118']
STYLE = {  # label, color, linestyle
    'USR-156': ('USR-156 · insider',    ORANGE, '-'),
    'USR-118': ('USR-118 · recon',      RED,    '-'),
    'USR-042': ('USR-042 · LOTL',       TEAL,   '-'),
    'USR-234': ('USR-234 · APT (flat)', PURP,   '--'),
}
ORDER = ['USR-156', 'USR-118', 'USR-042', 'USR-234']
FIGSIZE = (4.35, 3.35)
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9,
                     'axes.edgecolor': '#CCCCCC', 'axes.linewidth': 0.8})


def _frame(ax, title, xlab, ylab):
    ax.set_title(title, color=NAVY, fontweight='bold', fontsize=12, loc='left', pad=7)
    ax.set_xlabel(xlab, color=GREY, fontsize=9); ax.set_ylabel(ylab, color=GREY, fontsize=9)
    ax.margins(x=0.01)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=GREY, labelsize=8)


def _save(fig, name):
    # Fixed figsize, no tight-bbox crop -> all three share one aspect ratio so they
    # align to equal height when placed side by side at a common width.
    fig.tight_layout(pad=0.6)
    fig.savefig(name, facecolor='white')
    plt.close(fig)


wt = load_weekly_trajectories()
piv = wt.pivot_table(index='week_idx', columns='user_id', values='composite_drift',
                     aggfunc='first').sort_index()
weeks = piv.index.values
normals = [c for c in piv.columns if c not in ATT]

# ---------- Figure 1: per-week (raw) drift ----------
lo, hi = piv[normals].quantile(0.10, axis=1), piv[normals].quantile(0.90, axis=1)
inband234 = float(((piv['USR-234'] >= lo) & (piv['USR-234'] <= hi)).mean() * 100)
fig, ax = plt.subplots(figsize=FIGSIZE, dpi=200)
ax.fill_between(weeks, lo, hi, color=GREY, alpha=0.20, lw=0, label='Normal range (P10–P90)')
for u in ORDER:
    lab, col, ls = STYLE[u]
    ax.plot(weeks, piv[u].values, ls, color=col, lw=1.4, alpha=0.95, label=lab)
_frame(ax, 'Per-week drift (not accumulated)', 'Week', 'Weekly drift')
ax.text(0.50, 0.06, 'USR-234 stays in the normal range %.0f%% of weeks' % inband234,
        transform=ax.transAxes, color=PURP, fontsize=8, fontweight='bold')
ax.legend(loc='upper left', fontsize=7, frameon=False)
_save(fig, 'per_week_drift.png')

# ---------- Figure 2: cumulative drift ----------
cum = piv.cumsum()
clo, chi = cum[normals].quantile(0.10, axis=1), cum[normals].quantile(0.90, axis=1)
fig, ax = plt.subplots(figsize=FIGSIZE, dpi=200)
ax.fill_between(weeks, clo, chi, color=GREY, alpha=0.20, lw=0, label='Normal range (P10–P90)')
for u in ORDER:
    lab, col, ls = STYLE[u]
    ax.plot(weeks, cum[u].values, ls, color=col, lw=2.1, label=lab)
_frame(ax, 'Cumulative behavioral drift', 'Week', 'Cumulative drift')
ax.legend(loc='upper left', fontsize=7, frameon=False)
_save(fig, 'cumulative_drift.png')

# ---------- Figure 3: composite score by rank ----------
cs = load_composite_scores().sort_values('composite', ascending=False).reset_index(drop=True)
cs['rank'] = cs.index + 1
thr = float(cs[cs.uid.isin(ATT)].composite.min())
n_norm = int((~cs.uid.isin(ATT)).sum())
fp = 100.0 * int((cs[~cs.uid.isin(ATT)].composite >= thr).sum()) / n_norm
fig, ax = plt.subplots(figsize=FIGSIZE, dpi=200)
norm = cs[~cs.uid.isin(ATT)]
ax.bar(norm['rank'], norm['composite'], width=1.0, color=GREY, alpha=0.30, label='250 users')
ax.axhline(thr, color=BLUE, ls='--', lw=1.4)
ax.text(len(cs) * 0.40, thr + 2.6, 'Catch all 4 → %.0f%% false positives' % fp,
        color=BLUE, fontsize=8, fontweight='bold')
for u in ATT:
    row = cs[cs.uid == u].iloc[0]; _, col, _ = STYLE[u]
    ax.scatter([row['rank']], [row['composite']], color=col, s=42, zorder=5, edgecolor='white', lw=0.8)
    ax.annotate('%s #%d' % (u, int(row['rank'])), (row['rank'], row['composite']),
                textcoords='offset points', xytext=(7, 2), color=col, fontsize=8, fontweight='bold')
_frame(ax, 'Composite score (all fronts fused)', 'User rank (1 = highest risk)', 'Composite score')
ax.legend(loc='upper right', fontsize=7, frameon=False)
_save(fig, 'composite_score.png')

print('wrote per_week_drift.png, cumulative_drift.png, composite_score.png | '
      'USR-234 in-band=%.0f%%  thr=%.1f  FP=%.0f%%' % (inband234, thr, fp))
