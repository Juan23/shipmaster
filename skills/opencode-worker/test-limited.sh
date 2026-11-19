#!/bin/bash
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT; fails=0
# The child moves to its own process group, as opencode's server does, and ends when its file is gone.
cat > "$T/leaves-child.sh" <<'EOF'
#!/bin/bash
perl -e 'setpgrp(0, 0); while (1) { open my $f, ">>", $ARGV[0] or exit; print $f "x\n"; close $f; select undef, undef, undef, 0.2 }' "$1" &
wait
EOF
chmod +x "$T/leaves-child.sh"
stopped() { local a b; sleep 1; a=$(wc -l < "$1"); sleep 1; b=$(wc -l < "$1"); [ "$a" = "$b" ]; }
check() { if "${@:2}"; then echo "ok: $1"; else echo "FAIL: $1"; fails=1; fi; }

"$HERE/limited.sh" 2 "$T/leaves-child.sh" "$T/a"; code=$?
check "the limit exits 142" [ "$code" = 142 ]
check "the limit kills the child" stopped "$T/a"

"$HERE/limited.sh" 60 "$T/leaves-child.sh" "$T/b" & p=$!; sleep 1.5; kill "$p"; wait "$p"; code=$?
check "TERM exits 143" [ "$code" = 143 ]
check "TERM kills the child" stopped "$T/b"

"$HERE/limited.sh" 5 bash -c 'exit 3'; code=$?
check "the exit code passes through" [ "$code" = 3 ]
exit $fails
