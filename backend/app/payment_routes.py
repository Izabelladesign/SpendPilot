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
from app.governed_x402_service import execute_governed_x402
from app.policy_engine import SpendingPolicy
from app.shared_payment_service import (
    PaymentPreparationError,
    prepare_shared_payment,
)

router = APIRouter(prefix="/api", tags=["SpendPilot"])


def require_explicit_testnet_execution():
    """Separate opt-in for live Base Sepolia testnet transfers."""
    import os
    if os.getenv("SPENDPILOT_ENABLE_TESTNET_X402") != "true":
        raise HTTPException(
            status_code=403,
            detail="Real testnet x402 execution is disabled by default",
        )



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


class GovernedX402ExecutionRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    resource_url: str = "http://127.0.0.1:8001/paid-resource"


@router.post("/payments/execute-x402")
async def execute_x402_payment_route(
    payload: GovernedX402ExecutionRequest,
    operator: str = Depends(require_payment_operator),
    testnet_enabled: None = Depends(require_explicit_testnet_execution),
):
    """Execute an already-READY governed-ledger payment once."""
    try:
        result = await execute_governed_x402(
            idempotency_key=payload.idempotency_key,
            resource_url=payload.resource_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        # Avoid returning exception details that could expose secrets.
        raise HTTPException(
            status_code=502,
            detail=f"Governed execution failed: {type(exc).__name__}",
        ) from exc

    return {
        "status": result.status,
        "message": result.message,
        "idempotency_key": result.idempotency_key,
        "http_status": result.http_status,
    }


@router.post("/payments/execute-purchase-x402")
async def execute_approved_purchase_x402(
    purchase_request_id: str,
    operator: str = Depends(require_payment_operator),
    testnet_enabled: None = Depends(require_explicit_testnet_execution),
    db: Session = Depends(get_db),
):
    """Execute an approved shared purchase through governed x402."""
    from decimal import Decimal
    from sqlalchemy import update
    from app.models import (
        Approval, Budget, BudgetReservation, Payment,
        PurchaseRequest, Task,
    )
    from app.payment_store import connect
    from app.vendor_verifier import TRUSTED_VENDORS
    from app.governed_x402_service import execute_governed_x402

    purchase = db.get(PurchaseRequest, purchase_request_id)
    if purchase is None:
        raise HTTPException(404, "Purchase request not found")

    shared_payment = (
        db.query(Payment)
        .filter_by(purchase_request_id=purchase.id)
        .one_or_none()
    )
    if shared_payment is None:
        raise HTTPException(409, "Prepare the shared payment first")

    task = db.get(Task, purchase.task_id)
    if task is None or task.budget_id is None:
        raise HTTPException(409, "Purchase task has no budget")

    approval = (
        db.query(Approval)
        .filter_by(purchase_request_id=purchase.id)
        .one_or_none()
    )
    if (
        approval is None
        or approval.status != "APPROVED"
        or approval.decided_by is None
        or approval.decided_at is None
    ):
        raise HTTPException(409, "Explicit human approval is required")

    if shared_payment.status not in {"READY", "PAID"}:
        raise HTTPException(409, "Shared payment is not ready")

    provider = purchase.provider
    if provider is None or not provider.is_approved:
        raise HTTPException(409, "Provider is not approved")

    # Fail closed: only a vendor explicitly present in the trusted
    # registry may be charged. Do not infer trust from a display name.
    vendor_name = (provider.metadata_json or {}).get("x402_vendor_name", "")
    if vendor_name not in TRUSTED_VENDORS:
        raise HTTPException(
            409,
            "Provider needs a trusted x402_vendor_name in its metadata",
        )

    amount = Decimal(purchase.amount)

    # Copilot-vs-Cursor research demo: maximum $1 per purchase.
    # This is an additional limit, not a replacement for budget policy.
    if amount > Decimal("1.00"):
        raise HTTPException(409, "Research demo spending cap exceeded")

    if (
        purchase.currency != "USD"
        or amount <= 0
        or amount != Decimal(shared_payment.amount)
        or shared_payment.task_id != task.id
        or shared_payment.provider_id != provider.id
    ):
        raise HTTPException(409, "Purchase and payment details do not match")

    budget = db.get(Budget, task.budget_id)
    reservation = (
        db.query(BudgetReservation)
        .filter_by(purchase_request_id=purchase.id)
        .one_or_none()
    )
    if (
        budget is None
        or reservation is None
        or reservation.status != "ACTIVE"
        or reservation.budget_id != budget.id
        or Decimal(reservation.amount) != amount
    ):
        raise HTTPException(409, "Active matching budget reservation required")

    # A stable key binds retries to this exact shared payment.
    key = f"shared-payment:{shared_payment.id}"

    # The persistent ledger must already have its own budget for this
    # task. Do not silently create or double-reserve one here.
    from app import persistent_budget_service as persistent_budgets
    from app.unified_payment_service import prepare_governed_payment
    from app.policy_engine import PaymentRequest, SpendingPolicy

    persistent_budget = persistent_budgets.get_budget(task.id)
    if persistent_budget is None:
        raise HTTPException(
            409,
            "Persistent governed budget missing; reconcile budget setup first",
        )

    policy = SpendingPolicy(
        task_id=task.id,
        allowed_vendors=frozenset({vendor_name}),
        max_transaction_usd=amount,
        approval_threshold_usd=amount,
    )
    governed = prepare_governed_payment(
        idempotency_key=key,
        request=PaymentRequest(
            task_id=task.id,
            vendor=vendor_name,
            amount_usd=amount,
        ),
        policy=policy,
    )
    if governed.status not in {"READY", "PAID"}:
        return {
            "status": governed.status,
            "message": governed.message,
            "idempotency_key": key,
            "purchase_request_id": purchase.id,
        }

    # Never re-execute a payment that is already verified as PAID.
    # A retry may only reconcile shared accounting.
    if governed.status != "PAID":
        try:
            result = await execute_governed_x402(
                idempotency_key=key,
                resource_url="http://127.0.0.1:8001/paid-resource",
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

        if result.status != "PAID":
            return {
                "status": result.status,
                "message": result.message,
                "idempotency_key": key,
                "purchase_request_id": purchase.id,
                "payment_id": shared_payment.id,
            }

    # Get the transaction hash that the governed verifier recorded.
    with connect() as conn:
        row = conn.execute(
            "SELECT transaction_hash FROM verified_settlements "
            "WHERE idempotency_key = ?",
            (key,),
        ).fetchone()

    if row is None or not row[0]:
        raise HTTPException(
            409,
            "Settlement needs reconciliation; no verified hash recorded",
        )
    tx_hash = row[0]

    # Synchronize shared accounting in one SQLAlchemy transaction.
    try:
        if reservation.status == "ACTIVE":
            changed = db.execute(
                update(Budget)
                .where(
                    Budget.id == budget.id,
                    Budget.reserved >= amount,
                )
                .values(
                    reserved=Budget.reserved - amount,
                    spent=Budget.spent + amount,
                )
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                raise ValueError("Shared budget reconciliation failed")

            reservation.status = "COMMITTED"

        shared_payment.status = "PAID"
        shared_payment.transaction_reference = tx_hash
        db.commit()
    except Exception:
        db.rollback()
        # The on-chain settlement may already be final. Do not retry
        # the transfer; reconcile the shared database using the same key.
        raise HTTPException(
            409,
            "On-chain settlement verified; shared accounting needs reconciliation",
        )

    return {
        "status": "PAID",
        "message": "Settlement verified; shared budget committed",
        "purchase_request_id": purchase.id,
        "payment_id": shared_payment.id,
        "idempotency_key": key,
        "transaction_hash": tx_hash,
    }

@router.get("/payments/purchase/{purchase_request_id}/evidence")
def read_purchase_settlement_evidence(
    purchase_request_id: str,
    operator: str = Depends(require_payment_operator),
    db: Session = Depends(get_db),
):
    """Read verified Base Sepolia evidence; never sign or broadcast."""
    from app.models import Payment, BudgetReservation
    from app.payment_store import connect
    from app.vendor_verifier import TRUSTED_VENDORS

    purchase = db.get(PurchaseRequest, purchase_request_id)
    if purchase is None:
        raise HTTPException(404, "Purchase request not found")
    payment = db.query(Payment).filter_by(purchase_request_id=purchase.id).one_or_none()
    if payment is None:
        raise HTTPException(404, "Shared payment not found")

    key = f"shared-payment:{payment.id}"
    governed = payment_store.get_payment(key)
    governed_status = governed["status"] if governed else "NOT_PREPARED"
    reservation = db.query(BudgetReservation).filter_by(purchase_request_id=purchase.id).one_or_none()
    vendor_name = (purchase.provider.metadata_json or {}).get("x402_vendor_name", "") if purchase.provider else ""
    vendor = TRUSTED_VENDORS.get(vendor_name)
    with connect() as conn:
        row = conn.execute(
            "SELECT transaction_hash, verified_at FROM verified_settlements WHERE idempotency_key = ?",
            (key,),
        ).fetchone()

    # A transaction is displayed as verified only after BOTH ledgers agree.
    settled = bool(
        row and row[0]
        and governed_status == "PAID"
        and payment.status == "PAID"
        and reservation is not None
        and reservation.status == "COMMITTED"
        and payment.transaction_reference == row[0]
    )
    return {
        "purchase_request_id": purchase.id,
        "payment_id": payment.id,
        "idempotency_key": key,
        "status": "PAID" if settled else ("PENDING_RECONCILIATION" if row else governed_status),
        "shared_payment_status": payment.status,
        "governed_payment_status": governed_status,
        "settlement_verified": settled,
        "transaction_hash": row[0] if settled else None,
        "verified_at": row[1] if settled else None,
        "network": vendor.network if vendor else None,
        "asset": vendor.asset if vendor else None,
        "recipient": vendor.recipient if vendor else None,
        "amount_usd": str(purchase.amount),
        "evidence_type": "verified_onchain" if settled else "not_verified",
        "research_verification_status": "SEPARATE_FROM_PAYMENT",
    }

