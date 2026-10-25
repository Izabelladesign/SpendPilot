"""Deterministic SP-102 tests: all provider retrieval is a local fake."""

import asyncio
import json
from datetime import UTC, datetime
from email.message import Message
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from app.services.provider_research import (
    BrightDataSerpClient,
    ProviderResearchAgent,
    ResearchStatus,
    ResearchUnavailableError,
)
from app.services.task_parser import Budget, ParsedTask


class FakeResearchClient:
    """Captures the sole permitted SP-102 interaction without network I/O."""

    def __init__(self, records: list[Any] | None = None, error: Exception | None = None) -> None:
        self.records = records or []
        self.error = error
        self.calls: list[ParsedTask] = []

    async def find_providers(self, task: ParsedTask) -> list[Any]:
        self.calls.append(task)
        if self.error:
            raise self.error
        return self.records


TASK = ParsedTask(
    objective="Process documents",
    budget=Budget(amount=50, currency="USD"),
    quantity=1000,
    quality_target="95 percent accuracy",
    constraints=["EU data residency"],
)
TIMESTAMP = datetime(2026, 10, 24, 18, 0, tzinfo=UTC)


def provider(name: str, url: str, **overrides: Any) -> dict[str, Any]:
    return {
        "provider_name": name,
        "service_description": "Document processing service",
        "capabilities": ["document processing", "95 percent accuracy"],
        "pricing_model": "per document",
        "price_estimate": 25,
        "currency": "USD",
        "source_url": url,
        "retrieved_at": TIMESTAMP,
        "constraints": ["EU data residency"],
        "limitations": [],
        "quality_claims": ["95 percent accuracy"],
        "maximum_quantity": 5000,
        "confidence": 0.9,
        **overrides,
    }


@pytest.mark.asyncio
async def test_two_suitable_providers_are_normalized_with_sources_and_timestamps() -> None:
    client = FakeResearchClient(
        [
            provider("Alpha", "https://alpha.example/pricing"),
            provider("Beta", "https://beta.example/pricing"),
        ]
    )
    result = await ProviderResearchAgent(client).research(TASK)

    assert result.research_status is ResearchStatus.COMPLETE
    assert len(result.providers) == 2
    assert all(item.is_eligible for item in result.providers)
    assert result.source_urls == ["https://alpha.example/pricing", "https://beta.example/pricing"]
    assert result.retrieved_at == TIMESTAMP


@pytest.mark.asyncio
async def test_missing_price_or_capabilities_is_flagged() -> None:
    result = await ProviderResearchAgent(
        FakeResearchClient(
            [
                provider(
                    "Incomplete",
                    "https://incomplete.example",
                    price_estimate=None,
                    currency=None,
                    capabilities=[],
                )
            ]
        )
    ).research(TASK)

    warnings = result.providers[0].compatibility_warnings
    assert result.providers[0].is_eligible is False
    assert any("pricing" in warning for warning in warnings)
    assert any("capabilities" in warning for warning in warnings)


@pytest.mark.asyncio
async def test_hard_constraint_violation_is_ineligible() -> None:
    result = await ProviderResearchAgent(
        FakeResearchClient(
            [
                provider(
                    "Conflict",
                    "https://conflict.example",
                    limitations=["Does not support EU data residency"],
                )
            ]
        )
    ).research(TASK)

    assert result.research_status is ResearchStatus.NO_SUITABLE_PROVIDERS
    assert result.providers[0].is_eligible is False
    assert any(
        "conflicts with hard constraint" in warning
        for warning in result.providers[0].compatibility_warnings
    )


@pytest.mark.asyncio
async def test_no_providers_returns_safe_result_and_question() -> None:
    result = await ProviderResearchAgent(FakeResearchClient()).research(TASK)

    assert result.research_status is ResearchStatus.NO_SUITABLE_PROVIDERS
    assert result.providers == []
    assert result.clarification_questions


@pytest.mark.asyncio
async def test_malformed_retrieval_data_is_rejected_safely() -> None:
    result = await ProviderResearchAgent(
        FakeResearchClient([{"provider_name": "Broken"}])
    ).research(TASK)

    assert result.research_status is ResearchStatus.INVALID_RETRIEVAL_DATA
    assert result.providers == []
    assert "malformed" in result.warnings[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, status",
    [
        (ResearchUnavailableError("Retrieval unavailable"), ResearchStatus.RESEARCH_UNAVAILABLE),
        (asyncio.TimeoutError(), ResearchStatus.RESEARCH_TIMEOUT),
    ],
)
async def test_research_failure_and_timeout_are_safe(
    error: Exception, status: ResearchStatus
) -> None:
    result = await ProviderResearchAgent(FakeResearchClient(error=error)).research(TASK)

    assert result.research_status is status
    assert result.providers == []
    assert "No external action" in result.clarification_questions[0]


