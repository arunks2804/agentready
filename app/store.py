"""SQLite persistence and the assessment workflow."""
import json
import os
import shutil
import sqlite3
import statistics
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import checks as checks_module
from .checks import CHECK_INDEX, DIMENSIONS, run_checks, score
from .probe import run_probe
from .traces import classify

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
VAR = Path(os.environ.get("AGENTREADY_VAR", ROOT / "var"))
DB_PATH = VAR / "agentready.db"
WORKSPACES = VAR / "workspaces"
SAMPLE_TEAMS = {
    "billing-service": "team-billing",
    "notifications-service": "team-messaging",
    "identity-service": "team-identity",
}
OPEN_STATES = ("open", "in_remediation", "awaiting_verification", "reopened")

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS services (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, team TEXT NOT NULL, path TEXT NOT NULL,
  kind TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assessments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, service_id TEXT NOT NULL, trigger TEXT NOT NULL,
  score INTEGER NOT NULL, dimensions TEXT NOT NULL, checks TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS task_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, service_id TEXT NOT NULL, assessment_id INTEGER NOT NULL,
  task_id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, blocked_check TEXT,
  blocked_dimension TEXT, steps TEXT NOT NULL, duration_ms INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT, service_id TEXT NOT NULL, check_id TEXT NOT NULL,
  dimension TEXT NOT NULL, title TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL,
  owner_team TEXT NOT NULL, recommendation TEXT NOT NULL, evidence TEXT NOT NULL,
  first_seen TEXT NOT NULL, verified_at TEXT, reopen_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE (service_id, check_id));
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, service_id TEXT NOT NULL, finding_id INTEGER,
  type TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS traces (
  id INTEGER PRIMARY KEY AUTOINCREMENT, service_id TEXT NOT NULL, external_id TEXT NOT NULL,
  agent TEXT NOT NULL, provenance TEXT NOT NULL, title TEXT NOT NULL, outcome TEXT NOT NULL,
  classification TEXT NOT NULL, events TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE (service_id, external_id));
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    VAR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


def _rows(conn, sql, *params):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _event(conn, service_id, finding_id, type_, detail):
    conn.execute(
        "INSERT INTO events (service_id, finding_id, type, detail, created_at) VALUES (?,?,?,?,?)",
        (service_id, finding_id, type_, detail, now()),
    )


def _load_task(service):
    if service["kind"] != "sample":
        return None, None
    task = json.loads((SAMPLES / "tasks" / f"{service['id']}.json").read_text(encoding="utf-8"))
    return task, SAMPLES / "tasks" / service["id"]


