"""SQLite persistence and the assessment workflow."""
import json
import os
import shutil
import sqlite3
import statistics
import threading
from datetime import datetime, timezone
from pathlib import Path

from .checks import DIMENSIONS, run_checks, score
from .probe import run_probe
from .traces import classify

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
VAR = Path(os.environ.get("AGENTREADY_VAR", ROOT / "var"))
DB_PATH = VAR / "agentready.db"
WORKSPACES = VAR / "workspaces"
PRIMARY_SERVICE = "notifications-service"
SAMPLE_TEAMS = {
    PRIMARY_SERVICE: "team-messaging",
    "billing-service": "team-billing",
    "identity-service": "team-identity",
}
SHARED_TEAM = "team-developer-platform"
SHARED_CHECKS = {"ci_config", "definition_of_done", "issue_template"}
DEFAULT_SETTINGS = {
    "mode": "simulated",
    "base_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"), "gap_model": "", "coding_model": "",
    "timeout_s": 300, "run_budget_s": 1200, "num_ctx": 12288, "num_predict": 1500,
    "gap_max_steps": 10, "coding_max_steps": 14, "test_timeout_s": 30,
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
  source TEXT NOT NULL DEFAULT 'script', certainty TEXT NOT NULL DEFAULT 'confirmed',
  explanation TEXT NOT NULL DEFAULT '', closure TEXT NOT NULL DEFAULT '', agent_run_id INTEGER,
  UNIQUE (service_id, check_id));
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, service_id TEXT NOT NULL, finding_id INTEGER,
  type TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS traces (
  id INTEGER PRIMARY KEY AUTOINCREMENT, service_id TEXT NOT NULL, external_id TEXT NOT NULL,
  agent TEXT NOT NULL, provenance TEXT NOT NULL, title TEXT NOT NULL, outcome TEXT NOT NULL,
  classification TEXT NOT NULL, events TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE (service_id, external_id));
CREATE TABLE IF NOT EXISTS agent_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, service_id TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
  model TEXT, title TEXT NOT NULL, source_run_id INTEGER, trace TEXT NOT NULL DEFAULT '[]', result TEXT NOT NULL DEFAULT '{}',
  error TEXT, started_at TEXT NOT NULL, finished_at TEXT);
CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL);
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
        # A run cannot survive a restart, so it is reported as interrupted rather than left spinning.
        conn.execute("UPDATE agent_runs SET status='interrupted', finished_at=? WHERE status='running'", (now(),))


def _rows(conn, sql, *params):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _event(conn, service_id, finding_id, type_, detail):
    conn.execute(
        "INSERT INTO events (service_id, finding_id, type, detail, created_at) VALUES (?,?,?,?,?)",
        (service_id, finding_id, type_, detail, now()),
    )


def owner_for(service, check_id):
    return SHARED_TEAM if check_id in SHARED_CHECKS else service["team"]


def _load_task(service):
    path = SAMPLES / "tasks" / f"{service['id']}.json"
    if service["kind"] != "sample" or not path.is_file():
        return None, None
    task = json.loads(path.read_text(encoding="utf-8"))
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
                    "kind": "run", "provenance": "measured" if step.get("output") else "rule",
                    "ref": step["name"], "line": None,
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
                 owner_for(service, check_id), result["recommendation"], json.dumps(evidence), now()),
            )
            conn.execute("UPDATE findings SET closure=? WHERE id=?",
                         (f"Readiness check passes: {result['title']}", cursor.lastrowid))
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


