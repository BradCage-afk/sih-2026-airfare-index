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

TEAM = "‹TEAM NAME›"

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
set_title(s2, "A DAILY AIRFARE PRICE INDEX FOR INDIA", 26)
remove(shape_by_name(s2, "TextBox 8"))

prob = panel(s2, 0.45, 1.22, 6.2, 0.82, fill=PALE, line=None)
write(prob.text_frame, [
    ("THE PROBLEM", 11, True, NAVY),
    ("CPI prices air travel from occasional manual quotes — but an airfare is "
     "not one price. It depends on when you book.", 14, False, INK, 4)])

textbox(s2, 0.45, 2.26, 6.2, 1.4, [
    ("Proposed Solution", 15, True, NAVY),
    ("The 15 busiest domestic city pairs, re-priced every 10 minutes and "
     "published as a price index.", 15, False, INK, 8),
])
ln = s2.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.47), Inches(2.56),
                         Inches(1.5), Inches(0.03))
ln.fill.solid(); ln.fill.fore_color.rgb = BLUE; ln.line.fill.background()
ln.shadow.inherit = False

s2.shapes.add_picture(MAP, Inches(0.45), Inches(3.35), width=Inches(5.75))

s2.shapes.add_picture(CURVE, Inches(7.0), Inches(1.24), width=Inches(5.9))
textbox(s2, 7.0, 4.62, 5.9, 0.85, [
    ("Real fares from our own scraper.", 13.5, True, NAVY),
    ("Booking a month ahead saves 40% on BLR–HYD and nothing on DEL–BOM. "
     "Nobody publishes that spread — so it has to be measured.", 13, False, GREY, 4),
])

heading(s2, 7.0, 5.58, 5.9, "Innovation", 14)
bullets(s2, 7.0, 6.00, 5.9, 0.8, [
    "Fares found by shape, not by CSS selectors.",
    "The model is config; it fails over automatically.",
], size=13, gap=6)

# =====================================================================  S3
s3 = prs.slides[2]
set_team_oval(s3)
set_title(s3, "TECHNICAL APPROACH", 28)
remove(shape_by_name(s3, "TextBox 8"))

heading(s3, 0.45, 1.24, 12.4, "Methodology — one route, one booking window", 15)
STEPS = [("1", "Robots gate", "RFC 9309 check\nbefore any fetch"),
         ("2", "Fetch", "Headless browser\nrenders the page"),
         ("3", "Trim", "13,000 chars\ndown to 3,700"),
         ("4", "Extract", "LLM → strict JSON\nretry, then fail over"),
         ("5", "Validate", "Schema + range\nnever estimates"),
         ("6", "Store", "INSERT with the\nmodel that read it")]
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
    ("15,000+ live fares in Postgres · 132 scheduled runs, 98% clean · a public "
     "dashboard reading the database on every load.", 14, False, INK, 4)])

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

heading(s4, 0.45, 1.24, 6.0, "Feasibility", 15)
bullets(s4, 0.45, 1.70, 6.0, 2.0, [
    "A working prototype, collecting right now.",
    "₹0 a month: free tiers end to end.",
    "~2 minutes of compute per 10-minute cycle.",
    "A new route is one line; a new portal, one entry.",
], size=14, gap=9)

cost = panel(s4, 0.45, 3.95, 6.0, 0.95, fill=PALE, line=None)
write(cost.text_frame, [
    ("MANUAL COLLECTION vs THIS PIPELINE", 12, True, NAVY),
    ("periodic → every 10 minutes  ·  one quoted price → 5 lead times  ·  "
     "field notes → URL, timestamp and model stored per fare", 13, False, INK, 5)])

s4.shapes.add_picture(CARR, Inches(0.45), Inches(5.08), width=Inches(6.0))

heading(s4, 7.0, 1.24, 5.9, "Risks, and what we did", 15)
RISKS = [("Airline sites block automation",
          "Basket is OTA-first; an official feed closes the gap."),
         ("Cloud IPs are blocked too",
          "Verified in CI — so collection runs from a residential host."),
         ("Models get retired without notice",
          "Three died during this build. Extraction now fails over."),
         ("A model could invent a fare",
          "Strict schema; components stay NULL rather than guessed.")]
