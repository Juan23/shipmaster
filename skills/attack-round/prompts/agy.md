Your focus: any real bug. Cover wrong logic, failure paths that leave a bad state (including checks that fail open), races, tests that no longer match the behaviour, and docs the change made false.

Shell commands: use only plain `git diff`, `git log`, `git show`, `git grep` and `rg`, with no `*` or `?` wildcards; name folders instead. A refused command ends your review with no answer.
