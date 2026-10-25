"""Local SP-103 evidence and ranking tests; no provider calls are made."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.services.cost_optimizer import CostOptimizer
from app.services.provider_research import ProviderRecord, ProviderResearchResult, ResearchStatus
from app.services.task_parser import Budget, ParsedTask, ParserResult, ParserStatus
from app.services.workflow import SpendPilotWorkflow, WorkflowDependencies, WorkflowStatus

TASK = ParsedTask(
    objective="Process documents",
    budget=Budget(amount=50, currency="USD"),
    quantity=1000,
    quality_target="95 percent accuracy",
    constraints=["EU data residency"],
)
TIMESTAMP = datetime(2026, 10, 24, 18, 0, tzinfo=UTC)


def provider(name: str = "Alpha", /, **updates: object) -> ProviderRecord:
    base = ProviderRecord(
        provider_name=name,
        service_description="Document processing",
        capabilities=["document processing"],
        pricing_model="one-time total for requested quantity",
        price_estimate=25,
        currency="USD",
        source_url=f"https://{name.lower()}.example/pricing",
        retrieved_at=TIMESTAMP,
        constraints=["EU data residency"],
        quality_claims=["95 percent accuracy"],
        maximum_quantity=1000,
        is_eligible=True,
    )
    return base.model_copy(update=updates)


def research(*providers: ProviderRecord) -> ProviderResearchResult:
    return ProviderResearchResult(
        providers=list(providers),
        research_status=ResearchStatus.COMPLETE,
        retrieved_at=TIMESTAMP,
    )


def test_valid_total_price_is_recommended_with_evidence() -> None:
    result = CostOptimizer().optimize(TASK, research(provider()))

    assert result.recommendation is not None
    assert result.recommendation.estimated_cost == 25
    assert result.recommendation.constraints_satisfied is True
    assert result.ranked_options[0].estimated_total == Decimal("25.0")
    assert result.ranked_options[0].rank == 1


def test_over_budget_provider_is_not_recommended() -> None:
    result = CostOptimizer().optimize(TASK, research(provider(price_estimate=51)))

    assert result.recommendation is None
    assert "exceeds the task budget" in " ".join(result.assessments[0].issues)


@pytest.mark.parametrize("updates", [{"price_estimate": None}, {"pricing_model": None}])
def test_missing_or_unclear_pricing_cannot_support_recommendation(
    updates: dict[str, object],
) -> None:
    result = CostOptimizer().optimize(TASK, research(provider(**updates)))

    assert result.recommendation is None
    assert result.assessments[0].issues


@pytest.mark.parametrize(
    "updates, expected",
    [
        ({"currency": "EUR"}, "currency differs"),
        ({"pricing_model": "per month"}, "period is unclear"),
        ({"pricing_model": "per document"}, "period is unclear"),
        ({"pricing_model": "total"}, "requested quantity"),
    ],
)
def test_mismatched_currency_or_pricing_period_is_not_compared(
    updates: dict[str, object], expected: str
) -> None:
    result = CostOptimizer().optimize(TASK, research(provider(**updates)))

    assert result.recommendation is None
    assert expected in " ".join(result.assessments[0].issues)


def test_recurring_task_budget_is_not_assumed_to_be_one_time() -> None:
    task = TASK.model_copy(update={"objective": "Process documents for under $50 per month"})

    result = CostOptimizer().optimize(task, research(provider()))

    assert result.recommendation is None
    assert "Recurring" in " ".join(result.assessments[0].issues)


def test_verified_per_unit_price_is_multiplied_by_task_quantity() -> None:
    task = TASK.model_copy(update={"quantity_unit": "document"})
    item = provider(
        pricing_model="per unit",
        pricing_unit="document",
        billing_period="one-time",
        price_estimate=0.02,
    )

    result = CostOptimizer().optimize(task, research(item))

    assert result.recommendation is not None
    assert result.ranked_options[0].estimated_total == Decimal("20.00")
    assert result.recommendation.estimated_cost == 20


def test_verified_per_request_price_uses_explicit_request_count() -> None:
    task = TASK.model_copy(update={"request_count": 10})
    item = provider(pricing_model="per request", billing_period="one-time", price_estimate=3)

    result = CostOptimizer().optimize(task, research(item))

    assert result.recommendation is not None
    assert result.ranked_options[0].estimated_total == Decimal("30.0")


def test_per_unit_total_above_budget_is_not_recommended() -> None:
    task = TASK.model_copy(update={"quantity_unit": "document"})
    item = provider(
        pricing_model="per unit",
        pricing_unit="document",
        billing_period="one-time",
        price_estimate=0.10,
    )

    result = CostOptimizer().optimize(task, research(item))

    assert result.recommendation is None
    assert result.assessments[0].estimated_total == Decimal("100.00")
    assert "exceeds the task budget" in " ".join(result.assessments[0].issues)


@pytest.mark.parametrize(
    "task_updates, provider_updates, expected",
    [
        ({"quantity": None, "quantity_unit": "document"}, {}, "task quantity"),
        ({}, {}, "explicit task and provider units"),
        ({"quantity_unit": "page"}, {}, "do not match"),
        ({"quantity_unit": "document"}, {"billing_period": None}, "billing period"),
        ({"quantity_unit": "document"}, {"billing_period": "monthly"}, "billing period"),
    ],
)
def test_per_unit_requires_comparable_evidence(
    task_updates: dict[str, object], provider_updates: dict[str, object], expected: str
) -> None:
    task = TASK.model_copy(update=task_updates)
    updates = {
        "pricing_model": "per unit",
        "pricing_unit": "document",
        "billing_period": "one-time",
        "price_estimate": 0.02,
        **provider_updates,
    }
    result = CostOptimizer().optimize(task, research(provider(**updates)))

    assert result.recommendation is None
    assert result.assessments[0].estimated_total is None
    assert expected in " ".join(result.assessments[0].issues)


def test_per_request_requires_explicit_request_count() -> None:
    item = provider(pricing_model="per request", billing_period="one-time", price_estimate=3)

    result = CostOptimizer().optimize(TASK, research(item))

    assert result.recommendation is None
    assert result.assessments[0].estimated_total is None
    assert "request count" in " ".join(result.assessments[0].issues)


@pytest.mark.parametrize("billing_period", [None, "monthly"])
def test_per_request_requires_comparable_billing_period(billing_period: str | None) -> None:
    task = TASK.model_copy(update={"request_count": 10})
    item = provider(pricing_model="per request", billing_period=billing_period, price_estimate=3)

    result = CostOptimizer().optimize(task, research(item))

    assert result.recommendation is None
    assert result.assessments[0].estimated_total is None
    assert "billing period" in " ".join(result.assessments[0].issues)


def test_per_unit_currency_mismatch_is_not_calculated() -> None:
    task = TASK.model_copy(update={"quantity_unit": "document"})
    item = provider(
        pricing_model="per unit",
        pricing_unit="document",
        billing_period="one-time",
        currency="EUR",
        price_estimate=0.02,
    )

    result = CostOptimizer().optimize(task, research(item))

    assert result.recommendation is None
    assert result.assessments[0].estimated_total is None
    assert "currency differs" in " ".join(result.assessments[0].issues)


def test_ranking_mixed_total_unit_and_request_prices() -> None:
    task = TASK.model_copy(update={"quantity_unit": "document", "request_count": 10})
    result = CostOptimizer().optimize(
        task,
        research(
            provider("Total", price_estimate=25),
            provider(
                "Unit", pricing_model="per unit", pricing_unit="document",
                billing_period="one-time", price_estimate=0.02,
            ),
            provider("Request", pricing_model="per request", billing_period="one-time",
                     price_estimate=1),
        ),
    )

    assert [item.provider.provider_name for item in result.ranked_options] == [
        "Request", "Unit", "Total"
    ]
    assert [item.estimated_total for item in result.ranked_options] == [
        Decimal("10.0"), Decimal("20.00"), Decimal("25.0")
    ]


@pytest.mark.parametrize(
    "updates, expected",
    [
        ({"constraints": []}, "Constraint is unverified"),
        ({"limitations": ["Cannot provide EU data residency"]}, "may conflict"),
        ({"quality_claims": []}, "quality target"),
        ({"maximum_quantity": 500}, "capacity is below"),
        ({"maximum_quantity": None}, "capacity for the requested quantity is unverified"),
    ],
)
def test_unmet_or_unverified_requirements_are_not_recommended(
    updates: dict[str, object], expected: str
) -> None:
    result = CostOptimizer().optimize(TASK, research(provider(**updates)))

    assert result.recommendation is None
    assert expected in " ".join(result.assessments[0].issues)


def test_multiple_eligible_options_rank_by_supported_total() -> None:
    result = CostOptimizer().optimize(
        TASK,
        research(
            provider("Expensive", price_estimate=40),
            provider("Cheap", price_estimate=20),
            provider("Ignored", price_estimate=1, is_eligible=False),
        ),
    )

    assert [item.provider.provider_name for item in result.ranked_options] == ["Cheap", "Expensive"]
    assert result.recommendation is not None
    assert result.recommendation.provider.provider_name == "Cheap"
    assert len(result.assessments) == 2


def test_no_viable_options_returns_diagnostics() -> None:
    result = CostOptimizer().optimize(
        TASK, research(provider("Over", price_estimate=100), provider("Unknown", currency=None))
    )

    assert result.recommendation is None
    assert result.ranked_options == []
    assert len(result.assessments) == 2
    assert result.warnings


@pytest.mark.asyncio
async def test_optimizer_implements_workflow_port_and_stops_at_governance() -> None:
    class FakeParser:
        async def parse(self, raw_task: str) -> ParserResult:
            return ParserResult(
                is_ready_for_next_step=True, parsed_task=TASK, status=ParserStatus.COMPLETE
            )

    class FakeResearcher:
        async def research(self, task: ParsedTask) -> ProviderResearchResult:
            return research(provider())

    result = await SpendPilotWorkflow(
        WorkflowDependencies(
            parser=FakeParser(),
            researcher=FakeResearcher(),
            optimizer=CostOptimizer(),
        )
    ).run("Process documents")

    assert result.status is WorkflowStatus.AWAITING_GOVERNANCE_APPROVAL
    assert result.recommendation is not None
    assert result.execution_result is None
