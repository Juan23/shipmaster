# shipmaster

Claude Code skills and worker agents: workers picked from a performance log, and DeepSeek and Gemini attackers alongside the Claude merge-reviewer.

- **opencode-worker** runs DeepSeek through opencode as the read-only attackers of `attack-round`. It tells whether a run is done, stuck, looping or never started.
- **attack-round** runs cheap read-only reviewers (DeepSeek attackers and agy Gemini) on a committed branch at the same time as the Claude `merge-reviewer`, each with a 20-minute limit, picks a model other than the builder's where it can, and collects what they find.
- **worker-routing** picks the model and effort for every worker (builds, fixes, reviewers, merges, audits), from a log of how each tier did on earlier tasks, and adds to that log when the worker finishes.

## worker-routing

Before dispatching a worker (a build, a fix, a reviewer, a merge or an audit), `perf.py route` picks its tier. It starts from a tier set by the task's complexity, drops to a cheaper tier the log has proven on similar tasks, and skips tiers the log shows doing badly. With an empty log it returns the starting tier. After the worker finishes, `perf.py add` records the outcome. If accepted work later needs another build or test cycle, `perf.py rework` marks it, and that tier ranks lower next time.

```bash
python3 ~/.claude/skills/worker-routing/perf.py route --type coding --complexity 3
python3 ~/.claude/skills/worker-routing/perf.py stats
```

Work that local tests can prove starts on agy (Gemini, run from the shell): `hydrogen-high` and `neon-medium`, on trial against each other. Coding that ends in a staging or device run, harness work, and coding at complexity 4.5 and above start on `opus-medium`, then `opus-high` and `opus-xhigh`. Simple work falls back to `haiku-medium`. `sonnet-high` takes bug diagnosis, design, device runs and merges; it does not build, and DeepSeek does not build. PR reviews run on the `merge-reviewer` agent, which the review gate requires. The Claude tiers are subagent definitions in `agents/`. `skills/worker-routing/SKILL.md` has the full routing rules.

The log has one JSON line per worker and per rework, and is shared by every project on the machine: `~/.claude/skills/worker-routing/agent-performance-log.jsonl`. It never goes in this repo, and `.gitignore` blocks it if it ends up here.

## Install

```bash
git clone https://github.com/Juan23/shipmaster ~/Projects/shipmaster
mkdir -p ~/.claude/skills/worker-routing ~/.claude/agents
ln -sfn ~/Projects/shipmaster/skills/opencode-worker ~/.claude/skills/opencode-worker
ln -sfn ~/Projects/shipmaster/skills/attack-round ~/.claude/skills/attack-round
ln -sf ~/Projects/shipmaster/skills/worker-routing/{SKILL.md,perf.py} ~/.claude/skills/worker-routing/
ln -sf ~/Projects/shipmaster/agents/*.md ~/.claude/agents/
touch ~/.claude/skills/worker-routing/agent-performance-log.jsonl
```

The links keep the installed skills on the checkout, so `git pull` updates them. When a pull adds or removes an agent file, rerun the `ln -sf ~/Projects/shipmaster/agents/*.md` line and delete links in `~/.claude/agents/` that no longer point at a file (`find ~/.claude/agents -type l ! -exec test -e {} \; -delete`). On a machine that had the retired `ship` and `shipmaster` skills, delete their dead links once with `find ~/.claude/skills -maxdepth 1 -type l ! -exec test -e {} \; -delete`. The worker-routing install links its two files instead of the folder, so the log stays in `~/.claude/skills/worker-routing/` and out of the checkout. `touch` creates an empty log on a new machine and leaves an existing one alone. Running the block again after the clone is safe: it replaces copied skill files, copied agents and old links with links to this checkout. It can't fix two leftovers, so delete them first: an `opencode-worker` or `attack-round` folder that is a copy rather than a link, and a `worker-routing` folder that is itself a link.

You also need:

- Claude Code with the Agent tool;
- `git`, Python 3, opencode signed in to the `opencode-go` provider, and agy (Antigravity CLI) signed in.
