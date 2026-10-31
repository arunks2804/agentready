const view = document.getElementById("view");
const tooltip = document.getElementById("tooltip");
let dimensions = [];

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
  if (kind === "simulated") return `<span class="chip simulated" title="Fixture data. Not a real agent run.">Simulated</span>`;
  if (kind === "rule") return `<span class="chip" title="The script found something missing and stopped before running any test.">Rule-based stop</span>`;
  return `<span class="chip" title="Observed by AgentReady on this run.">Measured</span>`;
};

const SCRIPT_JOBS = [
  ["Check that files, API contracts, CI and owners exist", "These are facts"],
  ["Build the service and run its tests", "Pass or fail needs no judgement"],
  ["Rerun checks after a fix", "Must be repeatable and cheap"],
  ["Match known failure patterns", "A rule can cite the exact step"],
  ["Route findings and calculate metrics", "Plain workflow"],
];
const AI_JOBS = [
  ["Attempt a real task with no known answer", "Only an agent can show what stops an agent"],
  ["Explain new failures that match no known pattern", "Needs reading and judgement"],
  ["Judge whether documentation is usable", "A file can exist and still be useless"],
  ["Decide whether a ticket gives enough context", "Needs interpretation"],
  ["Draft a fix for the owner to review", "Saves effort, and a person stays accountable"],
];

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

async function renderOverview() {
  const o = await api("/overview");
  const { baseline, latest } = o.completion;
  view.innerHTML = `
    <div class="page-head"><div><h1>Can agents finish work on these services?</h1>
      <p class="sub">Task outcomes come from a scripted probe, which stops at a missing prerequisite or runs the sample repository's tests.</p></div></div>
    <section class="grid hero">
      <div class="card">
        <div class="muted">Task completion rate ${provenance("measured")}</div>
        <div class="bignum">${percent(latest)}%</div>
        <div>${latest.completed} of ${latest.total} tasks complete, from ${percent(baseline)}% at baseline</div>
        ${o.unmeasured_services ? `<div class="muted">${o.unmeasured_services} registered service(s) have static checks only and are excluded.</div>` : ""}
      </div>
      <div class="card">
        <div class="muted">Average readiness score</div>
        <div class="tile-num">${o.score.latest}</div>
        <div class="muted">From ${o.score.baseline} at baseline. Static checks only. A higher score does not show that agents do better.</div>
      </div>
    </section>
    <section class="grid tiles">
      ${tile("Tasks blocked", `${o.repeat_failures.latest}`, `${o.repeat_failures.baseline} at baseline`)}
      ${tile("Time to identify a blocker", o.time_to_identify_ms === null ? "n/a" : `${o.time_to_identify_ms} ms`, "Median blocked probe run")}
      ${tile("Time to remediate", o.time_to_remediate_s === null ? "n/a" : `${o.time_to_remediate_s}s`, "Median, demo clock only")}
      ${tile("Findings verified", `${o.findings.verified}`, `${o.findings.open} open, ${o.findings.reopened} reopened`)}
    </section>
    <section class="card"><h2>Services</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>Service</th><th>Owner</th><th>Latest task</th><th>Blocked at</th><th class="num">Score</th><th class="num">Open findings</th></tr></thead>
        <tbody>${o.services.map((s) => `<tr>
          <td><a href="#/service/${encodeURIComponent(s.id)}">${esc(s.name)}</a></td><td>${esc(s.team)}</td>
          <td>${outcome(s.latest_run)}</td>
          <td>${s.latest_run?.status === "blocked" ? esc(dimLabel(s.latest_run.blocked_dimension)) : "—"}</td>
          <td class="num">${s.score}</td><td class="num">${s.open_findings}</td></tr>`).join("")}</tbody>
      </table></div>
    </section>
    <section class="card" style="margin-top:16px"><h2>Register a repository</h2>
      <p class="muted">Local path inside your home folder. AgentReady reads files and never runs code from a registered repository, so its task outcome stays unmeasured.</p>
      <form class="form" id="register">
        <label>Service name<input name="name" required maxlength="80"></label>
        <label>Owning team<input name="team" required maxlength="80"></label>
        <label>Path<input name="path" required placeholder="~/workspace/my-service"></label>
        <button>Register and assess</button>
      </form><div class="error" id="register-error" role="alert"></div>
    </section>`;
  document.getElementById("register").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target));
    try {
      const created = await api("/services", { method: "POST", body: JSON.stringify(data) });
      location.hash = `#/service/${encodeURIComponent(created.id)}`;
    } catch (error) {
      document.getElementById("register-error").textContent = error.message;
    }
  });
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

