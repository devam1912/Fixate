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


def test_repository_scan_lists_parseable_failures(tmp_path):
    (tmp_path / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    (tmp_path / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 2) == 4\n", encoding="utf-8"
    )

    response = client.post("/api/repository/scan", json={"repo_path": str(tmp_path), "repo_name": None})

    assert response.status_code == 200
    body = response.json()
    assert body["total_failures"] == 1
    assert body["failures"][0]["language"] == "python"
    assert body["failures"][0]["test_name"] == "test_add"


def test_trigger_incident_endpoint():
    response = client.post(
        "/api/incident/trigger",
        json={"repo_name": "calculator_app", "human_approval_required": True},
    )
    assert response.status_code == 200
    summary = response.json()
    assert "incident_id" in summary
    assert "state" in summary


def test_telemetry_events_reach_live_subscribers():
    """The streaming path was previously dead: nothing ever called broadcast_event."""
    from fixate.api.routes import TELEMETRY
    from fixate.telemetry.events import DISPATCHER

    queue = DISPATCHER.subscribe_incident("inc_stream_test")
    try:
        TELEMETRY.log_event(
            incident_id="inc_stream_test",
            agent="Orchestrator",
            action="STATE_TRANSITION",
            input_summary="IDLE",
            output_summary="LOCALIZING",
            result="IN_PROGRESS",
        )
        assert queue.qsize() == 1
        assert queue.get_nowait().output_summary == "LOCALIZING"
    finally:
        DISPATCHER.unsubscribe_incident("inc_stream_test", queue)


def test_events_for_other_incidents_are_not_delivered():
    from fixate.api.routes import TELEMETRY
    from fixate.telemetry.events import DISPATCHER

    queue = DISPATCHER.subscribe_incident("inc_mine")
    try:
        TELEMETRY.log_event(
            incident_id="inc_someone_else",
            agent="Orchestrator",
            action="STATE_TRANSITION",
            input_summary="IDLE",
            output_summary="LOCALIZING",
            result="IN_PROGRESS",
        )
        assert queue.qsize() == 0
    finally:
        DISPATCHER.unsubscribe_incident("inc_mine", queue)


