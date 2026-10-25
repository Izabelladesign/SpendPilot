"""Local Base Sepolia x402 merchant for SpendPilot integration testing."""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

PAY_TO = os.getenv("EVM_ADDRESS")
NETWORK = "eip155:84532"

if not PAY_TO:
    raise RuntimeError("EVM_ADDRESS must identify the trusted merchant recipient")

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

app = FastAPI(title="SpendPilot x402 Demo Merchant")

facilitator_url = os.getenv(
    "FACILITATOR_URL",
    "https://x402.org/facilitator",
)
facilitator = HTTPFacilitatorClient(
    FacilitatorConfig(url=facilitator_url)
)
payment_server = x402ResourceServer(facilitator)
payment_server.register(NETWORK, ExactEvmServerScheme())

app.add_middleware(
    PaymentMiddlewareASGI,
    routes={
        "GET /paid-resource": RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact",
                    price="$0.01",
                    network=NETWORK,
                    pay_to=PAY_TO,
                )
            ],
            description="SpendPilot Base Sepolia integration test",
            mime_type="application/json",
        )
    },
    server=payment_server,
)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/paid-resource")
async def paid_resource():
    return {
        "status": "success",
        "service": "SpendPilot demo merchant",
        "result": "Payment accepted",
    }
