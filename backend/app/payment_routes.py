
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import payment_store
from app import persistent_budget_service as budgets
from app.policy_engine import PaymentRequest, SpendingPolicy
from app.unified_payment_service import prepare_governed_payment

router = APIRouter(prefix="/api", tags=["SpendPilot"])


# Demo policy configuration.
# Replace with authenticated, server-side policy storage
# before allowing real agent payments.
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


@router.post("/budgets")
def create_task_budget(payload: BudgetCreate):
    if payload.task_id not in DEMO_POLICIES:
        raise HTTPException(403, "Unknown task")

    try:
        created = budgets.create_budget(
            payload.task_id,
            payload.total_cents,
        )
    except budgets.BudgetError as error:
        raise HTTPException(400, str(error))

    return {
        "created": created,
        "budget": budgets.get_budget(payload.task_id),
    }


@router.get("/budgets/{task_id}")
def read_task_budget(task_id: str):
    budget = budgets.get_budget(task_id)

    if budget is None:
        raise HTTPException(404, "Budget not found")

    return budget


@router.post("/payments")
def create_payment(payload: PaymentCreate):
    policy = DEMO_POLICIES.get(payload.task_id)

    if policy is None:
        raise HTTPException(403, "Task is not authorized")

    request = PaymentRequest(
        task_id=payload.task_id,
        vendor=payload.vendor,
        amount_usd=payload.amount_usd,
    )

    try:
        result = prepare_governed_payment(
            idempotency_key=payload.idempotency_key,
            request=request,
            policy=policy,
        )
    except ValueError as error:
        raise HTTPException(409, str(error))

    return {
        "idempotency_key": result.idempotency_key,
        "status": result.status,
        "message": result.message,
    }


@router.get("/payments")
def list_payment_history(limit: int = 50):
    try:
        return {"payments": payment_store.list_payments(limit)}
    except ValueError as error:
        raise HTTPException(400, str(error))


@router.get("/payments/{idempotency_key}")
def read_payment(idempotency_key: str):
    payment = payment_store.get_payment(idempotency_key)

    if payment is None:
        raise HTTPException(404, "Payment not found")

    return {
        "idempotency_key": idempotency_key,
        **payment,
        "settlement": payment_store.get_verified_settlement(
            idempotency_key
        ),
    }


@router.get("/approvals")
def list_pending_approvals():
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
