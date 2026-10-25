
"""Shared REST endpoints for tasks, events, budgets, payments, and approvals."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    AgentEvent,
    Approval,
    Budget,
    Payment,
    Task,
    TaskStatus,
    User,
)
from app.reviewer_auth import require_reviewer
from app.schemas import (
    AgentEventResponse,
    ApprovalDecisionRequest,
    ApprovalResponse,
    BudgetResponse,
    CreateTaskRequest,
    ErrorBody,
    ErrorResponse,
    EventListResponse,
    ExecuteTaskRequest,
    PaymentListResponse,
    PaymentResponse,
    TaskListResponse,
    TaskResponse,
)

router = APIRouter()


def _error(
    code: str,
    message: str,
    request: Request,
    status_code: int,
) -> HTTPException:
    request_id = request.headers.get("x-request-id", str(uuid4()))
    return HTTPException(
        status_code=status_code,
        detail=ErrorResponse(
            error=ErrorBody(
                code=code,
                message=message,
                request_id=request_id,
            )
        ).model_dump(by_alias=True),
    )


def _find_task(task_id: str, db: Session, request: Request) -> Task:
    task = db.get(Task, task_id)

    if task is None:
        raise _error("not_found", "Task was not found.", request, 404)

    return task


def _demo_user(db: Session) -> User:
    user = (
        db.query(User)
        .filter_by(email="demo@spendpilot.local")
        .one_or_none()
    )

    if user is None:
        user = User(
            email="demo@spendpilot.local",
            display_name="SpendPilot Demo",
        )
        db.add(user)
        db.flush()

    return user


def _task_response(task: Task) -> TaskResponse:
    budget = task.budget

    return TaskResponse(
        id=task.id,
        userId=task.user_id,
        budgetId=task.budget_id,
        objective=task.objective,
        budget={
            "amount": budget.total if budget else Decimal("0"),
            "currency": budget.currency if budget else "USD",
        },
        quantity=task.quantity,
        qualityTarget=task.quality_target,
        constraints=task.constraints,
        status=task.status,
        selectedProviderId=task.selected_provider_id,
        output=task.output,
        failureReason=task.failure_reason,
        createdAt=task.created_at,
        updatedAt=task.updated_at,
    )


def _event_response(event: AgentEvent) -> AgentEventResponse:
    return AgentEventResponse(
        id=event.id,
        taskId=event.task_id,
        type=event.event_type,
        message=event.message,
        metadata=event.metadata_json,
        createdAt=event.created_at,
    )


def _budget_response(budget: Budget) -> BudgetResponse:
    return BudgetResponse(
        id=budget.id,
        name=budget.name,
        currency=budget.currency,
        total=budget.total,
        spent=budget.spent,
        reserved=budget.reserved,
        available=budget.total - budget.spent - budget.reserved,
        createdAt=budget.created_at,
        updatedAt=budget.updated_at,
    )


def _payment_response(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        id=payment.id,
        taskId=payment.task_id,
        purchaseRequestId=payment.purchase_request_id,
        providerId=payment.provider_id,
        amount=payment.amount,
        currency=payment.currency,
        status=payment.status,
        transactionReference=payment.transaction_reference,
        createdAt=payment.created_at,
        updatedAt=payment.updated_at,
    )


def _approval_response(approval: Approval) -> ApprovalResponse:
    return ApprovalResponse(
        id=approval.id,
        taskId=approval.task_id,
        purchaseRequestId=approval.purchase_request_id,
        amount=approval.amount,
        currency=approval.currency,
        vendor=approval.vendor,
        status=approval.status,
        reason=approval.reason,
        decidedBy=approval.decided_by,
        decidedAt=approval.decided_at,
        createdAt=approval.created_at,
        updatedAt=approval.updated_at,
    )


@router.post(
    "/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a local task record",
    description=(
        "Creates a task and local budget record only. It does not charge a card, "
        "call a paid provider, reserve real funds, or make a purchase. Omit "
        "userId and budgetId for the local demo user and task budget."
    ),
)
def create_task(
    payload: CreateTaskRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskResponse:
    user = db.get(User, payload.user_id) if payload.user_id else _demo_user(db)

    if user is None:
        raise _error("not_found", "User was not found.", request, 404)

    budget = db.get(Budget, payload.budget_id) if payload.budget_id else None

    if payload.budget_id and budget is None:
        raise _error("not_found", "Budget was not found.", request, 404)

    if budget and budget.owner_id != user.id:
        raise _error(
            "forbidden",
            "The budget does not belong to the user.",
            request,
            403,
        )

    if budget and budget.currency != payload.budget.currency:
        raise _error(
            "validation_error",
            "Task and budget currencies must match.",
            request,
            422,
        )

    if budget is None:
        budget = Budget(
            owner_id=user.id,
            name=f"Task budget: {payload.objective[:150]}",
            currency=payload.budget.currency,
            total=payload.budget.amount,
        )
        db.add(budget)
        db.flush()

    task = Task(
        user_id=user.id,
        budget_id=budget.id,
        objective=payload.objective,
        quantity=payload.quantity,
        quality_target=payload.quality_target,
        constraints=payload.constraints,
    )

    db.add(task)
    db.flush()

    db.add(
        AgentEvent(
            task_id=task.id,
            event_type="TASK_CREATED",
            message="Task received",
            metadata_json={},
        )
    )

    db.commit()
    db.refresh(task)

    return _task_response(task)


@router.get("/tasks", response_model=TaskListResponse)
def list_tasks(
    request: Request,
    task_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> TaskListResponse:
    query = db.query(Task).order_by(Task.updated_at.desc())
    if task_status:
        query = query.filter(Task.status == task_status)
    tasks = query.limit(limit).all()
    return TaskListResponse(items=[_task_response(task) for task in tasks])


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskResponse:
    return _task_response(_find_task(task_id, db, request))


@router.get(
    "/tasks/{task_id}/events",
    response_model=EventListResponse,
)
def get_task_events(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> EventListResponse:
    task = _find_task(task_id, db, request)

    return EventListResponse(
        items=[_event_response(event) for event in task.events]
    )


@router.post(
    "/tasks/{task_id}/execute",
    response_model=TaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def execute_task(
    task_id: str,
    payload: ExecuteTaskRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskResponse:
    task = _find_task(task_id, db, request)

    duplicate = (
        db.query(AgentEvent)
        .filter(
            AgentEvent.task_id == task.id,
            AgentEvent.event_type == "EXECUTION_REQUESTED",
        )
        .all()
    )

    if any(
        event.metadata_json.get("idempotencyKey") == payload.idempotency_key
        for event in duplicate
    ):
        return _task_response(task)

    if task.status in {
        TaskStatus.COMPLETED.value,
        TaskStatus.FAILED.value,
    }:
        raise _error(
            "invalid_state_transition",
            "A terminal task cannot be executed again.",
            request,
            409,
        )

    task.status = TaskStatus.RESEARCHING.value

    db.add(
        AgentEvent(
            task_id=task.id,
            event_type="EXECUTION_REQUESTED",
            message="Execution handed to the agent workflow",
            metadata_json={
                "idempotencyKey": payload.idempotency_key,
            },
        )
    )

    db.commit()
    db.refresh(task)

    return _task_response(task)


@router.get(
    "/budgets/{budget_id}",
    response_model=BudgetResponse,
)
def get_budget(
    budget_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> BudgetResponse:
    budget = db.get(Budget, budget_id)

    if budget is None:
        raise _error("not_found", "Budget was not found.", request, 404)

    return _budget_response(budget)


@router.get(
    "/payments",
    response_model=PaymentListResponse,
)
def get_payments(
    request: Request,
    task_id: str | None = Query(default=None, alias="taskId"),
    payment_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaymentListResponse:
    query = db.query(Payment).order_by(Payment.created_at.desc())

    if task_id:
        query = query.filter(Payment.task_id == task_id)

    if payment_status:
        query = query.filter(Payment.status == payment_status)

    payments = query.limit(limit).all()

    return PaymentListResponse(
        items=[_payment_response(payment) for payment in payments]
    )


@router.post(
    "/approvals/{approval_id}/decision",
    response_model=ApprovalResponse,
)
def decide_approval(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    request: Request,
    reviewer_email: str = Depends(require_reviewer),
    db: Session = Depends(get_db),
) -> ApprovalResponse:

    # 1. Verify reviewer identity.
    reviewer = (
        db.query(User)
        .filter_by(email=reviewer_email)
        .one_or_none()
    )

    if reviewer is None:
        raise _error(
            "forbidden",
            "Reviewer account is not authorized.",
            request,
            403,
        )

    # 2. Verify the approval exists.
    approval = db.get(Approval, approval_id)

    if approval is None:
        raise _error(
            "not_found",
            "Approval was not found.",
            request,
            404,
        )

    # 3. Verify task and purchase request consistency.
    task = db.get(Task, approval.task_id)
    purchase = approval.purchase_request

    if task is None or purchase is None:
        raise _error(
            "invalid_approval",
            "Approval is missing its task or purchase request.",
            request,
            409,
        )

    if purchase.task_id != task.id:
        raise _error(
            "invalid_approval",
            "Approval and purchase request belong to different tasks.",
            request,
            409,
        )

    # 4. Prevent users from approving their own purchases.
    if task.user_id == reviewer.id:
        raise _error(
            "forbidden",
            "You cannot approve your own purchase.",
            request,
            403,
        )

    # 5. Atomically update approval.
    # Only one request can change PENDING to a final status.
    decision_time = datetime.now(timezone.utc)

    result = db.execute(
        update(Approval)
        .where(
            Approval.id == approval_id,
            Approval.status == "PENDING",
        )
        .values(
            status=payload.decision,
            decided_by=reviewer.id,
            decided_at=decision_time,
        )
        .execution_options(synchronize_session=False)
    )

    if result.rowcount != 1:
        db.rollback()
        raise _error(
            "duplicate_request",
            "This approval has already been decided.",
            request,
            409,
        )

    # 6. Record the decision in the audit trail.
    db.add(
        AgentEvent(
            task_id=approval.task_id,
            event_type="APPROVAL_DECIDED",
            message=f"Approval {payload.decision.lower()}",
            metadata_json={
                "approvalId": approval.id,
                "reviewerId": reviewer.id,
                "comment": payload.comment,
            },
        )
    )

    # 7. Commit and reload the approval.
    db.commit()
    db.expire(approval)
    db.refresh(approval)

    return _approval_response(approval)
