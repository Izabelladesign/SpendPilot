
"""SpendPilot payment API routes.

Legacy payment history is preserved.
New payment preparation uses the shared SQLAlchemy database.

Demo only: no blockchain transaction is signed or broadcast here.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import payment_store
from app import persistent_budget_service as budgets
from app.database import get_db
from app.models import Budget, PurchaseRequest, Task
from app.payment_auth import require_payment_operator
from app.policy_engine import SpendingPolicy
from app.shared_payment_service import (
    PaymentPreparationError,
    prepare_shared_payment,
)


router = APIRouter(prefix="/api", tags=["SpendPilot"])


# Legacy demo policy, retained for reference.
DEMO_POLICIES = {
    "TASK-001": SpendingPolicy(
        task_id="TASK-001",
        allowed_vendors=frozenset({"spendpilot-demo"}),
        max_transaction_usd=Decimal("0.50"),
        approval_threshold_usd=Decimal("0.20"),
    )
}


class PaymentCreate(BaseModel):
    idempotency_key: str = Field(min_length=1)
    task_id: str
    vendor: str
    amount_usd: Decimal


class BudgetCreate(BaseModel):
    task_id: str
    total_cents: int = Field(ge=0)


class SharedPaymentCreate(BaseModel):
    purchase_request_id: str = Field(min_length=1)


# --------------------------------------------------
# Legacy demo budget endpoints
# --------------------------------------------------

@router.post("/budgets")
def create_task_budget(payload: BudgetCreate):
    raise HTTPException(
        status_code=403,
        detail=(
            "Legacy budget creation is disabled. "
            "Use the shared task and budget database."
        ),
    )


@router.get("/budgets/{task_id}")
def read_task_budget(task_id: str):
    budget = budgets.get_budget(task_id)

    if budget is None:
        raise HTTPException(
            status_code=404,
            detail="Legacy budget not found",
        )

    return budget


# --------------------------------------------------
# Legacy demo payment endpoints
# --------------------------------------------------

@router.post("/payments")
def create_payment(payload: PaymentCreate):
    """
    Disabled to prevent bypassing shared purchase approvals.
    """

    raise HTTPException(
        status_code=403,
        detail=(
            "Legacy payment preparation is disabled. "
            "Use POST /api/payments/prepare."
        ),
    )


@router.get("/payments")
def list_payment_history(limit: int = 50):
    try:
        return {
            "payments": payment_store.list_payments(limit)
        }
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )


@router.get("/payments/{idempotency_key}")
def read_payment(idempotency_key: str):
    payment = payment_store.get_payment(idempotency_key)

    if payment is None:
        raise HTTPException(
            status_code=404,
            detail="Legacy payment not found",
        )

    return {
        "idempotency_key": idempotency_key,
        **payment,
        "settlement": payment_store.get_verified_settlement(
            idempotency_key
        ),
    }


@router.get("/approvals")
def list_pending_approvals():
    """
    Legacy payment review records, read-only.

    These are not the shared human approval records.
    """

    payments = payment_store.list_payments(limit=100)

    return {
        "approvals": [
            {
                "idempotency_key": payment["idempotency_key"],
                "fingerprint": payment["fingerprint"],
                "status": payment["status"],
                "created_at": payment["created_at"],
            }
            for payment in payments
            if payment["status"] == "REVIEW_REQUIRED"
        ]
    }


# --------------------------------------------------
# Shared-database payment preparation
# --------------------------------------------------

@router.post("/payments/prepare")
def prepare_payment(
    payload: SharedPaymentCreate,
    operator: str = Depends(require_payment_operator),
    db: Session = Depends(get_db),
):
    """
    Validate a stored purchase and prepare a demo payment.

    Requires an authenticated payment operator.
    Requires human approval under the demo policy.
    Reserves shared budget but never transfers funds.
    """

    # 1. Find the purchase request.
    purchase = db.get(
        PurchaseRequest,
        payload.purchase_request_id,
    )

    if purchase is None:
        raise HTTPException(
            status_code=404,
            detail="Purchase request not found",
        )

    # 2. Find its task.
    task = db.get(Task, purchase.task_id)

    if task is None or task.budget_id is None:
        raise HTTPException(
            status_code=409,
            detail="Task budget is missing",
        )

    # 3. Find the shared budget.
    budget = db.get(Budget, task.budget_id)

    if budget is None:
        raise HTTPException(
            status_code=409,
            detail="Budget not found",
        )

    # 4. Find the stored provider.
    provider = purchase.provider

    if provider is None:
        raise HTTPException(
            status_code=409,
            detail="Provider not found",
        )

    # 5. Construct a server-side demo policy.
    # Every positive purchase requires human approval.
    #
    # TODO: Load an authenticated, persisted policy
    # instead of deriving it from the purchase's provider.
    policy = SpendingPolicy(
        task_id=task.id,
        allowed_vendors=frozenset({provider.name}),
        max_transaction_usd=budget.total,
        approval_threshold_usd=Decimal("0"),
    )

    # 6. Validate approval and reserve budget.
    try:
        result = prepare_shared_payment(
            db,
            purchase_request_id=purchase.id,
            policy=policy,
        )

    except PaymentPreparationError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=str(error),
        )

    # 7. Return preparation result.
    return {
        "purchase_request_id": purchase.id,
        "payment_id": result.payment_id,
        "status": result.status,
        "message": result.message,
    }
