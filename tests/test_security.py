JSON = {"Content-Type": "application/json"}
TRACE = {
    "external_id": "upload-1", "service": "billing-service", "agent": "a", "title": "t", "outcome": "failed",
    "events": [{"step": 1, "action": "a", "output": "b"}],
}


def billing_status(client):
    return client.get("/api/services/billing-service").json()["latest_run"]["status"]


def complete_billing(client):
    client.post("/api/services/billing-service/fixes/3-env-working-config/apply")
    client.post("/api/services/billing-service/assess")
    assert billing_status(client) == "completed"


def test_fake_host_is_rejected(client):
    assert client.get("/api/services", headers={"Host": "evil.example"}).status_code == 400
    assert client.post("/api/demo/reset", headers={"Host": "evil.example", **JSON}).status_code == 400


def test_allowed_hosts_work(client):
    for host in ("localhost:8010", "127.0.0.1:8010"):
        assert client.get("/api/services", headers={"Host": host}).status_code == 200


def test_cross_origin_write_is_rejected_and_changes_nothing(client):
    complete_billing(client)
    response = client.post("/api/demo/reset", headers={"Origin": "https://evil.example", **JSON})
    assert response.status_code == 403
    assert billing_status(client) == "completed"


def test_origin_on_a_different_port_is_rejected(client):
    headers = {"Origin": "http://localhost:9999", "Host": "localhost:8010", **JSON}
    assert client.post("/api/demo/reset", headers=headers).status_code == 403


def test_cross_site_form_style_write_is_rejected(client):
    complete_billing(client)
    response = client.post("/api/demo/reset", headers={"Content-Type": "text/plain"})
    assert response.status_code == 415
    assert billing_status(client) == "completed"


def test_write_without_content_type_is_rejected(client):
    bare = client.build_request("POST", "/api/services/billing-service/assess")
    del bare.headers["Content-Type"]
    assert client.send(bare).status_code == 415


def test_same_origin_write_is_allowed(client):
    headers = {"Origin": "http://localhost:8010", "Host": "localhost:8010", **JSON}
    assert client.post("/api/services/billing-service/assess", headers=headers).status_code == 200


def test_cross_site_read_is_not_granted_to_browsers(client):
    response = client.get("/api/services", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_client_cannot_set_provenance(client):
    for label in ("measured", "simulated"):
        assert client.post("/api/traces", json={**TRACE, "provenance": label}).status_code == 422


def test_uploaded_trace_is_always_simulated(client):
    assert client.post("/api/traces", json=TRACE).status_code == 201
    stored = next(t for t in client.get("/api/traces").json() if t["external_id"] == TRACE["external_id"])
    assert stored["provenance"] == "simulated"


def test_name_without_letters_or_numbers_gets_a_clear_error(client):
    response = client.post("/api/services", json={"name": "***", "team": "t", "path": "~"})
    assert response.status_code == 422
    assert "letter or number" in response.json()["detail"]


def test_real_duplicate_name_still_conflicts(client):
    response = client.post("/api/services", json={"name": "billing-service", "team": "t", "path": "~"})
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
