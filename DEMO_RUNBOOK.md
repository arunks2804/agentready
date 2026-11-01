# AgentReady Demo Runbook

## 1. Read this first

The demo runs in **Simulation mode**, and no AI model runs.

| Part | Real or simulated? |
|---|---|
| 17 script checks, including 6 of 17 and 9 of 17 | **Real** |
| Prepared fix buttons | **Real file changes,** written in advance |
| Findings from scripts | **Real** |
| Gap Analysis Agent findings and rechecks | **Simulated** |
| Coding Agent runs, code changes and test output | **Simulated** |
| Bug NOTIF-931 and Jira request NOTIF-932 | **Simulated** |
| Notifications Service, teams and customers | **Fictional** |

Every simulated result has a Simulated label, and a banner stays on every page.

**Real mode exists** under Settings, with real local models. It isn't used in the demo because the real Coding Agent isn't reliable yet.

## 2. Before you start

```bash
python3 -m uvicorn app.main:app --port 8010
```

Open http://127.0.0.1:8010, and click **Reset demo**. Check that **Simulation mode** appears under the header and `notifications-service` is selected. Ollama isn't needed.

## 3. Click by click

| # | Click | What appears | Say |
|---|---|---|---|
| 1 | **Assess Readiness** | 6 of 17, and 13 open findings | Scripts check the facts. The simulated Gap Analysis Agent adds what scripts can't judge |
| 2 | **Findings** | Findings grouped by team | Each has an owner, evidence, a recommendation and what must pass to close it. There's no Jira link yet |
| 3 | **Apply prepared fix** on the API contract, template guide, catalog and test command findings | The finding shows the fix was submitted | This really changes the sample files. A team can't close its own finding |
| 4 | **Readiness**, then **Reassess** | 9 of 17, and 8 open | The simulated recheck closes the agent's two findings. Remaining gaps stay visible |
| 5 | **Coding task**, then **Validate with Coding Agent** | Passed, labelled Simulated | This is a simulated run |
| 6 | **Raise bug NOTIF-931** | Not fixed, and Jira request NOTIF-932 | The simulated agent can't explain error 4701, so it raises a simulated request |
| 7 | **Diagnose from Jira request** | A link to the exposed gap | AgentReady reads the request and exposes the gap |
| 8 | **Findings**, then **Apply prepared fix** on SMS sender rules | The fix is submitted | This adds a real file, `docs/sms.md` |
| 9 | **Readiness**, then **Reassess** | The finding closes | Only reassessment closes it |
| 10 | **Coding task**, then **Rerun bug fix** | Fixed, labelled Simulated | The simulated rerun fixes the bug |

The Coding Agent is refused until the agent's findings are closed, which keeps the agreed order.

## 4. The recorded video

The video runs for 2:41, and follows steps 1 to 10. Recreate it with `python3 scripts/record_demo.py`. It stops if the app doesn't show what the narration says.

| Time | Part |
|---|---|
| 0:05 | Opening and limitation statement |
| 0:33 | Script checks |
| 0:41 | Gap Analysis Agent findings |
| 0:55 | Assignment |
| 1:07 | Fixes |
| 1:20 | Reassessment |
| 1:38 | Coding task |
| 1:50 | Bug and Jira request |
| 2:07 | Gap exposed |
| 2:15 | Fix, reassess and rerun |
| 2:31 | Close |

## 5. Questions you may get

**Is any AI running in the demo?** No. The agent steps are simulated and labelled. The voiceover is AI-generated, by Piper running locally.

**Does a real agent exist?** Yes, behind a switch in Settings. The Gap Analysis Agent works on local models, but it's slow and variable. The Coding Agent isn't reliable yet.

**What went wrong with the Coding Agent?** With `qwen3:8b`, it passed 5 of 5 on the unfixed repository, but 0 of 5 with the fixes in place. In the failure we traced, it invented a module and restructured working code. The cause isn't proven.

**So do the fixes help?** On this sample, there's no evidence that they do.

**Why not just use a better model?** That may help, but it hasn't been tested. It also sends code to a provider, unlike the local setup.

**Is Jira connected?** No. It's simulated. A real link is planned.

**Does a good result mean every future task will work?** No. A result applies only to the service, setup and scenarios tested.
