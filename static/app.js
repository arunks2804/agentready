const view = document.getElementById("view");
const tooltip = document.getElementById("tooltip");
const select = document.getElementById("service-select");
const PRIMARY = "notifications-service";
let dimensions = [];
let services = [];
let current = PRIMARY;
let poll = null;

const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));
const dimLabel = (key) => dimensions.find((d) => d.key === key)?.label ?? key ?? "Unclassified";
const percent = (r) => (r.total ? Math.round((100 * r.completed) / r.total) : 0);
const when = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Request failed");
  return body;
}

const provenance = (kind) => {
  if (kind === "simulated") return `<span class="chip simulated" title="Prepared data. No real agent ran.">Simulated</span>`;
  if (kind === "agent") return `<span class="chip" title="Quoted by the Gap Analysis Agent. AgentReady confirmed the quote is in the file.">Gap Analysis Agent</span>`;
  if (kind === "rule") return `<span class="chip" title="The script found something missing and stopped before running any test.">Rule-based stop</span>`;
  return `<span class="chip" title="Observed by AgentReady on this run.">Measured</span>`;
};

function outcome(run) {
  if (!run) return `<span class="status"><i class="dot none"></i>Not measured</span>`;
  return run.status === "completed"
    ? `<span class="status"><i class="dot good"></i>Completed</span>`
    : `<span class="status"><i class="dot square bad"></i>Blocked</span>`;
}

const SEVERITY = { blocker: ["bad", "Blocker"], high: ["serious", "High"], medium: ["warn", "Medium"], low: ["none", "Low"] };
const severity = (key) => `<span class="status"><i class="dot square ${SEVERITY[key][0]}"></i>${SEVERITY[key][1]}</span>`;
const STATUS = {
  open: "Open", in_remediation: "In remediation", awaiting_verification: "Awaiting verification",
  reopened: "Reopened", verified: "Verified",
};

function tile(label, value, note) {
  return `<div class="card"><div class="muted">${esc(label)}</div><div class="tile-num">${esc(value)}</div>
    <div class="muted">${esc(note)}</div></div>`;
}

function historyChart(history) {
  const w = 620, h = 190, left = 34, right = 14, top = 14, bottom = 26;
  const x = (i) => left + (history.length > 1 ? (i * (w - left - right)) / (history.length - 1) : (w - left - right) / 2);
  const y = (v) => top + ((100 - v) * (h - top - bottom)) / 100;
  const grid = [0, 50, 100].map((v) => `<line x1="${left}" x2="${w - right}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/>
    <text x="${left - 6}" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="var(--ink-3)">${v}</text>`).join("");
  const path = history.map((a, i) => `${i ? "L" : "M"}${x(i)},${y(a.score)}`).join(" ");
  const marks = history.map((a, i) => {
    const label = a.run_status === "completed" ? "completed" : a.run_status === "blocked" ? "blocked" : "not measured";
    const tip = `Run ${i + 1}: score ${a.score}, task ${label}`;
    const mark = a.run_status === "completed"
      ? `<circle cx="${x(i)}" cy="${y(a.score)}" r="6" fill="var(--good)" stroke="var(--surface)" stroke-width="2"/>`
      : a.run_status === "blocked"
        ? `<rect x="${x(i) - 5.5}" y="${y(a.score) - 5.5}" width="11" height="11" rx="2" fill="var(--critical)" stroke="var(--surface)" stroke-width="2"/>`
        : `<circle cx="${x(i)}" cy="${y(a.score)}" r="5" fill="var(--line-strong)"/>`;
    return `<g data-tip="${esc(tip)}">${mark}<circle cx="${x(i)}" cy="${y(a.score)}" r="16" fill="transparent"/>
      <text x="${x(i)}" y="${h - 8}" text-anchor="middle" font-size="11" fill="var(--ink-3)">${i + 1}</text></g>`;
  }).join("");
  return `<div class="chart"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Readiness score and task outcome for each assessment">
      ${grid}<path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2"/>${marks}</svg>
    <div class="legend"><span><i class="dot good"></i>Task completed</span><span><i class="dot square bad"></i>Task blocked</span><span>Line: readiness score, by assessment run</span></div>
    <details><summary>Table view</summary><div class="table-wrap"><table><thead><tr><th>Run</th><th>Trigger</th><th class="num">Score</th><th>Task</th></tr></thead>
      <tbody>${history.map((a, i) => `<tr><td>${i + 1}</td><td>${esc(a.trigger)}</td><td class="num">${a.score}</td><td>${esc(a.run_status ?? "not measured")}</td></tr>`).join("")}</tbody></table></div></details>
  </div>`;
}

