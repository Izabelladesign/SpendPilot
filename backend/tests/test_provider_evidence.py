"""SP-102 cited-evidence handoff tests with local fixtures only."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.services.cost_optimizer import CostOptimizer
from app.services.provider_evidence import (
    EvidenceSource,
    SourcedPricingEvidence,
    SourcedProviderEvidence,
    SuppliedEvidenceResearchClient,
)
from app.services.provider_research import ProviderResearchAgent, ResearchStatus
from app.services.task_parser import Budget, ParsedTask, ParserResult, ParserStatus
from app.services.workflow import SpendPilotWorkflow, WorkflowDependencies, WorkflowStatus

SERVICE_TIME = datetime(2026, 10, 24, 10, tzinfo=UTC)
PRICE_TIME = datetime(2026, 10, 24, 11, tzinfo=UTC)
TASK = ParsedTask(
    objective="Process documents",
    budget=Budget(amount=50, currency="USD"),
    quantity=1000,
    quantity_unit="document",
    quality_target="95 percent accuracy",
    constraints=["EU data residency"],
)


def evidence(name: str, price: float) -> SourcedProviderEvidence:
    return SourcedProviderEvidence(
        provider_name=name,
        service_description="Document processing service",
        source=EvidenceSource(
            url=f"https://{name.lower()}.example/service", retrieved_at=SERVICE_TIME
        ),
        capabilities=["document processing"],
        constraints=["EU data residency"],
        quality_claims=["95 percent accuracy"],
        maximum_quantity=1000,
        pricing=SourcedPricingEvidence(
            source=EvidenceSource(
                url=f"https://{name.lower()}.example/pricing", retrieved_at=PRICE_TIME
            ),
            price_estimate=price,
            currency="USD",
            pricing_model="per unit",
            pricing_unit="document",
            billing_period="one-time",
        ),
    )


@pytest.mark.asyncio
async def test_two_sourced_providers_rank_and_preserve_sources_and_timestamps() -> None:
    client = SuppliedEvidenceResearchClient([evidence("Alpha", 0.03), evidence("Beta", 0.02)])
    research = await ProviderResearchAgent(client).research(TASK)
    result = CostOptimizer().optimize(TASK, research)

    assert research.research_status is ResearchStatus.COMPLETE
    assert [item.provider.provider_name for item in result.ranked_options] == ["Beta", "Alpha"]
    assert [item.estimated_total for item in result.ranked_options] == [
        Decimal("20.00"), Decimal("30.00")
    ]
    alpha = research.providers[0]
    assert alpha.source_url == "https://alpha.example/service"
    assert alpha.retrieved_at == SERVICE_TIME
    assert alpha.pricing_source_url == "https://alpha.example/pricing"
    assert alpha.pricing_retrieved_at == PRICE_TIME
    assert research.source_urls == [
        "https://alpha.example/service",
        "https://alpha.example/pricing",
        "https://beta.example/service",
        "https://beta.example/pricing",
    ]
    assert research.retrieved_at == PRICE_TIME


@pytest.mark.asyncio
@pytest.mark.parametrize("pricing_kind", ["missing", "ambiguous"])
async def test_missing_or_ambiguous_pricing_is_not_recommended(pricing_kind: str) -> None:
    supplied = evidence("Alpha", 0.02)
    assert supplied.pricing is not None
    if pricing_kind == "missing":
        supplied.pricing = None
    else:
        supplied.pricing.pricing_model = None

    client = SuppliedEvidenceResearchClient([supplied])
    research = await ProviderResearchAgent(client).research(TASK)
    result = CostOptimizer().optimize(TASK, research)

    assert result.recommendation is None
    assert result.assessments[0].viable is False
    if pricing_kind == "missing":
        assert research.providers[0].price_estimate is None
        assert research.providers[0].pricing_source_url is None
    else:
        assert research.providers[0].pricing_model is None
    assert result.assessments[0].issues


@pytest.mark.asyncio
async def test_workflow_stops_without_sufficient_price_evidence() -> None:
    supplied = evidence("Alpha", 0.02)
    supplied.pricing = None

    class FakeParser:
        async def parse(self, raw_task: str) -> ParserResult:
            return ParserResult(
                is_ready_for_next_step=True, parsed_task=TASK, status=ParserStatus.COMPLETE
            )

    result = await SpendPilotWorkflow(
        WorkflowDependencies(
            parser=FakeParser(),
            researcher=ProviderResearchAgent(SuppliedEvidenceResearchClient([supplied])),
            optimizer=CostOptimizer(),
        )
    ).run("Process documents")

    assert result.status is WorkflowStatus.NO_RECOMMENDATION
    assert result.recommendation is None
    assert result.execution_result is None


def test_invalid_or_unsourced_price_cannot_enter_evidence_boundary() -> None:
    with pytest.raises(ValidationError):
        SourcedPricingEvidence.model_validate({"price_estimate": 10, "currency": "USD"})
    with pytest.raises(ValidationError):
        EvidenceSource(url="not-a-url", retrieved_at=SERVICE_TIME)
    with pytest.raises(ValidationError):
        EvidenceSource(url="https://example.com", retrieved_at=datetime(2026, 10, 24))
