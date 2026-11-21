---
name: attack-round
description: Alongside each pr-reviewer round for a code change, run cheap read-only attackers (DeepSeek focuses + agy Gemini; agy alone on most later changes) on the committed branch, triage their findings, and fix the real ones.
---

# Attack round

Owner's choice, 2026-11-19: cheap reviewers run **at the same time as** the pr-reviewer round, so the wait is the slower of the two, not their sum. Attackers never build, never run apps or emulators, and never replace a Claude review.

## When

- First change on a pull request: after the builder's own checks pass and the work is committed, start it in the background and spawn pr-reviewer round 1 at once.
- Later changes on the same pull request: agy only (`--focus ""`), alongside that round's pr-reviewer. Add a DeepSeek focus only when the new commits touch sign-in, permissions, money, retries or concurrency.
- Skip it for wording, layout or colour changes, and for docs-only changes.
- Pick only the focuses the change touches: `security` (sign-in, permissions, fail-open checks), `failure` (errors, offline, restarts), `timing` (races, stale state, expiry). agy always runs.

## Run

From the branch's checkout, as a background command (it ends within about 24 minutes: up to 4 for the pings, 20 for the reviewers):

```bash
~/.claude/skills/attack-round/attack-round.sh --base origin/main --focus security,failure,timing --builder <tier> --out "$SCRATCH/attack-round"
```

- `--builder` is the worker-routing tier that wrote the code. A reviewer differs from the builder's model where it can: for a `hydrogen-*` or `neon-*` builder, agy starts on Argon medium and falls back to Hydrogen. When only the builder's own model answers, it still reviews, and its status line ends `- same model as the builder`.
- It pings DeepSeek and agy first and skips any that do not answer. agy starts on the first of its two models that answers, so a primary that is down or out of quota costs only its ping.
- Each reviewer gets 20 minutes (`ATTACK_LIMIT`, seconds; Argon high needed 15 to 20 minutes in testing, Hydrogen high 4). A stalled reviewer is killed with all its child processes, and the round goes on with what arrived.
- agy uses Hydrogen high (owner, 2026-11-17: it took 4 minutes on a review where Argon medium took 11.5 and Argon high timed out). If Hydrogen fails fast (quota, error), it retries once on Argon medium. If headless agy refuses a command (it refuses any `*` wildcard, and one refusal ends its run), it retries once on the same model and is told which command was refused. A timeout does not retry, and a retry only gets the time left.
- Reviewers work in a throwaway worktree, which is deleted at the end. DeepSeek runs as the `attacker` agent (`opencode-attacker.md`, copied into that worktree): it can only read and search files inside the worktree, with no shell, no edits and no web, so the script saves the diff to `.attack/diff.patch` for it. agy runs in `--mode plan` under its own command allow list.
- Output: `findings.md` in the `--out` folder, with one status line per reviewer: `done`, `timeout`, `failed` or `skipped`.
- Fail fast, never stop: a reviewer that is `skipped`, `failed` or `timeout` does not hold up the work. Tell the owner one line per such reviewer in the report (the status line and its `*.err` file in the `--out` folder), so they can fix the tool, and carry on with what arrived.
- Tell the owner about `same model as the builder` only when no reviewer of another model answered.

## Triage

One worker (type `audit`, tier from `worker-routing`) checks each finding against the code:
- Keep it only if its scenario holds. Drop findings without a scenario.
- For each kept finding, the builder writes the failing test it names (`/tdd`), then the fix. Charge it to the builder with `perf.py rework` (worker-routing).
- The attack fixes and the same round's pr-reviewer fixes land as one commit. Never show the pr-reviewer the attack findings: it must not have seen the work.

## Why it stays

Owner, 2026-11-17: "we'll keep the attackers." In a 10-pull-request trial, 72% to 100% of each reviewer's findings were real.

## Test

`~/.claude/skills/attack-round/test-attack-round.sh` runs the script against fake opencode and agy binaries: success, a hang, a quota error, a timeout and a hung ping on the primary model, agy's own time limit, refused commands, a failed ping, a base with a slash, a reused output folder, a stopped round, the read-only agent, an uncommitted tree, a reviewer other than the builder's model with a same-model fallback, and an agy-only round.

## Revert

Everything this added, and how to undo each part (about two minutes):

1. Delete the skill and its link:
   ```bash
   rm -rf ~/Projects/shipmaster/skills/attack-round ~/.claude/skills/attack-round
   ```
2. Remove every other mention of the attackers: `git grep -n -i attack -- README.md skills/opencode-worker skills/worker-routing` lists them.
3. Tell Claude "attackers off" so it updates the `claude-workers-only` memory.

Not part of this skill, and kept on revert: the agy fixes of 2026-11-16 (the Linear MCP server removed, `read_file` allowed in the `review-for-me` hook, `rg`/`nl`/`sed`/`awk` allowed in agy settings). Backups of those files from before the fixes are in `~/.gemini/backups-2026-11-16/`.
