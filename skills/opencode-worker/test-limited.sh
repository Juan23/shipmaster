#!/bin/bash
# Tests limited.sh: the limit and TERM kill a child the command left running; the exit code passes through.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT; fails=0
printf '#!/bin/bash\n( while true; do echo x >> "$1"; sleep 0.2; done ) &\nwait\n' > "$T/fake.sh"; chmod +x "$T/fake.sh"
stopped() { local a b; sleep 1; a=$(wc -l < "$1"); sleep 1; b=$(wc -l < "$1"); [ "$a" = "$b" ]; }
check() { if "${@:2}"; then echo "ok: $1"; else echo "FAIL: $1"; fails=1; fi; }

"$HERE/limited.sh" 2 "$T/fake.sh" "$T/a"; code=$?
check "the limit exits 142" [ "$code" = 142 ]
check "the limit kills the child" stopped "$T/a"

"$HERE/limited.sh" 60 "$T/fake.sh" "$T/b" & p=$!; sleep 1.5; kill "$p"; wait "$p"; code=$?
check "TERM exits 143" [ "$code" = 143 ]
check "TERM kills the child" stopped "$T/b"

"$HERE/limited.sh" 5 bash -c 'exit 3'; code=$?
check "the exit code passes through" [ "$code" = 3 ]
exit $fails
