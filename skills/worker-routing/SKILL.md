---
name: worker-routing
description: "Use before dispatching any worker subagent (Agent tool) and after one finishes: pick its tier from the performance log, then record the outcome. Also for questions about tier/model statistics."
---

Every worker dispatch is a **routing** decision backed by the performance log, and every finished worker adds one **row** to it. Route to the cheapest tier the evidence doesn't rule out.

Tool: `python3 ~/.claude/skills/worker-routing/perf.py` — `route` before a dispatch, `add` after it, `rework` when its output later needs another build or test cycle, `stats` only when the user asks for statistics. The log is shared by every project (`~/.claude/skills/worker-routing/agent-performance-log.jsonl`), append-only, and owned by the tool: one `route` call and one `add` call per worker, one `rework` call per defect found later, nothing else touches the file.

## Tiers

Agent types in `~/.claude/agents/`, cheapest first:
`haiku-medium` → `haiku-high` → `sonnet-high` → `opus-low` → `opus-medium`.
`opus-high` is the PR reviewer only (rule 5), not a routing tier; `route` never returns it.

`sonnet-medium` and `haiku-xhigh` are retired (owner, 2026-10-22: weak or costly in the log); never dispatch them. Their old rows stay in `stats`.

Haiku costs ~20× less per token than Sonnet, so a Haiku pass at several times the tokens is still the cheaper pass.

## Dispatch

1. Classify the task's **type** (`audit`, `merge`, `cleanup`, `coding`, `bug-diagnosis`, `harness-build`, `device-run`, `harness-fix`, `review`) and score **complexity** 1.0–5.0, one decimal place (1 = mechanical, 3 = one ticket, 5 = multi-platform harness with unknown root cause). Hold both for the row. Hosted-harness work splits three ways: `harness-build` writes or changes runner, fixture, or checkpoint code; `device-run` executes a packaged iOS/Android run and reports; `harness-fix` diagnoses a failed run, patches, and reruns. Set `--platform ios|android|both` on any task that touches a device (default `none`); it is recorded for stats and does not change routing. Old rows keep the retired type `hosted-harness`; it shows in stats but `route` and `add` reject it.
2. `perf.py route --type <type> --complexity <#.#>`. It starts from a complexity floor, drops to a cheaper tier the log has **proven** on similar tasks, and steps over tiers the log shows **weak**.
3. Spawn with `subagent_type` set to the routed tier. Override it only with a reason the log can't see (for example, the task needs a device run the worker must design from scratch), and put that reason in the row's note. Give the worker an attempt cap for device runs.
4. **Owner default at c5** (complexity ≥ 4.5, any type): spawn `sonnet-high` whatever `route` returns, and start the row's note with `owner-default c5:`. The owner set this on 2026-10-13.
5. **Owner default for every PR review** (the final review that gates a merge and any earlier or re-review of a PR): spawn `opus-high` (Opus 5.5, high effort; `--model opus --effort high` on the row) whatever `route` returns, even at c5 (this rule overrides rule 4), type `review`, and start the row's note with `owner-default review:`. The owner set this on 2026-10-22 with `opus-medium` and raised it to `opus-high` on 2026-10-25: one fixed reviewer makes the review rows a measure of that reviewer's effectiveness, and the final review no longer comes from the Haiku tiers it judges. Review rows before 2026-10-22 mix tiers and are not evidence of it; review rows from 2026-10-22 to 2026-10-24 are opus-medium, and from 2026-10-25 they are opus-high.

## Escalation

When a worker returns `partial`/`fail` with `blocker: model`, self-declines on size, or retries blindly: record its row, then `route ... --after <its tier>` for the next one. An `env` blocker (device, host, network, staging drift) keeps the same tier: fix the environment and redispatch.

## Recording

After **each** worker finishes, append its row before acting on the result:

```bash
python3 ~/.claude/skills/worker-routing/perf.py add --model haiku --effort high --type coding --platform none --task "#88 capacity copy fix" --complexity 3 --outcome pass --blocker none --attempts 0 --interventions 0 --ktok 194 --note "one line: what happened and why"
```

- `ktok`: exact `subagent_tokens` from the task-notification `<usage>`, in thousands.
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