const errorLine = (output) => output.split("\n").filter((line) => /^\w*Error/.test(line)).at(-1) ?? output.trim().split("\n").at(-1);

function evidenceList(evidence) {
  return `<ul class="evidence">${evidence.map((e) => `<li>${provenance(e.provenance)}
    ${e.ref ? `<code>${esc(e.ref)}${e.line ? `:${e.line}` : ""}</code>` : ""} ${esc(e.detail)}
    ${e.output ? `<details><summary>Command output</summary><pre>${esc(e.output)}</pre></details>` : ""}</li>`).join("")}</ul>`;
}

function findingCard(f, fixes = []) {
  const fix = fixes.find((x) => !x.applied && (x.check_id === f.check_id || f.evidence.some((e) => x.cites.includes(e.ref))));
  const actions = f.status === "verified" ? "" : `<div class="actions">
    ${f.status === "awaiting_verification"
      ? `<span class="muted">Fix submitted. Only a reassessment can close this.</span>`
      : fix ? `<button class="ghost" data-fix="${esc(fix.id)}">Simulate team fix</button>` : ""}
  </div>`;
  return `<article class="finding">
    <div class="finding-head"><span class="finding-title">${esc(f.title)}</span>
      <span class="status">${severity(f.severity)} <span class="chip">${STATUS[f.status]}</span></span></div>
    <div class="muted">${esc(dimLabel(f.dimension))} · Owner: ${esc(f.owner_team)} · Found by ${f.source === "script" ? "script" : f.evidence.some((e) => e.provenance === "simulated") ? "simulated Gap Analysis Agent" : "Gap Analysis Agent"}${f.source === "script" || f.evidence.some((e) => e.provenance === "simulated") ? "" : ` · ${f.certainty === "hypothesis" ? "Hypothesis" : "Confirmed"}`}${f.reopen_count ? ` · reopened ${f.reopen_count}×` : ""}</div>
    ${f.explanation ? `<p style="margin-top:6px">${esc(f.explanation)}</p>` : ""}
    ${evidenceList(f.evidence)}
    <p style="margin-top:6px"><strong>Recommended:</strong> ${esc(f.recommendation)}</p>
    ${f.closure ? `<p class="muted" style="margin-top:2px"><strong>Closes when:</strong> ${esc(f.closure)}</p>` : ""}${actions}</article>`;
}

function runningBanner(run) {
  if (!run || run.status !== "running") return "";
  const last = run.trace.at(-1);
  return `<div class="card running" role="status"><i class="spinner"></i><div><strong>${esc(run.title)}</strong>
    <div class="muted">${run.model === "Simulated" ? "Simulated run with prepared data." : `Running on ${esc(run.model)} through Ollama on this machine.`} ${last ? `Step ${last.step}: ${esc(last.tool ?? "thinking")}` : "Loading the model."}</div></div></div>`;
}

function watch(run, refresh) {
  clearTimeout(poll);
  if (run?.status === "running") poll = setTimeout(refresh, 1500);
}

const latestRun = (s, ...kinds) => s.agent_runs.find((r) => kinds.includes(r.kind));

async function startAgent(kind, sourceRunId) {
  await api(`/services/${encodeURIComponent(current)}/agent-runs`, {
    method: "POST", body: JSON.stringify({ kind, source_run_id: sourceRunId ?? null }),
  });
}

function bindFixes(refresh) {
  view.querySelectorAll("[data-fix]").forEach((button) => button.addEventListener("click", async () => {
    button.disabled = true;
    await api(`/services/${encodeURIComponent(current)}/fixes/${encodeURIComponent(button.dataset.fix)}/apply`, { method: "POST" });
    refresh();
  }));
}

function showError(error) {
  const box = document.getElementById("action-error");
  if (box) box.textContent = error.message;
}

