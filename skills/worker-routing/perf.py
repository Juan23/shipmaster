#!/usr/bin/env python3
"""Worker performance log: `route` to pick a tier, `add` to record a finished worker, `stats` for humans.

One log for every project, in this user-level skill folder: ~/.claude/skills/worker-routing/agent-performance-log.jsonl
"""
import argparse, collections, json, os, sys
from datetime import date

MODELS = {"haiku": "haiku-5.5", "sonnet": "sonnet-5.5", "opus": "opus-5.5"}
EFFORTS = ["low", "medium", "high", "xhigh", "max", "unknown"]
TYPES = ["audit", "merge", "cleanup", "coding", "bug-diagnosis", "harness-build", "device-run", "harness-fix", "review"]
LEGACY_TYPES = ["hosted-harness"]  # pre-split rows; readable in stats, not accepted by add/route
PLATFORMS = ["ios", "android", "both", "none"]
OUTCOMES = ["pass", "partial", "fail"]
BLOCKERS = ["none", "model", "env"]
REWORK_ORDER = "kind date task tier type complexity cycles wall_min note".split()
ORDER = "date model effort type platform task complexity outcome blocker attempts interventions escalated_from escalated_to ktok wall_min note".split()


LOG_PATH = os.path.expanduser("~/.claude/skills/worker-routing/agent-performance-log.jsonl")


def tier(s):
    """'haiku-5.5'+'high' or 'haiku/high' or 'haiku-high' -> 'haiku-high'."""
    if not s:
        return None
    m, e = s.split("/") if "/" in s else s.rsplit("-", 1)
    return f"{m.split('-')[0]}-{e}"


def load(p):
    return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []


def split(rows):
    """Worker rows, plus the set of tasks a later rework row charged back to them."""
    reworked = {r["task"] for r in rows if r.get("kind") == "rework"}
    return [r for r in rows if r.get("kind") != "rework"], reworked


def stats(rows, a):
    rw = [r for r in rows if r.get("kind") == "rework" and (not a.type or r["type"] == a.type)]
    rows, reworked = split(rows)
    if a.type:
        rows = [r for r in rows if r["type"] == a.type]
    clean = [r for r in rows if r.get("blocker") != "env"]
    print(f"{len(rows)} rows ({len(clean)} non-env){' type=' + a.type if a.type else ''}\n")

    def table(title, key, src):
        g = collections.defaultdict(list)
        for r in src:
            g[key(r)].append(r)
        print(title)
        print(f"  {'group':34}{'n':>4}{'pass':>6}{'part':>6}{'fail':>6}{'pass%':>7}{'ktok':>7}{'ktok/pass':>10}{'rw%':>6}")
        for k in sorted(g, key=str):
            v = g[k]
            c = collections.Counter(r["outcome"] for r in v)
            kt = [r["ktok"] for r in v if isinstance(r.get("ktok"), (int, float))]
            avg = sum(kt) / len(kt) if kt else 0
            per = f"{sum(kt) / c['pass']:.0f}" if c["pass"] and kt else "-"
            rw = sum(r["task"] in reworked for r in v)
            print(f"  {str(k):34}{len(v):>4}{c['pass']:>6}{c['partial']:>6}{c['fail']:>6}{100 * c['pass'] / len(v):>6.0f}%{avg:>7.0f}{per:>10}{100 * rw / len(v):>5.0f}%")
        print()

    t = lambda r: f"{r['model'].split('-')[0]}-{r['effort']}"
    table("By tier (non-env):", t, clean)
    table("By type x tier (non-env):", lambda r: f"{r['type']} / {t(r)}", clean)
    table("By platform x tier (non-env, rows with a platform):", lambda r: f"{r['platform']} / {t(r)}", [r for r in clean if r.get("platform") not in (None, "none")])
    table("By complexity x tier (non-env):", lambda r: f"c{bucket(r)} / {t(r)}", clean)
    esc = collections.Counter((r["escalated_from"] or "-", t(r)) for r in rows if r.get("escalated_from"))
    if esc:
        print("Escalations (from -> to):")
        for (f, to), n in esc.most_common():
            print(f"  {f} -> {to}: {n}")
    if rw:
        print("Rework (by tier of the worker whose output needed it):")
        g = collections.defaultdict(list)
        for r in rw:
            g[r["tier"]].append(r)
        for t in sorted(g):
            v = g[t]
            print(f"  {t:34}{len(v):>3} reworks, {sum(r['cycles'] for r in v)} rebuild/retest cycles, {sum(r.get('wall_min') or 0 for r in v):.0f} min")


