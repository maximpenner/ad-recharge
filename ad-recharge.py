#!/usr/bin/env python3

import argparse
import base64
import logging
from logging.handlers import RotatingFileHandler
import sys
import time
import traceback
from pathlib import Path

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

DEFAULT_HEADLESS = True
BASE_DIR = Path(__file__).resolve().parent
USER_DATA_DIR = str(BASE_DIR / "pw-user-data")
LOG_FILE = BASE_DIR / "ad-recharge.log"
STATE_FILE = BASE_DIR / "ad-recharge.json"

NAV_TIMEOUT_MS = 25000
ACTION_TIMEOUT_MS = 10000
POST_LOAD_WAIT_MS = 4000
POST_CLICK_WAIT_MS = 5000
MAX_CONSECUTIVE_FAILURES = 3

logger = logging.getLogger("ad-recharge")
logger.setLevel(logging.INFO)
logger.propagate = False

def setup_logging():
    if logger.handlers:
        return

    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def log_info(message: str) -> None:
    logger.info(message)

def log_warning(message: str) -> None:
    logger.warning(message)

def log_error(message: str) -> None:
    logger.error(message)

def parse_args():
    parser = argparse.ArgumentParser(description="Recharge checker")
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
    parser.add_argument(
        "--window-width",
        type=int,
        default=900,
        help="Browser window width in headed mode.",
    )
    parser.add_argument(
        "--window-height",
        type=int,
        default=700,
        help="Browser window height in headed mode.",
    )
    return parser.parse_args()

def save_state(context) -> None:
    try:
        context.storage_state(path=str(STATE_FILE))
    except Exception as e:
        log_warning(f"save_state failed: {type(e).__name__}: {e}")

def sleep_until_next_cycle(interval: int) -> None:
    if interval == 0:
        log_info("interval is 0, waiting forever")
        while True:
            time.sleep(3600)
    time.sleep(interval)

def click_matching_button_on_scope(scope, label: str):
    button_labels = ["+1 GB", "1 gb", "unlimited"]

    for text in button_labels:
        locators = [
            scope.get_by_role("button", name=text, exact=False),
            scope.get_by_role("link", name=text, exact=False),
        ]

        for locator in locators:
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
                    return f"clicked matching option '{text}' in {label}"
                except Exception:
                    continue

    return None

def click_matching_button(page):
    result = click_matching_button_on_scope(page, "main page")
    if result:
        return result

    try:
        frames = page.frames
    except Exception:
        frames = []

    for i, frame in enumerate(frames):
        result = click_matching_button_on_scope(frame, f"frame-{i}")
        if result:
            return result

    return None

def launch_context(playwright, headless: bool, width: int, height: int):
    args = []
    no_viewport = False

    if not headless:
        args.append(f"--window-size={width},{height}")
        no_viewport = True

    context = playwright.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        headless=headless,
        args=args,
        no_viewport=no_viewport,
    )
    context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
    context.set_default_timeout(ACTION_TIMEOUT_MS)
    return context

def ensure_live_page(context):
    try:
        for p in context.pages:
            try:
                if not p.is_closed():
                    return p
            except Exception:
                continue
    except Exception:
        pass
    return context.new_page()

def page_health_check(page):
    try:
        if page.is_closed():
            return False
        _ = page.url
        return True
    except Exception:
        return False

def do_cycle(context):
    page = ensure_live_page(context)

    if not page_health_check(page):
        try:
            page.close()
        except Exception:
            pass
        page = context.new_page()

    URL = base64.b64decode(
        "aHR0cHM6Ly93d3cuYWxkaXRhbGsta3VuZGVucG9ydGFsLmRlL3BvcnRhbC9hdXRoL3VlYmVyc2ljaHQv"
    ).decode("utf-8")
    response = page.goto(URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    status = None
    try:
        if response is not None:
            status = response.status
    except Exception:
        pass

    page.wait_for_timeout(POST_LOAD_WAIT_MS)

    current_url = page.url.lower()
    if "login" in current_url or "signin" in current_url:
        log_warning(f"login required (status={status})")
        save_state(context)
        return

    result = click_matching_button(page)

    if result:
        log_info(f"{result} (status={status})")
        save_state(context)
        page.wait_for_timeout(POST_CLICK_WAIT_MS)

def main():
    setup_logging()
    args = parse_args()
    headless = DEFAULT_HEADLESS and not args.headed
    interval = args.interval

    mode = "headless" if headless else "headed"
    log_info(f"bot starting ({mode}, interval={interval}s)")

    consecutive_failures = 0

    with sync_playwright() as p:
        context = launch_context(
            p,
            headless=headless,
            width=args.window_width,
            height=args.window_height,
        )

        try:
            while True:
                try:
                    do_cycle(context)
                    consecutive_failures = 0

                except PlaywrightTimeoutError as e:
                    consecutive_failures += 1
                    log_warning(
                        f"timeout ({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}): {e}"
                    )

                except Exception as e:
                    consecutive_failures += 1
                    log_error(
                        f"error {type(e).__name__} ({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}): {e}"
                    )
                    tb = traceback.format_exc(limit=3).strip().replace("\n", " | ")
                    log_error(f"traceback: {tb}")

                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    log_warning("failure threshold reached, restarting browser context")
                    try:
                        save_state(context)
                    except Exception:
                        pass
                    try:
                        context.close()
                    except Exception as e:
                        log_warning(f"context close failed: {type(e).__name__}: {e}")

                    time.sleep(5)

                    context = launch_context(
                        p,
                        headless=headless,
                        width=args.window_width,
                        height=args.window_height,
                    )
                    consecutive_failures = 0
                    log_info("browser context restarted")

                sleep_until_next_cycle(interval)

        finally:
            try:
                save_state(context)
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass
            log_info("bot stopped")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        setup_logging()
        log_info("interrupted by user")
        sys.exit(130)