
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class Decision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True)
class SpendingPolicy:
    task_id: str
    allowed_vendors: frozenset[str]
    max_transaction_usd: Decimal
    approval_threshold_usd: Decimal


@dataclass(frozen=True)
class PaymentRequest:
    task_id: str
    vendor: str
    amount_usd: Decimal


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    reason: str


def evaluate_payment(
    request: PaymentRequest,
    policy: SpendingPolicy,
) -> PolicyResult:

    if request.task_id != policy.task_id:
        return PolicyResult(
            Decision.DENIED,
            "Payment is outside the authorized task",
        )

    if request.vendor not in policy.allowed_vendors:
        return PolicyResult(
            Decision.DENIED,
            "Vendor is not authorized",
        )

    if request.amount_usd <= 0:
        return PolicyResult(
            Decision.DENIED,
            "Payment amount must be positive",
        )

    if request.amount_usd > policy.max_transaction_usd:
        return PolicyResult(
            Decision.DENIED,
            "Payment exceeds transaction limit",
        )

    if request.amount_usd > policy.approval_threshold_usd:
        return PolicyResult(
            Decision.REVIEW_REQUIRED,
            "Human approval required",
        )

    return PolicyResult(
        Decision.APPROVED,
        "Payment authorized",
    )
