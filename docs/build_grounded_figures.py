"""Rebuild the four stale Word-doc figures (4, 10, 1, 11) as clean wide-banner graphics
with GROUNDED numbers and 'pilot' terminology, matching the document palette and the
~2.7:1 banner aspect of the originals.

Grounded sources:
  demand worked example  379 -> 225 P90, 154 fewer, ~$460K  (results_data_v2.json)
  held-out benchmark     EDM WAPE 0.78 vs Legacy 0.95        (s9_variety.json, TRACK SHOE)
  calibration            ECE 0.0322 (Grade A)
  supplier risk          qualitative (no AUC / C-index)
  cyber                  4/4 @ 8.1% FP, traditional 0-1/4
"""
import os, textwrap
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrow, Circle

OUT = "docs"
NAVY = '#1F3864'; BLUE = '#2E75B6'; TEAL = '#1F8A70'; AMBER = '#C55A11'
LBLUE = '#E8F0F9'; LTEAL = '#E2F2EE'; LAMBER = '#FBEEE2'; GRAY = '#EDEFF2'
INK = '#222a31'; SUB = '#555f6b'; WHITE = 'white'
plt.rcParams.update({'font.family': 'sans-serif', 'font.sans-serif': ['Segoe UI', 'Arial', 'DejaVu Sans']})


def new_fig(h_in):
    fig = plt.figure(figsize=(13.0, h_in), dpi=120)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis('off')
    return fig, ax


def rbox(ax, x, y, w, h, fc, ec='none', lw=1.2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0,rounding_size=1.6',
                                fc=fc, ec=ec, lw=lw, mutation_aspect=0.5))


def title(ax, text, y=91):
    ax.text(2, y, text, fontsize=21, fontweight='bold', color=NAVY, va='center')


def card(ax, x, w, ytop, ybot, head, headcolor, headfill, items, body_fs=11.5):
    rbox(ax, x, ybot, w, ytop - ybot, '#FFFFFF', ec='#D6DEE6', lw=1.1)
    rbox(ax, x, ytop - 8, w, 8, headfill)
    ax.text(x + w / 2, ytop - 4, head, ha='center', va='center', fontsize=13, fontweight='bold', color=headcolor)
    yy = ytop - 13
    for it in items:
        ax.text(x + 2.2, yy, '•', fontsize=12, color=headcolor, va='top')
        ax.text(x + 4.6, yy, it, fontsize=body_fs, color=INK, va='top', wrap=True)
        yy -= 8.5


def arrow(ax, x, y):
    ax.add_patch(FancyArrow(x, y, 3.2, 0, width=0.8, head_width=3.2, head_length=1.6,
                            length_includes_head=True, fc=BLUE, ec='none'))


def bottom_bar(ax, segments, fill=NAVY, label=None, y=4, h=16, seg_fs=12.5):
    rbox(ax, 2, y, 96, h, fill)
    txt = '       ·       '.join(segments)
    if label:
        ax.text(50, y + h * 0.66, label.rstrip(':'), ha='center', va='center',
                fontsize=12.5, fontweight='bold', color='#FFD9A8')
        ax.text(50, y + h * 0.30, txt, ha='center', va='center', fontsize=seg_fs, color=WHITE)
    else:
        ax.text(50, y + h / 2, txt, ha='center', va='center', fontsize=seg_fs, color=WHITE)


def step(ax, x, w, ytop, ybot, num, head, body, color, fill):
    rbox(ax, x, ybot, w, ytop - ybot, '#FFFFFF', ec='#D6DEE6', lw=1.1)
    ax.add_patch(Circle((x + 3.2, ytop - 4.5), 2.2, fc=fill, ec='none'))
    ax.text(x + 3.2, ytop - 4.5, str(num), ha='center', va='center', fontsize=11, fontweight='bold', color=color)
    ax.text(x + 6.6, ytop - 4.5, textwrap.fill(head, 14), ha='left', va='center',
            fontsize=10.5, fontweight='bold', color=color, linespacing=1.1)
    ax.text(x + 2.5, ytop - 13.5, textwrap.fill(body, 23), ha='left', va='top',
            fontsize=10, color=INK, linespacing=1.4)


# ===================== FIGURE 4 =====================
fig, ax = new_fig(4.4)
title(ax, 'Demand Forecasting and Inventory Planning')
yt, yb = 80, 27
card(ax, 2, 28, yt, yb, 'Traditional Approach', SUB, GRAY,
     ['Recent demand history', 'Fixed uncertainty bands', 'Reacts after the shift'])
arrow(ax, 31, (yt + yb) / 2)
card(ax, 36, 28, yt, yb, 'EDM / BEI Decision Intelligence', TEAL, LTEAL,
     ['Behavioral item-location entities', 'Drift detection across time', 'Dynamic P10-P90 planning bands', 'Procurement-plan adjustment'])