function findingCard(f, showService) {
  const actions = f.status === "verified" ? "" : `<div class="actions">
    ${["open", "reopened"].includes(f.status) ? `<button class="ghost" data-move="start" data-id="${f.id}">Start remediation</button>` : ""}
    ${f.status !== "awaiting_verification" ? `<button class="ghost" data-move="submit" data-id="${f.id}">Mark fix submitted</button>` : `<span class="muted">Waiting for reassessment to prove it.</span>`}
  </div>`;
  return `<article class="finding">
    <div class="finding-head"><span class="finding-title">${showService ? `${esc(f.service_name)}: ` : ""}${esc(f.title)}</span>
      <span class="status">${severity(f.severity)} <span class="chip">${STATUS[f.status]}</span></span></div>
    <div class="muted">${esc(dimLabel(f.dimension))} · ${esc(f.owner_team)}${f.reopen_count ? ` · reopened ${f.reopen_count}×` : ""}</div>
    ${evidenceList(f.evidence)}
    <p style="margin-top:6px"><strong>Recommended:</strong> ${esc(f.recommendation)}</p>${actions}</article>`;
}

function bindMoves(refresh) {
  view.querySelectorAll("[data-move]").forEach((button) => button.addEventListener("click", async () => {
    await api(`/findings/${button.dataset.id}/transition`, { method: "POST", body: JSON.stringify({ action: button.dataset.move }) });
    refresh();
  }));
}

function traceRow(t) {
  const c = t.classification;
  return `<tr><td>${esc(t.title)}<div class="muted">${esc(t.agent)}</div></td><td>${provenance(t.provenance)}</td>
    <td>${esc(c.label)}${c.quote ? `<div class="muted">Step ${esc(c.step)}: ${esc(c.quote)}</div>` : ""}</td>
    <td>${t.finding ? esc(STATUS[t.finding.status]) : "No linked finding"}</td></tr>`;
}

