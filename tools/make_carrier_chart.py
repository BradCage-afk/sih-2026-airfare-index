import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, sys, collections
sys.path.insert(0, "/home/ajeet/SIH/airfare-scraper")
import db
NAVY, BLUE, INK, GREY = "#1F497D", "#4F81BD", "#262B33", "#7B8794"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":13,"text.color":INK,
                     "xtick.color":GREY,"ytick.color":GREY})
c = db.FareStore()._client
rows = c.table("fares").select("carrier").execute().data
cnt = collections.Counter(r["carrier"] for r in rows)
items = cnt.most_common(5)
fig, ax = plt.subplots(figsize=(7.0, 2.05), dpi=200)
names = [k for k, _ in items][::-1]; vals = [v for _, v in items][::-1]
bars = ax.barh(names, vals, color=BLUE, height=.66)
bars[-1].set_color(NAVY)
for b, v in zip(bars, vals):
    ax.text(b.get_width() + max(vals)*0.02, b.get_y()+b.get_height()/2, f"{v:,}",
            va="center", fontsize=12, fontweight="bold", color=INK)
ax.set_xlim(0, max(vals)*1.18)
ax.set_xlabel("")
ax.grid(axis="x", color="#E3E8ED", lw=1); ax.set_axisbelow(True)
for sp in ("top","right","left"): ax.spines[sp].set_visible(False)
ax.tick_params(axis="y", length=0, labelsize=11)
ax.tick_params(axis="x", labelsize=10)
ax.set_title("One OTA source reaches every major Indian carrier",
             fontsize=12, fontweight="bold", color=NAVY, loc="left", pad=9)
fig.tight_layout()
fig.savefig("/home/ajeet/.claude/jobs/1319c671/tmp/chart-carriers.png",
            facecolor="white", bbox_inches="tight")
print("carriers:", dict(items))
