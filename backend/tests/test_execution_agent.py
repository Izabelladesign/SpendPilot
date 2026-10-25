"""SP-104 request-bound execution tests using only local collaborators."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.policy_engine import Decision, PaymentRequest, PolicyResult
from app.services.execution_agent import (
    AdapterResult,
    AdapterStatus,
    AgentExecutionResult,
    AgentStatus,
    BoundGovernanceDecision,
    ExecutionAgent,
    ExecutionPlan,
    PersistenceResult,
    PurchaseProposal,
    PurchaseRequest,
    ResolvedProvider,
)
from app.services.provider_research import ProviderRecord
from app.services.task_parser import Budget, ParsedTask
from app.services.workflow import OptimizerRecommendation

TASK = ParsedTask(
    objective="Process documents",
    budget=Budget(amount=50, currency="USD"),
    quantity=1000,
    quality_target="95 percent accuracy",
    constraints=["EU data residency"],
)
PROVIDER = ProviderRecord(
    provider_name="Alpha",
    service_description="Document processing",
    source_url="https://alpha.example/pricing",
    retrieved_at=datetime(2026, 10, 24, tzinfo=UTC),
    currency="USD",
    is_eligible=True,
)
RECOMMENDATION = OptimizerRecommendation(
    provider=PROVIDER,
    rationale="Supported total for the requested quantity.",
    estimated_cost=25,
    currency="USD",
    constraints_satisfied=True,
)


class FakeGovernance:
    def __init__(
        self, decision: Decision | None, *, mismatch: dict[str, object] | None = None
    ) -> None:
        self.decision = decision
        self.mismatch = mismatch
        self.calls: list[PaymentRequest] = []

    async def review(
        self, request: PaymentRequest, *, purchase: PurchaseRequest
    ) -> BoundGovernanceDecision | None:
        self.calls.append(request)
        if self.decision is None:
            return None
        if self.mismatch:
            purchase = purchase.model_copy(update=self.mismatch)
        return BoundGovernanceDecision(purchase, PolicyResult(self.decision, "Local fake decision"))


class FakeService:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[PurchaseRequest] = []
        self.fail = fail

    async def execute(
        self, plan: ExecutionPlan, request: PurchaseRequest, decision: BoundGovernanceDecision
    ) -> AdapterResult:
        self.calls.append(request)
        assert decision.request == request
        if self.fail:
            raise RuntimeError("private adapter error")
        return AdapterResult(status=AdapterStatus.SUCCEEDED)


class FakeResolver:
    async def resolve(self, *, vendor: str, source_url: str) -> ResolvedProvider:
        return ResolvedProvider(provider_id="provider-1", vendor=vendor, source_url=source_url)


class FakePersistence:
    def __init__(self, *, mismatch: dict[str, object] | None = None) -> None:
        self.proposals: list[PurchaseProposal] = []
        self.mismatch = mismatch or {}

    async def create(self, proposal: PurchaseProposal) -> PersistenceResult:
        duplicate = bool(self.proposals)
        self.proposals.append(proposal)
        request = PurchaseRequest(
            **proposal.model_dump(), id="purchase-1", decision="pending", decision_reason=""
        ).model_copy(update=self.mismatch)
        return PersistenceResult(request=request, created=not duplicate)


async def run_agent(agent: ExecutionAgent) -> AgentExecutionResult:
    agent._provider_resolver = FakeResolver()
    agent._persistence = FakePersistence()
    return await agent.execute(TASK, RECOMMENDATION, task_id="task-1", idempotency_key="run-1")


@pytest.mark.asyncio
async def test_matching_approval_invokes_adapter_once_but_awaits_verification() -> None:
    governance = FakeGovernance(Decision.APPROVED)
    service = FakeService()
    result = await run_agent(ExecutionAgent(governance=governance, service=service))

    assert result.status is AgentStatus.AWAITING_VERIFICATION
    assert result.plan is not None
    assert "Verify" in result.plan.steps[-1]
    assert result.purchase_request is not None
    assert governance.calls == [PaymentRequest("task-1", "Alpha", Decimal("25.0"))]
    assert service.calls == [result.purchase_request]
    assert any(event.type == "POLICY_DECISION" for event in result.events)


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", [Decision.DENIED, Decision.REVIEW_REQUIRED, None])
async def test_denied_or_missing_approval_never_invokes_service(decision: Decision | None) -> None:
    governance = FakeGovernance(decision)
    service = FakeService()
    result = await run_agent(ExecutionAgent(governance=governance, service=service))

    expected = (
        AgentStatus.REJECTED if decision is Decision.DENIED else AgentStatus.AWAITING_APPROVAL
    )
    assert result.status is expected
    assert len(governance.calls) == 1
    assert service.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch",
    [
        {"amount": Decimal("1.00")},
        {"task_id": "another-task"},
        {"provider_id": "another-provider"},
        {"idempotency_key": "another-key"},
        {"id": "another-request"},
        {"currency": "EUR"},
    ],
)
async def test_approval_for_different_purchase_is_not_authorization(
    mismatch: dict[str, object],
) -> None:
    governance = FakeGovernance(Decision.APPROVED, mismatch=mismatch)
    service = FakeService()
    result = await run_agent(ExecutionAgent(governance=governance, service=service))

    assert result.status is AgentStatus.AWAITING_APPROVAL
    assert service.calls == []


@pytest.mark.asyncio
async def test_persistence_receives_proposal_and_governance_receives_canonical_id() -> None:
    persistence = FakePersistence()
    governance = FakeGovernance(Decision.APPROVED)
    service = FakeService()
    agent = ExecutionAgent(
        provider_resolver=FakeResolver(), persistence=persistence,
        governance=governance, service=service,
    )
    result = await agent.execute(TASK, RECOMMENDATION, task_id="task-1", idempotency_key="run-1")
    assert persistence.proposals == [PurchaseProposal(
        task_id="task-1", provider_id="provider-1", idempotency_key="run-1",
        amount=Decimal("25.0"), currency="USD",
    )]
    assert result.purchase_request is not None
    assert result.purchase_request.id == "purchase-1"
    assert service.calls == [result.purchase_request]


@pytest.mark.asyncio
async def test_missing_persistence_stops_before_governance() -> None:
    governance = FakeGovernance(Decision.APPROVED)
    service = FakeService()
    agent = ExecutionAgent(provider_resolver=FakeResolver(), governance=governance, service=service)
    result = await agent.execute(TASK, RECOMMENDATION, task_id="task-1", idempotency_key="run-1")
    assert result.status is AgentStatus.HANDOFF_UNAVAILABLE
    assert not governance.calls and not service.calls


@pytest.mark.asyncio
async def test_persistence_failure_stops_without_exposing_error() -> None:
    class UnavailablePersistence:
        async def create(self, proposal: PurchaseProposal) -> PersistenceResult:
            raise TimeoutError("private backend details")

    governance = FakeGovernance(Decision.APPROVED)
    service = FakeService()
    agent = ExecutionAgent(
        provider_resolver=FakeResolver(), persistence=UnavailablePersistence(),
        governance=governance, service=service,
    )
    result = await agent.execute(TASK, RECOMMENDATION, task_id="task-1", idempotency_key="run-1")
    assert result.status is AgentStatus.HANDOFF_UNAVAILABLE
    assert "private backend details" not in result.model_dump_json()
    assert not governance.calls and not service.calls


@pytest.mark.asyncio
async def test_mismatched_provider_resolution_stops_before_persistence() -> None:
    class WrongResolver:
        async def resolve(self, *, vendor: str, source_url: str) -> ResolvedProvider:
            return ResolvedProvider(provider_id="provider-1", vendor="Other", source_url=source_url)

    persistence = FakePersistence()
    governance = FakeGovernance(Decision.APPROVED)
    agent = ExecutionAgent(
        provider_resolver=WrongResolver(), persistence=persistence, governance=governance,
    )
    result = await agent.execute(TASK, RECOMMENDATION, task_id="task-1", idempotency_key="run-1")
    assert result.status is AgentStatus.INVALID_REQUEST
    assert not persistence.proposals and not governance.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", [
    {"id": ""}, {"id": None}, {"task_id": "other"}, {"provider_id": "other"},
    {"idempotency_key": "other"}, {"amount": Decimal("1")}, {"currency": "EUR"},
])
async def test_mismatched_persisted_purchase_stops_before_governance(
    mismatch: dict[str, object],
) -> None:
    governance = FakeGovernance(Decision.APPROVED)
    service = FakeService()
    agent = ExecutionAgent(
        provider_resolver=FakeResolver(), persistence=FakePersistence(mismatch=mismatch),
        governance=governance, service=service,
    )
    result = await agent.execute(TASK, RECOMMENDATION, task_id="task-1", idempotency_key="run-1")
    assert result.status is AgentStatus.INVALID_REQUEST
    assert not governance.calls and not service.calls


@pytest.mark.asyncio
async def test_duplicate_request_never_executes_twice() -> None:
    service = FakeService()
    agent = ExecutionAgent(
        provider_resolver=FakeResolver(), persistence=FakePersistence(),
        governance=FakeGovernance(Decision.APPROVED), service=service,
    )
    first = await agent.execute(TASK, RECOMMENDATION, task_id="task-1", idempotency_key="run-1")
    second = await agent.execute(TASK, RECOMMENDATION, task_id="task-1", idempotency_key="run-1")
    assert first.status is AgentStatus.AWAITING_VERIFICATION
    assert second.status is AgentStatus.DUPLICATE_REQUEST
    assert len(service.calls) == 1


@pytest.mark.asyncio
async def test_missing_governance_never_invokes_service() -> None:
    service = FakeService()
    result = await run_agent(ExecutionAgent(service=service))

    assert result.status is AgentStatus.AWAITING_APPROVAL
    assert service.calls == []


@pytest.mark.asyncio
async def test_adapter_failure_is_safe_and_does_not_retry() -> None:
    governance = FakeGovernance(Decision.APPROVED)
    service = FakeService(fail=True)
    result = await run_agent(ExecutionAgent(governance=governance, service=service))

    assert result.status is AgentStatus.EXECUTION_FAILED
    assert len(service.calls) == 1
    assert "private adapter error" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_default_service_is_a_safe_stub_after_approval() -> None:
    result = await run_agent(ExecutionAgent(governance=FakeGovernance(Decision.APPROVED)))

    assert result.status is AgentStatus.EXECUTION_NOT_CONFIGURED


@pytest.mark.asyncio
async def test_unsupported_recommendation_never_reaches_governance_or_service() -> None:
    governance = FakeGovernance(Decision.APPROVED)
    service = FakeService()
    unsupported = RECOMMENDATION.model_copy(update={"constraints_satisfied": False})

    result = await ExecutionAgent(governance=governance, service=service).execute(
        TASK, unsupported, task_id="task-1", idempotency_key="run-1"
    )

    assert result.status is AgentStatus.INVALID_REQUEST
    assert governance.calls == []
    assert service.calls == []
