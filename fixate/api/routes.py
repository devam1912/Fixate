"""FastAPI API routes for Fixate web dashboard and self-healing endpoints."""

import os
import re
import sys
import glob
import logging
import uuid
import subprocess
from typing import Optional
from typing import Dict
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from fixate.orchestrator.engine import OrchestrationEngine
from fixate.graph.builder import CodebaseGraphBuilder
from fixate.eval.harness import (
    EvalHarnessRunner,
    capture_failure_log,
    load_scorecard,
    save_scorecard,
)
from fixate.languages import registry
from fixate.telemetry.events import DISPATCHER
from fixate.telemetry.logger import TelemetryLogger
from fixate.eval.cases import BENCHMARK_SUITE
from fixate.sample_repos import SAMPLE_REPOS, create_sample_repo_checkout

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# One telemetry logger for the process, with the live-stream dispatcher subscribed
# to it. This is the link that makes the dashboard's pipeline view actually live:
# every log_event call now fans out to connected SSE and WebSocket clients.
TELEMETRY = TelemetryLogger()
TELEMETRY.subscribe(DISPATCHER.broadcast_event)

# Terminal summaries, kept so a client that subscribed to the stream can fetch the
# final result once the run ends.
INCIDENT_RESULTS: Dict[str, dict] = {}
INCIDENT_ERRORS: Dict[str, str] = {}


def build_engine() -> OrchestrationEngine:
    """Construct an engine per request.

    Built fresh rather than at import so provider configuration picked up from the
    environment takes effect without restarting the process.
    """
    return OrchestrationEngine(telemetry_logger=TELEMETRY)

def clone_github_repo(repo_url: str) -> str:
    """Clone a public GitHub repository into a temporary workspace directory."""
    import tempfile
    clean_url = repo_url.strip()
    if not clean_url.startswith("http"):
        clean_url = f"https://github.com/{clean_url}"

    tmp_dir = tempfile.mkdtemp(prefix="fixate_github_repo_")
    logger.info(f"Cloning GitHub repository '{clean_url}' into '{tmp_dir}'")

    res = subprocess.run(
        ["git", "clone", "--depth", "1", clean_url, tmp_dir],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        logger.error(f"Git clone failed for {clean_url}: {res.stderr}")
        raise HTTPException(status_code=400, detail=f"Git clone failed: {res.stderr}")

    # Dependencies are NOT installed here. The orchestrator asks the language's
    # toolchain to prepare them inside an isolated environment (a per-repo venv, or
    # node_modules with lifecycle scripts disabled), because installing an
    # untrusted repository's packages executes arbitrary code and must never touch
    # the engine's own interpreter.
    return tmp_dir


class IncidentTriggerRequest(BaseModel):
    repo_name: Optional[str] = "calculator_app"
    repo_url: Optional[str] = None
    repo_path: Optional[str] = None
    pytest_log: Optional[str] = None
    env_text: Optional[str] = None
    human_approval_required: bool = True


@router.get("/health")
def health_check():
    """Health check endpoint for API and background task status."""
    return {"status": "ok", "service": "fixate-backend", "version": "0.1.0"}


@router.get("/sample-repos")
def list_sample_repos():
    """Return available sample repositories for dashboard selection."""
    return [
        {
            "id": repo_id,
            "name": repo_id.replace("_", " ").title(),
            "path": repo_path,
            "exists": os.path.exists(repo_path),
        }
        for repo_id, repo_path in SAMPLE_REPOS.items()
    ]


@router.get("/graph")
def get_codebase_graph(repo_name: Optional[str] = "calculator_app", custom_path: Optional[str] = None, repo_path: Optional[str] = None):
    """Retrieve NetworkX codebase AST dependency graph nodes and edges for visualization."""
    target_path = None
    effective_path = custom_path or repo_path
    if effective_path and os.path.exists(effective_path):
        target_path = os.path.abspath(effective_path)
    elif effective_path and effective_path.startswith("http"):
        target_path = clone_github_repo(effective_path)
    elif repo_name in SAMPLE_REPOS:
        target_path = SAMPLE_REPOS[repo_name]
    else:
        target_path = SAMPLE_REPOS["calculator_app"]

    try:
        builder = CodebaseGraphBuilder()
        graph = builder.build_from_directory(target_path)

        nodes = []
        for node_id, data in graph.nodes(data=True):
            nodes.append({
                "id": node_id,
                "label": data.get("name", node_id),
                "symbol_type": data.get("symbol_type", "function"),
                "file_path": data.get("file_path", ""),
                "is_test": data.get("is_test", False),
            })

        edges = []
        for u, v, data in graph.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                "relation": data.get("relation", "calls"),
            })

        return {"nodes": nodes, "edges": edges, "repo_path": target_path}
    except Exception as err:
        logger.error(f"Error constructing graph for {target_path}: {err}")
        raise HTTPException(status_code=500, detail=f"Graph construction error: {err}")


