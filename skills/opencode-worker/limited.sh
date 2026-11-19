#!/bin/bash
# limited.sh <seconds> <command...>: runs the command in its own process group and kills the whole group
# at the limit or on TERM, so opencode's child server cannot outlive it. `timeout` is not on every Mac; perl is.
exec perl -e '
  my $secs = shift;
  my $pid = fork() // exit 1;
  if ($pid == 0) { setpgrp(0, 0); exec @ARGV or exit 127; }
  $SIG{TERM} = $SIG{HUP} = sub { kill "KILL", -$pid; exit 143; };
  local $SIG{ALRM} = sub { kill "KILL", -$pid; waitpid($pid, 0); exit 142; };
  alarm $secs;
  waitpid($pid, 0);
  exit($? & 127 ? 128 + ($? & 127) : $? >> 8);
' "$@"
