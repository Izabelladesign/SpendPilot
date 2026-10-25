
"""Shared REST endpoints for tasks, events, budgets, payments, and approvals."""

from __future__ import annotations

import hmac
import os
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
    Provider,
    PurchaseRequest,
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
    ExecutionSummaryResponse,
    JiraSpendRequestSync,
    JiraSpendRequestSyncResponse,
    PaymentListResponse,
    PaymentResponse,
    PurchaseRequestStatusResponse,
    ResearchBriefVerificationRequest,
    TaskListResponse,
    TaskResponse,
)
from app.services.local_demo import (
    build_local_demo,
    is_local_demo_task,
    verify_local_demo,
)
from app.services.research_brief_verifier import verify_research_brief

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


def _create_task_record(
    payload: CreateTaskRequest | JiraSpendRequestSync,
    request: Request,
    db: Session,
    *,
    event_type: str = "TASK_CREATED",
    event_message: str = "Task received",
    event_metadata: dict[str, object] | None = None,
) -> Task:
    """Create the shared task record used by direct and Jira intake."""

    user_id = getattr(payload, "user_id", None)
    budget_id = getattr(payload, "budget_id", None)
    user = db.get(User, user_id) if user_id else _demo_user(db)

    if user is None:
        raise _error("not_found", "User was not found.", request, 404)

    budget = db.get(Budget, budget_id) if budget_id else None

    if budget_id and budget is None:
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
            event_type=event_type,
            message=event_message,
            metadata_json=event_metadata or {},
        )
    )
    return task


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


