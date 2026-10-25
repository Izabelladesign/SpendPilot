"""SP-004 approval-gated SpendPilot workflow orchestration.

The graph composes injected domain services only. It does not construct an LLM
or retrieval client, invoke Developer 2's payment service, persist state, or
write Jira/Forge data. A real integration must be supplied at a composition
root by its owning team.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.policy_engine import Decision, PolicyResult
from app.services.provider_research import ProviderRecord, ProviderResearchResult, ResearchStatus
from app.services.task_parser import ParsedTask, ParserResult


class WorkflowStatus(StrEnum):
    """Terminal workflow statuses; none imply payment authorization."""

    CLARIFICATION_NEEDED = "clarification_needed"
    RESEARCH_UNAVAILABLE = "research_unavailable"
    NO_RECOMMENDATION = "no_recommendation"
    AWAITING_GOVERNANCE_APPROVAL = "awaiting_governance_approval"
    REJECTED = "rejected"
    FAILED = "failed"
    COMPLETE = "complete"


class ApprovalStatus(StrEnum):
    """The only approval source is Developer 2's explicit PolicyResult."""

    NOT_REQUESTED = "not_requested"
    AWAITING = "awaiting"
    APPROVED = "approved"
    DENIED = "denied"


class ExecutionStatus(StrEnum):
    """Execution is deliberately a stub until an approved integration exists."""

    NOT_STARTED = "not_started"
    STUBBED = "stubbed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class VerificationStatus(StrEnum):
    """Verification is deliberately a stub until an approved integration exists."""

    NOT_STARTED = "not_started"
    STUBBED = "stubbed"
    VERIFIED = "verified"
    FAILED = "failed"


class SafeWorkflowError(BaseModel):
    """Display-safe orchestration failure; never includes secrets or raw exceptions."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class OptimizerRecommendation(BaseModel):
    """A candidate for governance review, never a provider selection or authorization."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderRecord
    rationale: str = Field(min_length=1)
    estimated_cost: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    constraints_satisfied: bool = False


class ExecutionResult(BaseModel):
    """Non-financial execution result supplied by an injected integration or safe stub."""

    model_config = ConfigDict(extra="forbid")

    status: ExecutionStatus
    message: str
    output_reference: str | None = None


class VerificationResult(BaseModel):
    """Outcome verification supplied by an injected integration or safe stub."""

    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus
    message: str


class WorkflowState(TypedDict, total=False):
    """Explicit typed LangGraph state shared by all workflow nodes."""

    raw_request: str
    parser_result: ParserResult
    parsed_task: ParsedTask
    research_result: ProviderResearchResult
    recommendation: OptimizerRecommendation
    governance_decision: PolicyResult
    approval_status: ApprovalStatus
    execution_result: ExecutionResult
    verification_result: VerificationResult
    warnings: list[str]
    safe_error: SafeWorkflowError
    terminal_status: WorkflowStatus


class TaskParserPort(Protocol):
    async def parse(self, raw_task: str) -> ParserResult: ...


class ProviderResearchPort(Protocol):
    async def research(self, task: ParsedTask) -> ProviderResearchResult: ...


class CostOptimizerPort(Protocol):
    async def recommend(
        self, task: ParsedTask, research: ProviderResearchResult
    ) -> OptimizerRecommendation | None: ...


class GovernanceApprovalPort(Protocol):
    """Developer 2 adapter; it returns a policy result but never executes payment here."""

    async def get_decision(
        self, task: ParsedTask, recommendation: OptimizerRecommendation
    ) -> PolicyResult | None: ...


class ProviderExecutionPort(Protocol):
    async def execute(
        self, task: ParsedTask, recommendation: OptimizerRecommendation
    ) -> ExecutionResult: ...


class CompletionVerificationPort(Protocol):
    async def verify(
        self,
        task: ParsedTask,
        recommendation: OptimizerRecommendation,
        execution: ExecutionResult,
    ) -> VerificationResult: ...


