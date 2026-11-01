"""Runs the agents in the background, and the single route into gap analysis.

Every question about a gap, from an assessment or from a failed coding task, comes
through here. Known problems go straight to scripts. Only unknown ones reach the agent.
"""
import threading
from pathlib import Path

from . import agents, checks, ollama, probe, sandbox, simulation, store

ANALYSIS_REPLY_TOKENS = 5000

_thread = None
_lock = threading.Lock()


class JobError(RuntimeError):
    pass


def busy():
    return _thread is not None and _thread.is_alive()


def wait(timeout=30):
    if _thread:
        _thread.join(timeout)


def ollama_status():
    settings = store.get_settings()
    try:
        models = ollama.installed_models(settings["base_url"])
        usable = [m["name"] for m in models if m["usable"]]
        return {"connected": True, "error": None, "models": models, "settings": resolved(settings, models, usable),
                "sandbox": sandbox.available(), "running": busy()}
    except ollama.OllamaError as error:
        return {"connected": False, "error": str(error), "models": [], "settings": settings,
                "sandbox": sandbox.available(), "running": busy()}


def resolved(settings, models, usable):
    """Keeps a saved choice only while that model is still installed."""
    chosen = dict(settings)
    for role in ("gap_model", "coding_model"):
        if chosen[role] not in usable:
            chosen[role] = usable[0] if usable else ""
    return chosen


def live_settings():
    status = ollama_status()
    if not status["connected"]:
        raise JobError(status["error"])
    settings = status["settings"]
    if not settings["gap_model"]:
        raise JobError("No installed Ollama model can call tools.")
    settings["thinking_models"] = sorted(m["name"] for m in status["models"] if "thinking" in m["capabilities"])
    return settings


def _settings_for(settings, kind, model):
    """Spotting a contradiction needs reasoning, so analysis runs with thinking on. Coding stays fast."""
    if model not in settings["thinking_models"]:
        return {**settings, "think": None}
    if kind == "coding":
        return {**settings, "think": False}
    return {**settings, "think": True, "num_predict": max(settings["num_predict"], ANALYSIS_REPLY_TOKENS)}


def start(service, kind, source_run_id=None):
    if store.get_settings()["mode"] == "simulated":
        return start_simulated(service, kind, source_run_id)
    return start_real(service, kind, source_run_id)


def start_simulated(service, kind, source_run_id):
    global _thread
    with _lock:
        if busy():
            raise JobError("An agent is already running.")
        if not simulation.available(service):
            raise JobError("This service has no simulated data.")
        reason = simulation.blocked_reason(service, kind)
        if reason:
            raise JobError(reason)
        source = store.get_agent_run(source_run_id) if source_run_id else None
        if kind == "diagnose" and (source is None or "ticket" not in source["result"]):
            raise JobError("Choose a failed run with a Jira request.")
        title = TITLES[kind](service)
        run_id = store.create_agent_run(service["id"], kind, title, simulation.MODEL, source_run_id)
        _thread = threading.Thread(target=_run, args=(service, kind, run_id, {}, source, simulation.RUNNERS), daemon=True)
        _thread.start()
        return run_id


def start_real(service, kind, source_run_id):
    global _thread
    with _lock:
        if busy():
            raise JobError("An agent is already running.")
        if kind == "bug":
            raise JobError("The bug scenario exists only in Simulation mode.")
        settings = live_settings()
        if kind == "coding" and not sandbox.available():
            raise JobError("The sandbox is unavailable, so model-written code cannot run.")
        if kind == "coding" and not store.coding_task(service["id"]):
            raise JobError("This service has no coding task.")
        if kind == "gap" and not service["checks"]:
            raise JobError("Run the readiness checks first.")
        source = store.get_agent_run(source_run_id) if source_run_id else None
        if kind == "diagnose" and (source is None or source["kind"] != "coding" or source["service_id"] != service["id"]):
            raise JobError("Choose a coding run to diagnose.")
        model = settings["coding_model"] if kind == "coding" else settings["gap_model"]
        settings = _settings_for(settings, kind, model)
        run_id = store.create_agent_run(service["id"], kind, TITLES[kind](service), model, source_run_id)
        _thread = threading.Thread(target=_run, args=(service, kind, run_id, settings, source, RUNNERS), daemon=True)
        _thread.start()
        return run_id


def _run(service, kind, run_id, settings, source, runners):
    trace = []

    def record(entry):
        trace.append(entry)
        store.save_trace(run_id, trace)

    try:
        status, result = runners[kind](service, run_id, settings, source, record)
        store.finish_agent_run(run_id, status, result)
    except (ollama.OllamaError, sandbox.SandboxError, OSError) as error:
        store.finish_agent_run(run_id, "error", error=str(error))
    except Exception as error:  # A crashed run must never be left looking like it is still running.
        store.finish_agent_run(run_id, "error", error=f"Unexpected failure: {error}")


def _existing(service):
    open_rows = [f for f in store.list_findings(service_id=service["id"]) if f["status"] != "verified"]
    return open_rows, "\n".join(f"#{f['id']}: {f['title']}" for f in open_rows) or "None."


