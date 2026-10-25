"""SpendPilot FastAPI application entry point.

The shared task API and the Coinbase/x402 payment API are mounted together,
but payment execution remains owned by the payment services.
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import router
from app.governance_routes import router as governance_router
from app.payment_routes import router as payment_router
from app.payment_store import initialize_database
from app.persistent_budget_service import initialize_budget_database
from app.purchase_request_routes import router as purchase_request_router
from app.task_routes import router as task_router

load_dotenv()

app = FastAPI(title="SpendPilot API", version="0.1.0")

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

initialize_database()
initialize_budget_database()
for route in governance_router.routes:
    app.router.routes.append(route)

# Developer 4 shared task, budget, event, and approval routes.
app.include_router(router)
app.include_router(purchase_request_router)

# Developer 2 payment/governance routes are namespaced under /api.
app.include_router(payment_router)

for route in task_router.routes:
    app.router.routes.append(route)

NETWORK = "eip155:84532"
PAY_TO = os.getenv("EVM_ADDRESS")
FACILITATOR_URL = os.getenv("FACILITATOR_URL", "https://x402.org/facilitator")

# Keep local task/API testing available without a wallet. The x402 middleware
# is enabled only when a recipient is explicitly configured. No wallet or
# payment credential is created by this module.
if PAY_TO:
    from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
    from x402.http.middleware.fastapi import PaymentMiddlewareASGI
    from x402.http.types import RouteConfig
    from x402.mechanisms.evm.exact import ExactEvmServerScheme
    from x402.server import x402ResourceServer

    facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
    payment_server = x402ResourceServer(facilitator)
    payment_server.register(NETWORK, ExactEvmServerScheme())
    payment_routes = {
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
    app.add_middleware(PaymentMiddlewareASGI, routes=payment_routes, server=payment_server)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Return contract-shaped errors for shared API exceptions."""

    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health")
async def health() -> dict[str, str]:
    """Provide a readiness check for local development."""

    return {"status": "ok"}


@app.get("/paid-api")
async def paid_api() -> dict[str, str]:
    """Return the demo resource only when x402 is configured."""

    if not PAY_TO:
        raise HTTPException(
            status_code=503,
            detail="Paid API is disabled until an explicit testnet recipient is configured.",
        )
    return {
        "status": "success",
        "service": "SpendPilot",
        "result": "Paid API access granted",
    }
