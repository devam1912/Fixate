"""The self-healing state machine.

Runs the five stages in order, emitting a telemetry event at every transition so
the dashboard can render progress live, and converting any stage failure into a
FAILED summary carrying an operator-facing explanation.

Stage ordering is deliberate: localization and retrieval run *before* the LLM
availability check, even though patch generation is what needs the model. An
incident with no model configured still tells the operator which symbol is
implicated and why, which is most of the diagnostic value, instead of refusing at
the door. The pipeline stops honestly at the first stage that genuinely cannot
proceed -- it never substitutes invented output to reach a terminal state.
"""

import logging
import os
import uuid
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from fixate.errors import LocalizationError, PipelineError
from fixate.graph.builder import CodebaseGraphBuilder
from fixate.languages import registry
from fixate.languages.base import LanguageToolchain
from fixate.languages.diagnostics import is_vendored, select_gate
from fixate.llm.base import BaseLLMProvider
from fixate.llm.factory import get_llm_provider
from fixate.localization.agent import FailureLocalizationAgent, LocalizationResult, SuspectFunction
from fixate.localization.parser import FailureTracebackParser, ParsedFailure
from fixate.patch.agent import PatchGeneratorAgent
from fixate.patch.schema import GeneratedPatch
from fixate.rag.agent import CodeRAGAgent, RAGContext
from fixate.safety import RiskAssessment, SafetyChecker
from fixate.telemetry import TelemetryEvent, TelemetryLogger, TelemetryTracker
from fixate.verification.agent import VerificationAgent, VerificationResult
from fixate.verification.oracles import DiagnosticGateOracle

logger = logging.getLogger(__name__)

MAX_VERIFICATION_ATTEMPTS = 3


class OrchestrationState(str, Enum):
    IDLE = "IDLE"
    LOCALIZING = "LOCALIZING"
    RETRIEVING = "RETRIEVING"
    PATCHING = "PATCHING"
    VERIFYING = "VERIFYING"
    CHECKING_SAFETY = "CHECKING_SAFETY"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class OrchestrationSummary(BaseModel):
    """Terminal report for one incident. Consumed directly by the dashboard."""

    incident_id: str
    state: OrchestrationState
    language: Optional[str] = None
    #: What had to pass for a patch to be accepted -- the test suite, or the
    #: checker used when a repository has none. Without this the summary reads as
    #: though tests ran even when none exist.
    verified_by: Optional[str] = None
    failing_test: Optional[str] = None
    exception_type: Optional[str] = None
    target_file: Optional[str] = None
    suspect_function: Optional[str] = None
    verified_patch: Optional[GeneratedPatch] = None
    risk_assessment: Optional[RiskAssessment] = None
    total_attempts: int = 0
    failure_report: Optional[str] = None
    telemetry_events: List[TelemetryEvent] = Field(default_factory=list)


