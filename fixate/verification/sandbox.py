"""Docker Sandbox Execution Manager for isolated test execution."""

import os
import sys
import time
import logging
import shutil
import subprocess
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SandboxRunResult(BaseModel):
    """Structured result of executing pytest in isolated sandbox."""
    passed: bool = Field(..., description="True if test suite passed cleanly with exit code 0")
    exit_code: int = Field(..., description="Process exit code from pytest run")
    stdout: str = Field(..., description="Standard output logs from test run")
    stderr: str = Field(..., description="Standard error logs from test run")
    execution_time_seconds: float = Field(..., description="Wall time spent running sandbox tests")


def build_workspace_pythonpath(workspace_dir: str, inherited: str = "", sep: str = os.pathsep) -> str:
    """Join workspace roots onto an inherited PYTHONPATH using the platform separator.

    The separator must follow the platform actually running the tests: the subprocess
    fallback executes inside the Linux container, where a hardcoded ';' would collapse
    every entry into a single unusable path.
    """
    parts = [workspace_dir, os.path.join(workspace_dir, "src")]
    parts.extend(p for p in inherited.split(sep) if p)
    return sep.join(p for p in parts if p)


class DockerSandboxManager:
    """Manages isolated container creation, code mounting, test execution, and cleanup."""

    def __init__(self, image_name: str = "fixate-sandbox:latest", timeout_seconds: int = 30):
        self.image_name = image_name
        self.timeout_seconds = timeout_seconds
        self._docker_client = None

        try:
            if os.path.exists("/.dockerenv"):
                logger.info("Running inside Docker container. Disabling Docker-in-Docker sandbox to avoid path mapping issues; forcing subprocess fallback.")
                self._docker_client = None
            else:
                import docker
                self._docker_client = docker.from_env()
                self._docker_client.ping()
                logger.info("Docker daemon connected successfully for sandbox verification.")
        except Exception as exc:
            logger.warning(f"Docker client unavailable: {exc}. Will use isolated subprocess fallback.")

    def run_tests_in_sandbox(
        self,
        workspace_dir: str,
        test_command: Union[str, List[str]] = "pytest",
        pytest_cmd: Optional[Union[str, List[str]]] = None,
        timeout_seconds: int = 300,
        custom_env: Optional[Dict[str, str]] = None,
        env_overrides: Optional[Dict[str, str]] = None,
        executable: Optional[str] = None,
    ) -> SandboxRunResult:
        """Run pytest inside isolated Docker container or subprocess fallback."""
        start_time = time.time()
        effective_cmd = pytest_cmd or test_command
        if isinstance(effective_cmd, str):
            cmd_args = effective_cmd.split()
        else:
            cmd_args = list(effective_cmd)

        if self._docker_client:
            try:
                # Container is always Linux: use POSIX separator and container-side paths,
                # not host paths, which do not exist inside the sandbox.
                container_env = {
                    "PYTHONPATH": "/workspace:/workspace/src",
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
                if custom_env:
                    container_env.update(custom_env)

                container = self._docker_client.containers.run(
                    self.image_name,
                    command=cmd_args,
                    volumes={workspace_dir: {"bind": "/workspace", "mode": "rw"}},
                    working_dir="/workspace",
                    environment=container_env,
                    detach=True,
                    mem_limit="512m",
                    network_mode="none",  # Security isolation
                )
                res = container.wait(timeout=timeout_seconds)
                logs = container.logs(stdout=True, stderr=True)
                container.remove(force=True)
                elapsed = time.time() - start_time
                exit_code = res.get("StatusCode", 1)

                return SandboxRunResult(
                    passed=(exit_code == 0),
                    exit_code=exit_code,
                    stdout=logs.decode("utf-8", errors="replace"),
                    stderr="",
                    execution_time_seconds=elapsed,
                )
            except Exception as docker_err:
                logger.warning(f"Docker sandbox execution failed: {docker_err}. Falling back to subprocess isolation.")

        # Subprocess Fallback Execution
        env = dict(os.environ)
        if env_overrides is not None:
            # The toolchain knows what its runtime needs on the path.
            env.update(env_overrides)
        else:
            env["PYTHONPATH"] = build_workspace_pythonpath(workspace_dir, env.get("PYTHONPATH", ""))
        if custom_env:
            env.update(custom_env)

        # Run tests with the interpreter that owns the installed dependencies. When
        # the toolchain built an isolated environment it passes that interpreter in;
        # otherwise fall back to the engine's own, since a bare "python" may resolve
        # elsewhere or not exist at all (e.g. python3-only images).
        if cmd_args and cmd_args[0] in ("python", "python3"):
            cmd_args = [executable or sys.executable] + cmd_args[1:]
        elif cmd_args:
            # Node tooling ships as `npx.cmd`/`npm.cmd` on Windows, which
            # subprocess cannot resolve without consulting PATHEXT. shutil.which
            # does that, and is a harmless no-op on POSIX.
            resolved = shutil.which(cmd_args[0])
            if resolved:
                cmd_args = [resolved] + cmd_args[1:]

        try:
            proc = subprocess.run(
                cmd_args,
                cwd=workspace_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            elapsed = time.time() - start_time

            return SandboxRunResult(
                passed=(proc.returncode == 0),
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                execution_time_seconds=elapsed,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            logger.error(f"Sandbox test execution timed out after {timeout_seconds}s.")
            return SandboxRunResult(
                passed=False,
                exit_code=124,
                stdout="",
                stderr=f"TimeoutExpired: Sandbox test execution exceeded {timeout_seconds} seconds.",
                execution_time_seconds=elapsed,
            )
        except Exception as exc:
            elapsed = time.time() - start_time
            logger.error(f"Subprocess sandbox execution error: {exc}")
            return SandboxRunResult(
                passed=False,
                exit_code=1,
                stdout="",
                stderr=str(exc),
                execution_time_seconds=elapsed,
            )
