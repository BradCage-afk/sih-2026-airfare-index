import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sys, collections
sys.path.insert(0, "/home/ajeet/SIH/airfare-scraper")
import db

NAVY, BLUE, GREY, INK = "#1F497D", "#4F81BD", "#7B8794", "#262B33"
S = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 13,
                     "axes.edgecolor": "#C7D3E3", "axes.labelcolor": INK,
                     "xtick.color": GREY, "ytick.color": GREY, "text.color": INK})

c = db.FareStore()._client
rows = c.table("fares_daily").select("*").execute().data
by = collections.defaultdict(dict)
for r in rows:
    by[f"{r['origin']}–{r['destination']}"][r["advance_window_days"]] = float(r["total_fare"])
print("routes:", list(by))

# ---- 1. the advance-booking curve, from real scraped fares
fig, ax = plt.subplots(figsize=(7.6, 4.3), dpi=200)
W = [1, 7, 15, 30, 45]
for i, (route, pts) in enumerate(sorted(by.items(), key=lambda kv: -max(kv[1].values()))):
    ys = [pts.get(w) for w in W]
    ax.plot(range(len(W)), ys, marker="o", ms=6, lw=2.4, color=S[i % 6], label=route,
            solid_capstyle="round")
ax.set_xticks(range(len(W))); ax.set_xticklabels([f"T+{w}" for w in W])
ax.set_xlabel("days booked before departure", labelpad=9)
ax.set_ylabel("mean fare  (₹)", labelpad=9)
ax.yaxis.set_major_formatter(lambda v, _: f"₹{v/1000:.0f}k")
ax.grid(axis="y", color="#E3E8ED", lw=1)
ax.set_axisbelow(True)
for sp in ("top", "right"): ax.spines[sp].set_visible(False)
ax.legend(frameon=False, fontsize=11, ncol=3, loc="upper right")
ax.set_title("Booking curves differ by route — so an index must measure, not assume",
             fontsize=13, fontweight="bold", color=NAVY, loc="left", pad=14)
fig.tight_layout()
fig.savefig("/home/ajeet/.claude/jobs/1319c671/tmp/chart-curve.png",
            facecolor="white", bbox_inches="tight")
print("wrote chart-curve.png")

# ---- 2. the premium headline
prem = []
for route, pts in by.items():
    if 1 in pts and 30 in pts:
        prem.append((route, (pts[1]/pts[30]-1)*100))
prem.sort(key=lambda x: -x[1])
fig, ax = plt.subplots(figsize=(7.6, 3.5), dpi=200)
names = [p[0] for p in prem]; vals = [p[1] for p in prem]
bars = ax.barh(names, vals, color=BLUE, height=.62)
bars[0].set_color("#C0504D")
for b, v in zip(bars, vals):
    ax.text(b.get_width()+1.5, b.get_y()+b.get_height()/2, f"{v:+.0f}%",
            va="center", fontsize=12, fontweight="bold", color=INK)
ax.invert_yaxis(); ax.set_xlim(min(0, min(vals)*1.2), max(vals)*1.22)
ax.set_xlabel("premium for booking tomorrow vs one month ahead", labelpad=9)
ax.grid(axis="x", color="#E3E8ED", lw=1); ax.set_axisbelow(True)
for sp in ("top", "right", "left"): ax.spines[sp].set_visible(False)
ax.tick_params(axis="y", length=0, labelsize=12)
ax.set_title("Late-booking premium, measured per route",
             fontsize=13, fontweight="bold", color=NAVY, loc="left", pad=14)
fig.tight_layout()
fig.savefig("/home/ajeet/.claude/jobs/1319c671/tmp/chart-premium.png",
            facecolor="white", bbox_inches="tight")
print("wrote chart-premium.png")
for r, v in prem: print(f"  {r}: {v:+.0f}%")
