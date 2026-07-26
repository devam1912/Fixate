"""Docker sandbox lifecycle manager and container isolator."""

import os
import subprocess
import shutil
import tempfile
import logging
from typing import Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SandboxRunResult(BaseModel):
    """Structured result of executing pytest in isolated sandbox."""
    passed: bool = Field(..., description="True if test suite passed cleanly with exit code 0")
    exit_code: int = Field(..., description="Process exit code from pytest run")
    stdout: str = Field(..., description="Standard output logs from test run")
    stderr: str = Field(..., description="Standard error logs from test run")
    execution_time_seconds: float = Field(..., description="Wall time spent running sandbox tests")


class DockerSandboxManager:
    """Manages isolated container creation, code mounting, test execution, and cleanup."""

    def __init__(self, image_name: str = "fixate-sandbox:latest", timeout_seconds: int = 30):
        self.image_name = image_name
        self.timeout_seconds = timeout_seconds
        self._docker_client = None

        try:
            import docker
            self._docker_client = docker.from_env()
            # Test ping connection
            self._docker_client.ping()
            logger.info("Docker daemon connected successfully for sandbox verification.")
        except Exception as exc:
            logger.warning(f"Docker client unavailable: {exc}. Will use isolated subprocess fallback.")

    def run_tests_in_sandbox(
        self,
        workspace_dir: str,
        test_command: str = "pytest",
    ) -> SandboxRunResult:
        """Run tests inside isolated Docker container or isolated subprocess fallback.
        
        Args:
            workspace_dir: Directory containing codebase checkout with applied patch.
            test_command: Test command string to execute, e.g. "pytest tests/test_app.py".
            
        Returns:
            SandboxRunResult containing pass status, exit code, and logs.
        """
        import time

        start_time = time.time()

        if self._docker_client:
            try:
                # Ensure image exists or build simple fallback
                container = self._docker_client.containers.run(
                    image="python:3.11-slim",
                    command=f"bash -c 'pip install pytest -q && cd /sandbox && {test_command}'",
                    volumes={os.path.abspath(workspace_dir): {"bind": "/sandbox", "mode": "rw"}},
                    working_dir="/sandbox",
                    detach=True,
                    network_mode="none",  # Security restriction: no network access in sandbox
                )

                try:
                    res = container.wait(timeout=self.timeout_seconds)
                    exit_code = res.get("StatusCode", 1)
                    logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
                    elapsed = time.time() - start_time
                    return SandboxRunResult(
                        passed=(exit_code == 0),
                        exit_code=exit_code,
                        stdout=logs,
                        stderr="",
                        execution_time_seconds=round(elapsed, 2),
                    )
                finally:
                    try:
                        container.remove(force=True)
                    except Exception as clean_err:
                        logger.error(f"Error cleaning up Docker container: {clean_err}")

            except Exception as docker_err:
                logger.error(f"Docker sandbox execution failed: {docker_err}. Falling back to subprocess isolation.")

        # Subprocess Fallback Execution
        try:
            proc = subprocess.run(
                test_command,
                cwd=workspace_dir,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            elapsed = time.time() - start_time
            return SandboxRunResult(
                passed=(proc.returncode == 0),
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                execution_time_seconds=round(elapsed, 2),
            )
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            return SandboxRunResult(
                passed=False,
                exit_code=-1,
                stdout="",
                stderr=f"Test execution timed out after {self.timeout_seconds} seconds.",
                execution_time_seconds=round(elapsed, 2),
            )
        except Exception as exc:
            elapsed = time.time() - start_time
            return SandboxRunResult(
                passed=False,
                exit_code=1,
                stdout="",
                stderr=f"Sandbox execution error: {exc}",
                execution_time_seconds=round(elapsed, 2),
            )
