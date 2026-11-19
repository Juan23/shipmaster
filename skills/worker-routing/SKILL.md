---
name: worker-routing
description: "Use before dispatching any worker (builds, fixes, check runs, reviewers, merges, audits) and after one finishes: pick its tier (DeepSeek, Gemini or Claude) from the performance log, then record the outcome. Also for questions about tier/model statistics."
---

Every worker dispatch is a **routing** decision backed by the performance log, and every finished worker adds one **row** to it. Route to the cheapest tier the evidence doesn't rule out.

Tool: `python3 ~/.claude/skills/worker-routing/perf.py` — `route` before a dispatch, `add` after it, `rework` when its output later needs another build or test cycle, `stats` only when the user asks for statistics. The log is shared by every project (`~/.claude/skills/worker-routing/agent-performance-log.jsonl`), append-only, and owned by the tool: one `route` call and one `add` call per worker, one `rework` call per defect found later, nothing else touches the file.

## Which work comes here (owner, 2026-11-19)

Every worker dispatch is routed here: builds, fixes and check runs, reviews (rule 5), merges, audits, diagnosis, device runs and design work. The cheapest tiers are DeepSeek and Gemini, run from the shell; the rest are Claude subagents.

## Tiers

Cheapest first (owner, 2026-11-19):
`deepseek-high` → `hydrogen-medium` → `argon-medium` → `sonnet-high` → `opus-medium` → `opus-high` → `opus-xhigh`.
PR reviews use their own agents, not a tier (rule 5).

| Tier | Runs as | Model |
|---|---|---|
| `deepseek-high` | opencode, the call in the `opencode-worker` skill | `opencode-go/deepseek-v4.1-flash#high` |
| `hydrogen-medium` | agy, the call below | `gemini-4-hydrogen-medium` (agy's default effort for Hydrogen) |
| `argon-medium` | agy, the call below | `gemini-4-argon-medium` (agy's default effort for Argon) |
| `haiku-medium`, `sonnet-high`, `opus-*` | Agent tool, `subagent_type` = the tier | the agent file in `~/.claude/agents/` |

The agy call, run from the worker's own worktree (`SCRATCH`: the session scratch folder):

```bash
~/.claude/skills/opencode-worker/limited.sh 1800 agy -p "<task>" --model gemini-4-hydrogen-medium \
  --print-timeout 1770s --output-format json < /dev/null > "$SCRATCH/agy.json" 2> "$SCRATCH/agy.err"
```

- agy's default mode edits files and runs commands headless; `--mode auto` is not available on this account.
- `ktok` for the row: `usage.total_tokens` in `agy.json`, in thousands.
- Hydrogen shares its quota with Neon and Gemini 3.8 Flash (resets about every 5 hours); Argon has its own weekly pool. A quota error is an `env` blocker: `route ... --after` that tier.
- Check a DeepSeek or Gemini worker's result yourself (diff, the repo's checks, scope), as the `opencode-worker` skill says.

Haiku is dropped except for the work the log shows it doing reliably: audits (research and read-only checks) at any complexity, and cleanup, merge and simple coding below c2.5. There `route` starts at `haiku-medium`, one step below `deepseek-high`; everywhere else it never returns Haiku.

Retired, never dispatched: `haiku-high`, `opus-low` (owner, 2026-11-02), `haiku-xhigh` (2026-10-22) and `sonnet-medium` (owner, 2026-11-19). Old rows stay in `stats`.

## Dispatch

1. Classify the task's **type** (`audit`, `merge`, `cleanup`, `coding`, `bug-diagnosis`, `harness-build`, `device-run`, `harness-fix`, `review`) and score **complexity** 1.0–5.0, one decimal place (1 = mechanical, 3 = one ticket, 5 = multi-platform harness with unknown root cause). Hold both for the row. `audit` finds facts (research, read-only checks); `design` compares ways to build something and reports options with trade-offs, such as a gremlins design scout. Hosted-harness work splits three ways: `harness-build` writes or changes runner, fixture, or checkpoint code; `device-run` executes a packaged iOS/Android run and reports; `harness-fix` diagnoses a failed run, patches, and reruns. Set `--platform ios|android|both` on any task that touches a device (default `none`); it is recorded for stats and does not change routing. Old rows keep the retired type `hosted-harness`; it shows in stats but `route` and `add` reject it.
2. `perf.py route --type <type> --complexity <#.#>`. It starts from a complexity floor, drops to a cheaper tier the log has **proven** on similar tasks, and steps over tiers the log shows **weak**.
3. Start the routed tier the way the Tiers table says. Override it only with a reason the log can't see (for example, the task needs a device run the worker must design from scratch), and put that reason in the row's note. Give the worker an attempt cap for device runs.
4. **Owner default at c5** (complexity ≥ 4.5, any type): spawn `sonnet-high` whatever `route` returns, and start the row's note with `owner-default c5:`. The owner set this on 2026-10-13.
5. **Owner default for every PR review**: spawn `pr-reviewer` for a review before the PR is opened and `merge-reviewer` for a review of an open PR, whatever `route` returns, even at c5 (this rule overrides rule 4). Both run the current Opus model at high effort; record the row with `--model opus --effort high`, type `review`, and start its note with `owner-default review:`. The review gate accepts only these two agents, and one fixed reviewer makes the review rows a measure of that reviewer.

## Escalation

When a worker returns `partial`/`fail` with `blocker: model`, self-declines on size, or retries blindly: record its row, then `route ... --after <its tier>` for the next one. An `env` blocker (device, host, network, staging drift) keeps the same tier: fix the environment and redispatch.

## Recording

After **each** worker finishes, append its row before acting on the result:

```bash
python3 ~/.claude/skills/worker-routing/perf.py add --model deepseek --effort high --type coding --platform none --task "#88 capacity copy fix" --complexity 3 --outcome pass --blocker none --attempts 0 --interventions 0 --ktok 194 --note "one line: what happened and why"
```

- `--model`: `haiku`, `sonnet`, `opus`, `deepseek`, `hydrogen` or `argon`.
- `ktok`: exact `subagent_tokens` from the task-notification `<usage>`, in thousands; for agy, `usage.total_tokens`; for opencode, the token totals of its `step_finish` events. Leave it out only for a killed or timed-out run that reported none.
- `blocker`: `model` when the worker's reasoning or harness code failed it; `env` when the device, host, network, or staging state did; `none` otherwise.
- `attempts`: device runs or retries used. `interventions`: orchestrator messages that redirected or unblocked it.
- `--escalated-from`/`--escalated-to`: tier names, set on both rows of a hand-off. `--wall-min` when known.

Done when `add` reports the appended row.

## Rework

**Rework** is a defect in a worker's accepted output, found later (review, screenshot check, device run), that forces another build or test cycle — a slight visual inconsistency counts. The owner's scarce resource is wall-clock time, and rework spends it, so `route` scores a reworked row 0.5 lower: a reworked pass ranks like a partial. A fix that needs no rebuild or retest (copy, comment) is not rework.

When you find rework, charge it to the worker whose row produced it, before dispatching the fix:

```bash
python3 ~/.claude/skills/worker-routing/perf.py rework --task "#88 capacity copy fix" --cycles 1 --wall-min 25 --note "one line: the defect and how it surfaced"
```

- `--task`: the exact `--task` of that worker's row; it charges the latest row with that task.
- `--cycles`: extra build/test cycles the defect caused. `--wall-min`: wall-clock minutes they cost, when known.

The fix itself is a new worker with its own `route` and `add`.