def _reconcile(conn, service, results, run):
    """Update findings from an assessment. Only this path can verify a finding."""
    blocked_check = run["blocked_check"] if run else None
    for result in results:
        check_id = result["check_id"]
        task_blocked_here = check_id == blocked_check
        failing = not result["passed"] or task_blocked_here
        evidence = list(result["evidence"])
        severity = result["severity"]
        if task_blocked_here:
            severity = "blocker"
            step = next((s for s in run["steps"] if s["status"] == "blocked"), None)
            if step:
                evidence.insert(0, {
                    "kind": "run", "provenance": "measured", "ref": step["name"], "line": None,
                    "detail": step["detail"], "output": step.get("output"),
                })
        row = conn.execute(
            "SELECT * FROM findings WHERE service_id=? AND check_id=?", (service["id"], check_id)
        ).fetchone()
        if failing and row is None:
            cursor = conn.execute(
                """INSERT INTO findings (service_id, check_id, dimension, title, severity, status, owner_team,
                   recommendation, evidence, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (service["id"], check_id, result["dimension"], result["title"], severity, "open",
                 service["team"], result["recommendation"], json.dumps(evidence), now()),
            )
            _event(conn, service["id"], cursor.lastrowid, "found", f"{result['title']}: failing")
        elif failing:
            status = row["status"]
            reopened = status in ("awaiting_verification", "verified")
            if reopened:
                status = "reopened"
                reason = (
                    "Static check passes, but the task still fails here."
                    if result["passed"] else "Reassessment still fails."
                )
                _event(conn, service["id"], row["id"], "reopened", reason)
            conn.execute(
                """UPDATE findings SET status=?, severity=?, evidence=?, verified_at=NULL,
                   reopen_count=reopen_count+? WHERE id=?""",
                (status, severity, json.dumps(evidence), int(reopened), row["id"]),
            )
        elif row is not None and row["status"] != "verified":
            conn.execute(
                "UPDATE findings SET status='verified', severity=?, evidence=?, verified_at=? WHERE id=?",
                (result["severity"], json.dumps(evidence), now(), row["id"]),
            )
            _event(conn, service["id"], row["id"], "verified", f"{result['title']}: passes on reassessment")


def assess(service_id, trigger):
    with _lock:
        with connect() as conn:
            service = dict(conn.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone())
        results = run_checks(service["path"])
        overall, dimensions = score(results)
        task, change_dir = _load_task(service)
        run = run_probe(service["path"], task, change_dir) if task else None
        with connect() as conn:
            cursor = conn.execute(
                "INSERT INTO assessments (service_id, trigger, score, dimensions, checks, created_at) VALUES (?,?,?,?,?,?)",
                (service_id, trigger, overall, json.dumps(dimensions), json.dumps(results), now()),
            )
            if run:
                conn.execute(
                    """INSERT INTO task_runs (service_id, assessment_id, task_id, title, status, blocked_check,
                       blocked_dimension, steps, duration_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (service_id, cursor.lastrowid, task["id"], task["title"], run["status"], run["blocked_check"],
                     run["blocked_dimension"], json.dumps(run["steps"]), run["duration_ms"], now()),
                )
            _reconcile(conn, service, results, run)
            outcome = run["status"] if run else "not measured"
            _event(conn, service_id, None, "assessed", f"Score {overall}, task {outcome}")
        return cursor.lastrowid


def register_service(service_id, name, team, path, kind):
    with connect() as conn:
        conn.execute(
            "INSERT INTO services (id, name, team, path, kind, created_at) VALUES (?,?,?,?,?,?)",
            (service_id, name, team, str(path), kind, now()),
        )
    assess(service_id, "registration")


def ingest_trace(data):
    classification = classify(data["events"])
    with connect() as conn:
        conn.execute(
            """INSERT INTO traces (service_id, external_id, agent, provenance, title, outcome, classification,
               events, created_at) VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT (service_id, external_id) DO UPDATE SET classification=excluded.classification,
               events=excluded.events, outcome=excluded.outcome""",
            (data["service"], data["external_id"], data["agent"], data["provenance"], data["title"],
             data["outcome"], json.dumps(classification), json.dumps(data["events"]), now()),
        )
    return classification


def seed():
    WORKSPACES.mkdir(parents=True, exist_ok=True)
    for service_id, team in SAMPLE_TEAMS.items():
        target = WORKSPACES / service_id
        shutil.copytree(SAMPLES / "repos" / service_id, target)
        register_service(service_id, service_id, team, target, "sample")
    for path in sorted((SAMPLES / "traces").glob("*.json")):
        ingest_trace(json.loads(path.read_text(encoding="utf-8")))


def seed_if_empty():
    init_db()
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM services").fetchone()[0]
    if count == 0:
        seed()


def reset():
    with _lock:
        if DB_PATH.exists():
            DB_PATH.unlink()
        if WORKSPACES.exists():
            shutil.rmtree(WORKSPACES)
        seed_if_empty()


def _decode_finding(row):
    row["evidence"] = json.loads(row["evidence"])
    return row


def _decode_run(row):
    row["steps"] = json.loads(row["steps"])
    return row


def _decode_assessment(row):
    row["dimensions"] = json.loads(row["dimensions"])
    row["checks"] = json.loads(row["checks"])
    return row


def service_summary(conn, service):
    latest = _decode_assessment(_rows(
        conn, "SELECT * FROM assessments WHERE service_id=? ORDER BY id DESC LIMIT 1", service["id"])[0])
    baseline = _rows(conn, "SELECT score FROM assessments WHERE service_id=? ORDER BY id LIMIT 1", service["id"])[0]
    runs = _rows(conn, "SELECT * FROM task_runs WHERE service_id=? ORDER BY id DESC LIMIT 1", service["id"])
    counts = _rows(conn, "SELECT severity, COUNT(*) n FROM findings WHERE service_id=? AND status!='verified' GROUP BY severity",
                   service["id"])
    return {
        **service,
        "score": latest["score"], "baseline_score": baseline["score"], "dimensions": latest["dimensions"],
        "assessed_at": latest["created_at"],
        "latest_run": _decode_run(runs[0]) if runs else None,
        "open_findings": sum(c["n"] for c in counts),
        "blockers": sum(c["n"] for c in counts if c["severity"] == "blocker"),
    }


def list_services():
    with connect() as conn:
        return [service_summary(conn, s) for s in _rows(conn, "SELECT * FROM services ORDER BY created_at")]


def service_detail(service_id):
    with connect() as conn:
        services = _rows(conn, "SELECT * FROM services WHERE id=?", service_id)
        if not services:
            return None
        detail = service_summary(conn, services[0])
        latest = _rows(conn, "SELECT * FROM assessments WHERE service_id=? ORDER BY id DESC LIMIT 1", service_id)[0]
        detail["checks"] = json.loads(latest["checks"])
        detail["history"] = [
            {**a, "run_status": r["status"] if (r := conn.execute(
                "SELECT status FROM task_runs WHERE assessment_id=?", (a["id"],)).fetchone()) else None}
            for a in _rows(conn, "SELECT id, trigger, score, created_at FROM assessments WHERE service_id=? ORDER BY id", service_id)
        ]
        detail["runs"] = [_decode_run(r) for r in _rows(
            conn, "SELECT * FROM task_runs WHERE service_id=? ORDER BY id DESC LIMIT 6", service_id)]
        detail["findings"] = list_findings(service_id=service_id, conn=conn)
        detail["events"] = _rows(conn, "SELECT * FROM events WHERE service_id=? ORDER BY id DESC LIMIT 30", service_id)
        detail["traces"] = list_traces(service_id=service_id, conn=conn)
        detail["fixes"] = list_fixes(services[0])
        return detail


def list_findings(service_id=None, conn=None):
    own = conn is None
    conn = conn or connect()
    sql = """SELECT f.*, s.name service_name FROM findings f JOIN services s ON s.id=f.service_id
             {} ORDER BY CASE f.severity WHEN 'blocker' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, f.id"""
    rows = (_rows(conn, sql.format("WHERE f.service_id=?"), service_id) if service_id
            else _rows(conn, sql.format("")))
    if own:
        conn.close()
    return [_decode_finding(r) for r in rows]


def transition_finding(finding_id, action, team=None):
    """Team-facing moves. Verification is deliberately not one of them."""
    moves = {"start": ("in_remediation", "Remediation started"),
             "submit": ("awaiting_verification", "Fix submitted for verification")}
    with connect() as conn:
        rows = _rows(conn, "SELECT * FROM findings WHERE id=?", finding_id)
        if not rows:
            return None
        finding = rows[0]
        if finding["status"] == "verified":
            raise ValueError("A verified finding can only change through reassessment.")
        if action == "assign":
            conn.execute("UPDATE findings SET owner_team=? WHERE id=?", (team, finding_id))
            _event(conn, finding["service_id"], finding_id, "assigned", f"Assigned to {team}")
        else:
            status, detail = moves[action]
            conn.execute("UPDATE findings SET status=? WHERE id=?", (status, finding_id))
            _event(conn, finding["service_id"], finding_id, action, detail)
    return True


def list_fixes(service):
    if service["kind"] != "sample":
        return []
    base = SAMPLES / "fixes" / service["id"]
    if not base.is_dir():
        return []
    fixes = []
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        fix = {"id": folder.name, **json.loads((folder / "fix.json").read_text(encoding="utf-8"))}
        first = next((p for p in (folder / "files").rglob("*") if p.is_file()), None)
        rel = first.relative_to(folder / "files") if first else None
        marker = Path(service["path"]) / rel if rel else None
        fix["applied"] = bool(marker and marker.exists() and marker.read_bytes() == first.read_bytes())
        fixes.append(fix)
    return fixes


def apply_fix(service_id, fix_id):
    """Stand-in for a team's commit: writes files, then requires a reassessment."""
    with connect() as conn:
        rows = _rows(conn, "SELECT * FROM services WHERE id=?", service_id)
        if not rows:
            return None
        service = rows[0]
        fix = next((f for f in list_fixes(service) if f["id"] == fix_id), None)
        if fix is None:
            return None
        shutil.copytree(SAMPLES / "fixes" / service_id / fix_id / "files", service["path"], dirs_exist_ok=True)
        conn.execute(
            """UPDATE findings SET status='awaiting_verification'
               WHERE service_id=? AND check_id=? AND status!='verified'""",
            (service_id, fix["check_id"]),
        )
        _event(conn, service_id, None, "fix", f"Simulated team fix applied: {fix['title']}")
    return fix


def list_traces(service_id=None, conn=None):
    own = conn is None
    conn = conn or connect()
    sql = "SELECT t.*, s.name service_name FROM traces t JOIN services s ON s.id=t.service_id {} ORDER BY t.id"
    rows = (_rows(conn, sql.format("WHERE t.service_id=?"), service_id) if service_id
            else _rows(conn, sql.format("")))
    findings = _rows(conn, "SELECT id, service_id, check_id, status FROM findings")
    if own:
        conn.close()
    lookup = {(f["service_id"], f["check_id"]): f for f in findings}
    for row in rows:
        row["classification"] = json.loads(row["classification"])
        row["events"] = json.loads(row["events"])
        row["finding"] = lookup.get((row["service_id"], row["classification"]["check_id"]))
    return rows


def _rate(rows):
    return {"completed": sum(r["status"] == "completed" for r in rows), "total": len(rows)}


def overview():
    with connect() as conn:
        services = _rows(conn, "SELECT * FROM services ORDER BY created_at")
        first_runs, last_runs = [], []
        for service in services:
            runs = _rows(conn, "SELECT * FROM task_runs WHERE service_id=? ORDER BY id", service["id"])
            if runs:
                first_runs.append(runs[0])
                last_runs.append(runs[-1])
        scores = [service_summary(conn, s) for s in services]
        findings = _rows(conn, "SELECT * FROM findings")
        all_runs = _rows(conn, "SELECT * FROM task_runs")
        traces = list_traces(conn=conn)

    labels = dict(DIMENSIONS)
    blocked_first = [r["blocked_dimension"] for r in first_runs if r["status"] != "completed"]
    blocked_last = [r["blocked_dimension"] for r in last_runs if r["status"] != "completed"]
    recurring = []
    for key, label in DIMENSIONS:
        open_rows = [f for f in findings if f["dimension"] == key and f["status"] != "verified"]
        recurring.append({
            "dimension": key, "label": label,
            "open_findings": len(open_rows),
            "services_affected": len({f["service_id"] for f in open_rows}),
            "measured_blocks_baseline": blocked_first.count(key),
            "measured_blocks_latest": blocked_last.count(key),
            "simulated_traces": sum(t["classification"]["dimension"] == key for t in traces),
        })

    verified = [f for f in findings if f["verified_at"]]
    remediation = [
        (datetime.fromisoformat(f["verified_at"]) - datetime.fromisoformat(f["first_seen"])).total_seconds()
        for f in verified
    ]
    blocked_runs = [r["duration_ms"] for r in all_runs if r["status"] != "completed"]
    return {
        "completion": {"baseline": _rate(first_runs), "latest": _rate(last_runs)},
        "unmeasured_services": len(services) - len(last_runs),
        "score": {
            "baseline": round(statistics.mean(s["baseline_score"] for s in scores)) if scores else 0,
            "latest": round(statistics.mean(s["score"] for s in scores)) if scores else 0,
        },
        "time_to_identify_ms": round(statistics.median(blocked_runs)) if blocked_runs else None,
        "time_to_remediate_s": round(statistics.median(remediation)) if remediation else None,
        "findings": {
            "open": sum(f["status"] != "verified" for f in findings),
            "verified": len(verified),
            "reopened": sum(f["reopen_count"] > 0 for f in findings),
        },
        "repeat_failures": {"baseline": len(blocked_first), "latest": len(blocked_last)},
        "recurring": recurring,
        "services": scores,
    }
