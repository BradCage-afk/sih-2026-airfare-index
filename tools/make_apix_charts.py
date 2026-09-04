"""Charts for the deck, drawn from the published index."""
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, sys, os
sys.path.insert(0, "/home/ajeet/SIH/airfare-scraper")
sys.path.insert(0, "/home/ajeet/SIH/engine")
import db, engine
NAVY, BLUE, INK, GREY, WARN = "#1F497D", "#4F81BD", "#262B33", "#7B8794", "#FAB219"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":12,"text.color":INK,
                     "xtick.color":GREY,"ytick.color":GREY})
OUT = "/home/ajeet/.claude/jobs/1319c671/tmp"

# ---- 1. the index itself
rows = [r for r in engine.series(db.FareStore()._client) if r.get("apix")]
fig, ax = plt.subplots(figsize=(7.0, 3.2), dpi=200)
xs = list(range(len(rows))); ys = [r["apix"] for r in rows]
ax.axhline(100, color="#C7D3E3", lw=1.4)
ax.fill_between(xs, ys, 100, color=BLUE, alpha=.14)
ax.plot(xs, ys, color=NAVY, lw=2.4, solid_capstyle="round", zorder=3)
for x, r in zip(xs, rows):
    ax.scatter([x], [r["apix"]], s=64, zorder=4, edgecolor="white", linewidth=1.8,
               color=WARN if r.get("provisional") else NAVY)
    ax.annotate(f"{r['apix']:.1f}", (x, r["apix"]), textcoords="offset points",
                xytext=(0, 11), ha="center", fontsize=11, fontweight="bold", color=INK)
ax.set_xticks(xs); ax.set_xticklabels([r["day"][5:] for r in rows])
ax.set_ylabel("APIx", labelpad=8)
ax.set_ylim(min(ys)-7, max(ys)+9)
ax.text(0, 100.6, "reference period = 100", fontsize=10, color=GREY)
for sp in ("top","right"): ax.spines[sp].set_visible(False)
ax.grid(axis="y", color="#E3E8ED", lw=1); ax.set_axisbelow(True)
ax.set_title("APIx — published from live observations (amber = provisional)",
             fontsize=12.5, fontweight="bold", color=NAVY, loc="left", pad=12)
fig.tight_layout(); fig.savefig(f"{OUT}/chart-apix.png", facecolor="white", bbox_inches="tight")
print("wrote chart-apix.png", [round(y,2) for y in ys])

# ---- 2. the portal survey — a finding in its own right
# Drawn at the aspect it is placed at on slide 6 (4.55 x 1.70 in) with the axes
# positioned by hand, so nothing is scaled down afterwards and the category
# labels stay legible in the deck.
CATS = [("Permitted and usable", 1, "#1baf7a"),
        ("Permitted, no date control", 1, "#eda100"),
        ("Disallowed by robots.txt", 6, "#4F81BD"),
        ("Unreachable or blocked", 4, "#8fa8c4"),
        ("Airlines block automation", 4, "#C0504D")]
fig, ax = plt.subplots(figsize=(5.0, 1.866), dpi=300)
fig.subplots_adjust(left=0.50, right=0.975, top=0.74, bottom=0.06)
names = [c[0] for c in CATS][::-1]
vals  = [c[1] for c in CATS][::-1]
cols  = [c[2] for c in CATS][::-1]
bars = ax.barh(names, vals, color=cols, height=.62)
for b, v in zip(bars, vals):
    ax.text(b.get_width() + .18, b.get_y() + b.get_height()/2, str(v),
            va="center", fontsize=10.5, fontweight="bold", color=INK)
ax.set_xlim(0, max(vals) + 1.2)
ax.set_xticks([])
ax.tick_params(axis="y", length=0, labelsize=9.5)
for lbl in ax.get_yticklabels():
    lbl.set_fontweight("bold"); lbl.set_color(INK)
for sp in ("top", "right", "bottom", "left"): ax.spines[sp].set_visible(False)
# the title belongs to the figure, not the axes, or it starts half way across
fig.text(0.016, 0.955, f"{sum(vals)} Indian travel portals surveyed — one is usable",
         ha="left", va="top", fontsize=9.5, fontweight="bold", color=NAVY)
fig.savefig(f"{OUT}/chart-survey.png", facecolor="white")
print("wrote chart-survey.png")
