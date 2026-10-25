"""Focused SP-004 workflow tests using only local injected fakes."""

from datetime import UTC, datetime

import pytest

from app.policy_engine import Decision, PolicyResult
from app.services.provider_research import (
    ProviderRecord,
    ProviderResearchResult,
    ResearchStatus,
)
from app.services.task_parser import Budget, ParsedTask, ParserResult, ParserStatus
from app.services.workflow import (
    ApprovalStatus,
    OptimizerRecommendation,
    SpendPilotWorkflow,
    WorkflowDependencies,
    WorkflowStatus,
)

TIMESTAMP = datetime(2026, 10, 24, 18, 0, tzinfo=UTC)
TASK = ParsedTask(
    objective="Process documents",
    budget=Budget(amount=50, currency="USD"),
    quantity=1000,
    quality_target="95 percent accuracy",
    constraints=["EU data residency"],
)
PROVIDER = ProviderRecord(
    provider_name="Alpha",
    service_description="Document processing service",
    capabilities=["document processing", "95 percent accuracy"],
    pricing_model="per document",
    price_estimate=25,
    currency="USD",
    source_url="https://alpha.example/pricing",
    retrieved_at=TIMESTAMP,
    constraints=["EU data residency"],
    quality_claims=["95 percent accuracy"],
    maximum_quantity=5000,
    confidence=0.9,
    is_eligible=True,
)
RESEARCH = ProviderResearchResult(
    providers=[PROVIDER],
    research_status=ResearchStatus.COMPLETE,
    source_urls=[str(PROVIDER.source_url)],
    retrieved_at=TIMESTAMP,
)
RECOMMENDATION = OptimizerRecommendation(
    provider=PROVIDER,
    rationale="Eligible provider is within the stated budget.",
    estimated_cost=25,
    currency="USD",
    constraints_satisfied=True,
)


class FakeParser:
    def __init__(self, result: ParserResult) -> None:
        self.result = result
        self.calls = 0

    async def parse(self, raw_task: str) -> ParserResult:
        del raw_task
        self.calls += 1
        return self.result


class FakeResearcher:
    def __init__(self, result: ProviderResearchResult) -> None:
        self.result = result
        self.calls = 0

    async def research(self, task: ParsedTask) -> ProviderResearchResult:
        assert task == TASK
        self.calls += 1
        return self.result


class FakeOptimizer:
    def __init__(self, recommendation: OptimizerRecommendation | None) -> None:
        self.recommendation = recommendation
        self.calls = 0

    async def recommend(
        self, task: ParsedTask, research: ProviderResearchResult
    ) -> OptimizerRecommendation | None:
        assert task == TASK
        assert research == RESEARCH
        self.calls += 1
        return self.recommendation


class FakeGovernance:
    def __init__(self, decision: PolicyResult | None) -> None:
        self.decision = decision
        self.calls = 0

    async def get_decision(
        self, task: ParsedTask, recommendation: OptimizerRecommendation
    ) -> PolicyResult | None:
        assert task == TASK
        assert recommendation == RECOMMENDATION
        self.calls += 1
        return self.decision


def complete_parser_result() -> ParserResult:
    return ParserResult(
        is_ready_for_next_step=True,
        parsed_task=TASK,
        status=ParserStatus.COMPLETE,
    )


def build_workflow(
    *,
    parser_result: ParserResult | None = None,
    research_result: ProviderResearchResult | None = None,
    recommendation: OptimizerRecommendation | None = RECOMMENDATION,
    governance: FakeGovernance | None = None,
) -> tuple[SpendPilotWorkflow, FakeParser, FakeResearcher, FakeOptimizer]:
    parser = FakeParser(parser_result or complete_parser_result())
    researcher = FakeResearcher(research_result or RESEARCH)
    optimizer = FakeOptimizer(recommendation)
    workflow = SpendPilotWorkflow(
        WorkflowDependencies(
            parser=parser,
            researcher=researcher,
            optimizer=optimizer,
            governance=governance,
        )
    )
    return workflow, parser, researcher, optimizer


