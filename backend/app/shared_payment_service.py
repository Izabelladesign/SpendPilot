
"""Shared-database payment preparation for SpendPilot.

Demo only: reserves budget; never transfers funds.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Approval, Budget, Payment, PurchaseRequest, Task
from app.policy_engine import (
    Decision,
    PaymentRequest,
    SpendingPolicy,
    evaluate_payment,
)


class PaymentPreparationError(Exception):
    pass


@dataclass(frozen=True)
class PaymentPreparationResult:
    status: str
    message: str
    payment_id: str | None = None


def prepare_shared_payment(
    db: Session,
    *,
    purchase_request_id: str,
    policy: SpendingPolicy,
) -> PaymentPreparationResult:
    """Validate purchase and atomically reserve its shared budget."""

    purchase = db.get(PurchaseRequest, purchase_request_id)

    if purchase is None:
        raise PaymentPreparationError("Purchase request not found")

    # SECURITY: Never prepare a purchase explicitly blocked
    # or rejected by the governance system.
    purchase_decision = (purchase.decision or "").upper()

    if purchase_decision in {
        "BLOCK",
        "BLOCKED",
        "DENIED",
        "REJECTED",
    }:
        return PaymentPreparationResult(
            "DENIED",
            "Purchase was blocked or rejected by governance",
        )

    # Fail closed on unexpected or missing purchase decisions.
    if purchase_decision not in {
        "ALLOW",
        "APPROVED",
        "REVIEW",
        "REVIEW_REQUIRED",
    }:
        return PaymentPreparationResult(
            "DENIED",
            "Purchase has no valid governance decision",
        )

    task = db.get(Task, purchase.task_id)

    if task is None or task.budget_id is None:
        raise PaymentPreparationError("Task has no assigned budget")

    provider = purchase.provider

    if provider is None or not provider.is_approved:
        raise PaymentPreparationError("Provider is not approved")

    if purchase.currency != "USD":
        raise PaymentPreparationError("Only USD is supported")

    amount = Decimal(purchase.amount)

    if not amount.is_finite() or amount <= 0:
        raise PaymentPreparationError("Invalid payment amount")

    request = PaymentRequest(
        task_id=task.id,
        vendor=provider.name,
        amount_usd=amount,
    )

    result = evaluate_payment(request, policy)

    if result.decision == Decision.DENIED:
        return PaymentPreparationResult(
            "DENIED",
            result.reason,
        )

    # SECURITY: Human approval is mandatory for every
    # shared-database payment preparation.
    # Do not rely only on the policy threshold.
    approval = (
        db.query(Approval)
        .filter_by(purchase_request_id=purchase.id)
        .one_or_none()
    )

    if approval is None:
        return PaymentPreparationResult(
            "REVIEW_REQUIRED",
            "Human approval required before payment preparation",
        )

    if approval.status in {"REJECTED", "DENIED"}:
        return PaymentPreparationResult(
            "DENIED",
            "Human reviewer rejected this purchase",
        )

    if approval.status != "APPROVED":
        return PaymentPreparationResult(
            "REVIEW_REQUIRED",
            "Human approval required before payment preparation",
        )

    # Verify approval belongs to the exact stored purchase.
    if (
        approval.task_id != task.id
        or Decimal(approval.amount) != amount
        or approval.currency != purchase.currency
        or approval.vendor != provider.name
        or approval.decided_by is None
        or approval.decided_at is None
    ):
        raise PaymentPreparationError(
            "Approval does not match purchase request"
        )

    # Return existing payment without reserving funds again.
    existing = (
        db.query(Payment)
        .filter_by(purchase_request_id=purchase.id)
        .first()
    )

    if existing is not None:
        return PaymentPreparationResult(
            existing.status,
            "Existing payment returned; no additional funds reserved",
            existing.id,
        )

    # Atomically reserve shared budget.
    reservation = db.execute(
        update(Budget)
        .where(
            Budget.id == task.budget_id,
            Budget.currency == purchase.currency,
            Budget.total - Budget.spent - Budget.reserved >= amount,
        )
        .values(
            reserved=Budget.reserved + amount
        )
        .execution_options(synchronize_session=False)
    )

    if reservation.rowcount != 1:
        db.rollback()
        return PaymentPreparationResult(
            "DENIED",
            "Insufficient available budget",
        )

    payment = Payment(
        task_id=task.id,
        purchase_request_id=purchase.id,
        provider_id=provider.id,
        amount=amount,
        currency=purchase.currency,
        status="READY",
    )

    try:
        db.add(payment)
        db.commit()
        db.refresh(payment)

    except IntegrityError:
        db.rollback()

        existing = (
            db.query(Payment)
            .filter_by(purchase_request_id=purchase.id)
            .one_or_none()
        )

        if existing is None:
            raise PaymentPreparationError(
                "Payment preparation conflict"
            )

        return PaymentPreparationResult(
            existing.status,
            "Existing payment returned; no additional funds reserved",
            existing.id,
        )

    return PaymentPreparationResult(
        "READY",
        "Policy verified and budget reserved; no payment executed",
        payment.id,
    )
