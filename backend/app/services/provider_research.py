"""SP-102 provider research normalization and compatibility checks.

This service accepts only a validated SP-101 ``ParsedTask`` and untrusted
provider data from an injected client. It normalizes evidence for later cost
optimization and governance; it never selects a provider or takes an action.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.services.task_parser import ParsedTask


class ResearchStatus(StrEnum):
    """Stable outcomes for research callers."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    NO_SUITABLE_PROVIDERS = "no_suitable_providers"
    INVALID_RETRIEVAL_DATA = "invalid_retrieval_data"
    RESEARCH_UNAVAILABLE = "research_unavailable"
    RESEARCH_TIMEOUT = "research_timeout"
    INCOMPLETE_TASK = "incomplete_task"


class MonthlyPriceTier(BaseModel):
    """Marginal per-unit price through an exclusive cumulative upper bound."""

    model_config = ConfigDict(extra="forbid")

    up_to: Decimal | None = Field(gt=0, allow_inf_nan=False)
    price_per_unit: Decimal = Field(ge=0, allow_inf_nan=False)


class ProviderRecord(BaseModel):
    """Normalized public provider evidence, not a purchase recommendation."""

    model_config = ConfigDict(extra="forbid")

    provider_name: str = Field(min_length=1)
    service_description: str = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    pricing_model: str | None = None
    pricing_unit: str | None = None
    billing_period: str | None = None
    monthly_price_tiers: list[MonthlyPriceTier] = Field(default_factory=list)
    monthly_usage_before: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    monthly_usage_source_url: str | None = None
    monthly_usage_retrieved_at: datetime | None = None
    monthly_additional_charges: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    monthly_conditions_confirmed: bool | None = Field(default=None, strict=True)
    price_estimate: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    source_url: str
    retrieved_at: datetime
    pricing_source_url: str | None = None
    pricing_retrieved_at: datetime | None = None
    constraints: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    quality_claims: list[str] = Field(default_factory=list)
    maximum_quantity: float | None = Field(default=None, gt=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    is_eligible: bool = False
    compatibility_warnings: list[str] = Field(default_factory=list)

    @field_validator("source_url", "pricing_source_url", "monthly_usage_source_url")
    @classmethod
    def source_url_must_be_public_http(cls, value: str | None) -> str | None:
        """Require a source reference without fetching or trusting its content."""

        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an absolute HTTP(S) URL")
        return value

    @field_validator("retrieved_at", "pricing_retrieved_at", "monthly_usage_retrieved_at")
    @classmethod
    def retrieval_time_must_include_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("retrieved_at must include a timezone")
        return value

    @field_validator("capabilities", "constraints", "limitations", "quality_claims", mode="after")
    @classmethod
    def normalize_text_lists(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]


class ProviderResearchResult(BaseModel):
    """SP-102 handoff to SP-103 and Developer 2; it never picks a winner."""

    model_config = ConfigDict(extra="forbid")

    providers: list[ProviderRecord] = Field(default_factory=list)
    research_status: ResearchStatus
    source_urls: list[str] = Field(default_factory=list)
    retrieved_at: datetime
    warnings: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)


class ResearchClient(Protocol):
    """Retrieval boundary for Bright Data, Apify, or a future public-data client."""

    async def find_providers(self, task: ParsedTask) -> list[ProviderRecord | dict[str, Any]]: ...


class ResearchUnavailableError(Exception):
    """Raised when the injected provider-retrieval service is unavailable."""


BrightDataRequest = Callable[[Request, float], tuple[int, bytes, Mapping[str, str]]]

_BRIGHT_DATA_SERP_ENDPOINT = "https://api.brightdata.com/request"
_BRIGHT_DATA_TIMEOUT_SECONDS = 20.0


def _send_bright_data_request_once(
    request: Request, timeout: float
) -> tuple[int, bytes, Mapping[str, str]]:
    """Send one HTTP request, without retries, polling, or diagnostic logging."""

    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS endpoint
        return (
            response.status,
            response.read(),
            {str(key).lower(): str(value) for key, value in response.headers.items()},
        )