@pytest.mark.asyncio
async def test_bright_data_expect_element_failure_is_safe_and_not_retried() -> None:
    """A live 502 must be surfaced safely without consuming more retrieval credits."""

    client = FakeResearchClient(
        error=ResearchUnavailableError("Bright Data returned HTTP 502 (expect_element).")
    )
    result = await ProviderResearchAgent(client).research(TASK)

    assert result.research_status is ResearchStatus.RESEARCH_UNAVAILABLE
    assert result.providers == []
    assert result.warnings == ["Bright Data returned HTTP 502 (expect_element)."]
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_bright_data_client_normalizes_mocked_body_wrapped_serp_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The concrete client makes one injected request and returns public evidence only."""

    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "test-key-not-a-real-secret")
    monkeypatch.setenv("BRIGHT_DATA_SERP_ZONE", "test-zone")
    requests: list[Request] = []

    def request_once(request: Request, timeout: float) -> tuple[int, bytes, dict[str, str]]:
        requests.append(request)
        assert timeout > 0
        serp_body = {
            "organic": [
                {
                    "title": "Acme Document API",
                    "link": "https://acme.example/pricing",
                    "snippet": "Document processing API with pricing details",
                }
            ]
        }
        body = {
            "status_code": 200,
            "headers": {"content-type": "application/json"},
            "body": json.dumps(serp_body),
        }
        return (
            200,
            json.dumps(body).encode("utf-8"),
            {},
        )

    result = await ProviderResearchAgent(
        BrightDataSerpClient(request_once=request_once)
    ).research(TASK)

    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].full_url == "https://api.brightdata.com/request"
    request_payload = json.loads(requests[0].data.decode("utf-8"))
    assert request_payload == {
        "zone": "test-zone",
        "url": "https://www.google.com/search?q=Process+documents+provider+pricing",
        "format": "json",
        "data_format": "parsed_light",
    }
    assert result.providers[0].provider_name == "Acme Document API"
    assert result.providers[0].source_url == "https://acme.example/pricing"
    assert result.providers[0].price_estimate is None
    assert result.source_urls == ["https://acme.example/pricing"]


def _raise_bright_data_502() -> tuple[int, bytes, dict[str, str]]:
    headers = Message()
    headers["x-brd-error-code"] = "expect_element"
    raise HTTPError(
        "https://api.brightdata.com/request",
        502,
        "Bad Gateway",
        headers,
        None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_once, expected_warning",
    [
        (
            # ``Message`` mirrors the HTTP header container supplied by urllib.
            lambda _request, _timeout: _raise_bright_data_502(),
            "HTTP 502 (expect_element)",
        ),
        (
            lambda _request, _timeout: (_ for _ in ()).throw(TimeoutError()),
            "unavailable or timed out",
        ),
        (
            lambda _request, _timeout: (200, b"not-json", {}),
            "malformed results",
        ),
    ],
)
async def test_bright_data_failures_are_safe_and_make_no_retry(
    monkeypatch: pytest.MonkeyPatch,
    request_once: Any,
    expected_warning: str,
) -> None:
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "test-key-not-a-real-secret")
    monkeypatch.setenv("BRIGHT_DATA_SERP_ZONE", "test-zone")
    calls = 0

    def counted_request(request: Request, timeout: float) -> tuple[int, bytes, dict[str, str]]:
        nonlocal calls
        calls += 1
        return request_once(request, timeout)

    result = await ProviderResearchAgent(
        BrightDataSerpClient(request_once=counted_request)
    ).research(TASK)

    assert result.research_status is ResearchStatus.RESEARCH_UNAVAILABLE
    assert expected_warning in result.warnings[0]
    assert calls == 1


@pytest.mark.asyncio
async def test_research_has_no_payment_database_jira_or_order_side_effects() -> None:
    client = FakeResearchClient([provider("Alpha", "https://alpha.example/pricing")])
    result = await ProviderResearchAgent(client).research(TASK)

    assert client.calls == [TASK]
    assert result.providers[0].provider_name == "Alpha"
    assert not hasattr(client, "database")
    assert not hasattr(client, "payment")
    assert not hasattr(client, "jira")
