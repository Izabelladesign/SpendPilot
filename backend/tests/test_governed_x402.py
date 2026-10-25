import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app import payment_store
from app.governed_x402_service import execute_governed_x402

URL = "http://127.0.0.1:8001/paid-resource"


def run_payment(key):
    return asyncio.run(
        execute_governed_x402(
            idempotency_key=key,
            resource_url=URL,
        )
    )


def test_unknown_payment_never_signs():
    with patch(
        "app.governed_x402_service.execute_x402_payment",
        new_callable=AsyncMock,
    ) as signer:
        with pytest.raises(ValueError, match="Payment not found"):
            run_payment("nonexistent-payment-key")

        signer.assert_not_awaited()


@pytest.mark.parametrize(
    "status",
    ["DENIED", "REVIEW_REQUIRED", "PENDING_RECONCILIATION", "PAID"],
)
def test_non_ready_payment_never_signs(status):
    with (
        patch(
            "app.governed_x402_service.payment_store.get_payment",
            return_value={"status": status, "fingerprint": {}},
        ),
        patch(
            "app.governed_x402_service.inspect_x402_payment",
            new_callable=AsyncMock,
        ) as inspector,
        patch(
            "app.governed_x402_service.execute_x402_payment",
            new_callable=AsyncMock,
        ) as signer,
    ):
        result = run_payment("existing-payment")

        assert result.status == status
        inspector.assert_not_awaited()
        signer.assert_not_awaited()


def test_ready_payment_requires_atomic_claim():
    payment = {
        "status": "READY",
        "fingerprint": {
            "vendor": "spendpilot-demo",
            "amount_usd": "1.00",
        },
    }

    with (
        patch(
            "app.governed_x402_service.payment_store.get_payment",
            return_value=payment,
        ),
        patch(
            "app.governed_x402_service.inspect_x402_payment",
            new_callable=AsyncMock,
        ) as inspector,
        patch(
            "app.governed_x402_service.payment_store.claim_payment_execution",
            return_value=False,
        ),
        patch(
            "app.governed_x402_service.execute_x402_payment",
            new_callable=AsyncMock,
        ) as signer,
    ):
        result = run_payment("already-claimed")

        assert result.status == "PENDING_RECONCILIATION"
        inspector.assert_awaited_once()
        signer.assert_not_awaited()


def test_invalid_challenge_never_claims_or_signs():
    payment = {
        "status": "READY",
        "fingerprint": {
            "vendor": "spendpilot-demo",
            "amount_usd": "1.00",
        },
    }

    with (
        patch(
            "app.governed_x402_service.payment_store.get_payment",
            return_value=payment,
        ),
        patch(
            "app.governed_x402_service.inspect_x402_payment",
            new_callable=AsyncMock,
            side_effect=ValueError("Untrusted recipient"),
        ),
        patch(
            "app.governed_x402_service.payment_store.claim_payment_execution",
        ) as claim,
        patch(
            "app.governed_x402_service.execute_x402_payment",
            new_callable=AsyncMock,
        ) as signer,
    ):
        with pytest.raises(ValueError, match="Untrusted recipient"):
            run_payment("invalid-challenge")

        claim.assert_not_called()
        signer.assert_not_awaited()


def test_invalid_resource_url_never_signs():
    with patch(
        "app.governed_x402_service.execute_x402_payment",
        new_callable=AsyncMock,
    ) as signer:
        with pytest.raises(ValueError):
            asyncio.run(
                execute_governed_x402(
                    idempotency_key="any-key",
                    resource_url="https://example.com/paid",
                )
            )

        signer.assert_not_awaited()
