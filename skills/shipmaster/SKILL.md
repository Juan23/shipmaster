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

**Ship default.** Every ship turn runs on the model and effort in `~/.claude/shipmaster-defaults` on this machine (`model=<id>` and `effort=<level>` lines, which `run-ship.sh` reads), and on Opus 5.5 at medium where the file names none; your own model does not carry over. When the arguments set the default instead of naming issues ("set default to sonnet 5.5 high"), write that file with the model's full id (Opus 5.5 is `claude-opus-5-5`) and an effort of low, medium, high, xhigh or max, keeping the current effort when the user names none. Read it back, report the model and effort and that the setting is for this machine only, and stop. Running ships pick it up on their next turn.

## 1. Plan

For each issue read `gh issue view <n> --json number,title,state,body` and its blockers, `gh api repos/<owner>/<repo>/issues/<n>/dependencies/blocked_by --jq '.[] | {number, state}'`, plus any `Blocked by: #a, #b` line in the body. Note the issue's **open PR**, if one exists: an open PR whose body names `#<n>` (`gh pr list --state open --json number,headRefName,body`). Without one, note its **earlier branch**, if one exists: after `git fetch origin`, a remote `ticket/<n>-*` branch (`git ls-remote --heads origin 'refs/heads/ticket/<n>-*'`), other than the one in its `ships/<n>/ship` file, with commits not on `origin/<default>` (`git rev-list --count origin/<default>..origin/<branch>`) and no PR in any state (`gh pr list --head <branch> --state all`); with several, take the one with the newest commit and name the rest in the plan. A closed issue is reported and dropped. An issue is **unblocked** when every blocker is closed. An issue is **stuck** when a blocker is open and outside the batch, stuck itself, or has a ship that merged or stopped without closing it; report it with that blocker. Recheck this on every wake.

Order the batch blockers first, otherwise in the user's order. State the plan in a few lines (the order, what starts now, what waits on what, what is stuck, each open PR or earlier branch a ship will take over, and any open PRs outside the batch), write the order and the count to `ships/batch` in the session scratchpad, and go straight on to step 2. When the user adds issues later, plan them the same way and append them to the order.

Done when every issue is ordered or reported.

## 2. Launch

Each ship keeps its state in `ships/<n>/` in the session scratchpad: a `ship` file with the lines `session=<uuid>`, `branch=<branch>` and `worktree=<absolute path>`, then one `<k>.msg` and `<k>.log` per turn, `k` counting from 1. An issue whose `ship` file exists has its ship; it never gets a second one.

While live ships are fewer than the count, take the next unblocked issue in plan order without a ship:

1. **Worktree.** Create one on a new branch `ticket/<n>-<slug>` (slug: a few words of the title, kebab-case) from the latest `origin/<default>`, with the repo's own worktree command where its instructions name one (jj: `scripts/worktree-new.sh ship-<n> <branch>`, which also installs and links the backend), otherwise `git fetch && git worktree add -b <branch> .claude/worktrees/ship-<n> origin/<default>`. An issue with an open PR uses that PR's head branch instead, based on `origin/<head branch>` (`git worktree add -b <branch> <path> origin/<branch>`, or the repo command with that base). An issue with an earlier branch gets the new ticket branch based on `origin/<earlier branch>`, with `-2` added to its name when it would match the earlier branch's, which stays as it was. Take its absolute path from `git worktree list`, and write the `ship` file with a new `uuidgen | tr A-Z a-z` as the session.
2. **Brief.** Write `1.msg` with the Write tool, brackets filled:

   > Ship issue #[n] in [owner/repo]. Read `~/.claude/skills/ship/SKILL.md` and follow it, with the arguments `[n][ with workers]`, except where this prompt says otherwise. Your worktree is already on the ticket branch `[branch]`; use it.[ Open PR only: Open PR #[pr] on that branch already holds work for this issue: take it as yours, finish what the issue still needs, and carry on from step 3 with that PR instead of opening another.][ Earlier branch only: Your branch starts from `[earlier branch]`, which holds earlier commits for this issue with no PR: take them as yours, bring the branch up to date with `origin/[default]`, and finish what the issue still needs.] You run headless and nobody can answer mid-turn: wherever ship says to ask the user, end your turn with `waiting on the user: <question>`, and the answer comes as your next message. The user started this batch, and through it authorizes the GitHub writes that ship and the repo's issue rules call for: comments, labels, ticked criteria and closing, on issue #[n], on your PR, and, after the merge, on any issue outside this batch that your PR fixes, which you close only with evidence that it is fixed. When such a write is refused anyway, end your turn with `waiting on the user: <the refused command and why it is needed>`. Leave the device lanes to the train: run none, and say so in your checks comment.[ Count above 1: Other ships run beside you on this machine, and only the holder of the baton may merge or run anything on a phone, emulator or Simulator. You hold it only while a message that hands it to you is your latest, and it passes back when your turn ends. Before such a device run without it, end your turn with `needs the baton: <the run>`. Once you hold it, end your turn as soon as that run finishes, with `device run done: <result>`, so the baton passes on while you wait to carry on. When the PR is green at step 5, end your turn with `ready to merge <PR url>` instead of merging.]