def register_service(service_id, name, team, path, kind, assess_now=True):
    with connect() as conn:
        conn.execute(
            "INSERT INTO services (id, name, team, path, kind, created_at) VALUES (?,?,?,?,?,?)",
            (service_id, name, team, str(path), kind, now()),
        )
    if assess_now:
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
        register_service(service_id, service_id, team, target, "sample", assess_now=service_id != PRIMARY_SERVICE)
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
        kept = get_settings() if DB_PATH.exists() else {}
        if DB_PATH.exists():
            DB_PATH.unlink()
        if WORKSPACES.exists():
            shutil.rmtree(WORKSPACES)
        seed_if_empty()
        if kept:
            save_settings(kept)


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
    rows = _rows(conn, "SELECT * FROM assessments WHERE service_id=? ORDER BY id DESC LIMIT 1", service["id"])
    latest = _decode_assessment(rows[0]) if rows else None
    baseline = _rows(conn, "SELECT score FROM assessments WHERE service_id=? ORDER BY id LIMIT 1", service["id"])
    runs = _rows(conn, "SELECT * FROM task_runs WHERE service_id=? ORDER BY id DESC LIMIT 1", service["id"])
    counts = _rows(conn, "SELECT severity, COUNT(*) n FROM findings WHERE service_id=? AND status!='verified' GROUP BY severity",
                   service["id"])
    return {
        **service,
        "score": latest["score"] if latest else None,
        "baseline_score": baseline[0]["score"] if baseline else None,
        "dimensions": latest["dimensions"] if latest else {},
        "assessed_at": latest["created_at"] if latest else None,
        "checks_passed": sum(c["passed"] for c in latest["checks"]) if latest else 0,
        "checks_total": len(latest["checks"]) if latest else 0,
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
        latest = _rows(conn, "SELECT * FROM assessments WHERE service_id=? ORDER BY id DESC LIMIT 1", service_id)
        detail["checks"] = json.loads(latest[0]["checks"]) if latest else []
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
        detail["coding_task"] = coding_task(service_id)
        detail["agent_runs"] = list_agent_runs(service_id, conn=conn)
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
        fix.setdefault("cites", [])
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
            (service_id, fix.get("check_id")),
        )
        for finding in _rows(conn, "SELECT * FROM findings WHERE service_id=? AND source!='script' AND status!='verified'", service_id):
            cited = {e.get("ref") for e in json.loads(finding["evidence"])}
            if cited & set(fix.get("cites", [])):
                conn.execute("UPDATE findings SET status='awaiting_verification' WHERE id=?", (finding["id"],))
        _event(conn, service_id, None, "fix", f"Prepared example fix applied: {fix['title']}")
    return fix


def coding_task(service_id):
    path = SAMPLES / "coding_tasks" / service_id / "task.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def get_settings():
    with connect() as conn:
        row = conn.execute("SELECT data FROM settings WHERE id=1").fetchone()
    return {**DEFAULT_SETTINGS, **(json.loads(row["data"]) if row else {})}


def save_settings(data):
    merged = {**get_settings(), **data}
    with connect() as conn:
        conn.execute("INSERT INTO settings (id, data) VALUES (1, ?) ON CONFLICT (id) DO UPDATE SET data=excluded.data",
                     (json.dumps(merged),))
    return merged


def create_agent_run(service_id, kind, title, model, source_run_id=None):
    with connect() as conn:
        return conn.execute(
            "INSERT INTO agent_runs (service_id, kind, status, model, title, source_run_id, started_at) VALUES (?,?,?,?,?,?,?)",
            (service_id, kind, "running", model, title, source_run_id, now()),
        ).lastrowid


def save_trace(run_id, trace):
    with connect() as conn:
        conn.execute("UPDATE agent_runs SET trace=? WHERE id=?", (json.dumps(trace), run_id))


def finish_agent_run(run_id, status, result=None, error=None):
    with connect() as conn:
        conn.execute("UPDATE agent_runs SET status=?, result=?, error=?, finished_at=? WHERE id=?",
                     (status, json.dumps(result or {}), error, now(), run_id))


def _decode_agent_run(row):
    row["trace"] = json.loads(row["trace"])
    row["result"] = json.loads(row["result"])
    return row


def get_agent_run(run_id):
    with connect() as conn:
        rows = _rows(conn, "SELECT * FROM agent_runs WHERE id=?", run_id)
    return _decode_agent_run(rows[0]) if rows else None


def list_agent_runs(service_id, conn=None):
    own = conn is None
    conn = conn or connect()
    rows = _rows(conn, "SELECT * FROM agent_runs WHERE service_id=? ORDER BY id DESC LIMIT 20", service_id)
    if own:
        conn.close()
    return [_decode_agent_run(r) for r in rows]


def slug(text):
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")[:60]


