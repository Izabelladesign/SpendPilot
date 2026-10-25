"""Bridge AI recommendations to persisted purchase governance."""

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Provider, Task
from app.payment_auth import require_payment_operator
from app.purchase_request_routes import (
    CreatePurchaseRequest,
    create_purchase_request,
)

router = APIRouter(prefix="/api/agent", tags=["Agent Governance"])


class AgentPurchaseRequest(BaseModel):
    task_id: str
    provider_name: str = Field(min_length=1)
    estimated_cost: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(pattern="^USD$")
    constraints_satisfied: bool
    idempotency_key: str = Field(min_length=1)


@router.post("/request-purchase")
def request_agent_purchase(
    payload: AgentPurchaseRequest,
    operator: str = Depends(require_payment_operator),
    db: Session = Depends(get_db),
):
    if not payload.constraints_satisfied:
        raise HTTPException(409, "Recommendation does not satisfy constraints")

    task = db.get(Task, payload.task_id)
    if task is None:
        raise HTTPException(404, "Task not found")

    provider = (
        db.query(Provider)
        .filter(Provider.name == payload.provider_name, Provider.is_approved.is_(True))
        .one_or_none()
    )
    if provider is None:
        raise HTTPException(404, "Approved provider not found")

    result = create_purchase_request(
        CreatePurchaseRequest(
            task_id=task.id,
            provider_id=provider.id,
            amount=payload.estimated_cost,
            currency=payload.currency,
            idempotency_key=payload.idempotency_key,
        ),
        operator=operator,
        db=db,
    )

    return result