class BrightDataSerpClient:
    """Explicit, one-request Bright Data SERP implementation of ``ResearchClient``.

    Credentials are read only when research is invoked. The adapter never runs at
    import time or application startup, never retries, and converts remote
    failures into ``ResearchUnavailableError`` so callers cannot mistake a
    retrieval failure for provider evidence.
    """

    def __init__(
        self,
        *,
        request_once: BrightDataRequest = _send_bright_data_request_once,
        timeout_seconds: float = _BRIGHT_DATA_TIMEOUT_SECONDS,
    ) -> None:
        self._request_once = request_once
        self._timeout_seconds = timeout_seconds

    async def find_providers(self, task: ParsedTask) -> list[dict[str, Any]]:
        """Retrieve one SERP response and normalize public result evidence.

        This is the only method that can issue a Bright Data request. It reads
        ``BRIGHT_DATA_API_KEY`` and ``BRIGHT_DATA_SERP_ZONE`` from the local
        environment; neither value is returned, logged, or retained in results.
        """

        api_key = os.getenv("BRIGHT_DATA_API_KEY")
        zone = os.getenv("BRIGHT_DATA_SERP_ZONE")
        if not api_key or not zone:
            raise ResearchUnavailableError(
                "Bright Data is not configured. Set BRIGHT_DATA_API_KEY and "
                "BRIGHT_DATA_SERP_ZONE locally before explicitly invoking research."
            )

        query = self._build_query(task)
        google_search_url = f"https://www.google.com/search?{urlencode({'q': query})}"
        request = Request(
            _BRIGHT_DATA_SERP_ENDPOINT,
            data=json.dumps(
                {
                    "zone": zone,
                    "url": google_search_url,
                    "format": "json",
                    "data_format": "parsed_light",
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            status, body, _headers = await asyncio.to_thread(
                self._request_once, request, self._timeout_seconds
            )
        except HTTPError as error:
            error_code = error.headers.get("x-brd-error-code") if error.headers else None
            detail = f" ({error_code})" if error_code else ""
            raise ResearchUnavailableError(
                f"Bright Data returned HTTP {error.code}{detail}; no retry was attempted."
            ) from None
        except (TimeoutError, URLError, OSError):
            raise ResearchUnavailableError(
                "Bright Data research is unavailable or timed out; no retry was attempted."
            ) from None

        if status < 200 or status >= 300:
            raise ResearchUnavailableError(
                f"Bright Data returned HTTP {status}; no retry was attempted."
            )

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ResearchUnavailableError(
                "Bright Data returned malformed results; no retry was attempted."
            ) from None

        return self._normalize_results(payload)

    @staticmethod
    def _build_query(task: ParsedTask) -> str:
        """Build a bounded search query from task facts, without inventing requirements."""

        parts = [task.objective or ""]
        if task.expected_deliverable:
            parts.append(task.expected_deliverable)
        parts.extend(task.provider_preferences)
        parts.append("provider pricing")
        return " ".join(part.strip() for part in parts if part.strip())[:500]

    @staticmethod
    def _normalize_results(payload: object) -> list[dict[str, Any]]:
        """Extract only result fields published by the SERP response as untrusted data."""

        items = BrightDataSerpClient._find_result_items(payload)
        if items is None:
            raise ResearchUnavailableError(
                "Bright Data returned malformed results; no retry was attempted."
            )

        retrieved_at = datetime.now(UTC)
        normalized: list[dict[str, Any]] = []
        for item in items:
            title_value = item.get("title") or item.get("name")
            source_url_value = item.get("url") or item.get("link")
            description_value = item.get("description") or item.get("snippet") or title_value
            if not (
                isinstance(title_value, str)
                and isinstance(source_url_value, str)
                and isinstance(description_value, str)
                and title_value.strip()
                and source_url_value.strip()
                and description_value.strip()
            ):
                continue
            title = title_value.strip()
            source_url = source_url_value.strip()
            description = description_value.strip()
            parsed_url = urlparse(source_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                continue
            normalized.append(
                {
                    "provider_name": title,
                    "service_description": description,
                    "capabilities": [description],
                    "pricing_model": None,
                    "price_estimate": None,
                    "currency": None,
                    "source_url": source_url,
                    "retrieved_at": retrieved_at,
                    "constraints": [],
                    "limitations": [],
                    "quality_claims": [],
                    "maximum_quantity": None,
                    "confidence": None,
                }
            )

        if items and not normalized:
            raise ResearchUnavailableError(
                "Bright Data returned malformed provider results; no retry was attempted."
            )
        return normalized

    @staticmethod
    def _find_result_items(payload: object) -> list[Mapping[str, Any]] | None:
        """Locate known SERP result lists without treating response text as instructions."""

        if isinstance(payload, list):
            for entry in payload:
                found = BrightDataSerpClient._find_result_items(entry)
                if found is not None:
                    return found
            return []
        if not isinstance(payload, Mapping):
            return None

        for key in ("organic", "organic_results", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
        for key in ("body", "response", "data", "multi"):
            if key in payload:
                nested_payload = payload[key]
                if key == "body" and isinstance(nested_payload, str):
                    try:
                        nested_payload = json.loads(nested_payload)
                    except json.JSONDecodeError:
                        return None
                found = BrightDataSerpClient._find_result_items(nested_payload)
                if found is not None:
                    return found
        return None


_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


def _tokens(value: str) -> set[str]:
    """Create conservative comparison tokens; web content is always data, not instructions."""

    return set(_TOKEN_RE.findall(value.lower()))


def _mentions_hard_constraint(task_constraint: str, limitation: str) -> bool:
    constraint_tokens = _tokens(task_constraint)
    limitation_tokens = _tokens(limitation)
    negative_words = {"cannot", "does", "not", "unsupported", "exclude", "prohibit", "without"}
    return (
        bool(constraint_tokens)
        and constraint_tokens.issubset(limitation_tokens)
        and bool(negative_words.intersection(limitation_tokens))
    )


class ProviderResearchAgent:
    """Side-effect-free provider research coordinator.

    The injected client is the only possible I/O path. This service has no
    imports for payment, persistence, Jira, Forge, storage, or ordering.
    """

    def __init__(self, client: ResearchClient) -> None:
        self._client = client

    async def research(self, task: ParsedTask) -> ProviderResearchResult:
        """Normalize provider evidence and identify basic non-authorizing compatibility."""

        missing_information, clarification_questions = self._task_gaps(task)
        now = datetime.now(UTC)
        if missing_information:
            return ProviderResearchResult(
                research_status=ResearchStatus.INCOMPLETE_TASK,
                retrieved_at=now,
                missing_information=missing_information,
                clarification_questions=clarification_questions,
                warnings=[
                    "Provider research was not started because task requirements are incomplete."
                ],
            )

        try:
            raw_records = await self._client.find_providers(task)
        except asyncio.TimeoutError:
            return self._failure(ResearchStatus.RESEARCH_TIMEOUT, "Provider research timed out.")
        except ResearchUnavailableError as error:
            return self._failure(ResearchStatus.RESEARCH_UNAVAILABLE, str(error))
        except Exception:
            return self._failure(
                ResearchStatus.RESEARCH_UNAVAILABLE, "Provider research is unavailable."
            )

        valid_records: list[ProviderRecord] = []
        warnings: list[str] = []
        for index, raw_record in enumerate(raw_records):
            try:
                record = (
                    raw_record
                    if isinstance(raw_record, ProviderRecord)
                    else ProviderRecord.model_validate(raw_record)
                )
            except ValidationError:
                warnings.append(f"Retrieved provider record {index + 1} was malformed and ignored.")
                continue
            valid_records.append(self._evaluate_compatibility(record, task))

        if not valid_records:
            status = (
                ResearchStatus.INVALID_RETRIEVAL_DATA
                if raw_records
                else ResearchStatus.NO_SUITABLE_PROVIDERS
            )
            return ProviderResearchResult(
                research_status=status,
                retrieved_at=now,
                warnings=warnings or ["No provider records were returned for this task."],
                clarification_questions=[
                    "Please clarify provider requirements or broaden the allowed "
                    "provider constraints."
                ],
            )

        eligible_count = sum(record.is_eligible for record in valid_records)
        if eligible_count == 0:
            status = ResearchStatus.NO_SUITABLE_PROVIDERS
            warnings.append(
                "No retrieved provider is compatible with the task's stated hard constraints."
            )
        elif eligible_count < 2:
            status = ResearchStatus.PARTIAL
            warnings.append(
                "Fewer than two suitable providers were available from the retrieved data."
            )
        elif warnings:
            status = ResearchStatus.PARTIAL
        else:
            status = ResearchStatus.COMPLETE

        source_urls = list(
            dict.fromkeys(
                url
                for record in valid_records
                for url in (
                    record.source_url,
                    record.pricing_source_url,
                    record.monthly_usage_source_url,
                )
                if url is not None
            )
        )
        return ProviderResearchResult(
            providers=valid_records,
            research_status=status,
            source_urls=source_urls,
            retrieved_at=max(
                timestamp
                for record in valid_records
                for timestamp in (
                    record.retrieved_at,
                    record.pricing_retrieved_at,
                    record.monthly_usage_retrieved_at,
                )
                if timestamp is not None
            ),
            warnings=warnings,
        )

    @staticmethod
    def _task_gaps(task: ParsedTask) -> tuple[list[str], list[str]]:
        gaps: list[tuple[str, str]] = []
        if task.objective is None:
            gaps.append(("objective", "What outcome should the provider help achieve?"))
        if task.quantity is None:
            gaps.append(("quantity", "What quantity or workload must the provider support?"))
        if task.quality_target is None:
            gaps.append(("quality_target", "What quality target must the provider meet?"))
        if not task.constraints:
            gaps.append(("constraints", "What hard constraints must providers satisfy?"))
        return [gap[0] for gap in gaps], [gap[1] for gap in gaps]

    @staticmethod
    def _failure(status: ResearchStatus, warning: str) -> ProviderResearchResult:
        return ProviderResearchResult(
            research_status=status,
            retrieved_at=datetime.now(UTC),
            warnings=[warning],
            clarification_questions=[
                "Please retry provider research. No external action has been taken."
            ],
        )

    @staticmethod
    def _evaluate_compatibility(record: ProviderRecord, task: ParsedTask) -> ProviderRecord:
        warnings: list[str] = []
        eligible = True

        if not record.capabilities:
            warnings.append("Provider capabilities were not supplied and cannot be verified.")
            eligible = False
        elif task.objective:
            objective_tokens = _tokens(task.objective)
            capability_tokens = _tokens(
                " ".join(record.capabilities + [record.service_description])
            )
            if objective_tokens and not objective_tokens.intersection(capability_tokens):
                warnings.append("Provider capabilities do not clearly match the stated objective.")

        has_monthly_tiers = (
            (record.pricing_model or "").strip().casefold() == "monthly tiered usage"
            and bool(record.monthly_price_tiers)
        )
        if (record.price_estimate is None and not has_monthly_tiers) or record.currency is None:
            warnings.append("Provider pricing or currency is unavailable.")
        elif (
            record.price_estimate is not None
            and not has_monthly_tiers
            and task.budget
            and record.currency == task.budget.currency
        ):
            if record.price_estimate > task.budget.amount:
                warnings.append("Provider price estimate exceeds the task budget.")
                eligible = False
        elif task.budget and record.currency != task.budget.currency:
            warnings.append(
                "Provider currency differs from the task budget and cannot be compared."
            )

        if task.quantity and record.maximum_quantity and record.maximum_quantity < task.quantity:
            warnings.append("Provider maximum quantity is below the requested quantity.")
            eligible = False

        if task.quality_target:
            quality_tokens = _tokens(task.quality_target)
            claim_tokens = _tokens(" ".join(record.quality_claims))
            if quality_tokens and not quality_tokens.intersection(claim_tokens):
                warnings.append(
                    "Provider quality claims do not verify the requested quality target."
                )

        for constraint in task.constraints:
            if any(_mentions_hard_constraint(constraint, limit) for limit in record.limitations):
                warnings.append(f"Provider limitation conflicts with hard constraint: {constraint}")
                eligible = False

        return record.model_copy(
            update={"is_eligible": eligible, "compatibility_warnings": warnings}
        )
