---
name: worker-routing
description: "Use before dispatching any worker (Agent tool or shell: builds, fixes, check runs, reviewers, merges, audits) and after one finishes: pick its tier from the performance log, then record the outcome. Also for questions about tier/model statistics."
---

Every worker dispatch is a **routing** decision backed by the performance log, and every finished worker adds one **row** to it. Route to the cheapest tier the evidence doesn't rule out.

Tool: `python3 ~/.claude/skills/worker-routing/perf.py` — `route` before a dispatch, `add` after it, `rework` when its output later needs another build or test cycle, `stats` only when the user asks for statistics. The log is shared by every project (`~/.claude/skills/worker-routing/agent-performance-log.jsonl`), append-only, and owned by the tool: one `route` call and one `add` call per worker, one `rework` call per defect found later, nothing else touches the file.

## Which work comes here (owner, 2026-11-19)

Every dispatch is routed here: builds, fixes and check runs, reviews (rule 5), merges, audits, diagnosis, device runs and design work. Gemini and DeepSeek go first wherever they can, to save Claude usage; they run from the shell, the rest are Claude subagents (owner, 2026-11-19).

## Tiers

Cheapest first (owner, 2026-11-19):
`hydrogen-medium` → `sonnet-high` → `opus-medium` → `opus-high` → `opus-xhigh`.
`hydrogen-medium` is the default worker below c4.5 and runs from the shell (next section); the rest are agent types in `~/.claude/agents/`. Merges skip the shell tiers.
PR reviews use their own agents, not a tier (rule 5).

Below the ladder, for the work the log shows Haiku doing reliably (audits at any complexity; cleanup, merge and simple coding below c2.5): `deepseek-high` first, then `haiku-medium` if DeepSeek fails (owner, 2026-11-19). Merges skip DeepSeek and start at `haiku-medium`. Everywhere else `route` returns neither.

Retired, never dispatched: `haiku-high`, `opus-low` (owner, 2026-11-02), `haiku-xhigh` (2026-10-22) and `sonnet-medium` (2026-11-19; `--after sonnet-medium` goes to `sonnet-high`). Old rows stay in `stats`.

## Dispatch

1. Classify the task's **type** (`audit`, `merge`, `cleanup`, `coding`, `bug-diagnosis`, `harness-build`, `device-run`, `harness-fix`, `review`) and score **complexity** 1.0–5.0, one decimal place (1 = mechanical, 3 = one ticket, 5 = multi-platform harness with unknown root cause). Hold both for the row. `audit` finds facts (research, read-only checks); `design` compares ways to build something and reports options with trade-offs, such as a gremlins design scout. Hosted-harness work splits three ways: `harness-build` writes or changes runner, fixture, or checkpoint code; `device-run` executes a packaged iOS/Android run and reports; `harness-fix` diagnoses a failed run, patches, and reruns. Set `--platform ios|android|both` on any task that touches a device (default `none`); it is recorded for stats and does not change routing. Old rows keep the retired type `hosted-harness`; it shows in stats but `route` and `add` reject it.
2. `perf.py route --type <type> --complexity <#.#>`. It starts from a complexity floor, drops to a cheaper tier the log has **proven** on similar tasks, and steps over tiers the log shows **weak**.
3. Spawn with `subagent_type` set to the routed tier, or run the shell command below for a non-Claude tier. Override it only with a reason the log can't see (for example, the task needs a device run the worker must design from scratch), and put that reason in the row's note. Give the worker an attempt cap for device runs.
4. **Owner default at c5** (complexity ≥ 4.5, any type): spawn `sonnet-high` whatever `route` returns, and start the row's note with `owner-default c5:`. The owner set this on 2026-10-13.
5. **Owner default for every PR review**: spawn `pr-reviewer` for a review before the PR is opened and `merge-reviewer` for a review of an open PR, whatever `route` returns, even at c5 (this rule overrides rule 4). Both run the current Opus model at high effort; record the row with `--model opus --effort high`, type `review`, and start its note with `owner-default review:`. The review gate accepts only these two agents, and one fixed reviewer makes the review rows a measure of that reviewer.

## Non-Claude tiers

Run each one in its own worktree, as a background command, one writer per set of files. Check its diff and run the checks yourself: its own report is not proof.

| Tier | Command |
|---|---|
| `deepseek-high` | The call in the `opencode-worker` skill (`opencode-go/deepseek-v4.1-flash#high`). |
| `hydrogen-medium` | `agy -p "<task>" --model gemini-4-hydrogen-medium --mode accept-edits --print-timeout 1770s --output-format json < /dev/null` |

- Medium is agy's own default for Hydrogen (the bare name resolves to `-medium`); the explicit name keeps the row's tier true if that default changes.
- Wrap the agy call in `perl -e 'alarm shift; exec @ARGV' 1800` for a hard 30-minute limit. Headless agy refuses any command with a `*` wildcard, and one refusal ends its run: say so in the task.
- Ktok: opencode's `step_finish` tokens or agy's `usage.total_tokens`, in thousands.
- Fail fast: ping before real work. `opencode-worker` has DeepSeek's; for agy, `agy -p "Reply with just: pong" --model gemini-4-hydrogen-medium --print-timeout 60s` must print `pong`.
- A tool that fails its ping, is out of quota or is not signed in: record the row with `blocker: env` and route `--after` that tier (Hydrogen goes to `sonnet-high`, DeepSeek to `haiku-medium`). This is the one `env` case that moves up a tier.

## Escalation

When a worker returns `partial`/`fail` with `blocker: model`, self-declines on size, or retries blindly: record its row, then `route ... --after <its tier>` for the next one. An `env` blocker (device, host, network, staging drift) keeps the same tier: fix the environment and redispatch. A shell tier that is down is the exception (Non-Claude tiers).

## Recording

After **each** worker finishes, append its row before acting on the result:

```bash
python3 ~/.claude/skills/worker-routing/perf.py add --model hydrogen --effort medium --type coding --platform none --task "#88 capacity copy fix" --complexity 3 --outcome pass --blocker none --attempts 0 --interventions 0 --ktok 194 --note "one line: what happened and why"
```

- `ktok`: exact `subagent_tokens` from the task-notification `<usage>`, in thousands.
- `blocker`: `model` when the worker's reasoning or harness code failed it; `env` when the device, host, network, or staging state did; `none` otherwise.
- `attempts`: device runs or retries used. `interventions`: orchestrator messages that redirected or unblocked it.
- `--escalated-from`/`--escalated-to`: tier names, set on both rows of a hand-off. `--wall-min` when known.

Done when `add` reports the appended row.

## Rework

**Rework** is a defect in a worker's accepted output, found later (review, screenshot check, device run), that forces another build or test cycle — a slight visual inconsistency counts. The owner's scarce resource is wall-clock time, and rework spends it, so `route` scores a reworked row 0.5 lower: a reworked pass ranks like a partial. A fix that needs no rebuild or retest (copy, comment) is not rework.

Every real finding from the attack round, a pr-reviewer or a merge-reviewer that needs a code fix is rework: this is how the log judges each builder tier, so a weak default worker drops out of `route` by itself. When you find rework, charge it to the worker whose row produced it, before dispatching the fix:

```bash
python3 ~/.claude/skills/worker-routing/perf.py rework --task "#88 capacity copy fix" --cycles 1 --wall-min 25 --note "one line: the defect and how it surfaced"
```

- `--task`: the exact `--task` of that worker's row; it charges the latest row with that task.
- `--cycles`: extra build/test cycles the defect caused. `--wall-min`: wall-clock minutes they cost, when known.

The fix itself is a new worker with its own `route` and `add`.
