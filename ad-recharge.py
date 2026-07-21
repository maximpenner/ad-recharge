#!/usr/bin/env python3

import argparse
import base64
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

DEFAULT_HEADLESS = True
BASE_DIR = Path(__file__).resolve().parent
USER_DATA_DIR = str(BASE_DIR / "pw-user-data")
LOG_FILE = BASE_DIR / "ad-recharge.log"
STATE_FILE = BASE_DIR / "ad-recharge.json"

def parse_args():
    parser = argparse.ArgumentParser(description="")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run with a visible browser window (default: headless mode).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        required=True,
        help="Check interval in seconds. Use 0 for infinite wait after a cycle.",
    )
    return parser.parse_args()

def log(message: str) -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")

def save_state(context) -> None:
    try:
        context.storage_state(path=str(STATE_FILE))
    except Exception:
        pass

def sleep_until_next_cycle(interval: int, cycle: int) -> None:
    if interval == 0:
        log(f"Cycle {cycle}: interval is 0, waiting forever")
        while True:
            time.sleep(3600)
    else:
        log(f"Cycle {cycle}: waiting {interval}s until next check")
        time.sleep(interval)

def click_matching_button_on_scope(scope, label: str):
    BUTTON_LABELS = ["+1 GB", "1 gb", "unlimited"]
    for text in BUTTON_LABELS:
        for locator in [
            scope.get_by_role("button", name=text, exact=False),
            scope.get_by_role("link", name=text, exact=False),
        ]:
            try:
                count = locator.count()
            except Exception:
                continue

            for i in range(count):
                element = locator.nth(i)
                try:
                    if not element.is_visible():
                        continue
                    if not element.is_enabled():
                        continue
                    element.click(timeout=5000)
                    return f"Clicked matching option: '{text}' ({label})"
                except Exception:
                    continue
    return None

def click_matching_button(page):
    result = click_matching_button_on_scope(page, "main page")
    if result:
        return result

    for i, frame in enumerate(page.frames):
        result = click_matching_button_on_scope(frame, f"frame-{i}")
        if result:
            return result

    return None

def main():
    args = parse_args()
    headless = DEFAULT_HEADLESS and not args.headed
    interval = args.interval

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=headless,
        )

        page = context.pages[0] if context.pages else context.new_page()
        cycle = 0

        mode = "headless" if headless else "headed"
        log(f"Bot started ({mode} mode, interval: {interval})")

        while True:
            cycle += 1
            try:
                log(f"Cycle {cycle}: starting check")
                URL = base64.b64decode(
                    "aHR0cHM6Ly93d3cuYWxkaXRhbGsta3VuZGVucG9ydGFsLmRlL3BvcnRhbC9hdXRoL3VlYmVyc2ljaHQv"
                ).decode("utf-8")
                page.goto(URL, wait_until="domcontentloaded")
                page.wait_for_timeout(4000)
                log(f"Cycle {cycle}: page loaded")

                current_url = page.url.lower()
                if "login" in current_url or "signin" in current_url:
                    log(f"Cycle {cycle}: login required")
                    save_state(context)
                    sleep_until_next_cycle(interval, cycle)
                    continue

                result = click_matching_button(page)

                if result:
                    log(f"Cycle {cycle}: {result}")
                    save_state(context)
                    page.wait_for_timeout(5000)
                else:
                    log(f"Cycle {cycle}: no active matching button found")

            except PlaywrightTimeoutError:
                log(f"Cycle {cycle}: timeout")
            except Exception as e:
                log(f"Cycle {cycle}: error {type(e).__name__}")

            sleep_until_next_cycle(interval, cycle)

if __name__ == "__main__":
    main()