y = 1.70
for risk, fix in RISKS:
    panel(s4, 7.0, y, 5.9, 0.95, fill=PALER, line=LINE)
    bar = s4.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(7.0), Inches(y),
                              Inches(0.055), Inches(0.95))
    bar.fill.solid(); bar.fill.fore_color.rgb = RED
    bar.line.fill.background(); bar.shadow.inherit = False
    textbox(s4, 7.2, y + 0.12, 5.6, 0.75,
            [(risk, 14, True, NAVY), (fix, 13, False, INK, 4)])
    y += 1.03

# =====================================================================  S5
s5 = prs.slides[4]
set_team_oval(s5)
set_title(s5, "IMPACT AND BENEFITS", 28)
remove(shape_by_name(s5, "TextBox 8"))

s5.shapes.add_picture(PREM, Inches(0.45), Inches(1.30), width=Inches(6.3))

heading(s5, 0.45, 4.62, 6.3, "Who it serves", 14)
bullets(s5, 0.45, 5.05, 6.3, 1.2, [
    "MoSPI / NSO — a defensible CPI transport input",
    "DGCA and policy — evidence on fare behaviour",
    "Citizens — when to book, and what is normal",
], size=13.5, gap=7)

fut = panel(s5, 0.45, 6.10, 6.3, 0.72, fill=PALE, line=None)
write(fut.text_frame, [
    ("NEXT", 11, True, NAVY),
    ("More city pairs, a second permitted portal, and rail and bus on the "
     "same pipeline.", 13, False, INK, 3)])

heading(s5, 7.0, 1.24, 5.9, "What changes", 15)
bullets(s5, 7.0, 1.70, 5.9, 1.7, [
    "A daily series, not occasional manual quotes.",
    "The booking-window dimension CPI cannot see.",
    "Every point traceable to source, time and model.",
], size=14, gap=10)

s5.shapes.add_picture(DASH, Inches(7.0), Inches(3.82), width=Inches(5.25))
textbox(s5, 7.0, 6.52, 5.9, 0.38,
        [("Live at real-time-airfare.vercel.app", 12.5, True, NAVY)])

# =====================================================================  S6
s6 = prs.slides[5]
set_team_oval(s6)
set_title(s6, "RESEARCH AND REFERENCES", 28)
remove(shape_by_name(s6, "TextBox 8"))

heading(s6, 0.45, 1.24, 6.1, "Methodology", 14)
bullets(s6, 0.45, 1.67, 6.1, 1.9, [
    "CPI Manual: Concepts and Methods (IMF / ILO, 2020)",
    "MoSPI — CPI (Base 2012=100), Transport sub-index",
    "Eurostat — web-scraped data in HICP compilation",
    "ONS (UK) — web-scraped data in consumer prices",
], size=13.5, gap=7)

heading(s6, 0.45, 3.85, 6.1, "Standards", 14)
bullets(s6, 0.45, 4.28, 6.1, 1.5, [
    "RFC 9309 — Robots Exclusion Protocol",
    "Each portal's robots.txt, re-checked at run time",
    "DGCA monthly domestic traffic — basket selection",
], size=13.5, gap=7)

heading(s6, 7.0, 1.24, 5.9, "Our own field research", 14)
bullets(s6, 7.0, 1.67, 5.9, 3.4, [
    "Portal survey: one OTA permits and serves us; two "
    "disallow or block outright.",
    "Python's standard robots parser wrongly permits paths "
    "these sites disallow — we implemented RFC 9309.",
    "Of 56 free-tier models, six answered; three reached "
    "end-of-life during the build, one mid-run.",
    "Splitting the prompt into 800-character chunks took a "
    "small model from 1 of 40 fares to 38.",
], size=13.5, gap=9)

drop_slide(prs, 6)
prs.save(OUT)
print("saved", OUT)