class OrchestrationEngine:
    """Drives one incident through localization, retrieval, repair, and sign-off."""

    def __init__(
        self,
        llm_provider: Optional[BaseLLMProvider] = None,
        telemetry_logger: Optional[TelemetryLogger] = None,
    ):
        self.llm = llm_provider or get_llm_provider()
        self.telemetry = telemetry_logger or TelemetryTracker()
        self.safety_checker = SafetyChecker()
        self.parser = FailureTracebackParser()

    def run_self_healing_pipeline(
        self,
        repo_dir: str,
        pytest_log: str,
        human_approval_required: bool = True,
        custom_env: Optional[Dict[str, str]] = None,
        incident_id: Optional[str] = None,
    ) -> OrchestrationSummary:
        """Run one incident end to end and return its terminal summary.

        An ``incident_id`` may be supplied so a caller can hand it to a client
        before the run begins; the client then subscribes to the telemetry stream
        and sees every stage, rather than only the terminal summary.
        """
        incident_id = incident_id or f"inc_{uuid.uuid4().hex[:8]}"
        logger.info("=== Incident %s starting (provider: %s) ===", incident_id, self.llm.name)

        failure: Optional[ParsedFailure] = None
        localization: Optional[LocalizationResult] = None
        language: Optional[str] = None

        try:
            failure, localization, graph_builder, toolchain = self._localize(
                incident_id, repo_dir, pytest_log
            )
            language = toolchain.name
            suspect = localization.suspect_functions[0]

            context, rag_agent = self._retrieve(incident_id, repo_dir, suspect, failure)

            verification = self._repair(
                incident_id=incident_id,
                repo_dir=repo_dir,
                suspect=suspect,
                failure=failure,
                context=context,
                graph_builder=graph_builder,
                toolchain=toolchain,
                custom_env=custom_env,
            )

            if not verification.success or verification.verified_patch is None:
                return self._failed(
                    incident_id,
                    failure=failure,
                    suspect=suspect,
                    report=verification.failure_report
                    or "Verification did not produce a passing patch.",
                    attempts=verification.total_attempts,
                    language=language,
                    verified_by=self._oracle_description(),
                )

            return self._sign_off(
                incident_id=incident_id,
                failure=failure,
                suspect=suspect,
                verification=verification,
                rag_agent=rag_agent,
                human_approval_required=human_approval_required,
                language=language,
            )

        except PipelineError as exc:
            logger.warning("Incident %s halted during %s: %s", incident_id, exc.stage, exc.message)
            self.telemetry.log_event(
                incident_id,
                "Orchestrator",
                "PIPELINE_HALTED",
                exc.stage,
                exc.message,
                "FAILURE",
                details={"stage": exc.stage, "remedy": exc.remedy or ""},
            )
            suspect = localization.suspect_functions[0] if localization and localization.suspect_functions else None
            return self._failed(
                incident_id, failure=failure, suspect=suspect, report=exc.report(), language=language
            )

        except Exception as exc:
            logger.exception("Incident %s crashed unexpectedly.", incident_id)
            self.telemetry.log_event(
                incident_id, "Orchestrator", "PIPELINE_CRASHED", "unexpected error", str(exc), "FAILURE"
            )
            return self._failed(
                incident_id,
                failure=failure,
                suspect=None,
                report=f"The pipeline stopped on an unexpected error: {exc}",
                language=language,
            )

    def _localize(
        self, incident_id: str, repo_dir: str, pytest_log: str
    ) -> tuple[ParsedFailure, LocalizationResult, CodebaseGraphBuilder, LanguageToolchain]:
        """Stage 1: identify the language, parse the failure, rank candidates."""
        self._transition(incident_id, OrchestrationState.IDLE, OrchestrationState.LOCALIZING)

        # The failing log names the runner that actually broke, which is what makes
        # a mixed-language repository tractable: one repo, but one language per
        # incident.
        toolchain = registry.resolve(repo_dir, log=pytest_log)
        if toolchain is None:
            raise LocalizationError(
                "Could not determine which language this failure belongs to. The log "
                "matched no supported test runner, and the repository contains no "
                "recognizable Python or JavaScript/TypeScript project.",
                remedy=(
                    "Supply the output of pytest, Jest, or Vitest. Other runners are "
                    "not yet supported."
                ),
            )

        # A repository with no runnable tests still has objective signals. Rather
        # than refusing outright, fall back to a checker that reports a concrete,
        # located defect -- and keep it as the oracle that must later pass.
        self._gate_oracle = None
        if not toolchain.has_test_setup(repo_dir) or toolchain.collected_nothing(pytest_log):
            failure = self._failure_from_gate(incident_id, repo_dir, toolchain)
        else:
            failure = toolchain.parse_failure(pytest_log)
            # A failure located inside an installed dependency is not this
            # repository's defect, and the runner crashing inside its own source
            # is not a defect at all. Either way there is nothing here to repair,
            # so fall back to a checker that reports on the repository itself
            # rather than hunting for a suspect that cannot exist.
            if not self._failure_is_in_repo(failure, repo_dir):
                logger.info(
                    "The reported failure points outside %s (%s); falling back to a "
                    "diagnostic gate.",
                    repo_dir,
                    failure.failing_file,
                )
                failure = self._failure_from_gate(incident_id, repo_dir, toolchain)

        graph_builder = CodebaseGraphBuilder()
        graph_builder.build_from_directory(repo_dir)

        localizer = FailureLocalizationAgent(graph_builder=graph_builder, llm_provider=self.llm)
        try:
            result = localizer.localize_parsed_failure(failure)
        except LocalizationError:
            # A file with a syntax error yields no AST symbols, so the graph is
            # empty exactly when the syntax gate has the most to say. The gate has
            # already pinpointed the file and line, which is all localization was
            # going to establish, so use that directly instead of failing.
            result = self._suspect_from_diagnostic(repo_dir, failure)
            if result is None:
                raise

        top = result.suspect_functions[0]

        self.telemetry.log_event(
            incident_id,
            "FailureLocalizationAgent",
            "LOCALIZE_ROOT_CAUSE",
            f"{failure.exception_type} in {failure.test_name}",
            f"{top.name} ({top.file_path}) via {result.ranking_source} ranking",
            "SUCCESS",
            details={
                "language": toolchain.name,
                "ranking_source": result.ranking_source,
                "suspects": [s.model_dump() for s in result.suspect_functions],
            },
        )
        return failure, result, graph_builder, toolchain

    @staticmethod
    def _failure_is_in_repo(failure: ParsedFailure, repo_dir: str) -> bool:
        """Whether the failure names a file belonging to the repository's own source.

        Two ways a frame can be disqualified, and both were observed in
        production: it sits under a vendored tree (``node_modules``, a venv, the
        npx download cache), or it is simply somewhere else on the filesystem
        entirely. A frame that is merely relative is assumed to be in-repo --
        runners print repository-relative paths routinely.
        """
        candidates = [failure.failing_file] + [f.file_path for f in failure.stack_frames]
        resolved_repo = os.path.realpath(repo_dir)

        for candidate in candidates:
            if not candidate:
                continue
            path = candidate.split(":")[0] if not os.path.isabs(candidate) else candidate
            if is_vendored(path):
                continue
            if not os.path.isabs(path):
                return True
            try:
                if os.path.commonpath([os.path.realpath(path), resolved_repo]) == resolved_repo:
                    return True
            except ValueError:
                # Different drives on Windows; definitively not inside the repo.
                continue
        return False

    def _oracle_description(self) -> str:
        """Describe what had to hold for a patch to be accepted."""
        oracle = getattr(self, "_gate_oracle", None)
        return oracle.describe() if oracle is not None else "the failing test passes"

    def _suspect_from_diagnostic(
        self, repo_dir: str, failure: ParsedFailure
    ) -> Optional[LocalizationResult]:
        """Build a suspect straight from a gate's file-and-line report.

        Used only when graph ranking found nothing, which happens precisely when
        the defect prevents the file from parsing. Returns None if the reported
        file cannot be read, so the caller can surface the original error.
        """
        if getattr(self, "_gate_oracle", None) is None or not failure.failing_file:
            return None

        path = failure.failing_file
        if not os.path.isabs(path):
            path = os.path.join(repo_dir, failure.failing_file)
        if not os.path.exists(path):
            return None

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                source = handle.read()
        except OSError:
            return None

        relative = os.path.relpath(path, repo_dir).replace("\\", "/")
        suspect = SuspectFunction(
            symbol_id=f"{relative}::<file>",
            file_path=path,
            name=os.path.basename(relative),
            code=source,
            rank=1,
            plausibility_reason=(
                f"Reported directly by the {self._gate_oracle.gate.name} gate at "
                f"{relative}:{failure.failing_line} -- {failure.exception_message}. "
                f"The file does not parse, so no call graph could be built from it."
            ),
            ranking_source="diagnostic",
            evidence=[f"{self._gate_oracle.gate.name} diagnostic at line {failure.failing_line}"],
        )
        logger.info("Localized directly from the gate diagnostic: %s", relative)

        return LocalizationResult(
            failing_test=failure.test_name,
            exception_type=failure.exception_type,
            exception_message=failure.exception_message,
            suspect_functions=[suspect],
            ranking_source="diagnostic",
        )

    def _failure_from_gate(
        self, incident_id: str, repo_dir: str, toolchain: LanguageToolchain
    ) -> ParsedFailure:
        """Derive a failure from a diagnostic gate when there is no test suite.

        Gates are tried most-conclusive first: a file that does not parse is
        definitely broken, while a lint violation is a much weaker claim. The
        selected gate becomes the verification oracle, so the same checker that
        found the problem is the one that must later agree it is gone.
        """
        selection = select_gate(toolchain.diagnostic_gates(), repo_dir)
        if selection is None:
            raise LocalizationError(
                "This repository has no runnable tests, and every available checker "
                "reports it as clean -- it parses, and no lint or type errors were "
                "found. There is no defect for the engine to act on.",
                remedy=(
                    "Paste a real failure (a production traceback or stack trace) into "
                    "the error-log field, or add a test that reproduces the bug."
                ),
            )

        gate, diagnostics = selection
        target = diagnostics[0]
        self._gate_oracle = DiagnosticGateOracle(
            gate=gate, baseline=diagnostics, target=target
        )

        self.telemetry.log_event(
            incident_id,
            "DiagnosticGate",
            "GATE_FALLBACK_SELECTED",
            "no runnable tests in this repository",
            f"{gate.name} reported {len(diagnostics)} diagnostic(s); targeting {target.describe()}",
            "SUCCESS",
            details={"gate": gate.name, "diagnostics": len(diagnostics)},
        )
        logger.info(
            "No tests found; using the %s gate as the verification oracle (%d diagnostics).",
            gate.name,
            len(diagnostics),
        )

        return ParsedFailure(
            test_name=f"{gate.name} check",
            failing_file=target.file_path,
            failing_line=target.line,
            exception_type=target.code or "Diagnostic",
            exception_message=target.message,
            stack_frames=[],
            raw_traceback="\n".join(d.describe() for d in diagnostics[:20]),
        )

    def _retrieve(
        self, incident_id: str, repo_dir: str, suspect: SuspectFunction, failure: ParsedFailure
    ) -> tuple[RAGContext, CodeRAGAgent]:
        """Stage 2: gather supporting code, tests, and prior fixes."""
        self._transition(incident_id, OrchestrationState.LOCALIZING, OrchestrationState.RETRIEVING)

        rag_agent = CodeRAGAgent()
        rag_agent.index_repository(repo_dir)
        context = rag_agent.retrieve_context_for_suspect(suspect, failure)

        self.telemetry.log_event(
            incident_id,
            "CodeRAGAgent",
            "RETRIEVE_CONTEXT",
            f"suspect {suspect.name}",
            f"{len(context.related_code_chunks)} code chunks, "
            f"{len(context.related_tests)} tests, {len(context.past_fixes)} prior fixes",
            "SUCCESS",
        )
        return context, rag_agent

    def _repair(
        self,
        incident_id: str,
        repo_dir: str,
        suspect: SuspectFunction,
        failure: ParsedFailure,
        context: RAGContext,
        graph_builder: CodebaseGraphBuilder,
        toolchain: LanguageToolchain,
        custom_env: Optional[Dict[str, str]],
    ) -> VerificationResult:
        """Stages 3 and 4: generate candidate patches and prove them in the sandbox."""
        self._transition(incident_id, OrchestrationState.RETRIEVING, OrchestrationState.PATCHING)
        self.telemetry.log_event(
            incident_id,
            "PatchGeneratorAgent",
            "PATCH_GENERATION_START",
            f"{suspect.name} in {suspect.file_path}",
            f"provider {self.llm.name} (live: {self.llm.is_live}), language {toolchain.name}",
            "IN_PROGRESS",
        )

        self._transition(incident_id, OrchestrationState.PATCHING, OrchestrationState.VERIFYING)

        # Third-party dependencies are prepared once per incident, in isolation,
        # before any test run needs them.
        install = toolchain.install_dependencies(repo_dir)
        if not install.succeeded:
            logger.warning("Dependency preparation incomplete: %s", install.detail)
        self.telemetry.log_event(
            incident_id,
            "DependencyInstaller",
            "PREPARE_DEPENDENCIES",
            f"{toolchain.name} project",
            install.detail,
            "SUCCESS" if install.succeeded else "FAILURE",
        )

        agent = VerificationAgent(
            patch_agent=PatchGeneratorAgent(llm_provider=self.llm),
            max_attempts=MAX_VERIFICATION_ATTEMPTS,
            toolchain=toolchain,
            executable=install.executable,
            oracle=getattr(self, "_gate_oracle", None),
        )
        result = agent.verify_fix(
            repo_dir=repo_dir,
            graph_builder=graph_builder,
            suspect=suspect,
            failure=failure,
            past_fix_examples=[fix.applied_diff for fix in context.past_fixes],
            custom_env=custom_env,
            related_code_context=[chunk.code for chunk in context.related_code_chunks],
        )

        self.telemetry.log_event(
            incident_id,
            "VerificationAgent",
            "VERIFY_PATCH_SANDBOX",
            f"{result.total_attempts} attempt(s)",
            "verified" if result.success else "no attempt passed its tests",
            "SUCCESS" if result.success else "FAILURE",
            details={
                "total_attempts": result.total_attempts,
                "outcomes": [a.outcome.value for a in result.attempts_history],
            },
        )
        return result

    def _sign_off(
        self,
        incident_id: str,
        failure: ParsedFailure,
        suspect: SuspectFunction,
        verification: VerificationResult,
        rag_agent: CodeRAGAgent,
        human_approval_required: bool,
        language: Optional[str] = None,
    ) -> OrchestrationSummary:
        """Stage 5: record the fix and decide whether it may auto-apply."""
        patch = verification.verified_patch

        # Only verified patches enter the fix history; recording unproven diffs
        # would poison the retrieval context for every later incident.
        rag_agent.fix_history.record_fix(
            exception_type=failure.exception_type,
            exception_message=failure.exception_message,
            failing_symbol=suspect.symbol_id,
            applied_diff=patch.unified_diff,
        )

        self._transition(incident_id, OrchestrationState.VERIFYING, OrchestrationState.CHECKING_SAFETY)
        risk = self.safety_checker.evaluate_patch_risk(
            patch.target_file, suspect.name, patch.unified_diff
        )

        gated = risk.is_risky and human_approval_required
        state = OrchestrationState.PENDING_APPROVAL if gated else OrchestrationState.COMPLETED

        self.telemetry.log_event(
            incident_id,
            "HumanApprovalChecker",
            "SAFETY_GATE_TRIGGERED" if gated else "AUTO_APPLY_APPROVED",
            f"risk {risk.risk_level}",
            risk.reason,
            "REQUIRES_APPROVAL" if gated else "SUCCESS",
            details={"matched_keywords": risk.matched_keywords},
        )
        self._transition(incident_id, OrchestrationState.CHECKING_SAFETY, state)

        logger.info("=== Incident %s finished: %s ===", incident_id, state.value)
        return OrchestrationSummary(
            incident_id=incident_id,
            state=state,
            language=language,
            verified_by=self._oracle_description(),
            failing_test=failure.test_name,
            exception_type=failure.exception_type,
            target_file=suspect.file_path,
            suspect_function=suspect.name,
            verified_patch=patch,
            risk_assessment=risk,
            total_attempts=verification.total_attempts,
            failure_report=None,
            telemetry_events=self.telemetry.get_incident_events(incident_id),
        )

    def _failed(
        self,
        incident_id: str,
        failure: Optional[ParsedFailure],
        suspect: Optional[SuspectFunction],
        report: str,
        attempts: int = 0,
        language: Optional[str] = None,
        verified_by: Optional[str] = None,
    ) -> OrchestrationSummary:
        """Build the terminal summary for an incident that could not be healed.

        The FAILED transition is emitted here rather than at each call site. Live
        subscribers close their stream on a terminal transition, and without one a
        failed incident leaves the dashboard spinning indefinitely on keepalives
        even though the run has finished.
        """
        self.telemetry.log_event(
            incident_id,
            "Orchestrator",
            "STATE_TRANSITION",
            "VERIFYING",
            OrchestrationState.FAILED.value,
            "FAILURE",
            details={"attempts": attempts},
        )
        return OrchestrationSummary(
            incident_id=incident_id,
            state=OrchestrationState.FAILED,
            language=language,
            verified_by=verified_by,
            failing_test=failure.test_name if failure else None,
            exception_type=failure.exception_type if failure else None,
            target_file=suspect.file_path if suspect else None,
            suspect_function=suspect.name if suspect else None,
            total_attempts=attempts,
            failure_report=report,
            telemetry_events=self.telemetry.get_incident_events(incident_id),
        )

    def _transition(
        self, incident_id: str, source: OrchestrationState, target: OrchestrationState
    ) -> None:
        self.telemetry.log_event(
            incident_id,
            "Orchestrator",
            "STATE_TRANSITION",
            source.value,
            target.value,
            "IN_PROGRESS",
        )
