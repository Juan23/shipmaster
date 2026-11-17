#!/bin/bash
# Tests attack-round.sh against fake opencode and agy binaries; no network, no real models.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/attack-round.sh"
FAILS=0
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

fail() { echo "FAIL: $1"; FAILS=$((FAILS + 1)); }
pass() { echo "ok: $1"; }

# Fake opencode: FAKE_DS = ok | hang | ping-fail. Answers pings with pong.
mkdir -p "$T/bin"
cat > "$T/bin/opencode" <<'EOF'
#!/bin/bash
prompt="${@: -1}"
if [[ "$prompt" == *"Reply with just: pong"* ]]; then
  [ "${FAKE_DS:-ok}" = ping-fail ] && { echo "Insufficient account funds" >&2; exit 1; }
  echo '{"type":"text","part":{"text":"pong"}}'; echo '{"type":"step_finish","part":{"reason":"stop"}}'; exit 0
fi
[[ " $* " == *" --agent attacker "* ]] && [ -f .opencode/agents/attacker.md ] && grep -q '^+b' .attack/diff.patch || { echo '{"type":"text","part":{"text":"ran without the read-only agent"}}'; exit 1; }
[ "${FAKE_DS:-ok}" = hang ] && sleep 37
focus=$(echo "$prompt" | sed -n 's/^FOCUS: //p')
echo '{"type":"step_start","part":{}}'
echo '{"type":"text","part":{"text":"Reading the diff first."}}'
range=$(echo "$prompt" | grep -o 'commit in [^ ]*\.\.HEAD' | head -n 1)
printf '{"type":"text","part":{"text":"DS finding for %s (%s)\\nScenario: two lines\\n- bullet inside finding\\nATTACK DONE"}}\n' "$focus" "$range"
echo '{"type":"step_finish","part":{"reason":"stop"}}'
EOF
# Fake agy (stream-json): FAKE_PRIMARY = ok | quota | quota-run | down | hang | print-timeout | denied | denied-once. The backup model always answers.
cat > "$T/bin/agy" <<'EOF'
#!/bin/bash
model=""; prompt=""
while [ $# -gt 0 ]; do
  case "$1" in --model) model="$2"; shift 2;; -p) prompt="$2"; shift 2;; *) shift;; esac
done
if [[ "$prompt" == *"Reply with just: pong"* ]]; then
  [ "$model" = gemini-4-hydrogen-high ] && [ "${FAKE_PRIMARY:-ok}" = quota ] && { echo 'AGY_ERROR: {"status":"RESOURCE_EXHAUSTED"}' >&2; exit 1; }
  [ "$model" = gemini-4-hydrogen-high ] && [ "${FAKE_PRIMARY:-ok}" = down ] && sleep 30
  echo pong; exit 0
fi
if [ "$model" = gemini-4-hydrogen-high ]; then
  case "${FAKE_PRIMARY:-ok}" in
    quota|quota-run) echo 'AGY_ERROR: {"status":"RESOURCE_EXHAUSTED"}' >&2; exit 1;;
    hang|down) sleep 30;;
    print-timeout) echo '{"event":"result","result":{"status":"ERROR","response":"","error":"print timeout after 14m30s"}}'
      echo 'AGY_ERROR: {"status":"DEADLINE_EXCEEDED","reason":"print_timeout"}' >&2; exit 1;;
    denied) echo '{"event":"result","result":{"status":"SUCCESS","response":"","denied_actions":[{"action":"command"}]}}'; exit 0;;
    denied-once)
      if [[ "$prompt" != *"was refused"* ]]; then
        echo '{"event":"step_update","step_update":{"tool_info":{"parameters":{"CommandLine":"git grep x dir/89*"}}}}'
        echo '{"event":"result","result":{"status":"SUCCESS","response":"","denied_actions":[{"action":"command"}]}}'; exit 0
      fi
      [[ "$prompt" == *"git grep x dir/89*"* ]] || { echo '{"event":"result","result":{"response":"retry did not name the refused command"}}'; exit 0; };;
  esac
fi
echo '{"event":"step_update","step_update":{"state":"DONE"}}'
printf '{"event":"result","result":{"status":"SUCCESS","response":"AGY finding from %s\\nsecond line"}}\n' "$model"
EOF
chmod +x "$T/bin/opencode" "$T/bin/agy"
export OPENCODE_BIN="$T/bin/opencode" AGY_BIN="$T/bin/agy"

R="$T/repo"
git init -q "$R" && cd "$R" || exit 1
git config user.email t@t && git config user.name t
echo a > f.txt && git add f.txt && git commit -qm base
echo b >> f.txt && git commit -qam change

run() { # run <name> [env...]: runs the script with a fresh output folder
  local name="$1"; shift
  env "$@" "$SCRIPT" --base HEAD~1 --focus security,timing --out "$T/out-$name" > "$T/$name.log" 2>&1
  echo $? > "$T/$name.exit"
}

run all-ok
F="$T/out-all-ok/findings.md"
grep -q "DS finding for security" "$F" && grep -q "DS finding for timing" "$F" && pass "both DeepSeek focuses reported" || fail "DeepSeek findings missing"
grep -q "AGY finding from gemini-4-hydrogen-high" "$F" && pass "the primary model reported" || fail "primary finding missing"
[ "$(cat "$T/all-ok.exit")" = 0 ] && pass "exit 0" || fail "exit $(cat "$T/all-ok.exit")"
[ -z "$(git -C "$R" worktree list | sed 1d)" ] && pass "throwaway worktree removed" || fail "worktree left behind"

