# AgentReady

Checks whether a service is ready for AI coding agents **before** work is assigned to them. It finds missing prerequisites, assigns each gap to the owning team, and proves a fix through reassessment.

**This is a local prototype. The demo runs in Simulation mode.** Agent steps use prepared data, because the real Coding Agent is not reliable yet. Script checks and file fixes are real.

[![AgentReady demo — click to play](docs/demo/agentready-demo-preview.gif)](https://arunks2804.github.io/agentready/)

**▶ [Watch the narrated demo (2:31, 1080p, with sound)](https://arunks2804.github.io/agentready/)** · [download the MP4](docs/demo/agentready-demo.mp4). The video was recorded on one machine. Nothing runs in your browser. The voiceover is AI-generated (Piper, run locally).

📄 [PRODUCT_BRIEF.md](PRODUCT_BRIEF.md) covers the product and its scope. 🎬 [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) gives a click-by-click script. 📊 [docs/examples/SUMMARY.md](docs/examples/SUMMARY.md) has the real model results.

## Run

```bash
python3 -m pip install -r requirements.txt
python3 -m uvicorn app.main:app --port 8010
```

Open http://127.0.0.1:8010. Tests: `python3 -m pytest`.

## The process

1. Scripts and the Gap Analysis Agent find the gaps.
2. AgentReady records each gap and assigns it to the owning team, inside the app. There is no Jira link yet.
3. The team fixes it. In the demo, a **Simulate team fix** button applies a prepared change to the sample files. The team is not informed.
4. Reassessment confirms the fix.
5. The Coding Agent tries the task.

The same process is intended for later failures, such as a Jira story or bug that the Coding Agent cannot complete. That part is not built. The full proposition is in the product brief.

## What is real and what is simulated

| Part | In Simulation mode (default) | In Real mode |
|---|---|---|
| 17 readiness checks | Real | Real |
| Prepared fixes | Real file changes, prepared in advance | Same |
| Gap Analysis Agent | **Simulated** | Real local model. Works, but slow and variable |
| Reassessment of agent findings | **Simulated** | Real, but the latest version is unproven on a real run |
| Coding Agent | **Simulated** | Real local model. **Not reliable** |
| Jira | Not built | Not built |

Switch modes under **Settings**. Real mode needs [Ollama](https://ollama.com) running locally with a model that supports tools. AgentReady reads the installed models at runtime and refuses a non-local Ollama address.

## Real model results

On the Notifications sample with `qwen3:8b`, run on one laptop:

- The Gap Analysis Agent produced findings with verified quotes in 4 of 4 runs, at 7–19 minutes each.
- The Coding Agent passed the task **0 of 5 times with the fixes in place**. It passed 5 of 5 on the unfixed repository, in an extra experiment. So this sample does **not** show that the fixes help a coding agent.

Details are in [docs/examples/SUMMARY.md](docs/examples/SUMMARY.md).

## Safety of real runs

Model-written code runs only in a temporary copy of a bundled sample, with an allowlisted test command, under a macOS sandbox with no network, no writes outside the copy and no reads of the home folder. If the sandbox is unavailable, the run is refused. A model's claim of success is never trusted: AgentReady reads the diff and runs its own acceptance tests.

## Re-record the demo

You need ffmpeg and a Piper voice in `var/voices/`:

```bash
python3 -m pip install -r requirements-demo.txt
python3 -m playwright install chromium
python3 -m piper.download_voices --download-dir var/voices en_GB-cori-high
python3 scripts/record_demo.py
```

The recorder runs its own copy of the app on port 8019 and stops if the app does not show what the narration says.

## Limits

- This is a proof of concept, not a production system. It has no login and should stay on localhost.
- Agent steps in the demo are simulated. There is no Jira integration, and teams are not notified.
- A good readiness result does not guarantee every future task. Any conclusion applies only to this service, setup and scenario.
- The sandbox is macOS only.
- Registered repositories get static checks only. Their code is never run.
- `billing-service` and `identity-service` remain as optional test data, and are not part of the demo.
