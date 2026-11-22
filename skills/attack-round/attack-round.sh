#!/bin/bash
# Attack round: cheap read-only reviewers (DeepSeek attackers + agy Gemini) on the committed branch,
# alongside the Claude merge-reviewer. Finishes within twice the ping limit plus the time limit, with whatever arrived.
# Usage: attack-round.sh --base <ref> [--focus security,failure,timing] [--builder <tier>] [--out <dir>]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
OPENCODE_BIN="${OPENCODE_BIN:-opencode}"
AGY_BIN="${AGY_BIN:-agy}"
DS_MODEL="opencode-go/deepseek-v4.1-flash#high"
PRIMARY="gemini-4-hydrogen-high" # 4 min against 11.5 for Argon medium on the same review
BACKUP="gemini-4-argon-medium"
LIMIT="${ATTACK_LIMIT:-1200}"
PING_LIMIT="${PING_LIMIT:-120}"
MIN_RETRY_SECS=120 # alarm 0 would turn the limit off, and print-timeout needs 30 s of margin
TIMED_OUT=142 # exit status of a process killed by the perl alarm (128 + SIGALRM)

BASE="" FOCUS="security,failure,timing" OUT="" BUILDER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="$2"; shift 2;;
    --focus) FOCUS="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --builder) BUILDER="$2"; shift 2;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done
[ -n "$BASE" ] || { echo "usage: attack-round.sh --base <ref> [--focus a,b] [--builder tier] [--out dir]" >&2; exit 2; }
# A reviewer differs from the builder where it can, and Argon has its own quota. Hydrogen still reviews a Hydrogen build when nothing else answers.
case "$BUILDER" in hydrogen*|neon*) PRIMARY="$BACKUP" BACKUP="gemini-4-hydrogen-high";; esac
same_model_note() { # same_model_note <status> <text naming the model>: only a reviewer that answered counts
  [ -n "$BUILDER" ] || return 0
  case "$1" in done*) case "$2" in *"${BUILDER%%-*}"*) echo " - same model as the builder";; esac;; esac
}

