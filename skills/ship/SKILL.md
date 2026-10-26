---
name: ship
description: "Take one GitHub issue to main: build it, open a PR, run fresh-reviewer rounds until green, merge."
disable-model-invocation: true
---

Take one ticket from open issue to merged on the default branch. The arguments hold the issue (`123`, `owner/repo#123` or its URL) and, sometimes, a request for workers. Every GitHub step runs through `gh`.

**Mode.** Solo by default: you write and fix the code yourself. Switch to workers mode only when the user asks for workers in their own words ("use workers", "with workers", "delegate it"), directly or through a shipmaster prompt; then a worker subagent builds the ticket by step 2 and a fresh worker does each fix round. Dispatch and record every worker, the reviewers included, through the `worker-routing` skill.

**Full checks** are the repo's own build, type check and test commands, run where its `AGENTS.md`/`CLAUDE.md` says they must run (a staging database, for example). Run them before every push. A pass holds for its tree (`git rev-parse 'HEAD^{tree}'`), so code that already passed is not rerun, and a commit that changes no code keeps the pass. A slow check (device lanes) covers only what the change can reach: where the repo has a selector, such as `skc-mobile/scripts/affected-lanes.mjs`, run the lanes it names, and say in the checks comment which earlier pass covers the rest.

## 1. Start

Read the issue with `gh issue view`; it must be open and belong to this checkout's repo. State its title. Ask the user when two readings of the ticket would ship different code, and, in the same one question, about every planned departure from an acceptance line (a substitute, a behaviour change), so no review round later waits on an owner approval. Record the answers on the issue. With a clean tree, fetch and create `ticket/<n>-<slug>` from the latest default branch, or switch to that branch if it already exists.

Done when you are on the ticket branch with the acceptance criteria in hand.

## 2. Build

Call the Skill tool with `tdd`. Where `tdd` says to confirm the seams with the user, take your recommended seams as confirmed: write each one down with its one-line note and carry on. Run type checks and single test files as you go, then the full checks. Commit to the ticket branch.

Done when every acceptance criterion is met, the full checks pass, and the tree is clean.

## 3. Open the PR

Push the branch and open the PR against the default branch with `gh pr create`: the issue's title, and a body whose first line is `Closes #<n>`, or the first line the repo's instructions require instead (such as `Part of #<n>`), then a short summary (what changed, the seams under test, how it was verified). Post the pass with `gh pr comment`, first line exactly `Checks passed on tree <tree>`, then the commands you ran.

Done when the PR is open with its checks comment.

## 4. Review rounds

Start round 1 as soon as the PR is open; it does not wait for slow checks still running, since the merge gate requires both.

Each **round**:

1. **Review.** Spawn a fresh reviewer with the brief below: a new worker every round, one that has seen no earlier round and wrote none of the code. Round N is one more than the PR comments whose first line starts `Review round`.
2. **Fix.** When the verdict is `changes`, fix each blocking finding. A finding you can show is wrong gets a reply on the PR with the evidence instead; the next reviewer reads the thread. Run the full checks, commit, push, post a new checks comment, and start the next round.

After five rounds with no clean one, stop and ask the user, listing the open findings.

Reviewer brief, brackets filled:

> Review PR [url] for issue [ref], in [repo path], which is checked out at the PR head. Call the Skill tool with `code-review`, giving it the fixed point `origin/[default branch]` and issue [ref] as the spec. A **blocking** finding is a Spec finding, or a Standards violation that changes behaviour, safety, security or data, that survives its verification step. Wording, naming, comment accuracy and judgement-call smells are notes and never block; a missing check result is not a finding either, since the merge gate checks evidence. Read the earlier rounds and replies (`gh pr view --comments`) first: a finding answered there with evidence stays answered unless the code proves the answer wrong. Post the code-review report with `gh pr comment`, first line exactly `Review round [N]: clean on <sha>` when nothing blocks, otherwise `Review round [N]: changes on <sha>`, where `<sha>` is the PR's full `headRefOid`, and include the lines `Reviewed-SHA: <sha>` and `Verdict: clean` (or `Verdict: findings`) on their own, which merge gates read. Leave the code exactly as it is. Reply with the verdict and the blocking findings.

Done when a round is clean.

## 5. Merge

The PR is **green** when every one of these holds, read from `gh pr view --json state,isDraft,mergeable,headRefOid,comments`, `gh issue view <n> --json comments` and the checkout:

- it is open, not a draft, and not `CONFLICTING`;
- the local `HEAD` is its `headRefOid` and contains the latest default branch (after `git fetch`, `git merge-base --is-ancestor origin/<default> HEAD`);
- the latest checks comment names the tree of that commit;
- the latest review comment reads `clean on` that `headRefOid`, or on an earlier head with the identical change (the same `git diff origin/<default>...<sha> | git patch-id --verbatim`);
- every departure from an acceptance line carries the user's approval, recorded on the issue or PR. A departure is any place where what you built or checked differs from what the line names (another control, screen, route or check). A reviewer's acceptance is not the user's: ask the user about any other departure, as in step 1, before you call the PR green;
- every evidence file the PR or issue cites is committed or lives outside the checkout. Copy one that sits only in an ignored or untracked folder to where the repo's instructions keep evidence (or `~/ship-evidence/<repo>/<n>/` where they name no place), and cite the copy, because a worktree is removed after the merge.

When the branch is behind or `CONFLICTING`, merge `origin/<default>` into it, resolving conflicts by the repo's rules, run the full checks, push and post a new checks comment; run a new review round only when the change is no longer identical.

Merge only a green PR, and only the commit you checked, with the repo's own merge command where its instructions name one (such as `node scripts/merge-gate.mjs <pr>`), otherwise `gh pr merge --squash --delete-branch --match-head-commit <headRefOid>`. When the cleanup after the merge fails because another worktree holds the default branch, the merge still stands; delete the remote branch if it remains.

Done when the PR shows `MERGED`, the issue shows `CLOSED` (close it yourself when the PR body did not, or leave it open with a comment naming what remains where the repo's closing rules say so), and the checkout is detached at the updated `origin/<default>`, since another worktree may hold the default branch.

Report the merged PR, the number of rounds, where its evidence is kept, and the non-blocking notes from the last review.
