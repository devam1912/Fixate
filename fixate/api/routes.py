"""REST API endpoints for incident triggering, codebase graph, and eval metrics."""

import os
from typing import Optional, List, Dict
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from fixate.orchestrator.engine import OrchestrationEngine, OrchestrationSummary
from fixate.graph.builder import CodebaseGraphBuilder
from fixate.eval.harness import EvalHarnessRunner
from fixate.eval.cases import BENCHMARK_SUITE_15
from fixate.telemetry.logger import TelemetryLogger

router = APIRouter(prefix="/api")
engine = OrchestrationEngine()
telemetry = TelemetryLogger()


class TriggerIncidentRequest(BaseModel):
    repo_name: str = Field("calculator_app", description="Name of sample repo or target directory path")
    pytest_log: Optional[str] = Field(None, description="Raw pytest log text. Defaults to sample failure.")
    human_approval_required: bool = Field(True, description="Enable safety human approval gate for risky patches")


@router.post("/incident/trigger", response_model=OrchestrationSummary)
def trigger_incident(req: TriggerIncidentRequest):
    """Trigger an incident self-healing pipeline run."""
    sample_dir = os.path.join(os.getcwd(), "sample_repos", req.repo_name)
    target_dir = sample_dir if os.path.exists(sample_dir) else req.repo_name

    if not os.path.exists(target_dir):
        raise HTTPException(status_code=404, detail=f"Target repository directory not found: {req.repo_name}")

    default_logs = {
        "calculator_app": "FAILED test_calculator.py::test_calculate_discount - AssertionError: assert 80.0 == 80.0",
        "ecommerce_api": "FAILED test_order_service.py::test_calculate_order_total - AttributeError: 'dict' object has no attribute 'price'",
        "data_processor": "FAILED test_pipeline.py::test_compute_average - AssertionError: assert 10.0 == 20.0",
    }

    log_text = req.pytest_log or default_logs.get(req.repo_name, "FAILED test_app.py::test_fail - AssertionError")

    summary = engine.run_self_healing_pipeline(
        repo_dir=target_dir,
        pytest_log=log_text,
        human_approval_required=req.human_approval_required,
    )
    return summary


@router.get("/graph")
def get_codebase_graph(repo_name: str = "calculator_app"):
    """Get nodes and edges JSON for interactive graph visualization."""
    sample_dir = os.path.join(os.getcwd(), "sample_repos", repo_name)
    target_dir = sample_dir if os.path.exists(sample_dir) else os.getcwd()

    builder = CodebaseGraphBuilder()
    builder.build_from_directory(target_dir)

    nodes = []
    for node_id, data in builder.graph.nodes(data=True):
        nodes.append({
            "id": node_id,
            "label": data.get("name", node_id),
            "symbol_type": data.get("symbol_type", "function"),
            "file_path": data.get("file_path", ""),
            "is_test": data.get("is_test", False),
        })

    edges = []
    for u, v, data in builder.graph.edges(data=True):
        edges.append({
            "source": u,
            "target": v,
            "relation": data.get("relation", "calls"),
        })

    return {"nodes": nodes, "edges": edges}


@router.get("/eval")
def run_eval_scorecard():
    """Run benchmark evaluation suite and return scorecard metrics."""
    runner = EvalHarnessRunner()
    for case in BENCHMARK_SUITE_15:
        runner.register_case(case)

    scorecard = runner.run_benchmark_suite()
    return scorecard.model_dump()


@router.get("/sample-repos")
def list_sample_repositories():
    """List available target sample repositories."""
    base_dir = os.path.join(os.getcwd(), "sample_repos")
    if not os.path.exists(base_dir):
        return []

    repos = [
        {"id": "calculator_app", "name": "Calculator App", "bug_type": "Math & Discount Logic Error"},
        {"id": "ecommerce_api", "name": "Ecommerce API Service", "bug_type": "Dict Attribute & Validation Error"},
        {"id": "data_processor", "name": "Data Pipeline Processor", "bug_type": "Off-by-One & Null Reference Error"},
    ]
    return repos
