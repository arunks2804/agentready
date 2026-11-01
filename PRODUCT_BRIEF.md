# AgentReady — Product Brief

> **Proposition:** Find out whether a service is ready for AI coding agents before stories are assigned to them, assign each gap to the team that owns it, and prove the fix through reassessment.

> **Status:** Local proof of concept on one fictional service, Notifications Service. The demo runs in Simulation mode, because the real Coding Agent is not reliable yet.

Setup is in [README.md](README.md). Real model results are in [docs/examples/SUMMARY.md](docs/examples/SUMMARY.md).

## 1. Overview

Coding agents fail on services that are missing what they need: wrong documentation, an inaccurate API contract, or no test command. AgentReady is not another coding agent. It assesses a service first and turns each gap into evidence-backed work for the owning team.

| | |
|---|---|
| **Primary value** | Proactive readiness assessment before AI coding tasks |
| **Users** | Service-owning teams, the AI coding-agent platform team, engineering managers, engineers operating coding agents |
| **Prototype** | FastAPI, SQLite, plain JavaScript, local Ollama, Playwright demo |

## Product demo

[![AgentReady product demo — click to play](docs/demo/agentready-demo-preview.gif)](https://arunks2804.github.io/agentready/)

**▶ [Watch the narrated demo (under 3 min, 1920×1080, with sound)](https://arunks2804.github.io/agentready/)**. It follows Notifications Service from first assessment through a later bug.

## 2. The process

1. Scripts and the Gap Analysis Agent find the gaps.
2. AgentReady records each gap and assigns it to the owning team, inside the app.
3. The team fixes it.
4. Reassessment confirms the fix.
5. The Coding Agent tries a representative task.

A later failure enters the same gap analysis. It does not need a separate feature. Known problems go straight to scripts, unknown ones go to the Gap Analysis Agent, and a problem that matches an existing finding updates it instead of duplicating it.

## 3. Users

| Persona | Question | How AgentReady helps |
|---|---|---|
| Service-owning team | "What is stopping agents on my service, and can you prove it?" | Findings arrive assigned, with evidence, a recommendation and what must pass to close them |
| AI coding-agent platform team | "Which problems are worth solving once for everybody?" | A platform view of open findings across services |
| Engineering manager | "Which of this work is worth my team's time?" | Findings ordered by severity, grouped by team |
| Engineer operating a coding agent | "Will it work before I assign it?" | Readiness and coding results are shown separately, with their scope |

## 4. Scripts first, AI where it is needed

| Job | Handled by |
|---|---|
| Files, metadata, contracts, configuration, tests, CI | **Scripts:** repeatable, and no model call |
| Docs or contracts that exist but are wrong or misleading | **Gap Analysis Agent** |
| Failures that match no known pattern | **Gap Analysis Agent** |
| Attempting a representative task | **Coding Agent** |

Passing a file check does not prove that a document is correct or sufficient. That is why the Gap Analysis Agent exists. A rule saves model calls too: while the text an agent cited is unchanged, reassessment needs no model.

## 5. What works today

| Capability | Status |
|---|---|
| 17 readiness checks across 8 dimensions | **Working** |
| Findings with evidence, owner, severity, status and closure rule | **Working** |
| Prepared fixes and reassessment with history | **Working.** Fixes are prepared in advance |
| Simulation mode for agents and Jira | **Working.** Labelled on screen |
| Real Gap Analysis Agent on local Ollama | **Works, but slow and variable** |
| Deduplication of agent findings | **Working** on a real run |
| Recheck of agent findings on a real model | **Unproven.** Changed after a real run judged fixed files wrongly |
| Real Coding Agent on local Ollama | **Built, not reliable.** 0 of 5 with the fixes in place |
| Independent verification of coding results | **Working.** Caught every failed run |
| Jira integration | **Not built.** Simulated in the demo |

## 6. Honest limits

- The acceptance goal of a real end-to-end demo is **not met**. The demo is simulated by decision, and says so.
- The sample service is fictional and small.
- On this sample, `qwen3:8b` passed the coding task 5 of 5 before the fixes and 0 of 5 after them. So there is no evidence yet that the fixes help a coding agent.
- A good readiness result does not guarantee every future task. Any conclusion applies only to the service, agent setup and scenarios tested.
- Scripted or simulated success is never labelled as a real run.

## 7. Production considerations

These are not delivered. A production system would need secure enterprise integration, repository permissions, identity and secrets management, tenancy, sandboxed distributed execution, scaling, observability, reliability, audit and operational policy.

## 8. What comes next

1. Make the real Coding Agent reliable, and find out why it fails after the fixes.
2. Decide whether local models are enough, or test a stronger model.
3. Prove the recheck on a real run.
4. Connect Jira, instead of simulating it.
5. Try a real service.