class SafeStubExecutor:
    """Pure in-memory default: it never contacts providers, carts, or payment tools."""

    async def execute(
        self, task: ParsedTask, recommendation: OptimizerRecommendation
    ) -> ExecutionResult:
        del task, recommendation
        return ExecutionResult(
            status=ExecutionStatus.STUBBED,
            message="Provider execution is not configured; no provider action was taken.",
        )


class SafeStubVerifier:
    """Pure in-memory default: it never asserts a real outcome was verified."""

    async def verify(
        self,
        task: ParsedTask,
        recommendation: OptimizerRecommendation,
        execution: ExecutionResult,
    ) -> VerificationResult:
        del task, recommendation, execution
        return VerificationResult(
            status=VerificationStatus.STUBBED,
            message="Outcome verification is not configured; no outcome was verified.",
        )


@dataclass(frozen=True)
class WorkflowDependencies:
    """All potential external work is explicit and injected by a composition root."""

    parser: TaskParserPort
    researcher: ProviderResearchPort
    optimizer: CostOptimizerPort
    governance: GovernanceApprovalPort | None = None
    executor: ProviderExecutionPort = SafeStubExecutor()
    verifier: CompletionVerificationPort = SafeStubVerifier()


class WorkflowResult(BaseModel):
    """Stable result returned to Developer 4; it does not persist or update Jira."""

    model_config = ConfigDict(extra="forbid")

    status: WorkflowStatus
    parsed_task: ParsedTask | None = None
    research_result: ProviderResearchResult | None = None
    recommendation: OptimizerRecommendation | None = None
    approval_status: ApprovalStatus
    execution_result: ExecutionResult | None = None
    verification_result: VerificationResult | None = None
    warnings: list[str] = Field(default_factory=list)
    safe_error: SafeWorkflowError | None = None


