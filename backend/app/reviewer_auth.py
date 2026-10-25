
"""Demo-only reviewer authentication. Not for production use."""

import os
import secrets

from fastapi import Header, HTTPException, status

DEMO_REVIEWER_EMAIL = "reviewer@spendpilot.local"


def require_reviewer(
    authorization: str | None = Header(default=None),
) -> str:
    expected_token = os.getenv("SPENDPILOT_REVIEWER_TOKEN")

    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reviewer authentication is not configured",
        )

    scheme, separator, supplied_token = (
        authorization or ""
    ).partition(" ")

    if (
        not separator
        or scheme.lower() != "bearer"
        or not secrets.compare_digest(supplied_token, expected_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid reviewer credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return DEMO_REVIEWER_EMAIL

