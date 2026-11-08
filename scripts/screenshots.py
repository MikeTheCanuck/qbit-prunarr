"""Retake the README screenshots from a running demo.

    cd app && python demo.py &
    pip install playwright && python -m playwright install chromium
    python scripts/screenshots.py docs/screenshots
"""
import sys
from playwright.sync_api import sync_playwright

OUT = sys.argv[1]
BASE = "http://127.0.0.1:8585"

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1200, "height": 500}, device_scale_factor=2,
                      color_scheme="dark")

    page.goto(f"{BASE}/")
    page.screenshot(path=f"{OUT}/cold-torrents.png", full_page=True)

    page.goto(f"{BASE}/orphans")
    page.click("#scan-btn")
    page.wait_for_selector("#review-buckets", state="attached", timeout=30000)

    page.click('button[role=tab][data-tab="download"]')
    page.wait_for_timeout(200)
    page.screenshot(path=f"{OUT}/unlinked-downloads.png", full_page=True)

    page.click('button[role=tab][data-tab="review"]')
    for kind in ["wanted", "plex", "junk"]:
        page.click(f'#review-buckets .bucket[data-kind="{kind}"]')
        page.wait_for_timeout(200)
        if kind == "junk":
            for box in page.query_selector_all('tbody.orphan-unit[data-verdict="junk"] input[type=checkbox]'):
                box.check()
            page.wait_for_timeout(200)
        page.screenshot(path=f"{OUT}/needs-review-{kind}.png", full_page=True)

    page.set_viewport_size({"width": 1200, "height": 680})
    page.click("#sticky-delete-btn")
    page.wait_for_selector("#delete-dialog[open]")
    page.wait_for_timeout(200)
    page.screenshot(path=f"{OUT}/delete-confirm.png")
    page.click("#dd-cancel")
    page.set_viewport_size({"width": 1200, "height": 500})

    page.click('button[role=tab][data-tab="extras"]')
    page.wait_for_timeout(200)
    page.screenshot(path=f"{OUT}/extras.png", full_page=True)
    b.close()
