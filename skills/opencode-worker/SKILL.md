---
name: opencode-worker
description: Run opencode (DeepSeek) as an external worker from the command line, and tell whether it is done, stuck, looping, idle or never started. Load before any `opencode run` call that does real work, or when the user asks to call DeepSeek or opencode as a worker or subagent.
---

# opencode worker

## Roles (owner, 2026-11-05)

| Role | Who | Does |
|---|---|---|
| Orchestrator | Claude (this session) | Splits the work, briefs the worker, watches it, checks its result. |
| Worker | DeepSeek via opencode | Writes the code and runs the checks it is given. |
| Reviewer | Claude | `/code-review` and `/commentdiet` before a PR opens; `/ponytail-review` on the PR. |
| Merger | Claude | Merges branches and PRs. |

Reviews and merges never go to DeepSeek: dispatch them as Claude subagents through the `worker-routing` skill. If opencode fails its ping or a setup check, report the error and fall back to the Claude worker tier `worker-routing` picks.

## The call

```bash
perl -e 'alarm shift; exec @ARGV' 1800 opencode run --standalone --format json \
  -m "opencode-go/deepseek-v4.1-flash#high" "<task>" \
  < /dev/null > "$SCRATCH/oc.jsonl" 2> "$SCRATCH/oc.err" &   # SCRATCH: the session scratch folder
echo $! > "$SCRATCH/oc.pid"; wait $!
```

