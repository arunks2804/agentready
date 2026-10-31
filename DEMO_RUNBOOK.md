# AgentReady Demo Runbook

This explains exactly what happens in the AgentReady demo: what is real, what is simulated, what gets copied, and what to say.

---

## 1. Read this first

**No AI runs anywhere in this demo.** No coding agent is called, and no Gap Analysis Agent exists yet.

| Common belief | What actually happens |
|---|---|
| A real coding agent is called | **No.** Nothing calls a coding agent |
| The script calls a coding agent | **No.** The script runs by itself |
| The script writes the code | **No.** It copies in a change written in advance |
| The script works out how to fix the bug | **No.** It already has the answer |
| The Gap Analysis Agent fixes things | **No.** It isn't built, and its planned job is to explain failures, not fix them |
| The tests are fake | **No.** The tests really run, and their pass or fail is real |
| This proves real coding agents do better | **No.** That has not been tested |

**In one sentence:** a script stands in for a coding agent, copies in a prepared code change, runs the real tests, and records what stopped them.

**Why does the script run code at all?** Reading files shows what information is missing. Running the tests shows which missing information actually stops the work.

---

## 2. Who does what

| Name | What it is | In this demo |
|---|---|---|
| **Coding agent** | An AI tool that works on tickets and changes code | **Not used** |
| **Script** (the scripted probe, `app/probe.py`) | A fixed list of steps | **Real.** It stands in for the coding agent |
| **Readiness checks** (`app/checks.py`) | 17 checks that read repository files | **Real** |
| **Sample services** | Three small services I wrote | **Real code, but made up.** Two have problems added on purpose |
| **Prepared code change** | The correct change for each ticket, written in advance | **Prepared.** The script copies it in |
| **Service-owning team** | The people who fix a readiness gap | **Simulated** by the **Apply** button |
| **Agent traces** | Logs from failed coding agent runs | **Simulated.** Written by hand, and not shown in the video |
| **Gap Analysis Agent** | Planned AI that explains failures scripts can't match | **Not built** |

---

## 3. What happens, step by step

The example is `billing-service` and ticket **BILL-2141: Fix proration rounding**.

**The defect:** `src/billing/proration.py` uses `int()`, which truncates the result. It should use `round()`.

### When the app loads the sample services
1. Reset copies each service from `samples/repos/` to `var/workspaces/`.
2. All later work uses the copy in `var/workspaces/`. The originals never change.

### When a task runs
This happens at first load, and each time you click **Reassess now**.

| Step on screen | What the script does | Real or prepared? |
|---|---|---|
| **Find the service** | Reads `catalog-info.yaml` and looks for the ticket's keyword, `proration` | **Real check.** The keyword comes from the prepared ticket |
| **Locate the code** | Confirms that `src/billing/proration.py` exists | **Real check.** The ticket tells it which file |
| **Find the test command** | Reads the docs and finds `python -m unittest discover -s tests` | **Real check** |
| **Prepare the environment** | Makes a temporary copy of the repository. Reads any settings from `.env.example` | **Real** |
| **Apply the code change** | Copies the prepared `proration.py` over the one in the temporary copy. This is the `int()` to `round()` change | **Prepared.** No code is written here |
| **Run the tests** | Runs the test command in the temporary copy, with a clean environment and a 30-second limit | **Real.** The result is not faked |

After the run, the temporary copy is deleted.

**This means the code change is never saved.** Even after a task completes, the sample service still has its `int()` defect. The run only proves that the task could finish.

### Why billing-service is blocked
1. The tests call the real code in `tax.py`.
2. `tax.py` needs the environment variable `BILLING_TAX_TABLE_PATH`.
3. Nothing documents that variable, so it isn't set.
4. The code crashes with `KeyError: 'BILLING_TAX_TABLE_PATH'`.
5. The script matches that error to a known pattern and records a **blocker**.
6. The blocker is assigned to `team-billing`, with the error as evidence.

### When you click Apply
This stands in for the team's work. It copies files from `samples/fixes/` into `var/workspaces/billing-service/`.

| File copied | Contents |
|---|---|
| `.env.example` | `BILLING_TAX_TABLE_PATH=config/tax_rates.sample.json` |
| `config/tax_rates.sample.json` | `{"CA": 0.075}` |

**The button does not change the result by itself.** The task only changes when the rerun finds those files.

