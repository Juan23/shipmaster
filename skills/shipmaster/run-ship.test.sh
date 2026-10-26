#!/bin/bash
# Runs run-ship.sh against a fake claude: argument pass-through, exit codes, and
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
export PATH="$dir:$PATH" SHIP_TICK_SECONDS=1 CLAUDECODE=1
fail() { echo "FAIL: $1"; exit 1; }
alive() { kill -0 "$(cat "$1")" 2>/dev/null; }

"$run" "$dir/a.log" --resume abc "hi there"; [ $? -eq 0 ] || fail "exit 0"
grep -q 'args: -p --output-format stream-json --verbose --resume abc hi there CLAUDECODE=unset' "$dir/a.log" || fail "args"

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
