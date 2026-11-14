---
name: ship
description: "Take one GitHub issue to main: build it, code-review it against the issue, open a PR, run fresh ponytail-review rounds until green, merge."
disable-model-invocation: true
---

Take one ticket from open issue to merged on the default branch. The arguments hold the issue (`123`, `owner/repo#123` or its URL) and, sometimes, a request for workers. Every GitHub step runs through `gh`.

**Mode.** Solo by default: you write and fix the code yourself. Switch to workers mode only when the user asks for workers in their own words ("use workers", "with workers", "delegate it"), directly or through a shipmaster prompt; then a Claude subagent builds the ticket by step 2 and a fresh one does each fix round. Dispatch and record the workers and the reviewers through the `worker-routing` skill.

**Full checks** are the repo's own build, type check and test commands, run where its `AGENTS.md`/`CLAUDE.md` says they must run (a staging database, for example). Where the repo names one pre-push check command, that command is the full checks: in Juan23/jj it is `npm run check` (the merge gate's checks for the diff, which switches to the full suite itself when its selection cannot be trusted). Run them before every push. A pass holds for its tree (`git rev-parse 'HEAD^{tree}'`), so code that already passed is not rerun, and a commit that changes no code keeps the pass. A pass of checks a selector covers (device lanes, for example) also carries across a merge of the default branch or a fix commit when the repo's selector, run on the change since the pass, names none of its checks; checks no selector covers rerun when code changed. The checks comment keeps the current tree in its first line and names, on a later line, the tree each carried pass came from. A slow check (device lanes) covers only what the change can reach, and a pull request never runs the full device suite unless the selector says to. Where the repo has a selector, such as `skc-mobile/scripts/affected-lanes.mjs` (in skc-workspace, `node tools/affected-checks.mjs` prints it with the API, webapp and harness checks), run exactly what it names and nothing more. When it answers "every lane", run the lanes on its `run on the pull request:` line; the full device suite before the next release build covers the rest. Say in the checks comment which lanes ran, and which earlier pass or release run covers the rest. Write the time each check command took in the checks comment.

## 1. Start

Read the issue with `gh issue view`; it must be open and belong to this checkout's repo. State its title. Ask the user when two readings of the ticket would ship different code, and, in the same one question, about every planned departure from an acceptance line (a substitute, a behaviour change), so no review round later waits on an owner approval. Record the answers on the issue. With a clean tree, fetch and create `ticket/<n>-<slug>` from the latest default branch, or switch to that branch if it already exists.

Done when you are on the ticket branch with the acceptance criteria in hand.

## 2. Build

When the change is docs only, or every changed line only sets a colour, skip `tdd`: no test can see it. Check it with the repo's build and, for a colour, a before and after screenshot. Otherwise call the Skill tool with `tdd`. Where `tdd` says to confirm the seams with the user, take your recommended seams as confirmed: write each one down with its one-line note and carry on. Run type checks and single test files as you go, and commit to the ticket branch. Leave the full checks until after the criteria check below.

Before the PR, check your work against each acceptance criterion yourself and commit everything to the ticket branch. Then run the full checks once, and commit. Then spawn a fresh `pr-reviewer` agent (Agent tool, `subagent_type` `pr-reviewer`) with the repository path, `origin/<default>` as the base, and the spec: the text of `gh issue view <n> --comments`, so the answers and approved departures recorded in step 1 count as spec. It runs `code-review` and `commentdiet` and fixes nothing. Fix every finding (in workers mode a fresh worker does the fixes), run the full checks, commit, and spawn a new `pr-reviewer`, until one reports REVIEW CLEAN for `HEAD`; the review gate blocks `gh pr create` until then. The PR's review rounds then run `ponytail-review`.

Done when every acceptance criterion is met, the `code-review` and `commentdiet` findings are fixed, the full checks pass, and the tree is clean.

## 3. Open the PR

