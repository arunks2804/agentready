# Real model results

Run on 1 November 2026 on one laptop with 17 GB of memory, against the fictional Notifications sample. These are small samples, so they show what happened here and do not predict other services.

## Models

| Model | Gap Analysis Agent | Coding Agent |
|---|---|---|
| `qwen3:8b` | Findings in 4 of 4 runs with the final design | See below |
| `llama3.1:8b` | Failed 2 of 2 runs, on an earlier design | Failed 4 of 4 runs, on an earlier design, while claiming success |
| `deepseek-r1:8b` | One run still unfinished after 15 minutes | Not reached |

## Gap Analysis Agent, `qwen3:8b`

- Each run took 7–19 minutes, with thinking on. With thinking off, it found nothing.
- It found the API contract problem in 4 of 4 runs, and the wrong template guide in 2 of 4.
- AgentReady confirmed that every accepted quote is in the file. It rejected invented or altered quotes.
- In one run it reported the API problem twice, and deduplication merged the reports into one finding.

## Coding Agent, `qwen3:8b`, final setup

| State of the repository | Passed |
|---|---|
| Before the fixes | 5 of 5 |
| After the fixes | 0 of 5 |

- The before-fix run was an extra experiment. It is not a step in the product.
- In the failed run we traced, the agent invented a module and restructured working code. Why this happens after the fixes is not proven.
- AgentReady caught every failure from the code and tests, including runs on an earlier design where the model claimed success.

## Not proven

- The Gap Analysis Agent's recheck was changed after a real run judged fixed files wrongly. Its new version has automated tests, but no real run yet.
- Whether fixing readiness gaps helps a coding agent. This sample does not show that it does.