arrow(ax, 65, (yt + yb) / 2)
card(ax, 70, 28, yt, yb, 'Decision Value', AMBER, LAMBER,
     ['Earlier stockout warning', 'More decision-useful planning', 'Explainable uncertainty movement'])
bottom_bar(ax, ['Legacy P90 379 units', 'EDM P90 225 units', '154 fewer units', '~$460K avoided over-procurement'],
           label='Representative proof point (synthetic):', y=4, h=16)
fig.savefig(f'{OUT}/_fig4_new.png'); plt.close(fig)

# ===================== FIGURE 10 =====================
fig, ax = new_fig(4.9)
title(ax, 'Technical Evidence Summary')
yt, yb = 82, 30
card(ax, 2, 30.5, yt, yb, 'Demand forecasting', BLUE, LBLUE,
     ['Held-out benchmark: EDM WAPE 0.78 vs Legacy 0.95', 'Worked example: P90 379 to 225 (~$460K)', 'Calibration ECE 0.0322 (Grade A)'], body_fs=11)
card(ax, 34.75, 30.5, yt, yb, 'Supplier risk', TEAL, LTEAL,
     ['Flags higher-risk suppliers', 'Estimates time-to-failure (30/60/90 day)', 'Explainable drivers (qualitative)'], body_fs=11)
card(ax, 67.5, 30.5, yt, yb, 'Network early warning', AMBER, LAMBER,
     ['4 of 4 cyber campaigns detected', '8.1% false-positive rate', 'Traditional methods: 0-1 of 4'], body_fs=11)
bottom_bar(ax, ['All results are representative / synthetic and must be validated on DLA operational data before production use.'],
           label='Validation boundary:', y=4, h=15, seg_fs=11)
fig.savefig(f'{OUT}/_fig10_new.png'); plt.close(fig)

# ===================== FIGURE 1 =====================
fig, ax = new_fig(4.75)
title(ax, 'From Metrics to Mission Decision Intelligence')
yt, yb = 80, 30
steps = [(1, 'Mission Need', 'Improve readiness and procurement decisions under uncertainty', NAVY, LBLUE),
         (2, 'Forecasting Limitation', 'Static history and fixed bands can react late', BLUE, LBLUE),
         (3, 'EDM Differentiator', 'Behavioral entities detect drift and uncertainty movement', TEAL, LTEAL),
         (4, 'Validation Path', 'Test side-by-side against DLA data through a bounded pilot', AMBER, LAMBER),
         (5, 'Decision Outcome', 'Earlier warning, better planning, explainable risk movement', NAVY, LBLUE)]
xs = [1, 20.2, 39.4, 58.6, 77.8]; w = 17
for i, (n, hd, bd, c, fl) in enumerate(steps):
    step(ax, xs[i], w, yt, yb, n, hd, bd, c, fl)
    if i < 4: arrow(ax, xs[i] + w + 0.2, (yt + yb) / 2)
bottom_bar(ax, ['Use existing data to move from backward-looking metrics to earlier, more decision-useful signals.'],
           label='Executive takeaway:', y=4, h=16, seg_fs=11.5)
fig.savefig(f'{OUT}/_fig1_new.png'); plt.close(fig)

# ===================== FIGURE 11 =====================
fig, ax = new_fig(4.9)
title(ax, 'Bounded Pilot Validation Path')
yt, yb = 82, 32
steps = [(1, 'Select DLA data scope', 'Choose NSNs, suppliers, depots, and scenarios', NAVY, LBLUE),
         (2, 'Configure entities', 'Map item, supplier, location, and network links', BLUE, LBLUE),
         (3, 'Run side by side', 'Compare current methods with new outputs', TEAL, LTEAL),
         (4, 'Review with SMEs', 'Validate signals, explanations, and operational usefulness', AMBER, LAMBER),
         (5, 'Decide on expansion', 'Determine readiness for broader pilot', NAVY, LBLUE)]
xs = [1, 20.2, 39.4, 58.6, 77.8]; w = 17
for i, (n, hd, bd, c, fl) in enumerate(steps):
    step(ax, xs[i], w, yt, yb, n, hd, bd, c, fl)
    if i < 4: arrow(ax, xs[i] + w + 0.2, (yt + yb) / 2)
bottom_bar(ax, ['Calibration', 'Procurement-plan accuracy', 'Early-warning lead time', 'Explainability', 'Analyst usability'],
           label='Success measures:', y=4, h=15)
fig.savefig(f'{OUT}/_fig11_new.png'); plt.close(fig)

print("built _fig4_new, _fig10_new, _fig1_new, _fig11_new")