### When you click Reassess now
1. The readiness checks read the repository again.
2. The script repeats every step, including the prepared code change.
3. This time the variable is set and the file exists, so the real tests pass.
4. The task shows **Completed**, and the blocker shows **Verified**.

Only a reassessment can set a finding to Verified. A person can't.

---

## 4. Two kinds of "blocked"

This difference matters if someone looks closely.

| | Test failure | Rule-based stop |
|---|---|---|
| **What happened** | The tests really ran and failed | The script found something missing and stopped before running any test |
| **Where** | `billing-service` | All three `notifications-service` blocks |
| **What it proves** | The work really was stopped | Only that the script's rule was not met. A real coding agent might get past it |
| **Label in the app** | **Test failure** | **Rule-based stop** |

---

## 5. Real, prepared or simulated

| Part | Status |
|---|---|
| Reading repository files | **Real** |
| Running the tests | **Real** |
| Tests passing or failing | **Real** |
| Scores and counts | **Real**, calculated from the runs |
| Sample services, tickets and teams | **Made up** |
| The problems in the samples | **Added on purpose** |
| The code change | **Prepared in advance** |
| The team's fix | **Simulated**, prepared in advance and applied with a button |
| Agent traces | **Simulated** |
| Coding agent | **Not used** |
| Gap Analysis Agent | **Not built** |
| Voiceover | **AI-generated** by Piper, not an AI agent in the product |

---

## 6. Can a script do this on real, complex code?

**Only partly.** It works here because I wrote the samples and prepared the answer.

| Job | Can a script do it on real code? |
|---|---|
| Read files, contracts and CI settings | **Yes** |
| Find undocumented environment variables | **Yes** |
| Run existing builds and tests | **Yes**, if the setup is defined. Complex services are harder |
| Match known failures | **Yes** |
| Understand a new ticket and work out the code change | **No.** This needs a coding agent |
| Trace a problem across several services | **No** |
| Explain a failure it hasn't seen before | **No.** This is the Gap Analysis Agent's planned job |

### How a real product would work
1. Scripts check every service on every change.
2. A real coding agent attempts a sample of tickets.
3. When it fails, scripts match known failure patterns.
4. If nothing matches, the Gap Analysis Agent explains the failure.
5. The owning team fixes the gap.
6. The coding agent tries the same ticket again.

None of steps 2 to 6 is connected to real systems yet. In this demo, the script stands in for the coding agent, and a button stands in for the team.

---

## 7. Run the demo live

### Before you start
Run these from the `agentready` folder:

```bash
python3 -m pip install -r requirements.txt
```

```bash
python3 -m uvicorn app.main:app --port 8010
```

1. Open http://127.0.0.1:8010.
2. Click **Reset demo**, then confirm. This is safe, and it removes only demo data.

### Part 1: where we start
**On screen:** Overview.

**Check that you see:** 33% task completion, 1 of 3 tasks complete.

| Service | Score | Latest task | Blocked at |
|---|---|---|---|
| billing-service | 88 | Blocked | Build environment |
| notifications-service | 12 | Blocked | Discovery |
| identity-service | 96 | Completed | — |

**Say:** "Each sample service has one ticket. A script stands in for a coding agent. Only one task finishes today. Billing is blocked, even though it scores 88."

### Part 2: what stopped the task
**Click:** `billing-service`.

**Point to:** the **Latest task** steps, then `KeyError: 'BILLING_TAX_TABLE_PATH'`.

**Say:** "The ticket is a proration rounding defect. The script copies in a prepared code change, then runs the real unit tests to validate it. The tests crash because an environment variable isn't documented. So the script can't validate the change."

**Scroll to:** Open findings, then **Required settings work**.

**Say:** "That becomes a blocker with evidence, a recommended fix, and team-billing as the owner."

### Part 3: the team fixes it
**Scroll to:** Simulate a team fix.

**Click:** **Apply** next to **Add a working sample settings file**.

**Say:** "This button stands in for team-billing. It copies in a sample settings file."

**Click:** **Reassess now**.

**Check that you see:** the task shows **Completed**, and the score is **94**.

**Say:** "The script reran the whole task, and the real tests passed. The finding closed because the rerun proved it, not because someone said so."

### Part 4: a view for each team
**Click:** **Remediation**.

**Say:** "Each team sees its own list of work."

**Click:** **Platform insights**.

**Say:** "The team that runs coding agents sees which problems come up most."

