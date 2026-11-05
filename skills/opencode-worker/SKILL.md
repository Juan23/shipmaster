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

## Rules

1. One bounded task with a checkable done condition ("tests in X pass", "file Y has Z").
2. Retry only temporary failures, and only once. Never retry setup or account errors.
3. Keep `oc.jsonl` and `oc.err` until the result is checked.
4. Check the result yourself: diff, the repo's checks, scope. Then clean up the process and the worktree.
