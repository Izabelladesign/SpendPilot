from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlparse

from app import payment_store
from app.x402_settlement import extract_transaction_hash
from app.unified_payment_service import finalize_verified_payment
from app.payment_adapter import (
    inspect_x402_payment,
    execute_x402_payment,
)


@dataclass(frozen=True)
class GovernedX402Result:
    status: str
    message: str
    idempotency_key: str
    http_status: int | None = None


def _require_local_demo_url(resource_url: str) -> None:
    parsed = urlparse(resource_url)

    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port != 8001
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Only the local x402 demo resource is permitted")


async def execute_governed_x402(
    *,
    idempotency_key: str,
    resource_url: str,
) -> GovernedX402Result:
    """
    Execute a previously authorized payment once.

    READY must only be produced after policy approval and
    successful persistent budget reservation.
    """
    _require_local_demo_url(resource_url)

    payment = payment_store.get_payment(idempotency_key)

    if payment is None:
        raise ValueError("Payment not found")

    status = payment["status"]

    if status != "READY":
        return GovernedX402Result(
            status=status,
            message="Payment is not READY; no new execution attempted",
            idempotency_key=idempotency_key,
        )

    fingerprint = payment["fingerprint"]

    vendor = fingerprint["vendor"]
    amount = Decimal(fingerprint["amount_usd"])

    # Inspect the merchant's challenge BEFORE claiming or signing.
    # This checks trusted recipient, Base Sepolia, USDC and amount.
    await inspect_x402_payment(
        resource_url=resource_url,
        vendor_name=vendor,
        approved_amount_usd=amount,
    )

    # Atomic claim: only one caller can proceed to execution.
    claimed = payment_store.claim_payment_execution(idempotency_key)

    if not claimed:
        return GovernedX402Result(
            status="PENDING_RECONCILIATION",
            message="Execution already claimed; do not retry",
            idempotency_key=idempotency_key,
        )

    # From here onward, never automatically retry this payment.
    # An uncertain network result could still have settled.
    try:
        result = await execute_x402_payment(
            resource_url=resource_url,
            vendor_name=vendor,
            approved_amount_usd=amount,
        )
    except Exception as exc:
        return GovernedX402Result(
            status="PENDING_RECONCILIATION",
            message=f"Execution outcome uncertain: {type(exc).__name__}",
            idempotency_key=idempotency_key,
        )

    if not result.success or not result.payment_response:
        return GovernedX402Result(
            status="PENDING_RECONCILIATION",
            message="Payment outcome uncertain; reconciliation required",
            idempotency_key=idempotency_key,
            http_status=result.status_code,
        )

    try:
        transaction_hash = extract_transaction_hash(
            result.payment_response
        )

        from eth_account import Account
        import os

        payer = Account.from_key(
            os.environ["PAYMENT_PRIVATE_KEY"]
        ).address

        verified = finalize_verified_payment(
            idempotency_key,
            transaction_hash,
            payer,
        )

    except Exception as exc:
        return GovernedX402Result(
            status="PENDING_RECONCILIATION",
            message=(
                "Settlement verification pending: "
                f"{type(exc).__name__}"
            ),
            idempotency_key=idempotency_key,
            http_status=result.status_code,
        )

    return GovernedX402Result(
        status=verified.status,
        message=verified.message,
        idempotency_key=idempotency_key,
        http_status=result.status_code,
    )



def reconcile_governed_x402(
    *,
    idempotency_key: str,
    transaction_hash: str,
    expected_payer: str,
) -> GovernedX402Result:
    """
    Independently verify a Base Sepolia USDC settlement
    and atomically commit the reserved task budget.

    Never trust a transaction hash without on-chain verification.
    """
    from app.unified_payment_service import finalize_verified_payment

    payment = payment_store.get_payment(idempotency_key)

    if payment is None:
        raise ValueError("Payment not found")

    if payment["status"] not in {"PENDING_RECONCILIATION", "PAID"}:
        raise ValueError(
            "Payment must have a claimed execution before reconciliation"
        )

    result = finalize_verified_payment(
        idempotency_key,
        transaction_hash,
        expected_payer,
    )

    return GovernedX402Result(
        status=result.status,
        message=result.message,
        idempotency_key=idempotency_key,
    )