REPO="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "not in a git repository" >&2; exit 2; }
git -C "$REPO" diff --quiet HEAD || { echo "commit your changes first: the round reviews a commit" >&2; exit 2; }
SHA="$(git -C "$REPO" rev-parse HEAD)"
git -C "$REPO" rev-parse --verify -q "$BASE^{commit}" >/dev/null || { echo "unknown base: $BASE" >&2; exit 2; }
OUT="${OUT:-${TMPDIR:-/tmp}/attack-round-${SHA:0:8}}"
mkdir -p "$OUT"
# A reused folder must not show an earlier run's outputs under this run's status lines.
rm -f "$OUT"/ds-*.md "$OUT"/ds-*.status "$OUT"/agy.md "$OUT"/agy.status "$OUT"/agy.denied "$OUT"/agy.model "$OUT"/*ping*.err
WT="$OUT/wt"

# Attackers may write files despite the prompt; a throwaway worktree keeps that away from the branch.
git -C "$REPO" worktree add -q --detach "$WT" "$SHA" || exit 2
cleanup() { git -C "$REPO" worktree remove --force "$WT" 2>/dev/null; }
trap cleanup EXIT
# opencode's default agent may edit and run any command; this project agent may only read inside the worktree,
# so it gets the diff as a file instead of running git.
mkdir -p "$WT/.opencode/agents" "$WT/.attack" && cp "$HERE/opencode-attacker.md" "$WT/.opencode/agents/attacker.md" || exit 2
git -C "$REPO" diff "$BASE..$SHA" > "$WT/.attack/diff.patch" && git -C "$REPO" log --format='%h %s' "$BASE..$SHA" > "$WT/.attack/commits.txt" || exit 2

# Runs a command in its own process group and kills the whole group at the limit, so opencode's child
# server cannot outlive it. `timeout` is not installed on every Mac; perl is. Closed stdin: opencode hangs on an open one.
limited() {
  local secs="$1"; shift
  perl -e '
    my $secs = shift;
    my $pid = fork() // exit 1;
    if ($pid == 0) { setpgrp(0, 0); exec @ARGV or exit 127; }
    $SIG{TERM} = $SIG{HUP} = sub { kill "KILL", -$pid; exit 143; };  # a stopped round must not leave the model running
    local $SIG{ALRM} = sub { kill "KILL", -$pid; waitpid($pid, 0); exit 142; };
    alarm $secs;
    waitpid($pid, 0);
    exit($? & 127 ? 128 + ($? & 127) : $? >> 8);
  ' "$secs" "$@" < /dev/null
}

common_prompt() { # bash substitution, not sed: a base such as origin/main breaks a sed pattern
  local text; text="$(cat "$HERE/prompts/common.md")"
  shopt -u patsub_replacement 2>/dev/null # bash 5.2+ would expand & in the base
  printf '%s\n' "${text//\{\{BASE\}\}/$BASE}"
}

prompt_for() { # prompt_for <focus>
  printf 'FOCUS: %s\n\n' "$1"
  common_prompt
  echo
  cat "$HERE/prompts/$1.md"
}

pinged() { # pinged <err file> <cmd...>: 0 on pong; a hung ping prints nothing, so its error file says so
  local err="$1" out code; shift
  out="$("$@" 2> "$err")"; code=$?
  [ "$code" = "$TIMED_OUT" ] && echo "no answer within ${PING_LIMIT}s" >> "$err"
  echo "$out" | grep -q pong
}
ds_ping() { (cd "$WT" && pinged "$OUT/ds-ping.err" limited "$PING_LIMIT" "$OPENCODE_BIN" run --standalone --format json --agent attacker -m "$DS_MODEL" "Reply with just: pong"); }
agy_ping_model() { pinged "$OUT/agy-ping-$1.err" limited "$PING_LIMIT" "$AGY_BIN" -p "Reply with just: pong" --model "$1" --print-timeout "${PING_LIMIT}s"; }
agy_ping() { # writes the first model that answers to agy.model; a primary that is down still leaves the backup
  local m
  for m in "$PRIMARY" "$BACKUP"; do agy_ping_model "$m" && { echo "$m" > "$OUT/agy.model"; return 0; }; done
  return 1
}

run_ds() { # run_ds <focus>: writes ds-<focus>.status and ds-<focus>.md
  local f="$1" log="$OUT/ds-$1.jsonl" code
  (cd "$WT" && limited "$LIMIT" "$OPENCODE_BIN" run --standalone --format json --agent attacker -m "$DS_MODEL" "$(prompt_for "$f")" > "$log" 2> "$OUT/ds-$f.err")
  code=$?
  # The last text event is the final answer; earlier ones are narration between tool calls.
  jq -rs 'map(select(.type == "text")) | last | .part.text // empty' "$log" 2>/dev/null > "$OUT/ds-$f.md"
  if [ "$code" = "$TIMED_OUT" ]; then echo timeout
  elif [ "$code" = 0 ] && tail -n 1 "$log" | jq -e '.type == "step_finish" and .part.reason == "stop"' >/dev/null 2>&1; then echo done
  else echo "failed (exit $code)"; fi > "$OUT/ds-$f.status"
}

DENIED=3 # agy_once: headless agy refused a tool, which ends its run with no answer

agy_once() { # agy_once <model> <seconds> [note]: 0 with the answer in agy.md, DENIED, TIMED_OUT, or another failure code
  # stream-json keeps each tool call in agy.jsonl, so a refused command can be named in the retry.
  (cd "$WT" && limited "$2" "$AGY_BIN" -p "$(common_prompt; echo; cat "$HERE/prompts/agy.md"; echo "${3:-}")" \
    --model "$1" --mode plan --print-timeout "$(($2 - 30))s" --output-format stream-json > "$OUT/agy.jsonl" 2> "$OUT/agy.err")
  local code=$? result
  [ "$code" = "$TIMED_OUT" ] && return "$code"
  grep -q 'print_timeout\|print timeout' "$OUT/agy.err" 2>/dev/null && return "$TIMED_OUT"
  result="$(grep '"event":"result"' "$OUT/agy.jsonl" | tail -n 1)"
  echo "$result" | jq -r '.result.response | select(. != null and . != "")' 2>/dev/null > "$OUT/agy.md"
  [ -s "$OUT/agy.md" ] && return 0
  echo "$result" | jq -r '.result.denied_actions // [] | map(.action) | unique | join(",")' 2>/dev/null > "$OUT/agy.denied"
  [ -s "$OUT/agy.denied" ] && return "$DENIED"
  [ "$code" = 0 ] && return 1
  return "$code"
}

run_agy() {
  # A timeout never retries; every retry gets only the time left.
  local code refused left started=$SECONDS first next=""
  first="$(cat "$OUT/agy.model")"
  [ "$first" = "$PRIMARY" ] && next="$BACKUP"
  agy_once "$first" "$LIMIT"; code=$?
  if [ "$code" = 0 ]; then echo "done ($first)" > "$OUT/agy.status"; return; fi
  if [ "$code" = "$TIMED_OUT" ]; then echo timeout > "$OUT/agy.status"; return; fi
  left=$((LIMIT - (SECONDS - started)))
  if [ "$code" = "$DENIED" ]; then
    refused="$(jq -r '.. | .CommandLine? // empty' "$OUT/agy.jsonl" 2>/dev/null | tail -n 1)"
    if [ "$left" -gt "$MIN_RETRY_SECS" ]; then
      agy_once "$first" "$left" "Your last run was stopped because this command was refused: ${refused:-unknown}. Do not use * or ? wildcards in shell commands; name folders instead, or use your built-in search tools."
      code=$?
      [ "$code" = 0 ] && { echo "done ($first, after a refused command)" > "$OUT/agy.status"; return; }
    fi
    case "$code" in
      "$TIMED_OUT") echo timeout;;
      "$DENIED") echo "failed (denied: $(cat "$OUT/agy.denied"))";;
      *) echo "failed (exit $code)";;
    esac > "$OUT/agy.status"
    return
  fi
  cp "$OUT/agy.err" "$OUT/agy-$first.err" 2>/dev/null
  if [ -z "$next" ]; then echo "failed ($first exit $code)" > "$OUT/agy.status"; return; fi
  if [ "$left" -le "$MIN_RETRY_SECS" ]; then echo "failed ($first exit $code, too little time left for $next)" > "$OUT/agy.status"; return; fi
  agy_once "$next" "$left"; code=$?
  if [ "$code" = 0 ]; then echo "done ($next, after $first failed)" > "$OUT/agy.status"
  elif [ "$code" = "$TIMED_OUT" ]; then echo timeout > "$OUT/agy.status"
  else echo "failed (exit $code)" > "$OUT/agy.status"; fi
}

FOCUSES="$(echo $FOCUS | tr ',' ' ' | xargs)" # xargs trims, so "," or " " leaves no focus
for f in $FOCUSES; do [ -f "$HERE/prompts/$f.md" ] || { echo "no prompt for focus: $f" >&2; exit 2; }; done

DS_UP=0
[ -n "$FOCUSES" ] && { ds_ping & DS_PING=$!; }
agy_ping & AGY_PING=$!
[ -n "$FOCUSES" ] && { wait "$DS_PING" && DS_UP=1; }
wait "$AGY_PING" && AGY_UP=1 || AGY_UP=0

for f in $FOCUSES; do
  if [ "$DS_UP" = 1 ]; then run_ds "$f" & else echo "skipped (ping failed, see ds-ping.err)" > "$OUT/ds-$f.status"; fi
done
if [ "$AGY_UP" = 1 ]; then run_agy & else echo "skipped (ping failed, see agy-ping-$PRIMARY.err and agy-ping-$BACKUP.err)" > "$OUT/agy.status"; fi
wait

{
  echo "# Attack round on ${SHA:0:8} (base $BASE)"
  echo
  for f in $FOCUSES; do s="$(cat "$OUT/ds-$f.status")"; echo "- deepseek-$f: $s$(same_model_note "$s" deepseek)"; done
  s="$(cat "$OUT/agy.status")"; echo "- agy: $s$(same_model_note "$s" "$s")"
  for f in $FOCUSES; do
    [ -s "$OUT/ds-$f.md" ] && { echo; echo "## deepseek-$f"; echo; cat "$OUT/ds-$f.md"; }
  done
  [ -s "$OUT/agy.md" ] && { echo; echo "## agy"; echo; cat "$OUT/agy.md"; }
} > "$OUT/findings.md"
sed '/^## /,$d' "$OUT/findings.md" | grep '^-\|^#'
echo "findings: $OUT/findings.md"
