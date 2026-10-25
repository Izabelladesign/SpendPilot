"""
SpendPilot: Copilot vs Cursor research-demo contract tests.

These tests validate:
- Research task requirements
- Budget and purchase handoff
- Payment/task status separation
- Research output verification
- Execution state transitions

They do NOT sign or broadcast blockchain transactions.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import re
import pytest


DEMO_TASK = {
    "task_id": "research-copilot-cursor-001",
    "quantity": 1,
    "products": ["GitHub Copilot", "Cursor"],
    "budget": Decimal("1.00"),
    "currency": "USD",
    "minimum_https_sources": 2,
    "requires_pricing": True,
    "requires_security": True,
    "requires_unknowns": True,
}


class PaymentStatus(str, Enum):
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    READY = "READY"
    PENDING_RECONCILIATION = "PENDING_RECONCILIATION"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    OUTPUT_RECEIVED = "OUTPUT_RECEIVED"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    FAILED_VERIFICATION = "FAILED_VERIFICATION"


@dataclass
class ResearchVerification:
    status: str
    reasons: list[str]
    source_count: int


def verify_research_brief(brief: str) -> ResearchVerification:
    reasons = []
    text = brief.strip()

    if not text:
        reasons.append("Research output is empty.")

    if not re.search(r"\bsummary\b", text, re.I):
        reasons.append("Readable summary missing.")

    if not re.search(r"github\s+copilot", text, re.I):
        reasons.append("GitHub Copilot coverage missing.")

    if not re.search(r"\bcursor\b", text, re.I):
        reasons.append("Cursor coverage missing.")

    if not re.search(r"\bpric(?:e|es|ing)\b", text, re.I):
        reasons.append("Pricing information missing.")

    if not re.search(r"\bsecurity\b", text, re.I):
        reasons.append("Security information missing.")

    urls = set(
        re.findall(
            r"https://[^\s<>\]\)\"']+",
            text,
            re.I,
        )
    )
    urls = {url.rstrip(".,;") for url in urls}

    if len(urls) < DEMO_TASK["minimum_https_sources"]:
        reasons.append("At least two unique HTTPS sources required.")

    if not re.search(r"\bnot verified\b", text, re.I):
        reasons.append("Unverified information must be identified.")

    return ResearchVerification(
        status="VERIFIED" if not reasons else "FAILED_VERIFICATION",
        reasons=reasons,
        source_count=len(urls),
    )


PASS_BRIEF = """
Summary:
This research brief compares GitHub Copilot and Cursor for a
50-person engineering team.

GitHub Copilot:
Pricing information and security considerations should be
reviewed against current vendor documentation.

Cursor:
Pricing information and security considerations should be
reviewed against current vendor documentation.

Sources:
https://github.com/features/copilot
https://cursor.com/pricing

Not verified:
Enterprise contract discounts and organization-specific
security configurations are not verified.
"""


@pytest.mark.parametrize(
    "amount,expected",
    [
        (Decimal("0.01"), True),
        (Decimal("0.50"), True),
        (Decimal("1.00"), True),
        (Decimal("1.01"), False),
        (Decimal("5.00"), False),
    ],
)
def test_demo_budget_boundary(amount, expected):
    assert (Decimal("0") < amount <= DEMO_TASK["budget"]) == expected


def test_research_brief_passes():
    result = verify_research_brief(PASS_BRIEF)
    assert result.status == "VERIFIED"
    assert result.source_count == 2
    assert not result.reasons


def test_research_brief_fails_with_one_source():
    brief = PASS_BRIEF.replace(
        "https://cursor.com/pricing",
        "https://github.com/features/copilot",
    )
    result = verify_research_brief(brief)
    assert result.status == "FAILED_VERIFICATION"
    assert "At least two unique HTTPS sources required." in result.reasons


def test_research_brief_fails_without_cursor():
    brief = PASS_BRIEF.replace("Cursor", "Other Product")
    brief = brief.replace("cursor.com", "example.com")
    result = verify_research_brief(brief)
    assert result.status == "FAILED_VERIFICATION"
    assert "Cursor coverage missing." in result.reasons


def test_research_brief_fails_without_security():
    brief = PASS_BRIEF.replace("security", "technical")
    result = verify_research_brief(brief)
    assert result.status == "FAILED_VERIFICATION"


def test_research_brief_fails_without_unknowns():
    brief = PASS_BRIEF.replace("Not verified", "Additional notes")
    brief = brief.replace("not verified", "pending confirmation")
    result = verify_research_brief(brief)
    assert result.status == "FAILED_VERIFICATION"


def test_research_brief_fails_when_empty():
    result = verify_research_brief("")
    assert result.status == "FAILED_VERIFICATION"


@pytest.mark.parametrize(
    "payment_status,task_status",
    [
        (PaymentStatus.SETTLED, TaskStatus.VERIFYING),
        (PaymentStatus.SETTLED, TaskStatus.FAILED_VERIFICATION),
        (PaymentStatus.SETTLED, TaskStatus.VERIFIED),
        (PaymentStatus.READY, TaskStatus.PENDING),
        (PaymentStatus.FAILED, TaskStatus.PENDING),
    ],
)
def test_payment_and_task_statuses_are_independent(
    payment_status, task_status
):
    state = {
        "payment_status": payment_status.value,
        "task_status": task_status.value,
    }
    assert state["payment_status"] == payment_status.value
    assert state["task_status"] == task_status.value

    if payment_status == PaymentStatus.READY:
        assert state["payment_status"] != "PAID"

    if task_status == TaskStatus.FAILED_VERIFICATION:
        assert state["task_status"] != "VERIFIED"


def test_research_purchase_handoff_fields():
    purchase = {
        "task_id": DEMO_TASK["task_id"],
        "provider_id": "research-provider-a",
        "purchase_id": "research-purchase-001",
        "amount": Decimal("0.50"),
        "currency": "USD",
        "task_requirements": DEMO_TASK,
        "idempotency_key": "research-purchase-001-v1",
    }

    required = {
        "task_id",
        "provider_id",
        "purchase_id",
        "amount",
        "currency",
        "task_requirements",
        "idempotency_key",
    }

    assert required <= purchase.keys()
    assert purchase["amount"] <= DEMO_TASK["budget"]


def test_execution_state_order():
    states = [
        "APPROVED",
        "READY",
        "PAYMENT_EXECUTION",
        "OUTPUT_RECEIVED",
        "VERIFYING",
        "VERIFIED",
    ]
    assert states.index("READY") < states.index("PAYMENT_EXECUTION")
    assert states.index("OUTPUT_RECEIVED") < states.index("VERIFIED")


def test_payment_settlement_does_not_imply_verified():
    payment_status = PaymentStatus.SETTLED
    task_status = TaskStatus.FAILED_VERIFICATION

    assert payment_status == PaymentStatus.SETTLED
    assert task_status != TaskStatus.VERIFIED
