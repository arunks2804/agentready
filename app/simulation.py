"""Prepared agent and Jira results for the demo. Nothing here calls a model or Jira.

Every run from this module is stored with the model name "Simulated", and the screens
label it. Script checks, prepared fixes and reassessment stay real.
"""
import json
import time

from . import store

MODEL = "Simulated"
STEP_SECONDS = 0.5


def _data(service):
    return json.loads((store.SAMPLES / "simulation" / f"{service['id']}.json").read_text(encoding="utf-8"))


def available(service):
    return (store.SAMPLES / "simulation" / f"{service['id']}.json").is_file()


def _play(trace, record):
    for number, entry in enumerate(trace, 1):
        time.sleep(STEP_SECONDS)
        record({"step": number, **entry})


def _applied(service):
    return {cite for fix in service["fixes"] if fix["applied"] for cite in fix["cites"]}


def blocked_reason(service, kind):
    """The agreed order: fix and reassess first, then the Coding Agent."""
    pending = [f for f in service["findings"] if f["source"] != "script" and f["status"] != "verified"]
    if kind == "coding" and pending:
        return "Fix the findings and reassess before the Coding Agent runs."
    return None


def run_gap(service, run_id, _settings, _source, record):
    data = _data(service)["gap"]
    _play(data["trace"], record)
    proposals = [{**p, "provenance": "simulated"} for p in data["findings"]]
    return "completed", {"simulated": True, "outcomes": [store.record_agent_finding(service, p, run_id) for p in proposals]}


def run_recheck(service, _run_id, _settings, _source, record):
    applied = _applied(service)
    outcomes = []
    rows = [f for f in store.list_findings(service_id=service["id"]) if f["source"] != "script" and f["status"] != "verified"]
    for number, finding in enumerate(rows, 1):
        done = any(e.get("ref") in applied for e in finding["evidence"])
        reason = "Simulated check: the prepared fix is in the repository." if done else "Simulated check: no fix applied."
        store.resolve_agent_finding(finding["id"], done, reason)
        record({"step": number, "tool": "recheck", "result": f"{finding['title']}: {reason}"})
        outcomes.append({"id": finding["id"], "title": finding["title"], "action": "resolved" if done else "still_present", "by": "simulation"})
    return "completed", {"simulated": True, "outcomes": outcomes}


def run_coding(service, _run_id, _settings, _source, record):
    data = _data(service)["coding"]
    _play(data["trace"], record)
    return "passed", {"simulated": True, **data["result"]}


def run_bug(service, _run_id, _settings, _source, record):
    data = _data(service)["bug"]
    fixed = "SMS sender setup" in _applied(service)
    _play(data["passed_trace" if fixed else "failed_trace"], record)
    return ("passed" if fixed else "failed"), {
        "simulated": True, "task": data["task"], **data["passed_result" if fixed else "failed_result"]}


def run_diagnose(service, run_id, _settings, source, record):
    data = _data(service)["bug"]
    ticket = source["result"]["ticket"]
    _play([
        {"tool": "read_ticket", "args": {"path": ticket["key"]}, "result": f"Simulated: read {ticket['key']}."},
        {"tool": "search", "args": {"text": "sender"}, "result": "Simulated: no SMS sender documentation found."},
    ], record)
    outcome = store.record_agent_finding(service, {**data["finding"], "provenance": "simulated"}, run_id)
    return "completed", {"simulated": True, "route": "ticket", "ticket": ticket["key"], "outcomes": [outcome]}


RUNNERS = {"gap": run_gap, "recheck": run_recheck, "coding": run_coding, "bug": run_bug, "diagnose": run_diagnose}