class SpendPilotWorkflow:
    """Typed LangGraph implementation of the non-authorizing SP-004 flow."""

    def __init__(self, dependencies: WorkflowDependencies) -> None:
        self._dependencies = dependencies
        self._graph = self._build_graph()

    async def run(self, raw_request: str) -> WorkflowResult:
        """Run the graph using only explicitly injected collaborators."""

        output = await self._graph.ainvoke(
            {
                "raw_request": raw_request,
                "approval_status": ApprovalStatus.NOT_REQUESTED,
                "warnings": [],
            }
        )
        return WorkflowResult(
            status=output["terminal_status"],
            parsed_task=output.get("parsed_task"),
            research_result=output.get("research_result"),
            recommendation=output.get("recommendation"),
            approval_status=output.get("approval_status", ApprovalStatus.NOT_REQUESTED),
            execution_result=output.get("execution_result"),
            verification_result=output.get("verification_result"),
            warnings=output.get("warnings", []),
            safe_error=output.get("safe_error"),
        )

    def _build_graph(
        self,
    ) -> CompiledStateGraph[WorkflowState, None, WorkflowState, WorkflowState]:
        graph = StateGraph(WorkflowState)
        graph.add_node("parse_request", self._parse_request)
        graph.add_node("research_providers", self._research_providers)
        graph.add_node("optimize_cost", self._optimize_cost)
        graph.add_node("await_governance_approval", self._await_governance_approval)
        graph.add_node("execute_selected_provider", self._execute_selected_provider)
        graph.add_node("verify_completion", self._verify_completion)
        graph.add_node("clarification_needed", self._clarification_needed)
        graph.add_node("research_unavailable", self._research_unavailable)
        graph.add_node("no_recommendation", self._no_recommendation)
        graph.add_node("rejected", self._rejected)
        graph.add_node("failed", self._failed)
        graph.add_node("complete", self._complete)

        graph.add_edge(START, "parse_request")
        graph.add_conditional_edges(
            "parse_request",
            self._after_parse,
            {
                "research_providers": "research_providers",
                "clarification_needed": "clarification_needed",
            },
        )
        graph.add_conditional_edges(
            "research_providers",
            self._after_research,
            {
                "optimize_cost": "optimize_cost",
                "research_unavailable": "research_unavailable",
                "no_recommendation": "no_recommendation",
            },
        )
        graph.add_conditional_edges(
            "optimize_cost",
            self._after_optimization,
            {
                "await_governance_approval": "await_governance_approval",
                "no_recommendation": "no_recommendation",
            },
        )
        graph.add_conditional_edges(
            "await_governance_approval",
            self._after_approval,
            {
                "awaiting": END,
                "execute_selected_provider": "execute_selected_provider",
                "rejected": "rejected",
            },
        )
        graph.add_conditional_edges(
            "execute_selected_provider",
            self._after_execution,
            {"verify_completion": "verify_completion", "failed": "failed"},
        )
        graph.add_edge("verify_completion", "complete")
        for terminal_node in (
            "clarification_needed",
            "research_unavailable",
            "no_recommendation",
            "rejected",
            "failed",
            "complete",
        ):
            graph.add_edge(terminal_node, END)
        return cast(
            CompiledStateGraph[WorkflowState, None, WorkflowState, WorkflowState], graph.compile()
        )

    async def _parse_request(self, state: WorkflowState) -> dict[str, object]:
        try:
            result = await self._dependencies.parser.parse(state["raw_request"])
        except Exception:
            return {
                "safe_error": SafeWorkflowError(
                    code="parser_unavailable", message="Task parsing is unavailable."
                )
            }
        return {"parser_result": result, "parsed_task": result.parsed_task}

    @staticmethod
    def _after_parse(state: WorkflowState) -> str:
        result = state.get("parser_result")
        if result is None or not result.is_ready_for_next_step or result.parsed_task is None:
            return "clarification_needed"
        return "research_providers"

    async def _research_providers(self, state: WorkflowState) -> dict[str, object]:
        try:
            result = await self._dependencies.researcher.research(state["parsed_task"])
        except Exception:
            return {
                "safe_error": SafeWorkflowError(
                    code="research_unavailable", message="Provider research is unavailable."
                )
            }
        return {"research_result": result}

    @staticmethod
    def _after_research(state: WorkflowState) -> str:
        error = state.get("safe_error")
        if error and error.code == "research_unavailable":
            return "research_unavailable"
        result = state.get("research_result")
        if result is None or result.research_status in {
            ResearchStatus.RESEARCH_UNAVAILABLE,
            ResearchStatus.RESEARCH_TIMEOUT,
            ResearchStatus.INVALID_RETRIEVAL_DATA,
        }:
            return "research_unavailable"
        if result.research_status is ResearchStatus.NO_SUITABLE_PROVIDERS or not any(
            provider.is_eligible for provider in result.providers
        ):
            return "no_recommendation"
        return "optimize_cost"

    async def _optimize_cost(self, state: WorkflowState) -> dict[str, object]:
        try:
            recommendation = await self._dependencies.optimizer.recommend(
                state["parsed_task"], state["research_result"]
            )
        except (ValidationError, Exception):
            return {
                "safe_error": SafeWorkflowError(
                    code="optimizer_unavailable", message="Cost optimization is unavailable."
                )
            }
        return {"recommendation": recommendation} if recommendation else {}

    @staticmethod
    def _after_optimization(state: WorkflowState) -> str:
        recommendation = state.get("recommendation")
        if recommendation is None or not recommendation.constraints_satisfied:
            return "no_recommendation"
        return "await_governance_approval"

    async def _await_governance_approval(self, state: WorkflowState) -> dict[str, object]:
        if self._dependencies.governance is None:
            return {
                "approval_status": ApprovalStatus.AWAITING,
                "terminal_status": WorkflowStatus.AWAITING_GOVERNANCE_APPROVAL,
                "warnings": state.get("warnings", [])
                + ["No explicit governance decision was supplied; workflow is paused."],
            }
        try:
            decision = await self._dependencies.governance.get_decision(
                state["parsed_task"], state["recommendation"]
            )
        except Exception:
            return {
                "approval_status": ApprovalStatus.AWAITING,
                "terminal_status": WorkflowStatus.AWAITING_GOVERNANCE_APPROVAL,
                "warnings": state.get("warnings", [])
                + ["Governance decision is unavailable; workflow is paused."],
            }
        if decision is None or decision.decision is Decision.REVIEW_REQUIRED:
            return {
                "approval_status": ApprovalStatus.AWAITING,
                "governance_decision": decision,
                "terminal_status": WorkflowStatus.AWAITING_GOVERNANCE_APPROVAL,
            }
        if decision.decision is Decision.DENIED:
            return {"approval_status": ApprovalStatus.DENIED, "governance_decision": decision}
        if decision.decision is Decision.APPROVED:
            return {"approval_status": ApprovalStatus.APPROVED, "governance_decision": decision}
        return {
            "approval_status": ApprovalStatus.AWAITING,
            "terminal_status": WorkflowStatus.AWAITING_GOVERNANCE_APPROVAL,
            "warnings": state.get("warnings", [])
            + ["Governance returned an unrecognized decision; workflow is paused."],
        }

    @staticmethod
    def _after_approval(state: WorkflowState) -> str:
        if state.get("approval_status") is ApprovalStatus.APPROVED:
            return "execute_selected_provider"
        if state.get("approval_status") is ApprovalStatus.DENIED:
            return "rejected"
        return "awaiting"

    async def _execute_selected_provider(self, state: WorkflowState) -> dict[str, object]:
        try:
            result = await self._dependencies.executor.execute(
                state["parsed_task"], state["recommendation"]
            )
        except Exception:
            return {
                "execution_result": ExecutionResult(
                    status=ExecutionStatus.FAILED, message="Provider execution failed safely."
                ),
                "safe_error": SafeWorkflowError(
                    code="execution_failed", message="Provider execution failed safely."
                ),
            }
        return {"execution_result": result}

    @staticmethod
    def _after_execution(state: WorkflowState) -> str:
        result = state.get("execution_result")
        if result is None or result.status is ExecutionStatus.FAILED:
            return "failed"
        return "verify_completion"

    async def _verify_completion(self, state: WorkflowState) -> dict[str, object]:
        try:
            result = await self._dependencies.verifier.verify(
                state["parsed_task"], state["recommendation"], state["execution_result"]
            )
        except Exception:
            return {
                "verification_result": VerificationResult(
                    status=VerificationStatus.FAILED, message="Outcome verification failed safely."
                ),
                "safe_error": SafeWorkflowError(
                    code="verification_failed", message="Outcome verification failed safely."
                ),
            }
        return {"verification_result": result}

    @staticmethod
    def _clarification_needed(state: WorkflowState) -> dict[str, object]:
        return {"terminal_status": WorkflowStatus.CLARIFICATION_NEEDED}

    @staticmethod
    def _research_unavailable(state: WorkflowState) -> dict[str, object]:
        return {"terminal_status": WorkflowStatus.RESEARCH_UNAVAILABLE}

    @staticmethod
    def _no_recommendation(state: WorkflowState) -> dict[str, object]:
        return {"terminal_status": WorkflowStatus.NO_RECOMMENDATION}

    @staticmethod
    def _rejected(state: WorkflowState) -> dict[str, object]:
        return {"terminal_status": WorkflowStatus.REJECTED}

    @staticmethod
    def _failed(state: WorkflowState) -> dict[str, object]:
        return {"terminal_status": WorkflowStatus.FAILED}

    @staticmethod
    def _complete(state: WorkflowState) -> dict[str, object]:
        warnings = state.get("warnings", [])
        execution = state.get("execution_result")
        verification = state.get("verification_result")
        if execution and execution.status is ExecutionStatus.STUBBED:
            warnings = warnings + [execution.message]
        if verification and verification.status is VerificationStatus.STUBBED:
            warnings = warnings + [verification.message]
        return {"terminal_status": WorkflowStatus.COMPLETE, "warnings": warnings}