LADDER = ["haiku-medium", "haiku-high", "sonnet-high", "opus-low", "opus-medium"]
def floor(c):
    """Cold-start tier index by complexity (1.0-5.0); data moves it either way."""
    return 0 if c < 2.5 else 1 if c < 3.5 else 2


def cx(s):
    """argparse type: complexity 1.0-5.0, at most one decimal place."""
    try:
        v = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"complexity must be a number 1-5, got {s!r}")
    if not 1 <= v <= 5 or round(v, 1) != v:
        raise argparse.ArgumentTypeError("complexity must be 1-5 with at most one decimal place (e.g. 3.5)")
    return int(v) if v == int(v) else v


def bucket(r):
    """Whole-number bucket for stats tables (half rounds up), so 3.5 groups with c4."""
    c = r.get("complexity")
    return "?" if c is None else int(c + 0.5)


def route(rows, a):
    """Cheapest tier the evidence doesn't rule out. Evidence: same type, non-env, known effort,
    complexity within 1.0. Score = (pass + partial/2) / n. With n >= 2: score >= .67 is 'proven',
    score < .5 is 'weak' and is stepped over. Weakness doesn't propagate down: escalated tasks are the
    hardest ones, so a strong tier's failures say little about a cheaper tier with its own record.
    A reworked row loses 0.5: a pass that needed another build/test cycle scores like a partial."""
    rows, reworked = split(rows)
    ev = collections.defaultdict(list)
    for r in rows:
        t = f"{r['model'].split('-')[0]}-{r['effort']}"
        if r["type"] == a.type and r.get("blocker") != "env" and t in LADDER and abs((r.get("complexity") or 0) - a.complexity) <= 1.0:
            ev[t].append(r)
    val = lambda r: max({"pass": 1, "partial": 0.5}.get(r["outcome"], 0) - 0.5 * (r["task"] in reworked), 0)
    score = {t: sum(val(r) for r in v) / len(v) for t, v in ev.items()}
    proven = [i for i, t in enumerate(LADDER) if len(ev[t]) >= 2 and score[t] >= 0.67]
    weak = [i for i, t in enumerate(LADDER) if len(ev[t]) >= 2 and score[t] < 0.5]
    i = floor(a.complexity)
    why = [f"floor {LADDER[i]} for c{a.complexity}"]
    if proven and min(proven) < i:
        i = min(proven)
        why.append(f"lowered: {LADDER[i]} proven")
    while i in weak and i < len(LADDER) - 1:
        why.append(f"skipped {LADDER[i]}: weak")
        i += 1
    if a.after:
        i = min(max(i, LADDER.index(tier(a.after)) + 1), len(LADDER) - 1)
        why.append(f"after {tier(a.after)} stalled")
    print(f"route: {LADDER[i]} ({'; '.join(why)})")
    for t in LADDER:
        if ev[t]:
            c = collections.Counter(r["outcome"] for r in ev[t])
            kt = [r["ktok"] for r in ev[t] if isinstance(r.get("ktok"), (int, float))]
            rw = sum(r["task"] in reworked for r in ev[t])
            print(f"  {t}: {c['pass']}/{c['partial']}/{c['fail']} p/pt/f, {rw} reworked, score {score[t]:.2f}, avg {sum(kt) / max(len(kt), 1):.0f}k")


