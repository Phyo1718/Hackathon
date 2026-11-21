"""Minimal headless Chrome driver (Chrome DevTools Protocol) for scripts/build_manual.py.

Uses the `websockets` package that is already installed with the app; no Playwright needed.
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from websockets.sync.client import connect

CHROME_CANDIDATES = [
    os.environ.get("CHROME_PATH", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
    shutil.which("chromium-browser") or "",
]


def find_chrome() -> str:
    for path in CHROME_CANDIDATES:
        if path and Path(path).exists():
            return path
    raise RuntimeError("Google Chrome / Chromium not found. Set CHROME_PATH.")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Chrome:
    """One headless Chrome tab. Use as a context manager."""

    def __init__(self, width: int = 1440, height: int = 1100, scale: float = 2.0):
        self.width, self.height, self.scale = width, height, scale
        self.port = free_port()
        self.profile = tempfile.mkdtemp(prefix="manual-chrome-")
        self.process = subprocess.Popen(
            [find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
             "--allow-file-access-from-files", f"--remote-debugging-port={self.port}",
             f"--user-data-dir={self.profile}", f"--window-size={width},{height}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        target = None
        for _ in range(80):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json") as response:
                    target = next((t for t in json.load(response) if t["type"] == "page"), None)
                if target:
                    break
            except OSError:
                pass
            time.sleep(0.25)
        if not target:
            raise RuntimeError("Chrome did not start.")
        self.ws = connect(target["webSocketDebuggerUrl"], max_size=None)
        self.next_id = 0
        self.send("Page.enable")
        self.send("Runtime.enable")
        self.set_viewport(width, height, scale)

    def __enter__(self) -> "Chrome":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.ws.close()
        finally:
            self.process.terminate()
            self.process.wait(timeout=10)
            shutil.rmtree(self.profile, ignore_errors=True)

    # --- Protocol -----------------------------------------------------------------------------

    def send(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.next_id += 1
        message_id = self.next_id
        self.ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == message_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    def eval(self, expression: str) -> Any:
        result = self.send("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})
        if "exceptionDetails" in result:
            raise RuntimeError(f"JS error: {result['exceptionDetails'].get('exception', {}).get('description')}")
        return result.get("result", {}).get("value")

    def set_viewport(self, width: int, height: int, scale: float) -> None:
        self.send("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height, "deviceScaleFactor": scale, "mobile": False})

    def navigate(self, url: str, wait: float = 1.0) -> None:
        self.send("Page.navigate", {"url": url})
        time.sleep(wait)

    def mouse_click(self, x: float, y: float) -> None:
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1})

    def key(self, key: str) -> None:
        codes = {"Escape": 27, "Enter": 13}
        for kind in ("rawKeyDown", "keyUp"):
            self.send("Input.dispatchKeyEvent", {"type": kind, "key": key, "windowsVirtualKeyCode": codes.get(key, 0)})

    def set_files(self, selector: str, files) -> None:
        root = self.send("DOM.getDocument", {"depth": -1, "pierce": True})["root"]
        node = self.send("DOM.querySelector", {"nodeId": root["nodeId"], "selector": selector})["nodeId"]
        self.send("DOM.setFileInputFiles", {"nodeId": node, "files": [str(f) for f in files]})

    def screenshot(self, path: Path, clip: Optional[Dict[str, float]] = None) -> None:
        params: Dict[str, Any] = {"format": "png"}
        if clip:
            params["clip"] = {**clip, "scale": 1}
        data = self.send("Page.captureScreenshot", params)["data"]
        Path(path).write_bytes(base64.b64decode(data))

    def print_pdf(self, path: Path, header: str = "", footer: str = "") -> None:
        data = self.send("Page.printToPDF", {
            "printBackground": True,
            "preferCSSPageSize": True,
            "displayHeaderFooter": bool(header or footer),
            "headerTemplate": header or "<span></span>",
            "footerTemplate": footer or "<span></span>",
        })["data"]
        Path(path).write_bytes(base64.b64decode(data))
