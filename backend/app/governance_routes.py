from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/governance", tags=["Governance"])

# Demo policy thresholds. These can later be stored per task/user.
AUTO_APPROVAL_LIMIT = Decimal("25.00")
MAX_PURCHASE_LIMIT = Decimal("500.00")

BLOCKED_TERMS = {
    "gift card",
    "gambling",
    "cryptocurrency",
    "weapon",
}


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
    objective = payload.objective.lower()

    if any(term in objective for term in BLOCKED_TERMS):
        status = "DENIED"
        reason = "Purchase category is prohibited"

    elif payload.budget_usd > MAX_PURCHASE_LIMIT:
        status = "DENIED"
        reason = "Purchase exceeds maximum allowed budget"

    elif payload.budget_usd > AUTO_APPROVAL_LIMIT:
        status = "REVIEW_REQUIRED"
        reason = "Human approval required for this spending amount"

    else:
        status = "APPROVED"
        reason = "Purchase proposal passed preliminary policy review"

    return GovernanceReviewResponse(
        status=status,
        reason=reason,
        proposed_budget_usd=payload.budget_usd,
        requires_human_approval=(status == "REVIEW_REQUIRED"),
        # Preliminary approval is NOT permission to execute payment.
        payment_authorized=False,
    )
