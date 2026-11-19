#!/bin/bash
# Kills the command's whole process tree at the limit or on TERM: opencode's server runs in its own process group. `timeout` is not on every Mac.
exec perl -e '
  sub tree { map { ($_, tree($_)) } split " ", `pgrep -P $_[0]` }
  sub stop { my @t = tree($pid); kill "KILL", -$pid, @t; }
  my $secs = shift;
  our $pid = fork() // exit 1;
  if ($pid == 0) { setpgrp(0, 0); exec @ARGV or exit 127; }
  $SIG{TERM} = $SIG{HUP} = sub { stop(); exit 143; };
  local $SIG{ALRM} = sub { stop(); waitpid($pid, 0); exit 142; };
  alarm $secs;
  waitpid($pid, 0);
  exit($? & 127 ? 128 + ($? & 127) : $? >> 8);
' "$@"
