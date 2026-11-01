"""The Gap Analysis Agent and the Coding Agent: one bounded tool loop, two sets of permissions.

Neither agent gets a shell. Each has an explicit tool list, a step limit and a time
limit. What they report is checked afterwards against files and test results.
"""
import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from . import checks, ollama, sandbox

RESULT_LIMIT = 5000
MAX_REPORT_ATTEMPTS = 3
BASELINE_TEST_COMMAND = "python -m unittest discover -s tests"


def _tool(name, description, properties, required=None):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required or list(properties)},
    }}


STRING = {"type": "string"}
READ_TOOLS = [
    _tool("list_files", "List the repository's files.", {"path": STRING}, []),
    _tool("read_file", "Read one file.", {"path": STRING}),
    _tool("search", "Find a piece of text across the repository.", {"text": STRING}),
]


def run_loop(settings, model, system, prompt, tools, handlers, finish, max_steps, record, nudge=None, conclude=None):
    """Returns the validated finish arguments, or None if the agent never finished.

    nudge says what is still missing when the agent stops calling tools. Once nothing
    is missing, or the steps run out, conclude asks for the structured result directly.
    """
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    deadline = time.monotonic() + settings["run_budget_s"]
    for step in range(1, max_steps + 1):
        if time.monotonic() > deadline:
            record({"step": step, "tool": None, "note": "Stopped: run time budget used up."})
            return conclude(messages, step) if conclude else None
        started = time.monotonic()
        reply = ollama.chat(settings, model, messages, tools)
        message = reply.get("message", {})
        call_ms = round((time.monotonic() - started) * 1000)
        calls = message.get("tool_calls") or []
        messages.append({k: message[k] for k in ("role", "content", "tool_calls") if k in message})
        if not calls:
            record({"step": step, "tool": None, "note": (message.get("content") or "").strip()[:1500], "ms": call_ms})
            missing = nudge() if nudge else None
            if conclude and not missing:
                return conclude(messages, step)
            messages.append({"role": "user", "content": missing or "Use a tool. Call the finishing tool when you are done."})
            continue
        for call in calls:
            name = call["function"]["name"]
            args = call["function"].get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            try:
                if name == finish[0]:
                    result = finish[1](args)
                    record({"step": step, "tool": name, "args": args, "result": "Accepted.", "ms": call_ms})
                    return result
                if name not in handlers:
                    raise ValueError(f"Unknown tool {name}.")
                output = str(handlers[name](args))
            except (ValueError, KeyError, TypeError, ValidationError) as error:
                output = f"Error: {error}"
            record({"step": step, "tool": name, "args": args, "result": output[:RESULT_LIMIT], "ms": call_ms})
            messages.append({"role": "tool", "tool_name": name, "content": output[:RESULT_LIMIT]})
    record({"step": max_steps, "tool": None, "note": f"Stopped: reached the limit of {max_steps} steps."})
    return conclude(messages, max_steps) if conclude else None


# Gap Analysis Agent

class Citation(BaseModel):
    file: str = Field(min_length=1, max_length=300)
    quote: str = Field(min_length=3, max_length=400)


class ProposedFinding(BaseModel):
    title: str = Field(min_length=5, max_length=160)
    dimension: Literal["discovery", "code_understanding", "api_context", "build_environment",
                       "testing", "debugging", "delivery", "task_context"]
    severity: Literal["blocker", "high", "medium", "low"]
    certainty: Literal["confirmed", "hypothesis"]
    explanation: str = Field(min_length=10, max_length=900)
    recommendation: str = Field(min_length=5, max_length=600)
    evidence: list[Citation] = Field(min_length=1, max_length=6)
    existing_finding_id: int | None = None


class Report(BaseModel):
    findings: list[ProposedFinding] = Field(max_length=6)


GAP_SYSTEM = """You are the Gap Analysis Agent in AgentReady. Scripts have already checked objective facts such as whether files exist.
Your job is what scripts cannot judge: whether the documentation and API contract are correct and usable by a coding agent.
Method: read the docs, the API contract and every source file. Then go through each specific claim the docs and the contract make, including how to change the service, what values are allowed and what responses contain, and test that claim against the code. A claim the code contradicts is a finding.
Rules:
- Report only problems you can support. Every citation must quote one line copied exactly from a file you read.
- Use certainty "confirmed" when the quotes prove the problem, and "hypothesis" when they only suggest it.
- If an existing finding already covers the same root cause, set existing_finding_id to it instead of reporting a new one.
- Do not report anything that the script results already cover.
- Finish by calling submit_report, even if the list of findings is empty."""

SUBMIT_TOOL = _tool("submit_report", "Submit structured findings and finish.", {"findings": {
    "type": "array", "items": {"type": "object", "properties": {
        "title": STRING,
        "dimension": {"type": "string", "enum": [key for key, _ in checks.DIMENSIONS]},
        "severity": {"type": "string", "enum": ["blocker", "high", "medium", "low"]},
        "certainty": {"type": "string", "enum": ["confirmed", "hypothesis"]},
        "explanation": STRING, "recommendation": STRING, "existing_finding_id": {"type": "integer"},
        "evidence": {"type": "array", "items": {"type": "object", "properties": {"file": STRING, "quote": STRING}}},
    }}}})
