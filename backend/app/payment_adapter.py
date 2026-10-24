
import os
from dataclasses import dataclass
from decimal import Decimal

import httpx
from eth_account import Account

from app.x402_policy import create_x402_policy

from x402 import x402Client
from x402.http.clients import x402HttpxClient
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact import ExactEvmScheme

from app.payment_validator import validate_payment_challenge


NETWORK = "eip155:84532"


@dataclass
class PaymentResult:
    success: bool
    status_code: int
    response_body: str
    payment_response: str | None


async def inspect_x402_payment(
    resource_url: str,
    vendor_name: str,
    approved_amount_usd: Decimal,
) -> dict:
    """
    Fetch and validate x402 payment requirements.

    Checks the vendor, recipient, network, asset,
    and amount before payment.

    Does NOT execute or sign a payment.
    """

    async with httpx.AsyncClient(timeout=15.0) as http:
        response = await http.get(resource_url)

    if response.status_code != 402:
        raise ValueError(
            f"Expected HTTP 402, received {response.status_code}"
        )

    header = response.headers.get("PAYMENT-REQUIRED")

    payment = validate_payment_challenge(
        payment_required_header=header,
        vendor_name=vendor_name,
        approved_amount_usd=approved_amount_usd,
    )

    return {
        "vendor": vendor_name,
        "network": payment["network"],
        "recipient": payment["payTo"],
        "asset": payment["asset"],
        "amount": payment["amount"],
        "validated": True,
    }


async def execute_x402_payment(
    resource_url: str,
    vendor_name: str,
    approved_amount_usd: Decimal,
) -> PaymentResult:
    """
    Execute an x402 payment with SDK-level requirement filtering.

    WARNING:
    This is not yet connected to SpendPilot's budget,
    approval, or persistent idempotency controls.
    Do not call directly from an AI agent.
    """

    if not resource_url.startswith("http://127.0.0.1:8001/"):
        raise ValueError("Resource URL is not allowlisted")

    private_key = os.environ.get("PAYMENT_PRIVATE_KEY")

    if not private_key:
        raise ValueError("PAYMENT_PRIVATE_KEY is not configured")

    account = Account.from_key(private_key)
    signer = EthAccountSigner(account)

    client = x402Client()

    client.register(
        NETWORK,
        ExactEvmScheme(signer=signer),
    )

    client.register_policy(
        create_x402_policy(
            vendor_name=vendor_name,
            approved_amount_usd=approved_amount_usd,
        )
    )

    async with x402HttpxClient(client) as http:
        response = await http.get(resource_url)

        payment_response = response.headers.get(
            "PAYMENT-RESPONSE"
        )

        return PaymentResult(
            success=(
                response.status_code == 200
                and payment_response is not None
            ),
            status_code=response.status_code,
            response_body=response.text,
            payment_response=payment_response,
        )