async function renderService(id) {
  const s = await api(`/services/${encodeURIComponent(id)}`);
  const run = s.latest_run;
  const previous = s.history.length > 1 ? s.history.at(-2) : null;
  const scoreRoseButBlocked = previous && s.score > previous.score && run?.status === "blocked";
  const open = s.findings.filter((f) => f.status !== "verified");
  const closed = s.findings.filter((f) => f.status === "verified");
  view.innerHTML = `
    <div class="page-head"><div><h1>${esc(s.name)}</h1><p class="sub">Owned by ${esc(s.team)}. Score ${s.score}, from ${s.baseline_score} at baseline.</p></div>
      <button id="assess">Reassess now</button></div>
    ${scoreRoseButBlocked ? `<div class="callout" role="status"><strong>The score rose ${s.score - previous.score} points, but the task is still blocked.</strong> This change has not helped an agent finish the work yet.</div>` : ""}
    <section class="grid two">
      <div class="card"><h2>Latest task ${run ? provenance("measured") : ""}</h2>
        ${run ? `<p class="muted">${esc(run.task_id)}: ${esc(run.title)}</p><p>${outcome(run)} <span class="chip">Run by script</span>
          ${run.status === "blocked" ? `<span class="chip" id="stop-kind">${run.steps.at(-1).output ? "Test failure" : "Rule-based stop"}</span>` : ""}
          <span class="muted">${(run.duration_ms / 1000).toFixed(2)}s</span></p>
        <ol class="steps">${run.steps.map((step) => `<li class="${step.status}"><span class="mark">${step.status === "passed" ? "✓" : "✕"}</span>
          <div><strong>${esc(step.name)}</strong><div class="muted">${esc(step.detail)}</div>
          ${step.status === "blocked" && step.output ? `<pre>${esc(errorLine(step.output))}</pre>
            <details><summary>Full output</summary><pre>${esc(step.output)}</pre></details>` : ""}</div></li>`).join("")}</ol>
        <p class="muted">The probe is a script that applies a known correct change. It tests the repository, not an LLM.</p>`
        : `<p class="muted">Not measured. AgentReady never runs code from registered repositories.</p>`}
      </div>
      <div class="card"><h2>Readiness by dimension</h2><p class="muted">Static checks</p>
        ${dimensions.map((d) => `<div class="bar-row"><span>${esc(d.label)}</span><div class="bar"><i style="width:${s.dimensions[d.key]}%"></i></div><b>${s.dimensions[d.key]}</b></div>`).join("")}
      </div>
    </section>
    <section class="grid two">
      <div class="card"><h2>Score and outcome over time</h2>${historyChart(s.history)}</div>
      <div class="card"><h2>Simulate a team fix</h2><p class="muted">Demo stand-in for a commit: it changes files in the sample repository. Reassess afterwards to see the measured result.</p>
        ${s.fixes.length ? s.fixes.map((fix) => `<div class="fix"><div><strong>${esc(fix.title)}</strong><div class="muted">${esc(fix.note)}</div></div>
          <button class="ghost" data-fix="${esc(fix.id)}" ${fix.applied ? "disabled" : ""}>${fix.applied ? "Applied" : "Apply"}</button></div>`).join("") : `<p class="muted">No scripted fixes for this service.</p>`}
      </div>
    </section>
    <section class="card" style="margin-bottom:16px"><h2>Open findings (${open.length})</h2>
      ${open.map((f) => findingCard(f)).join("") || `<p class="muted">No open findings.</p>`}
      ${closed.length ? `<details><summary>Verified findings (${closed.length})</summary>${closed.map((f) => findingCard(f)).join("")}</details>` : ""}
    </section>
    ${s.traces.length ? `<section class="card" style="margin-bottom:16px"><h2>Failed agent traces</h2><div class="table-wrap"><table>
      <thead><tr><th>Task</th><th>Source</th><th>Likely cause</th><th>Linked finding</th></tr></thead><tbody>${s.traces.map(traceRow).join("")}</tbody></table></div></section>` : ""}
    <section class="card"><h2>Activity</h2><div class="table-wrap"><table><tbody>
      ${s.events.map((e) => `<tr><td class="muted">${when(e.created_at)}</td><td>${esc(e.detail)}</td></tr>`).join("")}</tbody></table></div></section>`;
  const refresh = () => renderService(id);
  bindMoves(refresh);
  const assess = document.getElementById("assess");
  assess.addEventListener("click", async () => {
    assess.disabled = true;
    assess.textContent = "Running task…";
    await api(`/services/${encodeURIComponent(id)}/assess`, { method: "POST" });
    refresh();
  });
  view.querySelectorAll("[data-fix]").forEach((button) => button.addEventListener("click", async () => {
    button.disabled = true;
    await api(`/services/${encodeURIComponent(id)}/fixes/${encodeURIComponent(button.dataset.fix)}/apply`, { method: "POST" });
    refresh();
  }));
}

async function renderRemediation() {
  const findings = await api("/findings");
  const open = findings.filter((f) => f.status !== "verified");
  const teams = [...new Set(open.map((f) => f.owner_team))].sort();
  view.innerHTML = `<div class="page-head"><div><h1>Remediation</h1>
      <p class="sub">Work assigned to service owners. Teams can submit a fix, but only a reassessment can verify it.</p></div></div>
    ${teams.map((team) => {
      const rows = open.filter((f) => f.owner_team === team);
      return `<section class="card" style="margin-bottom:16px"><h2>${esc(team)} (${rows.length})</h2>${rows.map((f) => findingCard(f, true)).join("")}</section>`;
    }).join("") || `<p class="muted">Nothing open.</p>`}`;
  bindMoves(renderRemediation);
}

function heatCell(value, tip) {
  const strength = Math.round(12 + value * 0.8);
  const ink = strength > 75 ? "#fff" : "var(--ink)";
  return `<td class="cell" data-tip="${esc(tip)}" style="background:color-mix(in srgb, var(--accent) ${strength}%, var(--surface));color:${ink}">${value}</td>`;
}

