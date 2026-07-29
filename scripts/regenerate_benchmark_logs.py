"""Capture real failure logs from the sample repositories.

The benchmark cases used to carry hand-written ``pytest_log`` strings. Some did not
correspond to any real run -- one asserted ``AssertionError: assert 80.0 == 80.0``,
which would have passed -- so localization accuracy was being scored against
tracebacks no test ever emitted.

This regenerates them by running each sample repository's own suite and recording
what the runner actually printed. Run it after changing a sample repo's seeded
defect:

    python scripts/regenerate_benchmark_logs.py

It prints the captured logs; paste them into fixate/eval/cases.py, or use --write
to update the module in place.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fixate.languages import registry  # noqa: E402
from fixate.sample_repos import SAMPLE_REPOS, create_sample_repo_checkout  # noqa: E402


def capture(repo_name: str) -> str:
    """Run a sample repo's suite in a throwaway checkout and return its output."""
    workspace = create_sample_repo_checkout(repo_name)
    toolchains = registry.for_repo(workspace)
    if not toolchains:
        return f"[no supported language detected in {repo_name}]"

    toolchain = toolchains[0]
    from fixate.languages.base import TestSelection

    command = toolchain.test_command(workspace, TestSelection())
    env_overrides = toolchain.environment(workspace)

    import os

    env = {**os.environ, **env_overrides}
    if command and command[0] in ("python", "python3"):
        command = [sys.executable] + command[1:]

    try:
        result = subprocess.run(
            command, cwd=workspace, capture_output=True, text=True, timeout=300, env=env
        )
    except subprocess.TimeoutExpired:
        return f"[{repo_name}: test run timed out]"
    except FileNotFoundError:
        return f"[{repo_name}: runner {command[0]!r} not installed]"

    return f"{result.stdout}\n{result.stderr}".strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="Capture a single repository only.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = parser.parse_args()

    targets = [args.repo] if args.repo else list(SAMPLE_REPOS)
    captured = {name: capture(name) for name in targets}

    if args.json:
        print(json.dumps(captured, indent=2))
        return 0

    for name, log in captured.items():
        print(f"\n{'=' * 70}\n{name}\n{'=' * 70}")
        print(log or "[no output]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
