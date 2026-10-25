import base64
import json
import re

TX_HASH_PATTERN = re.compile(r"^0x[a-fA-F0-9]{64}$")


def extract_transaction_hash(payment_response: str) -> str:
    """Extract a transaction hash from an x402 settlement response."""
    if not payment_response:
        raise ValueError("Missing PAYMENT-RESPONSE header")

    try:
        decoded = base64.urlsafe_b64decode(
            payment_response + "=" * (-len(payment_response) % 4)
        )
        payload = json.loads(decoded)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid x402 settlement response") from exc

    if not isinstance(payload, dict):
        raise ValueError("Invalid settlement payload")

    if payload.get("success") is not True:
        raise ValueError("x402 settlement was not successful")

    tx_hash = payload.get("transaction")

    if not isinstance(tx_hash, str) or not TX_HASH_PATTERN.fullmatch(tx_hash):
        raise ValueError("Missing or invalid transaction hash")

    return tx_hash.lower()
