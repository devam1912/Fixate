"""FastAPI API routes for Fixate web dashboard and self-healing endpoints."""

import os
import re
import sys
import glob
import logging
import uuid
import subprocess
import time
from typing import Optional
from typing import Dict, List
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
from fixate.languages.base import TestSelection
from fixate.localization.parser import FailureTracebackParser, ParsedFailure, _SECTION_BANNER
from fixate.languages.javascript.failures import (
    JavaScriptFailureParser,
    _TEST_HEADER,
    _VITEST_FAIL,
)
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
INCIDENT_CONTEXTS: Dict[str, dict] = {}
REPOSITORY_SCANS: Dict[str, dict] = {}


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
    scan_id: Optional[str] = None
    failure_id: Optional[str] = None


class RepositoryScanRequest(BaseModel):
    repo_name: Optional[str] = "calculator_app"
    repo_url: Optional[str] = None
    repo_path: Optional[str] = None
    env_text: Optional[str] = None


class PullRequestRequest(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    base_branch: Optional[str] = None


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
    if req.scan_id and req.failure_id:
        scan = REPOSITORY_SCANS.get(req.scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail=f"No scan found for {req.scan_id}")
        failure = next((f for f in scan["failures"] if f["failure_id"] == req.failure_id), None)
        if not failure:
            raise HTTPException(status_code=404, detail=f"No failure {req.failure_id} in scan {req.scan_id}")
        req.pytest_log = failure["raw_log"]
        return scan["repo_path"]

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


def _request_from_scan(req: RepositoryScanRequest) -> IncidentTriggerRequest:
    return IncidentTriggerRequest(
        repo_name=req.repo_name,
        repo_url=req.repo_url,
        repo_path=req.repo_path,
        env_text=req.env_text,
    )


def _repo_url_for(req: IncidentTriggerRequest) -> Optional[str]:
    if req.repo_url:
        return req.repo_url
    if req.scan_id:
        scan = REPOSITORY_SCANS.get(req.scan_id)
        if scan:
            return scan.get("repo_url")
    return None


def _parse_env_text(env_text: Optional[str]) -> dict:
    """Parse the dashboard's KEY=value block into an environment mapping."""
    custom_env: dict = {}
    for line in (env_text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            raise HTTPException(status_code=400, detail=f"Invalid environment variable name: {key}")
        custom_env[key] = value.strip().strip('"').strip("'")
    return custom_env


def _redact_env_values(text: str, custom_env: Optional[dict]) -> str:
    """Remove user-supplied secret values before logs reach parsing, UI, or LLM prompts."""
    redacted = text or ""
    for key, value in (custom_env or {}).items():
        if not value or len(value) < 3:
            continue
        redacted = redacted.replace(value, f"<redacted:{key}>")
    return redacted


def _safe_request_context(req: IncidentTriggerRequest) -> dict:
    """Persist request metadata without keeping pasted secret material."""
    data = req.model_dump()
    if data.get("env_text"):
        data["env_text"] = "<redacted>"
    return data


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
    if custom_env:
        logger.info("Using %d runtime-only environment override(s) for this incident.", len(custom_env))

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
        pytest_log = capture_failure_log(
            target_path,
            executable=install.executable,
            custom_env=custom_env,
        )

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

    return target_path, _redact_env_values(pytest_log, custom_env), custom_env


def _capture_for_toolchain(repo_dir: str, toolchain, custom_env: Optional[dict] = None) -> tuple[str, str]:
    """Prepare and run one language's suite, returning output and install detail."""
    install = toolchain.install_dependencies(repo_dir)
    if not install.succeeded:
        return install.detail, install.detail

    command = toolchain.test_command(repo_dir, TestSelection())
    if command and command[0] in ("python", "python3"):
        command = [install.executable or sys.executable] + command[1:]

    env = {**os.environ, **toolchain.environment(repo_dir)}
    if custom_env:
        env.update(custom_env)
    try:
        result = subprocess.run(
            command,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
            shell=(os.name == "nt" and command[0] in {"npm", "npx"}),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return str(exc), install.detail

    return _redact_env_values(f"{result.stdout}\n{result.stderr}".strip(), custom_env), install.detail


def _split_pytest_failures(log: str) -> List[str]:
    lines = (log or "").splitlines()
    banners = [(idx, _SECTION_BANNER.match(line.strip())) for idx, line in enumerate(lines)]
    starts = [(idx, match.group("test")) for idx, match in banners if match]
    if not starts:
        return [log] if log.strip() else []

    sections: List[str] = []
    for pos, (start, _name) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        sections.append("\n".join(lines[start:end]))
    return sections


def _split_js_failures(log: str) -> List[str]:
    lines = (log or "").splitlines()
    starts: List[int] = []
    for index, line in enumerate(lines):
        vitest = _VITEST_FAIL.match(line)
        header = _TEST_HEADER.match(line)
        if vitest or (header and JavaScriptFailureParser._is_summary_bullet(header.group("name")) is False):
            starts.append(index)
    if not starts:
        return [log] if log.strip() else []

    sections: List[str] = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        sections.append("\n".join(lines[start:end]))
    return sections


def _failure_sections_for(toolchain, log: str) -> List[str]:
    if toolchain.name == "python":
        return _split_pytest_failures(log)
    if toolchain.name == "javascript":
        return _split_js_failures(log)
    return [log] if log.strip() else []


def _summarize_failure(failure: ParsedFailure, language: str, raw_log: str, index: int) -> dict:
    return {
        "failure_id": f"{language}-{index + 1}",
        "language": language,
        "test_name": failure.test_name,
        "exception_type": failure.exception_type,
        "exception_message": failure.exception_message,
        "failing_file": failure.failing_file,
        "failing_line": failure.failing_line,
        "raw_log": raw_log,
    }


@router.post("/repository/scan")
def scan_repository(req: RepositoryScanRequest):
    """Run every detected language's suite and return all parseable failures."""
    incident_req = _request_from_scan(req)
    repo_path = _resolve_target_path(incident_req)
    custom_env = _parse_env_text(req.env_text)
    if custom_env:
        logger.info("Using %d runtime-only environment override(s) for repository scan.", len(custom_env))

    toolchains = registry.for_repo(repo_path)
    if not toolchains:
        raise HTTPException(status_code=400, detail="No supported language detected.")

    scan_id = f"scan_{uuid.uuid4().hex[:8]}"
    languages: List[dict] = []
    failures: List[dict] = []

    for toolchain in toolchains:
        language_report = {
            "language": toolchain.name,
            "status": "not_run",
            "install_detail": "",
            "failure_count": 0,
            "log_excerpt": "",
        }

        if not toolchain.has_test_setup(repo_path):
            language_report.update(
                {
                    "status": "no_tests",
                    "install_detail": "No runnable test setup detected for this language.",
                }
            )
            languages.append(language_report)
            continue

        output, detail = _capture_for_toolchain(repo_path, toolchain, custom_env)
        language_report["install_detail"] = detail
        language_report["log_excerpt"] = output[:1200]

        if not output.strip():
            language_report["status"] = "no_output"
            languages.append(language_report)
            continue

        if toolchain.collected_nothing(output):
            language_report["status"] = "no_tests"
            languages.append(language_report)
            continue

        if not toolchain.owns_log(output):
            language_report["status"] = "passed"
            languages.append(language_report)
            continue

        parsed_count = 0
        for section in _failure_sections_for(toolchain, output):
            try:
                failure = toolchain.parse_failure(section)
            except Exception:
                continue
            failures.append(_summarize_failure(failure, toolchain.name, section, parsed_count))
            parsed_count += 1

        language_report["failure_count"] = parsed_count
        language_report["status"] = "failed" if parsed_count else "unparsed_failure"
        languages.append(language_report)

    payload = {
        "scan_id": scan_id,
        "repo_path": repo_path,
        "repo_url": req.repo_url,
        "languages": languages,
        "failures": failures,
        "total_failures": len(failures),
    }
    REPOSITORY_SCANS[scan_id] = payload
    return payload


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
    INCIDENT_CONTEXTS[summary.incident_id] = {
        "repo_path": target_path,
        "repo_url": _repo_url_for(req),
        "request": _safe_request_context(req),
    }
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
            INCIDENT_CONTEXTS[incident_id] = {
                "repo_path": target_path,
                "repo_url": _repo_url_for(req),
                "request": _safe_request_context(req),
            }
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


def _parse_github_slug(repo_url: str) -> tuple[str, str]:
    cleaned = repo_url.strip().removesuffix(".git")
    match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+)$", cleaned)
    if not match and "/" in cleaned and not cleaned.startswith("http"):
        owner, repo = cleaned.split("/", 1)
        return owner, repo
    if not match:
        raise HTTPException(status_code=400, detail="Only GitHub repository URLs are supported for PR creation.")
    return match.group("owner"), match.group("repo")


def _git(repo_path: str, args: List[str], check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if check and result.returncode != 0:
        detail = result.stderr or result.stdout or "git command failed"
        detail = re.sub(r"https://x-access-token:[^@]+@", "https://x-access-token:<redacted>@", detail)
        raise HTTPException(status_code=400, detail=detail[:1000])
    return result


def _default_branch(repo_path: str) -> str:
    result = _git(repo_path, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], check=False)
    if result.returncode == 0 and "/" in result.stdout:
        return result.stdout.strip().split("/", 1)[1]
    return "main"


def _github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_request(method: str, path: str, token: str, **kwargs):
    import requests

    return requests.request(
        method,
        f"https://api.github.com{path}",
        headers=_github_headers(token),
        timeout=30,
        **kwargs,
    )


def _github_login(token: str) -> str:
    response = _github_request("GET", "/user", token)
    if response.status_code != 200:
        raise HTTPException(status_code=400, detail=f"GitHub authentication failed: {response.text[:500]}")
    login = response.json().get("login")
    if not login:
        raise HTTPException(status_code=400, detail="GitHub did not return an authenticated user login.")
    return login


def _ensure_push_target(owner: str, repo: str, token: str) -> tuple[str, str, str]:
    """Return ``(head_owner, remote_owner, push_url)`` for the PR branch."""
    login = _github_login(token)
    if login.lower() == owner.lower():
        return login, owner, f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"

    existing = _github_request("GET", f"/repos/{login}/{repo}", token)
    if existing.status_code == 200:
        data = existing.json()
        parent = (data.get("parent") or {}).get("full_name")
        source = (data.get("source") or {}).get("full_name")
        if parent == f"{owner}/{repo}" or source == f"{owner}/{repo}":
            return login, login, f"https://x-access-token:{token}@github.com/{login}/{repo}.git"
        raise HTTPException(
            status_code=400,
            detail=(
                f"GitHub account '{login}' already has a repository named '{repo}', "
                "but it is not a fork of the target repository. Rename it or create the fork manually."
            ),
        )
    if existing.status_code not in (404,):
        raise HTTPException(status_code=400, detail=f"Could not inspect GitHub fork: {existing.text[:500]}")

    created = _github_request("POST", f"/repos/{owner}/{repo}/forks", token)
    if created.status_code not in (200, 201, 202):
        raise HTTPException(status_code=400, detail=f"Could not create GitHub fork: {created.text[:700]}")

    for _ in range(10):
        ready = _github_request("GET", f"/repos/{login}/{repo}", token)
        if ready.status_code == 200:
            return login, login, f"https://x-access-token:{token}@github.com/{login}/{repo}.git"
        time.sleep(1)

    raise HTTPException(
        status_code=400,
        detail=f"GitHub fork for '{login}/{repo}' was created but was not ready yet. Try creating the PR again.",
    )


def _create_pull_request(owner: str, repo: str, head: str, base: str, title: str, body: str, token: str) -> str:
    response = _github_request(
        "POST",
        f"/repos/{owner}/{repo}/pulls",
        token,
        json={"title": title, "head": head, "base": base, "body": body},
    )
    if response.status_code not in (200, 201):
        raise HTTPException(status_code=400, detail=f"GitHub PR creation failed: {response.text[:1000]}")
    return response.json()["html_url"]


@router.post("/incident/{incident_id}/pull-request")
def create_pull_request_for_incident(incident_id: str, req: PullRequestRequest):
    """Push the verified patch branch and open a pull request."""
    summary = INCIDENT_RESULTS.get(incident_id)
    context = INCIDENT_CONTEXTS.get(incident_id)
    if not summary or not context:
        raise HTTPException(status_code=404, detail=f"No completed incident found for {incident_id}")
    if summary.get("state") not in ("COMPLETED", "PENDING_APPROVAL"):
        raise HTTPException(status_code=400, detail="Only verified incidents can be pushed.")
    patch = summary.get("verified_patch")
    if not patch:
        raise HTTPException(status_code=400, detail="This incident has no verified patch to push.")

    repo_url = context.get("repo_url")
    if not repo_url:
        raise HTTPException(status_code=400, detail="This incident was not started from a GitHub URL.")

    repo_path = context["repo_path"]
    owner, repo = _parse_github_slug(repo_url)
    target_file = patch["target_file"].replace("\\", "/")
    branch = f"fixate/{incident_id}-{os.path.basename(target_file).split('.')[0]}"
    title = req.title or f"Fixate: repair {summary.get('failing_test') or target_file}"
    body = req.body or (
        f"Verified by Fixate incident `{incident_id}`.\n\n"
        f"- Failing test: `{summary.get('failing_test')}`\n"
        f"- Suspect: `{summary.get('suspect_function')}`\n"
        f"- Proof: {summary.get('verified_by') or 'verified test pass'}\n"
        f"- Risk: {(summary.get('risk_assessment') or {}).get('risk_level', 'unknown')}\n"
    )
    base = req.base_branch or _default_branch(repo_path)

    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        raise HTTPException(status_code=400, detail="Set GITHUB_TOKEN or GH_TOKEN before creating PRs.")

    head_owner, remote_owner, push_url = _ensure_push_target(owner, repo, token)
    head = f"{head_owner}:{branch}" if head_owner.lower() != owner.lower() else branch

    _git(repo_path, ["config", "user.name", "Fixate Bot"])
    _git(repo_path, ["config", "user.email", "fixate-bot@example.invalid"])
    _git(repo_path, ["checkout", "-B", branch])
    _git(repo_path, ["add", target_file])
    diff = _git(repo_path, ["diff", "--cached", "--quiet"], check=False)
    if diff.returncode == 0:
        raise HTTPException(status_code=400, detail="No file changes are staged for this incident.")
    _git(repo_path, ["commit", "-m", title])

    _git(repo_path, ["push", push_url, f"HEAD:{branch}"])
    pr_url = _create_pull_request(owner, repo, head, base, title, body, token)
    summary["pull_request"] = {
        "url": pr_url,
        "branch": branch,
        "base": base,
        "head": head,
        "head_owner": head_owner,
        "head_repository": f"{remote_owner}/{repo}",
        "base_repository": f"{owner}/{repo}",
    }
    return summary["pull_request"]


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
