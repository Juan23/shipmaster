---
name: attack-round
description: Before spawning the pr-reviewer for a code change, run cheap read-only attackers (3 DeepSeek focuses + agy Gemini Hydrogen) on the committed branch, triage their findings, and fix the real ones. Trial over 10 pull requests from 2026-11-17.
---

# Attack round

Owner's choice, 2026-11-17: cheap reviewers run **before** the Claude reviews, because the review gate passes one commit and any fix after a clean Claude review costs another Claude round. Attackers never build, never run apps or emulators, and never replace a Claude review.

## When

- After the builder's own checks pass and the work is committed, before the `pr-reviewer`.
- Skip it for wording, layout or colour changes, and for docs-only changes.
- Pick only the focuses the change touches: `security` (sign-in, permissions, fail-open checks), `failure` (errors, offline, restarts), `timing` (races, stale state, expiry). agy always runs.

## Run

From the branch's checkout, as a background command (it ends within about 22 minutes: 2 for the pings, 20 for the reviewers):

```bash
~/.claude/skills/attack-round/attack-round.sh --base origin/main --focus security,failure,timing --out "$SCRATCH/attack-round"
```

- It pings DeepSeek and agy first and skips any that do not answer.
- Each reviewer gets 20 minutes (`ATTACK_LIMIT`, seconds; Argon high needed 15 to 20 in testing, Hydrogen high 4). A stalled reviewer is killed with all its child processes, and the round goes on with what arrived.
- agy uses Hydrogen high (owner, 2026-11-17: it took 4 minutes on a review where Argon medium took 11.5 and Argon high timed out). If Hydrogen fails fast (quota, error), it retries once on Argon medium. If headless agy refuses a command (it refuses any `*` wildcard, and one refusal ends its run), it retries once on Hydrogen and is told which command was refused. A timeout does not retry, and a retry only gets the time left.
- Reviewers work in a throwaway worktree, which is deleted at the end. DeepSeek runs as the `attacker` agent (`opencode-attacker.md`, copied into that worktree): it can only read and search files inside the worktree, with no shell, no edits and no web, so the script saves the diff to `.attack/diff.patch` for it. agy runs in `--mode plan` under its own command allow list.
- Output: `findings.md` in the `--out` folder, with one status line per reviewer: `done`, `timeout`, `failed` or `skipped`. If every reviewer failed or was skipped, go straight to the `pr-reviewer`.

## Triage

One Claude worker (type `audit`, tier from `worker-routing`) checks each finding against the code:
- Keep it only if its scenario holds. Drop findings without a scenario.
- For each kept finding, the builder writes the failing test it names (`/tdd`), then the fix.
- All fixes land as one commit. Then spawn the `pr-reviewer` as usual. Never show it the attack findings: it must not have seen the work.

## Trial log

Append one line per pull request to `~/.claude/attack-round-log.jsonl`:

```json
{"date": "2026-11-17", "repo": "Juan23/skc-workspace", "pr": 410, "reviewer": "deepseek-security", "status": "done", "findings": 3, "real": 2, "minutes": 9, "claude_review_rounds": 1}
```

One line per reviewer (`deepseek-security`, `deepseek-failure`, `deepseek-timing`, `agy-hydrogen`, `agy-argon`). After 10 pull requests: keep a reviewer if at least half its findings were real and Claude review rounds dropped by about one; drop it if under 30% were real, or it timed out or failed on 3 or more pull requests. The baseline is the `review` rows since 2026-11-06 in the worker-routing log.

## Test

`~/.claude/skills/attack-round/test-attack-round.sh` runs the script against fake opencode and agy binaries: success, a hang, a quota error and a timeout on the primary model, agy's own time limit, refused commands, a failed ping, a base with a slash, a reused output folder, a stopped round, the read-only agent, and an uncommitted tree.

## Revert

Everything this added, and how to undo each part (about two minutes):

1. Delete the skill and its link:
   ```bash
   rm -rf ~/Projects/shipmaster/skills/attack-round ~/.claude/skills/attack-round
   ```
2. In the `~/Projects/shipmaster` checkout, two files carried uncommitted local edits on 2026-11-17 that are not in this repo's history. If they are still there, put back their earlier local text:
   - `skills/worker-routing/SKILL.md`, "Which work comes here": replace the sentence that names `attack-round` with:
     > DeepSeek, opencode and the arena are disabled until the owner says otherwise (owner, 2026-11-15): never call the `opencode-worker` skill.
   - `skills/opencode-worker/SKILL.md`: restore the description and banner:
     > description: DISABLED by the owner on 2026-11-15 until further notice. Do not load or use; workers are Claude subagents (worker-routing). Formerly ran opencode (DeepSeek) workers and the 3-worker arena.

     > **DISABLED (owner, 2026-11-15, until further notice).** Do not run opencode or DeepSeek, and do not run an arena. Every worker is a Claude subagent picked by the `worker-routing` skill. The text below is kept only for when the owner turns this back on.
3. In `README.md`, remove the `attack-round` bullet and its `ln -sfn` install line, and drop ", and as the read-only attackers of `attack-round`" from the opencode-worker bullet.
4. Tell Claude "DeepSeek off" so it updates the `claude-workers-only` memory.

Not part of this skill, and kept on revert: the agy fixes of 2026-11-16 (the Linear MCP server removed, `read_file` allowed in the `review-for-me` hook, `rg`/`nl`/`sed`/`awk` allowed in agy settings). Backups of those files from before the fixes are in `~/.gemini/backups-2026-11-16/`.
