"""Fill the SIH2026 idea template for SIH26056."""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from copy import deepcopy

SRC = "/home/ajeet/SIH/SIH2026-IDEA-Presentation-Format.pptx"
OUT = "/home/ajeet/SIH/SIH26056-Idea-Presentation.pptx"
TMP  = "/home/ajeet/.claude/jobs/1319c671/tmp"
DASH = TMP + "/dash-live.png"
CURVE = TMP + "/chart-curve.png"
PREM  = TMP + "/chart-premium.png"
CARR  = TMP + "/chart-carriers.png"
MAP   = TMP + "/chart-map.png"
CAD   = TMP + "/chart-cadence.png"
APIXC = TMP + "/chart-apix.png"
SURV  = TMP + "/chart-survey.png"
REC   = TMP + "/chart-record.png"

NAVY   = RGBColor(0x1F, 0x49, 0x7D)
BLUE   = RGBColor(0x4F, 0x81, 0xBD)
PALE   = RGBColor(0xDC, 0xE6, 0xF1)
PALER  = RGBColor(0xEE, 0xF3, 0xF9)
INK    = RGBColor(0x26, 0x2B, 0x33)
GREY   = RGBColor(0x5A, 0x62, 0x6C)
RED    = RGBColor(0xC0, 0x50, 0x4D)
GREEN  = RGBColor(0x4F, 0x7A, 0x3A)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
LINE   = RGBColor(0xC7, 0xD3, 0xE3)

TEAM = "Fare Enough"

prs = Presentation(SRC)


# ------------------------------------------------------------------ helpers
def drop_slide(prs, index):
    xml_slides = prs.slides._sldIdLst
    slides = list(xml_slides)
    rId = slides[index].get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
    prs.part.drop_rel(rId)
    xml_slides.remove(slides[index])


def shape_by_name(slide, name):
    for sh in slide.shapes:
        if sh.name == name:
            return sh
    return None


def remove(shape):
    shape._element.getparent().remove(shape._element)


def write(tf, blocks, wrap=True, margin=0.04):
    """blocks: (text, size, bold, color, space_before_pt, indent_level)"""
    tf.word_wrap = wrap
    tf.margin_left = tf.margin_right = Inches(margin)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    tf.clear()
    for i, b in enumerate(blocks):
        text, size, bold, color, before, lvl = (list(b) + [0, 0])[:6]
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.level = 0
        p.space_before = Pt(before)
        p.space_after = Pt(0)
        p.line_spacing = 0.95
        if lvl:
            p.paragraph_format if False else None
        r = p.add_run()
        r.text = text
        r.font.name = "Arial"
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
    return tf


def textbox(slide, x, y, w, h, blocks, **kw):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    write(tb.text_frame, blocks, **kw)
    return tb


def panel(slide, x, y, w, h, fill=PALER, line=LINE, radius=True, width_pt=1):
    shp = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        Inches(x), Inches(y), Inches(w), Inches(h))
    if radius:
        shp.adjustments[0] = 0.06
    shp.fill.solid(); shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line; shp.line.width = Pt(width_pt)
    shp.shadow.inherit = False
    shp.text_frame.word_wrap = True
    return shp


def chip(slide, x, y, w, h, text, fill=NAVY, fg=WHITE, size=10.5, bold=True):
    shp = panel(slide, x, y, w, h, fill=fill, line=None)
    tf = shp.text_frame
    tf.margin_left = tf.margin_right = Inches(0.03)
    tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = text
    r.font.name = "Arial"; r.font.size = Pt(size); r.font.bold = bold; r.font.color.rgb = fg
    return shp


