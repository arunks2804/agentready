import os
import tempfile

AGENTREADY_VAR = tempfile.mkdtemp(prefix="agentready-test-")
os.environ["AGENTREADY_VAR"] = AGENTREADY_VAR

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app, base_url="http://localhost", headers={"Content-Type": "application/json"}) as test_client:
        test_client.post("/api/demo/reset")
        yield test_client
