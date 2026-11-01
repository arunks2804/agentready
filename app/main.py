import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import jobs, ollama, sandbox, store
from .checks import DIMENSIONS

STATIC = Path(__file__).resolve().parent.parent / "static"
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@asynccontextmanager
async def lifespan(_app):
    store.seed_if_empty()
    yield


app = FastAPI(title="AgentReady", lifespan=lifespan)


@app.middleware("http")
async def reject_cross_site_writes(request: Request, call_next):
    """A browser cannot send a JSON content type cross-site without a preflight, which this app never allows."""
    if request.method not in SAFE_METHODS and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-site requests are not allowed"}, status_code=403)
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            return JSONResponse({"detail": "Requests must use application/json"}, status_code=415)
    return await call_next(request)


app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    team: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=1024)


class TransitionIn(BaseModel):
    action: Literal["start", "submit", "assign"]
    team: str | None = Field(default=None, max_length=80)


class TraceEvent(BaseModel):
    step: int
    action: str = Field(max_length=2000)
    output: str = Field(max_length=5000)


class TraceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=120)
    service: str
    agent: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    outcome: Literal["failed", "completed"]
    events: list[TraceEvent] = Field(min_length=1, max_length=500)


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["simulated", "real"] = "simulated"
    base_url: str = Field(min_length=1, max_length=200)
    gap_model: str = Field(max_length=120)
    coding_model: str = Field(max_length=120)
    timeout_s: int = Field(ge=10, le=600)
    run_budget_s: int = Field(ge=30, le=3600)
    num_ctx: int = Field(ge=2048, le=65536)
    num_predict: int = Field(ge=128, le=8192)
    gap_max_steps: int = Field(ge=1, le=30)
    coding_max_steps: int = Field(ge=1, le=40)
    test_timeout_s: int = Field(ge=5, le=120)


class AgentRunIn(BaseModel):
    kind: Literal["gap", "recheck", "coding", "bug", "diagnose"]
    source_run_id: int | None = None


def _require_service(service_id):
    detail = store.service_detail(service_id)
    if detail is None:
        raise HTTPException(404, "Service not found")
    return detail


@app.get("/api/overview")
def get_overview():
    return store.overview()


@app.get("/api/dimensions")
def get_dimensions():
    return [{"key": k, "label": v} for k, v in DIMENSIONS]


@app.get("/api/services")
def get_services():
    return store.list_services()


@app.post("/api/services", status_code=201)
def create_service(body: ServiceIn):
    path = Path(body.path).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(422, "Path is not a directory on this machine")
    if not path.is_relative_to(Path.home()):
        raise HTTPException(422, "Path must be inside your home directory")
    service_id = re.sub(r"[^a-z0-9-]+", "-", body.name.lower()).strip("-")
    if not service_id:
        raise HTTPException(422, "Service name needs at least one letter or number")
    if store.service_detail(service_id):
        raise HTTPException(409, "A service with that name already exists")
    store.register_service(service_id, body.name, body.team, path, "registered")
    return store.service_detail(service_id)


@app.get("/api/services/{service_id}")
def get_service(service_id: str):
    return _require_service(service_id)


@app.post("/api/services/{service_id}/assess")
def assess_service(service_id: str):
    _require_service(service_id)
    store.assess(service_id, "reassessment")
    return store.service_detail(service_id)


@app.post("/api/services/{service_id}/fixes/{fix_id}/apply")
def apply_fix(service_id: str, fix_id: str):
    fix = store.apply_fix(service_id, fix_id)
    if fix is None:
        raise HTTPException(404, "Fix not found")
    return store.service_detail(service_id)


@app.get("/api/ollama")
def get_ollama():
    return jobs.ollama_status()


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    if not ollama.is_local(body.base_url):
        raise HTTPException(422, "Ollama must run on this machine, so source code never leaves it.")
    store.save_settings(body.model_dump())
    return jobs.ollama_status()


@app.post("/api/services/{service_id}/agent-runs", status_code=202)
def start_agent_run(service_id: str, body: AgentRunIn):
    service = _require_service(service_id)
    if service["kind"] != "sample" and body.kind in ("coding", "bug"):
        raise HTTPException(422, "AgentReady only runs code in bundled sample repositories.")
    try:
        return {"id": jobs.start(service, body.kind, body.source_run_id)}
    except (jobs.JobError, sandbox.SandboxError, ollama.OllamaError) as error:
        raise HTTPException(409, str(error)) from error


@app.get("/api/agent-runs/{run_id}")
def get_agent_run(run_id: int):
    run = store.get_agent_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@app.get("/api/findings")
def get_findings():
    return store.list_findings()


@app.post("/api/findings/{finding_id}/transition")
def transition(finding_id: int, body: TransitionIn):
    if body.action == "assign" and not body.team:
        raise HTTPException(422, "Assigning needs a team")
    try:
        result = store.transition_finding(finding_id, body.action, body.team)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    if result is None:
        raise HTTPException(404, "Finding not found")
    return {"ok": True}


@app.get("/api/traces")
def get_traces():
    return store.list_traces()


@app.post("/api/traces", status_code=201)
def post_trace(body: TraceIn):
    _require_service(body.service)
    # Uploads cannot be verified, so a client never gets to call its own trace Measured.
    return store.ingest_trace({**body.model_dump(), "provenance": "simulated"})


@app.post("/api/demo/reset")
def demo_reset():
    if jobs.busy():
        raise HTTPException(409, "An agent is running. Wait for it to finish.")
    store.reset()
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