function codingSummary(run) {
  if (!run) return `<div class="stat">Not run</div><p class="muted">No coding agent has attempted a task on this service yet.</p>`;
  if (run.status === "running") return `<div class="stat">Running</div>`;
  if (run.status === "error" || run.status === "interrupted") return `<div class="stat">No result</div><p class="muted">${esc(run.error ?? "The run was interrupted.")}</p>`;
  const v = run.result;
  return `<div class="stat">${run.status === "passed" ? "Passed" : "Failed"}</div>
    <p>${esc(v.task.id)}: ${esc(v.task.title)}</p>
    <p class="muted">${v.simulated ? `${provenance("simulated")} Prepared result. No coding agent or tests ran.` : `Attempted by ${esc(run.model)}. ${v.tests_ran} tests ran. Measured by AgentReady from the code and tests, not from the agent's report.`}</p>`;
}

async function renderReadiness() {
  const s = await api(`/services/${encodeURIComponent(current)}`);
  const assessed = s.history.length > 0;
  const active = s.agent_runs.find((r) => r.status === "running");
  const coding = latestRun(s, "coding");
  const open = s.findings.filter((f) => f.status !== "verified");
  const groups = dimensions.map((d) => ({ ...d, rows: s.checks.filter((c) => c.dimension === d.key) }));
  view.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">Service readiness</div><h1>${esc(s.name)}</h1>
      <p class="sub">Is this service ready for AI coding agents before stories are assigned to them?</p></div>
      <div class="page-actions">
        ${assessed ? `<button class="ghost" id="reassess" ${active ? "disabled" : ""}>Reassess</button>
          <a href="#/findings"><button class="ghost" tabindex="-1">Review Findings</button></a>
          <a href="#/coding"><button tabindex="-1">Validate with Coding Agent</button></a>`
        : `<button id="assess" ${active ? "disabled" : ""}>Assess Readiness</button>`}
      </div></div>
    <div class="error" id="action-error" role="alert"></div>
    ${runningBanner(active)}
    <section class="card" style="margin-bottom:16px"><dl class="facts">
      <div><dt>Owner</dt><dd>${esc(s.team)}</dd></div>
      <div><dt>Repository</dt><dd>${s.kind === "sample" ? `samples/repos/${esc(s.id)}` : esc(s.path)}</dd></div>
      <div><dt>Readiness criteria</dt><dd>17 script checks, 8 dimensions</dd></div>
      <div><dt>Last assessed</dt><dd>${s.assessed_at ? esc(when(s.assessed_at)) : "Not yet"}</dd></div>
    </dl></section>
    ${assessed ? `
    <section class="split">
      <div class="card"><div class="muted">Readiness checks</div>
        <div class="stat">${s.checks_passed} of ${s.checks_total}</div>
        <p class="muted">Script checks passed. Passing shows a thing exists, not that it is correct or sufficient.</p></div>
      <div class="card"><div class="muted">Open findings</div>
        <div class="stat">${open.length}</div>
        <p class="muted">${open.filter((f) => f.source !== "script").length} from the Gap Analysis Agent, ${open.filter((f) => f.source === "script").length} from scripts. ${s.findings.length - open.length} closed.</p></div>
      <div class="card" style="grid-column:1/-1"><div class="muted">Coding task</div>${codingSummary(coding)}</div>
    </section>
    <section class="card"><h2>Readiness criteria</h2>
      ${groups.filter((g) => g.rows.length).map((g) => `<div class="check-group"><h3>${esc(g.label)}</h3>
        ${g.rows.map((c) => `<div class="check-row"><span class="check-mark ${c.passed ? "ok" : "no"}">${c.passed ? "✓" : "✕"}</span>
          <div>${esc(c.title)}<div class="muted">${esc(c.evidence[0]?.detail ?? "")}</div></div></div>`).join("")}</div>`).join("")}
    </section>` : `
    <section class="card"><h2>Not assessed yet</h2>
      <p class="muted">Assess Readiness runs the script checks, then the Gap Analysis Agent reviews what scripts cannot judge. Every issue appears at once.</p></section>`}`;
  const assess = async () => {
    try {
      await api(`/services/${encodeURIComponent(current)}/assess`, { method: "POST" });
      if (!assessed && s.kind === "sample" && s.coding_task) await startAgent("gap");
      else if (assessed && s.findings.some((f) => f.source !== "script" && f.status !== "verified")) await startAgent("recheck");
    } catch (error) { showError(error); }
    renderReadiness();
  };
  document.getElementById("assess")?.addEventListener("click", assess);
  document.getElementById("reassess")?.addEventListener("click", assess);
  watch(active, renderReadiness);
}

async function renderFindings() {
  const s = await api(`/services/${encodeURIComponent(current)}`);
  const open = s.findings.filter((f) => f.status !== "verified");
  const closed = s.findings.filter((f) => f.status === "verified");
  const active = s.agent_runs.find((r) => r.status === "running");
  const teams = [...new Set(open.map((f) => f.owner_team))].sort();
  view.innerHTML = `<div class="page-head"><div><div class="eyebrow">${esc(s.name)}</div><h1>Findings</h1>
      <p class="sub">One finding per root cause. A team can apply a fix, but only a reassessment can close a finding.</p></div>
      <div class="page-actions"><a href="#/"><button tabindex="-1">Reassess on Readiness page</button></a></div></div>
    ${runningBanner(active)}
    ${teams.map((team) => {
      const rows = open.filter((f) => f.owner_team === team);
      return `<section class="card" style="margin-bottom:16px"><h2>${esc(team)} (${rows.length})</h2>${rows.map((f) => findingCard(f, s.fixes)).join("")}</section>`;
    }).join("") || `<section class="card"><p class="muted">No open findings.</p></section>`}
    ${closed.length ? `<section class="card"><h2>Closed (${closed.length})</h2><p class="muted">Proved by reassessment.</p>
      ${closed.map((f) => `<div class="check-row"><span class="check-mark ok">✓</span><div>${esc(f.title)}<div class="muted">${esc(f.owner_team)}</div></div></div>`).join("")}</section>` : ""}`;
  bindFixes(renderFindings);
  watch(active, renderFindings);
}

function diffBlock(diff) {
  const lines = diff.split("\n").map((line) => {
    const kind = line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : "";
    return `<span class="${kind}">${esc(line)}</span>`;
  });
  return `<pre class="diff">${lines.join("\n")}</pre>`;
}

function traceList(trace) {
  return `<ol class="trace">${trace.map((e) => `<li><div><span class="muted">Step ${e.step}</span> ${e.tool ? `<code>${esc(e.tool)}</code>` : "No tool call"}
      ${e.args?.path ? `<span class="muted">${esc(e.args.path)}</span>` : ""}${e.args?.command ? `<span class="muted">${esc(e.args.command)}</span>` : ""}</div>
    <details><summary>Details</summary><pre>${esc(e.result ?? e.note ?? "")}</pre></details></li>`).join("")}</ol>`;
}

function resultCards(run) {
  const v = run.result;
  if (!v.checks) return "";
  return `<section class="split">
    <div class="card"><h2>Checks ${v.simulated ? provenance("simulated") : ""}</h2>
      ${v.checks.map((c) => `<div class="check-row"><span class="check-mark ${c.passed ? "ok" : "no"}">${c.passed ? "✓" : "✕"}</span><div>${esc(c.name)}</div></div>`).join("")}
      <p class="muted" style="margin-top:8px">The agent said: ${v.self_report ? `“${esc(v.self_report.summary)}”` : "nothing. It never finished."}</p>
      <details><summary>Test output</summary><pre>${esc(v.test_output)}</pre></details></div>
    <div class="card"><h2>Changed files (${v.changed_files.length})</h2>
      ${v.changed_files.length ? `<p class="muted">${v.changed_files.map(esc).join(", ")}</p>${diffBlock(v.diff)}` : `<p class="muted">The agent changed nothing.</p>`}</div>
  </section>`;
}

async function renderCoding() {
  const [s, status] = await Promise.all([api(`/services/${encodeURIComponent(current)}`), api("/ollama")]);
  const simulated = status.settings.mode === "simulated";
  const task = s.coding_task;
  const run = latestRun(s, "coding");
  const active = s.agent_runs.find((r) => r.status === "running");
  const diagnosis = s.agent_runs.find((r) => r.kind === "diagnose" && r.source_run_id === run?.id);
  const blocked = active || (!simulated && (!status.connected || !status.sandbox));
  view.innerHTML = `<div class="page-head"><div><div class="eyebrow">${esc(s.name)}</div><h1>Coding task validation</h1>
      <p class="sub">${simulated ? "Simulated results, until the real Coding Agent is reliable." : "A real local model attempts one small task in an isolated copy. The result applies to this task, model and setup only."}</p></div>
      <div class="page-actions">
        ${task && run?.status !== "passed" ? `<button id="validate" ${blocked ? "disabled" : ""}>${run ? "Retry" : "Validate with Coding Agent"}</button>` : ""}
        ${!simulated && run?.status === "failed" && !diagnosis ? `<button class="ghost" id="diagnose" ${active ? "disabled" : ""}>Diagnose failure</button>` : ""}
      </div></div>
    <div class="error" id="action-error" role="alert"></div>
    ${!simulated && !status.connected ? `<div class="callout">Ollama is not reachable. ${esc(status.error)}</div>` : ""}
    ${task ? "" : `<div class="callout">This service has no coding task.</div>`}
    ${runningBanner(active)}
    ${task ? `<section class="split">
      <div class="card"><div class="muted">Task</div><h2>${esc(task.id)}: ${esc(task.title)}</h2><p style="margin-top:6px">${esc(task.description)}</p></div>
      <div class="card"><div class="muted">Outcome</div>${codingSummary(run)}</div>
    </section>` : ""}
    ${run ? resultCards(run) : ""}
    ${!simulated && diagnosis && diagnosis.status !== "running" ? `<section class="card" style="margin-bottom:16px"><h2>Diagnosis</h2>
      <p class="muted">Routed to ${diagnosis.result.route === "script" ? "a known-pattern script" : `the Gap Analysis Agent (${esc(diagnosis.model)})`}.</p>
      ${(diagnosis.result.outcomes ?? []).map((o) => `<div class="check-row"><span></span><div>${o.action === "updated" ? "Added evidence to" : "Opened"} a finding: <a href="#/findings">${esc(o.title)}</a></div></div>`).join("") || `<p>No repository cause found. This looks like the model's own mistake.</p>`}
    </section>` : ""}
    ${run?.trace.length ? `<section class="card"><h2>Execution trace</h2>${traceList(run.trace)}</section>` : ""}`;
  const launch = (id, kind, source) => document.getElementById(id)?.addEventListener("click", async () => {
    try { await startAgent(kind, source); renderCoding(); } catch (error) { showError(error); }
  });
  launch("validate", "coding");
  launch("diagnose", "diagnose", run?.id);
  watch(active, renderCoding);
}

async function renderSettings() {
  const status = await api("/ollama");
  const f = status.settings;
  const usable = status.models.filter((m) => m.usable);
  const options = (chosen) => usable.map((m) => `<option ${m.name === chosen ? "selected" : ""}>${esc(m.name)}</option>`).join("");
  const number = (name, label) => `<label>${label}<input type="number" name="${name}" value="${f[name]}" required></label>`;
  view.innerHTML = `<div class="page-head"><div><h1>Settings</h1>
      <p class="sub">Both agents run on this machine through Ollama. They can use one model with different instructions and tool permissions.</p></div></div>
    <section class="card" style="margin-bottom:16px"><h2>Connection</h2>
      <p>${status.connected ? `<span class="status"><i class="dot good"></i>Connected</span>` : `<span class="status"><i class="dot square bad"></i>Not connected</span>`}
        <span class="muted">${status.connected ? `${usable.length} of ${status.models.length} installed models can call tools.` : esc(status.error)}</span></p>
      <p class="muted">Execution sandbox: ${status.sandbox ? "available" : "unavailable, so coding runs are refused"}.</p></section>
    <section class="card"><h2>Agents</h2>
      <form class="settings-form" id="settings">
        <label class="wide">Agent mode<select name="mode"><option value="simulated" ${f.mode === "simulated" ? "selected" : ""}>Simulation</option><option value="real" ${f.mode === "real" ? "selected" : ""}>Real local models</option></select></label>
        <label class="wide">Ollama base URL<input name="base_url" value="${esc(f.base_url)}" required></label>
        <label>Gap Analysis Agent model<select name="gap_model">${options(f.gap_model)}</select></label>
        <label>Coding Agent model<select name="coding_model">${options(f.coding_model)}</select></label>
        ${number("timeout_s", "Model call timeout (seconds)")}${number("run_budget_s", "Run time budget (seconds)")}
        ${number("num_ctx", "Context budget (tokens)")}${number("num_predict", "Reply budget (tokens)")}
        ${number("gap_max_steps", "Gap Analysis Agent step limit")}${number("coding_max_steps", "Coding Agent step limit")}
        ${number("test_timeout_s", "Test timeout (seconds)")}
        <div class="wide actions"><button>Save settings</button><span class="muted" id="saved" role="status"></span></div>
      </form><div class="error" id="settings-error" role="alert"></div></section>`;
  document.getElementById("settings").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target));
    for (const key of Object.keys(data)) if (/_s$|_steps$|^num_/.test(key)) data[key] = Number(data[key]);
    data.gap_model ??= ""; data.coding_model ??= "";
    try {
      await api("/settings", { method: "PUT", body: JSON.stringify(data) });
      document.getElementById("saved").textContent = "Saved.";
      showMode(data.mode);
      document.getElementById("settings-error").textContent = "";
    } catch (error) { document.getElementById("settings-error").textContent = error.message; }
  });
}

