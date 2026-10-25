"""Deterministic, evidence-based SP-103 provider cost comparison.

Only explicit one-time prices covering the requested quantity can be compared to
the current task budget: the shared task model has no budget period or unit.
This module performs no I/O and never authorizes a purchase.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field

from app.services.provider_research import ProviderRecord, ProviderResearchResult, ResearchStatus
from app.services.task_parser import ParsedTask
from app.services.workflow import OptimizerRecommendation

_TOTAL_PRICING_MODELS = {
    "total for requested quantity",
    "one-time total for requested quantity",
    "one time total for requested quantity",
    "fixed total for requested quantity",
}
_RECURRING = re.compile(
    r"(?:/\s*(?:day|week|month|year)|\b(?:daily|weekly|monthly|yearly|annual(?:ly)?|"
    r"per\s+(?:day|week|month|year))\b)",
    re.IGNORECASE,
)


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split())


class ProviderAssessment(BaseModel):
    """Comparison of one eligible provider and its documented evidence."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderRecord
    viable: bool
    estimated_total: Decimal | None = None
    issues: list[str] = Field(default_factory=list)
    rank: int | None = None


class CostOptimizationResult(BaseModel):
    """Detailed local result; recommendations are inputs to governance only."""

    model_config = ConfigDict(extra="forbid")

    recommendation: OptimizerRecommendation | None = None
    ranked_options: list[ProviderAssessment] = Field(default_factory=list)
    assessments: list[ProviderAssessment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CostOptimizer:
    """Compare eligible research results without network access or side effects."""

    async def recommend(
        self, task: ParsedTask, research: ProviderResearchResult
    ) -> OptimizerRecommendation | None:
        """Implement SP-004's CostOptimizerPort; use optimize() for full diagnostics."""

        return self.optimize(task, research).recommendation

    def optimize(
        self, task: ParsedTask, research: ProviderResearchResult
    ) -> CostOptimizationResult:
        """Rank justified candidates by comparable total cost and expose gaps."""

        if research.research_status not in {ResearchStatus.COMPLETE, ResearchStatus.PARTIAL}:
            return CostOptimizationResult(
                warnings=["Provider research is not available for cost comparison."]
            )

        assessments = [
            self._assess(task, provider) for provider in research.providers if provider.is_eligible
        ]
        viable = [assessment for assessment in assessments if assessment.viable]
        viable.sort(
            key=lambda item: (
                item.estimated_total if item.estimated_total is not None else Decimal("Infinity"),
                item.provider.provider_name.casefold(),
                item.provider.source_url,
            )
        )
        ranked = [item.model_copy(update={"rank": rank}) for rank, item in enumerate(viable, 1)]
        if not ranked:
            return CostOptimizationResult(
                assessments=assessments,
                warnings=["No eligible provider has enough comparable evidence to recommend."],
            )

        best = ranked[0]
        assert best.estimated_total is not None
        recommendation = OptimizerRecommendation(
            provider=best.provider,
            rationale=(
                f"Lowest supported one-time total: {best.estimated_total} "
                f"{best.provider.currency}. The stated quantity, quality target, and hard "
                "constraints have matching provider evidence. Subject to governance review."
            ),
            estimated_cost=float(best.estimated_total),
            currency=best.provider.currency,
            constraints_satisfied=True,
        )
        return CostOptimizationResult(
            recommendation=recommendation,
            ranked_options=ranked,
            assessments=assessments,
        )

    @staticmethod
    def _assess(task: ParsedTask, provider: ProviderRecord) -> ProviderAssessment:
        issues: list[str] = []
        estimated_total: Decimal | None = None

        if task.budget is None:
            issues.append("Task budget and currency are missing.")
        if task.ambiguities:
            issues.append("Task ambiguities must be resolved before comparison.")

        # A recurring budget cannot be compared: ParsedTask has no budget-period field.
        task_text = " ".join(
            [task.objective or "", task.expected_deliverable or "", *task.constraints]
        )
        if _RECURRING.search(task_text):
            issues.append("Recurring task or budget period cannot be compared as a task total.")

        pricing_model = _normalized(provider.pricing_model or "")
        if provider.price_estimate is None:
            issues.append("Provider price is missing.")
        elif pricing_model not in _TOTAL_PRICING_MODELS:
            issues.append(
                "Pricing model or period is unclear, or the total does not explicitly cover "
                "the requested quantity."
            )
        else:
            try:
                price = Decimal(str(provider.price_estimate))
                if not price.is_finite() or price < 0:
                    raise InvalidOperation
                estimated_total = price
            except InvalidOperation:
                issues.append("Provider price is not a finite, non-negative amount.")

        if not provider.currency:
            issues.append("Provider price currency is missing.")
        elif task.budget and provider.currency != task.budget.currency:
            issues.append("Provider currency differs from the task budget; no conversion was made.")

        if (
            task.budget
            and estimated_total is not None
            and provider.currency == task.budget.currency
        ):
            budget = Decimal(str(task.budget.amount))
            if not budget.is_finite() or budget <= 0:
                issues.append("Task budget is not a finite, positive amount.")
            elif estimated_total > budget:
                issues.append("Provider total exceeds the task budget.")

        if task.quantity is None:
            issues.append("Task quantity is missing.")
        elif not math.isfinite(task.quantity):
            issues.append("Task quantity must be finite.")
        elif provider.maximum_quantity is None:
            issues.append("Provider capacity for the requested quantity is unverified.")
        elif not math.isfinite(provider.maximum_quantity):
            issues.append("Provider capacity is not a finite documented quantity.")
        elif provider.maximum_quantity < task.quantity:
            issues.append("Provider capacity is below the requested quantity.")

        if not task.quality_target:
            issues.append("Task quality target is missing.")
        elif _normalized(task.quality_target) not in {
            _normalized(claim) for claim in provider.quality_claims
        }:
            issues.append("The requested quality target is not explicitly supported by a claim.")

        if not task.constraints:
            issues.append("Task hard constraints are missing or unverified.")
        provider_constraints = {_normalized(item) for item in provider.constraints}
        limitations = [_normalized(item) for item in provider.limitations]
        if task.quality_target and any(
            _normalized(task.quality_target) in limitation for limitation in limitations
        ):
            issues.append("Provider limitation may conflict with the requested quality target.")
        for constraint in task.constraints:
            normalized_constraint = _normalized(constraint)
            if normalized_constraint not in provider_constraints:
                issues.append(f"Constraint is unverified: {constraint}")
            if any(normalized_constraint in limitation for limitation in limitations):
                issues.append(f"Provider limitation may conflict with constraint: {constraint}")

        return ProviderAssessment(
            provider=provider,
            viable=not issues,
            estimated_total=estimated_total,
            issues=issues,
        )