RUN_CHECK_TOOL = _tool("run_check", f"Run one approved readiness script. Choose from: {', '.join(checks.CHECK_INDEX)}.",
                       {"check_id": STRING})
RUN_TESTS_TOOL = _tool("run_tests", "Run the service's unit tests in an isolated copy.", {})


def _gap_handlers(repo_path, workspace, settings):
    def run_check(args):
        check = checks.CHECK_INDEX[args["check_id"]]
        passed, evidence = check[4](checks.Repo(repo_path))
        return json.dumps({"passed": passed, "evidence": [e["detail"] for e in evidence]})

    def run_tests(_args):
        with tempfile.TemporaryDirectory(prefix="agentready-gap-") as tmp:
            work = sandbox.copy_repo(repo_path, Path(tmp) / "repo")
            result = sandbox.run_command(work, BASELINE_TEST_COMMAND, settings["test_timeout_s"])
        return f"exit {result['code']}\n{result['output']}"

    return {
        "list_files": lambda a: workspace.list_files(a.get("path", "")),
        "read_file": lambda a: workspace.read_file(a["path"]),
        "search": lambda a: workspace.search(a["text"]),
        "run_check": run_check, "run_tests": run_tests,
    }


def gap_analysis(settings, repo_path, prompt, existing_ids, record):
    """Returns proposed findings. Citations that do not check out are sent back to the agent."""
    workspace = sandbox.Workspace(repo_path)

    attempts = []

    def citation_problem(citation):
        """A quote found in another file the agent read is corrected. An invented one is never accepted."""
        if citation.file in workspace.read_paths and workspace.quote_in_file(citation.file, citation.quote):
            return None
        for other in sorted(workspace.read_paths):
            if workspace.quote_in_file(other, citation.quote):
                citation.file = other
                return None
        return f"This quote is not in any file you read: {citation.quote}"

    def finish(args):
        rows = args.get("findings") if isinstance(args, dict) else None
        for item in rows if isinstance(rows, list) else []:
            if isinstance(item, dict) and not item.get("existing_finding_id"):
                item.pop("existing_finding_id", None)
        report = Report.model_validate(args)
        attempts.append(1)
        if not report.findings and len(workspace.read_paths) < 2:
            raise ValueError("Read the documentation and the source code before you report.")
        problems, valid = [], []
        for finding in report.findings:
            found = [p for c in finding.evidence if (p := citation_problem(c))]
            if finding.existing_finding_id is not None and finding.existing_finding_id not in existing_ids:
                found.append(f"Finding {finding.existing_finding_id} does not exist.")
            problems += found
            if not found:
                valid.append(finding)
        if problems and len(attempts) < MAX_REPORT_ATTEMPTS:
            raise ValueError("Report rejected. Copy quotes exactly from the file. " + " ".join(problems))
        return Report(findings=valid)

    def unread():
        wanted = [f for f in workspace.files() if f.startswith("src/") or f.lower() == "readme.md" or "openapi" in f]
        left = [f for f in wanted if f not in workspace.read_paths]
        return f"You have not read these files yet: {', '.join(left)}. Read them with read_file." if left else None

    def conclude(messages, step):
        """Asks for the report as schema-bound JSON. Its quotes face the same checks as a tool call."""
        messages.append({"role": "user", "content": "Now give your final report. Each quote must be one line copied exactly."})
        for attempt in range(1, MAX_REPORT_ATTEMPTS + 1):
            started = time.monotonic()
            reply = ollama.chat(settings, settings["gap_model"], messages, [], schema=Report.model_json_schema())
            content = reply.get("message", {}).get("content") or ""
            entry = {"step": step + attempt, "tool": "submit_report", "ms": round((time.monotonic() - started) * 1000)}
            try:
                report = finish(json.loads(content))
                record({**entry, "args": {"findings": len(report.findings)}, "result": "Accepted."})
                return report
            except (ValueError, TypeError) as error:
                record({**entry, "result": f"Error: {error}"[:RESULT_LIMIT]})
                messages.append({"role": "user", "content": f"That report was rejected: {error}"[:RESULT_LIMIT]})
        return None

    tools = [*READ_TOOLS, RUN_CHECK_TOOL, RUN_TESTS_TOOL, SUBMIT_TOOL]
    handlers = _gap_handlers(repo_path, workspace, settings)
    return run_loop(settings, settings["gap_model"], GAP_SYSTEM, prompt, tools, handlers,
                    ("submit_report", finish), settings["gap_max_steps"], record, nudge=unread, conclude=conclude)


class Recheck(BaseModel):
    status: Literal["resolved", "still_present"]
    reason: str = Field(min_length=5, max_length=600)


