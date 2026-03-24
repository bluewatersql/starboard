#!/usr/bin/env python3
"""
Debug Browser - Playwright-based browser with automatic logging.

Launches Chrome with automatic capture of:
- Console messages (log, warn, error, info, debug)
- Network requests and responses
- JavaScript errors and exceptions
- Page navigations
- Dialog events (alerts, confirms, prompts)

Logs are written to .debug/browser/ with timestamps.

Usage:
    python scripts/debug_browser.py [URL]
    python scripts/debug_browser.py http://localhost:3000
    make dev-browser
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import ConsoleMessage, Dialog, Page, Request, Response

# Configuration
DEFAULT_URL = "http://localhost:3000"
DEBUG_DIR = Path(".debug/browser")
LOG_FILES = {
    "console": "console.log",
    "network": "network.log",
    "errors": "errors.log",
    "events": "events.log",
}


def timestamp() -> str:
    """Return ISO timestamp in UTC."""
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def ensure_debug_dir() -> None:
    """Create debug directory if it doesn't exist."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)


def clear_old_logs() -> None:
    """Clear old log files for fresh session."""
    for log_file in LOG_FILES.values():
        log_path = DEBUG_DIR / log_file
        if log_path.exists():
            log_path.unlink()


def write_log(log_type: str, message: str) -> None:
    """Write a log entry to the appropriate file."""
    log_file = LOG_FILES.get(log_type, "events.log")
    log_path = DEBUG_DIR / log_file
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(message + "\n")


def format_console_message(msg: ConsoleMessage) -> str:
    """Format a console message for logging."""
    msg_type = msg.type.upper()
    text = msg.text
    location = msg.location

    location_str = ""
    if location:
        url = location.get("url", "")
        line = location.get("lineNumber", "")
        col = location.get("columnNumber", "")
        if url:
            # Shorten URL for readability
            if "localhost" in url:
                url = url.split("localhost")[1] if "localhost" in url else url
            location_str = f" @ {url}:{line}:{col}"

    return f"[{timestamp()}] [{msg_type:7}] {text}{location_str}"


def format_request(request: Request) -> str:
    """Format a network request for logging."""
    method = request.method
    url = request.url
    resource_type = request.resource_type

    # Truncate long URLs
    display_url = url if len(url) < 150 else url[:147] + "..."

    return f"[{timestamp()}] [REQUEST ] {method:6} {resource_type:12} {display_url}"


def format_response(response: Response) -> str:
    """Format a network response for logging."""
    status = response.status
    url = response.url

    # Status indicator
    if status < 300:
        status_indicator = "✓"
    elif status < 400:
        status_indicator = "→"
    else:
        status_indicator = "✗"

    # Truncate long URLs
    display_url = url if len(url) < 150 else url[:147] + "..."

    return f"[{timestamp()}] [RESPONSE] {status_indicator} {status:3} {display_url}"


async def setup_page_listeners(page: Page) -> None:
    """Set up all event listeners for the page."""

    # Console messages
    def on_console(msg: ConsoleMessage) -> None:
        formatted = format_console_message(msg)
        write_log("console", formatted)
        # Also print errors and warnings to terminal
        if msg.type in ("error", "warning"):
            print(f"  {formatted}")

    page.on("console", on_console)

    # Network requests
    def on_request(request: Request) -> None:
        formatted = format_request(request)
        write_log("network", formatted)

    page.on("request", on_request)

    # Network responses
    def on_response(response: Response) -> None:
        formatted = format_response(response)
        write_log("network", formatted)
        # Log failed requests to errors
        if response.status >= 400:
            write_log(
                "errors", f"[{timestamp()}] [HTTP {response.status}] {response.url}"
            )
            print(f"  [HTTP {response.status}] {response.url}")

    page.on("response", on_response)

    # Page errors (uncaught exceptions)
    def on_page_error(error: Exception) -> None:
        error_msg = f"[{timestamp()}] [PAGE ERROR] {error}"
        write_log("errors", error_msg)
        print(f"  ⚠️  {error_msg}")

    page.on("pageerror", on_page_error)

    # Request failures
    def on_request_failed(request: Request) -> None:
        failure = request.failure
        failure_text = failure if failure else "unknown"
        error_msg = f"[{timestamp()}] [REQUEST FAILED] {request.method} {request.url} - {failure_text}"
        write_log("errors", error_msg)
        write_log("network", error_msg)
        print(f"  ⚠️  Request failed: {request.url}")

    page.on("requestfailed", on_request_failed)

    # Dialog events (alerts, confirms, prompts)
    async def on_dialog(dialog: Dialog) -> None:
        dialog_type = dialog.type
        message = dialog.message
        event_msg = f"[{timestamp()}] [DIALOG] {dialog_type}: {message}"
        write_log("events", event_msg)
        print(f"  💬 Dialog ({dialog_type}): {message}")
        # Auto-accept dialogs to prevent blocking
        await dialog.accept()

    page.on("dialog", on_dialog)

    # Page crash
    def on_crash() -> None:
        error_msg = f"[{timestamp()}] [CRASH] Page crashed!"
        write_log("errors", error_msg)
        print(f"  💥 {error_msg}")

    page.on("crash", on_crash)

    # Download events
    def on_download(download: object) -> None:
        event_msg = f"[{timestamp()}] [DOWNLOAD] File download initiated"
        write_log("events", event_msg)
        print("  📥 Download started")

    page.on("download", on_download)

    # Frame navigation
    def on_frame_navigated(frame: object) -> None:
        if hasattr(frame, "url"):
            url = frame.url  # type: ignore - property, not method
            event_msg = f"[{timestamp()}] [NAVIGATE] {url}"
            write_log("events", event_msg)

    page.on("framenavigated", on_frame_navigated)


