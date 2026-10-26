#!/bin/bash
# Usage: run-ship.sh <log> <claude args...>
# Runs one headless ship turn, appending its stream-json output to <log>. A hung
# turn would never wake the shipmaster, so it is killed after SHIP_IDLE_SECONDS
# (default 7200) without new output, and the script exits 124.
# Job control (-m) gives the turn its own process group, so a kill also reaches
# the tools it started, such as a merge gate or a device run.
set -um
log=$1; shift
idle=${SHIP_IDLE_SECONDS:-7200}
tick=${SHIP_TICK_SECONDS:-30}
: >> "$log"
# CLAUDECODE is unset because claude refuses to start inside another session.
env -u CLAUDECODE claude -p --output-format stream-json --verbose "$@" >> "$log" 2>&1 &
pid=$!
stop() { kill -- -"$pid" 2>/dev/null; wait "$pid" 2>/dev/null; }
trap 'stop; exit 143' TERM INT HUP
while kill -0 "$pid" 2>/dev/null; do
  sleep "$tick"
  if [ $(( $(date +%s) - $(date -r "$log" +%s) )) -ge "$idle" ]; then
    stop
    echo "run-ship: no output for ${idle}s, stopped" >> "$log"
    exit 124
  fi
done
wait "$pid"