def add(rows, a, p):
    model = MODELS.get(a.model.split("-")[0])
    if not model:
        sys.exit(f"model must be one of {list(MODELS)}")
    r = {
        "date": a.date or date.today().isoformat(),
        "model": model,
        "effort": a.effort,
        "type": a.type,
        "platform": a.platform,
        "task": a.task,
        "complexity": a.complexity,
        "outcome": a.outcome,
        "blocker": a.blocker,
        "attempts": a.attempts,
        "interventions": a.interventions,
        "escalated_from": tier(a.escalated_from),
        "escalated_to": tier(a.escalated_to),
        "ktok": a.ktok,
        "wall_min": a.wall_min,
        "note": a.note,
    }
    with open(p, "a") as f:
        f.write(json.dumps({k: r[k] for k in ORDER}) + "\n")
    print(f"appended row {len(rows) + 1} to {p}")


def rework(rows, a, p):
    """Charge a defect found after a worker's row back to that worker: latest worker row with this exact task."""
    src = [r for r in split(rows)[0] if r["task"] == a.task]
    if not src:
        near = sorted({r["task"] for r in rows if a.task.lower() in r["task"].lower()})[:5]
        sys.exit(f"perf.py: no worker row with task {a.task!r}" + (f"; close: {near}" if near else ""))
    w = src[-1]
    r = {"kind": "rework", "date": a.date or date.today().isoformat(), "task": a.task, "tier": tier(f"{w['model']}/{w['effort']}"),
         "type": w["type"], "complexity": w["complexity"], "cycles": a.cycles, "wall_min": a.wall_min, "note": a.note}
    with open(p, "a") as f:
        f.write(json.dumps({k: r[k] for k in REWORK_ORDER}) + "\n")
    print(f"appended rework row {len(rows) + 1} against {r['tier']} ({w['date']}) to {p}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", help="override log path")
    ap.add_argument("--init", action="store_true", help="allow creating the log on its first add")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stats")
    s.add_argument("--type", choices=TYPES + LEGACY_TYPES)
    sub.add_parser("path")
    ro = sub.add_parser("route")
    ro.add_argument("--type", required=True, choices=TYPES)
    ro.add_argument("--complexity", required=True, type=cx)
    ro.add_argument("--after", choices=LADDER, help="tier that just stalled on this task; route goes above it")
    rw = sub.add_parser("rework", help="a defect found in a worker's accepted output forced another build/test cycle")
    rw.add_argument("--task", required=True, help="exact --task of the worker row that produced the defect")
    rw.add_argument("--cycles", required=True, type=int, help="extra build/test cycles the defect caused (>= 1)")
    rw.add_argument("--wall-min", type=float, help="wall-clock minutes the rework cost")
    rw.add_argument("--date")
    rw.add_argument("--note", required=True)
    d = sub.add_parser("add")
    d.add_argument("--model", required=True, help="haiku | sonnet | opus")
    d.add_argument("--effort", required=True, choices=EFFORTS)
    d.add_argument("--type", required=True, choices=TYPES)
    d.add_argument("--platform", choices=PLATFORMS, default="none", help="device platform the task touched (default none)")
    d.add_argument("--task", required=True)
    d.add_argument("--complexity", required=True, type=cx)
    d.add_argument("--outcome", required=True, choices=OUTCOMES)
    d.add_argument("--blocker", required=True, choices=BLOCKERS)
    d.add_argument("--attempts", required=True, type=int)
    d.add_argument("--interventions", required=True, type=int)
    d.add_argument("--ktok", required=True, type=int)
    d.add_argument("--escalated-from")
    d.add_argument("--escalated-to")
    d.add_argument("--wall-min", type=float)
    d.add_argument("--date")
    d.add_argument("--note", required=True)
    a = ap.parse_args()
    p = a.log or LOG_PATH
    if a.cmd != "path" and not os.path.exists(p) and not (a.cmd == "add" and a.init):
        sys.exit(f"perf.py: no log at {p}; pass --init with add to start it")
    if a.cmd == "path":
        print(p)
    elif a.cmd == "route":
        route(load(p), a)
    elif a.cmd == "stats":
        stats(load(p), a)
    elif a.cmd == "rework":
        if a.cycles < 1:
            sys.exit("perf.py: --cycles must be >= 1")
        rework(load(p), a, p)
    else:
        add(load(p), a, p)


if __name__ == "__main__":
    main()
