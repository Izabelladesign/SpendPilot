"""Safe, deterministic end-to-end demo run for the enterprise experience.

The local demo mirrors the product workflow without contacting a provider,
reading a vendor account, or moving money. It is intentionally separate from
the live provider and payment adapters so the demo cannot silently become a
paid integration.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.models import Task
from app.services.research_brief_verifier import verify_research_brief

LOCAL_SCENARIO_PHRASES = ("copilot", "cursor")


def is_local_demo_task(task: Task) -> bool:
    objective = task.objective.casefold()
    return all(phrase in objective for phrase in LOCAL_SCENARIO_PHRASES)


def build_local_demo(task: Task) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a structured local run and its verifiable research brief."""

    budget_cap = Decimal(task.budget.total) if task.budget else Decimal("0")
    budget_text = f"{budget_cap:.2f} USD"
    candidates = [
        {
            "name": "GitHub Copilot",
            "rank": 1,
            "selected": True,
            "comparison": "Preferred fit for a team-wide managed rollout in this demo scenario.",
            "evidence": ["https://github.com/features/copilot"],
        },
        {
            "name": "Cursor",
            "rank": 2,
            "selected": False,
            "comparison": "Strong alternative kept visible for reviewer comparison.",
            "evidence": ["https://cursor.com/pricing"],
        },
    ]
    recommendation = {
        "selectedProduct": "GitHub Copilot",
        "alternativeProduct": "Cursor",
        "rationale": (
            "The local decision fixture ranks GitHub Copilot first for a team-wide "
            "managed rollout. Cursor remains visible as the alternative instead of "
            "being hidden behind a black-box answer."
        ),
        "estimatedResearchCost": "0.00 USD",
        "evidenceStatus": "SIMULATED_PUBLIC_METADATA",
    }
    governance = {
        "status": "REVIEW_REQUIRED",
        "budgetCap": budget_text,
        "approvalRequired": True,
        "paymentAuthorized": False,
        "reason": (
            "Recommendation is within the local demo scenario, but a human must "
            "approve before any purchase."
        ),
    }
    purchase = {
        "state": "PREVIEW_READY",
        "executed": False,
        "fundsMoved": False,
        "providerCalled": False,
        "nextStep": "Human approval and a configured provider connector are required.",
    }
    license_health = {
        "mode": "SAMPLE_TELEMETRY",
        "vendorAccountsAccessed": False,
        "items": [
            {
                "id": "figma",
                "product": "Figma Professional",
                "seats": "3 of 18 seats",
                "detail": "No activity in 30+ days",
                "action": "Review seats",
            },
            {
                "id": "notion",
                "product": "Notion Plus",
                "seats": "2 of 12 seats",
                "detail": "Assigned but never activated",
                "action": "Review seats",
            },
            {
                "id": "slack",
                "product": "Slack guest access",
                "seats": "7 guests",
                "detail": "Access review due this week",
                "action": "Review access",
            },
        ],
    }
    demo_run = {
        "mode": "LOCAL_SIMULATION",
        "scenario": "GitHub Copilot vs Cursor",
        "candidates": candidates,
        "recommendation": recommendation,
        "governance": governance,
        "purchase": purchase,
        "licenseHealth": license_health,
    }

    brief = {
        "summary": (
            "Recommendation: GitHub Copilot is the preferred option for a 50-person "
            "engineering team; Cursor remains the comparison alternative."
        ),
        "copilotSection": (
            "GitHub Copilot is the selected product in this local demo because it is "
            "treated as the stronger fit for a team-wide managed rollout."
        ),
        "cursorSection": (
            "Cursor is the researched alternative and remains visible for reviewer comparison."
        ),
        "pricingSection": (
            "The local demo compares pricing evidence structurally; it does not "
            "claim a live quote or charge a provider."
        ),
        "securitySection": (
            "Security details require review against current vendor documentation "
            "before a production purchase."
        ),
        "sourceUrls": [
            "https://github.com/features/copilot",
            "https://cursor.com/pricing",
        ],
        "unverifiedInformation": (
            "Enterprise discounts, current terms, and organization-specific settings "
            "are not verified."
        ),
    }
    return {"demoRun": demo_run, "researchBrief": brief}, brief


def verify_local_demo(brief: dict[str, Any]) -> dict[str, Any]:
    verification = verify_research_brief(
        summary=brief["summary"],
        copilot_section=brief["copilotSection"],
        cursor_section=brief["cursorSection"],
        pricing_section=brief["pricingSection"],
        security_section=brief["securitySection"],
        source_urls=brief["sourceUrls"],
        unverified_information=brief["unverifiedInformation"],
    )
    return {
        "status": verification.status.value,
        "message": verification.message,
        "checks": verification.checks,
    }
