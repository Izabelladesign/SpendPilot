"""Authenticated purchase-request intake for the SpendPilot demo."""

from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Approval, Budget, Provider, PurchaseRequest, Task
from app.payment_auth import require_payment_operator
from app.policy_engine import (
    Decision,
    PaymentRequest,
    SpendingPolicy,
    evaluate_payment,
)

router = APIRouter(prefix="/api/purchase-requests", tags=["Purchase Requests"])


class CreatePurchaseRequest(BaseModel):
    task_id: str
    provider_id: str
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(pattern="^USD$")
    idempotency_key: str = Field(min_length=1, max_length=255)


class PurchaseRequestResponse(BaseModel):
    purchase_request_id: str
    decision: str
    reason: str
    approval_id: str | None = None


@router.post("", response_model=PurchaseRequestResponse)
def create_purchase_request(
    payload: CreatePurchaseRequest,
    operator: str = Depends(require_payment_operator),
    db: Session = Depends(get_db),
):
    task = db.get(Task, payload.task_id)
    if task is None:
        raise HTTPException(404, "Task not found")

    existing = (
        db.query(PurchaseRequest)
        .filter_by(
            task_id=payload.task_id,
            idempotency_key=payload.idempotency_key,
        )
        .one_or_none()
    )

    if existing:
        if (
            existing.provider_id != payload.provider_id
            or existing.amount != payload.amount
            or existing.currency != payload.currency
        ):
            raise HTTPException(409, "Idempotency key reused with different details")

        return PurchaseRequestResponse(
            purchase_request_id=existing.id,
            decision=existing.decision,
            reason=existing.decision_reason,
            approval_id=existing.approval.id if existing.approval else None,
        )

    provider = db.get(Provider, payload.provider_id)
    if provider is None:
        raise HTTPException(404, "Provider not found")

    budget = db.get(Budget, task.budget_id) if task.budget_id else None
    if budget is None:
        raise HTTPException(409, "Task has no assigned budget")

    if budget.owner_id != task.user_id:
        raise HTTPException(403, "Task and budget owners do not match")

    if budget.currency != payload.currency:
        raise HTTPException(400, "Budget currency mismatch")

    if not provider.is_approved:
        raise HTTPException(403, "Provider is not approved")

    available = budget.total - budget.spent - budget.reserved

    policy = SpendingPolicy(
        task_id=task.id,
        allowed_vendors=frozenset({provider.name}),
        max_transaction_usd=max(Decimal("0"), available),
        approval_threshold_usd=Decimal("0"),
    )

    result = evaluate_payment(
        PaymentRequest(
            task_id=task.id,
            vendor=provider.name,
            amount_usd=payload.amount,
        ),
        policy,
    )

    purchase = PurchaseRequest(
        id=str(uuid4()),
        task_id=task.id,
        provider_id=provider.id,
        idempotency_key=payload.idempotency_key,
        amount=payload.amount,
        currency=payload.currency,
        decision=result.decision.value,
        decision_reason=result.reason,
    )
    db.add(purchase)

    approval = None

    if result.decision == Decision.REVIEW_REQUIRED:
        approval = Approval(
            id=str(uuid4()),
            task_id=task.id,
            purchase_request_id=purchase.id,
            amount=payload.amount,
            currency=payload.currency,
            vendor=provider.name,
            status="PENDING",
            reason=result.reason,
        )
        db.add(approval)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            "Purchase request conflict; retry with the same idempotency key",
        )

    return PurchaseRequestResponse(
        purchase_request_id=purchase.id,
        decision=result.decision.value,
        reason=result.reason,
        approval_id=approval.id if approval else None,
    )
