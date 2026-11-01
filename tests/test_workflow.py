from app import store
from app.traces import classify


def detail(client, service):
    return client.get(f"/api/services/{service}").json()


def finding(data, check_id):
    return next((f for f in data["findings"] if f["check_id"] == check_id), None)


def fix_and_reassess(client, service, fix_id):
    assert client.post(f"/api/services/{service}/fixes/{fix_id}/apply").status_code == 200
    return client.post(f"/api/services/{service}/assess").json()


def test_baseline_outcomes_are_really_measured(client):
    assert detail(client, "billing-service")["latest_run"]["status"] == "blocked"
    assert detail(client, "identity-service")["latest_run"]["status"] == "completed"
    assert client.get("/api/overview").json()["completion"]["baseline"] == {"completed": 1, "total": 2}


def test_billing_blocker_is_env_with_evidence(client):
    data = detail(client, "billing-service")
    assert data["latest_run"]["blocked_dimension"] == "build_environment"
    blocker = finding(data, "env_vars_documented")
    assert blocker["severity"] == "blocker"
    assert blocker["owner_team"] == "team-billing"
    run_evidence = blocker["evidence"][0]
    assert run_evidence["provenance"] == "measured"
    assert "BILLING_TAX_TABLE_PATH" in run_evidence["output"]


def test_score_can_rise_while_task_stays_blocked(client):
    before = detail(client, "billing-service")
    after = fix_and_reassess(client, "billing-service", "1-architecture-doc")
    assert after["score"] > before["score"]
    assert after["latest_run"]["status"] == "blocked"
    assert finding(after, "architecture_doc")["status"] == "verified"


def test_passing_static_check_does_not_verify_a_measured_blocker(client):
    data = fix_and_reassess(client, "billing-service", "2-env-name-only")
    check = next(c for c in data["checks"] if c["check_id"] == "env_vars_documented")
    blocker = finding(data, "env_vars_documented")
    assert check["passed"] is True
    assert data["latest_run"]["status"] == "blocked"
    assert blocker["status"] == "reopened"
    assert blocker["reopen_count"] == 1


def test_working_fix_completes_task_and_verifies(client):
    data = fix_and_reassess(client, "billing-service", "3-env-working-config")
    assert data["latest_run"]["status"] == "completed"
    assert finding(data, "env_vars_documented")["status"] == "verified"
    latest = client.get("/api/overview").json()["completion"]["latest"]
    assert latest == {"completed": 2, "total": 2}


def test_notifications_starts_unassessed_and_shows_all_issues_at_once(client):
    before = detail(client, "notifications-service")
    assert before["history"] == [] and before["score"] is None
    data = client.post("/api/services/notifications-service/assess").json()
    assert data["latest_run"] is None
    open_checks = {f["check_id"] for f in data["findings"]}
    assert {"catalog_entry", "test_command_documented", "structured_logging"} <= open_checks


def test_shared_gaps_go_to_the_platform_team(client):
    data = client.post("/api/services/notifications-service/assess").json()
    assert finding(data, "ci_config")["owner_team"] == store.SHARED_TEAM
    assert finding(data, "catalog_entry")["owner_team"] == "team-messaging"


def test_submitting_without_a_change_reopens(client):
    target = finding(detail(client, "billing-service"), "env_vars_documented")
    response = client.post(f"/api/findings/{target['id']}/transition", json={"action": "submit"})
    assert response.status_code == 200
    data = client.post("/api/services/billing-service/assess").json()
    assert finding(data, "env_vars_documented")["status"] == "reopened"


def test_teams_cannot_mark_verified(client):
    target = finding(detail(client, "billing-service"), "env_vars_documented")
    response = client.post(f"/api/findings/{target['id']}/transition", json={"action": "verified"})
    assert response.status_code == 422


def test_registered_repo_is_scanned_but_never_executed(client, tmp_path, monkeypatch):
    marker = tmp_path / "ran"
    (tmp_path / "README.md").write_text("Run `python -m unittest` \n")
    (tmp_path / "test_x.py").write_text(f"open({str(marker)!r}, 'w')\n")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path.parent)
    response = client.post("/api/services", json={"name": "My Repo", "team": "t", "path": str(tmp_path)})
    assert response.status_code == 201
    assert response.json()["latest_run"] is None
    assert not marker.exists()
    assert client.get("/api/overview").json()["unmeasured_services"] == 2


def test_register_rejects_path_outside_home(client):
    response = client.post("/api/services", json={"name": "x", "team": "t", "path": "/etc"})
    assert response.status_code == 422


def test_fix_id_cannot_traverse(client):
    assert client.post("/api/services/billing-service/fixes/..%2F..%2Frepos/apply").status_code == 404


def test_simulated_traces_stay_out_of_measured_completion(client):
    baseline = client.get("/api/overview").json()["completion"]["latest"]
    response = client.post("/api/traces", json={
        "external_id": "x1", "service": "billing-service", "agent": "a",
        "title": "t", "outcome": "completed", "events": [{"step": 1, "action": "a", "output": "ok"}],
    })
    assert response.status_code == 201
    assert client.get("/api/overview").json()["completion"]["latest"] == baseline


def test_trace_classifier():
    result = classify([{"step": 3, "action": "run", "output": "KeyError: 'BILLING_TAX_TABLE_PATH'"}])
    assert result["check_id"] == "env_vars_documented" and result["step"] == 3
    assert classify([{"step": 1, "action": "a", "output": "b"}])["label"] == "Unclassified"


def test_reset_restores_baseline(client):
    fix_and_reassess(client, "billing-service", "3-env-working-config")
    client.post("/api/demo/reset")
    assert detail(client, "billing-service")["latest_run"]["status"] == "blocked"
    assert store.WORKSPACES.name == "workspaces" and "agentready-test-" in str(store.WORKSPACES)
