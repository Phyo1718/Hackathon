"""Presentation-only theme for the Streamlit app (app.py).

Colour tokens, the global CSS, small decorative HTML/SVG helpers and the Altair colours. This module
holds no business logic: nothing here reads data, decides anything or produces information the user
needs. Every helper returns markup that is purely decorative (aria-hidden) or restyles text that
app.py already shows.

Hooks used by the CSS:
- Streamlit's own data-testid attributes and the st-key-<key> classes of keyed elements.
- Keyed layout containers added in app.py: hzhero_<view> (view header), hzcard_<name> (card),
  hzsec_<name> (section heading with icon), hzm_<name> (metric with icon), hzgate (startup screen).
- The existing classes gov-meta, budget-*, pdf-download and st-key-sidebar_nav.

All motion is wrapped in @media (prefers-reduced-motion: no-preference) and animates on mount only,
so Streamlit reruns (for example typing in a text area) do not replay it.
"""
import html
from typing import Dict

# ------------------------------------------------------------------------------------------------
# Tokens
# ------------------------------------------------------------------------------------------------

TOKENS: Dict[str, str] = {
    "paper": "#F8F7F4",
    "surface": "#FFFFFF",
    "line": "#E4E2DC",
    "text": "#45465A",
    "muted": "#6B6C7A",
    "blue": "#0B99C4",
    "blue_ink": "#076A89",
    "orange": "#CC6815",
    "orange_ink": "#A3510E",
    "sage": "#8EBE9E",
    "green_ink": "#2F6B4F",
    "teal": "#00837D",
    "red": "#D1344F",
    "red_ink": "#B82B45",
}

FONT_DISPLAY = "'Zilla Slab', Georgia, 'Times New Roman', serif"
FONT_LABEL = "'Barlow Condensed', 'Arial Narrow', 'Segoe UI', system-ui, sans-serif"
FONT_BODY = "Barlow, 'Segoe UI', system-ui, -apple-system, sans-serif"

# Altair chart colours (styling only; the charts' data and encodings live in app.py)
CHART: Dict[str, str] = {
    "blue": TOKENS["blue"],          # series, bars
    "orange": TOKENS["orange"],      # flagged bars
    "orange_ink": TOKENS["orange_ink"],  # small flagged text in tables
    "ink": TOKENS["text"],
    "muted": TOKENS["muted"],
    "grid": TOKENS["line"],
    "font": "Barlow",
}

# Budget meter fill colours, by the state app.py already decides (thresholds unchanged)
METER: Dict[str, str] = {"ok": TOKENS["green_ink"], "warn": TOKENS["orange"], "over": TOKENS["red"]}

# Decorative Material Symbols per budget line in the sidebar meters (fallback: account_balance)
BUDGET_ICONS: Dict[str, str] = {
    "IT-Ausstattung": "computer",
    "Büromaterial": "inventory_2",
    "Fahrzeuge": "local_shipping",
    "Feuerwehrtechnik": "fire_truck",
    "Gebäudeunterhaltung": "apartment",
}

# View header icon and circle palette
VIEW_ART: Dict[str, Dict[str, str]] = {
    "verify": {"icon": "fact_check", "tone": "blue"},
    "bids": {"icon": "gavel", "tone": "orange"},
    "add": {"icon": "add_circle", "tone": "sage"},
    "insights": {"icon": "insights", "tone": "teal"},
}

# Circle colours per tone: (large, medium, small)
_TONES: Dict[str, tuple] = {
    "blue": (TOKENS["blue"], TOKENS["sage"], TOKENS["orange"]),
    "orange": (TOKENS["orange"], TOKENS["blue"], TOKENS["sage"]),
    "sage": (TOKENS["sage"], TOKENS["blue"], TOKENS["orange"]),
    "teal": (TOKENS["blue"], TOKENS["orange"], TOKENS["sage"]),
    "green": (TOKENS["sage"], TOKENS["blue"], TOKENS["orange"]),
    "red": (TOKENS["red"], TOKENS["orange"], TOKENS["sage"]),
}

_ICON_INK = {
    "blue": TOKENS["blue_ink"], "orange": TOKENS["orange_ink"], "sage": TOKENS["green_ink"],
    "teal": TOKENS["teal"], "green": TOKENS["green_ink"], "red": TOKENS["red_ink"],
}


# ------------------------------------------------------------------------------------------------
# Decorative HTML helpers (aria-hidden, no information)
# ------------------------------------------------------------------------------------------------

def _circles(tone: str) -> str:
    """Three overlapping translucent circles, a dotted ring and a dot grid, as plain HTML spans.

    (st.html sanitises inline SVG away, so the motif is built from round, multiply-blended spans
    positioned in % of their box; it scales with any box size.)"""
    big, mid, small = _TONES.get(tone, _TONES["blue"])
    return (
        '<span class="hz-dots"></span>'
        f'<span class="hz-circle hz-c1" style="background:{big}"></span>'
        f'<span class="hz-circle hz-c2" style="background:{mid}"></span>'
        f'<span class="hz-circle hz-c3" style="background:{small}"></span>'
        '<span class="hz-ring"></span>'
    )


def hero_art(view: str) -> str:
    """Circle cluster with a large Material icon for the view header."""
    art = VIEW_ART.get(view, VIEW_ART["verify"])
    ink = _ICON_INK[art["tone"]]
    return (
        f'<div class="hz-art hz-hero-art hz-tone-{art["tone"]}" aria-hidden="true">'
        f'{_circles(art["tone"])}'
        f'<span class="hz-hero-icon" style="color:{ink}"><span class="hz-mi">{art["icon"]}</span></span>'
        "</div>"
    )


def illustration(icon: str, tone: str = "blue", size: str = "md", paper: bool = False) -> str:
    """Original flat illustration: overlapping circles, an optional sheet of paper, and a glyph badge.
    Used for empty states, the startup screen and success states."""
    ink = _ICON_INK.get(tone, TOKENS["blue_ink"])
    sheet = '<span class="hz-sheet"><i></i><i></i><i></i></span>' if paper else ""
    return (
        f'<div class="hz-art hz-illus hz-illus-{size}" aria-hidden="true">'
        f'{_circles(tone)}{sheet}'
        f'<span class="hz-illus-badge" style="color:{ink}"><span class="hz-mi">{icon}</span></span>'
        "</div>"
    )


def brand_mark() -> str:
    """Small decorative circle cluster for the sidebar header."""
    return (
        '<div class="hz-brand-mark" aria-hidden="true">'
        f'<span style="background:{TOKENS["blue"]}"></span>'
        f'<span style="background:{TOKENS["orange"]}"></span>'
        f'<span style="background:{TOKENS["sage"]}"></span>'
        "</div>"
    )


def step(number: int, tone: str = "orange") -> str:
    """Large italic step numeral (01 / 02 / ...) with a dotted rule: decoration around a sequence."""
    return (
        f'<div class="hz-step hz-step-{tone}" aria-hidden="true">'
        f'<span class="hz-step-num">{number:02d}</span><span class="hz-step-rule"></span></div>'
    )


def status_chip(icon: str, text: str, tone: str) -> str:
    """Bold uppercase status word with icon, repeating an existing (translated) status text."""
    return (
        f'<div class="hz-chip hz-chip-{tone}" aria-hidden="true"><span class="hz-mi">{icon}</span>'
        f"<span>{html.escape(text)}</span></div>"
    )


def label(icon: str, text: str) -> str:
    """Section label: icon + condensed uppercase text (same text as before, restyled)."""
    return (
        f'<div class="hz-label"><span class="hz-mi" aria-hidden="true">{icon}</span>'
        f"<span>{html.escape(text)}</span></div>"
    )


def style_chart(chart):
    """Brand fonts and quiet axes for an Altair top-level chart (styling only)."""
    return chart.configure(font=CHART["font"], background="transparent").configure_axis(
        labelFont=CHART["font"], titleFont=CHART["font"], labelFontSize=12, labelPadding=6,
    ).configure_text(font=CHART["font"])


