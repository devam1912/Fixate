"""Custom explicit state machine orchestrator loop connecting all 5 agents."""

import os
import uuid
import logging
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field

from fixate.graph.builder import CodebaseGraphBuilder
from fixate.localization.agent import FailureLocalizationAgent, LocalizationResult, SuspectFunction
from fixate.rag.agent import CodeRAGAgent, RAGContext
from fixate.patch.agent import PatchGeneratorAgent
from fixate.patch.schema import GeneratedPatch
from fixate.verification.agent import VerificationAgent, VerificationResult
from fixate.telemetry.logger import TelemetryLogger, AgentTelemetryEvent
from fixate.safety.approval import HumanApprovalChecker, RiskAssessment
from fixate.llm.base import BaseLLMProvider
from fixate.llm.factory import get_llm_provider

logger = logging.getLogger(__name__)


class OrchestrationState(str, Enum):
    IDLE = "IDLE"
    LOCALIZING = "LOCALIZING"
    RETRIEVING = "RETRIEVING"
    PATCHING = "PATCHING"
    VERIFYING = "VERIFYING"
    CHECKING_SAFETY = "CHECKING_SAFETY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PENDING_APPROVAL = "PENDING_APPROVAL"


class OrchestrationSummary(BaseModel):
    incident_id: str
    state: OrchestrationState
    failing_test: str
    exception_type: str
    target_file: Optional[str] = None
    suspect_function: Optional[str] = None
    verified_patch: Optional[GeneratedPatch] = None
    risk_assessment: Optional[RiskAssessment] = None
    total_attempts: int = 0
    failure_report: Optional[str] = None
    telemetry_events: List[AgentTelemetryEvent] = Field(default_factory=list)