def record_agent_finding(service, proposal, run_id):
    """One root cause, one finding. Anything else that matches gains evidence instead of a duplicate."""
    evidence = [{
        "kind": "citation", "provenance": proposal.get("provenance", "agent"), "ref": c["file"], "line": None,
        "detail": f"“{c['quote']}”", "output": None,
    } for c in proposal["evidence"]]
    cited = {c["file"] for c in proposal["evidence"]}
    with connect() as conn:
        rows = _rows(conn, "SELECT * FROM findings WHERE service_id=?", service["id"])
        match = next((r for r in rows if r["id"] == proposal.get("existing_finding_id")), None) or next(
            (r for r in rows if r["source"] != "script" and r["dimension"] == proposal["dimension"]
             and r["status"] != "verified" and cited & {e.get("ref") for e in json.loads(r["evidence"])}), None)
        if match:
            merged = json.loads(match["evidence"])
            merged += [e for e in evidence if e not in merged]
            conn.execute("UPDATE findings SET evidence=? WHERE id=?", (json.dumps(merged), match["id"]))
            _event(conn, service["id"], match["id"], "augmented", f"Added evidence to an existing finding: {match['title']}")
            return {"id": match["id"], "action": "updated", "title": match["title"]}
        cursor = conn.execute(
            """INSERT INTO findings (service_id, check_id, dimension, title, severity, status, owner_team, recommendation,
               evidence, first_seen, source, certainty, explanation, closure, agent_run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (service["id"], f"ctx-{slug(proposal['title'])}", proposal["dimension"], proposal["title"], proposal["severity"],
             "open", service["team"], proposal["recommendation"], json.dumps(evidence), now(), "agent",
             proposal["certainty"], proposal["explanation"],
             "The cited text is corrected, and the Gap Analysis Agent confirms the problem is gone on reassessment.", run_id),
        )
        _event(conn, service["id"], cursor.lastrowid, "found", f"Gap Analysis Agent: {proposal['title']}")
        return {"id": cursor.lastrowid, "action": "created", "title": proposal["title"]}


def add_failure_evidence(service, check_id, title, dimension, severity, recommendation, detail, output):
    """Known failure pattern: attach the failure to its finding, or open one if none exists."""
    item = {"kind": "run", "provenance": "measured", "ref": "Coding task", "line": None, "detail": detail, "output": output}
    with connect() as conn:
        row = conn.execute("SELECT * FROM findings WHERE service_id=? AND check_id=?", (service["id"], check_id)).fetchone()
        if row:
            merged = [item, *json.loads(row["evidence"])]
            status = "reopened" if row["status"] in ("verified", "awaiting_verification") else row["status"]
            conn.execute("UPDATE findings SET evidence=?, status=?, severity=?, verified_at=NULL WHERE id=?",
                         (json.dumps(merged), status, severity, row["id"]))
            _event(conn, service["id"], row["id"], "augmented", f"Coding task failure added to: {row['title']}")
            return {"id": row["id"], "action": "updated", "title": row["title"]}
        cursor = conn.execute(
            """INSERT INTO findings (service_id, check_id, dimension, title, severity, status, owner_team, recommendation,
               evidence, first_seen, closure) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (service["id"], check_id, dimension, title, severity, "open", owner_for(service, check_id), recommendation,
             json.dumps([item]), now(), f"Readiness check passes: {title}"),
        )
        _event(conn, service["id"], cursor.lastrowid, "found", f"{title}: found from a coding task failure")
        return {"id": cursor.lastrowid, "action": "created", "title": title}


def resolve_agent_finding(finding_id, resolved, reason):
    with connect() as conn:
        row = dict(conn.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone())
        if resolved:
            conn.execute("UPDATE findings SET status='verified', verified_at=? WHERE id=?", (now(), finding_id))
            _event(conn, row["service_id"], finding_id, "verified", f"{row['title']}: {reason}")
        elif row["status"] == "awaiting_verification":
            conn.execute("UPDATE findings SET status='reopened', reopen_count=reopen_count+1 WHERE id=?", (finding_id,))
            _event(conn, row["service_id"], finding_id, "reopened", f"{row['title']}: {reason}")


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
        summaries = [service_summary(conn, s) for s in services]
        scores = [s for s in summaries if s["score"] is not None]
        findings = _rows(conn, "SELECT * FROM findings")
        all_runs = _rows(conn, "SELECT * FROM task_runs")
        assessments = conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0]
        traces = list_traces(conn=conn)

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
        "automation": {"assessments": assessments, "task_runs": len(all_runs)},
        "services": summaries,
    }
