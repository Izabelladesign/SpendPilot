"""Monthly tier pricing tests using explicitly sourced local fixtures."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.services.cost_optimizer import CostOptimizationResult, CostOptimizer
from app.services.provider_evidence import (
    EvidenceSource,
    SourcedPricingEvidence,
    SourcedProviderEvidence,
    SuppliedEvidenceResearchClient,
)
from app.services.provider_research import (
    MonthlyPriceTier,
    ProviderResearchAgent,
    ProviderResearchResult,
)
from app.services.task_parser import Budget, ParsedTask

TIME = datetime(2026, 10, 24, 11, tzinfo=UTC)
TASK = ParsedTask(
    objective="Process documents",
    budget=Budget(amount=50, currency="USD"),
    quantity=100,
    quantity_unit="document",
    quality_target="95 percent accuracy",
    constraints=["EU data residency"],
)


def sourced_provider(name: str, prior: str = "0") -> SourcedProviderEvidence:
    return SourcedProviderEvidence(
        provider_name=name,
        service_description="Document processing service",
        source=EvidenceSource(url=f"https://{name.lower()}.example/service", retrieved_at=TIME),
        capabilities=["document processing"],
        constraints=["EU data residency"],
        quality_claims=["95 percent accuracy"],
        maximum_quantity=1000,
        monthly_usage_before=Decimal(prior),
        monthly_usage_source=EvidenceSource(
            url=f"https://{name.lower()}.example/account/usage", retrieved_at=TIME
        ),
        monthly_additional_charges=Decimal("0.25"),
        monthly_conditions_confirmed=True,
        pricing=SourcedPricingEvidence(
            source=EvidenceSource(
                url=f"https://{name.lower()}.example/pricing", retrieved_at=TIME
            ),
            currency="USD",
            pricing_model="monthly tiered usage",
            pricing_unit="document",
            billing_period="monthly",
            monthly_price_tiers=[
                MonthlyPriceTier(up_to=Decimal("1000"), price_per_unit=Decimal("0.01")),
                MonthlyPriceTier(up_to=None, price_per_unit=Decimal("0.02")),
            ],
        ),
    )


async def optimize(
    *items: SourcedProviderEvidence, task: ParsedTask = TASK
) -> tuple[ProviderResearchResult, CostOptimizationResult]:
    research = await ProviderResearchAgent(SuppliedEvidenceResearchClient(items)).research(task)
    return research, CostOptimizer().optimize(task, research)


@pytest.mark.asyncio
async def test_usage_within_one_tier_includes_explicit_additional_charges() -> None:
    research, result = await optimize(sourced_provider("Alpha", "20"))

    assert result.ranked_options[0].estimated_total == Decimal("1.25")
    assert result.recommendation is not None
    assert "monthly billing period" in result.recommendation.rationale
    assert "one-time" not in result.recommendation.rationale
    assert research.providers[0].monthly_usage_before == Decimal("20")
    assert research.providers[0].monthly_usage_retrieved_at == TIME


@pytest.mark.asyncio
async def test_usage_crossing_tier_boundary_charges_only_incremental_usage() -> None:
    _, result = await optimize(sourced_provider("Alpha", "950"))

    # 50 units at 0.01, 50 at 0.02, plus explicitly supplied charges.
    assert result.ranked_options[0].estimated_total == Decimal("1.75")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing, expected",
    [
        ("usage", "Prior monthly account usage is missing"),
        ("usage_source", "prior-usage source"),
        ("pricing_source", "pricing source URL"),
        ("additional_charges", "taxes and fees"),
        ("conditions", "billing conditions are not confirmed"),
    ],
)
async def test_missing_account_or_pricing_evidence_is_not_assumed(
    missing: str, expected: str
) -> None:
    item = sourced_provider("Alpha")
    if missing == "usage":
        item.monthly_usage_before = None
    elif missing == "usage_source":
        item.monthly_usage_source = None
    elif missing == "additional_charges":
        item.monthly_additional_charges = None
    elif missing == "conditions":
        item.monthly_conditions_confirmed = None

    record = item.to_provider_record()
    if missing == "pricing_source":
        record = record.model_copy(update={"pricing_source_url": None})
    assessment = CostOptimizer._assess(TASK, record)

    assert assessment.viable is False
    assert assessment.estimated_total is None
    assert expected in " ".join(assessment.issues)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tiers",
    [
        [],
        [MonthlyPriceTier(up_to=Decimal("1000"), price_per_unit=Decimal("0.01"))],
        [
            MonthlyPriceTier(up_to=Decimal("1000"), price_per_unit=Decimal("0.01")),
            MonthlyPriceTier(up_to=Decimal("500"), price_per_unit=Decimal("0.02")),
            MonthlyPriceTier(up_to=None, price_per_unit=Decimal("0.03")),
        ],
        [
            MonthlyPriceTier(up_to=None, price_per_unit=Decimal("0.01")),
            MonthlyPriceTier(up_to=None, price_per_unit=Decimal("0.02")),
        ],
    ],
)
async def test_invalid_or_incomplete_tier_schedule_is_not_recommended(
    tiers: list[MonthlyPriceTier],
) -> None:
    item = sourced_provider("Alpha")
    assert item.pricing is not None
    item.pricing.monthly_price_tiers = tiers
    assessment = CostOptimizer._assess(TASK, item.to_provider_record())

    assert assessment.viable is False
    assert assessment.estimated_total is None
    assert "tier" in " ".join(assessment.issues).lower()


def test_tier_upper_bound_and_prices_are_explicitly_validated() -> None:
    with pytest.raises(ValidationError):
        MonthlyPriceTier.model_validate({"price_per_unit": "0.01"})
    with pytest.raises(ValidationError):
        MonthlyPriceTier(up_to=None, price_per_unit=Decimal("-0.01"))


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["unit", "currency", "period"])
async def test_unit_currency_and_billing_period_must_match(mismatch: str) -> None:
    item = sourced_provider("Alpha")
    assert item.pricing is not None
    if mismatch == "unit":
        item.pricing.pricing_unit = "page"
    elif mismatch == "currency":
        item.pricing.currency = "EUR"
    else:
        item.pricing.billing_period = "yearly"

    _, result = await optimize(item)
    assert result.recommendation is None
    assert result.assessments[0].estimated_total is None


@pytest.mark.asyncio
async def test_over_budget_monthly_increment_is_not_recommended() -> None:
    task = TASK.model_copy(update={"budget": Budget(amount=1, currency="USD")})
    _, result = await optimize(sourced_provider("Alpha"), task=task)

    assert result.recommendation is None
    assert "exceeds the task budget" in " ".join(result.assessments[0].issues)


@pytest.mark.asyncio
async def test_two_sourced_monthly_providers_can_be_ranked() -> None:
    alpha = sourced_provider("Alpha", "950")
    beta = sourced_provider("Beta", "20")

    research, result = await optimize(alpha, beta)

    assert [item.provider.provider_name for item in result.ranked_options] == ["Beta", "Alpha"]
    assert [item.estimated_total for item in result.ranked_options] == [
        Decimal("1.25"), Decimal("1.75")
    ]
    assert research.providers[0].pricing_source_url == "https://alpha.example/pricing"
    assert research.providers[0].pricing_retrieved_at == TIME
    assert "https://alpha.example/account/usage" in research.source_urls


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["quality", "constraint"])
async def test_missing_requirement_evidence_prevents_recommendation(missing: str) -> None:
    item = sourced_provider("Alpha")
    if missing == "quality":
        item.quality_claims = []
    else:
        item.constraints = []

    _, result = await optimize(item)

    assert result.recommendation is None
    assert result.assessments[0].viable is False
