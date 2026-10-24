"""SP-101 natural-language task parsing.

The parser has one responsibility: turn untrusted natural-language task text
into validated planning data. It neither chooses a provider nor treats a budget
as authorization. All I/O is isolated behind ``StructuredTaskClient`` so the
domain parser remains straightforward to test and Developer 4 can call it from
their future FastAPI layer.
"""

from __future__ import annotations

import asyncio
import os
from enum import StrEnum
from typing import Any, Protocol, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ParserStatus(StrEnum):
    """Safe, stable outcomes for parser callers and orchestration."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    INVALID_MODEL_OUTPUT = "invalid_model_output"
    MODEL_REFUSED = "model_refused"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"


class FieldValidationError(BaseModel):
    """A validation problem that callers can display without parsing strings."""

    field: str
    code: str
    message: str


class Budget(BaseModel):
    """A requester's spending ceiling, not an authorization or reservation."""

    model_config = ConfigDict(extra="forbid")

    amount: float = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class ParsedTask(BaseModel):
    """Normalized facts explicitly supported by a task request.

    Fields are nullable so that the structured model can represent absence. The
    parser uses that distinction to ask questions instead of guessing values.
    """

    model_config = ConfigDict(extra="forbid")

    objective: str | None = None
    budget: Budget | None = None
    quantity: float | None = Field(default=None, gt=0)
    quality_target: str | None = None
    constraints: list[str] = Field(default_factory=list)
    deadline: str | None = None
    provider_preferences: list[str] = Field(default_factory=list)
    expected_deliverable: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator(
        "objective",
        "quality_target",
        "deadline",
        "expected_deliverable",
        mode="before",
    )
    @classmethod
    def empty_text_is_missing(cls, value: object) -> object:
        """Normalize blank extracted strings to missing rather than inventing data."""

        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("constraints", "provider_preferences", "assumptions", "ambiguities")
    @classmethod
    def remove_blank_list_values(cls, values: list[str]) -> list[str]:
        """Do not expose blank model artifacts as meaningful constraints."""

        return [value.strip() for value in values if value.strip()]


class ParserResult(BaseModel):
    """Stable handoff contract for governance, shopping, and orchestration."""

    model_config = ConfigDict(extra="forbid")

    is_ready_for_next_step: bool
    parsed_task: ParsedTask | None
    missing_fields: list[str] = Field(default_factory=list)
    validation_errors: list[FieldValidationError] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    status: ParserStatus


StructuredTask = TypeVar("StructuredTask", bound=BaseModel)


class StructuredTaskClient(Protocol):
    """Minimal injected interface for OpenAI or Azure OpenAI structured output."""

    async def parse_structured(
        self, *, raw_task: str, response_model: type[StructuredTask]
    ) -> StructuredTask | dict[str, Any]: ...


class ModelRefusalError(Exception):
    """Raised when the model refuses to return a structured task."""


class ModelUnavailableError(Exception):
    """Raised when the configured model service cannot be reached."""


class OpenAIStructuredTaskClient:
    """Thin official-SDK adapter supporting OpenAI and Azure OpenAI clients.

    The caller provides a configured SDK client. This keeps API keys and Azure
    endpoint details in Developer 4's approved environment configuration, not
    in parser code, test fixtures, logs, or returned data.
    """

    def __init__(self, client: Any, *, model: str) -> None:
        self._client = client
        self._model = model

    async def parse_structured(
        self, *, raw_task: str, response_model: type[StructuredTask]
    ) -> StructuredTask | dict[str, Any]:
        try:
            completion = await self._client.beta.chat.completions.parse(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract only facts stated in the task. Use null for missing scalar "
                            "fields and [] for missing lists. Never infer spending authorization, "
                            "provider names, quantities, budgets, or requirements."
                        ),
                    },
                    {"role": "user", "content": raw_task},
                ],
                response_format=response_model,
            )
        except TimeoutError:
            # Preserve the distinction so orchestration can offer a safe retry.
            raise
        except Exception as error:  # SDK/network failures are made safe at the boundary.
            raise ModelUnavailableError("The structured model service is unavailable.") from error

        message = completion.choices[0].message
        if getattr(message, "refusal", None):
            raise ModelRefusalError("The structured model refused this request.")
        if message.parsed is None:
            raise ModelRefusalError("The structured model returned no parsed task.")
        # The SDK exposes parsed structured output as Any; it is validated by
        # ParsedTask.model_validate in TaskParser before becoming public data.
        return cast(StructuredTask | dict[str, Any], message.parsed)


_REQUIRED_FIELDS = ("objective", "budget", "quantity", "quality_target", "constraints")
_MODEL_FIELDS = frozenset(ParsedTask.model_fields)
_QUESTIONS = {
    "objective": "What outcome should SpendPilot achieve?",
    "budget": "What is the maximum budget and ISO currency for this task?",
    "quantity": "What quantity or workload volume is required?",
    "quality_target": "What quality target or acceptance threshold is required?",
    "constraints": "What hard constraints must the task satisfy?",
}


