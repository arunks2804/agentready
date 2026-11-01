from app import jobs, ollama, simulation, store

SERVICE = "notifications-service"


def start(client, kind, source=None):
    response = client.post(f"/api/services/{SERVICE}/agent-runs", json={"kind": kind, "source_run_id": source})
    assert response.status_code == 202, response.text
    jobs.wait()
    return store.get_agent_run(response.json()["id"])


def agent_findings():
    return [f for f in store.list_findings(SERVICE) if f["source"] != "script"]


def fix_all(client):
    data = client.get(f"/api/services/{SERVICE}").json()
    for fix in data["fixes"]:
        client.post(f"/api/services/{SERVICE}/fixes/{fix['id']}/apply")


def setup(client, monkeypatch):
    monkeypatch.setattr(simulation, "STEP_SECONDS", 0)
    monkeypatch.setattr(ollama, "chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No model may be called")))
    store.save_settings({"mode": "simulated"})
    client.post(f"/api/services/{SERVICE}/assess")


def test_agreed_process_in_order(client, monkeypatch):
    setup(client, monkeypatch)
    gap = start(client, "gap")
    assert gap["model"] == "Simulated" and gap["result"]["simulated"] is True
    assert {e["provenance"] for f in agent_findings() for e in f["evidence"]} == {"simulated"}
    assert client.post(f"/api/services/{SERVICE}/agent-runs", json={"kind": "coding"}).status_code == 409
    for fix in ("2-test-command", "3-api-contract", "4-template-guide"):
        client.post(f"/api/services/{SERVICE}/fixes/{fix}/apply")
    client.post(f"/api/services/{SERVICE}/assess")
    start(client, "recheck")
    assert all(f["status"] == "verified" for f in agent_findings())
    assert start(client, "coding")["status"] == "passed"


def test_recheck_keeps_a_finding_open_without_its_fix(client, monkeypatch):
    setup(client, monkeypatch)
    start(client, "gap")
    start(client, "recheck")
    assert all(f["status"] != "verified" for f in agent_findings())


def test_bug_raises_ticket_exposes_gap_and_passes_after_fix(client, monkeypatch):
    setup(client, monkeypatch)
    failed = start(client, "bug")
    assert failed["status"] == "failed" and failed["result"]["ticket"]["key"] == "NOTIF-932"
    diagnosis = start(client, "diagnose", failed["id"])
    assert diagnosis["result"]["route"] == "ticket"
    gap = next(f for f in agent_findings() if "SMS sender" in f["title"])
    assert gap["owner_team"] == "team-messaging"
    client.post(f"/api/services/{SERVICE}/fixes/5-sms-setup/apply")
    start(client, "recheck")
    assert next(f for f in agent_findings() if f["id"] == gap["id"])["status"] == "verified"
    assert start(client, "bug")["status"] == "passed"


def test_real_mode_refuses_the_simulated_bug(client, monkeypatch):
    monkeypatch.setattr(ollama, "installed_models", lambda _url: [])
    store.save_settings({"mode": "real"})
    client.post(f"/api/services/{SERVICE}/assess")
    response = client.post(f"/api/services/{SERVICE}/agent-runs", json={"kind": "bug"})
    assert response.status_code == 409
