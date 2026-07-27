"""Unit and integration tests for FastAPI backend routes."""

import pytest
from fastapi.testclient import TestClient
from fixate.api.server import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "fixate-api"


def test_sample_repos_endpoint():
    response = client.get("/api/sample-repos")
    assert response.status_code == 200
    repos = response.json()
    assert isinstance(repos, list)
    assert len(repos) >= 3
    repo_ids = {r["id"] for r in repos}
    assert "calculator_app" in repo_ids


def test_codebase_graph_endpoint():
    response = client.get("/api/graph?repo_name=calculator_app")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data
    assert isinstance(data["nodes"], list)


def test_trigger_incident_endpoint():
    response = client.post(
        "/api/incident/trigger",
        json={"repo_name": "calculator_app", "human_approval_required": True},
    )
    assert response.status_code == 200
    summary = response.json()
    assert "incident_id" in summary
    assert "state" in summary