def _resolve_target_path(req: "IncidentTriggerRequest") -> str:
    """Work out which directory this incident should run against."""
    if req.repo_url and req.repo_url.strip():
        target_path = clone_github_repo(req.repo_url)
    elif req.repo_path and os.path.exists(req.repo_path):
        target_path = os.path.abspath(req.repo_path)
    elif req.repo_name in SAMPLE_REPOS:
        target_path = create_sample_repo_checkout(req.repo_name)
    elif req.repo_name and os.path.exists(req.repo_name):
        target_path = os.path.abspath(req.repo_name)
    else:
        target_path = create_sample_repo_checkout("calculator_app")

    # Fixate repairs any language it has a toolchain for, so the gate is "is this a
    # supported project?" rather than the old "does it contain .py files?".
    if not registry.for_repo(target_path):
        raise HTTPException(
            status_code=400,
            detail=(
                "No supported language detected in this repository. Fixate can repair "
                "Python (pytest) and JavaScript/TypeScript (Jest or Vitest) projects."
            ),
        )

    return target_path


def _parse_env_text(env_text: Optional[str]) -> dict:
    """Parse the dashboard's KEY=value block into an environment mapping."""
    custom_env: dict = {}
    for line in (env_text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        custom_env[key.strip()] = value.strip().strip('"').strip("'")
    return custom_env


def _prepare_incident(req: IncidentTriggerRequest) -> tuple:
    """Resolve the repository and obtain a failure log to work from.

    Shared by both entry points. The synchronous and background endpoints must do
    identical preparation -- when they diverged, the background path skipped log
    capture entirely and every dashboard run failed with "the supplied pytest log
    was empty".

    Returns ``(target_path, pytest_log, custom_env)``.
    """
    target_path = _resolve_target_path(req)
    custom_env = _parse_env_text(req.env_text)

    # Auto-generate .env and .streamlit/secrets.toml if env vars are provided
    if custom_env and target_path:
        env_path = os.path.join(target_path, ".env")
        with open(env_path, "w", encoding="utf-8") as f:
            for k, v in custom_env.items():
                f.write(f"{k}={v}\n")
        
        streamlit_dir = os.path.join(target_path, ".streamlit")
        os.makedirs(streamlit_dir, exist_ok=True)
        secrets_path = os.path.join(streamlit_dir, "secrets.toml")
        with open(secrets_path, "w", encoding="utf-8") as f:
            for k, v in custom_env.items():
                f.write(f'{k} = "{v}"\n')
        logger.info(f"Generated .env and .streamlit/secrets.toml in {target_path}")

    pytest_log = req.pytest_log

    if not pytest_log:
        # Prepare dependencies through the language's toolchain, which isolates the
        # install (a per-repo venv for Python, node_modules with lifecycle scripts
        # disabled for JavaScript). Installing an untrusted repository's packages
        # runs arbitrary code, so it must never reach the engine's own interpreter.
        toolchains = registry.for_repo(target_path)
        if not toolchains:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No supported language detected. Fixate can repair Python "
                    "(pytest) and JavaScript/TypeScript (Jest or Vitest) projects."
                ),
            )

        toolchain = toolchains[0]

        # A repository with no runnable tests is not a dead end. The engine falls
        # back to a diagnostic gate -- parser, type-checker, or linter -- which
        # supplies both the defect and the oracle that must later agree it is
        # fixed, so the verification guarantee is preserved rather than waived.
        #
        # Establish that from the repository's files before running anything.
        # Invoking a runner to find out is what produced the worst failure mode
        # this code has had: for a repository with no package.json, `npx jest`
        # downloaded Jest, crashed inside its own config loader, and the engine
        # then tried to localize a defect in the npx cache.
        if not toolchain.has_test_setup(target_path):
            logger.info(
                "No test setup in %s; skipping the test run and falling back to a "
                "diagnostic gate.",
                target_path,
            )
            return target_path, "", custom_env

        install = toolchain.install_dependencies(target_path)
        if not install.succeeded:
            logger.warning("Dependency preparation incomplete: %s", install.detail)

        # Run the suite with the interpreter that owns the freshly installed
        # dependencies, not the engine's own.
        pytest_log = capture_failure_log(target_path, executable=install.executable)

        if not pytest_log.strip():
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Could not capture any test output from this repository using the "
                    f"{toolchain.name} toolchain. {install.detail}"
                ),
            )

        if toolchain.collected_nothing(pytest_log):
            logger.info(
                "No runnable tests in %s; the engine will fall back to a diagnostic gate.",
                target_path,
            )

    missing_module = re.search(r"No module named ['\"]([^'\"]+)['\"]", pytest_log)
    if missing_module:
        raise HTTPException(
            status_code=400,
            detail=(
                f"The repository imports '{missing_module.group(1)}', which is not "
                f"installed. Its dependency install did not complete, so the test run "
                f"reflects a broken environment rather than a code defect. Fix the "
                f"install (or supply a pytest log directly) before self-healing."
            ),
        )

    return target_path, pytest_log, custom_env