### Part 5: three blockers
**Click:** **Overview**, then `notifications-service`.

| Step | Click | Then you should see |
|---|---|---|
| Start | — | Blocked at **Find the service**, score 12 |
| 1 | Apply **Add the service to the catalog**, then **Reassess now** | Blocked at **Read the API contract**, score 19 |
| 2 | Apply **Publish the API contract**, then **Reassess now** | Blocked at **Find the test command**, score 32 |
| 3 | Apply **Document the test command**, then **Reassess now** | **Completed**, score 41 |

**Say:** "Each fix reveals the next blocker. These three are rule-based stops, not test failures. The task finished at 41, while billing was blocked at 88, so a score alone can't tell you whether the work will finish."

### Part 6: scripts and AI
**Click:** **Scripts and AI**.

**Check that you see:** 7 assessments, 7 task runs, 0 AI model calls, saving not measured.

**Say:** "Scripts handle the facts. A real coding agent would attempt tasks, and the Gap Analysis Agent would explain new failures. Those AI roles are planned, and the cost saving hasn't been measured."

**Finish with Overview:** 100% task completion, 3 of 3 tasks complete.

**Say:** "This shows the method on sample services. The next step is testing with a real coding agent on real repositories."

### If you're asked for the weak-fix example
1. Click **Reset demo** and confirm.
2. Open `billing-service`, then open **Other changes to try**.
3. Apply **Add architecture overview**, then click **Reassess now**. The score rises to 92, and the task stays blocked.
4. Apply **Name the setting only**, then click **Reassess now**. The score reaches 97, the task stays blocked, and the finding reopens.

---

## 8. The recorded video

Video: https://arunks2804.github.io/agentready/ (7:53, with full captions)

| Time | Part | What it covers |
|---|---|---|
| 0:02 | Opening | The problem, the five steps, and how the demo works |
| 0:43 | How this demo works | No AI runs. The script stands in for a coding agent, using a prepared code change |
| 1:22 | 1 · Where we start | One of three tickets completes |
| 1:45 | 2 · What blocked the ticket | BILL-2141, the undocumented environment variable and the recommended fix |
| 2:52 | 3 · The team fixes it | The recommended fix is applied, and the rerun completes |
| 3:16 | 4 · A view for each team | Remediation queues and recurring blockers |
| 3:43 | 5 · A ticket with three blockers | NOTIF-877, one layer at a time |
| 6:21 | 6 · Scripts first, AI where it counts | Scripts, what a real coding agent would do, and cost |
| 7:38 | Summary | Before and after, and the next step |

Captions show the exact technical names, such as `BILLING_TAX_TABLE_PATH`. The voice says them as separate words so they can be pronounced.

---

## 9. Questions you may get

**Is a real coding agent running?**
No. A script stands in for one. No AI model is called.

**Then how can you say this is about AI agents?**
The product is built for AI coding agents, but this prototype only proves the workflow. Whether fixing these gaps helps a real coding agent has not been tested.

**Who wrote the code change?**
I did, in advance. It's stored in `samples/tasks/`, and the script copies it in. That removes coding mistakes as a cause of failure, so the run tests the repository.

**Does the script run code?**
Yes. It runs the sample service's tests, and those tests run the service's code. It runs them only on the bundled samples, in a temporary copy. It never runs code from a repository you register.

**Can a script do this on a complex codebase?**
It can check the repository and run existing tests if the setup is defined. It can't work out a code change for a new ticket. That needs a real coding agent.

**Are the results real?**
Test passes and failures are real, but the services are made up and the problems were added on purpose. The 1-of-3 to 3-of-3 result shows the method and isn't evidence of real-world improvement.

**Is the bug fixed at the end?**
No. The code change is applied only to a temporary copy. The run proves the task could finish. Nothing is saved to the sample service.

**Does AgentReady fix the problems?**
No. It finds them, assigns them and verifies the result. The owning team fixes them.

**What's the difference between the coding agent and the Gap Analysis Agent?**
The coding agent attempts the ticket. The Gap Analysis Agent would read a failed run and explain why it failed. Neither runs in this demo.

**Do you need a ticketing system?**
Not in the prototype: AgentReady tracks each finding itself. A real deployment would connect to Jira, with AgentReady deciding whether a fix worked.

**What's the next step?**
Run a real coding agent on real repositories, before and after remediation, and compare task completion.