def run_gap(service, run_id, settings, _source, record):
    failed = "\n".join(f"- {c['title']}" for c in service["checks"] if not c["passed"]) or "None."
    open_rows, listing = _existing(service)
    prompt = (f"Service: {service['name']}, owned by {service['team']}.\n"
              f"Script checks that already failed, which you must not repeat:\n{failed}\n"
              f"Existing findings:\n{listing}\n"
              "Look for documentation or an API contract that exists but is wrong, misleading or contradicts the code. "
              "Compare README.md and any API contract with the source files.")
    report = agents.gap_analysis(settings, service["path"], prompt, {f["id"] for f in open_rows}, record)
    if report is None:
        return "failed", {"outcomes": [], "note": "The agent stopped without submitting a valid report."}
    outcomes = [store.record_agent_finding(service, p.model_dump(), run_id) for p in report.findings]
    return "completed", {"outcomes": outcomes}


def run_recheck(service, _run_id, settings, _source, record):
    """Quotes still in place settle the answer with no model call. A changed file goes to the agent."""
    outcomes = []
    workspace = sandbox.Workspace(service["path"])
    rows = [f for f in store.list_findings(service_id=service["id"]) if f["source"] != "script" and f["status"] != "verified"]
    for finding in rows:
        cited = [e for e in finding["evidence"] if e.get("kind") == "citation"]
        unchanged = cited and all(workspace.quote_in_file(e["ref"], e["detail"].strip("“”")) for e in cited)
        if unchanged:
            store.resolve_agent_finding(finding["id"], False, "The cited text has not changed.")
            outcomes.append({"id": finding["id"], "title": finding["title"], "action": "still_present", "by": "script"})
            continue
        answer = agents.recheck(settings, service["path"], finding, record)
        resolved_now = bool(answer and answer.status == "resolved")
        reason = answer.reason if answer else "The agent could not confirm the fix."
        store.resolve_agent_finding(finding["id"], resolved_now, reason)
        outcomes.append({"id": finding["id"], "title": finding["title"], "by": "agent", "reason": reason,
                         "action": "resolved" if resolved_now else "still_present"})
    return "completed", {"outcomes": outcomes}


def run_coding(service, _run_id, settings, _source, record):
    task = store.coding_task(service["id"])
    acceptance = Path(store.SAMPLES) / "coding_tasks" / service["id"] / "acceptance"
    verdict = agents.coding_task(settings, service["path"], task, acceptance, record)
    return ("passed" if verdict["passed"] else "failed"), {"task": task, **verdict}


def run_diagnose(service, run_id, settings, source, record):
    verdict = source["result"]
    output = verdict.get("test_output", "")
    check_id, dimension = probe.classify_output(output)
    if check_id:
        check = checks.CHECK_INDEX[check_id]
        passed, _evidence = check[4](checks.Repo(service["path"]))
        record({"step": 1, "tool": "run_check", "args": {"check_id": check_id}, "result": f"passed: {passed}"})
        outcome = store.add_failure_evidence(service, check_id, check[3], dimension, "blocker", check[5],
                                             f"Coding run {source['id']} failed with a known pattern.", output)
        return "completed", {"route": "script", "outcomes": [outcome]}
    open_rows, listing = _existing(service)
    steps = [f"{e.get('tool')}: {str(e.get('result') or e.get('note'))[:300]}" for e in source["trace"]][-10:]
    self_report = verdict.get("self_report")
    prompt = (f"A coding agent failed this task: {verdict.get('task', {}).get('description')}\n"
              f"Files it changed: {', '.join(verdict.get('changed_files', [])) or 'none'}\n"
              f"Its own report: {self_report}\nFinal test output:\n{output[-1800:]}\n"
              f"Last steps:\n" + "\n".join(steps) + f"\n\nExisting findings:\n{listing}\n"
              "Find the root cause in the repository. If an existing finding explains it, set existing_finding_id. "
              "If it was only the agent's own mistake and nothing in the repository contributed, return no findings.")
    report = agents.gap_analysis(settings, service["path"], prompt, {f["id"] for f in open_rows}, record)
    if report is None:
        return "failed", {"route": "agent", "outcomes": [], "note": "The agent stopped without submitting a valid report."}
    outcomes = [store.record_agent_finding(service, p.model_dump(), run_id) for p in report.findings]
    return "completed", {"route": "agent", "outcomes": outcomes}


RUNNERS = {"gap": run_gap, "recheck": run_recheck, "coding": run_coding, "diagnose": run_diagnose}
TITLES = {
    "gap": lambda s: f"Contextual review of {s['name']}",
    "recheck": lambda s: f"Recheck contextual findings on {s['name']}",
    "coding": lambda s: store.coding_task(s["id"])["title"] if store.coding_task(s["id"]) else "Coding task",
    "bug": lambda s: "Bug NOTIF-931: login codes rejected",
    "diagnose": lambda s: f"Diagnose a coding failure on {s['name']}",
}
