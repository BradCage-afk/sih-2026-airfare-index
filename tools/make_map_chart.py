"""Route basket as a schematic map, and one real fare record."""
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, sys
sys.path.insert(0, "/home/ajeet/SIH/airfare-scraper")
import db
NAVY, BLUE, INK, GREY, PALE = "#1F497D", "#4F81BD", "#262B33", "#7B8794", "#DCE6F1"
plt.rcParams.update({"font.family":"DejaVu Sans","text.color":INK})
OUT = "/home/ajeet/.claude/jobs/1319c671/tmp"

CITY = {"DEL":(77.10,28.56,"Delhi"),   "BOM":(72.87,19.09,"Mumbai"),
        "BLR":(77.71,13.20,"Bengaluru"), "CCU":(88.45,22.65,"Kolkata"),
        "HYD":(78.43,17.24,"Hyderabad"), "MAA":(80.17,12.99,"Chennai"),
        "PNQ":(73.92,18.58,"Pune"),      "AMD":(72.63,23.07,"Ahmedabad"),
        "SXR":(74.77,33.99,"Srinagar")}
import config
ROUTES = [r for r in config.ROUTES if r[0] in CITY and r[1] in CITY]

fig, ax = plt.subplots(figsize=(6.2, 3.5), dpi=200)
for a, b in ROUTES:
    x1,y1,_ = CITY[a]; x2,y2,_ = CITY[b]
    ax.plot([x1,x2],[y1,y2], color=BLUE, lw=1.6, alpha=.6, zorder=1,
            solid_capstyle="round")
# label placement chosen per city so nothing collides
OFFSET = {"DEL":(14, 6, "left"),   "BOM":(-13, -9, "right"), "BLR":(-13, -4, "right"),
          "CCU":(14, 0, "left"),  "HYD":(14, 2, "left"),    "MAA":(14, -8, "left"),
          "PNQ":(11, -12, "left"), "AMD":(-13, 3, "right"),  "SXR":(14, -2, "left")}
for code,(x,y,name) in CITY.items():
    dx, dy, ha = OFFSET[code]
    ax.scatter([x],[y], s=170, color=NAVY, zorder=3, edgecolor="white", linewidth=2)
    ax.annotate(f"{code}\n{name}", (x,y), textcoords="offset points",
                xytext=(dx,dy), ha=ha, fontsize=10.5, fontweight="bold",
                color=INK, zorder=4)
ax.set_xlim(67, 94); ax.set_ylim(8, 38)
ax.axis("off")
ax.set_title(f"The fixed basket — {len(ROUTES)} busiest city pairs (schematic)",
             fontsize=13, fontweight="bold", color=NAVY, loc="left", pad=6)
ax.text(0.0, -0.01, "Ranked by scheduled seats, so the basket follows traffic rather than intuition.",
        transform=ax.transAxes, fontsize=9.5, color=GREY, va="top")
fig.tight_layout()
fig.savefig(f"{OUT}/chart-map.png", facecolor="white", bbox_inches="tight")
print("wrote chart-map.png")

# ---- one real row, as a figure
c = db.FareStore()._client
row = c.table("fares").select("*").order("scraped_at", desc=True).limit(1).execute().data[0]
FIELDS = [("origin → destination", f"{row['origin']} → {row['destination']}"),
          ("carrier", row["carrier"]),
          ("departure_time", row.get("departure_time") or "—"),
          ("advance_window_days", f"T+{row['advance_window_days']}"),
          ("total_fare", f"₹{int(row['total_fare']):,}"),
          ("base_fare / taxes / udf", "NULL — not published on the listing"),
          ("source", row["source"]),
          ("model_used", row["model_used"]),
          ("scraped_at", row["scraped_at"][:19].replace("T", " ") + " UTC")]
fig, ax = plt.subplots(figsize=(6.4, 3.1), dpi=200); ax.axis("off")
for i,(k,v) in enumerate(FIELDS):
    y = 1 - i*0.112
    ax.add_patch(plt.Rectangle((0, y-0.085), 1, 0.098, transform=ax.transAxes,
                 facecolor=PALE if i % 2 == 0 else "white", edgecolor="none"))
    ax.text(0.015, y-0.038, k, fontsize=10, color=GREY, transform=ax.transAxes,
            va="center", family="monospace")
    ax.text(0.50, y-0.038, v, fontsize=10.5, color=INK, fontweight="bold",
            transform=ax.transAxes, va="center")
ax.set_title("One stored fare — every field traceable",
             fontsize=13, fontweight="bold", color=NAVY, loc="left", pad=8)
fig.tight_layout()
fig.savefig(f"{OUT}/chart-record.png", facecolor="white", bbox_inches="tight")
print("wrote chart-record.png; sample:", row["origin"], row["destination"], row["carrier"])