function heatCell(value, tip) {
  const strength = Math.round(12 + value * 0.8);
  const ink = strength > 75 ? "#fff" : "var(--ink)";
  return `<td class="cell" data-tip="${esc(tip)}" style="background:color-mix(in srgb, var(--accent) ${strength}%, var(--surface));color:${ink}">${value}</td>`;
}

async function renderPlatform() {
  const o = await api("/overview");
  const top = [...o.recurring].sort((a, b) => b.open_findings - a.open_findings);
  view.innerHTML = `<div class="page-head"><div><h1>Platform insights</h1>
      <p class="sub">Aggregate view for the AI coding-agent platform team. Use it to find blockers worth solving once, across teams.</p></div></div>
    <section class="card" style="margin-bottom:16px"><h2>Recurring blockers</h2><p class="muted">Sorted by open findings across every registered service, including optional test data.</p>
      <div class="table-wrap"><table><thead><tr><th>Dimension</th><th class="num">Open findings</th><th class="num">Services affected</th></tr></thead>
      <tbody>${top.map((r) => `<tr><td>${esc(r.label)}</td><td class="num">${r.open_findings}</td><td class="num">${r.services_affected}</td></tr>`).join("")}</tbody></table></div></section>
    <section class="card"><h2>Readiness heatmap</h2><p class="muted">Static check score per dimension, 0 to 100. Stronger blue is higher.</p>
      <div class="table-wrap"><table class="heat"><thead><tr><th>Service</th>${dimensions.map((d) => `<th>${esc(d.label.split(" ")[0])}</th>`).join("")}</tr></thead>
      <tbody>${o.services.filter((s) => s.score !== null).map((s) => `<tr><td>${esc(s.name)}</td>${dimensions.map((d) => heatCell(s.dimensions[d.key], `${s.name}, ${d.label}: ${s.dimensions[d.key]}`)).join("")}</tr>`).join("")}</tbody></table></div></section>`;
}