def _purchase_request_status_response(
    purchase: PurchaseRequest,
) -> PurchaseRequestStatusResponse:
    return PurchaseRequestStatusResponse(
        id=purchase.id,
        taskId=purchase.task_id,
        providerId=purchase.provider_id,
        amount=purchase.amount,
        currency=purchase.currency,
        decision=purchase.decision,
        decisionReason=purchase.decision_reason,
        approvalId=purchase.approval.id if purchase.approval else None,
        createdAt=purchase.created_at,
        updatedAt=purchase.updated_at,
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
    task = _create_task_record(payload, request, db)

    db.commit()
    db.refresh(task)

    return _task_response(task)


@router.post(
    "/integrations/jira/spend-requests",
    response_model=JiraSpendRequestSyncResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Link a Jira spend request to a backend task",
    description=(
        "Creates or returns a local task record linked to an existing Jira review issue. "
        "This endpoint never approves, purchases, reserves real funds, or charges money."
    ),
)
def sync_jira_spend_request(
    payload: JiraSpendRequestSync,
    request: Request,
    db: Session = Depends(get_db),
) -> JiraSpendRequestSyncResponse:
    """Bridge the Forge-created Jira issue into the shared task timeline."""

    expected_token = os.getenv("SPENDPILOT_JIRA_SYNC_TOKEN")
    supplied_token = request.headers.get("x-spendpilot-sync-token", "")
    if expected_token and not hmac.compare_digest(supplied_token, expected_token):
        raise _error("unauthorized", "The Jira sync token is invalid.", request, 401)

    linked_event = (
        db.query(AgentEvent)
        .filter(AgentEvent.event_type == "JIRA_REQUEST_LINKED")
        .all()
    )
    for event in linked_event:
        if event.metadata_json.get("jiraIssueKey") == payload.jira_issue_key:
            task = db.get(Task, event.task_id)
            if task is not None:
                return JiraSpendRequestSyncResponse(
                    status="already_linked",
                    jiraIssueKey=payload.jira_issue_key,
                    task=_task_response(task),
                    message=f"Jira issue {payload.jira_issue_key} is already linked to this task.",
                )

    task = _create_task_record(
        payload,
        request,
        db,
        event_metadata={
            "source": "forge_jira",
            "jiraIssueKey": payload.jira_issue_key,
        },
    )
    task.output = {
        "source": "forge_jira",
        "jiraIssueKey": payload.jira_issue_key,
        "approvalRequired": True,
        "purchaseAuthorized": False,
    }
    db.add(
        AgentEvent(
            task_id=task.id,
            event_type="JIRA_REQUEST_LINKED",
            message=f"Linked Jira review issue {payload.jira_issue_key} to the task",
            metadata_json={
                "jiraIssueKey": payload.jira_issue_key,
                "source": "forge_jira",
            },
        )
    )
    db.commit()
    db.refresh(task)

    return JiraSpendRequestSyncResponse(
        status="linked",
        jiraIssueKey=payload.jira_issue_key,
        task=_task_response(task),
        message=(
            f"Jira issue {payload.jira_issue_key} is linked to backend task {task.id}. "
            "Approval and purchase remain separate."
        ),
    )


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
    return TaskListResponse(
        items=[
            _task_response(task)
            for task in tasks
            if task.budget is not None and task.budget.total > 0
        ]
    )


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


@router.get(
    "/tasks/{task_id}/execution",
    response_model=ExecutionSummaryResponse,
    summary="Read the task execution summary",
)
def get_task_execution_summary(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> ExecutionSummaryResponse:
    """Join governance, payment, and event state for dashboard readers.

    This endpoint is deliberately read-only. It reports payment state alongside
    the task state without treating a settled payment as a successful task.
    """

    task = _find_task(task_id, db, request)
    purchase_requests = (
        db.query(PurchaseRequest)
        .filter(PurchaseRequest.task_id == task.id)
        .order_by(PurchaseRequest.created_at.asc())
        .all()
    )
    payments = (
        db.query(Payment)
        .filter(Payment.task_id == task.id)
        .order_by(Payment.created_at.asc())
        .all()
    )
    approvals = (
        db.query(Approval)
        .filter(Approval.task_id == task.id)
        .order_by(Approval.created_at.asc())
        .all()
    )
    events = (
        db.query(AgentEvent)
        .filter(AgentEvent.task_id == task.id)
        .order_by(AgentEvent.created_at.asc())
        .all()
    )

    return ExecutionSummaryResponse(
        taskId=task.id,
        taskStatus=task.status,
        purchaseRequests=[
            _purchase_request_status_response(purchase)
            for purchase in purchase_requests
        ],
        payments=[_payment_response(payment) for payment in payments],
        approvals=[_approval_response(approval) for approval in approvals],
        events=[_event_response(event) for event in events],
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


@router.post(
    "/tasks/{task_id}/verify",
    response_model=TaskResponse,
    summary="Verify a returned research brief",
    description=(
        "Local demo endpoint: runs the server-owned research brief verifier "
        "and records the result. It does not call a provider or execute payment."
    ),
)
def verify_task_output(
    task_id: str,
    payload: ResearchBriefVerificationRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskResponse:
    """Persist a service response and complete the task only after verification."""

    task = _find_task(task_id, db, request)

    if task.status in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value}:
        raise _error(
            "invalid_state_transition",
            "A terminal task cannot be verified again.",
            request,
            409,
        )

    task.status = TaskStatus.VERIFYING.value
    task.output = {
        "researchBrief": payload.model_dump(by_alias=True),
    }
    db.add(
        AgentEvent(
            task_id=task.id,
            event_type="OUTPUT_RECEIVED",
            message="Research service response received; verification started",
            metadata_json={"sourceCount": len(payload.source_urls)},
        )
    )

    verification = verify_research_brief(
        summary=payload.summary,
        copilot_section=payload.copilot_section,
        cursor_section=payload.cursor_section,
        pricing_section=payload.pricing_section,
        security_section=payload.security_section,
        source_urls=payload.source_urls,
        unverified_information=payload.unverified_information,
    )
    task.output["verification"] = {
        "status": verification.status.value,
        "message": verification.message,
        "checks": verification.checks,
    }

    if verification.verified:
        task.status = TaskStatus.COMPLETED.value
        task.failure_reason = None
        event_type = "OUTPUT_VERIFIED"
        event_message = "Research brief verified; task completed"
    else:
        task.status = TaskStatus.FAILED.value
        task.failure_reason = verification.message
        event_type = "VERIFICATION_FAILED"
        event_message = "Research brief failed verification; task not completed"

    db.add(
        AgentEvent(
            task_id=task.id,
            event_type=event_type,
            message=event_message,
            metadata_json={
                "verificationStatus": verification.status.value,
                "checks": verification.checks,
            },
        )
    )
    db.commit()
    db.refresh(task)

    return _task_response(task)


@router.post(
    "/tasks/{task_id}/demo-run",
    response_model=TaskResponse,
    summary="Run the safe local enterprise demo",
    description=(
        "Runs the deterministic Copilot-versus-Cursor enterprise demo. It records "
        "research candidates, a recommendation, governance state, a purchase "
        "preview, license findings, and verification without calling a provider "
        "or moving money."
    ),
)
def run_local_demo(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskResponse:
    """Persist one idempotent, no-money end-to-end demo run."""

    task = _find_task(task_id, db, request)
    existing_run = next(
        (
            event
            for event in task.events
            if event.event_type == "DEMO_RUN_STARTED"
        ),
        None,
    )
    if existing_run:
        return _task_response(task)

    if task.status in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value}:
        raise _error(
            "invalid_state_transition",
            "A terminal task cannot start a local demo run.",
            request,
            409,
        )

    if not is_local_demo_task(task):
        raise _error(
            "unsupported_demo_scenario",
            (
                "The safe local demo is configured for the default GitHub Copilot "
                "versus Cursor scenario."
            ),
            request,
            409,
        )

    output, brief = build_local_demo(task)
    demo_run = output["demoRun"]
    governance = demo_run["governance"]
    recommendation = demo_run["recommendation"]

    task.status = TaskStatus.RESEARCHING.value
    db.add(
        AgentEvent(
            task_id=task.id,
            event_type="DEMO_RUN_STARTED",
            message="Local agent run started; no external services are enabled",
            metadata_json={"mode": "LOCAL_SIMULATION"},
        )
    )
    db.add(
        AgentEvent(
            task_id=task.id,
            event_type="RESEARCH_COMPLETED",
            message="Compared GitHub Copilot and Cursor",
            metadata_json={
                "candidateCount": len(demo_run["candidates"]),
                "candidates": [candidate["name"] for candidate in demo_run["candidates"]],
                "evidenceStatus": recommendation["evidenceStatus"],
            },
        )
    )
    db.add(
        AgentEvent(
            task_id=task.id,
            event_type="RECOMMENDATION_CREATED",
            message="Recommended GitHub Copilot over Cursor",
            metadata_json={
                "selectedProduct": recommendation["selectedProduct"],
                "alternativeProduct": recommendation["alternativeProduct"],
                "rationale": recommendation["rationale"],
            },
        )
    )
    db.add(
        AgentEvent(
            task_id=task.id,
            event_type="POLICY_DECISION",
            message="Recommendation is gated for human approval",
            metadata_json={
                "decision": governance["status"],
                "budgetCap": governance["budgetCap"],
                "paymentAuthorized": governance["paymentAuthorized"],
            },
        )
    )
    db.add(
        AgentEvent(
            task_id=task.id,
            event_type="PURCHASE_PREVIEWED",
            message="Prepared a governed purchase preview; no funds moved",
            metadata_json={
                "executed": False,
                "fundsMoved": False,
                "providerCalled": False,
            },
        )
    )

    task.status = TaskStatus.VERIFYING.value
    task.output = output
    db.add(
        AgentEvent(
            task_id=task.id,
            event_type="OUTPUT_RECEIVED",
            message="Local research result received; verification started",
            metadata_json={"sourceCount": len(brief["sourceUrls"])},
        )
    )
    verification = verify_local_demo(brief)
    task.output["verification"] = verification

    if verification["status"] == "VERIFIED":
        task.status = TaskStatus.COMPLETED.value
        task.failure_reason = None
        db.add(
            AgentEvent(
                task_id=task.id,
                event_type="OUTPUT_VERIFIED",
                message="Local agent run verified; task completed",
                metadata_json={
                    "verificationStatus": verification["status"],
                    "checks": verification["checks"],
                },
            )
        )
    else:
        task.status = TaskStatus.FAILED.value
        task.failure_reason = verification["message"]
        db.add(
            AgentEvent(
                task_id=task.id,
                event_type="VERIFICATION_FAILED",
                message="Local agent run failed verification",
                metadata_json={
                    "verificationStatus": verification["status"],
                    "checks": verification["checks"],
                },
            )
        )

    db.commit()
    db.refresh(task)
    return _task_response(task)


@router.post(
    "/tasks/{task_id}/demo-purchase-preview",
    response_model=TaskResponse,
    summary="Create the local demo decision packet",
    description=(
        "Creates a persisted, human-reviewable purchase request and approval "
        "record for the local demo. It does not call a provider, reserve real "
        "funds, execute x402, or move money."
    ),
)
def create_demo_purchase_preview(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskResponse:
    """Persist the approval boundary shown by the company-facing demo.

    The local demo used to stop at a JSON purchase preview. This endpoint makes
    the next product boundary visible in the shared records: a recommendation
    becomes a purchase request that still needs a human approval. The provider
    record is explicitly marked as local simulation so this route cannot be
    mistaken for a live merchant or Coinbase payment.
    """

    task = _find_task(task_id, db, request)
    if not is_local_demo_task(task) or not task.output or "demoRun" not in task.output:
        raise _error(
            "invalid_state_transition",
            "Run the safe local demo before creating its approval packet.",
            request,
            409,
        )

    idempotency_key = f"local-demo-purchase-{task.id}"
    existing = (
        db.query(PurchaseRequest)
        .filter_by(task_id=task.id, idempotency_key=idempotency_key)
        .one_or_none()
    )
    if existing:
        return _task_response(task)

    provider_name = "GitHub Copilot (local demo)"
    provider = db.query(Provider).filter_by(name=provider_name).one_or_none()
    if provider is None:
        provider = Provider(
            name=provider_name,
            service_description=(
                "Deterministic SpendPilot demo provider; no vendor account is accessed."
            ),
            is_approved=True,
            metadata_json={
                "mode": "LOCAL_SIMULATION",
                "product": "GitHub Copilot",
                "paymentEnabled": False,
            },
        )
        db.add(provider)
        db.flush()

    amount = task.budget.total if task.budget else Decimal("0")
    if amount <= 0:
        raise _error(
            "invalid_budget",
            "The local demo needs a positive task budget for its illustrative request.",
            request,
            422,
        )

    reason = (
        "The agent recommendation is ready, but a human must approve the "
        "illustrative purchase before any real provider or payment connector could run."
    )
    purchase = PurchaseRequest(
        task_id=task.id,
        provider_id=provider.id,
        idempotency_key=idempotency_key,
        amount=amount,
        currency=task.budget.currency if task.budget else "USD",
        decision="REVIEW_REQUIRED",
        decision_reason=reason,
    )
    db.add(purchase)
    db.flush()

    approval = Approval(
        task_id=task.id,
        purchase_request_id=purchase.id,
        amount=purchase.amount,
        currency=purchase.currency,
        vendor="GitHub Copilot",
        status="PENDING",
        reason=reason,
    )
    db.add(approval)

    demo_run = dict(task.output["demoRun"])
    purchase_preview = dict(demo_run.get("purchase", {}))
    purchase_preview.update(
        {
            "state": "AWAITING_HUMAN_APPROVAL",
            "executed": False,
            "fundsMoved": False,
            "providerCalled": False,
            "purchaseRequestId": purchase.id,
            "approvalId": approval.id,
            "nextStep": "A reviewer must approve this request before payment can be considered.",
        }
    )
    demo_run["purchase"] = purchase_preview
    output = dict(task.output)
    output["demoRun"] = demo_run
    output["decisionPacket"] = {
        "mode": "LOCAL_SIMULATION",
        "selectedProduct": "GitHub Copilot",
        "providerId": provider.id,
        "purchaseRequestId": purchase.id,
        "approvalId": approval.id,
        "approvalStatus": approval.status,
        "paymentStatus": "NOT_AUTHORIZED",
        "fundsMoved": False,
        "message": "Decision packet created for review; no payment was attempted.",
    }
    task.output = output
    task.selected_provider_id = provider.id

    db.add(
        AgentEvent(
            task_id=task.id,
            event_type="PURCHASE_REQUEST_CREATED",
            message="Created a local decision packet and routed it for human approval",
            metadata_json={
                "mode": "LOCAL_SIMULATION",
                "purchaseRequestId": purchase.id,
                "approvalId": approval.id,
                "paymentAuthorized": False,
                "fundsMoved": False,
            },
        )
    )
    db.commit()
    db.refresh(task)
    return _task_response(task)


def _latest_local_demo_purchase(task: Task, db: Session, request: Request) -> PurchaseRequest:
    purchase = (
        db.query(PurchaseRequest)
        .filter_by(task_id=task.id, idempotency_key=f"local-demo-purchase-{task.id}")
        .one_or_none()
    )
    if purchase is None:
        raise _error(
            "invalid_state_transition",
            "Create the local demo approval packet before continuing.",
            request,
            409,
        )
    return purchase


@router.post(
    "/tasks/{task_id}/demo-approve",
    response_model=TaskResponse,
    summary="Approve the local demo request",
    description=(
        "Approves the local demo decision packet for presentation purposes only. "
        "It does not authorize a real payment, access a wallet, or call Coinbase."
    ),
)
def approve_demo_purchase(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskResponse:
    """Show the human approval gate without requiring reviewer credentials."""

    task = _find_task(task_id, db, request)
    purchase = _latest_local_demo_purchase(task, db, request)
    approval = purchase.approval
    if approval is None:
        raise _error("invalid_approval", "The demo purchase has no approval record.", request, 409)
    if approval.status == "APPROVED":
        return _task_response(task)
    if approval.status != "PENDING":
        raise _error(
            "duplicate_request",
            "The local demo approval has already been decided.",
            request,
            409,
        )

    reviewer = db.query(User).filter_by(email="reviewer@spendpilot.local").one_or_none()
    if reviewer is None:
        reviewer = User(
            email="reviewer@spendpilot.local",
            display_name="SpendPilot Demo Reviewer",
        )
        db.add(reviewer)
        db.flush()

    approval.status = "APPROVED"
    approval.decided_by = reviewer.id
    approval.decided_at = datetime.now(timezone.utc)
    purchase.decision = "APPROVED"
    task.output = dict(task.output or {})
    packet = dict(task.output.get("decisionPacket", {}))
    packet["approvalStatus"] = "APPROVED"
    packet["paymentStatus"] = "NOT_AUTHORIZED"
    packet["message"] = (
        "Human approval recorded in local simulation; payment is still not authorized."
    )
    task.output["decisionPacket"] = packet

    db.add(
        AgentEvent(
            task_id=task.id,
            event_type="APPROVAL_DECIDED",
            message="Demo reviewer approved the decision packet; payment remains simulated",
            metadata_json={
                "approvalId": approval.id,
                "decision": "APPROVED",
                "mode": "LOCAL_SIMULATION",
                "paymentAuthorized": False,
            },
        )
    )
    db.commit()
    db.refresh(task)
    return _task_response(task)


@router.post(
    "/tasks/{task_id}/demo-payment",
    response_model=TaskResponse,
    summary="Simulate the local Coinbase payment step",
    description=(
        "Records a clearly labeled local payment simulation after demo approval. "
        "It does not sign a transaction, call x402, contact Coinbase, reserve "
        "funds, or move money."
    ),
)
def simulate_demo_payment(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskResponse:
    """Complete the visible payment stage without creating a blockchain payment."""

    task = _find_task(task_id, db, request)
    purchase = _latest_local_demo_purchase(task, db, request)
    approval = purchase.approval
    if approval is None or approval.status != "APPROVED":
        raise _error(
            "approval_required",
            "The local demo request must be approved before payment simulation.",
            request,
            409,
        )
    if purchase.payment is not None:
        return _task_response(task)

    payment = Payment(
        task_id=task.id,
        purchase_request_id=purchase.id,
        provider_id=purchase.provider_id,
        amount=purchase.amount,
        currency=purchase.currency,
        status="SIMULATED",
        transaction_reference=f"demo-only:{task.id}",
    )
    db.add(payment)
    task.output = dict(task.output or {})
    packet = dict(task.output.get("decisionPacket", {}))
    packet["approvalStatus"] = approval.status
    packet["paymentStatus"] = "SIMULATED_NO_FUNDS"
    packet["fundsMoved"] = False
    packet["transactionReference"] = payment.transaction_reference
    packet["message"] = "Payment stage simulated for the demo; no chain transaction exists."
    task.output["decisionPacket"] = packet
    demo_run = dict(task.output.get("demoRun", {}))
    purchase_preview = dict(demo_run.get("purchase", {}))
    purchase_preview.update(
        {
            "state": "SIMULATED_NO_FUNDS",
            "executed": False,
            "fundsMoved": False,
            "providerCalled": False,
            "transactionReference": payment.transaction_reference,
            "nextStep": "Production would verify settlement and the delivered outcome here.",
        }
    )
    demo_run["purchase"] = purchase_preview
    task.output["demoRun"] = demo_run

    db.add(
        AgentEvent(
            task_id=task.id,
            event_type="PAYMENT_SIMULATED",
            message="Coinbase/x402 payment stage simulated; no funds moved",
            metadata_json={
                "mode": "LOCAL_SIMULATION",
                "paymentId": payment.id,
                "transactionReference": payment.transaction_reference,
                "fundsMoved": False,
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
