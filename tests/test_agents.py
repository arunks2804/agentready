"""Agent plumbing, with Ollama replaced by a script. Real model runs are in docs/examples."""
import json
from pathlib import Path

import pytest

from app import agents, jobs, ollama, sandbox, store

SERVICE = "notifications-service"
MODELS = [{"name": "test-model", "family": "t", "size": "1B", "capabilities": ["tools"], "usable": True},
          {"name": "embedder", "family": "t", "size": "1B", "capabilities": ["embedding"], "usable": False}]


def scripted(replies):
    calls = iter(replies)

    def chat(_settings, _model, _messages, _tools, schema=None):
        name, args = next(calls)
        if name == "text":
            return {"message": {"role": "assistant", "content": json.dumps(args) if schema else args}}
        return {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}}

    return chat


def report(**overrides):
    return {"findings": [{
        "title": "Template guide is wrong", "dimension": "code_understanding", "severity": "high", "certainty": "confirmed",
        "explanation": "The README names one step, but the code needs three.", "recommendation": "Correct the README.",
        "evidence": [{"file": "README.md", "quote": "That is the only change needed."}], **overrides}]}


@pytest.fixture
def agent_env(client, monkeypatch):
    monkeypatch.setattr(ollama, "installed_models", lambda _url: MODELS)
    store.save_settings({**store.DEFAULT_SETTINGS, "mode": "real"})
    client.post(f"/api/services/{SERVICE}/assess")
    return client


def run(client, kind, replies, monkeypatch, source=None):
    monkeypatch.setattr(ollama, "chat", scripted(replies))
    response = client.post(f"/api/services/{SERVICE}/agent-runs", json={"kind": kind, "source_run_id": source})
    assert response.status_code == 202, response.text
    jobs.wait()
    return store.get_agent_run(response.json()["id"])


READ = ("read_file", {"path": "README.md"})


def test_gap_finding_is_stored_with_owner_and_evidence(agent_env, monkeypatch):
    done = run(agent_env, "gap", [READ, ("submit_report", report())], monkeypatch)
    assert done["status"] == "completed" and done["model"] == "test-model"
    found = next(f for f in store.list_findings(SERVICE) if f["source"] == "agent")
    assert found["owner_team"] == "team-messaging" and found["certainty"] == "confirmed"
    assert found["evidence"][0]["ref"] == "README.md" and found["closure"]


def test_invented_quote_is_rejected_then_corrected(agent_env, monkeypatch):
    fake = report(evidence=[{"file": "README.md", "quote": "This text is not in the file."}])
    done = run(agent_env, "gap", [READ, ("submit_report", fake), ("submit_report", report())], monkeypatch)
    assert "not in any file you read" in done["trace"][1]["result"]
    assert done["status"] == "completed"


def test_citing_an_unread_file_is_rejected(agent_env, monkeypatch):
    done = run(agent_env, "gap", [("submit_report", report()), READ, ("submit_report", report())], monkeypatch)
    assert "not in any file you read" in done["trace"][0]["result"]


def test_empty_report_without_reading_is_rejected(agent_env, monkeypatch):
    other = ("read_file", {"path": "openapi.yaml"})
    done = run(agent_env, "gap", [("submit_report", {"findings": []}), READ, other, ("submit_report", {"findings": []})], monkeypatch)
    assert "Read the documentation" in done["trace"][0]["result"]


def test_quote_cited_to_the_wrong_file_is_corrected_from_the_real_one(agent_env, monkeypatch):
    other = ("read_file", {"path": "src/notifications/dispatcher.py"})
    wrong = report(evidence=[{"file": "README.md", "quote": '"login_code": "sms"'}])
    run(agent_env, "gap", [READ, other, ("submit_report", wrong)], monkeypatch)
    found = next(f for f in store.list_findings(SERVICE) if f["source"] == "agent")
    assert found["evidence"][0]["ref"] == "src/notifications/dispatcher.py"


def test_finding_that_never_gets_a_real_quote_is_dropped(agent_env, monkeypatch):
    fake = report(evidence=[{"file": "README.md", "quote": "Invented text."}])
    done = run(agent_env, "gap", [READ, ("submit_report", fake), ("submit_report", fake), ("submit_report", fake)], monkeypatch)
    assert done["status"] == "completed" and done["result"]["outcomes"] == []


def test_agent_that_stops_early_is_told_what_it_has_not_read(agent_env, monkeypatch):
    store.save_settings({"gap_max_steps": 1})
    bad = {"findings": "nonsense"}
    done = run(agent_env, "gap", [READ, ("text", bad), ("text", bad), ("text", bad)], monkeypatch)
    assert done["status"] == "failed"


