
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from app.payment_routes import router as payment_router
from app.payment_store import initialize_database
from app.persistent_budget_service import initialize_budget_database

from x402.http import (
    HTTPFacilitatorClient,
    FacilitatorConfig,
    PaymentOption,
)
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

load_dotenv()

app = FastAPI(title="SpendPilot x402 API")

initialize_database()
initialize_budget_database()

for route in payment_router.routes:
    app.router.routes.append(route)

NETWORK = "eip155:84532"
PAY_TO = os.getenv("EVM_ADDRESS")
FACILITATOR_URL = os.getenv(
    "FACILITATOR_URL",
    "https://x402.org/facilitator",
)

if not PAY_TO:
    raise ValueError("EVM_ADDRESS is missing from .env")

facilitator = HTTPFacilitatorClient(
    FacilitatorConfig(url=FACILITATOR_URL)
)

payment_server = x402ResourceServer(facilitator)

payment_server.register(
    NETWORK,
    ExactEvmServerScheme(),
)

routes = {
    "GET /paid-api": RouteConfig(
        accepts=[
            PaymentOption(
                scheme="exact",
                price="$0.01",
                network=NETWORK,
                pay_to=PAY_TO,
            )
        ],
        description="SpendPilot paid API demo",
        mime_type="application/json",
    )
}

app.add_middleware(
    PaymentMiddlewareASGI,
    routes=routes,
    server=payment_server,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Provide a readiness check for local development."""
    return {"status": "ok"}


@app.get("/paid-api")
async def paid_api():
    return {
        "status": "success",
        "service": "SpendPilot",
        "result": "Paid API access granted",
    }
