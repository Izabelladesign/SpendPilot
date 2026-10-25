"""Normalize explicitly supplied provider evidence for SP-102 and SP-103.

This boundary performs no retrieval or independent fact verification. Its
caller supplies source references and observed facts; absent facts stay absent.
Search-result snippets are not promoted into pricing or requirement evidence.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.provider_research import MonthlyPriceTier, ProviderRecord
from app.services.task_parser import ParsedTask


class EvidenceSource(BaseModel):
    """A source and the time its contents were inspected, supplied by the caller."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    retrieved_at: datetime

    @field_validator("url")
    @classmethod
    def require_http_source(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Evidence source must be an absolute HTTP(S) URL")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Evidence retrieval time must include a timezone")
        return value


class SourcedPricingEvidence(BaseModel):
    """Price facts explicitly supported by the cited source; unknowns remain null."""

    model_config = ConfigDict(extra="forbid")

    source: EvidenceSource
    price_estimate: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    pricing_model: str | None = None
    pricing_unit: str | None = None
    billing_period: str | None = None
    monthly_price_tiers: list[MonthlyPriceTier] = Field(default_factory=list)


class SourcedProviderEvidence(BaseModel):
    """Caller-attested service facts and, optionally, separately sourced price facts."""

    model_config = ConfigDict(extra="forbid")

    provider_name: str = Field(min_length=1)
    service_description: str = Field(min_length=1)
    source: EvidenceSource
    capabilities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    quality_claims: list[str] = Field(default_factory=list)
    maximum_quantity: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    # Account-specific usage must be supplied by the caller, not the price page.
    monthly_usage_before: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    monthly_usage_source: EvidenceSource | None = None
    # Total task-specific tax and fees, explicitly known even when zero.
    monthly_additional_charges: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    # Caller attests the cited tier schedule applies to this account and task
    # within the same billing period, with no other unmodeled charges.
    monthly_conditions_confirmed: bool | None = Field(default=None, strict=True)
    pricing: SourcedPricingEvidence | None = None

    def to_provider_record(self) -> ProviderRecord:
        """Copy only supplied facts; SP-102 separately evaluates eligibility."""

        pricing = self.pricing
        return ProviderRecord(
            provider_name=self.provider_name,
            service_description=self.service_description,
            capabilities=self.capabilities,
            constraints=self.constraints,
            limitations=self.limitations,
            quality_claims=self.quality_claims,
            maximum_quantity=self.maximum_quantity,
            source_url=self.source.url,
            retrieved_at=self.source.retrieved_at,
            price_estimate=pricing.price_estimate if pricing else None,
            currency=pricing.currency if pricing else None,
            pricing_model=pricing.pricing_model if pricing else None,
            pricing_unit=pricing.pricing_unit if pricing else None,
            billing_period=pricing.billing_period if pricing else None,
            monthly_price_tiers=pricing.monthly_price_tiers if pricing else [],
            monthly_usage_before=self.monthly_usage_before,
            monthly_usage_source_url=(
                self.monthly_usage_source.url if self.monthly_usage_source else None
            ),
            monthly_usage_retrieved_at=(
                self.monthly_usage_source.retrieved_at if self.monthly_usage_source else None
            ),
            monthly_additional_charges=self.monthly_additional_charges,
            monthly_conditions_confirmed=self.monthly_conditions_confirmed,
            pricing_source_url=pricing.source.url if pricing else None,
            pricing_retrieved_at=pricing.source.retrieved_at if pricing else None,
        )


class SuppliedEvidenceResearchClient:
    """In-memory ResearchClient for evidence collected explicitly by a caller."""

    def __init__(self, evidence: Sequence[SourcedProviderEvidence]) -> None:
        self._evidence = tuple(evidence)

    async def find_providers(self, task: ParsedTask) -> list[ProviderRecord | dict[str, Any]]:
        """Return cited facts without contacting any provider or model service."""

        del task
        return [item.to_provider_record() for item in self._evidence]
