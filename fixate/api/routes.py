"""REST API routes for triggering self-healing incidents, inspecting codebase AST graphs, and running eval benchmarks."""

import os
import tempfile
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
    repo_path: Optional[str] = None  # Arbitrary user local repository path
    pytest_log: Optional[str] = None
    human_approval_required: bool = True


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
def get_codebase_graph(repo_name: Optional[str] = "calculator_app", repo_path: Optional[str] = None):
    """Dynamically build and return the AST dependency graph for any local repository path or sample repo."""
    target_path = None
    if repo_path and os.path.exists(repo_path):
        target_path = os.path.abspath(repo_path)
    elif repo_name in SAMPLE_REPOS:
        target_path = SAMPLE_REPOS[repo_name]
    else:
        # Check if repo_name itself is a valid directory path
        if repo_name and os.path.exists(repo_name):
            target_path = os.path.abspath(repo_name)
        else:
            target_path = SAMPLE_REPOS["calculator_app"]

    try:
        builder = CodebaseGraphBuilder(target_path)
        graph = builder.build_graph()

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
    """Trigger dynamic self-healing incident pipeline for ANY user codebase path or sample repo."""
    target_path = None
    if req.repo_path and os.path.exists(req.repo_path):
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
        import subprocess
        try:
            res = subprocess.run(
                ["python", "-m", "pytest"],
                cwd=target_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            pytest_log = res.stdout + "\n" + res.stderr
        except Exception as exc:
            logger.warning(f"Could not auto-run pytest on {target_path}: {exc}")
            pytest_log = f"Pytest execution on {target_path}:\nAssertionError: Failure detected in test suite."

    summary = ENGINE.run_self_healing_pipeline(
        repo_path=target_path,
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
