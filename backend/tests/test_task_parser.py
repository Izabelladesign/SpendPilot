"""Deterministic SP-101 tests: the model client is always a local fake."""

from typing import Any

import pytest

from app.services.task_parser import (
    ModelRefusalError,
    ModelUnavailableError,
    ParserStatus,
    TaskParser,
)


class FakeStructuredClient:
    """Captures the sole permitted parser interaction without any I/O."""

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[str] = []

    async def parse_structured(self, *, raw_task: str, response_model: type[Any]) -> Any:
        self.calls.append(raw_task)
        if self.error:
            raise self.error
        return self.response


COMPLETE_TASK = {
    "objective": "Process documents",
    "budget": {"amount": 50, "currency": "USD"},
    "quantity": 1000,
    "quality_target": "At least 95% accuracy",
    "constraints": ["Total cost must not exceed the budget"],
    "deadline": None,
    "provider_preferences": [],
    "expected_deliverable": "Processed documents with an accuracy report",
    "assumptions": [],
    "ambiguities": [],
    "confidence": 0.98,
}


@pytest.mark.asyncio
async def test_complete_request_produces_normalized_valid_task() -> None:
    client = FakeStructuredClient(COMPLETE_TASK)
    result = await TaskParser(client).parse(
        "Process 1,000 documents with at least 95% accuracy for under $50."
    )

    assert result.is_ready_for_next_step is True
    assert result.status is ParserStatus.COMPLETE
    assert result.parsed_task is not None
    assert result.parsed_task.quantity == 1000
    assert result.parsed_task.budget.currency == "USD"


@pytest.mark.asyncio
async def test_missing_required_fields_returns_questions() -> None:
    incomplete = {
        **COMPLETE_TASK,
        "objective": None,
        "budget": None,
        "quantity": None,
        "quality_target": None,
        "constraints": [],
    }
    result = await TaskParser(FakeStructuredClient(incomplete)).parse("Please help with this.")

    assert result.is_ready_for_next_step is False
    assert result.status is ParserStatus.INCOMPLETE
    assert result.missing_fields == [
        "objective",
        "budget",
        "quantity",
        "quality_target",
        "constraints",
    ]
    assert "ISO currency" in result.clarification_questions[1]


@pytest.mark.asyncio
async def test_ambiguous_requests_remain_unresolved() -> None:
    ambiguous = {
        **COMPLETE_TASK,
        "quantity": None,
        "ambiguities": ["It is unclear how many documents to process."],
    }
    result = await TaskParser(FakeStructuredClient(ambiguous)).parse(
        "Process documents for under $50."
    )

    assert result.is_ready_for_next_step is False
    assert result.parsed_task is not None
    assert result.parsed_task.quantity is None
    assert result.ambiguities == ["It is unclear how many documents to process."]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field, value",
    [
        ("quantity", 0),
        ("budget", {"amount": -1, "currency": "USD"}),
        ("budget", {"amount": 50, "currency": "US"}),
    ],
)
async def test_invalid_values_are_rejected(field: str, value: Any) -> None:
    invalid = {**COMPLETE_TASK, field: value}
    result = await TaskParser(FakeStructuredClient(invalid)).parse("Process documents.")

    assert result.is_ready_for_next_step is False
    assert result.status is ParserStatus.INVALID_MODEL_OUTPUT
    assert result.validation_errors


@pytest.mark.asyncio
async def test_malformed_structured_output_is_rejected_safely() -> None:
    result = await TaskParser(FakeStructuredClient({"objective": "Process documents"})).parse(
        "Process documents."
    )

    assert result.status is ParserStatus.INVALID_MODEL_OUTPUT
    assert result.parsed_task is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, expected_status",
    [
        (ModelRefusalError("Request refused"), ParserStatus.MODEL_REFUSED),
        (ModelUnavailableError("Service unavailable"), ParserStatus.MODEL_UNAVAILABLE),
        (TimeoutError(), ParserStatus.MODEL_TIMEOUT),
    ],
)
async def test_model_failures_are_safe(error: Exception, expected_status: ParserStatus) -> None:
    result = await TaskParser(FakeStructuredClient(error=error)).parse("Process documents.")

    assert result.is_ready_for_next_step is False
    assert result.status is expected_status
    assert "No external action" in result.clarification_questions[0]


@pytest.mark.asyncio
async def test_parser_has_no_database_payment_provider_storage_or_jira_side_effects() -> None:
    client = FakeStructuredClient(COMPLETE_TASK)
    result = await TaskParser(client).parse("Process 1,000 documents for under $50.")

    assert result.is_ready_for_next_step is True
    assert client.calls == ["Process 1,000 documents for under $50."]
    assert not hasattr(client, "database")
    assert not hasattr(client, "payment")
    assert not hasattr(client, "jira")