3. **Start**, as a background Bash command (`run_in_background: true`):

   ```bash
   cd <worktree> && { [ ! -f .env.worktree ] || . ./.env.worktree; } && ~/.claude/skills/shipmaster/run-ship.sh <dir>/1.log --permission-mode auto -n ship-<n> --session-id <uuid> "$(cat <dir>/1.msg)"
   ```

To **resume** a ship, write the message to the next `<k>.msg` and run the same command with `<k>.log` and `--resume <uuid> "$(cat <dir>/<k>.msg)"` in place of the `-n` and `--session-id` arguments. The file keeps quotes and backticks in a message intact. Each command exits when the ship's turn ends, and its exit wakes you.

## 3. Each wake

On every wake and every user message, rebuild the state from GitHub and `ships/`; they hold everything, so nothing depends on your memory of earlier turns. A ship's reply is the `result` field of the `"type":"result"` line in its latest `<k>.log` (`grep '"type":"result"' <log> | tail -1`). Give each ship the first state that matches:

1. **working**: `pgrep -f <its latest log>` finds its command or its wake (below). That command ends 15 minutes after the ship's reply even when the ship's own process (`pgrep -f '[c]laude -p .*<uuid>'`) stays alive, held open by something it left running, such as a server; that process may still carry on with another reply once the thing it waits on ends.
2. **waiting**: its reply ends with `waiting on the user: <question>`, even after its PR merged (a refused write after the merge asks this way). Pass the question to the user word for word, with the issue, once per log. Resume the ship with their answer as they wrote it.
3. **merged**: `gh pr list --head <branch> --state merged` finds its PR. Remove its worktree with `git worktree remove <path>` to free the disk: its commits are on the default branch, and ship copies its evidence out before merging. Only a dirty worktree stays, since uncommitted edits are on no branch; report it. While the ship's process is alive, leave the worktree for a later wake.
4. **ready**: its reply ends with `ready to merge <PR url>`.
5. **needs the baton**: its reply ends with `needs the baton: <the run>`.
6. **device run done**: its reply ends with `device run done: <result>`.
7. **lingering**: its process is alive and `<k>.wait` is missing or holds a different reply count than the log. It is live: start its wake.
8. **stopped**: anything else: no reply in the latest log, an error, five review rounds without a clean one, a log ending `run-ship: no output`, or a lingering ship whose wake ran out. Report its last reply, and if its process is still alive, its pid and that `kill <pid>` stops it.

**Never resume a ship whose process is alive**, since two turns of one session would then run in one worktree. Where an action below would resume it, start its wake instead and resume it when the wake ends. When its wake has already run out (`<k>.wait` holds the log's reply count), tell the user once that its process is still alive, with its pid, and that it resumes once they stop it with `kill <pid>`.

**A ship's wake** ends on a new reply, on its process exiting, or after two hours. Write the log's reply count to `<k>.wait`, then run as a background command (the log path in it makes the ship count as working meanwhile):

```bash
log=<log>; n=$(grep -c '"type":"result"' "$log"); end=$((SECONDS+7200)); while pgrep -f '[c]laude -p .*<uuid>' >/dev/null && [ "$(grep -c '"type":"result"' "$log")" -eq "$n" ] && [ $SECONDS -lt $end ]; do sleep 30; done
```

Then act, in this order:

1. **Pass the baton.** The **baton** is the one right to merge or use a device; it keeps two ships off one emulator and keeps merge checks and device runs from loading the machine at once. When no working ship's latest message handed it over, give it to the earliest ready ship in plan order ("You hold the baton: merge now, carrying on from step 5."), or else to the earliest ship that needs it ("You hold the baton: do that run."), by resuming that ship. A ship hands it back as soon as its run ends, so a merge never waits behind the rest of another ship's work.
2. **Carry on.** Resume every ship whose device run is done with "Carry on from where you stopped."; it no longer holds the baton.
3. **Train.** The **train** is one full device run on the default branch that covers every ship merged since the last one, in place of a run per ship. One is due once four ships have merged since the last train, or when no ship is live, none can launch and one has merged since. Start it when it is due and no ship holds the baton, and hand the baton to no ship until it ends. Run it the repo's way (skc-workspace: `skc-mobile/docs/tier2-lane.md`, "A full run"), and wait for its result with a background command that ends when the run does. When it is red, open one issue naming each failing lane, its log, and the PRs merged since the last green train, so the next train covers them again.
4. **Launch.** Run step 2 for every slot that is free.
5. **Tell.** One line per change since the last wake: merged, waiting with its question, a device run's or a train's result, stopped with its reason.

When no ship is live, none can launch and no train is due or running, go to step 4. Otherwise end your turn.

## 4. Report

One line per issue: merged (its PR, and its worktree if it stayed dirty), stuck (its blocker), stopped (its reason), or waiting (its question). The user can open any idle ship with `claude --resume <uuid>` from its worktree.
