
import base64
import json


class SettlementVerificationError(Exception):
    pass


def decode_payment_response(header: str) -> dict:
    """
    Decode an x402 PAYMENT-RESPONSE header.

    Decoding is not proof of on-chain settlement.
    """

    if not header:
        raise SettlementVerificationError(
            "Missing PAYMENT-RESPONSE header"
        )

    try:
        padded = header + "=" * (-len(header) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        data = json.loads(decoded)
    except (ValueError, UnicodeDecodeError) as error:
        raise SettlementVerificationError(
            "Invalid payment response encoding"
        ) from error

    if not isinstance(data, dict):
        raise SettlementVerificationError(
            "Payment response must be a JSON object"
        )

    if data.get("success") is not True:
        raise SettlementVerificationError(
            "Payment response does not indicate success"
        )

    transaction = data.get("transaction")
    network = data.get("network")

    if not isinstance(transaction, str) or not transaction:
        raise SettlementVerificationError(
            "Missing settlement transaction"
        )

    if network != "eip155:84532":
        raise SettlementVerificationError(
            "Unexpected settlement network"
        )

    return data