@router.post("/incident/trigger")
def trigger_incident(req: IncidentTriggerRequest):
    """Run a self-healing incident and return its terminal summary.

    Synchronous. Clients that want to watch the pipeline advance should call
    /api/incident/start, which returns an id immediately and streams progress.
    """
    target_path, pytest_log, custom_env = _prepare_incident(req)

    summary = build_engine().run_self_healing_pipeline(
        repo_dir=target_path,
        pytest_log=pytest_log,
        human_approval_required=req.human_approval_required,
        custom_env=custom_env,
    )

    INCIDENT_RESULTS[summary.incident_id] = summary.model_dump()
    return summary


def _announce_failure(incident_id: str, detail: str) -> None:
    """Emit a terminal telemetry event so live subscribers stop waiting.

    An incident that dies before the pipeline starts produces no state
    transitions, so without this the SSE stream would heartbeat indefinitely and
    the dashboard would sit on a spinner.
    """
    TELEMETRY.log_event(
        incident_id,
        "Orchestrator",
        "PIPELINE_HALTED",
        "incident preparation",
        detail,
        "FAILURE",
    )


@router.post("/incident/start")
def start_incident(req: IncidentTriggerRequest, background: BackgroundTasks):
    """Begin an incident and return its id immediately.

    The id is allocated before any work starts so the dashboard can subscribe to
    /api/stream/sse/{id} and see every stage transition, rather than receiving one
    response after the run has already finished.
    """
    incident_id = f"inc_{uuid.uuid4().hex[:8]}"

    def run() -> None:
        try:
            # Identical preparation to the synchronous endpoint: clone or resolve
            # the repository, install its dependencies in isolation, and capture a
            # real failure log. Skipping this is what left the pipeline with an
            # empty log on every dashboard-initiated run.
            target_path, pytest_log, custom_env = _prepare_incident(req)

            summary = build_engine().run_self_healing_pipeline(
                repo_dir=target_path,
                pytest_log=pytest_log,
                human_approval_required=req.human_approval_required,
                custom_env=custom_env,
                incident_id=incident_id,
            )
            INCIDENT_RESULTS[incident_id] = summary.model_dump()
        except HTTPException as exc:
            # Preparation failures carry an operator-facing explanation; surface it
            # rather than a bare exception string.
            logger.warning("Incident %s could not start: %s", incident_id, exc.detail)
            INCIDENT_ERRORS[incident_id] = str(exc.detail)
            _announce_failure(incident_id, str(exc.detail))
        except Exception as exc:
            logger.exception("Background incident %s failed", incident_id)
            INCIDENT_ERRORS[incident_id] = str(exc)
            _announce_failure(incident_id, str(exc))

    background.add_task(run)
    return {"incident_id": incident_id, "status": "running"}


@router.get("/incident/{incident_id}")
def get_incident(incident_id: str):
    """Fetch a finished incident's summary."""
    if incident_id in INCIDENT_RESULTS:
        return {"status": "completed", "summary": INCIDENT_RESULTS[incident_id]}
    if incident_id in INCIDENT_ERRORS:
        return {"status": "error", "detail": INCIDENT_ERRORS[incident_id]}
    return {"status": "running"}


@router.get("/eval")
def get_eval_scorecard():
    """Return the last recorded benchmark run.

    Returns ``{"recorded": false}`` when the suite has never been run. The engine
    reports measurements it actually made, never a placeholder standing in for one.
    """
    stored = load_scorecard()
    if stored is None:
        return {
            "recorded": False,
            "detail": "No benchmark run has been recorded yet. Run the suite to measure performance.",
            "total_cases": len(BENCHMARK_SUITE),
        }
    return {"recorded": True, **stored}


@router.post("/eval/run")
def run_eval_suite():
    """Run the benchmark suite for real and persist the result.

    This costs LLM calls for every case, so it is never triggered automatically.
    """
    runner = EvalHarnessRunner()
    for case in BENCHMARK_SUITE:
        runner.register_case(case)

    scorecard = runner.run_benchmark_suite()
    return {"recorded": True, **save_scorecard(scorecard)}
