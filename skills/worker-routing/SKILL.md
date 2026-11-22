---
name: worker-routing
description: "Use before dispatching any worker (Agent tool or shell: builds, fixes, check runs, reviewers, merges, audits) and after one finishes: pick its tier from the performance log, then record the outcome. Also for questions about tier/model statistics."
---

Every worker dispatch is a **routing** decision backed by the performance log, and every finished worker adds one **row** to it. Route to the cheapest tier the evidence doesn't rule out.

Tool: `python3 ~/.claude/skills/worker-routing/perf.py` — `route` before a dispatch, `add` after it, `rework` when its output later needs another build or test cycle, `stats` only when the user asks for statistics. The log is shared by every project (`~/.claude/skills/worker-routing/agent-performance-log.jsonl`), append-only, and owned by the tool: one `route` call and one `add` call per worker, one `rework` call per defect found later, nothing else touches the file.

## Which work comes here (owner, 2026-11-19)

Every dispatch is routed here: builds, fixes and check runs, reviews (rule 5), merges, audits, diagnosis, device runs and design work. agy (Gemini) goes first on work that local tests can prove, to save Claude usage; it runs from the shell, the rest are Claude subagents (owner, 2026-11-21).

## Tiers

Owner, 2026-11-21, from a three-model roundtable. `route` builds the ladder for each task and prints it:

| Work | Ladder, cheapest first |
|---|---|
| Coding that ends in a staging or device run (`--cycle`); all harness work; coding at c4.5 and above | `opus-medium` → `opus-high` → `opus-xhigh` |
| Other coding and cleanup; audits | the two agy tiers → `haiku-medium` (audits; coding and cleanup below c2.5) → `opus-medium` → `opus-high` → `opus-xhigh` |
| Bug diagnosis, design, device runs | `hydrogen-high` → `sonnet-high` → `opus-medium` → `opus-high` → `opus-xhigh`; c4.5 and above starts on `sonnet-high` |
| Merges | `haiku-medium` (below c2.5) → `sonnet-high` → `opus-medium` → `opus-high` → `opus-xhigh` |

- A mistake in cycle work costs a slow test cycle and one more review round, so that work starts on Opus. Work that local tests can prove starts on agy.
- The agy tiers are `hydrogen-high` and `neon-medium`, on trial against each other: `route` gives each task to the one with fewer rows of that type at that complexity. A run that the environment stopped does not count as a turn. Neon's rows from before the trial count, so Hydrogen takes the first tasks until it has as many as Neon; old `hydrogen-medium` rows do not count. The trial is 20 tasks each; `stats` shows the count, and the owner reads it and decides. `route` never sends work to a tier the log shows weak for it: a weak agy tier gets no more tasks near that complexity, in the trial or as the second try.
- A proposal for the owner's decision, not a rule, and `route` does not apply it: the roundtable of 2026-11-21 proposed that an agy tier passes the trial when at most 4 of its 20 tasks needed rework or stopped on agy's five-hour "Gemini Models" quota, and its pull requests needed no more review rounds than a Claude builder's. A tier that fails would do attacks and audits only. Check again at 40 tasks. A quota stop is an `env` row, which `stats` leaves out: count those from the log, beside the 20.
- `sonnet-high` and DeepSeek do not build. DeepSeek is an attacker only (`attack-round`).
- The agy tiers run from the shell (next section); the rest are agent types in `~/.claude/agents/`.
- PR reviews use their own agents, not a tier (rule 5).

Retired, never dispatched: `haiku-high`, `opus-low` (owner, 2026-11-02), `haiku-xhigh` (2026-10-22), `sonnet-medium` (2026-11-19), `hydrogen-medium` and `deepseek-high` (both 2026-11-21). `route --after` accepts a retired tier and steps above it. Old rows stay in `stats`.

## Dispatch

1. Classify the task's **type** (`audit`, `merge`, `cleanup`, `coding`, `bug-diagnosis`, `harness-build`, `device-run`, `harness-fix`, `review`) and score **complexity** 1.0–5.0, one decimal place (1 = mechanical, 3 = one ticket, 5 = multi-platform harness with unknown root cause). Hold both for the row. `audit` finds facts (research, read-only checks); `design` compares ways to build something and reports options with trade-offs, such as a gremlins design scout. Hosted-harness work splits three ways: `harness-build` writes or changes runner, fixture, or checkpoint code; `device-run` executes a packaged iOS/Android run and reports; `harness-fix` diagnoses a failed run, patches, and reruns. Set `--platform ios|android|both` on any task that touches a device (default `none`); it is recorded for stats and does not change routing. Old rows keep the retired type `hosted-harness`; it shows in stats but `route` and `add` reject it.
2. `perf.py route --type <type> --complexity <#.#>`. Add `--cycle` when a coding task ends in a staging or device run. It starts from a complexity floor, drops to a cheaper tier the log has **proven** on similar tasks, and steps over tiers the log shows **weak**.
3. Spawn with `subagent_type` set to the routed tier, or run the shell command below for a non-Claude tier. Override it only with a reason the log can't see (for example, the task needs a device run the worker must design from scratch), and put that reason in the row's note. Give the worker an attempt cap for device runs.
4. **Owner default at c5** (complexity ≥ 4.5; bug diagnosis, design, device runs and merges): spawn `sonnet-high` whatever `route` returns, and start the row's note with `owner-default c5:`. The owner set this on 2026-10-13. It does not cover coding and harness work, which `route` starts on `opus-medium`, or cleanup and audits, which start on agy.
5. **Owner default for every PR review**: spawn `merge-reviewer` on the open PR, whatever `route` returns, even at c5 (this rule overrides rule 4). It runs the current Opus model at high effort; record the row with `--model opus --effort high`, type `review`, and start its note with `owner-default review:`. The review gate accepts only this agent, and one fixed reviewer makes the review rows a measure of that reviewer.

