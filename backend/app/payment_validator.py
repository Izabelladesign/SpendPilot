
import base64
import json
from decimal import Decimal

from app.vendor_verifier import verify_vendor


class PaymentValidationError(Exception):
    pass


def validate_payment_challenge(
    payment_required_header: str,
    vendor_name: str,
    approved_amount_usd: Decimal,
) -> dict:
    """Validate x402 requirements before allowing payment."""

    if not payment_required_header:
        raise PaymentValidationError(
            "Missing PAYMENT-REQUIRED header"
        )

    try:
        decoded = base64.urlsafe_b64decode(
            payment_required_header
            + "=" * (-len(payment_required_header) % 4)
        )
        challenge = json.loads(decoded)
    except (ValueError, UnicodeDecodeError) as error:
        raise PaymentValidationError(
            "Invalid x402 payment challenge"
        ) from error

    if challenge.get("x402Version") != 2:
        raise PaymentValidationError(
            "Unsupported x402 version"
        )

    accepts = challenge.get("accepts", [])

    if len(accepts) != 1:
        raise PaymentValidationError(
            "Expected exactly one payment option"
        )

    payment = accepts[0]

    if payment.get("scheme") != "exact":
        raise PaymentValidationError(
            "Unsupported payment scheme"
        )

    if not verify_vendor(
        vendor_name,
        payment.get("payTo", ""),
        payment.get("network", ""),
        payment.get("asset", ""),
    ):
        raise PaymentValidationError(
            "Untrusted payment destination or asset"
        )

    try:
        amount_units = int(payment["amount"])
    except (KeyError, TypeError, ValueError) as error:
        raise PaymentValidationError(
            "Invalid payment amount"
        ) from error

    if amount_units <= 0 or str(amount_units) != str(payment["amount"]):
        raise PaymentValidationError(
            "Invalid payment amount format"
        )

    actual_amount = Decimal(amount_units) / Decimal(1_000_000)

    if actual_amount != approved_amount_usd:
        raise PaymentValidationError(
            f"Amount mismatch: expected {approved_amount_usd}, "
            f"received {actual_amount}"
        )

    return payment