async def main(url: str, headless: bool = False) -> None:
    """Main browser launch and monitoring loop."""
    # Import here to give better error message if not installed
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Error: playwright is not installed.")
        print("Install it with: pip install playwright && playwright install chromium")
        sys.exit(1)

    ensure_debug_dir()
    clear_old_logs()

    print("\n" + "=" * 60)
    print("🌐 Debug Browser - Playwright Chrome with Logging")
    print("=" * 60)
    print(f"  URL:      {url}")
    print(f"  Logs:     {DEBUG_DIR.absolute()}/")
    print(f"  Headless: {headless}")
    print("-" * 60)
    print("  Log files:")
    for name, filename in LOG_FILES.items():
        print(f"    • {name:8} → {filename}")
    print("-" * 60)
    print("  Press Ctrl+C to stop")
    print("=" * 60 + "\n")

    # Write session start marker
    session_start = (
        f"\n{'=' * 60}\nSession started: {timestamp()}\nURL: {url}\n{'=' * 60}\n"
    )
    for log_type in LOG_FILES:
        write_log(log_type, session_start)

    shutdown_event = asyncio.Event()

    def signal_handler(sig: int, frame: object) -> None:
        print("\n\n🛑 Shutting down browser...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    async with async_playwright() as p:
        # Launch browser with dev tools available
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--auto-open-devtools-for-tabs",  # Open DevTools automatically
            ],
        )

        # Create context with viewport
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True,  # Allow self-signed certs for local dev
        )

        # Create page and set up listeners
        page = await context.new_page()
        await setup_page_listeners(page)

        # Handle new pages/tabs
        async def on_new_page(new_page: Page) -> None:
            print("  📄 New tab opened")
            await setup_page_listeners(new_page)

        context.on("page", on_new_page)

        # Navigate to URL
        try:
            print(f"🔗 Navigating to {url}...")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            print("✅ Page loaded\n")
        except Exception as e:
            print(f"⚠️  Navigation error: {e}")
            print("   Browser will stay open - navigate manually if needed.\n")

        # Wait for shutdown signal
        await shutdown_event.wait()

        # Write session end marker
        session_end = f"\n{'=' * 60}\nSession ended: {timestamp()}\n{'=' * 60}\n"
        for log_type in LOG_FILES:
            write_log(log_type, session_end)

        # Close browser
        await browser.close()

    print("\n✅ Browser closed. Logs saved to:")
    for _name, filename in LOG_FILES.items():
        log_path = DEBUG_DIR / filename
        if log_path.exists():
            size = log_path.stat().st_size
            print(f"   • {log_path} ({size:,} bytes)")
    print()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Launch Chrome browser with automatic debug logging",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Open localhost:3000
  %(prog)s http://localhost:8000    # Open specific URL
  %(prog)s --headless               # Run headless (for CI)

Log files are written to .debug/browser/:
  • console.log  - All console messages
  • network.log  - HTTP requests and responses
  • errors.log   - Errors and failures
  • events.log   - Dialogs, downloads, navigation
        """,
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=DEFAULT_URL,
        help=f"URL to open (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(main(args.url, headless=args.headless))
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl+C