class OrchestrationEngine:
    """Master agent state machine orchestrating Localize -> Retrieve -> Patch -> Verify -> Safety Check."""

    def __init__(
        self,
        telemetry_logger: Optional[TelemetryLogger] = None,
        llm_provider: Optional[BaseLLMProvider] = None,
    ):
        self.telemetry = telemetry_logger or TelemetryLogger()
        self.llm = llm_provider or get_llm_provider()
        self.safety_checker = HumanApprovalChecker()

    def run_self_healing_pipeline(
        self,
        repo_dir: str,
        pytest_log: str,
        human_approval_required: bool = True,
    ) -> OrchestrationSummary:
        """Execute the end-to-end self-healing CI pipeline.
        
        Args:
            repo_dir: Absolute path to target codebase repository.
            pytest_log: Raw pytest failure output log.
            human_approval_required: If True, halts high-risk patches for explicit human gate sign-off.
            
        Returns:
            OrchestrationSummary object containing complete incident audit trail and outcome.
        """
        incident_id = f"inc_{uuid.uuid4().hex[:8]}"
        logger.info(f"=== Starting Incident Self-Healing Pipeline: {incident_id} ===")

        # 1. Initialize Codebase Graph
        graph_builder = CodebaseGraphBuilder()
        graph_builder.build_from_directory(repo_dir)

        # State 1: LOCALIZING
        self.telemetry.log_event(
            incident_id, "Orchestrator", "STATE_TRANSITION", "IDLE", "LOCALIZING", "IN_PROGRESS"
        )
        localizer = FailureLocalizationAgent(graph_builder=graph_builder, llm_provider=self.llm)
        loc_res: LocalizationResult = localizer.localize_failure(pytest_log)

        self.telemetry.log_event(
            incident_id,
            "LocalizationAgent",
            "LOCALIZE_ROOT_CAUSE",
            f"Traceback: {loc_res.exception_type}",
            f"Suspects: {[s.name for s in loc_res.suspect_functions]}",
            "SUCCESS",
            details=loc_res.model_dump(),
        )

        if not loc_res.suspect_functions:
            self.telemetry.log_event(
                incident_id, "Orchestrator", "FAIL", "Localization", "No suspect functions found", "FAILURE"
            )
            return OrchestrationSummary(
                incident_id=incident_id,
                state=OrchestrationState.FAILED,
                failing_test=loc_res.failing_test,
                exception_type=loc_res.exception_type,
                failure_report="Localization failed: No candidate root cause functions identified via graph.",
            )

        top_suspect: SuspectFunction = loc_res.suspect_functions[0]

        # State 2: RETRIEVING
        self.telemetry.log_event(
            incident_id, "Orchestrator", "STATE_TRANSITION", "LOCALIZING", "RETRIEVING", "IN_PROGRESS"
        )
        rag_agent = CodeRAGAgent()
        rag_agent.index_repository(repo_dir)
        rag_context: RAGContext = rag_agent.retrieve_context_for_suspect(top_suspect, localizer.parser.parse_log(pytest_log))

        self.telemetry.log_event(
            incident_id,
            "CodeRAGAgent",
            "RETRIEVE_CONTEXT",
            f"Suspect: {top_suspect.name}",
            f"Code Chunks: {len(rag_context.related_code_chunks)}, Past Fixes: {len(rag_context.past_fixes)}",
            "SUCCESS",
        )

        # State 3 & 4: PATCHING & VERIFYING
        self.telemetry.log_event(
            incident_id, "Orchestrator", "STATE_TRANSITION", "RETRIEVING", "VERIFYING", "IN_PROGRESS"
        )
        patch_agent = PatchGeneratorAgent(llm_provider=self.llm)
        ver_agent = VerificationAgent(patch_agent=patch_agent, max_attempts=3)

        past_diffs = [f.applied_diff for f in rag_context.past_fixes]
        ver_res: VerificationResult = ver_agent.verify_fix(
            repo_dir=repo_dir,
            graph_builder=graph_builder,
            suspect=top_suspect,
            failure=localizer.parser.parse_log(pytest_log),
            past_fix_examples=past_diffs,
        )

        self.telemetry.log_event(
            incident_id,
            "VerificationAgent",
            "VERIFY_PATCH_SANDBOX",
            f"Attempts: {ver_res.total_attempts}",
            f"Outcome: {'PASSED' if ver_res.success else 'FAILED'}",
            "SUCCESS" if ver_res.success else "FAILURE",
            details={"total_attempts": ver_res.total_attempts},
        )

        if not ver_res.success or ver_res.verified_patch is None:
            self.telemetry.log_event(
                incident_id, "Orchestrator", "FAIL", "Verification", "Sandboxed tests failed after 3 attempts", "FAILURE"
            )
            return OrchestrationSummary(
                incident_id=incident_id,
                state=OrchestrationState.FAILED,
                failing_test=loc_res.failing_test,
                exception_type=loc_res.exception_type,
                target_file=top_suspect.file_path,
                suspect_function=top_suspect.name,
                total_attempts=ver_res.total_attempts,
                failure_report=ver_res.failure_report,
                telemetry_events=self.telemetry.get_incident_events(incident_id),
            )

        verified_patch: GeneratedPatch = ver_res.verified_patch

        # Record successful fix in Fix History Store for future RAG retrieval
        rag_agent.fix_history.record_fix(
            exception_type=loc_res.exception_type,
            exception_message=loc_res.exception_message,
            failing_symbol=top_suspect.symbol_id,
            applied_diff=verified_patch.unified_diff,
        )

        # State 5: CHECKING_SAFETY
        self.telemetry.log_event(
            incident_id, "Orchestrator", "STATE_TRANSITION", "VERIFYING", "CHECKING_SAFETY", "IN_PROGRESS"
        )
        risk: RiskAssessment = self.safety_checker.evaluate_patch_risk(
            verified_patch.target_file, top_suspect.name, verified_patch.unified_diff
        )

        final_state = OrchestrationState.COMPLETED
        if risk.is_risky and human_approval_required:
            final_state = OrchestrationState.PENDING_APPROVAL
            self.telemetry.log_event(
                incident_id,
                "HumanApprovalChecker",
                "SAFETY_GATE_TRIGGERED",
                f"Risk: {risk.risk_level}",
                risk.reason,
                "REQUIRES_APPROVAL",
            )
        else:
            self.telemetry.log_event(
                incident_id,
                "HumanApprovalChecker",
                "AUTO_APPLY_APPROVED",
                f"Risk: {risk.risk_level}",
                risk.reason,
                "SUCCESS",
            )

        events = self.telemetry.get_incident_events(incident_id)

        return OrchestrationSummary(
            incident_id=incident_id,
            state=final_state,
            failing_test=loc_res.failing_test,
            exception_type=loc_res.exception_type,
            target_file=top_suspect.file_path,
            suspect_function=top_suspect.name,
            verified_patch=verified_patch,
            risk_assessment=risk,
            total_attempts=ver_res.total_attempts,
            failure_report=None,
            telemetry_events=events,
        )
