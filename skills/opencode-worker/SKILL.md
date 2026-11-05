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
perl -e 'alarm shift; exec @ARGV' 1800 opencode run --auto --format json \
  -m "opencode-go/deepseek-v4.1-flash#high" "<task>" \
  > "$SCRATCH/oc.jsonl" 2> "$SCRATCH/oc.err"   # SCRATCH: the session scratch folder
```

- The `perl` line is a 30-minute hard limit that works on every Mac; `timeout` is not installed on the m1air.
- Model and effort are fixed: `opencode-go/deepseek-v4.1-flash#high`. The paid `opencode/deepseek-*` models fail with "Insufficient account funds". Always pass `-m`; never rely on defaults.
- An unknown `#variant` is rejected at once, so a typo cannot silently drop the effort.
- Errors exit 1. Exit 0 only means the process ended, not that the task is done.
- `--format json` prints one event per line (`step_start`, `text`, tool events, `step_finish`), each with `timestamp` and `sessionID`. Save the `sessionID`: `-s <id>` resumes or inspects that run.
- Without `--auto`, a headless run can hang forever on a permission prompt.
- Run it with `run_in_background` and wait for the exit notice; do not poll in a loop.
- Run in its own worktree or branch, one writer per set of files, so a bad run is thrown away instead of untangled.

## Before real work

Ping: `opencode run -m "opencode-go/deepseek-v4.1-flash#high" "Reply with just: pong"`. Anything but `pong` is a setup failure: report it, do not send the task.

## States and what to do

| State | Sign | Action |
|---|---|---|
| Done | Final `step_finish`, exit 0, and the done condition holds when you check it | Review it with Claude, then clean up. |
| Did not start | Non-zero exit within seconds; error on stderr (bad model, not signed in, no funds, binary missing) | Setup failure. Never retry unchanged; report the error. |
| Started, no first event | No `step_start` within 60s | Background service or provider queue is stuck. Kill it; retry once with `--standalone`. |
| Running and working | New events keep arriving; files change | Leave it. |
| Alive but idle | Process exists, no new event for 10 min, low CPU | Hidden prompt, network wait or throttling. Kill it. High effort thinks quietly, so judge by CPU and missing events, not silence alone. |
| Alive but looping | Same tool call or error 3+ times; a file edited back and forth | Kill it. Narrow the task before any retry. |
| Busy, no progress | Many reads or thinking, no edits, no `step_finish` | Hard wall-clock limit (the `perl` alarm). |
| Says done, isn't | Exit 0, task unmet or nothing changed | Never trust its report; check the diff and tests yourself. |
| Done but wrong | Changes are broken or outside scope | Run the repo's checks; reject edits outside the files given. |
| Partial | Killed or crashed midway | Discard the worktree. |
| Provider error midway | Error event or exit 1 after some events (rate limit, funds, context too long) | Retry once if temporary; report funds or access errors. |
| Output cut short | No final `step_finish` | Failure, even with exit 0. |
| Orphan | Wrapper died, opencode still editing | Record the worker's process id at launch; at cleanup kill that id only, never a broad `pkill`, since other sessions may run opencode too. |
| Service broken | Every call hangs, ping included | `opencode service restart`, or use `--standalone`. |

## Rules

1. One bounded task with a checkable done condition ("tests in X pass", "file Y has Z").
2. Retry only temporary failures, and only once. Never retry setup or account errors.
3. Keep `oc.jsonl` and `oc.err` until the result is checked.
4. Check the result yourself: diff, the repo's checks, scope. Then clean up the process and the worktree.
