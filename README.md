# shipmaster

Claude Code skills that take GitHub issues to merged without you watching each one.

- **ship** takes one issue to merged: it builds the change test-first, opens a PR, runs review rounds with a fresh reviewer until one is clean, and merges.
- **shipmaster** runs `ship` for a batch of issues, one at a time or several at once. As soon as a ship merges, it starts the next unblocked issue. It only coordinates; the ships do the work.

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

## Install

```bash
git clone https://github.com/Juan23/shipmaster ~/Projects/shipmaster
ln -s ~/Projects/shipmaster/skills/ship ~/.claude/skills/ship
ln -s ~/Projects/shipmaster/skills/shipmaster ~/.claude/skills/shipmaster
```

The links keep the installed skills on the checkout, so `git pull` updates them.

You also need:

- Claude Code 2.1.304 or later (for `-p`, `--session-id`, `--resume` and `stream-json` output);
- `gh`, signed in, and `git`;
- the `tdd`, `code-review` and `worker-routing` skills, which `ship` calls.

Run the shipmaster from a session in auto permission mode; its ships run in auto mode too.

## Test

```bash
skills/shipmaster/run-ship.test.sh
```

It runs `run-ship.sh` against a fake `claude`. It checks that arguments and exit codes pass through, and that the hang timer and a stop signal both end the ship and the processes it started.