start=$(date +%s)
run ds-hang FAKE_DS=hang ATTACK_LIMIT=3
took=$(( $(date +%s) - start ))
[ "$took" -lt 20 ] && pass "a hung attacker is cut off at the limit (${took}s)" || fail "hung attacker not cut off (${took}s)"
F="$T/out-ds-hang/findings.md"
grep -q "deepseek-security: timeout" "$F" && pass "hang reported as timeout" || fail "hang not reported as timeout"
pgrep -f "sleep 37" >/dev/null && fail "child processes of a timed-out attacker left running" || pass "a timed-out attacker leaves no child processes"
grep -q "AGY finding from gemini-4-hydrogen-high" "$F" && pass "other reviewers still reported" || fail "agy result lost when DeepSeek hung"

perl -e 'setpgrp(0, 0); exec @ARGV' env FAKE_DS=hang ATTACK_LIMIT=30 "$SCRIPT" --base HEAD~1 --focus security --out "$T/out-stopped" > /dev/null 2>&1 &
stopped=$!
sleep 3; kill -TERM -"$stopped"; sleep 2
pgrep -f "sleep 37" >/dev/null && fail "a stopped round left a reviewer running" || pass "stopping the round stops its reviewers"
wait "$stopped" 2>/dev/null

run primary-quota FAKE_PRIMARY=quota-run
F="$T/out-primary-quota/findings.md"
grep -q "AGY finding from gemini-4-argon-medium" "$F" && pass "a primary failure falls back to the backup model" || fail "no backup fallback"
run primary-no-quota FAKE_PRIMARY=quota
grep -q "agy: done (gemini-4-argon-medium)" "$T/out-primary-no-quota/findings.md" && pass "a primary out of quota at the ping goes straight to the backup" || fail "primary out of quota skipped agy"

start=$(date +%s)
run primary-down FAKE_PRIMARY=down PING_LIMIT=2 ATTACK_LIMIT=20
took=$(( $(date +%s) - start ))
grep -q "agy: done (gemini-4-argon-medium)" "$T/out-primary-down/findings.md" && [ "$took" -lt 15 ] && pass "a primary that hangs on its ping is skipped for the backup (${took}s)" || fail "hung primary still started (${took}s)"

run primary-hang FAKE_PRIMARY=hang ATTACK_LIMIT=3
F="$T/out-primary-hang/findings.md"
grep -q "agy: timeout" "$F" && ! grep -q "argon-medium" "$F" && pass "a primary timeout does not start the backup" || fail "primary timeout handling wrong"

grep -q "Scenario: two lines" "$T/out-all-ok/findings.md" && ! grep -q "Reading the diff first" "$T/out-all-ok/findings.md" && pass "the whole final DeepSeek answer is kept, narration dropped" || fail "DeepSeek answer cut or narration kept"
grep -q "bullet inside finding" "$T/out-all-ok/findings.md" && ! grep -q "bullet inside finding" "$T/all-ok.log" && pass "the printed summary shows status lines only" || fail "finding bullets leaked into the printed summary"
grep -q "second line" "$T/out-all-ok/findings.md" && pass "the whole agy answer is kept" || fail "agy answer cut"

run primary-quota-late FAKE_PRIMARY=quota-run ATTACK_LIMIT=100
grep -q "agy: failed (gemini-4-hydrogen-high exit 1, too little time left for gemini-4-argon-medium)" "$T/out-primary-quota-late/findings.md" && pass "no backup retry without enough time left" || fail "backup retried with too little time"

run primary-denied FAKE_PRIMARY=denied
F="$T/out-primary-denied/findings.md"
grep -q "agy: failed (denied: command)" "$F" && ! grep -q argon-medium "$F" && pass "a run refused twice is reported as failed, not done, and never goes to the backup" || fail "denied tool not reported"

run primary-print-timeout FAKE_PRIMARY=print-timeout
F="$T/out-primary-print-timeout/findings.md"
grep -q "agy: timeout" "$F" && ! grep -q argon-medium "$F" && pass "agy's own time limit counts as a timeout" || fail "agy's own time limit not reported as timeout"

run primary-denied-once FAKE_PRIMARY=denied-once
F="$T/out-primary-denied-once/findings.md"
grep -q "AGY finding from gemini-4-hydrogen-high" "$F" && grep -q "agy: done (gemini-4-hydrogen-high, after a refused command)" "$F" && pass "a refused command is retried once, naming the command" || fail "no retry after a refused command"

run ds-down FAKE_DS=ping-fail
F="$T/out-ds-down/findings.md"
grep -q "deepseek-security: skipped" "$F" && pass "failed ping skips DeepSeek" || fail "DeepSeek not skipped on failed ping"
grep -q "AGY finding" "$F" && pass "agy still runs when DeepSeek is down" || fail "agy did not run"

git branch -q base/x HEAD~1
"$SCRIPT" --base base/x --focus security --out "$T/out-slash" > /dev/null 2>&1
grep -q "commit in base/x..HEAD" "$T/out-slash/findings.md" && pass "a base with a slash reaches the prompt" || fail "base with a slash lost from the prompt"

"$SCRIPT" --base HEAD~1 --focus security --out "$T/out-reuse" > /dev/null 2>&1
env FAKE_DS=ping-fail FAKE_PRIMARY=hang ATTACK_LIMIT=3 "$SCRIPT" --base HEAD~1 --focus security --out "$T/out-reuse" > /dev/null 2>&1
F="$T/out-reuse/findings.md"
! grep -q "DS finding\|AGY finding" "$F" && pass "a reused output folder shows no earlier answers" || fail "earlier answers leaked into a reused folder"

echo c >> f.txt
run dirty
[ "$(cat "$T/dirty.exit")" = 2 ] && pass "uncommitted changes refused (exit 2)" || fail "dirty tree not refused"
git checkout -q f.txt

echo; [ "$FAILS" = 0 ] && echo "ALL PASSED" || { echo "$FAILS FAILED"; exit 1; }