def recheck(settings, repo_path, finding, record):
    """Used only when a cited file changed, so the old quotes can no longer settle the question."""
    workspace = sandbox.Workspace(repo_path)
    cited = sorted({e["ref"] for e in finding["evidence"] if e.get("ref")})
    current = "\n\n".join(f"--- {rel} ---\n{workspace.read_file(rel)}" for rel in cited)
    prompt = (f"A finding was reported: {finding['title']}\nDetail: {finding['explanation']}\n\n"
              f"These are the cited files as they are now. Judge only from this text, not from the finding's wording:\n{current}\n\n"
              "Has the problem gone? Call report_recheck.")
    tool = _tool("report_recheck", "Report whether the problem is gone.",
                 {"status": {"type": "string", "enum": ["resolved", "still_present"]}, "reason": STRING})
    handlers = {"read_file": lambda a: workspace.read_file(a["path"]), "search": lambda a: workspace.search(a["text"])}
    return run_loop(settings, settings["gap_model"], GAP_SYSTEM.split("Rules:")[0], prompt,
                    [*READ_TOOLS[1:], tool], handlers, ("report_recheck", Recheck.model_validate),
                    settings["gap_max_steps"], record)


# Coding Agent

CODING_SYSTEM = """You are a coding agent working in an isolated copy of a repository.
Read the repository's documentation and code, make the change, then run the tests. If they fail, read the error and fix it.
To change a file, call write_file with its complete new content, including everything you are keeping.
Tests run with run_command. Find the right command in the repository's documentation. Only Python test commands are allowed.
When you are finished, call finish with a short summary and whether you believe the task is complete."""

CODING_TOOLS = [
    *READ_TOOLS,
    _tool("write_file", "Replace a file with new content, or create it.", {"path": STRING, "content": STRING}),
    _tool("run_command", "Run an allowed test command, such as python -m unittest.", {"command": STRING}),
    _tool("finish", "Finish the task.", {"summary": STRING, "believes_complete": {"type": "boolean"}}),
]


class Finish(BaseModel):
    summary: str = Field(default="", max_length=1000)
    believes_complete: bool = False


def verify(work, acceptance_dir, original, settings):
    """AgentReady's own verdict. It reads the diff and runs the tests itself; the model's report plays no part."""
    changed, diff = sandbox.repo_diff(original, work)
    source_changed = any(f.startswith("src/") for f in changed)
    test_changed = any(f.startswith("tests/") for f in changed)
    if source_changed:
        shutil.copytree(acceptance_dir, Path(work) / "tests", dirs_exist_ok=True)
    result = sandbox.run_command(work, BASELINE_TEST_COMMAND, settings["test_timeout_s"])
    ran = re.search(r"Ran (\d+) tests?", result["output"])
    checks_list = [
        {"name": "Source code changed", "passed": source_changed},
        {"name": "A test was added or changed", "passed": test_changed},
        {"name": "All tests pass, including AgentReady's acceptance tests", "passed": source_changed and result["code"] == 0},
    ]
    return {
        "passed": all(c["passed"] for c in checks_list), "checks": checks_list, "changed_files": changed, "diff": diff,
        "test_exit": result["code"], "test_output": result["output"], "tests_ran": int(ran.group(1)) if ran else 0,
    }


def coding_task(settings, repo_path, task, acceptance_dir, record):
    with tempfile.TemporaryDirectory(prefix="agentready-coding-") as tmp:
        original = sandbox.copy_repo(repo_path, Path(tmp) / "original")
        work = sandbox.copy_repo(repo_path, Path(tmp) / "work")
        workspace = sandbox.Workspace(work, writable=True)

        last_exit = []

        def run_command(args):
            result = sandbox.run_command(work, args["command"], settings["test_timeout_s"])
            if result["code"] is not None:
                last_exit[:] = [result["code"]]
            return f"exit {result['code']}\n{result['output']}"

        def finish(args):
            """An agent with steps left keeps working. This steers it only; verify() still decides the result."""
            if last_exit != [0]:
                raise ValueError("The tests have not passed yet. Read the error, change the code and run them again.")
            return Finish.model_validate(args)

        handlers = {
            "list_files": lambda a: workspace.list_files(a.get("path", "")),
            "read_file": lambda a: workspace.read_file(a["path"]),
            "search": lambda a: workspace.search(a["text"]),
            "write_file": lambda a: workspace.write_file(a["path"], a["content"]),
            "run_command": run_command,
        }
        prompt = f"Task {task['id']}: {task['title']}\n\n{task['description']}"
        guide = Path(work) / "AGENTS.md"
        if guide.is_file():  # Coding agents load this file on start, which is the reason it exists.
            prompt += f"\n\nThe repository's AGENTS.md says:\n{guide.read_text(encoding='utf-8')[:sandbox.MAX_FILE_BYTES]}"
        final = run_loop(settings, settings["coding_model"], CODING_SYSTEM, prompt, CODING_TOOLS, handlers,
                         ("finish", finish), settings["coding_max_steps"], record)
        verdict = verify(work, acceptance_dir, original, settings)
    verdict["self_report"] = final.model_dump() if final else None
    return verdict
