"""SP-104 request-bound execution coordination, with no live integrations.

Developer 2 owns authorization and payment; Developer 4 owns persistence and
idempotency. The injected governance adapter is a provisional handoff until
those teams provide a request-bound authorization contract. No real payment or
service adapter is constructed by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.policy_engine import Decision, PaymentRequest, PolicyResult
from app.services.task_parser import ParsedTask
from app.services.workflow import OptimizerRecommendation


class AgentStatus(StrEnum):
    INVALID_REQUEST = "invalid_request"
    HANDOFF_UNAVAILABLE = "handoff_unavailable"
    DUPLICATE_REQUEST = "duplicate_request"
    AWAITING_APPROVAL = "awaiting_approval"
    REJECTED = "rejected"
    EXECUTION_NOT_CONFIGURED = "execution_not_configured"
    EXECUTION_FAILED = "execution_failed"
    AWAITING_VERIFICATION = "awaiting_verification"


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    objective: str = Field(min_length=1)
    steps: tuple[str, ...]


class PurchaseProposal(BaseModel):
    """Details submitted to the shared backend; never an authorization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    amount: Decimal = Field(gt=0, allow_inf_nan=False)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class PurchaseRequest(PurchaseProposal):
    """Canonical backend response bound to the exact proposed purchase."""

    id: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    decision_reason: str

    def as_policy_request(self, vendor: str) -> PaymentRequest:
        """Map to Developer 2's existing USD-only governance input."""

        return PaymentRequest(task_id=self.task_id, vendor=vendor, amount_usd=self.amount)