# ------------------------------------------------------------------------------------------------
# CSS
# ------------------------------------------------------------------------------------------------

_NOISE = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E"
    "%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/%3E"
    "%3CfeColorMatrix values='0 0 0 0 .27 0 0 0 0 .27 0 0 0 0 .35 0 0 0 1 0'/%3E%3C/filter%3E"
    "%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.035'/%3E%3C/svg%3E"
)

_FONT_FACES = [
    ("Zilla Slab", "ZillaSlab-BoldItalic.woff2", 700, "italic"),
    ("Barlow Condensed", "BarlowCondensed-400.woff2", 400, "normal"),
    ("Barlow Condensed", "BarlowCondensed-500.woff2", 500, "normal"),
    ("Barlow Condensed", "BarlowCondensed-600.woff2", 600, "normal"),
    ("Barlow", "Barlow-400.woff2", 400, "normal"),
    ("Barlow", "Barlow-400-italic.woff2", 400, "italic"),
    ("Barlow", "Barlow-500.woff2", 500, "normal"),
    ("Barlow", "Barlow-600.woff2", 600, "normal"),
    ("Barlow", "Barlow-700.woff2", 700, "normal"),
]

_BASE_CSS = """
:root {
  --hz-paper: #F8F7F4; --hz-surface: #FFFFFF; --hz-line: #E4E2DC; --hz-text: #45465A; --hz-muted: #6B6C7A;
  --hz-blue: #0B99C4; --hz-blue-ink: #076A89; --hz-orange: #CC6815; --hz-orange-ink: #A3510E;
  --hz-sage: #8EBE9E; --hz-green-ink: #2F6B4F; --hz-teal: #00837D; --hz-red: #D1344F; --hz-red-ink: #B82B45;
  --hz-blue-tint: #E6F3F7; --hz-orange-tint: #FBEFE4; --hz-green-tint: #EAF3EE; --hz-red-tint: #FBEAED; --hz-warm-tint: #F2F0EB;
  --hz-shadow: 0 2px 10px rgba(69, 70, 90, .06);
  --hz-shadow-lift: 0 10px 24px rgba(69, 70, 90, .12);
  --hz-ease: cubic-bezier(.2, .8, .2, 1);
  --hz-font-display: __DISPLAY__;
  --hz-font-label: __LABEL__;
  --hz-font-body: __BODY__;
}

/* ---------- Page, header, typography ---------------------------------------------------------- */
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  background-color: var(--hz-paper);
  color: var(--hz-text);
}
.stApp { background-image: url("__NOISE__"); }
[data-testid="stAppViewContainer"], [data-testid="stMain"] { background-color: transparent; }
[data-testid="stHeader"] { background-color: var(--hz-paper); box-shadow: 0 1px 0 var(--hz-line); }
[data-testid="stMainBlockContainer"] { padding-top: 5.25rem; padding-bottom: 4rem; }
html, body, .stApp, .stApp p, .stApp li, .stApp label, .stApp input, .stApp textarea, .stApp button {
  font-family: var(--hz-font-body);
}
.stApp [data-testid="stMarkdownContainer"] p, .stApp [data-testid="stMarkdownContainer"] li { line-height: 1.55; }
[data-testid="stIconMaterial"], .hz-mi {
  font-family: "Material Symbols Rounded" !important;
  font-weight: normal; font-style: normal; letter-spacing: normal !important; text-transform: none !important;
  line-height: 1; white-space: nowrap; direction: ltr; -webkit-font-smoothing: antialiased;
  font-feature-settings: "liga"; display: inline-block;
}
.stApp h1, .stApp h2, .stApp h3, section[role="dialog"] h2 {
  font-family: var(--hz-font-display) !important;
  font-style: italic; font-weight: 700; text-transform: uppercase;
  letter-spacing: -.005em; line-height: 1.04; color: var(--hz-text);
  overflow-wrap: break-word;
}
.stApp h1 { font-size: clamp(1.7rem, 6.4vw, 3.3rem); padding-top: .1rem; }
.stApp h3 { font-size: clamp(1.2rem, 3.4vw, 1.55rem); }
section[role="dialog"] h2 { font-size: clamp(1.4rem, 4vw, 2rem); color: var(--hz-blue-ink); }
.stApp h1 [data-testid="stHeaderActionElements"], .stApp h3 [data-testid="stHeaderActionElements"] { display: none; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: var(--hz-muted) !important; opacity: 1 !important; font-size: .95rem; line-height: 1.5; }
.stApp a { color: var(--hz-blue-ink); text-underline-offset: 3px; }
.stApp hr { border-color: var(--hz-line); }

/* Kicker label (agency line) */
.gov-meta {
  display: flex; align-items: center; gap: .6rem;
  color: var(--hz-blue-ink);
  font-family: var(--hz-font-label);
  font-size: .9rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: .08em; line-height: 1.35;
  margin-bottom: .25rem;
}
.gov-meta::before {
  content: ""; flex: 0 0 28px; height: 0; border-top: 3px dotted var(--hz-orange);
}

/* Widget labels: thin condensed uppercase (not checkbox sentences) */
:is([data-testid="stTextArea"], [data-testid="stTextInput"], [data-testid="stSelectbox"], [data-testid="stNumberInput"],
    [data-testid="stFileUploader"], [data-testid="stRadio"], [data-testid="stButtonGroup"]) > [data-testid="stWidgetLabel"] p {
  font-family: var(--hz-font-label); text-transform: uppercase; letter-spacing: .07em;
  font-weight: 500; font-size: .95rem; color: var(--hz-text);
}

/* Section label (replaces plain bold headers; same text) */
.hz-label {
  display: flex; align-items: center; gap: .55rem; margin: .15rem 0 .1rem;
  font-family: var(--hz-font-label); font-weight: 600; font-size: 1.02rem;
  text-transform: uppercase; letter-spacing: .07em; color: var(--hz-text);
}
.hz-label .hz-mi {
  display: inline-grid; place-items: center; width: 1.9rem; height: 1.9rem; border-radius: 50%;
  background: var(--hz-blue-tint); color: var(--hz-blue-ink); font-size: 1.15rem;
}

/* Section headings with icons (keyed hzsec_/hzcard_ containers set --hz-icon) */
[class*="st-key-hzsec_"] h3::before, [class*="st-key-hzcard_tile"] h3::before, .st-key-hzcard_winner h3::before {
  content: var(--hz-icon, "label");
  font-family: "Material Symbols Rounded"; font-style: normal; font-weight: normal;
  text-transform: none; letter-spacing: normal; font-feature-settings: "liga";
  display: inline-grid; place-items: center; vertical-align: -.18em;
  width: 1.8em; height: 1.8em; margin-right: .5em; border-radius: 50%;
  font-size: .82em; line-height: 1; background: var(--hz-blue-tint); color: var(--hz-blue-ink);
}
.st-key-hzsec_queue { --hz-icon: "inbox"; }
.st-key-hzsec_matrix { --hz-icon: "leaderboard"; }
.st-key-hzsec_letters { --hz-icon: "mail"; }
.st-key-hzcard_winner { --hz-icon: "emoji_events"; }
.st-key-hzcard_tile_budget { --hz-icon: "account_balance"; }
.st-key-hzcard_tile_suppliers { --hz-icon: "local_shipping"; }
.st-key-hzcard_tile_oversight { --hz-icon: "visibility"; }
.st-key-hzcard_winner h3::before { background: var(--hz-orange-tint); color: var(--hz-orange-ink); }

/* ---------- View header (hero) ---------------------------------------------------------------- */
[class*="st-key-hzhero_"] {
  position: relative; padding: .35rem 250px .9rem 0; min-height: 200px; justify-content: center;
}
[class*="st-key-hzhero_"] > [data-testid="stElementContainer"]:has(.hz-hero-art) {
  position: absolute !important; top: 50%; right: 0; width: 240px !important; height: 190px;
  transform: translateY(-50%); pointer-events: none; margin: 0; z-index: 0;
}
[class*="st-key-hzhero_"] > * { position: relative; z-index: 1; }
[class*="st-key-hzhero_"] [data-testid="stCaptionContainer"] p { font-size: 1.05rem; max-width: 62ch; color: var(--hz-muted); }
.hz-art { position: relative; isolation: isolate; }
.hz-hero-art { width: 240px; height: 190px; }
.hz-art > span { position: absolute; display: block; }
.hz-circle { border-radius: 50%; aspect-ratio: 1; mix-blend-mode: multiply; opacity: .85; }
.hz-c1 { left: 35%; top: 8%; width: 55%; }
.hz-c2 { left: 16%; top: 36%; width: 40%; }
.hz-c3 { left: 68%; top: 58%; width: 25%; }
.hz-ring { left: 18%; top: 2%; width: 74%; aspect-ratio: 1; border-radius: 50%; border: 3px dotted var(--hz-orange); opacity: .9; }
.hz-dots {
  left: 0; top: 6%; width: 28%; height: 26%;
  background-image: radial-gradient(circle, rgba(69, 70, 90, .3) 1.4px, transparent 1.6px); background-size: 11px 11px;
}
.hz-hero-icon {
  left: 62.5%; top: 43%; transform: translate(-50%, -50%);
  width: 84px; height: 84px; border-radius: 50%; background: var(--hz-surface);
  display: grid !important; place-items: center; box-shadow: 0 8px 22px rgba(69, 70, 90, .16);
}
.hz-hero-icon .hz-mi { font-size: 46px; }

/* ---------- Illustrations, step numerals, chips --------------------------------------------- */
.hz-illus { margin: .25rem auto .35rem; width: 200px; height: 150px; }
.hz-illus-sm { width: 140px; height: 105px; }
.hz-illus-lg { width: 280px; height: 210px; }
.hz-sheet {
  left: 36%; top: 10%; width: 28%; aspect-ratio: .78; background: #FFFFFF; border: 2px solid var(--hz-text); border-radius: 6px;
  box-shadow: 0 6px 12px rgba(69, 70, 90, .14); padding: 26% 12% 0; box-sizing: border-box;
  display: flex !important; flex-direction: column; gap: 11%;
}
.hz-sheet i { display: block; width: 100%; height: 5px; flex: 0 0 5px; border-radius: 4px; background: var(--hz-line); }
.hz-sheet i:nth-child(2) { width: 80%; }
.hz-sheet i:nth-child(3) { width: 55%; }
.hz-illus-badge {
  right: 16%; bottom: 8%; width: 30%; aspect-ratio: 1; border-radius: 50%;
  background: var(--hz-surface); display: grid !important; place-items: center; box-shadow: 0 6px 16px rgba(69,70,90,.16);
}
.hz-illus-badge .hz-mi { font-size: 2rem; }
.hz-illus:not(:has(.hz-sheet)) .hz-illus-badge { right: auto; bottom: auto; left: 47.5%; top: 24.7%; }
.hz-illus-sm .hz-illus-badge .hz-mi { font-size: 1.5rem; }
.hz-illus-lg .hz-illus-badge .hz-mi { font-size: 2.6rem; }

.hz-step { display: flex; align-items: center; gap: .8rem; margin: .6rem 0 -.1rem; }
.hz-step-num {
  font-family: var(--hz-font-display); font-style: italic; font-weight: 700; font-size: 2.4rem; line-height: 1;
  color: var(--hz-orange);
}
.hz-step-blue .hz-step-num { color: var(--hz-blue); }
.hz-step-teal .hz-step-num { color: var(--hz-teal); }
.hz-step-rule { flex: 1; height: 0; border-top: 3px dotted var(--hz-line); }

.hz-chip {
  display: inline-flex; align-items: center; gap: .4rem; padding: .3rem .8rem .3rem .55rem; border-radius: 999px;
  font-family: var(--hz-font-label); font-weight: 600; font-size: .95rem; letter-spacing: .07em; text-transform: uppercase;
}
.hz-chip .hz-mi { font-size: 1.15rem; }
.hz-chip-green { background: var(--hz-green-tint); color: var(--hz-green-ink); }
.hz-chip-orange { background: var(--hz-orange-tint); color: var(--hz-orange-ink); }
.hz-chip-red { background: var(--hz-red-tint); color: var(--hz-red-ink); }
.hz-chip-blue { background: var(--hz-blue-tint); color: var(--hz-blue-ink); }

/* ---------- Cards (bordered containers) ------------------------------------------------------ */
[data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]:not([class*="st-key-"]):not([role="dialog"] > div > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"] > *),
[data-testid="stLayoutWrapper"] > [class*="st-key-hzcard_"],
[data-testid="stLayoutWrapper"] > [class*="st-key-hzm_"] {
  background-color: var(--hz-surface);
  border-color: var(--hz-line) !important;
  border-radius: 16px !important;
  box-shadow: var(--hz-shadow);
}
.st-key-hzcard_winner { background: linear-gradient(120deg, #FFFFFF 55%, var(--hz-orange-tint)) !important; }
[data-testid="stSidebar"] [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]:not([class*="st-key-"]) { box-shadow: none; }
.st-key-hzcard_empty_queue, .st-key-hzcard_no_tender { text-align: center; }
.st-key-hzcard_empty_queue [data-testid="stCaptionContainer"] p { font-size: 1.02rem; }

/* ---------- Buttons --------------------------------------------------------------------------- */
:is([data-testid="stBaseButton-primary"], [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-tertiary"],
    [data-testid="stBaseLinkButton-primary"], [data-testid="stBaseLinkButton-secondary"]) {
  border-radius: 999px; min-height: 2.65rem; padding: .45rem 1.15rem;
  font-weight: 600; letter-spacing: .01em;
}
:is([data-testid="stBaseButton-primary"], [data-testid="stBaseLinkButton-primary"]) {
  background-color: var(--hz-blue-ink); border: 1px solid var(--hz-blue-ink); color: #FFFFFF;
}
:is([data-testid="stBaseButton-primary"], [data-testid="stBaseLinkButton-primary"]):hover:not(:disabled):not([disabled]) {
  background-color: #055A74; border-color: #055A74; color: #FFFFFF;
}
:is([data-testid="stBaseButton-secondary"], [data-testid="stBaseLinkButton-secondary"]) {
  background-color: var(--hz-surface); border: 1px solid var(--hz-line); color: var(--hz-text);
}
:is([data-testid="stBaseButton-secondary"], [data-testid="stBaseLinkButton-secondary"]):hover:not(:disabled):not([disabled]) {
  border-color: var(--hz-blue-ink); color: var(--hz-blue-ink); background-color: var(--hz-blue-tint);
}
:is([data-testid^="stBaseButton-"], [data-testid^="stBaseLinkButton-"]):focus-visible {
  outline: 3px solid var(--hz-blue) !important; outline-offset: 2px; box-shadow: none;
}
:is([data-testid="stBaseButton-primary"], [data-testid="stBaseButton-secondary"], [data-testid="stBaseLinkButton-primary"],
    [data-testid="stBaseLinkButton-secondary"]):is(:disabled, [disabled], [aria-disabled="true"]) {
  background-color: #EFEEEA !important; border-color: var(--hz-line) !important; color: #8E8F99 !important;
  box-shadow: none !important; transform: none !important; cursor: not-allowed;
}
/* Primary CTAs: arrow right after the label that nudges right on hover (not the sidebar navigation) */
[data-testid="stBaseButton-primary"] [data-testid="stMarkdownContainer"] p::after {
  content: "\\2192"; display: inline-block; margin-left: .55rem; font-weight: 600;
}
.st-key-sidebar_nav [data-testid="stBaseButton-primary"] [data-testid="stMarkdownContainer"] p::after { content: none; }
[data-testid="stBaseButton-primary"]:disabled [data-testid="stMarkdownContainer"] p::after { opacity: .6; }

/* Text-link CTAs: uppercase thin label + arrow */
:is(.st-key-go_add_btn, .st-key-go_verify_btn, .st-key-go_verify_from_bids) button {
  background: transparent !important; border: none !important; box-shadow: none !important; padding-left: .2rem; padding-right: .2rem;
  color: var(--hz-blue-ink) !important;
}
:is(.st-key-go_add_btn, .st-key-go_verify_btn, .st-key-go_verify_from_bids) button p {
  font-family: var(--hz-font-label); text-transform: uppercase; letter-spacing: .08em; font-weight: 600; font-size: 1rem;
  white-space: normal !important; overflow: visible !important; text-overflow: clip !important; text-align: left; line-height: 1.25;
}
:is(.st-key-go_add_btn, .st-key-go_verify_btn, .st-key-go_verify_from_bids) button p::after {
  content: "\\2192"; display: inline-block; margin-left: .45rem; color: var(--hz-orange); font-weight: 700;
}
:is(.st-key-go_add_btn, .st-key-go_verify_btn, .st-key-go_verify_from_bids) button:hover p { text-decoration: underline; text-underline-offset: 4px; }
.st-key-hzcard_no_tender .st-key-go_verify_from_bids { align-self: center; }

/* History button: top right of the view */
:is(.st-key-history_btn_verify, .st-key-history_btn_bids) { align-self: flex-end; z-index: 2; }

/* PDF data-URI link rendered as a secondary button */
a.pdf-download {
  display: block; text-align: center; padding: .6rem 1.1rem; border: 1px solid var(--hz-blue-ink);
  border-radius: 999px; background: var(--hz-surface); color: var(--hz-blue-ink) !important;
  font-weight: 600; text-decoration: none;
}
a.pdf-download::before {
  content: "picture_as_pdf"; font-family: "Material Symbols Rounded"; font-feature-settings: "liga";
  font-size: 1.25rem; vertical-align: -.25em; margin-right: .45rem; text-transform: none; letter-spacing: normal;
}
a.pdf-download:hover { background-color: var(--hz-blue-tint); }
a.pdf-download:focus-visible { outline: 3px solid var(--hz-blue); outline-offset: 2px; }

/* Gmail text link */
.stApp a[href^="https://mail.google.com"] {
  font-family: var(--hz-font-label); text-transform: uppercase; letter-spacing: .07em; font-weight: 600; text-decoration: none;
}
.stApp a[href^="https://mail.google.com"]::after { content: " \\2192"; color: var(--hz-orange); display: inline-block; }

/* ---------- Segmented controls (language, filters, criteria set) ------------------------------ */
[data-testid="stButtonGroup"] [role="radiogroup"] {
  background: var(--hz-warm-tint); border-radius: 999px; padding: 3px; gap: 3px; flex-wrap: wrap;
}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] {
  border: none !important; border-radius: 999px !important; background: transparent; color: var(--hz-muted);
  min-height: 2.2rem; margin: 0 !important; box-shadow: none;
}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] p { font-weight: 600; }
[data-testid="stButtonGroup"] button[data-variant="segmented_control"]:hover { color: var(--hz-blue-ink); background: rgba(255,255,255,.7); }
[data-testid="stButtonGroup"] button[data-variant="segmented_control"][aria-checked="true"] {
  background: var(--hz-surface); color: var(--hz-blue-ink); box-shadow: 0 1px 6px rgba(69, 70, 90, .14);
}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"]:focus-visible { outline: 3px solid var(--hz-blue); outline-offset: 1px; }
.st-key-lang_toggle [data-testid="stWidgetLabel"] p::before {
  content: "translate"; font-family: "Material Symbols Rounded"; font-feature-settings: "liga"; text-transform: none;
  letter-spacing: normal; font-size: 1.05rem; vertical-align: -.2em; margin-right: .35rem; color: var(--hz-blue-ink);
}

/* ---------- Inputs ---------------------------------------------------------------------------- */
/* Unchecked radios and checkboxes: a visible outline (non-text contrast >= 3:1) */
label[data-testid="stRadioOption"]:not([data-selected="true"]) > div > div:first-child,
[data-testid="stCheckbox"] label:not([data-selected="true"]) > span + div {
  box-shadow: inset 0 0 0 2px #8E8F99;
}
[data-testid="stCheckbox"] label:has(input:focus-visible) > span + div,
label[data-testid="stRadioOption"]:has(input:focus-visible) > div > div:first-child {
  outline: 3px solid var(--hz-blue); outline-offset: 2px;
}
:is([data-baseweb="textarea"], [data-baseweb="input"], [data-baseweb="select"] > div) {
  border-radius: 12px !important; background-color: var(--hz-surface);
}
:is([data-baseweb="textarea"], [data-baseweb="input"], [data-baseweb="select"] > div):focus-within {
  border-color: var(--hz-blue-ink) !important; box-shadow: 0 0 0 3px rgba(11, 153, 196, .22);
}

/* File uploader drop zone */
[data-testid="stFileUploaderDropzone"] {
  border: 2px dashed rgba(7, 106, 137, .45); border-radius: 16px;
  background: #F2F8FA; min-height: 5.5rem;
}
[data-testid="stFileUploaderDropzone"]:hover { border-color: var(--hz-blue-ink); box-shadow: 0 0 0 4px rgba(11, 153, 196, .16); background-color: #EAF5F9; }
[data-testid="stFileUploaderDropzone"][aria-disabled="true"] {
  border-color: var(--hz-line); background-color: #F3F2EE; filter: grayscale(1); opacity: .75; box-shadow: none;
}
[data-testid="stFileUploaderDropzone"][aria-disabled="true"]:hover { transform: none; }

/* ---------- Status messages ------------------------------------------------------------------ */
[data-testid="stAlertContainer"] {
  --hz-accent: var(--hz-blue); --hz-accent-ink: var(--hz-blue-ink);
  border-radius: 14px; border: 1px solid transparent; border-left: 6px solid var(--hz-accent);
  box-shadow: var(--hz-shadow);
}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) { --hz-accent: var(--hz-green-ink); --hz-accent-ink: var(--hz-green-ink); background-color: var(--hz-green-tint); }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) { --hz-accent: var(--hz-orange); --hz-accent-ink: var(--hz-orange-ink); background-color: var(--hz-orange-tint); }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) { --hz-accent: var(--hz-red); --hz-accent-ink: var(--hz-red-ink); background-color: var(--hz-red-tint); }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) { --hz-accent: var(--hz-blue); --hz-accent-ink: var(--hz-blue-ink); background-color: var(--hz-blue-tint); }
[data-testid="stAlertContainer"] [data-testid="stMarkdownContainer"], [data-testid="stAlertContainer"] [data-testid="stMarkdownContainer"] p { color: var(--hz-text); }
[data-testid="stAlertContainer"] :is([data-testid="stIconMaterial"], [data-testid="stAlertDynamicIcon"]) { color: var(--hz-accent-ink); font-size: 1.35rem; }
[data-testid="stAlertContainer"] code { background: rgba(255,255,255,.7); color: var(--hz-text); }

/* Badges: bold uppercase status words */
[data-testid="stMarkdownContainer"] span[class*="Badge"], .stBadge, [data-testid="stBadge"] {
  text-transform: uppercase; letter-spacing: .06em; font-weight: 700;
}

/* Toasts */
[data-testid="stToast"] {
  background: var(--hz-surface) !important; color: var(--hz-text); border: 1px solid var(--hz-line);
  border-left: 6px solid var(--hz-blue); border-radius: 14px !important; box-shadow: var(--hz-shadow-lift);
}
[data-testid="stToast"] [data-testid="stIconMaterial"] { color: var(--hz-blue-ink); }

/* Spinners in brand colours */
[data-testid="stSpinner"] i {
  border-color: var(--hz-line) !important; border-top-color: var(--hz-blue) !important; border-right-color: var(--hz-orange) !important;
}
[data-testid="stSpinner"] { color: var(--hz-muted); }

/* ---------- Expanders ------------------------------------------------------------------------- */
[data-testid="stExpander"] details {
  border: 1px solid var(--hz-line); border-radius: 14px; background: var(--hz-surface); box-shadow: var(--hz-shadow);
}
[data-testid="stExpander"] details:hover { border-color: #B9D6E0; }
[data-testid="stExpander"] summary { border-radius: 14px; }
[data-testid="stExpander"] summary:hover { color: var(--hz-blue-ink); }
[data-testid="stExpander"] summary:focus-visible { outline: 3px solid var(--hz-blue); outline-offset: 2px; }
[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] p { font-weight: 600; }
/* One chevron glyph that rotates instead of swapping */
[data-testid="stExpander"] summary > span > span:first-child [data-testid="stIconMaterial"] { font-size: 0 !important; width: 1.5rem; }
[data-testid="stExpander"] summary > span > span:first-child [data-testid="stIconMaterial"]::after {
  content: "chevron_right"; font-size: 1.5rem; display: inline-block; color: var(--hz-blue-ink);
}
[data-testid="stExpander"] details[open] > summary > span > span:first-child [data-testid="stIconMaterial"]::after { transform: rotate(90deg); }
[data-testid="stExpander"] summary > span > span:not(:first-child) [data-testid="stIconMaterial"] { color: var(--hz-blue-ink); }

/* ---------- Metrics --------------------------------------------------------------------------- */
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] > div { max-width: 100%; }
[data-testid="stMetricLabel"] .stMarkdownEllipsis, [data-testid="stMetricLabel"] p {
  white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
}
[data-testid="stMetricLabel"] p {
  font-family: var(--hz-font-label); text-transform: uppercase; letter-spacing: .07em; font-weight: 500;
  font-size: .95rem !important; color: var(--hz-muted);
}
[data-testid="stMetricValue"] {
  font-family: var(--hz-font-display); font-style: italic; font-weight: 700; color: var(--hz-blue-ink);
  font-size: clamp(1.9rem, 3.4vw, 2.6rem) !important; line-height: 1.1;
}
[data-testid="stMetricDelta"] svg { display: inline; }
[data-testid="stMetricDelta"]:has(svg[data-testid="stMetricDeltaIcon-Up"]) { color: var(--hz-green-ink); }
[data-testid="stMetricDelta"]:has(svg[data-testid="stMetricDeltaIcon-Down"]) { color: var(--hz-red-ink); }
[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [class*="st-key-hzm_"]) { align-items: stretch; }
[data-testid="stColumn"]:has([class*="st-key-hzm_"]) { display: flex; flex-direction: column; }
[data-testid="stColumn"]:has([class*="st-key-hzm_"]) > [data-testid="stVerticalBlock"],
[data-testid="stColumn"]:has([class*="st-key-hzm_"]) [data-testid="stLayoutWrapper"]:has(> [class*="st-key-hzm_"]) { flex: 1 1 auto; display: flex; flex-direction: column; }
[data-testid="stLayoutWrapper"] > [class*="st-key-hzm_"] {
  flex: 1 1 auto; height: 100%; border: 1px solid var(--hz-line); border-radius: 16px !important; padding: 1rem; justify-content: flex-start;
}
[class*="st-key-hzm_"] [data-testid="stMetricLabel"] { min-height: 2.7em; align-items: flex-start; flex: 1 0 auto; }
[class*="st-key-hzm_"] { position: relative; }
[class*="st-key-hzm_"] > [data-testid="stElementContainer"]:has([data-testid="stMetric"]) { flex: 1 1 auto; display: flex; }
[class*="st-key-hzm_"] [data-testid="stMetric"] { flex: 1 1 auto; display: flex; flex-direction: column; }
[class*="st-key-hzm_"] [data-testid="stMetric"] > div { flex: 1 1 auto; display: flex; flex-direction: column; }
/* Insights row: every card reserves the caption space; the one caption sits inside its card */
:is(.st-key-hzm_agreement, .st-key-hzm_overrides, .st-key-hzm_deferred, .st-key-hzm_transfers, .st-key-hzm_committee) { padding-bottom: 3.3rem !important; }
.st-key-hzm_agreement > [data-testid="stElementContainer"]:has([data-testid="stCaptionContainer"]) {
  position: absolute !important; left: 1rem; right: 1rem; bottom: .9rem; width: auto !important;
}
.st-key-hzm_agreement [data-testid="stCaptionContainer"] p { font-size: .88rem; line-height: 1.3; }
:is(.st-key-hzm_agreement, .st-key-hzm_overrides, .st-key-hzm_deferred, .st-key-hzm_transfers, .st-key-hzm_committee) [data-testid="stMetricLabel"] p {
  font-size: .86rem !important; letter-spacing: .025em; overflow-wrap: normal; word-break: normal;
}
[class*="st-key-hzm_"] [data-testid="stMetric"] { position: relative; padding-right: 3.2rem; }
[class*="st-key-hzm_"] [data-testid="stMetric"]::after {
  content: var(--hz-icon, "bar_chart"); position: absolute; top: .1rem; right: 0;
  font-family: "Material Symbols Rounded"; font-feature-settings: "liga"; font-size: 1.45rem; line-height: 1;
  display: grid; place-items: center; width: 2.6rem; height: 2.6rem; border-radius: 50%;
  background: var(--hz-m-tint, var(--hz-blue-tint)); color: var(--hz-m-ink, var(--hz-blue-ink));
}
[class*="st-key-hzm_"] [data-testid="stMetricValue"] { color: var(--hz-m-ink, var(--hz-blue-ink)); }
:is(.st-key-hzm_agreement, .st-key-hzm_overrides, .st-key-hzm_deferred, .st-key-hzm_transfers, .st-key-hzm_committee) [data-testid="stMetric"] {
  padding-right: 0; padding-top: 3.1rem;
}
:is(.st-key-hzm_agreement, .st-key-hzm_overrides, .st-key-hzm_deferred, .st-key-hzm_transfers, .st-key-hzm_committee) [data-testid="stMetric"]::after {
  left: 0; right: auto; top: 0;
}
.st-key-hzm_pending { --hz-icon: "pending"; --hz-m-ink: var(--hz-orange-ink); --hz-m-tint: var(--hz-orange-tint); }
.st-key-hzm_approved { --hz-icon: "check_circle"; --hz-m-ink: var(--hz-green-ink); --hz-m-tint: var(--hz-green-tint); }
.st-key-hzm_rejected { --hz-icon: "cancel"; --hz-m-ink: var(--hz-red-ink); --hz-m-tint: var(--hz-red-tint); }
.st-key-hzm_points { --hz-icon: "emoji_events"; --hz-m-ink: var(--hz-orange-ink); --hz-m-tint: var(--hz-orange-tint); }
.st-key-hzm_price { --hz-icon: "euro"; }
.st-key-hzm_lead { --hz-icon: "trending_up"; --hz-m-ink: var(--hz-green-ink); --hz-m-tint: var(--hz-green-tint); }
.st-key-hzm_agreement { --hz-icon: "handshake"; --hz-m-ink: var(--hz-green-ink); --hz-m-tint: var(--hz-green-tint); }
.st-key-hzm_overrides { --hz-icon: "swap_horiz"; --hz-m-ink: var(--hz-orange-ink); --hz-m-tint: var(--hz-orange-tint); }
.st-key-hzm_deferred { --hz-icon: "person"; }
.st-key-hzm_transfers { --hz-icon: "account_balance"; }
.st-key-hzm_committee { --hz-icon: "groups"; }

/* ---------- Dataframes, charts, tooltips ----------------------------------------------------- */
[data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; box-shadow: var(--hz-shadow); background: var(--hz-surface); }
#vg-tooltip-element, .vg-tooltip {
  font-family: var(--hz-font-body) !important; color: var(--hz-text) !important; background: rgba(255,255,255,.97) !important;
  border: 1px solid var(--hz-line) !important; border-radius: 10px !important; box-shadow: var(--hz-shadow-lift) !important;
}

/* ---------- Dialogs --------------------------------------------------------------------------- */
[data-testid="stDialog"] { background-color: rgba(69, 70, 90, .34) !important; backdrop-filter: blur(3px); }
[data-testid="stDialog"] > div { border-radius: 22px !important; background-color: var(--hz-surface); box-shadow: 0 24px 60px rgba(69, 70, 90, .28); }
section[role="dialog"] > button[aria-label="Close"] { border-radius: 50%; }
section[role="dialog"] > button[aria-label="Close"]:hover { background: var(--hz-warm-tint); }
section[role="dialog"] > button[aria-label="Close"]:focus-visible { outline: 3px solid var(--hz-blue); outline-offset: 2px; }

/* ---------- Sidebar --------------------------------------------------------------------------- */
[data-testid="stSidebar"] { background-color: var(--hz-surface); border-right: 1px solid var(--hz-line); }
[data-testid="stSidebarUserContent"] { padding-top: .25rem; }
.hz-brand-mark { position: relative; isolation: isolate; width: 64px; height: 40px; margin: 0 0 .1rem -2px; }
.hz-brand-mark span { position: absolute; border-radius: 50%; mix-blend-mode: multiply; opacity: .85; }
.hz-brand-mark span:nth-child(1) { left: 4px; top: 6px; width: 28px; height: 28px; }
.hz-brand-mark span:nth-child(2) { left: 22px; top: 10px; width: 24px; height: 24px; }
.hz-brand-mark span:nth-child(3) { left: 37px; top: 7px; width: 20px; height: 20px; }
.st-key-hzbrand .gov-meta { line-height: 1.3; align-items: flex-start; }
.st-key-hzbrand [data-testid="stMarkdownContainer"] p strong {
  font-family: var(--hz-font-display); font-style: italic; font-weight: 700; text-transform: uppercase;
  font-size: 1.04rem; line-height: 1.1; color: var(--hz-text); display: block; letter-spacing: 0;
}
.st-key-hzbrand .gov-meta { font-size: .82rem; }
.st-key-hzbrand .gov-meta::before { flex-basis: 18px; margin-top: .55em; }

/* Sidebar navigation: full-width list items, active item highlighted */
.st-key-sidebar_nav { gap: .2rem; }
.st-key-sidebar_nav div.stButton > button {
  justify-content: flex-start; text-align: left; border: none; border-radius: 12px;
  background-color: transparent; color: var(--hz-text); box-shadow: none;
  padding: .55rem .8rem .55rem 1rem; min-height: 2.8rem; position: relative; overflow: hidden;
}
.st-key-sidebar_nav div.stButton > button * { text-align: left; justify-content: flex-start; }
.st-key-sidebar_nav div.stButton > button p {
  font-family: var(--hz-font-label); text-transform: uppercase; letter-spacing: .07em; font-weight: 500; font-size: 1.02rem;
}
.st-key-sidebar_nav div.stButton > button [data-testid="stIconMaterial"] { color: var(--hz-muted); font-size: 1.3rem; }
.st-key-sidebar_nav div.stButton > button::before {
  content: ""; position: absolute; left: 0; top: 18%; bottom: 18%; width: 4px; border-radius: 0 4px 4px 0;
  background: var(--hz-orange); transform: scaleY(0); transform-origin: center;
}
.st-key-sidebar_nav div.stButton > button:hover { background-color: var(--hz-warm-tint); color: var(--hz-text); }
.st-key-sidebar_nav div.stButton > button:hover::before { transform: scaleY(1); }
.st-key-sidebar_nav div.stButton > button:hover [data-testid="stIconMaterial"] { color: var(--hz-orange-ink); }
.st-key-sidebar_nav div.stButton > button[kind="primary"],
.st-key-sidebar_nav div.stButton > button[data-testid="stBaseButton-primary"] {
  background-color: var(--hz-blue-tint); color: var(--hz-blue-ink); border: none;
}
.st-key-sidebar_nav div.stButton > button[data-testid="stBaseButton-primary"] p { font-weight: 600; }
.st-key-sidebar_nav div.stButton > button[data-testid="stBaseButton-primary"] [data-testid="stIconMaterial"] { color: var(--hz-blue-ink); }
.st-key-sidebar_nav div.stButton > button[data-testid="stBaseButton-primary"]::before { transform: scaleY(1); background: var(--hz-blue-ink); }
.st-key-sidebar_nav div.stButton > button[data-testid="stBaseButton-primary"]::after {
  content: ""; width: 9px; height: 9px; margin-left: auto; border-radius: 50%; background: var(--hz-orange); flex: 0 0 9px;
}
.st-key-sidebar_nav div.stButton > button:focus-visible { outline: 3px solid var(--hz-blue) !important; outline-offset: -3px; }

/* Sidebar budget meters: one block per position, each bar scaled to its own total */
.budget-total {
  font-size: .9rem; color: var(--hz-text); margin: 0 0 .9rem; padding: .55rem .75rem;
  background: var(--hz-warm-tint); border-radius: 12px; font-weight: 500;
}
.budget-meter { margin: 0 0 1rem; }
.budget-meter-head, .budget-meter-caption { display: flex; justify-content: space-between; align-items: baseline; gap: .5rem; }
.budget-meter-head { font-size: .92rem; margin-bottom: .35rem; align-items: center; flex-wrap: wrap; column-gap: .45rem; row-gap: .1rem; }
.budget-meter-icon {
  font-family: "Material Symbols Rounded"; font-feature-settings: "liga"; font-size: 1.1rem; line-height: 1;
  color: var(--hz-blue-ink); flex: 0 0 auto; text-transform: none; letter-spacing: normal;
}
.budget-meter-name {
  font-weight: 600; color: var(--hz-text); min-width: 0; overflow-wrap: break-word; flex: 1 1 auto;
  font-family: var(--hz-font-label); text-transform: uppercase; letter-spacing: .05em; font-size: .98rem;
}
.budget-meter-left { color: var(--hz-text); white-space: nowrap; font-weight: 500; margin-left: auto; }
.budget-meter-left.over { color: var(--hz-red-ink); font-weight: 700; }
.budget-meter-track { height: 10px; border-radius: 999px; background-color: #ECEAE4; overflow: hidden; }
.budget-meter-fill { height: 100%; border-radius: 999px; }
.budget-meter-fill.ok { background-image: linear-gradient(90deg, var(--hz-sage), var(--hz-green-ink)); }
.budget-meter-fill.warn { background-image: linear-gradient(90deg, #E9A266, var(--hz-orange)); }
.budget-meter-fill.over { background-image: linear-gradient(90deg, #E68597, var(--hz-red)); }
.budget-meter-caption { font-size: .8rem; color: var(--hz-muted); margin-top: .3rem; }

/* Sidebar toggle: a hamburger icon (Material "menu") in both states, at the same spot,
   always visible. Streamlit's own buttons and toggle behaviour are kept; only the icon
   (a Material Symbols ligature) is swapped. */
[data-testid="stSidebarCollapseButton"] {
  visibility: visible !important; opacity: 1 !important;
  order: -1;  /* left end of the sidebar header, where the expand button sits when collapsed */
  position: relative;
  left: -11px;  /* same x as the expand button (19px), so the icon does not jump; no layout effect */
}
[data-testid="stSidebarCollapseButton"] button, button[data-testid="stExpandSidebarButton"] { border-radius: 50%; }
[data-testid="stSidebarCollapseButton"] button:hover, button[data-testid="stExpandSidebarButton"]:hover { background-color: var(--hz-blue-tint); }
[data-testid="stSidebarCollapseButton"] button:focus-visible, button[data-testid="stExpandSidebarButton"]:focus-visible {
  outline: 3px solid var(--hz-blue); outline-offset: 2px;
}
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"],
[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"] { font-size: 0 !important; }
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"]::after,
[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"]::after {
  content: "menu"; font-family: "Material Symbols Rounded"; font-size: 24px; line-height: 1;
  color: var(--hz-blue-ink); display: inline-block; vertical-align: middle;
}

/* ---------- Help assistant: round button fixed at the bottom right, themed panel ---------------- */
.st-key-help_chat { position: fixed; right: 1.5rem; bottom: 1.5rem; z-index: 999; width: auto !important; }
.st-key-help_chat button {
  position: relative; width: 3.5rem; height: 3.5rem; min-height: 3.5rem; border-radius: 50%; padding: 0;
  background-color: var(--hz-blue-ink); border: none; color: #FFFFFF;
  box-shadow: 0 8px 20px rgba(7, 106, 137, .32);
}
.st-key-help_chat button::after {  /* decorative orange dot */
  content: ""; position: absolute; top: 2px; right: 2px; width: 13px; height: 13px; border-radius: 50%;
  background: var(--hz-orange); box-shadow: 0 0 0 3px var(--hz-paper);
}
.st-key-help_chat button:hover { background-color: #055A74; color: #FFFFFF; }
.st-key-help_chat button[aria-expanded="true"], .st-key-help_chat button:focus, .st-key-help_chat button:active {
  background-color: var(--hz-blue-ink); color: #FFFFFF;
}
.st-key-help_chat button:focus-visible { outline: 3px solid var(--hz-blue); outline-offset: 3px; }
/* The emoji label is replaced visually by a Material chat glyph (the label text itself is unchanged) */
.st-key-help_chat button p { font-size: 0 !important; line-height: 1; }
.st-key-help_chat button p::before {
  content: "chat"; font-family: "Material Symbols Rounded"; font-feature-settings: "liga"; font-size: 1.75rem;
  text-transform: none; letter-spacing: normal; color: #FFFFFF; display: inline-block;
}
.st-key-help_chat button [data-testid="stIconMaterial"] { display: none; }  /* no dropdown chevron */
[data-testid="stPopoverBody"]:has(.st-key-help_chat_panel) {
  width: 360px; max-width: calc(100vw - 2rem); border: 1px solid var(--hz-line) !important; border-radius: 16px !important;
  background: var(--hz-surface) !important; box-shadow: var(--hz-shadow-lift) !important;
}
.st-key-help_chat_panel > [data-testid="stElementContainer"]:first-child strong {
  display: flex; align-items: center; gap: .55rem;
  font-family: var(--hz-font-display); font-style: italic; font-weight: 700; text-transform: uppercase;
  font-size: 1.3rem; color: var(--hz-text); line-height: 1.1;
}
.st-key-help_chat_panel > [data-testid="stElementContainer"]:first-child strong::before {
  content: ""; flex: 0 0 14px; height: 14px; border-radius: 50%;
  background: radial-gradient(circle at 35% 35%, var(--hz-blue) 0 55%, transparent 56%), var(--hz-orange);
}
[class*="st-key-help_chat_starter_"] button {
  border-radius: 999px !important; border: 1px solid #B9D6E0 !important; background: var(--hz-blue-tint) !important;
  color: var(--hz-blue-ink) !important; justify-content: flex-start; text-align: left; min-height: 2.3rem;
}
[class*="st-key-help_chat_starter_"] button p { font-weight: 500; white-space: normal; text-align: left; }
[class*="st-key-help_chat_starter_"] button:hover { border-color: var(--hz-blue-ink) !important; background: #D8EDF4 !important; }
.st-key-help_chat_panel [data-testid="stChatMessage"] { border-radius: 14px; padding: .6rem .75rem; background: var(--hz-paper); }
.st-key-help_chat_panel [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { background: var(--hz-blue-tint); }
.st-key-help_chat_clear button { color: var(--hz-blue-ink) !important; padding-left: 0; }
.st-key-help_chat_clear button p {
  font-family: var(--hz-font-label); text-transform: uppercase; letter-spacing: .07em; font-weight: 600;
}
.st-key-help_chat_clear button p::after { content: " \\2192"; color: var(--hz-orange); display: inline-block; }
.st-key-help_chat_panel [data-testid="stChatInput"] { border-radius: 14px; }
.st-key-help_chat_panel [data-testid="stChatInput"]:focus-within { box-shadow: 0 0 0 3px rgba(11, 153, 196, .22); border-color: var(--hz-blue-ink); }
/* The help button never covers content: bottom padding, and a right gutter on wide screens */
[data-testid="stMainBlockContainer"] { padding-bottom: 7.5rem !important; }
@media (min-width: 641px) {
  [data-testid="stMain"]:has(.st-key-help_chat) [data-testid="stMainBlockContainer"] { padding-right: 6.75rem !important; }
}
/* Phones: the help button sits in the (empty) top header bar, left of the menu, above all content */
@media (max-width: 640px) {
  .st-key-help_chat { top: .5rem; bottom: auto; right: 3.4rem; z-index: 1000001; }
  .st-key-help_chat button { width: 2.75rem; height: 2.75rem; min-height: 2.75rem; box-shadow: 0 4px 12px rgba(7, 106, 137, .28); }
  .st-key-help_chat button::after { width: 10px; height: 10px; top: 0; right: 0; }
  .st-key-help_chat button p::before { font-size: 1.4rem; }
  [data-testid="stMainBlockContainer"] { padding-bottom: 3rem !important; }
}

/* ---------- Startup gate ---------------------------------------------------------------------- */
.st-key-hzgate { max-width: 760px; margin: 4vh auto 0; position: relative; }
.st-key-hzgate [data-testid="stAlertContainer"] { box-shadow: var(--hz-shadow-lift); }

/* ---------- Narrow screens -------------------------------------------------------------------- */
@media (max-width: 900px) {
  [class*="st-key-hzhero_"] { padding-right: 170px; }
  [class*="st-key-hzhero_"] > [data-testid="stElementContainer"]:has(.hz-hero-art) { width: 170px !important; }
  .hz-hero-art { transform: scale(.72); transform-origin: right center; }
}
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"] { padding-top: 4.75rem; }
  [class*="st-key-hzhero_"] { padding-right: 0; min-height: 0; padding-top: 5.4rem; }
  [class*="st-key-hzhero_"] > [data-testid="stElementContainer"]:has(.hz-hero-art) {
    top: 0; transform: none; width: 120px !important; height: 92px; overflow: visible;
  }
  .hz-hero-art { position: absolute; right: 0; top: 0; transform: scale(.48); transform-origin: top right; }
  :is(.st-key-history_btn_verify, .st-key-history_btn_bids) { margin-bottom: 0; align-self: flex-start; }
  .hz-step-num { font-size: 2rem; }
}
"""