Push the branch and open the PR against the default branch with `gh pr create`: the issue's title, and a body whose first line is `Closes #<n>`, or the first line the repo's instructions require instead (such as `Part of #<n>`), then a short summary (what changed, the seams under test, how it was verified, and what `code-review` found and what you fixed), then a `Criteria` heading that round 1 fills. Post the pass with `gh pr comment`, first line exactly `Checks passed on tree <tree>`, then the commands you ran.

Done when the PR is open with its checks comment.

## 4. Review rounds

Start round 1 as soon as the PR is open; it does not wait for slow checks still running, since the merge gate requires both.

Each **round**:

1. **Review.** Spawn a fresh `merge-reviewer` agent (Agent tool, `subagent_type` `merge-reviewer`) with the brief below: a new one every round, one that has seen no earlier round and wrote none of the code. Round N is one more than the PR comments whose first line starts `Review round`. Round 1 reviews the whole change; from round 2 on, the reviewer reviews only what changed since the last round (the brief says how). First, when a file in that change is on a **security path** (`git diff --name-only` over the same range; from round 2 on, leave out files the default branch brought in, as the brief does), spawn a fresh security reviewer (`subagent_type` `opus-high`; it is not a gate review and posts no review block) with the security brief below and paste its reply into the reviewer brief; otherwise fill that bracket with `not run: no security path changed`. The security paths are the ones the repo's `AGENTS.md`/`CLAUDE.md` names as security-sensitive, or, where it names none, every path with `migration`, `polic`, `rls`, `auth`, `functions` (edge or server), `payment`, `billing`, `secret` or `.env` in its name; in Juan23/jj that is at least `supabase/migrations/`, `supabase/functions/` and anything auth or payments. Paths decide, not your judgement of the change.
2. **Fix.** After round 1, edit the PR body to quote its `Criteria:` lines under the `Criteria` heading. When the verdict is `changes`, fix each blocking finding. A finding you can show is wrong gets a reply on the PR with the evidence instead; the next reviewer reads the thread. Run the full checks, commit, push, post a new checks comment, and start the next round. For each unrelated finding the round marks `UNFILED`, open an issue (labelled `ready-for-agent` where the repo uses that label) and link it on the PR, so the next round finds it covered.

After five rounds with no clean one, stop and ask the user, listing the open findings.

Reviewer brief, brackets filled:

> Review PR [url] for issue [ref], in [repo path], which is checked out at the PR head. Read the issue and the earlier rounds and replies (`gh pr view --comments`) first: a finding answered there with evidence stays answered unless the code proves the answer wrong. Then call the Skill tool with `ponytail:ponytail-review` on the change since [`origin/<default branch>` in round 1; the last round's `Reviewed-SHA` from round 2 on], with the issue for context.[ Round 1: also give each acceptance criterion of the issue a verdict, met or not met, with the evidence you checked it by (a file and line, a test name, a command and its result).][ Round 2 on: you review only the change since that SHA. When the branch merged the default branch since then, leave out what the merge brought in: compare `git diff origin/[default branch]...<that SHA>` with `git diff origin/[default branch]...HEAD`. Also check that each blocking finding of the earlier rounds is fixed, answered, or (an unrelated one) covered by an issue linked on the PR; one that is none of these blocks. Judge whether the issue's items are all built against the whole change (`git diff origin/[default branch]...HEAD`), not the delta, so earlier work is not reported missing.] Security review: [the security reviewer's reply, or `not run: no security path changed`]; each of its findings that the change causes blocks, unless the code proves it wrong or the thread answers it with evidence the code does not contradict. Count only findings that survive ponytail's "Check before you report". A finding is **related** when the change causes it (in code it adds or alters, or in a caller it breaks); in round 1, an acceptance criterion that is not met or has no verdict is related too. Every related finding blocks. Every other finding (a fault that was already there, or one that needs an input nobody has made yet) is **unrelated**: look for an open issue that covers it, and mark it `UNFILED` when none does; an `UNFILED` finding blocks. A missing check result is not a finding, since the merge gate checks evidence. Post one comment with `gh pr comment`: first line exactly `Review round [N]: clean on <sha>` when nothing blocks, otherwise `Review round [N]: changes on <sha>`, where `<sha>` is the PR's full `headRefOid`; then the lines `Reviewed-SHA: <sha>` and `Verdict: clean` (or `Verdict: findings`) on their own, which merge gates read, before any quoted text could carry a line like them;[ round 1: then `Criteria:` and one line per acceptance criterion, in the issue's order: `- met:` or `- not met:`, the criterion, then `Evidence:` and where you checked it;] then a `Security:` line, `Security: not run, no security path changed` or `Security: reviewed, <count> findings`, and the security findings; then ponytail's report without its own `Verdict:` line. Leave the code exactly as it is. Reply with the blocking findings, then end with your agent's `REVIEW CLEAN` block when nothing blocks, otherwise its `REVIEW FINDINGS` block; the review gate reads that block.

