
from dataclasses import dataclass
from decimal import Decimal

from app.policy_engine import (
    Decision,
    PaymentRequest,
    SpendingPolicy,
    evaluate_payment,
)
from app import payment_store
from app import persistent_budget_service as budgets
import os
from dotenv import load_dotenv

from app.onchain_verifier import verify_usdc_settlement
from app.vendor_verifier import TRUSTED_VENDORS

@dataclass(frozen=True)
class GovernedPaymentResult:
    status: str
    message: str
    idempotency_key: str


def amount_to_cents(amount: Decimal) -> int:
    cents = amount * Decimal("100")

    if (
        not cents.is_finite()
        or cents <= 0
        or cents != cents.to_integral_value()
    ):
        raise ValueError(
            "Amount must be a positive whole number of cents"
        )

    return int(cents)


def payment_fingerprint(
    request: PaymentRequest,
    policy: SpendingPolicy,
):
    return {
        "task_id": request.task_id,
        "vendor": request.vendor,
        "amount_usd": str(request.amount_usd),
        "policy_task_id": policy.task_id,
        "allowed_vendors": sorted(policy.allowed_vendors),
        "max_transaction_usd": str(policy.max_transaction_usd),
        "approval_threshold_usd": str(
            policy.approval_threshold_usd
        ),
    }


def prepare_governed_payment(
    idempotency_key: str,
    request: PaymentRequest,
    policy: SpendingPolicy,
) -> GovernedPaymentResult:
    """
    Apply policy and atomically reserve persistent budget.

    Does not sign or execute blockchain payments.
    """

    fingerprint = payment_fingerprint(request, policy)

    created = payment_store.create_payment(
        idempotency_key,
        fingerprint,
    )

    if not created:
        existing = payment_store.get_payment(idempotency_key)

        return GovernedPaymentResult(
            status=existing["status"],
            message=existing["message"] or (
                "Existing payment returned; not executed again"
            ),
            idempotency_key=idempotency_key,
        )

    result = evaluate_payment(request, policy)

    if result.decision == Decision.DENIED:
        payment_store.update_payment(
            idempotency_key,
            "DENIED",
            result.reason,
        )
        return GovernedPaymentResult(
            "DENIED",
            result.reason,
            idempotency_key,
        )

    if result.decision == Decision.REVIEW_REQUIRED:
        payment_store.update_payment(
            idempotency_key,
            "REVIEW_REQUIRED",
            result.reason,
        )
        return GovernedPaymentResult(
            "REVIEW_REQUIRED",
            result.reason,
            idempotency_key,
        )

    try:
        amount_cents = amount_to_cents(request.amount_usd)

        budgets.reserve_budget(
            task_id=request.task_id,
            payment_key=idempotency_key,
            amount_cents=amount_cents,
        )

    except (ValueError, budgets.BudgetError) as error:
        payment_store.update_payment(
            idempotency_key,
            "DENIED",
            str(error),
        )
        return GovernedPaymentResult(
            "DENIED",
            str(error),
            idempotency_key,
        )

    payment_store.update_payment(
        idempotency_key,
        "READY",
        "Policy approved and funds reserved",
    )

    return GovernedPaymentResult(
        "READY",
        "Policy approved and funds reserved",
        idempotency_key,
    )


def mark_payment_uncertain(
    idempotency_key: str,
    message: str = "Payment outcome requires reconciliation",
):
    """
    Keep funds reserved while settlement is unknown.
    """

    payment_store.update_payment(
        idempotency_key,
        "PENDING_RECONCILIATION",
        message,
    )

    return GovernedPaymentResult(
        "PENDING_RECONCILIATION",
        message,
        idempotency_key,
    )


def finalize_verified_payment(
    idempotency_key: str,
    transaction_hash: str,
    expected_payer: str,
) -> GovernedPaymentResult:
    """
    Independently verify the on-chain USDC transfer
    before committing the payment and budget.

    No private key is used.
    """

    payment = payment_store.get_payment(idempotency_key)

    if payment is None:
        raise ValueError("Payment does not exist")

    fingerprint = payment["fingerprint"]

    if payment["status"] not in {
        "IN_PROGRESS",
        "PENDING_RECONCILIATION",
        "PAID",
    }:
        raise ValueError(
            "Payment is not eligible for settlement"
        )

    vendor_name = fingerprint["vendor"]
    task_id = fingerprint["task_id"]
    amount_usd = Decimal(fingerprint["amount_usd"])
    amount_cents = amount_to_cents(amount_usd)

    if vendor_name not in TRUSTED_VENDORS:
        raise ValueError("Vendor is not trusted")

    load_dotenv(".env")

    rpc_url = os.environ["BASE_SEPOLIA_RPC_URL"]

    # This function queries Base Sepolia and checks:
    # transaction status, token, sender, recipient,
    # transfer amount, and network.
    verification = verify_usdc_settlement(
        transaction_hash=transaction_hash,
        vendor_name=vendor_name,
        expected_amount_usd=amount_usd,
        rpc_url=rpc_url,
        expected_payer=expected_payer,
    )

    if verification["verified"] is not True:
        raise ValueError("Settlement verification failed")

    payment_store.finalize_settlement_atomic(
        idempotency_key=idempotency_key,
        transaction_hash=verification["transaction_hash"],
        expected_task_id=task_id,
        expected_amount_cents=amount_cents,
    )

    return GovernedPaymentResult(
        status="PAID",
        message="USDC settlement verified on-chain",
        idempotency_key=idempotency_key,
    )