# Motion: only for users who did not ask for reduced motion. Every animation runs on mount.
_MOTION_CSS = """
@media (prefers-reduced-motion: no-preference) {
  @keyframes hz-fade { from { opacity: 0; } to { opacity: 1; } }
  @keyframes hz-rise { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
  @keyframes hz-pop { from { opacity: 0; transform: scale(.98); } to { opacity: 1; transform: none; } }
  @keyframes hz-panel { from { opacity: 0; transform: scale(.96); } to { opacity: 1; transform: none; } }
  @keyframes hz-check { 0% { transform: scale(0) rotate(-30deg); } 60% { transform: scale(1.18) rotate(6deg); } 100% { transform: none; } }
  @keyframes hz-grow { from { clip-path: inset(0 100% 0 0); } to { clip-path: inset(0 0 0 0); } }
  @keyframes hz-toast { from { opacity: 0; transform: translateX(28px); } to { opacity: 1; transform: none; } }
  @keyframes hz-float-a { from { transform: translate(0, 0); } to { transform: translate(-3px, -5px); } }
  @keyframes hz-float-b { from { transform: translate(0, 0); } to { transform: translate(4px, 3px); } }
  @keyframes hz-float-c { from { transform: translate(0, 0); } to { transform: translate(-2px, 5px); } }

  /* 3. Buttons: lift on hover, press, arrow nudge */
  :is([data-testid="stBaseButton-primary"], [data-testid="stBaseButton-secondary"], [data-testid="stBaseLinkButton-primary"],
      [data-testid="stBaseLinkButton-secondary"], a.pdf-download) {
    transition: transform 180ms var(--hz-ease), box-shadow 220ms var(--hz-ease), background-color 180ms ease, border-color 180ms ease, color 180ms ease;
  }
  :is([data-testid="stBaseButton-primary"], [data-testid="stBaseButton-secondary"], [data-testid="stBaseLinkButton-primary"],
      [data-testid="stBaseLinkButton-secondary"], a.pdf-download):hover:not(:disabled):not([disabled]):not([aria-disabled="true"]) {
    transform: translateY(-2px); box-shadow: 0 8px 18px rgba(7, 106, 137, .18);
  }
  :is([data-testid="stBaseButton-primary"], [data-testid="stBaseButton-secondary"], [data-testid="stBaseLinkButton-primary"],
      [data-testid="stBaseLinkButton-secondary"], a.pdf-download):active:not(:disabled):not([disabled]) {
    transform: scale(.97); box-shadow: none; transition-duration: 90ms;
  }
  [data-testid="stBaseButton-primary"] [data-testid="stMarkdownContainer"] p::after,
  :is(.st-key-go_add_btn, .st-key-go_verify_btn, .st-key-go_verify_from_bids) button p::after { transition: transform 260ms var(--hz-ease); }
  [data-testid="stBaseButton-primary"]:hover:not(:disabled) [data-testid="stMarkdownContainer"] p::after,
  :is(.st-key-go_add_btn, .st-key-go_verify_btn, .st-key-go_verify_from_bids) button:hover p::after { transform: translateX(5px); }
  :is(.st-key-go_add_btn, .st-key-go_verify_btn, .st-key-go_verify_from_bids) button:hover { transform: none !important; box-shadow: none !important; }
  .stApp a[href^="https://mail.google.com"]::after { transition: transform 260ms var(--hz-ease); }
  .stApp a[href^="https://mail.google.com"]:hover::after { transform: translateX(5px); }

  /* 5. Sidebar navigation */
  .st-key-sidebar_nav div.stButton > button { transition: transform 220ms var(--hz-ease), background-color 200ms ease, color 200ms ease; }
  .st-key-sidebar_nav div.stButton > button::before { transition: transform 260ms var(--hz-ease); }
  .st-key-sidebar_nav div.stButton > button:hover { transform: translateX(4px); box-shadow: none; }
  .st-key-sidebar_nav div.stButton > button:active { transform: translateX(4px) scale(.98); }

  /* 6. Cards and expanders */
  [data-testid="stExpander"] details { transition: border-color 220ms ease, box-shadow 260ms var(--hz-ease), transform 260ms var(--hz-ease); }
  [data-testid="stExpander"] details:hover { transform: translateY(-1px); box-shadow: var(--hz-shadow-lift); }
  [data-testid="stExpander"] summary > span > span:first-child [data-testid="stIconMaterial"]::after { transition: transform 260ms var(--hz-ease); }

  /* 7. Budget meters fill on first appearance */
  .budget-meter-fill { animation: hz-grow 700ms var(--hz-ease) 150ms backwards; }

  /* 8. Status messages pop in; success icon draws in */
  [data-testid="stAlert"] { animation: hz-pop 380ms var(--hz-ease) backwards; }
  [data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) :is([data-testid="stIconMaterial"], [data-testid="stAlertDynamicIcon"]) {
    animation: hz-check 600ms var(--hz-ease) 120ms backwards;
  }
  .hz-illus, .hz-chip { animation: hz-pop 460ms var(--hz-ease) backwards; }
  .hz-illus-badge { animation: hz-check 640ms var(--hz-ease) 200ms backwards; }

  /* 9. Dialogs */
  [data-testid="stDialog"] { animation: hz-fade 240ms ease backwards; }
  [data-testid="stDialog"] > div { animation: hz-panel 340ms var(--hz-ease) backwards; }

  /* 10. Segmented controls */
  [data-testid="stButtonGroup"] button[data-variant="segmented_control"] {
    transition: background-color 240ms var(--hz-ease), color 200ms ease, box-shadow 240ms var(--hz-ease);
  }

  /* 11. File uploader */
  [data-testid="stFileUploaderDropzone"] {
    transition: transform 240ms var(--hz-ease), box-shadow 240ms var(--hz-ease), border-color 200ms ease, background-color 200ms ease;
  }
  [data-testid="stFileUploaderDropzone"]:not([aria-disabled="true"]):hover { transform: scale(1.01); }

  /* 12. Metrics */
  [data-testid="stMetricValue"] { animation: hz-rise 520ms var(--hz-ease) 120ms backwards; }

  /* 13. Toasts */
  [data-testid="stToast"] { animation: hz-toast 420ms var(--hz-ease) backwards; }

  /* Inputs */
  :is([data-baseweb="textarea"], [data-baseweb="input"], [data-baseweb="select"] > div) { transition: box-shadow 200ms ease, border-color 200ms ease; }

  /* 2. Hero circles: very slow float (the only infinite animation besides spinners) */
  .hz-hero-art .hz-c1 { animation: hz-float-a 8s ease-in-out infinite alternate; }
  .hz-hero-art .hz-c2 { animation: hz-float-b 9.5s ease-in-out infinite alternate; }
  .hz-hero-art .hz-c3 { animation: hz-float-c 7s ease-in-out infinite alternate; }

  /* Startup screen */
  .st-key-hzgate { animation: hz-rise 560ms var(--hz-ease) backwards; }
}
"""


