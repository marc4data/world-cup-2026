"""Render an HTML file (or URL) to image(s) with headless Chromium (Playwright).

Two jobs:
  * a visual-feedback loop for HTML/CSS/JS graphics (render -> look -> iterate), the
    same tight loop the matplotlib reports have; and
  * turning a multi-page print document into **one clean image per page** — e.g. the
    4-page world-cup-2026.html infographic, which is four `<div class="page">`
    landscape US-Letter sheets. `--pages ".page"` emits page-1.jpg … page-4.jpg with
    no wonky pagination.

A real browser engine is used (not a static HTML->image converter) so JS content
(the Plotly maps) draws and fonts/layout match a browser. JPEG vs PNG is inferred
from the --out extension.

Setup (one-time, into the .venv):
    .venv/bin/python -m pip install -r requirements-dev.txt
    .venv/bin/python -m playwright install chromium

Usage:
    # 4-page infographic -> 4 JPEGs (wc-page-1.jpg … wc-page-4.jpg)
    python scripts/render_html.py world-cup-2026.html --pages ".page" --out /tmp/wc-page.jpg

    # whole page, or one element, as a single image
    python scripts/render_html.py world-cup-2026.html --out /tmp/wc.png --full-page
    python scripts/render_html.py world-cup-2026.html --out /tmp/map.png --selector "#venue-map"
"""
from __future__ import annotations

import argparse
import pathlib
import sys

from playwright.sync_api import sync_playwright


def _to_url(src: str) -> str:
    if src.startswith(("http://", "https://")):
        return src
    return pathlib.Path(src).resolve().as_uri()


def _shot_kwargs(out: pathlib.Path, quality: int) -> dict:
    kw: dict = {"path": str(out)}
    if out.suffix.lower() in (".jpg", ".jpeg"):
        kw["type"] = "jpeg"
        kw["quality"] = quality
    return kw


def render(src, out, *, width=1280, height=900, full_page=False, scale=2,
           wait_ms=1500, selector=None, quality=90) -> list[str]:
    out = pathlib.Path(out)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height},
                                device_scale_factor=scale)
        page.goto(_to_url(src), wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(wait_ms)
        if selector:
            page.locator(selector).first.screenshot(**_shot_kwargs(out, quality))
        else:
            page.screenshot(full_page=full_page, **_shot_kwargs(out, quality))
        browser.close()
    return [str(out)]


def render_pages(src, out, selector, *, width=1100, height=850, scale=2,
                 wait_ms=1500, quality=90) -> list[str]:
    """Screenshot every element matching `selector` to its own numbered image."""
    out = pathlib.Path(out)
    files = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height},
                                device_scale_factor=scale)
        page.goto(_to_url(src), wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(wait_ms)
        els = page.locator(selector)
        for i in range(els.count()):
            f = out.with_name(f"{out.stem}-{i + 1}{out.suffix}")
            els.nth(i).screenshot(**_shot_kwargs(f, quality))
            files.append(str(f))
        browser.close()
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render HTML/URL to image(s) via headless Chromium")
    ap.add_argument("src", help="HTML file path or http(s) URL")
    ap.add_argument("--out", default="/tmp/render.png", help="output path (.jpg or .png)")
    ap.add_argument("--pages", default=None, metavar="SELECTOR",
                    help="paginate: one image per element matching SELECTOR (e.g. '.page')")
    ap.add_argument("--selector", default=None, help="render just the first element matching this")
    ap.add_argument("--full-page", action="store_true")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--quality", type=int, default=90, help="JPEG quality (0-100)")
    ap.add_argument("--wait-ms", type=int, default=1500)
    args = ap.parse_args(argv)

    if args.pages:
        files = render_pages(args.src, args.out, args.pages, scale=args.scale,
                             wait_ms=args.wait_ms, quality=args.quality)
    else:
        files = render(args.src, args.out, width=args.width, height=args.height,
                       full_page=args.full_page, scale=args.scale, wait_ms=args.wait_ms,
                       selector=args.selector, quality=args.quality)
    for f in files:
        print("wrote", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
