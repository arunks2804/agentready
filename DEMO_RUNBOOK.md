# AgentReady Demo Runbook

## 1. Read this first

The demo runs in **Simulation mode**, and no AI model runs.

| Part | Real or simulated? |
|---|---|
| 17 script checks, including 6 of 17 and 9 of 17 | **Real** |
| Simulate team fix buttons | **Real file changes,** written in advance. No team is involved or informed |
| Findings from scripts | **Real** |
| Gap Analysis Agent findings and rechecks | **Simulated** |
| Coding Agent runs, code changes and test output | **Simulated** |
| Notifications Service and its teams | **Fictional** |

Every simulated result has a Simulated label, and a banner stays on every page.

**Real mode exists** under Settings, with real local models. It isn't used in the demo because the real Coding Agent isn't reliable yet.

## 2. Before you start

```bash
python3 -m uvicorn app.main:app --port 8010
```

Open http://127.0.0.1:8010, and click **Reset demo**. Check that **Simulation mode** appears under the header and `notifications-service` is selected. Ollama isn't needed.

## 3. Click by click

**Opening:** "This is AgentReady. It checks whether a service is ready for AI coding agents before work is assigned to them. This is a local prototype using one sample service, Notifications Service. In this demo, the agent steps are simulated with prepared data, because the coding agent isn't reliable yet. The script checks and file fixes are real, and simulated steps are labelled on screen."

| # | Click | What appears | Say |
|---|---|---|---|
| 1 | **Assess Readiness** | 6 of 17, and 13 open findings | Scripts check the facts. The simulated Gap Analysis Agent adds what scripts can't judge |
| 2 | **Findings** | Findings grouped by team | Each has an owner, evidence, a recommendation and what must pass to close it. There's no Jira link yet |
| 3 | **Simulate team fix** on the API contract, template guide, catalog and test command findings | The finding shows the fix was submitted | In a real product, the team would be informed and would make the fix. Here it's simulated with a prepared change. A team can't close its own finding |
| 4 | **Readiness**, then **Reassess** | 9 of 17, and 8 open | The simulated recheck closes the agent's two findings. Remaining gaps stay visible |
| 5 | **Coding task**, then **Validate with Coding Agent** | Passed, labelled Simulated | This is a simulated run |

Finish with the two closing parts, which match the video:

**After the first assessment:** "After this first assessment, the same process applies whenever work gets stuck. A story, bug or requirement is raised in Jira. If the coding agent can't complete it, it raises an issue to the platform. The platform analyses the issue, the gap goes to the owning team, it's fixed, and the service is reassessed. This part isn't built yet. This demo shows the first assessment only."

**Conclusion:** "AgentReady shows whether a service is ready for AI coding agents before work is assigned, and finds what's missing whenever agents get stuck. Every gap has an owner and evidence, and a gap closes only when reassessment confirms the fix. The process repeats as work continues, so agents can work smoothly. Don't just ask whether the AI agent is ready for work. Make sure it always has what it needs to do the work. This is an early prototype, and the next step is making the real coding agent reliable."

The Coding Agent is refused until the agent's findings are closed, which keeps the agreed order.

## 4. The recorded video

The video runs for 2:49, and follows steps 1 to 5. Recreate it with `python3 scripts/record_demo.py`. It stops if the app doesn't show what the narration says.

| Time | Part |
|---|---|
| 0:05 | Opening and limitation statement |
| 0:33 | Script checks |
| 0:41 | Gap Analysis Agent findings |
| 0:54 | Assignment |
| 1:07 | Simulated team fix |
| 1:20 | Reassessment |
| 1:38 | Coding task |
| 1:51 | What happens later (not built) |
| 2:20 | Conclusion slide |

## 5. Questions you may get

**Is any AI running in the demo?** No. The agent steps are simulated and labelled. The voiceover is AI-generated, by Piper running locally.

**Does a real agent exist?** Yes, behind a switch in Settings. The Gap Analysis Agent works on local models, but it's slow and variable. The Coding Agent isn't reliable yet.

**What went wrong with the Coding Agent?** With `qwen3:8b`, it passed 5 of 5 on the unfixed repository, but 0 of 5 with the fixes in place. In the failure we traced, it invented a module and restructured working code. The cause isn't proven.

**So do the fixes help?** On this sample, there's no evidence that they do.

**Why not just use a better model?** That may help, but it hasn't been tested. It also sends code to a provider, unlike the local setup.

**Is Jira connected?** No. It's part of the product, but isn't built yet.

**Is the team told about a finding?** Not today. It's assigned inside the app, and someone has to open it.

**Does a good result mean every future task will work?** No. A result applies only to the service, setup and scenarios tested.