class ResolvedProvider(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str = Field(min_length=1)
    vendor: str = Field(min_length=1)
    source_url: str = Field(min_length=1)


class ProviderResolverPort(Protocol):
    async def resolve(self, *, vendor: str, source_url: str) -> ResolvedProvider | None: ...


class PersistenceResult(BaseModel):
    """The backend must atomically indicate whether this key was newly created."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: PurchaseRequest
    created: bool = Field(strict=True)


class PurchasePersistencePort(Protocol):
    async def create(self, proposal: PurchaseProposal) -> PersistenceResult | None: ...


@dataclass(frozen=True)
class BoundGovernanceDecision:
    """Provisional adapter return: Developer 2 must attest the exact request.

    This wrapper is not an authorization credential. Its trusted adapter must
    retrieve and validate the actual server-owned decision and replay controls.
    """

    request: PurchaseRequest
    result: PolicyResult


class GovernanceReviewPort(Protocol):
    async def review(
        self, request: PaymentRequest, *, purchase: PurchaseRequest
    ) -> BoundGovernanceDecision | None: ...


class AdapterStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AdapterResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: AdapterStatus


class ApprovedServicePort(Protocol):
    async def execute(
        self, plan: ExecutionPlan, request: PurchaseRequest, decision: BoundGovernanceDecision
    ) -> AdapterResult: ...


class SafeServiceStub:
    """Default execution adapter; never performs payment or provider operations."""

    async def execute(
        self, plan: ExecutionPlan, request: PurchaseRequest, decision: BoundGovernanceDecision
    ) -> AdapterResult:
        return AdapterResult(status=AdapterStatus.NOT_CONFIGURED)


class AgentEvent(BaseModel):
    """Safe, in-memory event suitable for mapping to Developer 4's event schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str
    message: str


class AgentExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AgentStatus
    plan: ExecutionPlan | None = None
    purchase_request: PurchaseRequest | None = None
    events: list[AgentEvent] = Field(default_factory=list)


class ExecutionAgent:
    """Plan, request approval, and use only explicitly injected collaborators."""

    def __init__(
        self,
        *,
        governance: GovernanceReviewPort | None = None,
        service: ApprovedServicePort | None = None,
        provider_resolver: ProviderResolverPort | None = None,
        persistence: PurchasePersistencePort | None = None,
    ) -> None:
        self._governance = governance
        self._service = service if service is not None else SafeServiceStub()
        self._provider_resolver = provider_resolver
        self._persistence = persistence

    async def execute(
        self,
        task: ParsedTask,
        recommendation: OptimizerRecommendation,
        *,
        task_id: str,
        idempotency_key: str,
    ) -> AgentExecutionResult:
        """Coordinate one proposal; only a matching approved decision opens the gate."""

        provider = recommendation.provider
        if (
            not task.objective
            or task.ambiguities
            or not task_id.strip()
            or not idempotency_key.strip()
            or not provider.provider_name.strip()
            or not provider.is_eligible
            or not recommendation.constraints_satisfied
            or recommendation.currency != "USD"
            or provider.currency != recommendation.currency
            or recommendation.estimated_cost is None
        ):
            return self._result(
                AgentStatus.INVALID_REQUEST,
                "A supported task, USD recommendation, task ID, and idempotency key are required.",
            )

        if self._provider_resolver is None or self._persistence is None:
            return self._result(
                AgentStatus.HANDOFF_UNAVAILABLE,
                "Provider resolution and purchase persistence are not configured.",
            )
        try:
            resolved = await self._provider_resolver.resolve(
                vendor=provider.provider_name, source_url=provider.source_url
            )
        except Exception:
            return self._result(AgentStatus.HANDOFF_UNAVAILABLE, "Provider resolution unavailable.")
        if (
            not isinstance(resolved, ResolvedProvider)
            or not isinstance(resolved.provider_id, str)
            or not resolved.provider_id.strip()
            or resolved.vendor != provider.provider_name
            or resolved.source_url != provider.source_url
        ):
            return self._result(AgentStatus.INVALID_REQUEST, "Provider resolution did not match.")

        try:
            proposal = PurchaseProposal(
                task_id=task_id.strip(),
                provider_id=resolved.provider_id,
                idempotency_key=idempotency_key.strip(),
                amount=Decimal(str(recommendation.estimated_cost)),
                currency=recommendation.currency,
            )
        except (ValidationError, ValueError):
            return self._result(AgentStatus.INVALID_REQUEST, "The proposed purchase is invalid.")

        plan = ExecutionPlan(
            objective=task.objective,
            steps=(
                "Request governance review for the proposed purchase.",
                "Use the approved service through the configured adapter.",
                "Verify the outcome before marking the task complete.",
            ),
        )
        events = [AgentEvent(type="EXECUTION_PLANNED", message="Execution plan prepared.")]

        try:
            persisted = await self._persistence.create(proposal)
        except Exception:
            return self._result(
                AgentStatus.HANDOFF_UNAVAILABLE, "Purchase persistence unavailable.", plan
            )
        if not isinstance(persisted, PersistenceResult):
            return self._result(
                AgentStatus.HANDOFF_UNAVAILABLE, "No canonical purchase request returned.", plan
            )
        purchase = persisted.request
        if (
            not isinstance(purchase, PurchaseRequest)
            or not isinstance(purchase.id, str)
            or not purchase.id.strip()
            or any(
                getattr(purchase, field) != getattr(proposal, field)
                for field in type(proposal).model_fields
            )
        ):
            return self._result(
                AgentStatus.INVALID_REQUEST, "Canonical purchase details do not match.", plan
            )
        if persisted.created is not True:
            return self._result(
                AgentStatus.DUPLICATE_REQUEST,
                "Existing idempotency key requires backend reconciliation before execution.",
                plan, purchase, events,
            )

        if self._governance is None:
            return self._result(
                AgentStatus.AWAITING_APPROVAL,
                "Governance integration is not configured; no service action was taken.",
                plan,
                purchase,
                events,
            )
        try:
            decision = await self._governance.review(
                purchase.as_policy_request(provider.provider_name), purchase=purchase
            )
        except Exception:
            return self._result(
                AgentStatus.AWAITING_APPROVAL,
                "Governance review is unavailable; no service action was taken.",
                plan,
                purchase,
                events,
            )

        if (
            not isinstance(decision, BoundGovernanceDecision)
            or not isinstance(decision.result, PolicyResult)
            or decision.request != purchase
        ):
            return self._result(
                AgentStatus.AWAITING_APPROVAL,
                "No matching authorization was supplied; no service action was taken.",
                plan,
                purchase,
                events,
            )
        if decision.result.decision is Decision.DENIED:
            return self._result(
                AgentStatus.REJECTED, "Governance denied the request.", plan, purchase, events
            )
        if decision.result.decision is not Decision.APPROVED:
            return self._result(
                AgentStatus.AWAITING_APPROVAL,
                "Governance approval is pending; no service action was taken.",
                plan,
                purchase,
                events,
            )

        events.append(AgentEvent(type="POLICY_DECISION", message="Matching request approved."))
        try:
            adapter_result = await self._service.execute(plan, purchase, decision)
        except Exception:
            return self._result(
                AgentStatus.EXECUTION_FAILED,
                "Service adapter failed; outcome requires investigation before retrying.",
                plan,
                purchase,
                events,
            )
        if (
            not isinstance(adapter_result, AdapterResult)
            or adapter_result.status is AdapterStatus.FAILED
        ):
            return self._result(
                AgentStatus.EXECUTION_FAILED,
                "Service adapter did not confirm execution; investigate before retrying.",
                plan,
                purchase,
                events,
            )
        if adapter_result.status is AdapterStatus.NOT_CONFIGURED:
            return self._result(
                AgentStatus.EXECUTION_NOT_CONFIGURED,
                "Approved service integration is not configured; no service action was taken.",
                plan,
                purchase,
                events,
            )
        if adapter_result.status is not AdapterStatus.SUCCEEDED:
            return self._result(
                AgentStatus.EXECUTION_FAILED,
                "Service adapter returned an unrecognized status; investigate before retrying.",
                plan,
                purchase,
                events,
            )
        return self._result(
            AgentStatus.AWAITING_VERIFICATION,
            "Service adapter reported success; the task outcome still requires verification.",
            plan,
            purchase,
            events,
        )

    @staticmethod
    def _result(
        status: AgentStatus,
        message: str,
        plan: ExecutionPlan | None = None,
        purchase: PurchaseRequest | None = None,
        events: list[AgentEvent] | None = None,
    ) -> AgentExecutionResult:
        return AgentExecutionResult(
            status=status,
            plan=plan,
            purchase_request=purchase,
            events=[*(events or []), AgentEvent(type=status.value.upper(), message=message)],
        )
