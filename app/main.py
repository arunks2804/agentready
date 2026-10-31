import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import store
from .checks import DIMENSIONS

STATIC = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_app):
    store.seed_if_empty()
    yield


app = FastAPI(title="AgentReady", lifespan=lifespan)


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
    external_id: str = Field(min_length=1, max_length=120)
    service: str
    agent: str = Field(min_length=1, max_length=120)
    provenance: Literal["simulated", "measured"]
    title: str = Field(min_length=1, max_length=200)
    outcome: Literal["failed", "completed"]
    events: list[TraceEvent] = Field(min_length=1, max_length=500)


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
    if not service_id or store.service_detail(service_id):
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
        raise HTTPException(409, str(error))
    if result is None:
        raise HTTPException(404, "Finding not found")
    return {"ok": True}


@app.get("/api/traces")
def get_traces():
    return store.list_traces()


@app.post("/api/traces", status_code=201)
def post_trace(body: TraceIn):
    _require_service(body.service)
    return store.ingest_trace(body.model_dump())


@app.post("/api/demo/reset")
def demo_reset():
    store.reset()
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