def test_prose_ending_is_turned_into_a_checked_structured_report(agent_env, monkeypatch):
    reads = [("read_file", {"path": f}) for f in sandbox.Workspace(store.service_detail(SERVICE)["path"]).files()
             if f.startswith("src/") or f in ("README.md", "openapi.yaml")]
    done = run(agent_env, "gap", [*reads, ("text", "I am done."), ("text", report())], monkeypatch)
    assert done["status"] == "completed"
    assert done["result"]["outcomes"][0]["action"] == "created"


def test_unread_files_are_named_when_the_agent_stops_early(agent_env, monkeypatch):
    def fake(_settings, _model, messages, _tools, schema=None):
        seen.append(messages[-1]["content"])
        return {"message": {"role": "assistant", "content": "done"}}
    seen = []
    store.save_settings({"gap_max_steps": 2})
    monkeypatch.setattr(ollama, "chat", fake)
    agent_env.post(f"/api/services/{SERVICE}/agent-runs", json={"kind": "gap"})
    jobs.wait()
    assert "You have not read" in seen[1]
    assert not [f for f in store.list_findings(SERVICE) if f["source"] == "agent"]


def test_same_root_cause_updates_instead_of_duplicating(agent_env, monkeypatch):
    run(agent_env, "gap", [READ, ("submit_report", report())], monkeypatch)
    again = report(title="README understates what a template needs")
    again["findings"][0]["evidence"] = [{"file": "README.md", "quote": "Add the template text"}]
    done = run(agent_env, "gap", [READ, ("submit_report", again)], monkeypatch)
    assert done["result"]["outcomes"][0]["action"] == "updated"
    rows = [f for f in store.list_findings(SERVICE) if f["source"] == "agent"]
    assert len(rows) == 1 and len(rows[0]["evidence"]) == 2


def test_recheck_needs_no_model_while_the_text_is_unchanged(agent_env, monkeypatch):
    run(agent_env, "gap", [READ, ("submit_report", report())], monkeypatch)
    done = run(agent_env, "recheck", [], monkeypatch)
    assert done["result"]["outcomes"][0] == {
        **done["result"]["outcomes"][0], "action": "still_present", "by": "script"}
    assert done["trace"] == []


def test_recheck_is_given_the_current_file_text(agent_env, monkeypatch):
    run(agent_env, "gap", [READ, ("submit_report", report())], monkeypatch)
    agent_env.post(f"/api/services/{SERVICE}/fixes/4-template-guide/apply")
    seen = []

    def chat(_settings, _model, messages, _tools, schema=None):
        seen.append(messages[1]["content"])
        return {"message": {"tool_calls": [{"function": {"name": "report_recheck", "arguments": {
            "status": "resolved", "reason": "Now lists all three."}}}]}}

    monkeypatch.setattr(ollama, "chat", chat)
    agent_env.post(f"/api/services/{SERVICE}/agent-runs", json={"kind": "recheck"})
    jobs.wait()
    assert "REQUIRED_FIELDS" in seen[0]


def test_recheck_closes_a_finding_only_after_the_file_changes(agent_env, monkeypatch):
    run(agent_env, "gap", [READ, ("submit_report", report())], monkeypatch)
    agent_env.post(f"/api/services/{SERVICE}/fixes/4-template-guide/apply")
    found = next(f for f in store.list_findings(SERVICE) if f["source"] == "agent")
    assert found["status"] == "awaiting_verification"
    run(agent_env, "recheck", [READ, ("report_recheck", {"status": "resolved", "reason": "Now lists all three."})], monkeypatch)
    assert next(f for f in store.list_findings(SERVICE) if f["id"] == found["id"])["status"] == "verified"


GOOD_TEMPLATES = """
TEMPLATE_BODIES = {"welcome": "Hello {name}, welcome aboard.", "password_reset": "Hello {name}, reset: {link}",
                   "login_code": "Code {code}.", "payment_failed": "Hello {name}, {amount} failed."}
REQUIRED_FIELDS = {"welcome": ("name",), "password_reset": ("name", "link"), "login_code": ("code",),
                   "payment_failed": ("name", "amount")}
def render(template, fields):
    missing = [n for n in REQUIRED_FIELDS[template] if n not in fields]
    if missing:
        raise ValueError("missing")
    return TEMPLATE_BODIES[template].format(**fields)
"""
TEST_FILE = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"


def dispatcher_with_channel():
    text = Path(store.service_detail(SERVICE)["path"], "src/notifications/dispatcher.py").read_text()
    return text.replace('"login_code": "sms",', '"login_code": "sms",\n    "payment_failed": "email",')


