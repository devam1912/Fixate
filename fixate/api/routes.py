"""REST API routes for triggering self-healing incidents, inspecting codebase AST graphs, and running eval benchmarks."""

import os
import shutil
import tempfile
import subprocess
import logging
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from fixate.graph.builder import CodebaseGraphBuilder
from fixate.eval.harness import EvalHarnessRunner
from fixate.orchestrator.engine import OrchestrationEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# Singletons / Registries
ENGINE = OrchestrationEngine()
EVAL_RUNNER = EvalHarnessRunner()

# Pre-packaged sample repo directory mapping
SAMPLE_REPOS = {
    "calculator_app": os.path.abspath(os.path.join("sample_repos", "calculator_app")),
    "ecommerce_api": os.path.abspath(os.path.join("sample_repos", "ecommerce_api")),
    "data_processor": os.path.abspath(os.path.join("sample_repos", "data_processor")),
}


class IncidentTriggerRequest(BaseModel):
    repo_name: Optional[str] = "calculator_app"
    repo_url: Optional[str] = None   # GitHub Repository URL (e.g., https://github.com/owner/repo)
    repo_path: Optional[str] = None  # Local directory path
    pytest_log: Optional[str] = None
    human_approval_required: bool = True


def clone_github_repo(repo_url: str) -> str:
    """Clone a GitHub repository URL into a temporary directory and return absolute path."""
    temp_dir = tempfile.mkdtemp(prefix="fixate_github_repo_")
    url = repo_url.strip()
    if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("git@"):
        url = f"https://github.com/{url}"
    if not url.endswith(".git"):
        url = f"{url}.git"

    logger.info(f"Cloning GitHub repository: {url} -> {temp_dir}")
    try:
        res = subprocess.run(
            ["git", "clone", "--depth", "1", url, temp_dir],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if res.returncode != 0:
            raise RuntimeError(f"Git clone failed: {res.stderr}")
        return temp_dir
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Could not clone GitHub repository '{url}': {exc}")


@router.get("/sample-repos")
def get_sample_repos():
    """List available sample repositories and metadata."""
    return [
        {
            "id": "calculator_app",
            "name": "calculator_app",
            "path": SAMPLE_REPOS["calculator_app"],
            "bug": "Discount Logic Formula Error",
            "type": "Math / Logic",
            "description": "Off-by-one percentage discount formula error in price engine.",
        },
        {
            "id": "ecommerce_api",
            "name": "ecommerce_api",
            "path": SAMPLE_REPOS["ecommerce_api"],
            "bug": "Dict KeyError & Attribute Exception",
            "type": "API Schema",
            "description": "Missing dictionary attribute validation in order creation endpoint.",
        },
        {
            "id": "data_processor",
            "name": "data_processor",
            "path": SAMPLE_REPOS["data_processor"],
            "bug": "Off-by-One Loop & Null Reference",
            "type": "Pipeline Data",
            "description": "Index boundary overshoot and unhandled None value in record transformer.",
        },
    ]


@router.get("/graph")
def get_codebase_graph(
    repo_name: Optional[str] = "calculator_app",
    repo_url: Optional[str] = None,
    repo_path: Optional[str] = None,
):
    """Dynamically build and return the AST dependency graph for any GitHub repo URL, local path, or sample repo."""
    target_path = None

    if repo_url and repo_url.strip():
        target_path = clone_github_repo(repo_url)
    elif repo_path and os.path.exists(repo_path):
        target_path = os.path.abspath(repo_path)
    elif repo_name in SAMPLE_REPOS:
        target_path = SAMPLE_REPOS[repo_name]
    elif repo_name and os.path.exists(repo_name):
        target_path = os.path.abspath(repo_name)
    else:
        target_path = SAMPLE_REPOS["calculator_app"]

    try:
        builder = CodebaseGraphBuilder()
        graph = builder.build_from_directory(target_path)

        nodes = []
        for node_id, data in graph.nodes(data=True):
            symbol = data.get("symbol")
            if symbol:
                nodes.append({
                    "id": symbol.id,
                    "label": symbol.name,
                    "symbol_type": symbol.symbol_type.value,
                    "file_path": symbol.file_path,
                    "is_test": symbol.is_test,
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


@router.post("/incident/trigger")
def trigger_incident(req: IncidentTriggerRequest):
    """Trigger dynamic self-healing incident pipeline for ANY GitHub repository URL or codebase path."""
    target_path = None
    if req.repo_url and req.repo_url.strip():
        target_path = clone_github_repo(req.repo_url)
    elif req.repo_path and os.path.exists(req.repo_path):
        target_path = os.path.abspath(req.repo_path)
    elif req.repo_name in SAMPLE_REPOS:
        target_path = SAMPLE_REPOS[req.repo_name]
    elif req.repo_name and os.path.exists(req.repo_name):
        target_path = os.path.abspath(req.repo_name)
    else:
        target_path = SAMPLE_REPOS["calculator_app"]

    pytest_log = req.pytest_log

    # If no explicit traceback log provided, auto-discover by running pytest on target_path
    if not pytest_log:
        try:
            res = subprocess.run(
                ["python", "-m", "pytest"],
                cwd=target_path,
                capture_output=True,
                text=True,
                timeout=45,
            )
            pytest_log = res.stdout + "\n" + res.stderr
        except Exception as exc:
            logger.warning(f"Could not auto-run pytest on {target_path}: {exc}")
            pytest_log = f"Pytest execution on {target_path}:\nAssertionError: Failure detected in test suite."

    summary = ENGINE.run_self_healing_pipeline(
        repo_dir=target_path,
        pytest_log=pytest_log,
        human_approval_required=req.human_approval_required,
    )
    return summary


@router.get("/eval")
def get_eval_scorecard():
    """Run benchmark evaluation suite across sample repositories and return scorecard metrics."""
    try:
        scorecard = EVAL_RUNNER.run_benchmark_suite()
        return scorecard.model_dump()
    except Exception as exc:
        logger.error(f"Error generating eval scorecard: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
