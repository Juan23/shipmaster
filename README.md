# shipmaster

Claude Code skills that take GitHub issues to merged without you watching each one.

- **ship** takes one issue to merged: it builds the change test-first, opens a PR, runs review rounds with a fresh reviewer until one is clean, and merges.
- **shipmaster** runs `ship` for a batch of issues, one at a time or several at once. As soon as a ship merges, it starts the next unblocked issue. It only coordinates; the ships do the work.
- **worker-routing** picks the model and effort for each worker subagent from a log of how each tier did on earlier tasks, and adds to that log when the worker finishes. `ship` uses it in workers mode and for its reviewers.

```
shipmaster
├── ship #12   (optional workers)
└── ship #13   (optional workers)
```

## Use

In Claude Code, from a checkout of the repo the issues belong to:

```
/shipmaster 12 13 14                   one by one
/shipmaster 12 13 14 15 3 concurrent   three ships at a time
/shipmaster 12 13 use worker-routing   ships build and fix through workers
/ship 12                               a single issue
```

## How it works

- Each ship is a headless `claude -p` session in its own git worktree, started in the background by `run-ship.sh`. When a ship's turn ends, the command exits and wakes the shipmaster.
- Blockers come from GitHub's issue dependencies, or from a `Blocked by: #n` line in the issue body. An issue that already has an open PR continues that PR on its branch.
- With more than one ship, a **baton** lets one ship at a time merge or use a phone, emulator or Simulator, so ships never share a device or load the machine with two merge checks.
- When a ship needs an answer from you, the question appears in the shipmaster session, and your reply goes back to that ship.
- All state is on disk in the session scratchpad (`ships/`), and the shipmaster rebuilds it from there and from GitHub on every wake.
- A ship with no output for two hours is stopped, along with the processes it started.

## worker-routing

Before dispatching a worker, `perf.py route` picks its tier. It starts from a tier set by the task's complexity, drops to a cheaper tier the log has proven on similar tasks, and skips tiers the log shows doing badly. With an empty log it returns the starting tier. After the worker finishes, `perf.py add` records the outcome. If accepted work later needs another build or test cycle, `perf.py rework` marks it, and that tier ranks lower next time.

```bash
python3 ~/.claude/skills/worker-routing/perf.py route --type coding --complexity 3
python3 ~/.claude/skills/worker-routing/perf.py stats
```

The tiers, cheapest first, are `haiku-medium`, `haiku-high`, `sonnet-high`, `opus-low` and `opus-medium`. `opus-high` (Opus 5.5, high effort) does every PR review and is never routed to. They are subagent definitions in `agents/`. `skills/worker-routing/SKILL.md` has the full routing rules.

The log has one JSON line per worker and per rework, and is shared by every project on the machine: `~/.claude/skills/worker-routing/agent-performance-log.jsonl`. It never goes in this repo, and `.gitignore` blocks it if it ends up here.

## Install

```bash
git clone https://github.com/Juan23/shipmaster ~/Projects/shipmaster
mkdir -p ~/.claude/skills/worker-routing ~/.claude/agents
ln -sfn ~/Projects/shipmaster/skills/ship ~/.claude/skills/ship
ln -sfn ~/Projects/shipmaster/skills/shipmaster ~/.claude/skills/shipmaster
ln -sf ~/Projects/shipmaster/skills/worker-routing/{SKILL.md,perf.py} ~/.claude/skills/worker-routing/
ln -sf ~/Projects/shipmaster/agents/*.md ~/.claude/agents/
touch ~/.claude/skills/worker-routing/agent-performance-log.jsonl
```

The links keep the installed skills on the checkout, so `git pull` updates them. The worker-routing install links its two files instead of the folder, so the log stays in `~/.claude/skills/worker-routing/` and out of the checkout. `touch` creates an empty log on a new machine and leaves an existing one alone. Running the block again after the clone is safe: it replaces copied skill files, copied agents and old links with links to this checkout. It can't fix two leftovers, so delete them first: a `ship` or `shipmaster` folder that is a copy rather than a link, and a `worker-routing` folder that is itself a link.

You also need:

- Claude Code 2.1.304 or later (for `-p`, `--session-id`, `--resume` and `stream-json` output);
- `gh`, signed in, `git` and Python 3;
- the `tdd` and `code-review` skills, which `ship` calls.

Run the shipmaster from a session in auto permission mode; its ships run in auto mode too.

## Test

```bash
skills/shipmaster/run-ship.test.sh
```

It runs `run-ship.sh` against a fake `claude`. It checks that arguments and exit codes pass through, and that the hang timer and a stop signal both end the ship and the processes it started.
