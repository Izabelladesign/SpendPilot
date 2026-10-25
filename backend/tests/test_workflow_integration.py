"""Local integration of intake, research, optimization, and the approval gate."""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.policy_engine import Decision, PolicyResult
from app.services.cost_optimizer import CostOptimizer
from app.services.provider_research import ProviderRecord, ProviderResearchAgent
from app.services.task_parser import Budget, ParsedTask, StructuredTask, TaskParser
from app.services.workflow import (
    ApprovalStatus,
    ExecutionResult,
    ExecutionStatus,
    OptimizerRecommendation,
    SpendPilotWorkflow,
    WorkflowDependencies,
    WorkflowStatus,
)

REQUEST = "Process 1,000 documents for under $50 with 95 percent accuracy and EU data residency."
TASK = ParsedTask(
    objective="Process documents",
    budget=Budget(amount=50, currency="USD"),
    quantity=1000,
    quality_target="95 percent accuracy",
    constraints=["EU data residency"],
)


class FakeStructuredClient:
    """Provide a structured model response without contacting OpenAI."""

    def __init__(self) -> None:
        self.calls = 0

    async def parse_structured(
        self, *, raw_task: str, response_model: type[StructuredTask]
    ) -> StructuredTask | dict[str, Any]:
        self.calls += 1
        assert raw_task == REQUEST
        assert response_model is ParsedTask
        return TASK.model_dump()


class FakeResearchClient:
    """Provide local SP-102 records without contacting Bright Data."""

    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record
        self.calls = 0

    async def find_providers(self, task: ParsedTask) -> list[ProviderRecord | dict[str, Any]]:
        self.calls += 1
        assert task == TASK
        return [self.record]


class FakeGovernance:
    def __init__(self, decision: PolicyResult | None) -> None:
        self.decision = decision
        self.calls = 0

    async def get_decision(
        self, task: ParsedTask, recommendation: OptimizerRecommendation
    ) -> PolicyResult | None:
        self.calls += 1
        assert task == TASK
        assert recommendation.provider.provider_name == "Document Provider"
        return self.decision


class SpyExecutor:
    """A local spy that cannot execute a provider or initiate payment."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self, task: ParsedTask, recommendation: OptimizerRecommendation
    ) -> ExecutionResult:
        self.calls += 1
        return ExecutionResult(status=ExecutionStatus.STUBBED, message="No provider action.")


@pytest.fixture
def priced_provider() -> dict[str, Any]:
    return {
        "provider_name": "Document Provider",
        "service_description": "Document processing",
        "capabilities": ["process documents"],
        "pricing_model": "one-time total for requested quantity",
        "price_estimate": 25,
        "currency": "USD",
        "source_url": "https://provider.example/pricing",
        "retrieved_at": datetime(2026, 10, 24, tzinfo=UTC),
        "constraints": ["EU data residency"],
        "quality_claims": ["95 percent accuracy"],
        "maximum_quantity": 1000,
    }


def build_flow(
    record: dict[str, Any], governance: FakeGovernance | None, executor: SpyExecutor
) -> tuple[SpendPilotWorkflow, FakeStructuredClient, FakeResearchClient]:
    model = FakeStructuredClient()
    research_client = FakeResearchClient(record)
    workflow = SpendPilotWorkflow(
        WorkflowDependencies(
            parser=TaskParser(model),
            researcher=ProviderResearchAgent(research_client),
            optimizer=CostOptimizer(),
            governance=governance,
            executor=executor,
        )
    )
    return workflow, model, research_client


@pytest.mark.asyncio
async def test_supported_provider_is_recommended_and_awaits_approval(
    priced_provider: dict[str, Any],
) -> None:
    governance = FakeGovernance(None)
    executor = SpyExecutor()
    workflow, model, research = build_flow(priced_provider, governance, executor)

    result = await workflow.run(REQUEST)

    assert model.calls == research.calls == governance.calls == 1
    assert result.parsed_task == TASK
    assert result.research_result is not None
    assert result.research_result.providers[0].is_eligible
    assert result.recommendation is not None
    assert result.recommendation.estimated_cost == 25
    assert result.status is WorkflowStatus.AWAITING_GOVERNANCE_APPROVAL
    assert result.approval_status is ApprovalStatus.AWAITING
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_bright_data_style_missing_pricing_produces_no_recommendation(
    priced_provider: dict[str, Any],
) -> None:
    bright_data_style = {
        **priced_provider,
        "pricing_model": None,
        "price_estimate": None,
        "currency": None,
        "constraints": [],
        "quality_claims": [],
        "maximum_quantity": None,
    }
    governance = FakeGovernance(None)
    executor = SpyExecutor()
    workflow, _, research = build_flow(bright_data_style, governance, executor)

    result = await workflow.run(REQUEST)

    assert research.calls == 1
    assert result.research_result is not None
    assert result.research_result.providers[0].price_estimate is None
    assert result.recommendation is None
    assert result.status is WorkflowStatus.NO_RECOMMENDATION
    assert governance.calls == executor.calls == 0


@pytest.mark.asyncio
async def test_denied_approval_never_triggers_execution(priced_provider: dict[str, Any]) -> None:
    governance = FakeGovernance(PolicyResult(Decision.DENIED, "Denied by policy."))
    executor = SpyExecutor()
    workflow, _, _ = build_flow(priced_provider, governance, executor)

    result = await workflow.run(REQUEST)

    assert result.status is WorkflowStatus.REJECTED
    assert result.approval_status is ApprovalStatus.DENIED
    assert governance.calls == 1
    assert executor.calls == 0
    assert result.execution_result is None


@pytest.mark.asyncio
async def test_no_execution_without_explicit_governance_approval(
    priced_provider: dict[str, Any],
) -> None:
    executor = SpyExecutor()
    workflow, _, _ = build_flow(priced_provider, None, executor)

    result = await workflow.run(REQUEST)

    assert result.status is WorkflowStatus.AWAITING_GOVERNANCE_APPROVAL
    assert executor.calls == 0
    assert result.execution_result is None
