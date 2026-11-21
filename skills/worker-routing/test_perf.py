import contextlib, io, json, os, sys, tempfile, unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf

def routed(rows, type_, c, after=None, cycle=False):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        perf.route(rows, SimpleNamespace(type=type_, complexity=c, after=[after] if isinstance(after, str) else after, cycle=cycle))
    return out.getvalue().split()[1]


def row(model, effort, type_="coding", c=3):
    return {"model": perf.MODELS[model], "effort": effort, "type": type_, "complexity": c, "outcome": "pass", "blocker": "none", "task": f"{model}-{effort}"}


class Route(unittest.TestCase):
    def test_local_test_building_and_audits_start_on_agy(self):
        for type_, c in (("coding", 2), ("coding", 4), ("cleanup", 3), ("audit", 3)):
            self.assertEqual(routed([], type_, c), "hydrogen-high")

    def test_the_agy_trial_gives_the_next_task_to_the_model_with_fewer_rows_at_that_complexity(self):
        self.assertEqual(routed([row("hydrogen", "high")], "coding", 3), "neon-medium")
        self.assertEqual(routed([row("hydrogen", "high", c=2)], "coding", 4), "hydrogen-high")

    def test_a_failed_agy_task_gets_one_try_on_the_other_agy_model(self):
        self.assertEqual(routed([], "coding", 3, after="hydrogen-high"), "neon-medium")
        self.assertEqual(routed([row("hydrogen", "high")], "coding", 3, after="neon-medium"), "hydrogen-high")

    def test_the_failed_tasks_own_row_does_not_change_where_it_goes_next(self):
        failed = [row("hydrogen", "high")]
        self.assertEqual(routed(failed, "coding", 3, after="hydrogen-high"), "neon-medium")
        self.assertEqual(routed(failed + [row("neon", "medium")], "coding", 3, after=perf.AGY), "opus-medium")
        self.assertEqual(routed(failed, "coding", 3, after=perf.AGY), "opus-medium")

    def test_an_in_flight_hydrogen_medium_task_still_gets_its_try_on_neon(self):
        self.assertEqual(routed([], "coding", 3, after="hydrogen-medium"), "neon-medium")

    def test_a_run_the_environment_stopped_does_not_use_up_a_trial_turn(self):
        stopped = dict(row("hydrogen", "high"), outcome="fail", blocker="env")
        self.assertEqual(routed([stopped], "coding", 3), "hydrogen-high")

    def test_after_both_agy_models_simple_work_goes_to_haiku_and_the_rest_to_opus_medium(self):
        self.assertEqual(routed([], "coding", 2, after=perf.AGY), "haiku-medium")
        self.assertEqual(routed([], "coding", 2, after="haiku-medium"), "opus-medium")
        self.assertEqual(routed([], "coding", 3, after=perf.AGY), "opus-medium")
        self.assertEqual(routed([], "audit", 3, after=perf.AGY), "haiku-medium")

    def test_cycle_work_harness_work_and_hard_coding_start_on_opus_medium(self):
        self.assertEqual(routed([], "coding", 3, cycle=True), "opus-medium")
        self.assertEqual(routed([], "harness-build", 2), "opus-medium")
        self.assertEqual(routed([], "harness-fix", 3), "opus-medium")
        self.assertEqual(routed([], "coding", 4.5), "opus-medium")
        self.assertEqual(routed([], "coding", 3, cycle=True, after="opus-medium"), "opus-high")

    def test_sonnet_and_deepseek_never_build(self):
        for c, cycle in ((2, False), (3, False), (3, True), (5, False)):
            tier, seen = routed([], "coding", c, cycle=cycle), []
            while tier not in seen:
                seen.append(tier)
                tier = routed([], "coding", c, cycle=cycle, after=list(seen))
            self.assertFalse({"sonnet-high", "deepseek-high"} & set(seen), seen)

    def test_other_work_keeps_its_ladder(self):
        self.assertEqual(routed([], "bug-diagnosis", 2), "hydrogen-high")
        self.assertEqual(routed([], "bug-diagnosis", 4.5), "sonnet-high")
        self.assertEqual(routed([], "bug-diagnosis", 2, after="sonnet-medium"), "sonnet-high")
        self.assertEqual(routed([], "audit", 4.5), "hydrogen-high")
        self.assertEqual(routed([], "cleanup", 4.5), "hydrogen-high")
        self.assertEqual(routed([], "cleanup", 3, cycle=True), "hydrogen-high")

    def test_neon_is_on_trial_for_building_and_audits_only(self):
        hydrogen_ran = [row("hydrogen", "high", "bug-diagnosis", 2), row("hydrogen", "high", "device-run", 3)]
        self.assertEqual(routed(hydrogen_ran, "bug-diagnosis", 2), "hydrogen-high")
        self.assertEqual(routed(hydrogen_ran, "device-run", 3, after="hydrogen-high"), "sonnet-high")

    def test_merges_stay_on_claude(self):
        self.assertEqual(routed([], "merge", 2), "haiku-medium")
        self.assertEqual(routed([], "merge", 3), "sonnet-high")

    def test_after_a_retired_tier_a_low_merge_never_drops_below_it(self):
        self.assertEqual(routed([], "merge", 2, after="sonnet-medium"), "sonnet-high")
        self.assertEqual(routed([], "merge", 2, after="deepseek-high"), "haiku-medium")

    def test_gemini_rows_key_to_their_tiers(self):
        self.assertEqual(perf.tier(f"{perf.MODELS['neon']}/medium"), "neon-medium")
        self.assertEqual(perf.tier(f"{perf.MODELS['hydrogen']}/medium"), "hydrogen-medium")


class Stats(unittest.TestCase):
    def test_stats_prints_every_table(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            perf.stats([dict(row("hydrogen", "high"), platform="ios", escalated_from="neon-medium", ktok=10)], SimpleNamespace(type=None))
        for title in ("By tier", "By type x tier", "By platform x tier", "By complexity x tier"):
            self.assertIn(title, out.getvalue())


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
