"""Structural verification for the SpendPilot research brief.

This verifies that required sections are present.
It does NOT fact-check claims or prove that sources are accurate,
relevant, current, or reachable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    message: str
    checks: dict[str, bool]

    @property
    def verified(self) -> bool:
        return self.status == VerificationStatus.VERIFIED


def _valid_https_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False

    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
    )


def verify_research_brief(
    *,
    summary: str,
    copilot_section: str,
    cursor_section: str,
    pricing_section: str,
    security_section: str,
    source_urls: list[str],
    unverified_information: str,
) -> VerificationResult:
    """Verify the required structure of a Copilot vs Cursor brief."""

    valid_sources = {
        url.strip()
        for url in source_urls
        if isinstance(url, str)
        and url.strip()
        and _valid_https_url(url.strip())
    }

    checks = {
        "summary_present": bool(summary.strip()),
        "copilot_present": bool(copilot_section.strip()),
        "cursor_present": bool(cursor_section.strip()),
        "pricing_present": bool(pricing_section.strip()),
        "security_present": bool(security_section.strip()),
        "two_unique_https_sources": len(valid_sources) >= 2,
        "unverified_information_present": bool(
            unverified_information.strip()
        ),
    }

    failed = [
        check
        for check, passed in checks.items()
        if not passed
    ]

    if failed:
        return VerificationResult(
            status=VerificationStatus.FAILED,
            message=(
                "Research brief failed structural verification: "
                + ", ".join(failed)
            ),
            checks=checks,
        )

    return VerificationResult(
        status=VerificationStatus.VERIFIED,
        message=(
            "Research brief structure verified. "
            "This does not establish factual accuracy, source relevance, "
            "source reachability, or freshness."
        ),
        checks=checks,
    )