def test_incident_start_returns_an_id_immediately():
    response = client.post(
        "/api/incident/start",
        json={"repo_name": "calculator_app", "human_approval_required": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["incident_id"].startswith("inc_")
    assert body["status"] == "running"


def test_unsupported_repository_is_rejected(tmp_path):
    (tmp_path / "notes.txt").write_text("no source here", encoding="utf-8")
    response = client.post(
        "/api/incident/trigger",
        json={"repo_path": str(tmp_path), "human_approval_required": True},
    )
    assert response.status_code == 400
    assert "No supported language" in response.json()["detail"]


def test_untested_repository_falls_back_to_diagnostic_gates(tmp_path):
    """No tests is not a dead end: gates supply both the defect and the oracle.

    This particular repository is clean, so the honest outcome is "nothing to
    fix" rather than a refusal to even look.
    """
    (tmp_path / "app.py").write_text("def f(x):\n    return x - 1\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")

    response = client.post(
        "/api/incident/trigger",
        json={"repo_path": str(tmp_path), "human_approval_required": True},
    )

    assert response.status_code == 200
    summary = response.json()
    assert summary["state"] == "FAILED"
    assert "reports it as clean" in summary["failure_report"]


def test_background_start_captures_a_failure_log_like_the_sync_path(tmp_path):
    """The two endpoints must prepare identically.

    When they diverged, /incident/start passed `req.pytest_log or ""` straight
    through and skipped dependency install and log capture, so every
    dashboard-initiated run died with "the supplied pytest log was empty".
    """
    from fixate.api.routes import IncidentTriggerRequest, _prepare_incident

    (tmp_path / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    (tmp_path / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 2) == 4\n", encoding="utf-8"
    )

    _, pytest_log, _ = _prepare_incident(
        IncidentTriggerRequest(repo_path=str(tmp_path), repo_name=None)
    )

    assert pytest_log.strip(), "preparation must produce a real failure log"
    assert "test_add" in pytest_log


def test_runtime_env_values_are_not_written_or_returned_raw(tmp_path):
    from fixate.api.routes import IncidentTriggerRequest, _prepare_incident

    (tmp_path / "app.py").write_text(
        "import os\n\n"
        "def exposed_secret():\n"
        "    return os.environ['TEST_SECRET_TOKEN']\n",
        encoding="utf-8",
    )
    (tmp_path / "test_app.py").write_text(
        "from app import exposed_secret\n\n"
        "def test_secret_is_redacted():\n"
        "    assert exposed_secret() == 'not-the-secret'\n",
        encoding="utf-8",
    )

    _repo_path, pytest_log, custom_env = _prepare_incident(
        IncidentTriggerRequest(
            repo_path=str(tmp_path),
            repo_name=None,
            env_text="TEST_SECRET_TOKEN=super-secret-value",
        )
    )

    assert custom_env["TEST_SECRET_TOKEN"] == "super-secret-value"
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / ".streamlit" / "secrets.toml").exists()
    assert "super-secret-value" not in pytest_log
    assert "<redacted:TEST_SECRET_TOKEN>" in pytest_log


def test_background_start_reports_preparation_errors(monkeypatch):
    """A run that dies before the pipeline must still reach the subscriber."""
    import fixate.api.routes as routes
    from fixate.telemetry.events import DISPATCHER

    def boom(_req):
        raise RuntimeError("clone exploded")

    monkeypatch.setattr(routes, "_prepare_incident", boom)

    response = client.post(
        "/api/incident/start", json={"repo_name": "calculator_app"}
    )
    incident_id = response.json()["incident_id"]

    # The failure is retrievable, and a terminal event was broadcast so the SSE
    # stream closes instead of heartbeating forever.
    status = client.get(f"/api/incident/{incident_id}").json()
    assert status["status"] == "error"
    assert "clone exploded" in status["detail"]


def test_failure_log_is_captured_with_the_interpreter_that_owns_dependencies(tmp_path):
    """Isolated installs are useless if the suite runs with the wrong interpreter.

    Dependencies land in a per-repo virtualenv, so capturing the log with the
    engine's own interpreter reports every third-party import as missing and makes
    a working repository look like a broken environment.
    """
    from unittest import mock
    import fixate.eval.harness as harness

    (tmp_path / "lib.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "test_lib.py").write_text(
        "from lib import f\n\ndef test_f():\n    assert f() == 2\n", encoding="utf-8"
    )
    (tmp_path / "requirements.txt").write_text("six\n", encoding="utf-8")

    venv_python = str(tmp_path / ".fixate_venv" / "bin" / "python")
    captured = {}

    real_run = harness.subprocess.run

    def spy(command, **kwargs):
        captured["command"] = command
        return real_run([harness.sys.executable, "-m", "pytest"], **kwargs)

    with mock.patch.object(harness.subprocess, "run", spy):
        harness.capture_failure_log(str(tmp_path), executable=venv_python)

    assert captured["command"][0] == venv_python, (
        "the suite must run with the interpreter holding the repo's dependencies"
    )


def test_missing_static_css_returns_404_not_index_html():
    """Missing CSS files should return 404, not fallback index.html which triggers MIME errors."""
    response = client.get("/nonexistent_style.css")
    assert response.status_code == 404


def test_pull_request_uses_authenticated_fork_head(monkeypatch, tmp_path):
    import fixate.api.routes as routes

    incident_id = "inc_prfork"
    routes.INCIDENT_RESULTS[incident_id] = {
        "incident_id": incident_id,
        "state": "PENDING_APPROVAL",
        "failing_test": "test_checkout",
        "suspect_function": "checkout",
        "verified_by": "pytest",
        "risk_assessment": {"risk_level": "LOW"},
        "verified_patch": {
            "target_file": "src/cart.py",
            "unified_diff": "--- a/src/cart.py\n+++ b/src/cart.py\n",
            "explanation": "Fix cart total.",
            "lines_changed": 1,
        },
    }
    routes.INCIDENT_CONTEXTS[incident_id] = {
        "repo_path": str(tmp_path),
        "repo_url": "https://github.com/source-owner/shop.git",
    }

    monkeypatch.setenv("GITHUB_TOKEN", "token-value")
    monkeypatch.setattr(
        routes,
        "_ensure_push_target",
        lambda owner, repo, token: (
            "devam1912",
            "devam1912",
            "https://x-access-token:token-value@github.com/devam1912/shop.git",
        ),
    )
    monkeypatch.setattr(routes, "_default_branch", lambda _repo_path: "main")

    git_calls = []

    class GitResult:
        def __init__(self, returncode=0):
            self.returncode = returncode
            self.stdout = ""
            self.stderr = ""

    def fake_git(_repo_path, args, check=True):
        git_calls.append(args)
        if args == ["diff", "--cached", "--quiet"]:
            return GitResult(returncode=1)
        return GitResult()

    pr_call = {}

    def fake_create_pr(owner, repo, head, base, title, body, token):
        pr_call.update(
            {
                "owner": owner,
                "repo": repo,
                "head": head,
                "base": base,
                "title": title,
                "token": token,
            }
        )
        return "https://github.com/source-owner/shop/pull/7"

    monkeypatch.setattr(routes, "_git", fake_git)
    monkeypatch.setattr(routes, "_create_pull_request", fake_create_pr)

    result = routes.create_pull_request_for_incident(
        incident_id,
        routes.PullRequestRequest(),
    )

    assert any(
        call[:2] == ["push", "https://x-access-token:token-value@github.com/devam1912/shop.git"]
        for call in git_calls
    )
    assert pr_call["head"] == "devam1912:fixate/inc_prfork-cart"
    assert pr_call["base"] == "main"
    assert result["head"] == "devam1912:fixate/inc_prfork-cart"
    assert result["head_repository"] == "devam1912/shop"
    assert result["base_repository"] == "source-owner/shop"
