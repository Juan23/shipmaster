#!/bin/bash
# Usage: run-ship.sh <log> <claude args...>
# Runs one headless ship turn, appending its stream-json output to <log>. A hung
# turn would never wake the shipmaster, so it is killed after SHIP_IDLE_SECONDS
# (default 7200) without new output, and the script exits 124.
# Job control (-m) gives the turn its own process group, so a kill also reaches
# the tools it started, such as a merge gate or a device run.
# Every turn runs on the ship model and effort in SHIPMASTER_DEFAULTS
# (default ~/.claude/shipmaster-defaults: model=<id>, effort=<level> lines),
# Opus 5.5 at medium where it names none.
set -um
log=$1; shift
idle=${SHIP_IDLE_SECONDS:-7200}
tick=${SHIP_TICK_SECONDS:-30}
defaults=${SHIPMASTER_DEFAULTS:-$HOME/.claude/shipmaster-defaults}
setting() { [ -f "$defaults" ] && sed -n "s/^$1=//p" "$defaults" | tail -1; }
model=$(setting model); model=${model:-claude-opus-5-5}
effort=$(setting effort); effort=${effort:-medium}
refuse() { echo "run-ship: $1" | tee -a "$log" >&2; exit 2; }
case "$effort" in low|medium|high|xhigh|max) ;; *) refuse "effort '$effort' in $defaults is not low, medium, high, xhigh or max" ;; esac
case "$model" in ''|*[!A-Za-z0-9._\[\]-]*) refuse "model '$model' in $defaults is not a model name" ;; esac
: >> "$log"
# CLAUDECODE is unset because claude refuses to start inside another session.
env -u CLAUDECODE claude -p --output-format stream-json --verbose --model "$model" --effort "$effort" "$@" >> "$log" 2>&1 &
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