- The `perl` line is a 30-minute hard limit that works on every Mac; `timeout` is not installed on the m1air.
- Model and effort are fixed: `opencode-go/deepseek-v4.1-flash#high`. The paid `opencode/deepseek-*` models fail with "Insufficient account funds". Always pass `-m`; never rely on defaults.
- An unknown `#variant` is rejected at once, so a typo cannot silently drop the effort.
- Errors exit 1. Exit 0 only means the process ended, not that the task is done.
- `--format json` prints one event per line (`step_start`, `text`, tool events, `step_finish`), each with `timestamp` and `sessionID`. Save the `sessionID`: `-s <id>` resumes or inspects that run.
- Leave out `--auto` (it approves every action, and Claude Code's safety check blocks a call that uses it). Runs still finish headless on both Macs; if one waits on a permission prompt, that is the "Alive but idle" row.
- `< /dev/null` is required: with `--standalone` and an open input, opencode waits on it and the run hangs until the alarm.
- `--standalone` gives the run its own server. Without it every run shares one `opencode serve --service` process with other sessions' workers, so its CPU tells you nothing and killing the client may not stop it.
- Run the call with `run_in_background`, and watch `oc.jsonl` with the Monitor tool: an until-loop that ends on the exit, on no `step_start` within 60s, on no new event for 10 minutes, or on the same tool call 3+ times. Waiting only for the exit notice lets an idle or looping run burn the full 30 minutes.
- Run in its own worktree or branch, one writer per set of files, so a bad run is thrown away instead of untangled.

## Before real work

Ping: `perl -e 'alarm shift; exec @ARGV' 120 opencode run --standalone -m "opencode-go/deepseek-v4.1-flash#high" "Reply with just: pong" < /dev/null`. Anything but `pong` is a setup failure: report it, do not send the task.

## States and what to do

| State | Sign | Action |
|---|---|---|
| Done | Final `step_finish`, exit 0, and the done condition holds when you check it | Review it with Claude, then clean up. |
| Did not start | Non-zero exit within seconds; error on stderr (bad model, not signed in, no funds, binary missing) | Setup failure. Never retry unchanged; report the error. |
| Started, no first event | No `step_start` within 60s | Provider queue or server start is stuck. Kill it; retry once. |
| Running and working | New events keep arriving; files change | Leave it. |
| Alive but idle | Process exists, no new event for 10 min, low CPU | Hidden prompt, network wait or throttling. Kill it. High effort thinks quietly, so judge by CPU and missing events, not silence alone. The work runs in the client's child server, so read that one: `ps -o %cpu= -p $(pgrep -P $(cat oc.pid))`. |
| Alive but looping | Same tool call or error 3+ times; a file edited back and forth | Kill it. Narrow the task before any retry. |
| Busy, no progress | Many reads or thinking, no edits, no `step_finish` | Hard wall-clock limit (the `perl` alarm). |
| Says done, isn't | Exit 0, task unmet or nothing changed | Never trust its report; check the diff and tests yourself. |
| Done but wrong | Changes are broken or outside scope | Run the repo's checks; reject edits outside the files given. |
| Partial | Killed or crashed midway | Discard the worktree. |
| Provider error midway | Error event or exit 1 after some events (rate limit, funds, context too long) | Retry once if temporary; report funds or access errors. |
| Output cut short | No final `step_finish` | Failure, even with exit 0. |
| Orphan | Wrapper died, opencode still editing | Kill the id in `oc.pid` only, never a broad `pkill`, since other sessions run opencode too. |
| Every call hangs | Ping times out too | Report it. Never restart the shared opencode service: it runs other sessions' workers. |

## Arena (owner, 2026-11-05, trial)

A build scored complexity 2.0 or more (score it as `worker-routing` does) runs as an **arena**: three workers build the same ticket independently, sharing only facts and blockers, and Claude keeps the best result. Below 2.0, and for every fix round, one worker builds. The owner is watching this trial before deciding whether it becomes its own skill.

### 1. Start

- Commit the ticket branch. Cut three worktrees from its tip, on branches `<ticket branch>-arena-a`, `-b` and `-c`, the way the repo's `AGENTS.md`/`CLAUDE.md` makes worktrees (its script, env file and install step), so the checks can run in each.
- Make `$SCRATCH/arena/` outside the worktrees, holding empty `a.md`, `b.md`, `c.md` and `claude.md`. Each worker's call writes to `$SCRATCH/arena/<letter>.oc.jsonl`, `.oc.err` and `.oc.pid` in place of the single-run paths, so every check and kill names its letter. opencode reads and writes this folder without a permission prompt (tested 2026-11-05).
- One brief for all three: the ticket, "commit your work to your branch before you finish", and this paragraph with the worker's letter and the folder filled in:

  > Shared notes: append one line to `<folder>/<letter>.md` each time you learn a fact about the environment or hit a blocker, for example "type check needs `npm run gen` first", "the API returns null for an empty cart", "the fixture lives in tests/fixtures/cart.json", "blocked: migration 042 fails on a clean database". Before each test run, read every other file in that folder; `claude.md` holds corrections from the orchestrator and overrides the rest. Write facts and blockers only: no code, no plan, no approach, no style. Write only to your own file.

### 2. Watch

Watch each run as above. Also read the notes files on each check:
- A wrong fact: append the correction to `claude.md` ("ignore a.md line 3: the fixture moved to …").
- A note that carries code, a plan, an approach or style: append "ignore a.md line 3" to `claude.md`.
- A blocker all three share: decide whether the ticket is blocked before more runs burn on it.

Wait until every run is Done or killed; each call's 30-minute alarm bounds the wait.

### 3. Judge

Run the checks in one worktree at a time.
1. **Fast checks** on each Done run's committed branch: the type check and the test files it touched. Drop a run that fails them, or that committed nothing.
2. **Cross-tests**, with two or more survivors: in each survivor's worktree, `git checkout <other branch> -- <test files the other branch changed>` (from `git diff --name-only <ticket branch>...<other branch>`, test files only), run them, then `git reset -q --hard && git clean -fdq` to drop the copies; the tree was clean, since the worker committed. A cross-failure is a bug in that code, an over-specified test, or a helper the test needs that only its own branch has: read the failing test to tell which.
3. **Read** the two survivors with the fewest real bugs found by cross-tests, the smaller diff breaking a tie. Take one. Graft a piece of the other only when it is small, and only with a test that shows why. With one survivor, take it.
4. **Log** (below), then **merge** the winner into the ticket branch and remove the three worktrees, their branches and `$SCRATCH/arena/`.

Done when the ticket branch holds the winner and its fast checks pass. The full checks run where the calling skill runs them. With no survivor, discard the worktrees and build once with a single worker, with the notes as facts in its brief.

### 4. Log

Append one line per build to `~/.claude/skills/worker-routing/arena-log.jsonl`, beside the performance log and outside the checkout. Single-worker builds at any complexity get a line too, as the baseline:

```json
{"date": "2026-11-05", "repo": "Juan23/jj", "ticket": 123, "complexity": 2.5, "workers": 3, "done": 3, "fast_pass": 2, "cross_bugs": {"a": 0, "b": 2}, "winner": "a", "grafted": false, "notes": 7, "corrections": 1, "wall_min": 34}
```

`notes` counts lines across the workers' files; `corrections` counts lines in `claude.md`; `wall_min` runs from the first call to the merge. A single-worker line has `"workers": 1` and leaves out the arena fields. The review rounds the PR needed are in its comments, so the log leaves them out.

## Rules

1. One bounded task with a checkable done condition ("tests in X pass", "file Y has Z").
2. Retry only temporary failures, and only once. Never retry setup or account errors.
3. Keep `oc.jsonl` and `oc.err` until the result is checked.
4. Check the result yourself: diff, the repo's checks, scope. Then clean up the process and the worktree.