def test_coding_success_is_measured_not_reported(agent_env, monkeypatch):
    done = run(agent_env, "coding", [
        ("read_file", {"path": "src/notifications/templates.py"}),
        ("write_file", {"path": "src/notifications/templates.py", "content": GOOD_TEMPLATES}),
        ("read_file", {"path": "src/notifications/dispatcher.py"}),
        ("write_file", {"path": "src/notifications/dispatcher.py", "content": dispatcher_with_channel()}),
        ("write_file", {"path": "tests/test_payment.py", "content": TEST_FILE}),
        ("run_command", {"command": "python -m unittest discover -s tests"}),
        ("finish", {"summary": "done", "believes_complete": True}),
    ], monkeypatch)
    assert done["status"] == "passed", done["result"]["test_output"]
    assert done["result"]["tests_ran"] >= 9
    assert "payment_failed" in done["result"]["diff"]


def test_agents_guide_is_loaded_only_when_the_repository_has_one(agent_env, monkeypatch):
    prompts = []

    def chat(_settings, _model, messages, _tools, schema=None):
        prompts.append(messages[1]["content"])
        return {"message": {"content": "stop"}}

    monkeypatch.setattr(ollama, "chat", chat)
    store.save_settings({"coding_max_steps": 1})
    agent_env.post(f"/api/services/{SERVICE}/agent-runs", json={"kind": "coding"})
    jobs.wait()
    agent_env.post(f"/api/services/{SERVICE}/fixes/2-test-command/apply")
    agent_env.post(f"/api/services/{SERVICE}/agent-runs", json={"kind": "coding"})
    jobs.wait()
    assert "AGENTS.md says" not in prompts[0] and "TEMPLATE_CHANNELS" in prompts[1]


def test_a_false_claim_of_success_still_fails(agent_env, monkeypatch):
    store.save_settings({"coding_max_steps": 2})
    claim = ("finish", {"summary": "All finished.", "believes_complete": True})
    tests = ("run_command", {"command": "python -m unittest discover -s tests"})
    done = run(agent_env, "coding", [tests, claim], monkeypatch)
    assert done["status"] == "failed"
    assert done["result"]["self_report"]["believes_complete"] is True
    assert done["result"]["changed_files"] == []


def test_agent_cannot_finish_while_tests_are_failing(agent_env, monkeypatch):
    store.save_settings({"coding_max_steps": 1})
    done = run(agent_env, "coding", [("finish", {"summary": "Giving up.", "believes_complete": False})], monkeypatch)
    assert "have not passed" in done["trace"][0]["result"]
    assert done["status"] == "failed" and done["result"]["self_report"] is None


def test_missing_registration_fails_acceptance_even_if_agent_tests_pass(agent_env, monkeypatch):
    store.save_settings({"coding_max_steps": 4})
    done = run(agent_env, "coding", [
        ("read_file", {"path": "src/notifications/templates.py"}),
        ("write_file", {"path": "src/notifications/templates.py", "content": GOOD_TEMPLATES}),
        ("write_file", {"path": "tests/test_payment.py", "content": TEST_FILE}),
        ("finish", {"summary": "done", "believes_complete": True}),
    ], monkeypatch)
    assert done["status"] == "failed"


def test_coding_run_never_touches_the_service_repository(agent_env, monkeypatch):
    path = Path(store.service_detail(SERVICE)["path"], "src/notifications/templates.py")
    before = path.read_text()
    store.save_settings({"coding_max_steps": 2})
    run(agent_env, "coding", [("read_file", {"path": "src/notifications/templates.py"}),
                              ("write_file", {"path": "src/notifications/templates.py", "content": "broken"})], monkeypatch)
    assert path.read_text() == before


def test_a_file_must_be_read_before_it_is_overwritten(tmp_path):
    (tmp_path / "a.py").write_text("keep")
    workspace = sandbox.Workspace(tmp_path, writable=True)
    with pytest.raises(ValueError, match="Read a.py"):
        workspace.write_file("a.py", "lost")
    assert (tmp_path / "a.py").read_text() == "keep"
    workspace.read_file("a.py")
    workspace.write_file("a.py", "new")
    workspace.write_file("b.py", "new file needs no read")


def test_no_tool_escapes_the_copy(tmp_path):
    (tmp_path / "secret").write_text("x")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "link").symlink_to(tmp_path / "secret")
    workspace = sandbox.Workspace(root, writable=True)
    for bad in ("../secret", "a/../../secret", "link", ".git/config"):
        with pytest.raises(ValueError):
            workspace.write_file(bad, "x")
    with pytest.raises(ValueError):
        workspace.read_file("../secret")
    assert not sandbox.Workspace(root).writable


