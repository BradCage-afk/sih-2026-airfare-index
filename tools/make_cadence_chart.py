"""Collection cadence — fares landing every ten minutes."""
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.dates as mdates, sys, datetime as dt
sys.path.insert(0, "/home/ajeet/SIH/airfare-scraper")
import db
NAVY, BLUE, INK, GREY = "#1F497D", "#4F81BD", "#262B33", "#7B8794"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":11,"text.color":INK,
                     "xtick.color":GREY,"ytick.color":GREY})
c = db.FareStore()._client
runs = sorted(c.table("scrape_runs").select("started_at,rows_written,status")
              .order("started_at").execute().data, key=lambda r: r["started_at"])
runs = [r for r in runs if r["rows_written"]]
t = [dt.datetime.fromisoformat(r["started_at"][:19]) for r in runs]
cum, tot = [], 0
for r in runs:
    tot += r["rows_written"]; cum.append(tot)

fig, ax = plt.subplots(figsize=(7.0, 3.0), dpi=200)
ax.fill_between(t, cum, color=BLUE, alpha=.16)
ax.plot(t, cum, color=NAVY, lw=2.2, solid_capstyle="round")
ax.scatter([t[-1]], [cum[-1]], s=55, color=NAVY, zorder=3,
           edgecolor="white", linewidth=1.8)
ax.set_ylabel("fares collected", fontsize=10.5, labelpad=8)
ax.yaxis.set_major_formatter(lambda v,_: f"{v/1000:.0f}k" if v >= 1000 else f"{v:.0f}")
ax.grid(axis="y", color="#E3E8ED", lw=1); ax.set_axisbelow(True)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
ax.xaxis.set_major_locator(mdates.HourLocator(interval=12))
for sp in ("top","right"): ax.spines[sp].set_visible(False)
ax.annotate(f"{cum[-1]:,}", (t[-1], cum[-1]), textcoords="offset points",
            xytext=(-8, -18), ha="right", fontsize=13, fontweight="bold", color=NAVY)
# mark where the 10-minute schedule took over from manual runs
gaps = [i for i in range(1, len(t)) if (t[i]-t[i-1]).total_seconds() <= 900]
if gaps:
    ax.axvline(t[gaps[0]], color=GREY, lw=1, ls="-", alpha=.5)
    ax.annotate("10-minute schedule starts", (t[gaps[0]], max(cum)*0.62),
                textcoords="offset points", xytext=(8, 0), fontsize=10, color=GREY)
ax.set_title(f"Collection is continuous — {len(runs)} runs, every 10 minutes",
             fontsize=12.5, fontweight="bold", color=NAVY, loc="left", pad=12)
fig.tight_layout()
fig.savefig("/home/ajeet/.claude/jobs/1319c671/tmp/chart-cadence.png",
            facecolor="white", bbox_inches="tight")
print(f"wrote chart-cadence.png — {len(runs)} runs, {cum[-1]:,} fares")