def _validation_errors(error: ValidationError) -> list[FieldValidationError]:
    """Translate Pydantic details into the stable public result contract."""

    return [
        FieldValidationError(
            field=".".join(str(part) for part in issue["loc"]),
            code=str(issue["type"]),
            message=str(issue["msg"]),
        )
        for issue in error.errors()
    ]


class TaskParser:
    """Side-effect-free SP-101 parser service.

    The only possible external operation is the injected structured-model call.
    There are intentionally no database, payment, provider, storage, Jira, or
    Forge imports in this module.
    """

    def __init__(self, client: StructuredTaskClient) -> None:
        self._client = client

    async def parse(self, raw_task: str) -> ParserResult:
        """Return a validated, non-authorizing task specification."""

        if not raw_task or not raw_task.strip():
            return ParserResult(
                is_ready_for_next_step=False,
                parsed_task=None,
                missing_fields=list(_REQUIRED_FIELDS),
                validation_errors=[
                    FieldValidationError(
                        field="raw_task", code="required", message="A non-empty task is required."
                    )
                ],
                clarification_questions=[_QUESTIONS[field] for field in _REQUIRED_FIELDS],
                status=ParserStatus.INCOMPLETE,
            )

        try:
            proposal = await self._client.parse_structured(
                raw_task=raw_task.strip(), response_model=ParsedTask
            )
        except ModelRefusalError as error:
            return self._model_failure(ParserStatus.MODEL_REFUSED, str(error))
        except asyncio.TimeoutError:
            return self._model_failure(
                ParserStatus.MODEL_TIMEOUT, "The structured model request timed out."
            )
        except ModelUnavailableError as error:
            return self._model_failure(ParserStatus.MODEL_UNAVAILABLE, str(error))
        except Exception:
            return self._model_failure(
                ParserStatus.MODEL_UNAVAILABLE, "The structured model service is unavailable."
            )

        if isinstance(proposal, dict):
            absent_model_fields = sorted(_MODEL_FIELDS.difference(proposal))
            if absent_model_fields:
                return ParserResult(
                    is_ready_for_next_step=False,
                    parsed_task=None,
                    validation_errors=[
                        FieldValidationError(
                            field=field,
                            code="missing",
                            message="Structured model output omitted a required schema field.",
                        )
                        for field in absent_model_fields
                    ],
                    clarification_questions=[
                        "Please retry the request. No external action has been taken."
                    ],
                    status=ParserStatus.INVALID_MODEL_OUTPUT,
                )

        try:
            parsed_task = (
                proposal
                if isinstance(proposal, ParsedTask)
                else ParsedTask.model_validate(proposal)
            )
        except ValidationError as error:
            return ParserResult(
                is_ready_for_next_step=False,
                parsed_task=None,
                validation_errors=_validation_errors(error),
                clarification_questions=[
                    "Please restate the task with an objective, budget and ISO currency, quantity, "
                    "quality target, and hard constraints."
                ],
                status=ParserStatus.INVALID_MODEL_OUTPUT,
            )

        missing_fields = [
            field
            for field in _REQUIRED_FIELDS
            if (
                not parsed_task.constraints
                if field == "constraints"
                else getattr(parsed_task, field) is None
            )
        ]
        clarification_questions = [_QUESTIONS[field] for field in missing_fields]
        clarification_questions.extend(
            f"Please clarify: {item}" for item in parsed_task.ambiguities
        )
        is_ready = not missing_fields and not parsed_task.ambiguities
        return ParserResult(
            is_ready_for_next_step=is_ready,
            parsed_task=parsed_task,
            missing_fields=missing_fields,
            clarification_questions=clarification_questions,
            assumptions=parsed_task.assumptions,
            ambiguities=parsed_task.ambiguities,
            status=ParserStatus.COMPLETE if is_ready else ParserStatus.INCOMPLETE,
        )

    @staticmethod
    def _model_failure(status: ParserStatus, message: str) -> ParserResult:
        return ParserResult(
            is_ready_for_next_step=False,
            parsed_task=None,
            validation_errors=[
                FieldValidationError(field="raw_task", code=status, message=message)
            ],
            clarification_questions=[
                "Please retry the request. No external action has been taken."
            ],
            status=status,
        )


def configured_openai_client() -> OpenAIStructuredTaskClient:
    """Create an OpenAI SDK adapter from environment configuration only.

    This helper is intentionally not called by the parser. Developer 4 may use
    it at their composition root after setting ``OPENAI_API_KEY`` and optional
    ``OPENAI_TASK_PARSER_MODEL`` encrypted deployment variables.
    """

    from openai import AsyncOpenAI

    return OpenAIStructuredTaskClient(
        AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"]),
        model=os.environ.get("OPENAI_TASK_PARSER_MODEL", "gpt-4.1-mini"),
    )
