---
name: shipmaster
description: "Ship a batch of GitHub issues for you: one ship per issue, one at a time or N at once, each unblocked issue starting as soon as a slot frees."
disable-model-invocation: true
---

You do what the user otherwise does by hand: ship an issue, wait for it to merge, check what is unblocked, ship the next. A **ship** is a headless Claude session that runs the `ship` skill on one issue in its own worktree: it builds, reviews and merges. You coordinate. You read GitHub, start and resume ships, pass their questions to the user, and pace their merges. The code, reviews, PRs and issue updates all belong to the ships.

The arguments hold the issues (numbers, `owner/repo#n` or URLs, all in this checkout's repo) and, sometimes:

- **a count** ("3 concurrent", "4 at once"): keep that many ships live. Without one, the count is 1 and issues ship one by one.
- **workers** ("use worker-routing", "with workers"): each ship gets `with workers`, so it builds and fixes through workers routed by the `worker-routing` skill.

A ship is **live** from its start until it merges or stops; one waiting on the user is live. Ships run in auto permission mode, so run this only from a session in auto mode; otherwise stop and say so.

## 1. Plan

For each issue read `gh issue view <n> --json number,title,state,body` and its blockers, `gh api repos/<owner>/<repo>/issues/<n>/dependencies/blocked_by --jq '.[] | {number, state}'`, plus any `Blocked by: #a, #b` line in the body. Note the issue's **open PR**, if one exists: an open PR whose body names `#<n>` (`gh pr list --state open --json number,headRefName,body`). A closed issue is reported and dropped. An issue is **unblocked** when every blocker is closed. An issue is **stuck** when a blocker is open and outside the batch, stuck itself, or has a ship that merged or stopped without closing it; report it with that blocker. Recheck this on every wake.

Order the batch blockers first, otherwise in the user's order. State the plan in a few lines (the order, what starts now, what waits on what, what is stuck, and any open PRs outside the batch), write the order and the count to `ships/batch` in the session scratchpad, and go straight on to step 2. When the user adds issues later, plan them the same way and append them to the order.

Done when every issue is ordered or reported.

## 2. Launch

Each ship keeps its state in `ships/<n>/` in the session scratchpad: a `ship` file with the lines `session=<uuid>`, `branch=<branch>` and `worktree=<absolute path>`, then one `<k>.msg` and `<k>.log` per turn, `k` counting from 1. An issue whose `ship` file exists has its ship; it never gets a second one.

While live ships are fewer than the count, take the next unblocked issue in plan order without a ship:

1. **Worktree.** Create one on a new branch `ticket/<n>-<slug>` (slug: a few words of the title, kebab-case) from the latest `origin/<default>`, with the repo's own worktree command where its instructions name one (jj: `scripts/worktree-new.sh ship-<n> <branch>`, which also installs and links the backend), otherwise `git fetch && git worktree add -b <branch> .claude/worktrees/ship-<n> origin/<default>`. An issue with an open PR uses that PR's head branch instead, based on `origin/<head branch>` (`git worktree add -b <branch> <path> origin/<branch>`, or the repo command with that base). Take its absolute path from `git worktree list`, and write the `ship` file with a new `uuidgen | tr A-Z a-z` as the session.
2. **Brief.** Write `1.msg` with the Write tool, brackets filled:

   > Ship issue #[n] in [owner/repo]. Read `~/.claude/skills/ship/SKILL.md` and follow it, with the arguments `[n][ with workers]`, except where this prompt says otherwise. Your worktree is already on the ticket branch `[branch]`; use it.[ Open PR only: Open PR #[pr] on that branch already holds work for this issue: take it as yours, finish what the issue still needs, and carry on from step 3 with that PR instead of opening another.] You run headless and nobody can answer mid-turn: wherever ship says to ask the user, end your turn with `waiting on the user: <question>`, and the answer comes as your next message.[ Count above 1: Other ships run beside you on this machine, and only the holder of the baton may merge or run anything on a phone, emulator or Simulator. You hold it only while a message that hands it to you is your latest, and it passes back when your turn ends. Before such a device run without it, end your turn with `needs the baton: <the run>`. When the PR is green at step 5, end your turn with `ready to merge <PR url>` instead of merging.]

3. **Start**, as a background Bash command (`run_in_background: true`):

   ```bash
   cd <worktree> && { [ ! -f .env.worktree ] || . ./.env.worktree; } && ~/.claude/skills/shipmaster/run-ship.sh <dir>/1.log --permission-mode auto -n ship-<n> --session-id <uuid> "$(cat <dir>/1.msg)"
   ```

To **resume** a ship, write the message to the next `<k>.msg` and run the same command with `<k>.log` and `--resume <uuid> "$(cat <dir>/<k>.msg)"` in place of the `-n` and `--session-id` arguments. The file keeps quotes and backticks in a message intact. Each command exits when the ship's turn ends, and its exit wakes you.

## 3. Each wake

On every wake and every user message, rebuild the state from GitHub and `ships/`; they hold everything, so nothing depends on your memory of earlier turns. A ship's reply is the `result` field of the `"type":"result"` line in its latest `<k>.log` (`grep '"type":"result"' <log> | tail -1`). Give each ship the first state that matches:

1. **working**: `pgrep -f <its latest log>` finds its command.
2. **merged**: `gh pr list --head <branch> --state merged` finds its PR. Remove its worktree with `git worktree remove <path>` to free the disk: its commits are on the default branch, and ship copies its evidence out before merging. Only a dirty worktree stays, since uncommitted edits are on no branch; report it.
3. **waiting**: its reply ends with `waiting on the user: <question>`. Pass the question to the user word for word, with the issue, once per log. Resume the ship with their answer as they wrote it.
4. **ready**: its reply says `ready to merge`.
5. **needs the baton**: its reply ends with `needs the baton: <the run>`.
6. **stopped**: anything else: no reply in the latest log, an error, five review rounds without a clean one, or a log ending `run-ship: no output`. Report its last reply.

Then act, in this order:

1. **Pass the baton.** The **baton** is the one right to merge or use a device; it keeps two ships off one emulator and keeps merge checks and device runs from loading the machine at once. When no working ship's latest message handed it over, give it to the earliest ready ship in plan order ("You hold the baton: merge now, carrying on from step 5."), or else to the earliest ship that needs it ("You hold the baton: do that run, then carry on."), by resuming that ship.
2. **Launch.** Run step 2 for every slot that is free.
3. **Tell.** One line per change since the last wake: merged, waiting with its question, stopped with its reason.

When no ship is live and none can launch, go to step 4. Otherwise end your turn.

## 4. Report

One line per issue: merged (its PR, and its worktree if it stayed dirty), stuck (its blocker), stopped (its reason), or waiting (its question). The user can open any idle ship with `claude --resume <uuid>` from its worktree.
