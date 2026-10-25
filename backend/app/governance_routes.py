
from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/governance", tags=["Governance"])


class GovernanceReviewRequest(BaseModel):
    objective: str = Field(min_length=1)
    budget_usd: Decimal = Field(gt=0, decimal_places=2)
    quantity: Decimal = Field(gt=0)
    constraints: list[str] = Field(default_factory=list)


class GovernanceReviewResponse(BaseModel):
    status: str
    reason: str
    proposed_budget_usd: Decimal
    requires_human_approval: bool
    payment_authorized: bool


@router.post("/review", response_model=GovernanceReviewResponse)
def review_request(payload: GovernanceReviewRequest):
    return GovernanceReviewResponse(
        status="REVIEW_REQUIRED",
        reason=(
            "Purchase request is valid for review. "
            "A human must authorize the spending policy "
            "before any payment can be prepared."
        ),
        proposed_budget_usd=payload.budget_usd,
        requires_human_approval=True,
        payment_authorized=False,
    )
