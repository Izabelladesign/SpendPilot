from app.services.research_brief_verifier import (
    VerificationStatus,
    verify_research_brief,
)


def valid_brief():
    return {
        "summary": "Comparison of GitHub Copilot and Cursor.",
        "copilot_section": "GitHub Copilot information.",
        "cursor_section": "Cursor information.",
        "pricing_section": "Pricing information for both products.",
        "security_section": "Security information for both products.",
        "source_urls": [
            "https://github.com/features/copilot",
            "https://www.cursor.com/security",
        ],
        "unverified_information": (
            "None identified from the available sources."
        ),
    }


def test_valid_brief_passes():
    result = verify_research_brief(**valid_brief())

    assert result.status == VerificationStatus.VERIFIED
    assert result.verified is True
    assert all(result.checks.values())


def test_missing_copilot_fails():
    brief = valid_brief()
    brief["copilot_section"] = ""

    result = verify_research_brief(**brief)

    assert result.status == VerificationStatus.FAILED
    assert result.checks["copilot_present"] is False


def test_missing_cursor_fails():
    brief = valid_brief()
    brief["cursor_section"] = ""

    result = verify_research_brief(**brief)

    assert result.status == VerificationStatus.FAILED
    assert result.checks["cursor_present"] is False


def test_missing_pricing_fails():
    brief = valid_brief()
    brief["pricing_section"] = ""

    result = verify_research_brief(**brief)

    assert result.status == VerificationStatus.FAILED
    assert result.checks["pricing_present"] is False


def test_missing_security_fails():
    brief = valid_brief()
    brief["security_section"] = ""

    result = verify_research_brief(**brief)

    assert result.status == VerificationStatus.FAILED
    assert result.checks["security_present"] is False


def test_only_one_source_fails():
    brief = valid_brief()
    brief["source_urls"] = [
        "https://github.com/features/copilot",
    ]

    result = verify_research_brief(**brief)

    assert result.status == VerificationStatus.FAILED
    assert result.checks["two_unique_https_sources"] is False


def test_duplicate_sources_fail():
    brief = valid_brief()
    brief["source_urls"] = [
        "https://github.com/features/copilot",
        "https://github.com/features/copilot",
    ]

    result = verify_research_brief(**brief)

    assert result.status == VerificationStatus.FAILED
    assert result.checks["two_unique_https_sources"] is False


def test_http_source_does_not_count():
    brief = valid_brief()
    brief["source_urls"] = [
        "http://example.com/copilot",
        "https://www.cursor.com/security",
    ]

    result = verify_research_brief(**brief)

    assert result.status == VerificationStatus.FAILED
    assert result.checks["two_unique_https_sources"] is False


def test_missing_unverified_section_fails():
    brief = valid_brief()
    brief["unverified_information"] = ""

    result = verify_research_brief(**brief)

    assert result.status == VerificationStatus.FAILED
    assert result.checks["unverified_information_present"] is False


def test_explicit_none_unverified_is_valid():
    brief = valid_brief()
    brief["unverified_information"] = (
        "None identified from the available sources."
    )

    result = verify_research_brief(**brief)

    assert result.status == VerificationStatus.VERIFIED