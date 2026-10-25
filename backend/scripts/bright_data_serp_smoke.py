#!/usr/bin/env python3
"""One-request, opt-in Bright Data SERP smoke test for SP-102.

This script is deliberately not imported by the FastAPI app or pytest. It can
only make a network request when a developer explicitly runs it with
``--confirm-live`` and has configured their local Bright Data credentials.

The request is a harmless provider-discovery query. It intentionally performs
no result polling or retries, because each additional request may consume
Bright Data credits.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_ENDPOINT = "https://api.brightdata.com/request"
SMOKE_QUERY = "document processing API providers"
REQUEST_TIMEOUT_SECONDS = 30


def parse_args() -> argparse.Namespace:
    """Require an explicit local confirmation before any network activity."""

    parser = argparse.ArgumentParser(description="Run one Bright Data SERP smoke request.")
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="required acknowledgement that this one request may consume Bright Data credits",
    )
    return parser.parse_args()


def source_urls(value: Any) -> list[str]:
    """Extract public URLs from a response without printing any untrusted body text."""

    urls: list[str] = []
    seen: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if key.lower() in {"url", "link", "source_url"} and isinstance(nested, str):
                    if nested.startswith(("https://", "http://")) and nested not in seen:
                        seen.add(nested)
                        urls.append(nested)
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return urls


def result_count(value: Any) -> int:
    """Report a conservative count from known list-style SERP result fields."""

    if not isinstance(value, dict):
        return 0
    for key in ("organic", "organic_results", "results", "items"):
        candidate = value.get(key)
        if isinstance(candidate, list):
            return len(candidate)
    multi = value.get("multi")
    if isinstance(multi, list):
        return sum(result_count(item) for item in multi)
    return 0


def safe_error_code(error: HTTPError) -> str | None:
    """Read only Bright Data's diagnostic header; never log authorization data."""

    return error.headers.get("x-brd-error-code")


def diagnostic_for_http_error(error: HTTPError) -> str:
    """Translate common one-request failures into actionable, non-secret diagnostics."""

    error_code = safe_error_code(error)
    suffix = f" (Bright Data error: {error_code})" if error_code else ""
    if error.code in {401, 403}:
        return f"Bright Data rejected the token or zone configuration: HTTP {error.code}{suffix}."
    if error.code == 502:
        return (
            f"Bright Data upstream request failed safely: HTTP 502{suffix}. "
            "Do not retry automatically."
        )
    return f"Bright Data request failed: HTTP {error.code}{suffix}."


def main() -> int:
    """Make exactly one request and print metadata-only diagnostics."""

    args = parse_args()
    if not args.confirm_live:
        print("Refusing to make a live request without --confirm-live.", file=sys.stderr)
        return 2

    api_key = os.environ.get("BRIGHT_DATA_API_KEY")
    zone = os.environ.get("BRIGHT_DATA_SERP_ZONE")
    if not api_key:
        print("BRIGHT_DATA_API_KEY is required; no request was made.", file=sys.stderr)
        return 2
    if not zone:
        print("BRIGHT_DATA_SERP_ZONE is required; no request was made.", file=sys.stderr)
        return 2

    print("Warning: this one live Bright Data request may consume free credits.", file=sys.stderr)
    payload = json.dumps(
        {
            "zone": zone,
            "url": f"https://www.google.com/search?{urlencode({'q': SMOKE_QUERY})}",
            "format": "json",
            "data_format": "parsed_light",
        }
    ).encode("utf-8")
    request = Request(
        DEFAULT_ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        # This is the script's only urlopen call. There is intentionally no retry or poll.
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
            status = response.status
            body = response.read()
    except HTTPError as error:
        print(diagnostic_for_http_error(error), file=sys.stderr)
        return 1
    except (TimeoutError, socket.timeout):
        print("Bright Data request timed out; no retry was attempted.", file=sys.stderr)
        return 1
    except URLError as error:
        print(
            f"Bright Data network request failed: {error.reason}. No retry was attempted.",
            file=sys.stderr,
        )
        return 1

    try:
        results = json.loads(body)
    except json.JSONDecodeError:
        print(f"HTTP status: {status}")
        print("Bright Data returned malformed or non-JSON results.", file=sys.stderr)
        return 1

    urls = source_urls(results)
    print(f"HTTP status: {status}")
    print(f"Provider/search result count: {result_count(results)}")
    print("Source URLs:")
    for url in urls:
        print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