async function renderPlatform() {
  const o = await api("/overview");
  const top = [...o.recurring].sort((a, b) => b.measured_blocks_latest - a.measured_blocks_latest || b.open_findings - a.open_findings);
  view.innerHTML = `<div class="page-head"><div><h1>Platform insights</h1>
      <p class="sub">Aggregate view for the AI coding-agent platform team. Use it to find blockers worth solving once, across teams.</p></div></div>
    <section class="card" style="margin-bottom:16px"><h2>Recurring blockers</h2><p class="muted">Sorted by measured blocks. Simulated traces are counted separately.</p>
      <div class="table-wrap"><table><thead><tr><th>Dimension</th><th class="num">Blocking now</th><th class="num">At baseline</th><th class="num">Open findings</th><th class="num">Services affected</th><th class="num">Simulated traces</th></tr></thead>
      <tbody>${top.map((r) => `<tr><td>${esc(r.label)}</td><td class="num">${r.measured_blocks_latest}</td><td class="num">${r.measured_blocks_baseline}</td>
        <td class="num">${r.open_findings}</td><td class="num">${r.services_affected}</td><td class="num">${r.simulated_traces}</td></tr>`).join("")}</tbody></table></div></section>
    <section class="card"><h2>Readiness heatmap</h2><p class="muted">Static check score per dimension, 0 to 100. Stronger blue is higher.</p>
      <div class="table-wrap"><table class="heat"><thead><tr><th>Service</th>${dimensions.map((d) => `<th>${esc(d.label.split(" ")[0])}</th>`).join("")}</tr></thead>
      <tbody>${o.services.map((s) => `<tr><td>${esc(s.name)}</td>${dimensions.map((d) => heatCell(s.dimensions[d.key], `${s.name}, ${d.label}: ${s.dimensions[d.key]}`)).join("")}</tr>`).join("")}</tbody></table></div></section>`;
}

async function renderTraces() {
  const traces = await api("/traces");
  const simulated = traces.filter((t) => t.provenance === "simulated").length;
  view.innerHTML = `<div class="page-head"><div><h1>Agent traces</h1>
      <p class="sub">Failed runs matched to a likely cause by rule-based signatures. Traces never count toward task completion.</p></div></div>
    <div class="callout">${simulated} of ${traces.length} traces are simulated fixtures. No real LLM agent has run in this demo.</div>
    <section class="card"><div class="table-wrap"><table><thead><tr><th>Task</th><th>Source</th><th>Likely cause</th><th>Linked finding</th></tr></thead>
    <tbody>${traces.map(traceRow).join("")}</tbody></table></div></section>`;
}

function jobTable(id, heading, note, jobs, status) {
  return `<section class="card" id="${id}" style="margin-bottom:16px"><h2>${heading}</h2><p class="muted">${note}</p>
    <div class="table-wrap"><table><thead><tr><th>Job</th><th>Why</th><th>Status</th></tr></thead>
    <tbody>${jobs.map(([job, why]) => `<tr><td>${esc(job)}</td><td>${esc(why)}</td><td>${status}</td></tr>`).join("")}</tbody></table></div></section>`;
}

async function renderAutomation() {
  const { automation } = await api("/overview");
  view.innerHTML = `<div class="page-head"><div><h1>Scripts first, AI where it is needed</h1>
      <p class="sub">Use a script when the answer is a fact. Use an AI agent when the job needs judgement, or when the agent's own behaviour is being measured.</p></div></div>
    <section class="grid tiles" id="counts">
      ${tile("Assessments by script", automation.assessments, "Since the last reset")}
      ${tile("Task runs by script", automation.task_runs, "Since the last reset")}
      ${tile("AI model calls", 0, "No AI is used in this prototype")}
      ${tile("Estimated saving", "Not measured", "Needs real agent runs")}
    </section>
    ${jobTable("script-jobs", "Scripts handle", "Fast, repeatable and cheap, so they can run on every change.", SCRIPT_JOBS, "Built")}
    ${jobTable("ai-jobs", "AI agents handle", "Reserved for a sample of tasks and for work scripts cannot judge.", AI_JOBS, "Planned")}
    <div class="callout" id="cost-note"><strong>How this lowers cost:</strong> scripts screen every service on every change, and agents run only on a small sample. When an agent finds a repeatable failure, it becomes a new script check.</div>`;
}

async function route() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [page, id] = hash.split("/");
  document.querySelectorAll("[data-nav]").forEach((link) => {
    const current = link.dataset.nav === (page || "overview") || (page === "service" && link.dataset.nav === "overview");
    if (current) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
  tooltip.hidden = true;
  try {
    if (page === "service") await renderService(decodeURIComponent(id));
    else if (page === "remediation") await renderRemediation();
    else if (page === "platform") await renderPlatform();
    else if (page === "traces") await renderTraces();
    else if (page === "automation") await renderAutomation();
    else await renderOverview();
  } catch (error) {
    view.innerHTML = `<p class="error" role="alert">${esc(error.message)}</p>`;
  }
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
  location.hash = "#/";
  route();
});
addEventListener("hashchange", route);

api("/dimensions").then((rows) => { dimensions = rows; route(); });