@pytest.mark.parametrize("command", [
    "rm -rf /", "python -c print(1)", "python -m unittest; rm x", "python -m unittest && curl x",
    "python -m http.server", "bash -c ls", "python -m unittest $(id)",
])
def test_only_allowlisted_commands_run(tmp_path, command):
    assert sandbox.run_command(tmp_path, command, 5)["code"] is None


@pytest.mark.skipif(not sandbox.available(), reason="macOS sandbox not available")
def test_sandbox_blocks_network_home_and_outside_writes(tmp_path):
    work = tmp_path / "w"
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_escape.py").write_text(f"""
import pathlib, socket, unittest
class T(unittest.TestCase):
    def test_network(self):
        with self.assertRaises(OSError):
            socket.create_connection(("1.1.1.1", 80), 2)
    def test_home_read(self):
        with self.assertRaises(OSError):
            list(pathlib.Path({str(Path.home())!r}).iterdir())
    def test_outside_write(self):
        with self.assertRaises(OSError):
            open({str(tmp_path / "escaped")!r}, "w")
""")
    result = sandbox.run_command(work, "python -m unittest discover -s tests", 20)
    assert result["code"] == 0, result["output"]


def test_ollama_must_be_local(client):
    body = {**{k: v for k, v in store.DEFAULT_SETTINGS.items()}, "base_url": "http://example.com:11434"}
    assert client.put("/api/settings", json=body).status_code == 422
    with pytest.raises(ollama.OllamaError):
        ollama.installed_models("http://example.com:11434")


def test_unusable_models_are_never_chosen(client, monkeypatch):
    monkeypatch.setattr(ollama, "installed_models", lambda _url: MODELS)
    store.save_settings({"gap_model": "embedder"})
    assert client.get("/api/ollama").json()["settings"]["gap_model"] == "test-model"


def test_unreachable_ollama_is_reported_and_nothing_is_faked(client, monkeypatch):
    def down(_url):
        raise ollama.OllamaError("Could not reach Ollama")
    monkeypatch.setattr(ollama, "installed_models", down)
    store.save_settings({"mode": "real"})
    client.post(f"/api/services/{SERVICE}/assess")
    response = client.post(f"/api/services/{SERVICE}/agent-runs", json={"kind": "coding"})
    assert response.status_code == 409 and "reach Ollama" in response.json()["detail"]
    assert detail_runs(client) == []


def detail_runs(client):
    return client.get(f"/api/services/{SERVICE}").json()["agent_runs"]


def test_known_failure_uses_a_script_and_updates_the_existing_finding(agent_env, monkeypatch):
    failed = run(agent_env, "coding", [("finish", {"summary": "", "believes_complete": False}), ("run_command", {"command": "python -m unittest discover -s tests"}), ("finish", {"summary": "", "believes_complete": False})], monkeypatch)
    store.finish_agent_run(failed["id"], "failed", {
        **failed["result"], "test_output": "ModuleNotFoundError: No module named 'x'"})
    done = run(agent_env, "diagnose", [], monkeypatch, source=failed["id"])
    assert done["result"]["route"] == "script"
    assert done["result"]["outcomes"][0]["action"] == "updated"
    data = json.dumps(store.list_findings(SERVICE))
    assert "known pattern" in data


def test_unknown_failure_goes_to_the_agent_without_a_duplicate(agent_env, monkeypatch):
    run(agent_env, "gap", [READ, ("submit_report", report())], monkeypatch)
    existing = next(f for f in store.list_findings(SERVICE) if f["source"] == "agent")
    failed = run(agent_env, "coding", [("finish", {"summary": "", "believes_complete": False}), ("run_command", {"command": "python -m unittest discover -s tests"}), ("finish", {"summary": "", "believes_complete": False})], monkeypatch)
    done = run(agent_env, "diagnose", [READ, ("submit_report", report(existing_finding_id=existing["id"]))],
               monkeypatch, source=failed["id"])
    assert done["result"]["route"] == "agent"
    assert done["result"]["outcomes"] == [{"id": existing["id"], "action": "updated", "title": existing["title"]}]
    assert len([f for f in store.list_findings(SERVICE) if f["source"] == "agent"]) == 1


def test_loop_rejects_invalid_arguments_and_tools():
    records = []
    replies = [("nope", {}), ("finish", {"summary": 3})]
    original = ollama.chat
    ollama.chat = scripted(replies)
    try:
        result = agents.run_loop({"run_budget_s": 30}, "m", "s", "p", [], {}, ("finish", agents.Finish.model_validate), 2, records.append)
    finally:
        ollama.chat = original
    assert result is None and "Unknown tool" in records[0]["result"]