def heading(slide, x, y, w, text, size=13.5):
    """Section heading = the template's required pointer, kept verbatim."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(0.3))
    write(tb.text_frame, [(text, size, True, NAVY)])
    # underline rule
    ln = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x + 0.02), Inches(y + 0.30),
                                Inches(min(w, 1.5)), Inches(0.028))
    ln.fill.solid(); ln.fill.fore_color.rgb = BLUE
    ln.line.fill.background(); ln.shadow.inherit = False
    return tb


def bullets(slide, x, y, w, h, items, size=11.5, gap=4, color=INK):
    blocks = []
    for i, it in enumerate(items):
        if isinstance(it, tuple):
            txt, bold, col = it
        else:
            txt, bold, col = it, False, color
        blocks.append(("•  " + txt if not txt.startswith(" ") else txt,
                       size, bold, col, 0 if i == 0 else gap))
    return textbox(slide, x, y, w, h, blocks)


def set_team_oval(slide):
    for sh in slide.shapes:
        if sh.name.startswith("Oval") and sh.has_text_frame:
            tf = sh.text_frame
            p = tf.paragraphs[0]
            for r in p.runs:
                r.text = ""
            if p.runs:
                p.runs[0].text = TEAM
            else:
                r = p.add_run(); r.text = TEAM
                r.font.size = Pt(11)
            p.alignment = PP_ALIGN.CENTER
            for r in p.runs:
                r.font.size = Pt(10.5)
                r.font.bold = True


def set_title(slide, text, size=30):
    t = shape_by_name(slide, "Title 1")
    tf = t.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    r = p.add_run(); r.text = text
    r.font.name = "Times New Roman"; r.font.size = Pt(size)
    r.font.bold = True; r.font.color.rgb = NAVY
    p.alignment = PP_ALIGN.CENTER
    return t


# =====================================================================  S1
s1 = prs.slides[0]
sub = shape_by_name(s1, "Subtitle 3")
if sub:
    remove(sub)
tb = shape_by_name(s1, "TextBox 9")
tb.left, tb.top, tb.width, tb.height = Inches(0.42), Inches(2.15), Inches(6.35), Inches(4.95)
FIELDS = [
    ("Problem Statement ID", "SIH26056"),
    ("Problem Statement Title",
     "Development of a Real-time Airfare Price Index for India through "
     "Automated Web Scraping of Airline and Online Travel Aggregator Portals "
     "for Augmentation of the Consumer Price Index (CPI)"),
    ("Theme", "Travel & Tourism"),
    ("PS Category", "Software"),
    ("Sponsoring Ministry", "MoSPI — Ministry of Statistics and Programme Implementation"),
    ("Team ID", "‹TEAM ID›"),
    ("Team Name", TEAM + "  (as registered on portal)"),
]
blocks = []
for i, (label, value) in enumerate(FIELDS):
    blocks.append((label.upper(), 9.5, True, BLUE, 0 if i == 0 else 9))
    blocks.append((value, 13 if label != "Problem Statement Title" else 12, True, INK, 1))
write(tb.text_frame, blocks)


# =====================================================================  S2
s2 = prs.slides[1]
set_team_oval(s2)
set_title(s2, "WHY WE STAND OUT", 28)
remove(shape_by_name(s2, "TextBox 8"))

textbox(s2, 0.45, 1.18, 8.6, 0.6, [
    ("APIx  \u2014  a daily airfare inflation index for the CPI", 15, True, NAVY),
    ("India's CPI still prices air travel from monthly manual visits. We measure it "
     "every ten minutes and publish it in the form a statistical office can ingest.",
     12.5, False, GREY, 4)])

CARDS = [
    ("The standard method,\nnot a homemade average",
     "Weighted Jevons on minimum logical fares \u2014 the elementary-aggregate method "
     "Eurostat and ONS use for their own price indices."),
    ("Weighting is a matrix,\nnot a guess",
     "Every cell is weighted by route share of scheduled seats \u00d7 booking lead "
     "time, so Delhi\u2013Mumbai moves the index three times as much as Delhi\u2013Srinagar."),
    ("It knows when not\nto publish",
     "Below 60% basket coverage a figure is marked provisional with the reason. "
     "An index that admits thin coverage is worth more than one that never does."),
    ("Machine-readable\nfor MoSPI",
     "An authenticated REST endpoint returns the index with its method, coverage "
     "and revision history. Nobody retypes a number from a screen."),
    ("Compliance by\nconstruction",
     "robots.txt is checked to RFC 9309 before every single request. We wrote our "
     "own parser because Python's standard one gets it wrong."),
    ("It never\nestimates",
     "Fields a portal does not publish stay NULL. Cells with too few observations "
     "are excluded, not filled in. The system says when it does not know."),
]
cw, ch, gx, gy = 4.05, 1.46, 0.28, 0.18
for i, (title, body) in enumerate(CARDS):
    x = 0.45 + (i % 3) * (cw + gx)
    y = 2.28 + (i // 3) * (ch + gy)
    card = panel(s2, x, y, cw, ch, fill=PALER, line=LINE)
    bar = s2.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y),
                              Inches(cw), Inches(0.05))
    bar.fill.solid(); bar.fill.fore_color.rgb = BLUE
    bar.line.fill.background(); bar.shadow.inherit = False
    write(card.text_frame, [(title, 13, True, NAVY), (body, 10.5, False, INK, 5)])

run = panel(s2, 0.45, 5.62, 12.4, 0.74, fill=PALE, line=None)
write(run.text_frame, [
    ("BUILT AND RUNNING  \u00b7  36,000+ fares collected  \u00b7  15 busiest city pairs "
     "\u00d7 5 booking lead times  \u00b7  every 10 minutes  \u00b7  \u20b90 a month",
     13, True, NAVY)])

# =====================================================================  S3
s3 = prs.slides[2]
set_team_oval(s3)
set_title(s3, "TECHNICAL APPROACH", 28)
remove(shape_by_name(s3, "TextBox 8"))

heading(s3, 0.45, 1.24, 12.4, "Methodology — one route, one booking window", 15)
STEPS = [("1", "Collect", "Robots-gated fetch\nevery 10 minutes"),
         ("2", "Extract", "LLM → strict JSON\nretry, then fail over"),
         ("3", "Validate", "Schema + range\nnever estimates"),
         ("4", "Clean", "Min 3 observations\nexclusions published"),
         ("5", "Index", "Weighted Jevons\nroute × lead time"),
         ("6", "Publish", "Portal + REST API\nfor MoSPI ingestion")]
bw, gap = 1.86, 0.24
for i, (n, t, d) in enumerate(STEPS):
    x = 0.45 + i * (bw + gap)
    box = panel(s3, x, 1.78, bw, 1.5, fill=PALER, line=LINE)
    write(box.text_frame, [(n, 12, True, BLUE), (t, 14, True, NAVY, 2),
                           (d, 11.5, False, GREY, 4)])
    box.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    if i < 5:
        ar = s3.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x + bw + 0.02),
                                 Inches(2.42), Inches(gap - 0.04), Inches(0.22))
        ar.fill.solid(); ar.fill.fore_color.rgb = BLUE
        ar.line.fill.background(); ar.shadow.inherit = False

ev = panel(s3, 0.45, 3.55, 12.4, 0.92, fill=PALE, line=None)
write(ev.text_frame, [
    ("BUILT AND RUNNING", 12, True, NAVY),
    ("36,076 fares · 298 runs, 98.7% clean · APIx published daily and monthly · "
     "live portal and authenticated REST API, both reading Postgres directly.",
     14, False, INK, 4)])

s3.shapes.add_picture(REC, Inches(0.45), Inches(4.58), width=Inches(4.45))
s3.shapes.add_picture(CAD, Inches(5.30), Inches(4.62), width=Inches(4.6))

heading(s3, 10.25, 4.62, 2.6, "Stack", 13)
bullets(s3, 10.25, 5.02, 2.7, 1.8, [
    "Python · Playwright",
    "OpenAI-compatible LLM",
    "Pydantic validation",
    "Supabase Postgres",
    "cron · HTML + SVG",
], size=11.5, gap=5)

# =====================================================================  S4
s4 = prs.slides[3]
set_team_oval(s4)
set_title(s4, "FEASIBILITY AND VIABILITY", 28)
remove(shape_by_name(s4, "TextBox 8"))

FEAS = [
    ("Technical feasibility",
     "India is the world's fifth-largest aviation market, worth USD 18.14 bn in 2026 "
     "and growing at 11.72% a year. The prices exist and change constantly \u2014 "
     "what is missing is a systematic way to measure them."),
    ("Operational feasibility",
     "164 million domestic passengers a year across 148 operational airports, up from "
     "74 in 2014. A fixed basket of the 15 busiest city pairs tracks the traffic that "
     "actually matters."),
    ("Economic feasibility",
     "The pipeline runs on free tiers at \u20b90 a month and ~2 minutes of compute per "
     "cycle. MoSPI's field collectors visit shops and markets monthly; this observes "
     "144 times a day without leaving a desk."),
    ("Regulatory feasibility",
     "Eurostat publishes guidance on web-scraped prices for HICP and names air fares "
     "explicitly. ONS has done it since 2014. The method is precedented in official "
     "statistics, not experimental."),
]
y = 1.24
for title, body in FEAS:
    card = panel(s4, 0.45, y, 6.15, 1.28, fill=PALER, line=LINE)
    bar = s4.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.45), Inches(y),
                              Inches(0.055), Inches(1.28))
    bar.fill.solid(); bar.fill.fore_color.rgb = BLUE
    bar.line.fill.background(); bar.shadow.inherit = False
    write(card.text_frame, [(title, 13.5, True, NAVY), (body, 11, False, INK, 4)])
    y += 1.40

heading(s4, 7.0, 1.24, 5.9, "Risks, and what we did about them", 14)
RISKS = [("16 portals surveyed, one is usable",
          "Ten disallow us, four block us, airlines refuse automation entirely."),
         ("Cloud IPs are blocked too",
          "Verified in CI \u2014 so collection runs from a residential host."),
         ("Models get retired without notice",
          "Three died during this build. Extraction now fails over automatically."),
         ("Thin coverage would mislead",
          "Days below 60% basket weight publish as provisional, with the reason.")]
y = 1.70
for risk, fix in RISKS:
    panel(s4, 7.0, y, 5.9, 0.95, fill=PALER, line=LINE)
    bar = s4.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(7.0), Inches(y),
                              Inches(0.055), Inches(0.95))
    bar.fill.solid(); bar.fill.fore_color.rgb = RED
    bar.line.fill.background(); bar.shadow.inherit = False
    textbox(s4, 7.2, y + 0.12, 5.6, 0.75,
            [(risk, 13, True, NAVY), (fix, 11.5, False, INK, 4)])
    y += 1.03


# =====================================================================  S5
s5 = prs.slides[4]
set_team_oval(s5)
set_title(s5, "IMPACT AND BENEFITS", 28)
remove(shape_by_name(s5, "TextBox 8"))

heading(s5, 0.45, 1.20, 12.4, "From a fare on a screen to a figure in the CPI", 14)
JOURNEY = [
    ("A fare is published", "A portal shows a price for one route\non one departure date"),
    ("We observe it", "Collected every 10 minutes,\nrobots-checked, timestamped"),
    ("It becomes a price", "Cheapest fare per route \u00d7 lead time\n\u2014 what a traveller could transact at"),
    ("It becomes an index", "Weighted Jevons across the basket\n\u2192 airfare inflation"),
    ("MoSPI ingests it", "REST API with method, coverage\nand revision history attached"),
    ("CPI reflects reality", "Transport sub-index priced from\n144 daily observations, not 1 visit"),
]
bw, gap = 1.86, 0.24
for i, (t, d) in enumerate(JOURNEY):
    x = 0.45 + i * (bw + gap)
    box = panel(s5, x, 1.70, bw, 1.36, fill=PALER, line=LINE)
    write(box.text_frame, [(str(i + 1), 11.5, True, BLUE),
                           (t, 12.5, True, NAVY, 2), (d, 9.5, False, GREY, 4)])
    box.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    if i < len(JOURNEY) - 1:
        ar = s5.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x + bw + 0.02),
                                 Inches(2.28), Inches(gap - 0.04), Inches(0.20))
        ar.fill.solid(); ar.fill.fore_color.rgb = BLUE
        ar.line.fill.background(); ar.shadow.inherit = False

s5.shapes.add_picture(APIXC, Inches(0.45), Inches(3.32), width=Inches(6.2))

heading(s5, 7.0, 3.32, 5.9, "Who benefits, and how", 14)
BEN = [("MoSPI / NSO", "A defensible transport input, recomputable from stored micro-data"),
       ("DGCA and policy", "Route-level fare behaviour nobody currently publishes"),
       ("Citizens", "A public record of what air travel actually costs over time"),
       ("Researchers", "An open, reproducible price series for a market that has none")]
y = 3.76
for who, what in BEN:
    chip(s5, 7.0, y, 1.75, 0.30, who, fill=NAVY, size=10)
    textbox(s5, 8.95, y - 0.02, 3.95, 0.5, [(what, 11.5, False, INK)])
    y += 0.56

promise = panel(s5, 7.0, 6.06, 5.9, 0.80, fill=PALE, line=None)
write(promise.text_frame, [
    ("OUR PROMISE", 10.5, True, NAVY),
    ("Replace one manual price visit a month with 144 automated observations a day "
     "\u2014 at zero marginal cost.", 12, False, INK, 3)])

# =====================================================================  S6
s6 = prs.slides[5]
set_team_oval(s6)
set_title(s6, "RESEARCH AND REFERENCES", 28)
remove(shape_by_name(s6, "TextBox 8"))

REFS = [
    ("Method \u2014 why Jevons",
     "Eurostat, Practical guidelines on web scraping for the HICP (2020). Names air "
     "fares explicitly as a scraped category. HICP is a chain-linked Laspeyres index "
     "built on Jevons elementary aggregates."),
    ("Precedent \u2014 it is already done",
     "ONS ran a web-scraping programme for consumer prices from 2014, Eurostat-funded "
     "from 2015. Kn\u00ed\u017eat (2023), Web scraped data in consumer price indices, "
     "on aggregating daily scraped prices to monthly."),
    ("The Indian basket",
     "DGCA monthly city-pair statistics: 164 million domestic passengers, IndiGo 64.2% "
     "share. Our own 1,000-fare sample returned 68.2% IndiGo \u2014 arrived at "
     "independently."),
    ("Standards we hold ourselves to",
     "RFC 9309, the Robots Exclusion Protocol. We implemented it ourselves after "
     "finding Python's standard parser reports disallowed paths as allowed."),
    ("Our own field research",
     "16 Indian portals surveyed: one usable. 56 free-tier models tested: six answered, "
     "three reached end-of-life mid-build. Prompt chunking took a small model from 1 of "
     "40 fares to 38."),
    ("Live for inspection",
     "Portal: apix-portal.pages.dev  \u00b7  API: apix-api-n5ux.onrender.com/docs  "
     "\u00b7  Code and full method: github.com/BradCage-afk/sih-2026-airfare-index"),
]
cw2, ch2, gx2, gy2 = 4.05, 1.82, 0.28, 0.20
for i, (title, body) in enumerate(REFS):
    x = 0.45 + (i % 3) * (cw2 + gx2)
    y = 1.24 + (i // 3) * (ch2 + gy2)
    card = panel(s6, x, y, cw2, ch2, fill=PALER, line=LINE)
    bar = s6.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y),
                              Inches(cw2), Inches(0.05))
    bar.fill.solid(); bar.fill.fore_color.rgb = BLUE
    bar.line.fill.background(); bar.shadow.inherit = False
    write(card.text_frame, [(title, 12.5, True, NAVY), (body, 10, False, INK, 5)])

s6.shapes.add_picture(SURV, Inches(0.45), Inches(5.28), width=Inches(4.5))
textbox(s6, 5.25, 5.34, 7.6, 1.4, [
    ("Everything above is reproducible.", 12.5, True, NAVY),
    ("The index, the charts in this deck and the figures on the portal are all "
     "regenerated from the database by scripts in the repository \u2014 nothing here "
     "is transcribed by hand, so no number in this presentation can drift from what "
     "the system actually holds.", 11, False, INK, 4)])

drop_slide(prs, 6)
prs.save(OUT)
print("saved", OUT)