async function route() {
  clearTimeout(poll);
  const page = location.hash.replace(/^#\/?/, "").split("/")[0] || "readiness";
  document.querySelectorAll("[data-nav]").forEach((link) => {
    if (link.dataset.nav === page) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
  tooltip.hidden = true;
  const pages = { readiness: renderReadiness, findings: renderFindings, coding: renderCoding, platform: renderPlatform, settings: renderSettings };
  try {
    await (pages[page] ?? renderReadiness)();
  } catch (error) {
    view.innerHTML = `<p class="error" role="alert">${esc(error.message)}</p>`;
  }
}

function showMode(mode) {
  document.getElementById("mode-banner").hidden = mode !== "simulated";
}

async function loadServices() {
  services = await api("/services");
  select.innerHTML = services.map((s) => `<option value="${esc(s.id)}" ${s.id === current ? "selected" : ""}>${esc(s.name)}${s.id === PRIMARY ? "" : " (test data)"}</option>`).join("");
}

document.addEventListener("mousemove", (event) => {
  const target = event.target.closest?.("[data-tip]");
  tooltip.hidden = !target;
  if (target) {
    tooltip.textContent = target.dataset.tip;
    tooltip.style.left = `${Math.min(event.clientX + 12, innerWidth - 270)}px`;
    tooltip.style.top = `${event.clientY + 14}px`;
  }
});
document.getElementById("reset").addEventListener("click", async () => {
  if (!confirm("Reset the demo to its baseline? Registered services and history will be removed.")) return;
  await api("/demo/reset", { method: "POST" });
  current = PRIMARY;
  await loadServices();
  location.hash = "#/";
  route();
});
select.addEventListener("change", () => { current = select.value; route(); });
addEventListener("hashchange", route);

Promise.all([api("/dimensions"), loadServices(), api("/ollama")]).then(([rows, , status]) => {
  dimensions = rows;
  showMode(status.settings.mode);
  route();
});
