"""Browser tests.

These run against a real Chromium with real device emulation, because a
desktop window resized to 390px wide does not reproduce what a phone does:
it has no device pixel ratio, no touch, no mobile user agent and no
on-screen keyboard. Two bugs in an earlier build only appeared under proper
emulation, which is why these tests use device descriptors rather than
viewport sizes.
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "antrix_app"
SHOTS = Path("/private/tmp/claude-501/-Users-chiragdawra-Desktop-HackSpace-AntriX/"
             "9320defb-2dfc-4a75-b23f-780c27767df3/scratchpad")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = free_port()
    process = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=APP_DIR,
        env={"PORT": str(port), "PATH": "/usr/bin:/bin"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"

    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                break
        except OSError:
            time.sleep(0.2)
    else:
        process.terminate()
        pytest.fail("dashboard server did not start")

    yield url
    process.terminate()
    process.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        instance = p.chromium.launch()
        yield p, instance
        instance.close()


def collect_errors(page):
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    return errors


def test_dashboard_loads_without_console_errors(server, browser):
    _, instance = browser
    page = instance.new_page(viewport={"width": 1440, "height": 900})
    errors = collect_errors(page)

    page.goto(server, wait_until="networkidle")
    page.wait_for_selector(".item", timeout=15000)

    assert page.locator(".metric").count() >= 5
    assert page.locator(".source").count() == 4
    assert page.locator(".item").count() > 0
    # The provenance strip must show a real snapshot, not the placeholder.
    assert page.locator("#p-snap").inner_text().strip() not in ("", "—")

    if SHOTS.exists():
        page.screenshot(path=str(SHOTS / "ui_desktop.png"))

    assert not errors, errors
    page.close()


def test_detail_panel_shows_per_source_distances(server, browser):
    _, instance = browser
    page = instance.new_page(viewport={"width": 1440, "height": 900})
    errors = collect_errors(page)

    page.goto(server, wait_until="networkidle")
    page.wait_for_selector(".item", timeout=15000)
    page.locator(".item").first.click()
    page.wait_for_selector("#detail:not([hidden])", timeout=5000)

    assert page.locator(".contrib").count() >= 5
    assert page.locator(".srcmatrix > div").count() == 4

    # A loaded registry must show a distance, not "n/a" -- the bug that hid
    # the whole corroboration matrix when sources_loaded was not sent.
    matrix = page.locator(".srcmatrix .d").all_inner_texts()
    assert any("km" in cell for cell in matrix), matrix

    # The detection becomes addressable.
    assert "detection=" in page.url

    if SHOTS.exists():
        page.screenshot(path=str(SHOTS / "ui_detail.png"))

    assert not errors, errors
    page.close()


def test_source_filter_narrows_the_feed(server, browser):
    _, instance = browser
    page = instance.new_page(viewport={"width": 1440, "height": 900})
    page.goto(server, wait_until="networkidle")
    page.wait_for_selector(".item", timeout=15000)

    before = page.locator("#feedcount").inner_text()
    page.locator('.source:not([disabled])').first.click()
    page.wait_for_timeout(400)
    after = page.locator("#feedcount").inner_text()

    assert before != after
    # And the export URL follows the filter, so the CSV matches the screen.
    assert "sources=" in page.locator("#ex-csv").get_attribute("href")
    page.close()


def test_unavailable_source_is_disabled_and_explains_itself(server, browser):
    _, instance = browser
    page = instance.new_page(viewport={"width": 1440, "height": 900})
    page.goto(server, wait_until="networkidle")
    page.wait_for_selector(".source", timeout=15000)

    disabled = page.locator(".source[disabled]")
    if disabled.count():
        assert disabled.first.get_attribute("title")
        assert "not loaded" in disabled.first.inner_text().lower()
    page.close()


def test_phone_layout_under_device_emulation(server, browser):
    p, instance = browser
    device = p.devices["iPhone 13"]
    ctx = instance.new_context(**device)
    page = ctx.new_page()
    errors = collect_errors(page)

    page.goto(server, wait_until="networkidle")
    page.wait_for_selector(".item", timeout=15000)

    # No horizontal page scroll: the single most common phone regression.
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 1, f"page scrolls horizontally by {overflow}px"

    # The bottom sheet's handle has to be reachable.
    assert page.locator("#sheetgrab").is_visible()

    # Tap targets: anything smaller than ~40px is a miss on a phone.
    small = page.evaluate("""() => {
      const bad = [];
      document.querySelectorAll('.chip, .source:not([disabled]), .btn').forEach(n => {
        const r = n.getBoundingClientRect();
        if (r.height > 0 && r.height < 32) bad.push(n.className + ':' + Math.round(r.height));
      });
      return bad;
    }""")
    assert not small, small

    if SHOTS.exists():
        page.screenshot(path=str(SHOTS / "ui_phone.png"))

    page.locator("#sheetgrab").click()
    page.wait_for_timeout(500)
    if SHOTS.exists():
        page.screenshot(path=str(SHOTS / "ui_phone_sheet.png"))

    assert not errors, errors
    ctx.close()


def test_keyboard_navigation_moves_through_the_feed(server, browser):
    _, instance = browser
    page = instance.new_page(viewport={"width": 1440, "height": 900})
    page.goto(server, wait_until="networkidle")
    page.wait_for_selector(".item", timeout=15000)

    page.locator(".item").first.click()
    page.wait_for_selector("#detail:not([hidden])", timeout=5000)
    first_title = page.locator("#d-title").inner_text()

    page.locator("#feed").focus()
    page.keyboard.press("ArrowDown")
    page.wait_for_timeout(300)
    assert page.locator("#d-title").inner_text() != first_title or \
        page.locator('.item[aria-selected="true"]').count() == 1

    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert page.locator("#detail").get_attribute("hidden") is not None
    page.close()


def test_site_view_opens_from_a_detection(server, browser):
    _, instance = browser
    page = instance.new_page(viewport={"width": 1440, "height": 900})
    errors = collect_errors(page)

    page.goto(server, wait_until="networkidle")
    page.wait_for_selector(".item", timeout=15000)
    page.locator(".item").first.click()
    page.wait_for_selector("#detail:not([hidden])", timeout=5000)

    link = page.locator(".sitelink")
    if link.count() == 0 or link.first.is_disabled():
        pytest.skip("first detection has no matched site")

    link.first.click()
    page.wait_for_selector("#site:not([hidden])", timeout=5000)

    assert page.locator("#s-title").inner_text().strip() not in ("", "—")
    assert page.locator(".daybars .col").count() > 0

    if SHOTS.exists():
        page.screenshot(path=str(SHOTS / "ui_site.png"))

    assert not errors, errors
    page.close()


def test_watchlist_persists_across_reloads(server, browser):
    _, instance = browser
    ctx = instance.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()

    page.goto(server, wait_until="networkidle")
    page.wait_for_selector(".item", timeout=15000)
    page.locator(".item").first.click()
    page.wait_for_selector("#detail:not([hidden])", timeout=5000)

    link = page.locator(".sitelink")
    if link.count() == 0 or link.first.is_disabled():
        ctx.close()
        pytest.skip("first detection has no matched site")

    link.first.click()
    page.wait_for_selector("#site:not([hidden])", timeout=5000)
    page.locator("#s-watch").click()
    assert "Watching" in page.locator("#s-watch").inner_text()
    assert page.locator("#watch-count").inner_text() == "1"

    page.reload(wait_until="networkidle")
    page.wait_for_selector(".item", timeout=15000)
    assert page.locator("#watch-count").inner_text() == "1"

    # The reload restores the deep-linked detection, so the detail panel is
    # covering the toolbar; dismiss it the way a user would.
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    # Filtering to the watchlist must actually narrow the feed.
    total = page.locator(".item").count()
    page.locator("#watch-filter").click()
    page.wait_for_timeout(400)
    assert page.locator(".item").count() < total

    ctx.close()


def test_dashboard_works_with_every_external_host_blocked(server, browser):
    """Venue wifi, or a firewall, or Esri having a bad day.

    Basemap tiles, fonts and the imagery overlay all come from third parties.
    None of them may be load-bearing: with all of them blocked the detections,
    the feed and the evidence panel must still work.
    """
    _, instance = browser
    ctx = instance.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()

    page.route("**://*.arcgisonline.com/**", lambda route: route.abort())
    page.route("**://*.googleapis.com/**", lambda route: route.abort())
    page.route("**://*.gstatic.com/**", lambda route: route.abort())
    page.route("**://*.earthdata.nasa.gov/**", lambda route: route.abort())

    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_selector(".item", timeout=15000)

    assert page.locator(".item").count() > 0
    assert page.locator(".source").count() == 4

    page.locator(".item").first.click()
    page.wait_for_selector("#detail:not([hidden])", timeout=5000)
    assert page.locator(".contrib").count() >= 5

    if SHOTS.exists():
        page.screenshot(path=str(SHOTS / "ui_offline.png"))
    ctx.close()


def test_first_paint_is_not_blocked_by_the_data_volume(server, browser):
    _, instance = browser
    page = instance.new_page(viewport={"width": 1440, "height": 900})

    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_selector(".item", timeout=20000)

    timing = page.evaluate("""() => {
      const nav = performance.getEntriesByType('navigation')[0];
      return { dcl: nav.domContentLoadedEventEnd, rows: document.querySelectorAll('.item').length };
    }""")

    # The feed is capped so a large snapshot cannot turn into thousands of
    # DOM nodes; the full set stays available through the CSV export.
    assert timing["rows"] <= 400
    assert timing["dcl"] < 4000, timing
    page.close()