## Non-Claude tiers

Run each one in its own worktree, as a background command, one writer per set of files. Check its diff and run the checks yourself: its own report is not proof.

| Tier | Command |
|---|---|
| `hydrogen-high` | `agy -p "<task>" --model gemini-4-hydrogen-high --mode accept-edits --print-timeout 1770s --output-format json < /dev/null` |
| `neon-medium` | The same call with `--model gemini-4-neon-medium`. |

- Always pass the full model name with its effort, so the row's tier stays true if agy's default changes.
- Wrap the agy call in `perl -e 'alarm shift; exec @ARGV' 1800` for a hard 30-minute limit. Headless agy runs only commands on `permissions.allow` in `~/.gemini/antigravity-cli/settings.json` and one refusal ends its run with no output. A repo script called by its path is refused: tell it to run `bash <script>` or `node <script>`.
- agy's own safety check refuses two more command shapes even when the command is on the allow list (tested 2026-11-21). Put both lines in every agy brief: "Never use `find -exec`: list the files first, then run the next command on them, or use `rg`." and "Never write the words pkill, killall or kill in a command, not even as search text: read the files with your file tool to find them." Pipes, `&&` and loops run.
- A run whose JSON has `denied_actions` ended on a refusal. Read the refused command with `grep -o 'user denied permission to run command:\\n.*' ~/.gemini/antigravity-cli/brain/<conversation_id>/.system_generated/logs/transcript_full.jsonl | sed 's/\\nDo not attempt.*//'`, record the row with `blocker: env`, and rerun the same tier once with that command shape banned in the brief. If that rerun is refused too, route `--after <that tier>`.
- Ktok: agy's `usage.total_tokens`, in thousands.
- Fail fast: ping the routed model before real work: `agy -p "Run the shell command echo pong and reply with just its output" --model <the routed model> --mode accept-edits --print-timeout 60s < /dev/null` must print `pong`.
- Both agy tiers draw on one quota, "Gemini Models" in `agy -p /quota`: when it is out, both are out.
- A model that fails its ping: record the row with `blocker: env` and route `--after <that tier>`. agy out of quota or not signed in stops both models: route `--after hydrogen-high neon-medium`. These are the `env` cases that move up a tier.

## Escalation

When a worker returns `partial`/`fail` with `blocker: model`, self-declines on size, retries blindly, stalls (no progress, or it hits its time limit), or needs a second correction from you: record its row, then `route ... --after <every tier that stalled on this task>` for the next one. An `env` blocker (device, host, network, staging drift) keeps the same tier: fix the environment and redispatch. A shell tier that is down is the exception (Non-Claude tiers).

- Name every stalled tier each time: `route` cannot see the earlier attempts. After Hydrogen fails, `--after hydrogen-high` gives Neon its one try, unless the log shows Neon weak for such work. After Neon fails too, `--after hydrogen-high neon-medium` goes on to Haiku or Opus.
- Cycle work moves from `opus-medium` to `opus-high` after one failed cycle.

## Recording

After **each** worker finishes, append its row before acting on the result:

```bash
python3 ~/.claude/skills/worker-routing/perf.py add --model hydrogen --effort high --type coding --platform none --task "#88 capacity copy fix" --complexity 3 --outcome pass --blocker none --attempts 0 --interventions 0 --ktok 194 --note "one line: what happened and why"
```

- `ktok`: exact `subagent_tokens` from the task-notification `<usage>`, in thousands.
- `blocker`: `model` when the worker's reasoning or harness code failed it; `env` when the device, host, network, or staging state did; `none` otherwise.
- `attempts`: device runs or retries used. `interventions`: orchestrator messages that redirected or unblocked it.
- `--escalated-from`/`--escalated-to`: tier names, set on both rows of a hand-off. `--wall-min` when known.

Done when `add` reports the appended row.

## Rework

**Rework** is a defect in a worker's accepted output, found later (review, screenshot check, device run), that forces another build or test cycle — a slight visual inconsistency counts. The owner's scarce resource is wall-clock time, and rework spends it, so `route` scores a reworked row 0.5 lower: a reworked pass ranks like a partial. A fix that needs no rebuild or retest (copy, comment) is not rework.

Every real finding from the attack round or a merge-reviewer that needs a code fix is rework: this is how the log judges each builder tier, so a weak default worker drops out of `route` by itself. When you find rework, charge it to the worker whose row produced it, before dispatching the fix:

```bash
python3 ~/.claude/skills/worker-routing/perf.py rework --task "#88 capacity copy fix" --cycles 1 --wall-min 25 --note "one line: the defect and how it surfaced"
```

- `--task`: the exact `--task` of that worker's row; it charges the latest row with that task.
- `--cycles`: extra build/test cycles the defect caused. `--wall-min`: wall-clock minutes they cost, when known.

The fix itself is a new worker with its own `route` and `add`.