@pytest.mark.asyncio
async def test_incomplete_task_routes_to_clarification_needed() -> None:
    incomplete = ParserResult(
        is_ready_for_next_step=False,
        parsed_task=TASK.model_copy(update={"quantity": None}),
        missing_fields=["quantity"],
        clarification_questions=["What quantity is required?"],
        status=ParserStatus.INCOMPLETE,
    )
    workflow, parser, researcher, optimizer = build_workflow(parser_result=incomplete)

    result = await workflow.run("Process some documents.")

    assert result.status is WorkflowStatus.CLARIFICATION_NEEDED
    assert parser.calls == 1
    assert researcher.calls == 0
    assert optimizer.calls == 0


@pytest.mark.asyncio
async def test_research_failure_routes_to_safe_failure() -> None:
    unavailable = ProviderResearchResult(
        research_status=ResearchStatus.RESEARCH_UNAVAILABLE,
        retrieved_at=TIMESTAMP,
        warnings=["Provider research is unavailable."],
    )
    workflow, _, researcher, optimizer = build_workflow(research_result=unavailable)

    result = await workflow.run("Process 1,000 documents under $50.")

    assert result.status is WorkflowStatus.RESEARCH_UNAVAILABLE
    assert researcher.calls == 1
    assert optimizer.calls == 0


@pytest.mark.asyncio
async def test_recommendation_stops_awaiting_explicit_governance_approval() -> None:
    workflow, _, _, _ = build_workflow()

    result = await workflow.run("Process 1,000 documents under $50.")

    assert result.status is WorkflowStatus.AWAITING_GOVERNANCE_APPROVAL
    assert result.approval_status is ApprovalStatus.AWAITING
    assert result.execution_result is None
    assert result.verification_result is None


@pytest.mark.asyncio
async def test_no_viable_recommendation_routes_to_safe_terminal_state() -> None:
    workflow, _, _, optimizer = build_workflow(recommendation=None)

    result = await workflow.run("Process 1,000 documents under $50.")

    assert result.status is WorkflowStatus.NO_RECOMMENDATION
    assert optimizer.calls == 1
    assert result.execution_result is None


@pytest.mark.asyncio
async def test_denied_governance_decision_routes_to_rejected() -> None:
    governance = FakeGovernance(PolicyResult(Decision.DENIED, "Budget policy denied request."))
    workflow, _, _, _ = build_workflow(governance=governance)

    result = await workflow.run("Process 1,000 documents under $50.")

    assert result.status is WorkflowStatus.REJECTED
    assert result.approval_status is ApprovalStatus.DENIED
    assert governance.calls == 1
    assert result.execution_result is None


@pytest.mark.asyncio
async def test_approved_path_uses_safe_stub_execution_and_verification() -> None:
    governance = FakeGovernance(PolicyResult(Decision.APPROVED, "Explicitly approved."))
    workflow, _, _, _ = build_workflow(governance=governance)

    result = await workflow.run("Process 1,000 documents under $50.")

    assert result.status is WorkflowStatus.COMPLETE
    assert result.approval_status is ApprovalStatus.APPROVED
    assert result.execution_result is not None
    assert result.execution_result.status.value == "stubbed"
    assert result.verification_result is not None
    assert result.verification_result.status.value == "stubbed"
    assert any("no provider action" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_no_governance_or_execution_is_called_without_explicit_approval() -> None:
    workflow, parser, researcher, optimizer = build_workflow()

    result = await workflow.run("Process 1,000 documents under $50.")

    assert result.status is WorkflowStatus.AWAITING_GOVERNANCE_APPROVAL
    assert parser.calls == 1
    assert researcher.calls == 1
    assert optimizer.calls == 1
    assert result.execution_result is None
    assert result.verification_result is None
