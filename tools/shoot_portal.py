"""Capture the live statistical release portal for slide 5 of the deck.

Reproducible so the deck's screenshot can never drift from what the portal
actually shows. Run after a full index-tier collection, so the route heat map
has every booking lead time populated.

    python3 tools/shoot_portal.py [--url URL] [--out PATH]
"""
import argparse
import sys

URL = "https://apix-portal.pages.dev"
OUT = "/home/ajeet/.claude/jobs/1319c671/tmp/portal-shot.png"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=700)
    ap.add_argument("--wait-ms", type=int, default=9000,
                    help="time for the Supabase fetch and the SVG draws to settle")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": args.width, "height": args.height},
                                device_scale_factor=2)
        page.goto(args.url, wait_until="networkidle", timeout=60_000)
        # the page renders sample data first, then repaints from Supabase
        page.wait_for_timeout(args.wait_ms)

        headline = page.inner_text("#h-infl") if page.query_selector("#h-infl") else "?"
        status = page.inner_text("#h-status") if page.query_selector("#h-status") else "?"
        page.screenshot(path=args.out, clip={"x": 0, "y": 0,
                                             "width": args.width, "height": args.height})
        browser.close()

    print(f"wrote {args.out}  headline={headline!r} status={status!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