Security brief, brackets filled:

> Review the security of PR [url] for issue [ref], in [repo path], which is checked out at the PR head. Read the earlier rounds and replies (`gh pr view --comments`) first, and leave out any finding answered there with evidence the code does not contradict. Call the Skill tool with `security-review`, which reviews the whole PR;[ round 2 on: report only findings in what changed since [the last round's `Reviewed-SHA`], leaving out what a merge of the default branch brought in (compare `git diff origin/[default branch]...<that SHA>` with `git diff origin/[default branch]...HEAD`);] report only faults this PR causes, and read the repo's `AGENTS.md`/`CLAUDE.md` for its backend rules (row-level security, migrations, auth in edge or server functions, service-role or admin keys, payments, secrets). Report only what you have checked: a finding names the file and line and the concrete failing case (the request, row or caller that gets through); a risk you cannot show that way is a note. Post nothing on GitHub, change no code, and ask nobody: reply with the findings, then the notes, or `no findings`.

Done when a round is clean.

## 5. Merge

The PR is **green** when every one of these holds, read from `gh pr view --json state,isDraft,mergeable,headRefOid,comments`, `gh issue view <n> --json comments` and the checkout:

- it is open, not a draft, and not `CONFLICTING`;
- the local `HEAD` is its `headRefOid` and contains the latest default branch (after `git fetch`, `git merge-base --is-ancestor origin/<default> HEAD`);
- the latest checks comment names the tree of that commit;
- the latest review comment reads `clean on` that exact `headRefOid`: the review gate accepts only a `merge-reviewer` REVIEW CLEAN block for the PR's current head, so any new commit needs a new round;
- every departure from an acceptance line carries the user's approval, recorded on the issue or PR. A departure is any place where what you built or checked differs from what the line names (another control, screen, route or check). A reviewer's acceptance is not the user's: ask the user about any other departure, as in step 1, before you call the PR green;
- every evidence file the PR or issue cites is committed or lives outside the checkout. Copy one that sits only in an ignored or untracked folder to where the repo's instructions keep evidence (or `~/ship-evidence/<repo>/<n>/` where they name no place), and cite the copy, because a worktree is removed after the merge.

When the branch is behind or `CONFLICTING`, merge `origin/<default>` into it, resolving conflicts by the repo's rules, run the full checks, push and post a new checks comment, then run a new review round on the new head.

Merge only a green PR, and only the commit you checked, with the repo's own merge command where its instructions name one (such as `node scripts/merge-gate.mjs <pr>`), otherwise `gh pr merge <pr> --squash --delete-branch --match-head-commit <headRefOid>` (name the PR: the gate otherwise reads it from the session's folder, which may not be this worktree). When the cleanup after the merge fails because another worktree holds the default branch, the merge still stands; delete the remote branch if it remains.

Done when the PR shows `MERGED`, the issue shows `CLOSED` (close it yourself when the PR body did not, or leave it open with a comment naming what remains where the repo's closing rules say so), and the checkout is detached at the updated `origin/<default>`, since another worktree may hold the default branch.

Report the merged PR, the number of rounds, where its evidence is kept, and the issues opened for unrelated findings.
