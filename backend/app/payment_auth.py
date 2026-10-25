
"""Demo-only authentication for payment preparation."""

import os
import secrets

from fastapi import Header, HTTPException, status


def require_payment_operator(
    authorization: str | None = Header(default=None),
) -> str:
    expected_token = os.getenv("SPENDPILOT_PAYMENT_TOKEN")

    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment authentication is not configured",
        )

    scheme, separator, supplied_token = (
        authorization or ""
    ).partition(" ")

    if (
        not separator
        or scheme.lower() != "bearer"
        or not secrets.compare_digest(
            supplied_token,
            expected_token,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid payment credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return "demo-payment-operator"
