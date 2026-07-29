"""Shared filesystem paths for the Fixate project."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
SAMPLE_REPOS_DIR = PROJECT_ROOT / "sample_repos"
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
TELEMETRY_LOG_DIR = PROJECT_ROOT / "telemetry_logs"

# Persisted state that must survive a restart. Benchmark results live here so the
# dashboard can show a real, dated measurement instead of hardcoded numbers.
DATA_DIR = PROJECT_ROOT / "data"
EVAL_SCORECARD_FILE = DATA_DIR / "eval_scorecard.json"
