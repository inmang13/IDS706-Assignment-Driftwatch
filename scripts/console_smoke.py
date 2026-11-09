"""Console smoke test (C10.4): every tab loads, no requests leave the origin, screenshots to docs/images/.

Needs a running server (make serve) and `pip install playwright`; uses the system Chrome (channel="chrome"),
so no browser download. Not part of `make test` (pytest never needs a browser).

    .venv\\Scripts\\python.exe scripts/console_smoke.py [--base http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "docs" / "images"
SHOTS = [
    ("console", "/?site=03455000", None),
    ("gauge_hepco", "/?site=03459500", None),
    ("gauge_mills", "/?site=03446000", None),
    ("registry", "/?tab=registry", "#reg-cards .mod"),
    ("education", "/?tab=education", "#edu-list .edu"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    origin = urlparse(args.base).netloc
    OUT.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        for width, suffix in [(1440, ""), (390, "_phone")]:
            page = browser.new_page(viewport={"width": width, "height": 1000})
            page.on(
                "request",
                lambda r: (
                    problems.append(f"off-origin request: {r.url}")
                    if urlparse(r.url).scheme in ("http", "https")
                    and urlparse(r.url).netloc != origin
                    else None
                ),
            )
            page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
            page.on(
                "response",
                lambda r: problems.append(f"HTTP {r.status}: {r.url}") if r.status >= 400 else None,
            )
            for name, path, wait_for in SHOTS:
                page.goto(args.base + path)
                page.wait_for_selector("body[data-state=done]", timeout=30000)
                if wait_for:
                    page.wait_for_selector(wait_for, timeout=10000)
                page.wait_for_timeout(600)  # fonts + plotly relayout
                if "[content coming]" in page.inner_text("body") and name == "education":
                    problems.append("education tab fell back to the placeholder")
                page.screenshot(path=str(OUT / f"{name}{suffix}.png"), full_page=True)
                print(f"ok {name}{suffix}")
            page.close()
        browser.close()
    for msg in problems:
        print("FAIL", msg)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
