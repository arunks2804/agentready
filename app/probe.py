"""Scripted probe agent.

It walks the path a coding agent would take and stops at the first thing the
repository does not provide. It is a deterministic script that applies a known
correct change, so it measures whether the repository lets a task complete,
not how capable any LLM agent is.

Execution is limited to bundled sample repositories, in a throwaway copy with a
clean environment. Registered repositories only get static checks.
"""
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .checks import Repo, find_test_command, parse_catalog

TIMEOUT_SECONDS = 30
OUTPUT_LIMIT = 1500

# First match wins. Maps test output to the check that explains it.
OUTPUT_SIGNATURES = [
    (r"KeyError: '([A-Z][A-Z0-9_]+)'", "env_vars_documented", "build_environment"),
    (r"FileNotFoundError|No such file or directory", "env_vars_documented", "build_environment"),
    (r"ModuleNotFoundError|ImportError", "dependency_manifest", "build_environment"),
]


def _step(steps, name, dimension, status, detail, output=None):
    steps.append({"name": name, "dimension": dimension, "status": status, "detail": detail, "output": output})


def _result(status, steps, started, check_id=None, dimension=None):
    return {
        "status": status, "blocked_check": check_id, "blocked_dimension": dimension,
        "steps": steps, "duration_ms": round((time.monotonic() - started) * 1000),
    }


def _read_env_file(path):
    env = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^([A-Za-z_]\w*)=(.*)$", line.strip())
            if match:
                env[match.group(1)] = match.group(2)
    return env


def classify_output(output):
    for pattern, check_id, dimension in OUTPUT_SIGNATURES:
        if re.search(pattern, output):
            return check_id, dimension
    return None, "testing"


def run_probe(path, task, change_dir):
    started = time.monotonic()
    steps = []
    repo = Repo(path)

    catalog_rel, fields = parse_catalog(repo)
    description = fields.get("description", "").lower()
    if not catalog_rel or not all(k in description for k in task["keywords"]):
        _step(steps, "Find the service", "discovery", "blocked",
              f"Searched the catalog for “{' '.join(task['keywords'])}” and found no matching service.")
        return _result("blocked", steps, started, "catalog_entry", "discovery")
    _step(steps, "Find the service", "discovery", "passed", f"Catalog entry {catalog_rel} matches the ticket.")

    if not repo.has(task["target_file"]):
        _step(steps, "Locate the code", "code_understanding", "blocked", f"{task['target_file']} does not exist.")
        return _result("blocked", steps, started, "readme_overview", "code_understanding")
    _step(steps, "Locate the code", "code_understanding", "passed", f"Found {task['target_file']}.")

    if task.get("requires_api_spec"):
        spec = repo.has("openapi.yaml", "openapi.yml", "openapi.json", "docs/openapi.yaml")
        if not spec:
            _step(steps, "Read the API contract", "api_context", "blocked",
                  "This ticket changes API behaviour and no contract is published.")
            return _result("blocked", steps, started, "api_spec", "api_context")
        _step(steps, "Read the API contract", "api_context", "passed", f"Read {spec}.")

    doc, command = find_test_command(repo)
    if not command:
        _step(steps, "Find the test command", "testing", "blocked", "No test command is documented.")
        return _result("blocked", steps, started, "test_command_documented", "testing")
    _step(steps, "Find the test command", "testing", "passed", f"{doc}: {command}")

    with tempfile.TemporaryDirectory(prefix="agentready-probe-") as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(path, work, symlinks=True)
        documented_env = _read_env_file(work / ".env.example")
        _step(steps, "Prepare the environment", "build_environment", "passed",
              f"Clean environment plus {len(documented_env)} documented variable(s) from .env.example.")

        shutil.copytree(change_dir, work, dirs_exist_ok=True)
        _step(steps, "Apply the code change", "task_context", "passed",
              f"Applied the known correct change for {task['id']}.")

        args = command.split()
        if args[0] in ("python", "python3"):
            args[0] = sys.executable
        env = {"PATH": "/usr/bin:/bin", "HOME": tmp, "PYTHONDONTWRITEBYTECODE": "1", **documented_env}
        try:
            done = subprocess.run(args, cwd=work, env=env, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
            output, code = (done.stdout + done.stderr)[-OUTPUT_LIMIT:], done.returncode
        except subprocess.TimeoutExpired:
            output, code = f"Timed out after {TIMEOUT_SECONDS} seconds", 124

    if code == 0:
        _step(steps, "Run the tests", "testing", "passed", f"{command} exited 0.", output)
        return _result("completed", steps, started)

    check_id, dimension = classify_output(output)
    _step(steps, "Run the tests", dimension, "blocked", f"{command} exited {code}.", output)
    return _result("blocked", steps, started, check_id, dimension)
