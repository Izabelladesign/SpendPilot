"""Pydantic request and response schemas for the shared API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class APIModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True, extra="forbid")


class Money(APIModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class CreateTaskRequest(APIModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        json_schema_extra={
            "example": {
                "objective": "Test a local document-processing task",
                "budget": {"amount": "1.00", "currency": "USD"},
                "quantity": 1,
                "qualityTarget": "Return a valid test result",
                "constraints": ["Local demo only"],
            }
        },
    )

    objective: str = Field(min_length=1, max_length=10_000)
    budget: Money
    quantity: Decimal | None = Field(default=None, gt=0)
    quality_target: str | None = Field(default=None, alias="qualityTarget", max_length=10_000)
    constraints: list[str] = Field(default_factory=list)
    user_id: str | None = Field(default=None, alias="userId")
    budget_id: str | None = Field(default=None, alias="budgetId")

    @field_validator("objective")
    @classmethod
    def objective_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Objective must not be blank.")
        return value.strip()


class TaskResponse(APIModel):
    id: str
    user_id: str = Field(alias="userId")
    budget_id: str | None = Field(alias="budgetId")
    objective: str
    budget: Money
    quantity: Decimal | None
    quality_target: str | None = Field(alias="qualityTarget")
    constraints: list[str]
    status: str
    selected_provider_id: str | None = Field(alias="selectedProviderId")
    output: dict[str, Any] | None
    failure_reason: str | None = Field(alias="failureReason")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class TaskListResponse(APIModel):
    items: list[TaskResponse]
    next_cursor: str | None = Field(default=None, alias="nextCursor")


class AgentEventResponse(APIModel):
    id: str
    task_id: str = Field(alias="taskId")
    type: str = Field(validation_alias="event_type", serialization_alias="type")
    message: str
    metadata: dict[str, Any] = Field(
        validation_alias="metadata_json",
        serialization_alias="metadata",
    )
    created_at: datetime = Field(alias="createdAt")


class EventListResponse(APIModel):
    items: list[AgentEventResponse]


class ExecuteTaskRequest(APIModel):
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=255)


class ResearchBriefVerificationRequest(APIModel):
    summary: str = Field(min_length=1, max_length=50_000)
    copilot_section: str = Field(alias="copilotSection", min_length=1, max_length=50_000)
    cursor_section: str = Field(alias="cursorSection", min_length=1, max_length=50_000)
    pricing_section: str = Field(alias="pricingSection", min_length=1, max_length=50_000)
    security_section: str = Field(alias="securitySection", min_length=1, max_length=50_000)
    source_urls: list[str] = Field(alias="sourceUrls", max_length=20)
    unverified_information: str = Field(
        alias="unverifiedInformation",
        min_length=1,
        max_length=50_000,
    )


class BudgetResponse(APIModel):
    id: str
    name: str
    currency: str
    total: Decimal
    spent: Decimal
    reserved: Decimal
    available: Decimal
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class PaymentResponse(APIModel):
    id: str
    task_id: str = Field(alias="taskId")
    purchase_request_id: str = Field(alias="purchaseRequestId")
    provider_id: str = Field(alias="providerId")
    amount: Decimal
    currency: str
    status: str
    transaction_reference: str | None = Field(alias="transactionReference")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class PurchaseRequestStatusResponse(APIModel):
    id: str
    task_id: str = Field(alias="taskId")
    provider_id: str = Field(alias="providerId")
    amount: Decimal
    currency: str
    decision: str
    decision_reason: str = Field(alias="decisionReason")
    approval_id: str | None = Field(alias="approvalId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class PaymentListResponse(APIModel):
    items: list[PaymentResponse]
    next_cursor: str | None = Field(default=None, alias="nextCursor")


class ApprovalDecisionRequest(APIModel):
    decision: str = Field(pattern=r"^(APPROVED|REJECTED)$")
    comment: str | None = Field(default=None, max_length=2_000)


class ApprovalResponse(APIModel):
    id: str
    task_id: str = Field(alias="taskId")
    purchase_request_id: str = Field(alias="purchaseRequestId")
    amount: Decimal
    currency: str
    vendor: str
    status: str
    reason: str
    decided_by: str | None = Field(alias="decidedBy")
    decided_at: datetime | None = Field(alias="decidedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class ExecutionSummaryResponse(APIModel):
    task_id: str = Field(alias="taskId")
    task_status: str = Field(alias="taskStatus")
    purchase_requests: list[PurchaseRequestStatusResponse] = Field(alias="purchaseRequests")
    payments: list[PaymentResponse]
    approvals: list[ApprovalResponse]
    events: list[AgentEventResponse]


class ErrorBody(APIModel):
    code: str
    message: str
    request_id: str = Field(alias="requestId")
    field_errors: list[dict[str, Any]] = Field(default_factory=list, alias="fieldErrors")


class ErrorResponse(APIModel):
    error: ErrorBody
