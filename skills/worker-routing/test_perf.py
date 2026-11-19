#!/usr/bin/env python3
"""Run: python3 ~/.claude/skills/worker-routing/test_perf.py"""
import json, os, subprocess, sys, tempfile, unittest

PERF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perf.py")


class Route(unittest.TestCase):
    def setUp(self):
        fd, self.log = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)

    def tearDown(self):
        os.unlink(self.log)

    def run_perf(self, *args):
        p = subprocess.run([sys.executable, PERF, "--log", self.log, *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def route(self, *args):
        return self.run_perf("route", *args).splitlines()[0]

    def add(self, model, effort, outcome, complexity="3"):
        self.run_perf("add", "--model", model, "--effort", effort, "--type", "coding", "--task", f"t-{model}-{outcome}",
                      "--complexity", complexity, "--outcome", outcome, "--blocker", "none", "--attempts", "0",
                      "--interventions", "0", "--ktok", "10", "--note", "x")

    def test_low_complexity_starts_at_deepseek(self):
        self.assertIn("route: deepseek-high", self.route("--type", "bug-diagnosis", "--complexity", "3"))

    def test_high_complexity_floor_is_still_sonnet_high(self):
        self.assertIn("route: sonnet-high", self.route("--type", "coding", "--complexity", "4"))

    def test_after_argon_goes_to_sonnet_high(self):
        self.assertIn("route: sonnet-high", self.route("--type", "coding", "--complexity", "3", "--after", "argon-medium"))

    def test_after_retired_sonnet_medium_goes_to_sonnet_high(self):
        self.assertIn("route: sonnet-high", self.route("--type", "coding", "--complexity", "3", "--after", "sonnet-medium"))

    def test_weak_deepseek_steps_to_hydrogen(self):
        self.add("deepseek", "high", "fail")
        self.add("deepseek", "high", "fail")
        self.assertIn("route: hydrogen-medium", self.route("--type", "coding", "--complexity", "3"))

    def test_add_records_gemini_model_names(self):
        self.add("argon", "medium", "pass")
        with open(self.log) as f:
            self.assertEqual(json.loads(f.readline())["model"], "argon-4")


if __name__ == "__main__":
    unittest.main()
