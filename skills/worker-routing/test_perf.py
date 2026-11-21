import contextlib, io, json, os, sys, tempfile, unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf

def routed(rows, type_, c, after=None):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        perf.route(rows, SimpleNamespace(type=type_, complexity=c, after=after))
    return out.getvalue().split()[1]


class Route(unittest.TestCase):
    def test_default_worker_is_hydrogen_high(self):
        self.assertEqual(routed([], "bug-diagnosis", 2), "hydrogen-high")
        self.assertEqual(routed([], "coding", 4), "hydrogen-high")

    def test_after_hydrogen_or_a_retired_gemini_tier_goes_to_sonnet_high(self):
        for stalled in ("hydrogen-high", "neon-medium", "hydrogen-medium"):
            self.assertEqual(routed([], "coding", 3, after=stalled), "sonnet-high")

    def test_c5_floor_is_sonnet_high(self):
        self.assertEqual(routed([], "bug-diagnosis", 4.5), "sonnet-high")

    def test_haiku_work_starts_on_deepseek_then_haiku(self):
        self.assertEqual(routed([], "audit", 3), "deepseek-high")
        self.assertEqual(routed([], "coding", 2), "deepseek-high")
        self.assertEqual(routed([], "audit", 3, after="deepseek-high"), "haiku-medium")

    def test_after_an_in_flight_sonnet_medium_goes_to_sonnet_high(self):
        self.assertEqual(routed([], "bug-diagnosis", 2, after="sonnet-medium"), "sonnet-high")

    def test_merges_stay_on_claude(self):
        self.assertEqual(routed([], "merge", 2), "haiku-medium")
        self.assertEqual(routed([], "merge", 3), "sonnet-high")

    def test_after_a_shell_tier_a_low_merge_never_drops_below_it(self):
        self.assertEqual(routed([], "merge", 2, after="sonnet-medium"), "sonnet-high")
        self.assertEqual(routed([], "merge", 2, after="deepseek-high"), "haiku-medium")

    def test_gemini_rows_key_to_their_tiers(self):
        self.assertEqual(perf.tier(f"{perf.MODELS['neon']}/medium"), "neon-medium")
        self.assertEqual(perf.tier(f"{perf.MODELS['hydrogen']}/medium"), "hydrogen-medium")


class Add(unittest.TestCase):
    def test_add_accepts_each_new_model(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.jsonl")
            for m in ("deepseek", "hydrogen", "neon"):
                a = SimpleNamespace(model=m, effort="high", type="coding", platform="none", task=m, complexity=2, outcome="pass",
                                    blocker="none", attempts=0, interventions=0, escalated_from=None, escalated_to=None, ktok=1,
                                    wall_min=None, note="t", date=None)
                with contextlib.redirect_stdout(io.StringIO()):
                    perf.add([], a, p)
            tiers = [perf.tier(f"{r['model']}/{r['effort']}") for r in map(json.loads, open(p))]
            self.assertEqual(tiers, ["deepseek-high", "hydrogen-high", "neon-high"])


if __name__ == "__main__":
    unittest.main()
