import contextlib, io, json, os, sys, tempfile, unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf

CHEAP = ["deepseek-high", "hydrogen-medium", "argon-medium"]


def routed(rows, type_, c, after=None):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        perf.route(rows, SimpleNamespace(type=type_, complexity=c, after=after))
    return out.getvalue().split()[1]


def row(model, effort, outcome="pass", c=2):
    return {"model": model, "effort": effort, "type": "bug-diagnosis", "complexity": c, "outcome": outcome, "blocker": "none", "task": f"{model} {outcome}"}


class Route(unittest.TestCase):
    def test_low_complexity_starts_on_a_cheap_non_claude_tier(self):
        self.assertIn(routed([], "bug-diagnosis", 2), CHEAP)

    def test_high_complexity_floor_stays_sonnet_high(self):
        self.assertEqual(routed([], "bug-diagnosis", 4), "sonnet-high")

    def test_after_an_in_flight_sonnet_medium_goes_to_sonnet_high(self):
        self.assertEqual(routed([], "bug-diagnosis", 2, after="sonnet-medium"), "sonnet-high")

    def test_merges_stay_on_claude(self):
        self.assertEqual(routed([], "merge", 3), "sonnet-high")

    def test_after_a_shell_tier_a_low_merge_never_drops_below_it(self):
        self.assertEqual(routed([], "merge", 2, after="sonnet-medium"), "sonnet-high")
        self.assertEqual(routed([], "merge", 2, after="deepseek-high"), "sonnet-high")

    def test_hydrogen_and_argon_keep_separate_records(self):
        self.assertEqual(perf.tier(f"{perf.MODELS['hydrogen']}/medium"), "hydrogen-medium")
        self.assertEqual(perf.tier(f"{perf.MODELS['argon']}/medium"), "argon-medium")


class Add(unittest.TestCase):
    def test_add_accepts_each_new_model(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.jsonl")
            for m in ("deepseek", "hydrogen", "argon"):
                a = SimpleNamespace(model=m, effort="high", type="coding", platform="none", task=m, complexity=2, outcome="pass",
                                    blocker="none", attempts=0, interventions=0, escalated_from=None, escalated_to=None, ktok=1,
                                    wall_min=None, note="t", date=None)
                with contextlib.redirect_stdout(io.StringIO()):
                    perf.add([], a, p)
            tiers = [perf.tier(f"{r['model']}/{r['effort']}") for r in map(json.loads, open(p))]
            self.assertEqual(tiers, ["deepseek-high", "hydrogen-high", "argon-high"])


if __name__ == "__main__":
    unittest.main()
