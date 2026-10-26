#!/bin/bash
# Runs run-ship.sh against a fake claude: the ship default, argument pass-through, exit codes, and
# that the idle kill and a TERM both stop the turn and the processes it started.
set -u
dir=$(mktemp -d); trap 'rm -rf "$dir"' EXIT
run=$(dirname "$0")/run-ship.sh
cat > "$dir/claude" <<'FAKE'
#!/bin/bash
echo "args: $* CLAUDECODE=${CLAUDECODE:-unset}"
if [ -n "${FAKE_CHILD:-}" ]; then sleep 60 & echo $! > "$FAKE_CHILD"; fi
sleep "${FAKE_SLEEP:-0}"
exit "${FAKE_EXIT:-0}"
FAKE
chmod +x "$dir/claude"
export PATH="$dir:$PATH" SHIP_TICK_SECONDS=1 CLAUDECODE=1 SHIPMASTER_DEFAULTS="$dir/none"
fail() { echo "FAIL: $1"; exit 1; }
alive() { kill -0 "$(cat "$1")" 2>/dev/null; }

"$run" "$dir/a.log" --resume abc "hi there"; [ $? -eq 0 ] || fail "exit 0"
grep -q 'args: -p --output-format stream-json --verbose --model claude-opus-5-5 --effort medium --resume abc hi there CLAUDECODE=unset' "$dir/a.log" || fail "args with the built-in default"

printf 'model=claude-sonnet-5-5\neffort=high\n' > "$dir/defaults"
SHIPMASTER_DEFAULTS="$dir/defaults" "$run" "$dir/f.log" x; [ $? -eq 0 ] || fail "defaults file exit"
grep -q 'args: -p --output-format stream-json --verbose --model claude-sonnet-5-5 --effort high x' "$dir/f.log" || fail "defaults file"

printf 'effort=loud\n' > "$dir/bad"
SHIPMASTER_DEFAULTS="$dir/bad" "$run" "$dir/g.log" x 2>/dev/null; [ $? -eq 2 ] || fail "bad effort refused"
grep -q "run-ship: effort 'loud'" "$dir/g.log" || fail "bad effort reason in the log"
grep -q 'args:' "$dir/g.log" && fail "bad effort started a turn"

printf 'model=x;rm\n' > "$dir/bad2"
SHIPMASTER_DEFAULTS="$dir/bad2" "$run" "$dir/h.log" x 2>/dev/null; [ $? -eq 2 ] || fail "bad model refused"

FAKE_EXIT=3 "$run" "$dir/b.log" x; [ $? -eq 3 ] || fail "exit code pass-through"

start=$(date +%s)
FAKE_CHILD="$dir/c.pid" FAKE_SLEEP=30 SHIP_IDLE_SECONDS=2 "$run" "$dir/c.log" x; code=$?
[ $code -eq 124 ] || fail "idle kill exit $code"
[ $(( $(date +%s) - start )) -lt 10 ] || fail "idle kill too slow"
grep -q 'run-ship: no output for 2s, stopped' "$dir/c.log" || fail "idle kill note"
sleep 1; alive "$dir/c.pid" && fail "idle kill left a child running"

FAKE_SLEEP=3 SHIP_IDLE_SECONDS=10 "$run" "$dir/d.log" x; [ $? -eq 0 ] || fail "slow but under the limit"

FAKE_CHILD="$dir/e.pid" FAKE_SLEEP=30 "$run" "$dir/e.log" x & runner=$!
sleep 2; kill -TERM "$runner"; wait "$runner"; code=$?
[ $code -eq 143 ] || fail "TERM exit $code"
sleep 1; alive "$dir/e.pid" && fail "TERM left a child running"
echo "run-ship: all checks pass"