def _entrance_css(views) -> str:
    """1. View entrance: the first blocks of the main column fade in and slide up, staggered.

    One keyframe name per view: switching the view changes the animation name, so the entrance
    replays on a view change, but never on a rerun within the same view."""
    rules = []
    for view in views:
        rules.append(f"@keyframes hz-enter-{view} {{ from {{ opacity: 0; transform: translateY(12px); }} to {{ opacity: 1; transform: none; }} }}")
        scope = f'[data-testid="stMain"]:has(.st-key-hzhero_{view}) [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"]'
        rules.append(f"{scope} > :nth-child(-n+7) {{ animation: hz-enter-{view} 520ms var(--hz-ease) backwards; }}")
        for index in range(2, 8):
            rules.append(f"{scope} > :nth-child({index}) {{ animation-delay: {(index - 1) * 50}ms; }}")
    return "@media (prefers-reduced-motion: no-preference) {\n" + "\n".join(rules) + "\n}\n"


def css(views=tuple(VIEW_ART)) -> str:
    """The complete <style> block (fonts, theme, components, motion)."""
    faces = "\n".join(
        f'@font-face {{ font-family: "{family}"; src: url("app/static/fonts/{file}") format("woff2"); '
        f"font-weight: {weight}; font-style: {style}; font-display: swap; }}"
        for family, file, weight, style in _FONT_FACES
    )
    base = (_BASE_CSS.replace("__DISPLAY__", FONT_DISPLAY).replace("__LABEL__", FONT_LABEL)
            .replace("__BODY__", FONT_BODY).replace("__NOISE__", _NOISE))
    return f"<style>\n{faces}\n{base}\n{_MOTION_CSS}\n{_entrance_css(views)}</style>"
