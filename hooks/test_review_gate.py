import json, os, subprocess, sys, tempfile, unittest

GATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_gate.py")
SETTINGS = os.path.expanduser("~/.claude/settings.json")


class ReviewGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.transcript = os.path.join(self.tmp.name, "session.jsonl")
        self.subagents = os.path.join(self.tmp.name, "session", "subagents")
        os.makedirs(self.subagents)
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        git = lambda *a: subprocess.run(["git", "-C", self.repo, *a], check=True, capture_output=True)
        git("init", "-q")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
        self.sha = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def run_gate(self, tool, tool_input, env=None):
        hook_input = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
                      "cwd": self.repo, "transcript_path": self.transcript}
        p = subprocess.run([sys.executable, GATE], input=json.dumps(hook_input),
                           capture_output=True, text=True, env=dict(os.environ, **(env or {})))
        return p.returncode, p.stderr

    def reviewer(self, agent_type, report, finished=True, handback=False):
        """A reviewer agent's two files, as Claude Code writes them."""
        self.n += 1
        base = os.path.join(self.subagents, f"agent-{self.n}")
        meta = {"agentType": agent_type}
        if finished:
            meta["finished"] = True
        with open(base + ".meta.json", "w") as f:
            json.dump(meta, f)
        part = ({"type": "tool_use", "name": "SubagentHandback", "input": {"message": report}} if handback
                else {"type": "text", "text": report})
        with open(base + ".jsonl", "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [part]}}) + "\n")

    def clean(self, sha=None, extra=""):
        return f"All good.\n\nREVIEW CLEAN\ncommit: {sha or self.sha}\nrepo: {self.repo}\n{extra}"

    def other_branch(self):
        """Branch `other` with a commit of its own, in a git worktree beside the session's folder."""
        self.other = os.path.join(self.tmp.name, "other")
        subprocess.run(["git", "-C", self.repo, "worktree", "add", "-q", "-b", "other", self.other],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", self.other, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                        "--allow-empty", "-m", "y"], check=True, capture_output=True)
        return subprocess.run(["git", "-C", self.other, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()

    def create(self, command, env=None):
        return self.run_gate("Bash", {"command": command}, env)[0]

    # Mistake caught: a PR opens with no review at all.
    def test_pr_create_blocked_without_review(self):
        code, err = self.run_gate("Bash", {"command": "gh pr create --fill"})
        self.assertEqual(code, 2)
        self.assertIn("pr-reviewer", err)

    # Mistake caught: the gate blocks a PR after a clean review of this commit.
    def test_pr_create_allowed_after_clean_review(self):
        self.reviewer("pr-reviewer", self.clean())
        code, err = self.run_gate("Bash", {"command": "gh pr create --fill"})
        self.assertEqual(code, 0, err)

    # Mistake caught: a reviewed branch in a worktree cannot be opened from the main checkout.
    def test_head_branch_is_the_commit_checked(self):
        self.reviewer("pr-reviewer", self.clean(sha=self.other_branch()))
        for head in ("--head other", "-H other", "--head=other", "-dH other", "--head Juan23:other"):
            command = f'gh pr create -R o/r --base main {head} --title "a; b" --body-file /tmp/b.md'
            code, err = self.run_gate("Bash", {"command": command})
            self.assertEqual(code, 0, f"{head}: {err}")

    # Mistake caught: --head opens a branch nobody reviewed, because the session's own HEAD was reviewed.
    def test_unreviewed_head_branch_blocks(self):
        other = self.other_branch()
        self.reviewer("pr-reviewer", self.clean())
        code, err = self.run_gate("Bash", {"command": "gh pr create --head other --fill"})
        self.assertEqual(code, 2)
        self.assertIn(other, err)

    # Mistake caught: a --head branch the gate cannot find falls back to the session's reviewed HEAD.
    def test_unknown_head_branch_blocks(self):
        self.reviewer("pr-reviewer", self.clean())
        code, err = self.run_gate("Bash", {"command": "gh pr create --head nope --fill"})
        self.assertEqual(code, 2)
        self.assertIn("nope", err)

    # Mistake caught: text that only looks like --head (another flag's value) picks the reviewed branch,
    # while gh opens the session's unreviewed one.
    def test_head_inside_another_flags_value_does_not_count(self):
        self.reviewer("pr-reviewer", self.clean(sha=self.other_branch()))
        self.assertEqual(self.create("gh pr create --title --head=other"), 2)
        self.assertEqual(self.create("gh pr create -t -H other"), 2)

    # Mistake caught: `cd <worktree> && gh pr create` is checked against the session's folder.
    def test_leading_cd_is_the_folder_checked(self):
        self.reviewer("pr-reviewer", self.clean(sha=self.other_branch()))
        self.assertEqual(self.create(f"cd {self.other} && gh pr create --fill"), 0)
        self.assertEqual(self.create(f"cd {self.other}; gh pr create --fill"), 0)
        self.assertEqual(self.create("cd ../other && gh pr create --fill"), 0)
        self.assertEqual(self.create("cd ~/other && gh pr create --fill", {"HOME": self.tmp.name}), 0)

    # Mistake caught: the session's reviewed HEAD lets `cd <unreviewed worktree> && gh pr create` through.
    def test_leading_cd_to_unreviewed_folder_blocks(self):
        self.other_branch()
        self.reviewer("pr-reviewer", self.clean())
        self.assertEqual(self.create(f"cd {self.other} && gh pr create --fill"), 2)

    # Mistake caught: a cd that gh does not run under (a subshell, a later cd back) picks the reviewed folder.
    def test_cd_that_does_not_reach_gh_does_not_count(self):
        self.reviewer("pr-reviewer", self.clean(sha=self.other_branch()))
        self.assertEqual(self.create(f"(cd {self.other}) ; gh pr create --fill"), 2)
        self.assertEqual(self.create(f"cd {self.other} && cd {self.repo} && gh pr create --fill"), 2)

    # Mistake caught: only the first gh pr create of a command is checked.
    def test_every_create_in_a_command_is_checked(self):
        self.reviewer("pr-reviewer", self.clean(sha=self.other_branch()))
        self.assertEqual(self.create("gh pr create --head other --fill && gh pr create --fill"), 2)
        self.assertEqual(self.create("gh pr create --head other --fill\ngh pr create --fill"), 2)

    # Mistake caught: a reviewed PR whose body is a here-document (with an apostrophe) is refused as unreadable.
    def test_heredoc_body_after_reviewed_create_passes(self):
        self.reviewer("pr-reviewer", self.clean())
        for command in ("gh pr create --title \"The slider's result\" --body-file - <<'EOF'\nIt's done.\nEOF",
                        "gh pr create --title t --body \"$(cat <<'EOF'\nIt's done.\nEOF\n)\""):
            code, err = self.run_gate("Bash", {"command": command})
            self.assertEqual(code, 0, f"{command}: {err}")

    # Mistake caught: a command the gate cannot read opens a PR unchecked.
    def test_unreadable_create_command_blocks(self):
        self.reviewer("pr-reviewer", self.clean())
        self.assertEqual(self.create('gh pr create --title "x'), 2)

    # Mistake caught: the report handed back with SubagentHandback is not read (seen live on 2.1.318).
    def test_handback_report_is_read(self):
        self.reviewer("pr-reviewer", self.clean(), handback=True)
        self.assertEqual(self.run_gate("Bash", {"command": "gh pr create"})[0], 0)

    # Mistake caught: a review with findings counts.
    def test_findings_do_not_count(self):
        self.reviewer("pr-reviewer", f"REVIEW FINDINGS\ncommit: {self.sha}\nrepo: {self.repo}\n- bug")
        self.assertEqual(self.run_gate("Bash", {"command": "gh pr create"})[0], 2)

    # Mistake caught: a report that has both a clean line and a findings block counts as clean.
    def test_report_with_both_markers_does_not_count(self):
        self.reviewer("pr-reviewer", self.clean() + "\nREVIEW FINDINGS\n- bug")
        self.assertEqual(self.run_gate("Bash", {"command": "gh pr create"})[0], 2)

    # Mistake caught: a review of an older commit counts for new code.
    def test_review_of_other_commit_does_not_count(self):
        self.reviewer("pr-reviewer", self.clean(sha="0" * 40))
        self.assertEqual(self.run_gate("Bash", {"command": "gh pr create"})[0], 2)

    # Mistake caught: a commit line quoted above the clean block is read as the reviewed commit.
    def test_commit_is_read_only_from_the_clean_block(self):
        self.reviewer("pr-reviewer", f"Quoted from an older report:\ncommit: {self.sha}\n\n" + self.clean(sha="0" * 40))
        self.assertEqual(self.run_gate("Bash", {"command": "gh pr create"})[0], 2)

    # Mistake caught: "REVIEW CLEAN" inside a sentence above the block decides which commit is read.
    def test_clean_words_in_prose_do_not_move_the_block(self):
        self.reviewer("pr-reviewer", f"Round 1 ended REVIEW CLEAN too, for\ncommit: {'0' * 40}\n\n" + self.clean())
        self.assertEqual(self.run_gate("Bash", {"command": "gh pr create"})[0], 0)

    # Mistake caught: the working agent signs off its own work.
    def test_other_agent_types_do_not_count(self):
        self.reviewer("general-purpose", self.clean())
        self.reviewer("merge-reviewer", self.clean(extra="issues: none\n"))
        self.assertEqual(self.run_gate("Bash", {"command": "gh pr create"})[0], 2)

    # Mistake caught: a reviewer still running signs off the work.
    def test_unfinished_reviewer_does_not_count(self):
        self.reviewer("pr-reviewer", self.clean(), finished=False)
        self.assertEqual(self.run_gate("Bash", {"command": "gh pr create"})[0], 2)

    # Mistake caught: with no transcript path, reviewer files in the repository are trusted.
    def test_missing_transcript_path_blocks(self):
        self.reviewer("pr-reviewer", self.clean())
        # Run from the folder that holds subagents/, where an empty path would lead the search.
        p = subprocess.run([sys.executable, GATE], capture_output=True, text=True,
                           cwd=os.path.dirname(self.subagents), input=json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "gh pr create"}, "cwd": self.repo}))
        self.assertEqual(p.returncode, 2)

    # Mistake caught: a worker agent's own transcript path hides the session's reviewers.
    def test_worker_agent_transcript_finds_reviewers(self):
        self.reviewer("pr-reviewer", self.clean())
        self.transcript = os.path.join(self.subagents, "agent-worker.jsonl")
        self.assertEqual(self.run_gate("Bash", {"command": "gh pr create"})[0], 0)

    # Mistake caught: the gate blocks unrelated commands.
    def test_other_commands_pass(self):
        self.assertEqual(self.run_gate("Bash", {"command": "gh pr view 3"})[0], 0)
        self.assertEqual(self.run_gate("Bash", {"command": "gh pr create --help"})[0], 0)
        self.assertEqual(self.run_gate("Bash", {"command": "echo $(date); gh pr merge --help | grep -i alias"})[0], 0)

    # Mistake caught: a merge goes through with no ponytail review.
    # REVIEW_GATE_PR_SHA stands in for the gh lookup of the PR's head commit.
    def test_pr_merge_blocked_without_review(self):
        code, err = self.run_gate("Bash", {"command": "gh pr merge 7 --squash"}, {"REVIEW_GATE_PR_SHA": self.sha})
        self.assertEqual(code, 2)
        self.assertIn("ponytail-review", err)

    # Mistake caught: a merge review with no issues line (unrelated findings not stated) counts.
    def test_pr_merge_needs_issues_line(self):
        self.reviewer("merge-reviewer", self.clean())
        self.assertEqual(self.run_gate("Bash", {"command": "gh pr merge 7"}, {"REVIEW_GATE_PR_SHA": self.sha})[0], 2)

    # Mistake caught: the gate blocks a merge after a clean merge review.
    def test_pr_merge_allowed_after_clean_review(self):
        self.reviewer("merge-reviewer", self.clean(extra="issues: https://github.com/o/r/issues/9\n"))
        self.assertEqual(self.run_gate("Bash", {"command": "gh pr merge 7"}, {"REVIEW_GATE_PR_SHA": self.sha})[0], 0)

    # Mistake caught: the gate itself can be deleted or rewritten.
    def test_gate_files_are_protected(self):
        installed = os.path.expanduser("~/.claude/hooks/review_gate.py")
        self.assertEqual(self.run_gate("Bash", {"command": f"rm {installed}"})[0], 2)
        self.assertEqual(self.run_gate("Write", {"file_path": installed, "content": ""})[0], 2)
        self.assertEqual(self.run_gate("Edit", {"file_path": installed, "old_string": "a", "new_string": "b"})[0], 2)
        self.assertEqual(self.run_gate("Bash", {"command": f"python3 {installed} < x"})[0], 0)

    # Mistake caught: the hook entry is removed from settings.json.
    def test_settings_entry_is_protected(self):
        self.assertEqual(self.run_gate("Write", {"file_path": SETTINGS, "content": "{}"})[0], 2)
        self.assertEqual(self.run_gate("Edit", {"file_path": SETTINGS,
            "old_string": '"command": "python3 review_gate.py"', "new_string": ""})[0], 2)
        self.assertEqual(self.run_gate("Edit", {"file_path": SETTINGS,
            "old_string": '"theme": "auto"', "new_string": '"theme": "dark"'})[0], 0)
        self.assertEqual(self.run_gate("Bash", {"command": f"jq . {SETTINGS} > /tmp/s && mv /tmp/s {SETTINGS}"})[0], 2)

    # Mistake caught: a command that only reads a protected file is blocked because it also writes
    # somewhere else (stderr to /dev/null, a copy in /tmp). Seen live 39 times on 2026-11-14/15.
    def test_reading_protected_files_passes(self):
        gate = "~/.claude/hooks/review_gate.py"
        for command in (f"grep -n review_gate {SETTINGS} 2>/dev/null",
                        "ls ~/.claude/hooks/ 2>/dev/null; jq -c .hooks ~/.claude/settings.json",
                        f"cat {SETTINGS} > /tmp/settings-copy.json",
                        f"cp {gate} /tmp/gate-copy.py",
                        f"jq .hooks {SETTINGS} | tee /tmp/hooks.json",
                        f"sed -n 1,20p {gate} >> /tmp/notes.txt",
                        f"cp {gate} /tmp/scratch/review_gate.py"):
            self.assertEqual(self.create(command), 0, command)

    # Mistake caught: a shell write into a protected file passes now that reads are let through.
    def test_shell_writes_to_protected_files_block(self):
        gate = "~/.claude/hooks/review_gate.py"
        for command in (f"echo {{}} > {SETTINGS}",
                        f"jq . /tmp/s 2>/dev/null >> ~/.claude/settings.json",
                        f"sed -i '' s/a/b/ {SETTINGS}",
                        f"cp /tmp/x.py {gate}",
                        "cp /tmp/settings.json ~/.claude/",
                        f"mv {SETTINGS} /tmp/old.json",
                        f"sudo rm -f {gate}",
                        f"jq . /tmp/s | tee {SETTINGS} 2>&1",
                        "find ~/.claude/hooks -name review_gate.py -delete",
                        "cd ~/.claude && cp /tmp/s settings.json",
                        "cd ~/.claude/hooks && rm review_gate.py",
                        "D=~/.claude/hooks; cp /tmp/x.py ${D}/review_gate.py",
                        "cp /tmp/x.py $UNKNOWN/review_gate.py"):
            self.assertEqual(self.create(command), 2, command)

    # Mistake caught: a command that only mentions gh pr create or merge (a search, a script, a note)
    # is checked as if it opened or merged a pull request. Seen live on 2026-11-15.
    def test_text_that_mentions_pr_commands_passes(self):
        for command in ('grep -rn "gh pr create" docs',
                        "cat <<'EOF' > /tmp/s.py\nimport re\nhit = re.search(r'\\bgh pr create\\b', s)  # don't\nEOF",
                        "cat <<EOF > notes.md\nRun gh pr create, then gh pr merge 7 later.\nEOF",
                        'echo "next: gh pr merge 7"'):
            code, err = self.run_gate("Bash", {"command": command})
            self.assertEqual(code, 0, f"{command}: {err}")

    # Mistake caught: a real gh pr create or merge behind a wrapper or inside a shell string goes unchecked.
    def test_wrapped_pr_commands_are_checked(self):
        for command in ('bash -c "gh pr create --fill"',
                        "GH_TOKEN=x gh pr create --fill",
                        "timeout 60 gh pr create --fill",
                        "bash <<'EOF'\ngh pr create --fill\nEOF"):
            self.assertEqual(self.create(command), 2, command)
        self.assertEqual(self.create("env gh pr merge 7", {"REVIEW_GATE_PR_SHA": self.sha}), 2)

    # Mistake caught: a write or a gh call in a common shell shape (stderr redirect, if/for/{ } block,
    # bash -lc, a here-document piped to a shell, xargs, find -exec) goes unchecked.
    def test_common_shell_shapes_are_still_checked(self):
        gate, merge = "~/.claude/hooks/review_gate.py", {"REVIEW_GATE_PR_SHA": self.sha}
        for command in (f"cp /tmp/x {SETTINGS} 2>/dev/null",
                        f"ln -sf /tmp/x {SETTINGS} 2>&1",
                        f"cp /tmp/x.py {gate} 2>&1 | tail -1",
                        f"(echo x)>{SETTINGS}",
                        f"find ~/.claude/hooks -name review_gate.py | xargs rm -f",
                        f"echo {SETTINGS} | xargs rm",
                        "find ~/.claude/hooks -name review_gate.py -exec sed -i '' s/a/b/ {} +",
                        f"cat <<'EOF' | bash\nrm -f {gate}\nEOF",
                        "if true; then gh pr create --fill; fi",
                        "{ gh pr create --fill; }",
                        "bash -lc 'gh pr create --fill'",
                        "cat <<'EOF' | bash\ngh pr create --fill\nEOF",
                        "/opt/homebrew/bin/gh pr create --fill",
                        "URL=`gh pr create --fill`"):
            self.assertEqual(self.create(command), 2, command)
        for command in ("for p in 7; do gh pr merge $p --squash; done",
                        "gh pr merge 7 --squash && du -h ."):
            self.assertEqual(self.create(command, merge), 2, command)

    # Mistake caught: a shell form the gate does not read fully (command substitution, a redirect first,
    # a shell string, a pattern, xargs, export, git rm, a script run later) escapes the word match.
    def test_forms_the_gate_does_not_read_keep_the_word_match(self):
        merge = {"REVIEW_GATE_PR_SHA": self.sha}
        for command in ('URL="$(gh pr create --fill)"',
                        'echo "$(rm ~/.claude/settings.json)"',
                        ">/dev/null rm ~/.claude/settings.json",
                        "bash -c 'rm ~/.claude/settings.json'",
                        "rm ~/.claude/hooks/review_gate*",
                        "find ~/.claude/hooks -name review_gate.py | xargs -I {} rm {}",
                        "export F=~/.claude/settings.json; rm $F",
                        "git -C ~/.claude/hooks rm review_gate.py",
                        "cat <<'EOF' > /tmp/s.sh\nrm ~/.claude/settings.json\nEOF\nbash /tmp/s.sh",
                        'echo "a <<EOF"\nrm ~/.claude/settings.json',
                        "ln -s ~/.claude/settings.json /tmp/lnk; echo x > /tmp/lnk",
                        "ssh host gh pr create --fill"):
            self.assertEqual(self.create(command), 2, command)
        self.assertEqual(self.create("echo 7 | xargs -I {} gh pr merge {} --squash", merge), 2)

    # Mistake caught: a form outside the allowlist is read as plain and lets a real write or create through
    # (quoted operators, an expanding here-document, ~user, a cd that may fail, a short-lived variable,
    # a parent folder, find, a writer not on the list, a runner the gate does not know).
    def test_forms_outside_the_allowlist_are_not_read_as_plain(self):
        gate = "~/.claude/hooks/review_gate.py"
        for command in (f"rm ';' {gate}",
                        f"cat <<EOF\n$(rm {gate})\nEOF",
                        "cat <<EOF\n$(gh pr create --fill)\nEOF",
                        f"echo hi # <<EOF\nrm {gate}\nEOF",
                        f"cat <<EOF-X\nEOF-X\nrm {gate}\nEOF",
                        "rm ~juan/.claude/hooks/review_gate.py",
                        "cd ~/.claude/hooks || cd /tmp; rm review_gate.py",
                        "cd ~/.claude/hooks; cd /tmp; cd -; rm review_gate.py",
                        "D=~/.claude/hooks; D=/tmp true; rm $D/review_gate.py",
                        "X=1; rm ${X:+~}/.claude/hooks/review_gate.py",
                        "mv ~/.claude/hooks /tmp/review_gate_old",
                        "cat ~/.claude/settings.json; rm -rf ~/.claude",
                        "find ~/.claude -name review_gate.py -delete 2>/dev/null",
                        f"dd if=/tmp/evil of={os.path.expanduser(gate)} 2>/dev/null",
                        f"sed -n 'w {os.path.expanduser(gate)}' /tmp/evil 2>/dev/null",
                        f"ksh -c 'rm {gate}'",
                        "trap 'gh pr create --fill' EXIT",
                        "gh pr create --title --help --body x"):
            self.assertEqual(self.create(command), 2, command)

    # Mistake caught: shell details the allowlist must refuse let a real write or gh call through
    # (a word that is part quoted, zsh >!, a quote opened on an earlier line, assignments, a cd through
    # a link or one that failed, a path after --, a gh download, gh flags or quotes before the subcommand).
    def test_shell_details_are_not_read_as_plain(self):
        gate, merge = os.path.expanduser("~/.claude/hooks/review_gate.py"), {"REVIEW_GATE_PR_SHA": self.sha}
        for command in (f"rm -f '{gate[:-3]}'.py",
                        f"echo x >! {gate}",
                        f'echo "\n<<A "\nrm -f {gate}\nA',
                        'echo "\n<<A "\ngh pr create --fill\nA',
                        f"'HOME=/tmp'; rm -f $HOME/.claude/hooks/review_gate.py",
                        "HOME=/tmp | rm -f $HOME/.claude/hooks/review_gate.py",
                        f"HOME={os.path.expanduser('~/.claude')}; rm -f ~/hooks/review_gate.py",
                        "cd ~/jjitems/.. && rm -f .claude/hooks/review_gate.py",
                        "cd /nonexistent && true || rm -f ../../.claude/hooks/review_gate.py",
                        "mkdir -- -x && rm -f -- -x/" + "../" * 40 + gate.lstrip("/"),
                        f"gh release download v1 -R o/r -p a -O {gate} --clobber && echo cp"):
            self.assertEqual(self.create(command), 2, command)
        for command in ("gh pr 'm'erge 5", "gh -R o/r pr merge 5"):
            self.assertEqual(self.create(command, merge), 2, command)

    # Mistake caught: a settings file written with the Edit or Write tool turns every hook off.
    def test_settings_cannot_turn_hooks_off(self):
        local = os.path.join(self.repo, ".claude", "settings.local.json")
        os.makedirs(os.path.dirname(local))
        with open(local, "w") as f:
            f.write("{}")
        self.assertEqual(self.run_gate("Write", {"file_path": local, "content": '{"disableAllHooks": true}'})[0], 2)
        self.assertEqual(self.run_gate("Edit", {"file_path": local, "old_string": "{",
                                                "new_string": '{"disableAllHooks": true,'})[0], 2)
        self.assertEqual(self.run_gate("Write", {"file_path": local, "content": '{"env": {}}'})[0], 0)
        upper = os.path.join(self.repo, ".claude", "Settings.Local.json")
        self.assertEqual(self.run_gate("Write", {"file_path": upper, "content": '{"disable\\u0041llHooks": true}'})[0], 2)
        with open(local, "w") as f:
            f.write('{"disableAll_Hooks": true}')
        self.assertEqual(self.run_gate("Edit", {"file_path": local, "old_string": "All_Hooks",
                                                "new_string": "AllHooks"})[0], 2)

    # Mistake caught: the gate's files are replaced through a name the disk folds to theirs.
    def test_gate_files_are_protected_in_any_case(self):
        for name in ("~/.claude/hooks/Review_Gate.py", "~/.claude/hookſ/review_gate.py"):
            self.assertEqual(self.run_gate("Write", {"file_path": os.path.expanduser(name), "content": ""})[0], 2, name)
        self.assertEqual(self.run_gate("Write", {"file_path": os.path.expanduser("~/.claude/Settings.json"),
                                                 "content": "{}"})[0], 2)
        for command in ("rm ~/.claude/hookſ/review_gate.py",
                        "cat <<EOF; echo \"\n\" ; rm ~/.claude/hooks/review_gate.py ; echo \"\nEOF\n\"",
                        "cd /nonexistent && true ; rm ../../.claude/hooks/review_gate.py"):
            self.assertEqual(self.create(command), 2, command)

    # Mistake caught: a write outside ~/.claude (another settings.json, a copy of the gate) is blocked.
    def test_writes_elsewhere_pass(self):
        for command in ('cp /tmp/a "$WORKTREE/settings.json"',
                        "cd ~/Projects/x && jq .a .claude/settings.json > t && mv t .claude/settings.json",
                        f"cp {SETTINGS} .",
                        "cp ~/.claude/hooks/review_gate.py review_gate.py",
                        "cat > ship.sh <<'EOF'\ngh pr create --fill\nEOF"):
            code, err = self.run_gate("Bash", {"command": command})
            self.assertEqual(code, 0, f"{command}: {err}")


if __name__ == "__main__":
    unittest.main()
