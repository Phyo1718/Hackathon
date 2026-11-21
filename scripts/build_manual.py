"""Builds the user manual: docs/Benutzerhandbuch.pdf (DE) and docs/User_Manual.pdf (EN).

    python scripts/build_manual.py                   # diagrams, fresh screenshots, both PDFs
    python scripts/build_manual.py --no-screenshots  # reuse docs/manual/img/

Steps, all offline in headless Chrome (no CDN):
1. Diagrams: docs/manual/diagrams/*.mmd -> .svg (embedded in the PDF) and .png (slides), rendered
   with the local Mermaid copy in scripts/manual/node_modules (installed from
   scripts/manual/package.json on the first run).
2. Screenshots: starts the app on a free port with its own temporary database, clicks
   "Reset Demo Data", walks through the demo in DE and EN and saves cropped screenshots with
   numbered red markers to docs/manual/img/.
3. PDF: docs/manual/user_manual_{de,en}.md -> HTML (local marked copy, print CSS in the app's
   navy and Source Sans) -> PDF via Chrome's print function.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chrome_cdp import Chrome, free_port  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "docs" / "manual"
IMG = MANUAL / "img"
DIAGRAMS = MANUAL / "diagrams"
NODE_DIR = ROOT / "scripts" / "manual"
MERMAID_JS = NODE_DIR / "node_modules" / "mermaid" / "dist" / "mermaid.min.js"
MARKED_JS = NODE_DIR / "node_modules" / "marked" / "lib" / "marked.umd.js"
FIXTURES = ROOT / "tests" / "fixtures"
PDF_OUT = {"de": ROOT / "docs" / "Benutzerhandbuch.pdf", "en": ROOT / "docs" / "User_Manual.pdf"}
VERSION = "1.0 (Hackathon-Prototyp)"

# One window size for every screenshot; rendered at 2x for sharp images in the PDF
WINDOW = (1440, 1800)
SCALE = 2
NAVY = "#1E3A8A"

MERMAID_CONFIG = {
    "startOnLoad": False,
    "theme": "base",
    "securityLevel": "loose",
    # Compact spacing and a large font, so the text stays readable when a diagram is scaled to A4
    # Line breaks come from the <br/> in the sources only (wrappingWidth above any label width);
    # subgraph titles get their own margin so they never touch the first box
    "flowchart": {"htmlLabels": False, "curve": "basis", "padding": 8, "nodeSpacing": 22, "rankSpacing": 24,
                  "useMaxWidth": False, "wrappingWidth": 420, "subGraphTitleMargin": {"top": 4, "bottom": 10}},
    "themeVariables": {
        "fontFamily": "Source Sans, Helvetica, Arial, sans-serif", "fontSize": "20px", "lineColor": "#475569",
        "clusterBkg": "#F8FAFC", "clusterBorder": "#CBD5E1", "primaryTextColor": "#0F172A",
        "edgeLabelBackground": "#FFFFFF",
    },
}


def source_sans() -> Path:
    """Source Sans as shipped with Streamlit (the app's font), so no font download is needed."""
    import streamlit
    media = Path(streamlit.__file__).parent / "static" / "static" / "media"
    return next(media.glob("SourceSansVF-Upright*.woff2"))


def font_face_css() -> str:
    return (f"@font-face {{ font-family: 'Source Sans'; src: url('{source_sans().as_uri()}') format('woff2'); "
            "font-weight: 200 900; }")


def ensure_node_modules() -> None:
    if MERMAID_JS.exists() and MARKED_JS.exists():
        return
    print("Installing the local Mermaid/marked copies (scripts/manual/package.json) ...")
    cache = Path(tempfile.gettempdir()) / "procurement-manual-npm-cache"
    subprocess.run(["npm", "install", "--no-audit", "--no-fund", "--cache", str(cache)], cwd=NODE_DIR, check=True)


# ==============================================================================================
# 1. Diagrams
# ==============================================================================================


def render_diagrams(chrome: Chrome, work: Path) -> None:
    page = work / "mermaid.html"
    page.write_text(
        f"""<!doctype html><html><head><meta charset="utf-8"><style>{font_face_css()}
        body {{ margin: 0; background: #FFFFFF; font-family: 'Source Sans'; }}
        #out {{ display: inline-block; padding: 12px; background: #FFFFFF; }}</style>
        <script src="{MERMAID_JS.as_uri()}"></script></head><body><div id="out"></div></body></html>""",
        encoding="utf-8",
    )
    chrome.set_viewport(2400, 2400, SCALE)
    chrome.navigate(page.as_uri(), 1.0)
    chrome.eval("document.fonts.load('17px \"Source Sans\"').then(() => document.fonts.ready).then(() => true)")
    chrome.eval(f"mermaid.initialize({json.dumps(MERMAID_CONFIG)}); true")
    for source in sorted(DIAGRAMS.glob("*.mmd")):
        diagram_id = "d_" + re.sub(r"\W", "_", source.stem)
        rect = chrome.eval(
            f"""(async () => {{
                const {{svg}} = await mermaid.render({json.dumps(diagram_id)}, {json.dumps(source.read_text(encoding="utf-8"))});
                const out = document.getElementById('out'); out.innerHTML = svg;
                const r = out.getBoundingClientRect();
                return {{x: r.x, y: r.y, width: Math.ceil(r.width), height: Math.ceil(r.height)}};
            }})()"""
        )
        svg = chrome.eval("document.querySelector('#out svg').outerHTML")
        source.with_suffix(".svg").write_text(svg, encoding="utf-8")
        chrome.screenshot(source.with_suffix(".png"), rect)
        print(f"  diagram {source.stem}: {rect['width']}x{rect['height']} px")
    chrome.set_viewport(*WINDOW, SCALE)


# ==============================================================================================
# 2. Screenshots
# ==============================================================================================

# Text the walkthrough clicks or looks for, per UI language (identical to the app's labels)
UI = {
    "de": {
        "lang_btn": "DE", "reset": "Demo-Daten zurücksetzen", "manual": "Benutzerhandbuch", "history": "Verlauf",
        "nav_verify": "Antragsprüfung", "nav_bids": "Angebotswertung", "nav_add": "Beschaffungsantrag erfassen",
        "nav_insights": "Management-Übersicht", "approve": "Genehmigen und Budget belasten", "reject": "Ablehnen",
        "decision": "Entscheidung der Sachbearbeitung", "issues": "Offene Punkte", "transfer": "Budgetverschiebung möglich",
        "transfer_include": "Budgetverschiebung aus", "note": "Vermerk der Sachbearbeitung", "pdf": "Antragsentwurf",
        "samples": "Beispielanträge", "submit": "Zur Prüfung einreichen", "table": "Angebotsdaten",
        "committee": "Wertungskommission", "breakdown": "Punktevorschlag des Agenten", "run": "Wertung starten",
        "winner": "Empfohlener Bieter", "matrix": "Wertungsmatrix", "letters": "Zuschlags- und Absageschreiben",
        "approval": "Zuschlag freigegeben", "email": "E-Mail", "gmail": "In Gmail öffnen", "sent": "Als versandt markieren",
        "tile_budget": "Budget je Haushaltsposition", "tile_suppliers": "Lieferantenanteil",
        "tile_oversight": "Aufsicht über den Agenten", "how": "So funktioniert",
    },
    "en": {
        "lang_btn": "EN", "reset": "Reset Demo Data", "manual": "User manual", "history": "History",
        "nav_verify": "Request Verification", "nav_bids": "Bid Evaluation", "nav_add": "Add Procurement Request",
        "nav_insights": "Management Insights", "approve": "Approve & Commit to Budget", "reject": "Reject",
        "decision": "Caseworker decision", "issues": "Open issues", "transfer": "Budget transfer possible",
        "transfer_include": "Include budget transfer from", "note": "Caseworker note", "pdf": "Download draft application",
        "samples": "Sample requests", "submit": "Submit for Verification", "table": "Bid data",
        "committee": "evaluation committee has reviewed", "breakdown": "Agent scoring breakdown", "run": "Run Evaluation",
        "winner": "Recommended supplier", "matrix": "Scoring matrix", "letters": "Award and rejection letters",
        "approval": "Award approved", "email": "Email", "gmail": "Open in Gmail", "sent": "Mark as sent",
        "tile_budget": "Budget per line", "tile_suppliers": "Supplier share", "tile_oversight": "AI oversight",
        "how": "How it works",
    },
}

# Finds elements by text and draws numbered markers (red outline + number) for the screenshots
PAGE_HELPERS = r"""
window.M = {
  vis(e) { return !!e && e.offsetParent !== null; },
  root(r) { return r ? (typeof r === 'string' ? document.querySelector(r) : r) : document; },
  q(sel, text, r) {
    const all = [...M.root(r).querySelectorAll(sel)].filter(M.vis);
    return text == null ? all[0] : all.find(e => (e.innerText || '').trim().includes(text));
  },
  qa(sel, r) { return [...M.root(r).querySelectorAll(sel)].filter(M.vis); },
  up(e, sel) { return e && e.closest(sel); },
  bordered(e) { return getComputedStyle(e).borderTopWidth !== '0px'; },
  boxes(r) { return M.qa('[data-testid=stVerticalBlock]', r).filter(M.bordered); },
  box(e) { while (e && !(e.dataset && e.dataset.testid === 'stVerticalBlock' && M.bordered(e))) e = e.parentElement; return e; },
  rect(e) { const r = e.getBoundingClientRect(); return {x: r.left, y: r.top, width: r.width, height: r.height}; },
  mark(e, n) {
    if (!e) return false;
    const r = e.getBoundingClientRect();
    const box = document.createElement('div'), badge = document.createElement('div');
    box.className = badge.className = '__mk';
    Object.assign(box.style, {position: 'fixed', left: (r.left - 5) + 'px', top: (r.top - 5) + 'px',
      width: (r.width + 10) + 'px', height: (r.height + 10) + 'px', border: '3px solid #DC2626',
      borderRadius: '8px', zIndex: 2147483647, pointerEvents: 'none', boxSizing: 'border-box'});
    badge.textContent = n;
    Object.assign(badge.style, {position: 'fixed', left: (r.left - 17) + 'px', top: (r.top - 17) + 'px',
      width: '26px', height: '26px', borderRadius: '13px', background: '#DC2626', color: '#FFFFFF',
      font: "700 15px 'Source Sans Pro', 'Source Sans', sans-serif", display: 'flex', alignItems: 'center',
      justifyContent: 'center', zIndex: 2147483647, pointerEvents: 'none', boxShadow: '0 0 0 2px #FFFFFF'});
    document.body.append(box, badge);
    return true;
  },
  clear() { document.querySelectorAll('.__mk').forEach(e => e.remove()); return true; },
};
true
"""


class AppServer:
    """The app on a free port with its own temporary database (the developer's data is untouched)."""

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="manual-app-"))
        self.port = free_port()
        self.env = dict(os.environ, PROCUREMENT_DB_PATH=str(self.dir / "mock_data.db"))
        # The walkthrough never calls Gemini; the app only needs a key to show its pages
        self.env.setdefault("GEMINI_API_KEY", "manual-screenshots")
        python = Path(sys.executable)
        subprocess.run([str(python), "-c", "from src.init_db import init_db; init_db()"], cwd=ROOT, env=self.env,
                       check=True, capture_output=True)
        self.process = subprocess.Popen(
            [str(python), "-m", "streamlit", "run", "app.py", "--server.port", str(self.port),
             "--server.headless", "true", "--browser.gatherUsageStats", "false"],
            cwd=ROOT, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/_stcore/health")
                return
            except OSError:
                time.sleep(0.5)
        raise RuntimeError("The app did not start.")

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self.process.terminate()
        self.process.wait(timeout=15)
        shutil.rmtree(self.dir, ignore_errors=True)


class Walk:
    """Clicks through the app like a user and takes the manual's screenshots."""

    def __init__(self, chrome: Chrome, lang: str):
        self.c, self.lang, self.ui = chrome, lang, UI[lang]

    def idle(self, extra: float = 0.8) -> None:
        for _ in range(160):
            busy = self.c.eval("!!document.querySelector('[data-testid=stStatusWidget]') || "
                               "!document.querySelector('[data-testid=stSidebar]')")
            if not busy:
                break
            time.sleep(0.25)
        time.sleep(extra)
        if not self.c.eval("!!window.M"):
            self.c.eval(PAGE_HELPERS)

    def click(self, element_js: str, wait: float = 1.2) -> None:
        """Real mouse click in the middle of the element (after scrolling it into view)."""
        point = self.c.eval(f"""(() => {{ const e = {element_js}; if (!e) return null;
            e.scrollIntoView({{block: 'center'}}); const r = e.getBoundingClientRect();
            return {{x: r.left + Math.min(r.width / 2, 24), y: r.top + r.height / 2}}; }})()""")
        if point is None:
            raise RuntimeError(f"[{self.lang}] element not found: {element_js}")
        self.c.mouse_click(point["x"], point["y"])
        self.idle(wait)

    def button(self, text: str, root: Optional[str] = None, wait: float = 1.2) -> None:
        scope = json.dumps(root) if root else "null"
        self.click(f"M.q('button, a', {json.dumps(text)}, {scope})", wait)

    def checkbox(self, text: str, wait: float = 1.5) -> None:
        self.click(f"M.q('[data-testid=stCheckbox] label', {json.dumps(text)})", wait)

    def scroll_to(self, element_js: str, offset: int = 90) -> None:
        self.c.eval(f"""(() => {{ const e = {element_js}; if (!e) return false; e.scrollIntoView({{block: 'start'}});
            const s = e.closest('[data-testid=stMain], [role=dialog]') ; window.scrollBy(0, -{offset});
            let p = e.parentElement; while (p) {{ if (p.scrollHeight > p.clientHeight + 4 &&
              getComputedStyle(p).overflowY !== 'visible') {{ p.scrollTop -= {offset}; break; }} p = p.parentElement; }}
            return true; }})()""")
        time.sleep(0.6)

    def shot(self, name: str, region: Sequence[str], marks: Sequence[str] = (), pad: int = 22,
             max_height: Optional[int] = None, clamp: Optional[str] = None) -> None:
        """Crops to the union of the region elements (within the clamp element, e.g. a dialog) and
        marks the given elements 1, 2, 3 ..."""
        # Toasts (e.g. "Demo data reset") would cover part of the crop: hidden by CSS, not removed
        self.c.eval("""M.clear(); if (!document.getElementById('__notoast')) { const st = document.createElement('style');
            st.id = '__notoast'; st.textContent = '[data-testid=stToastContainer] { display: none !important; }';
            document.head.append(st); } true""")
        for number, element_js in enumerate(marks, start=1):
            if not self.c.eval(f"M.mark({element_js}, {number})"):
                raise RuntimeError(f"[{self.lang}] {name}: marker {number} not found: {element_js}")
        rect = self.c.eval(f"""(() => {{
            const els = [{', '.join(region)}].filter(Boolean);
            if (!els.length) return null;
            const rs = els.map(e => e.getBoundingClientRect());
            let x0 = Math.min(...rs.map(r => r.left)) - {pad}, y0 = Math.min(...rs.map(r => r.top)) - {pad};
            let x1 = Math.max(...rs.map(r => r.right)) + {pad}, y1 = Math.max(...rs.map(r => r.bottom)) + {pad};
            const c = {json.dumps(clamp)} ? document.querySelector({json.dumps(clamp)}).getBoundingClientRect()
                : {{left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight}};
            x0 = Math.max(0, c.left, x0); y0 = Math.max(0, c.top, y0);
            x1 = Math.min(window.innerWidth, c.right, x1); y1 = Math.min(window.innerHeight, c.bottom, y1);
            return {{x: x0, y: y0, width: x1 - x0, height: y1 - y0}}; }})()""")
        if not rect:
            raise RuntimeError(f"[{self.lang}] {name}: region not found")
        if max_height:
            rect["height"] = min(rect["height"], max_height)
        self.c.screenshot(IMG / f"{name}_{self.lang}.png", rect)
        self.c.eval("M.clear()")
        print(f"  screenshot {name}_{self.lang}.png")

    # ------------------------------------------------------------------------------------------

    def run(self, url: str) -> None:
        ui, c = self.ui, self.c
        c.navigate(url, 2.0)
        self.idle(2.0)
        self.button(ui["lang_btn"], "[data-testid=stSidebar]", 2.0)
        self.button(ui["reset"], "[data-testid=stSidebar]", 2.5)
        sidebar = "document.querySelector('[data-testid=stSidebar]')"

        # Sidebar: language, navigation, budget meters, reset, manual
        self.shot("01_sidebar", [f"M.up(M.q('button', {json.dumps(ui['lang_btn'])}, {sidebar}), '[data-testid=stButtonGroup]')",
                                 f"M.q('button, a', {json.dumps(ui['manual'])}, {sidebar})"], [
            f"M.up(M.q('button', {json.dumps(ui['lang_btn'])}, {sidebar}), '[data-testid=stButtonGroup]')",
            f"M.up(M.q('button', {json.dumps(ui['nav_verify'])}, {sidebar}), '[data-testid=stVerticalBlock]')",
            f"M.up(M.q('[class*=budget-meter]', null, {sidebar}), '[data-testid=stElementContainer]')",
            f"M.q('button', {json.dumps(ui['reset'])}, {sidebar})",
            f"M.q('button, a', {json.dumps(ui['manual'])}, {sidebar})",
        ], pad=28)

        # Request Verification: queue
        main = "document.querySelector('[data-testid=stMain] [data-testid=stMainBlockContainer]')"
        self.shot("02_queue", [f"M.q('button', {json.dumps(ui['history'])})",
                               "M.q('[data-testid=stDataFrame]')"], [
            "M.q('[data-testid=stDataFrame]')",
            f"M.q('button', {json.dumps(ui['history'])})",
        ])

        # Request VA-2026-0001: the agent's checks, then the decision area
        self.open_queue_row(0)
        dialog = "'[role=dialog]'"
        self.shot("03_request_checks", [f"M.q('h2', 'VA-2026-0001', {dialog})",
                                        f"M.boxes({dialog})[0]"], [
            f"M.qa('[data-testid=stAlert]', {dialog})[0]",
            f"M.qa('[data-testid=stAlert]', {dialog})[1]",
            f"M.boxes({dialog})[0]",
        ], clamp='[role=dialog]')
        self.scroll_to(f"M.q('p, strong, h3, h4', {json.dumps(ui['decision'])}, {dialog})")
        self.shot("04_request_decision", [f"M.q('p, strong, h3, h4', {json.dumps(ui['decision'])}, {dialog})",
                                          f"M.q('button', {json.dumps(ui['approve'])}, {dialog})"], [
            f"M.q('[data-testid=stTextArea]', null, {dialog})",
            f"M.q('button', {json.dumps(ui['approve'])}, {dialog})",
            f"M.q('button', {json.dumps(ui['reject'])}, {dialog})",
        ], clamp='[role=dialog]')
        self.close_dialog()

        # VA-2026-0002: the agent recommends rejection; approving would be an override
        self.open_queue_row(1)
        self.scroll_to(f"M.q('p, strong, h3, h4', {json.dumps(ui['issues'])}, {dialog})")
        self.shot("05_override", [f"M.q('p, strong, h3, h4', {json.dumps(ui['issues'])}, {dialog})",
                                  f"M.q('button', {json.dumps(ui['approve'])}, {dialog})"], [
            f"M.q('p, strong, h3, h4', {json.dumps(ui['issues'])}, {dialog})",
            f"M.q('[data-testid=stTextArea]', null, {dialog})",
            f"M.q('button', {json.dumps(ui['approve'])}, {dialog})",
        ], clamp='[role=dialog]')
        self.close_dialog()

        # VA-2026-0003: budget transfer suggestion and the pre-filled Deckungsantrag
        self.open_queue_row(2)
        self.scroll_to(f"M.q('p, strong, h3, h4', {json.dumps(ui['transfer'])}, {dialog})")
        self.shot("06_transfer", [f"M.q('p, strong, h3, h4', {json.dumps(ui['transfer'])}, {dialog})",
                                  f"M.q('[data-testid=stCheckbox]', {json.dumps(ui['transfer_include'])}, {dialog})"], [
            f"M.q('[data-testid=stRadio]', null, {dialog})",
            f"M.q('[data-testid=stDownloadButton]', {json.dumps(ui['pdf'])}, {dialog})",
            f"M.q('[data-testid=stCheckbox]', {json.dumps(ui['transfer_include'])}, {dialog})",
        ], clamp='[role=dialog]')
        self.close_dialog()

        # Add Procurement Request
        self.button(ui["nav_add"], "[data-testid=stSidebar]", 2.0)
        self.shot("07_add_request", [f"M.q('[data-testid=stFileUploader]')", f"M.q('button', {json.dumps(ui['submit'])})"], [
            "M.q('[data-testid=stFileUploader]')",
            f"M.up(M.q('button', 'IT'), '[data-testid=stHorizontalBlock]')",
            "M.q('[data-testid=stTextArea]')",
            f"M.q('button', {json.dumps(ui['submit'])})",
        ])

        # Approve VA-2026-0001 so it can be tendered
        self.button(ui["nav_verify"], "[data-testid=stSidebar]", 2.0)
        self.open_queue_row(0)
        self.button(ui["approve"], "[role=dialog]", 3.0)
        self.close_dialog()

        # Bid Evaluation: request, criteria, upload
        self.button(ui["nav_bids"], "[data-testid=stSidebar]", 2.0)
        c.set_files('input[type="file"]', [FIXTURES / n for n in ("Bechtle_bid.pdf", "dell_bid.pdf", "OfficeDepot_bid.pdf")])
        self.idle(4.0)
        self.scroll_to("M.q('[data-testid=stSelectbox]')", 40)
        self.shot("08_bids_setup", ["M.q('[data-testid=stSelectbox]')", "M.boxes()[0]"], [
            "M.q('[data-testid=stSelectbox]')",
            "M.q('[data-testid=stFileUploader]')",
            "M.q('[data-testid=stButtonGroup]', null, M.boxes()[0])",
            "M.up(M.q('[data-testid=stNumberInput]'), '[data-testid=stHorizontalBlock]')",
        ])

        # Bid data with the agent's proposals and the breakdown
        self.click(f"M.q('summary', {json.dumps(ui['breakdown'])})", 1.2)
        self.scroll_to(f"M.q('p, strong', {json.dumps(ui['table'])})", 40)
        self.shot("09_bid_table", [f"M.q('p, strong', {json.dumps(ui['table'])})",
                                   f"M.up(M.q('summary', {json.dumps(ui['breakdown'])}), '[data-testid=stExpander]')"], [
            f"M.q('[data-testid=stCheckbox]', {json.dumps(ui['committee'])})",
            "M.q('[data-testid=stDataFrame]')",
            f"M.up(M.q('summary', {json.dumps(ui['breakdown'])}), '[data-testid=stExpander]')",
        ], max_height=1180)

        # Run the evaluation: recommended supplier and scoring matrix
        self.click(f"M.q('summary', {json.dumps(ui['breakdown'])})", 0.8)
        self.checkbox(ui["committee"])
        self.button(ui["run"], None, 4.0)
        self.scroll_to(f"M.q('[data-testid=stCaptionContainer]', {json.dumps(ui['winner'])})", 30)
        self.shot("10_result", [f"M.q('[data-testid=stCaptionContainer]', {json.dumps(ui['winner'])})",
                                "M.qa('[data-testid=stDataFrame]').slice(-1)[0]"], [
            "M.q('h3')",
            "M.qa('[data-testid=stMetric]')[0]",
            "M.qa('[data-testid=stDataFrame]').slice(-1)[0]",
        ])

        # Letters: approval unlocks all emails
        self.scroll_to(f"M.q('h3', {json.dumps(ui['letters'])})", 30)
        self.shot("11_letters_locked", [f"M.q('h3', {json.dumps(ui['letters'])})",
                                        "M.qa('[data-testid=stExpander]').slice(-1)[0]"], [
            f"M.q('[data-testid=stCheckbox]', {json.dumps(ui['approval'])})",
            "M.qa('[data-testid=stLinkButton]')[0]",
        ])
        self.checkbox(ui["approval"])
        self.scroll_to(f"M.q('h3', {json.dumps(ui['letters'])})", 30)
        self.shot("12_letters_unlocked", [f"M.q('h3', {json.dumps(ui['letters'])})",
                                          f"M.qa('[data-testid=stCheckbox]').filter(e => e.innerText.includes({json.dumps(ui['sent'])})).slice(-1)[0]"], [
            f"M.q('[data-testid=stCheckbox]', {json.dumps(ui['approval'])})",
            "M.qa('[data-testid=stLinkButton]')[0]",
            f"M.q('a', {json.dumps(ui['gmail'])})",
            f"M.q('[data-testid=stCheckbox]', {json.dumps(ui['sent'])})",
            "M.qa('[data-testid=stExpander]')[1]",
        ])
        # The award is sent and marked; the bid history shows the status per bidder
        self.checkbox(ui["sent"])
        c.eval("window.scrollTo(0, 0); document.querySelector('[data-testid=stMain]').scrollTop = 0; true")
        self.button(ui["history"], None, 2.5)
        self.shot("13_bid_history", ["M.q('[role=dialog] h2')", "M.boxes('[role=dialog]')[2]"], [
            "M.boxes('[role=dialog]')[0]",
            "M.qa('[role=dialog] [data-testid=stLinkButton]')[1]",
            "M.qa('[role=dialog] [data-testid=stCheckbox]')[1]",
        ], clamp='[role=dialog]')
        self.close_dialog()

        # Request history
        self.button(ui["nav_verify"], "[data-testid=stSidebar]", 2.0)
        self.button(ui["history"], None, 2.5)
        self.shot("14_request_history", ["M.q('[role=dialog] h2')", "M.boxes('[role=dialog]')[1]"], [
            "M.q('[data-testid=stButtonGroup]', null, '[role=dialog]')",
            "M.boxes('[role=dialog]')[0]",
            "M.boxes('[role=dialog]')[1]",
        ], clamp='[role=dialog]')
        self.close_dialog()

        # Management Insights
        self.button(ui["nav_insights"], "[data-testid=stSidebar]", 2.5)
        self.shot("15_insights_budget", [f"M.q('[data-testid=stExpander]', {json.dumps(ui['how'])})",
                                         f"M.box(M.q('h3', {json.dumps(ui['tile_suppliers'])}))"], [
            f"M.q('[data-testid=stExpander]', {json.dumps(ui['how'])})",
            f"M.box(M.q('h3', {json.dumps(ui['tile_budget'])}))",
            f"M.box(M.q('h3', {json.dumps(ui['tile_suppliers'])}))",
        ], max_height=1180)
        self.scroll_to(f"M.q('h3', {json.dumps(ui['tile_oversight'])})", 30)
        self.shot("16_insights_oversight", [
            f"M.box(M.q('h3', {json.dumps(ui['tile_oversight'])}))"], [
            "M.qa('[data-testid=stMetric]')[0]",
            "M.qa('[data-testid=stMetric]')[1]",
            "M.qa('[data-testid=stMetric]').slice(-1)[0]",
        ], max_height=1180)

    def open_queue_row(self, index: int) -> None:
        """Opens a request from the queue table and waits until its dialog is fully rendered."""
        for _ in range(3):
            point = self.c.eval(f"""(() => {{ const g = M.q('[data-testid=stDataFrame]'); if (!g) return null;
                g.scrollIntoView({{block: 'center'}}); const r = g.getBoundingClientRect();
                return {{x: r.left + 16, y: r.top + 35 + 35 * {index} + 17}}; }})()""")
            if point:
                self.c.mouse_click(point["x"], point["y"])
            for _ in range(40):
                self.idle(0.25)
                if self.c.eval("!!document.querySelector('[role=dialog] [data-testid=stButton]')"):
                    time.sleep(1.0)
                    return
        raise RuntimeError(f"[{self.lang}] request row {index} did not open")

    def close_dialog(self) -> None:
        self.c.key("Escape")
        self.idle(1.5)


def take_screenshots(chrome: Chrome) -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    # A placeholder manual makes the sidebar download button visible on the first build
    for path in PDF_OUT.values():
        if not path.exists():
            path.write_bytes(b"%PDF-1.4\n% placeholder, replaced by build_manual.py\n")
    server = AppServer()
    try:
        for lang in ("de", "en"):
            print(f"Screenshots ({lang}) ...")
            chrome.set_viewport(*WINDOW, SCALE)
            Walk(chrome, lang).run(server.url)
    finally:
        server.stop()


# ==============================================================================================
# 3. Markdown -> HTML -> PDF
# ==============================================================================================

PRINT_CSS = """
@page { size: A4; margin: 17mm 16mm 18mm 16mm; }
html { font-family: 'Source Sans', 'Helvetica Neue', Arial, sans-serif; font-size: 10.2pt; color: #0F172A; }
body { margin: 0; line-height: 1.38; }
h1, h2, h3 { color: #1E3A8A; line-height: 1.2; break-after: avoid; }
h1 { font-size: 19pt; margin: 18pt 0 8pt; padding-bottom: 4pt; border-bottom: 2.5pt solid #1E3A8A; }
h1.page, .page-break { break-before: page; }
h2 { font-size: 13.5pt; margin: 15pt 0 5pt; }
h3 { font-size: 11.5pt; margin: 11pt 0 4pt; }
p { margin: 0 0 6pt; }
ul, ol { margin: 0 0 7pt; padding-left: 17pt; }
li { margin: 0 0 2.5pt; }
strong { color: #0F172A; }
code { font-family: 'Source Sans', monospace; background: #EEF2FF; padding: 0 3pt; border-radius: 3pt; }
a { color: #1E3A8A; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 9pt; font-size: 9.6pt; break-inside: auto; }
th { background: #1E3A8A; color: #FFFFFF; text-align: left; font-weight: 600; }
th, td { border: 0.6pt solid #CBD5E1; padding: 3.5pt 5pt; vertical-align: top; }
tr { break-inside: avoid; }
tr:nth-child(even) td { background: #F8FAFC; }
blockquote { margin: 6pt 0 9pt; padding: 6pt 9pt; background: #EEF2FF; border-left: 3pt solid #1E3A8A; border-radius: 3pt; }
blockquote p:last-child { margin: 0; }
figure { margin: 6pt 0 11pt; break-inside: avoid; text-align: center; }
figure img { max-width: 100%; max-height: 72mm; border: 0.6pt solid #CBD5E1; border-radius: 4pt; }
figure.tall { float: right; width: 50mm; margin: 2pt 0 6pt 10pt; }
figure.tall img { max-height: 178mm; }
/* Diagrams are sized so their text prints at about 8-9 pt */
figure.diagram svg { max-width: 100%; height: auto; max-height: 200mm; }
figure.diagram.small svg { max-height: 165mm; }
.row { display: flex; gap: 6mm; align-items: flex-start; break-inside: avoid; }
.row figure { flex: 1 1 0; margin-top: 2pt; }
.row figure img { max-height: 95mm; }
.overview figure.diagram svg { max-height: 200mm; }
figcaption { font-size: 9pt; color: #475569; margin-top: 3pt; font-style: italic; }
.cover { break-after: page; height: 255mm; display: flex; flex-direction: column; justify-content: center; }
.cover .agency { color: #1E3A8A; font-weight: 700; letter-spacing: 0.08em; font-size: 10pt; text-transform: uppercase; }
.cover .title { font-size: 34pt; font-weight: 700; color: #0F172A; margin: 10pt 0 4pt; line-height: 1.1; }
.cover .subtitle { font-size: 15pt; color: #334155; margin-bottom: 26pt; }
.cover .meta { font-size: 10.5pt; color: #475569; border-top: 1pt solid #CBD5E1; padding-top: 8pt; }
.cover .note { margin-top: 18pt; background: #FEF3C7; border-left: 3pt solid #D97706; padding: 8pt 10pt; font-size: 10pt; }
.overview h1 { break-before: page; }
.keep { break-inside: avoid; }
"""

FOOTER = {
    "de": "Benutzerhandbuch · Öffentlicher Vergabeassistent · Stadt Hildesheim",
    "en": "User manual · Public Procurement Assistant · City of Hildesheim",
}
PAGE_WORD = {"de": ("Seite", "von"), "en": ("Page", "of")}


def embed_diagrams(markdown: str) -> str:
    """![caption](diagrams/name.svg){.small} -> inline SVG figure (stays vector, uses Source Sans)."""
    def replace(match: re.Match) -> str:
        caption, path, extra = match.group(1), match.group(2), match.group(3) or ""
        svg = (MANUAL / path).read_text(encoding="utf-8")
        classes = "diagram" + (" small" if "small" in extra else "")
        return f'\n<figure class="{classes}">{svg}<figcaption>{caption}</figcaption></figure>\n'
    return re.sub(r"!\[([^\]]*)\]\((diagrams/[^)]+\.svg)\)(\{[^}]*\})?", replace, markdown)


def screenshot_figures(markdown: str) -> str:
    """![caption](img/name.png){.tall} -> figure with caption ({.tall}: narrow, tall screenshot)."""
    def replace(match: re.Match) -> str:
        tall = " class=\"tall\"" if match.group(3) and "tall" in match.group(3) else ""
        return (f'\n<figure{tall}><img src="{(MANUAL / match.group(2)).as_uri()}">'
                f'<figcaption>{match.group(1)}</figcaption></figure>\n')
    return re.sub(r"!\[([^\]]+)\]\((img/[^)]+\.png)\)(\{[^}]*\})?", replace, markdown)


def build_pdf(chrome: Chrome, lang: str, work: Path) -> Path:
    text = (MANUAL / f"user_manual_{lang}.md").read_text(encoding="utf-8")
    text = text.replace("{{VERSION}}", VERSION).replace("{{DATE}}", date.today().strftime("%d.%m.%Y" if lang == "de" else "%Y-%m-%d"))
    text = screenshot_figures(embed_diagrams(text))
    page = work / f"manual_{lang}.html"
    page.write_text(
        f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{FOOTER[lang]}</title>
        <style>{font_face_css()}{PRINT_CSS}</style><script src="{MARKED_JS.as_uri()}"></script></head>
        <body><main id="doc"></main><script id="md" type="text/markdown">{text.replace('</script', '<\\/script')}</script>
        <script>document.getElementById('doc').innerHTML = marked.parse(document.getElementById('md').textContent);</script>
        </body></html>""",
        encoding="utf-8",
    )
    chrome.navigate(page.as_uri(), 1.0)
    chrome.eval("document.fonts.ready.then(() => Promise.all([...document.images].map(i => i.complete ? 1 : "
                "new Promise(r => { i.onload = i.onerror = r; })))).then(() => true)")
    word, of = PAGE_WORD[lang]
    style = "font-family: 'Source Sans', Helvetica, Arial, sans-serif; font-size: 8pt; color: #64748B; width: 100%; padding: 0 16mm;"
    footer = (f'<div style="{style} display: flex; justify-content: space-between;"><span>{FOOTER[lang]}</span>'
              f'<span>{word} <span class="pageNumber"></span> {of} <span class="totalPages"></span></span></div>')
    out = PDF_OUT[lang]
    chrome.print_pdf(out, footer=footer)
    return out


def page_count(path: Path) -> int:
    from pypdf import PdfReader
    return len(PdfReader(str(path)).pages)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-screenshots", action="store_true", help="reuse the screenshots in docs/manual/img/")
    args = parser.parse_args(argv)

    ensure_node_modules()
    work = Path(tempfile.mkdtemp(prefix="manual-build-"))
    try:
        with Chrome(*WINDOW, SCALE) as chrome:
            print("Diagrams ...")
            render_diagrams(chrome, work)
            if not args.no_screenshots:
                take_screenshots(chrome)
            for lang in ("de", "en"):
                out = build_pdf(chrome, lang, work)
                print(f"{out.relative_to(ROOT)}: {page_count(out)} pages")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
