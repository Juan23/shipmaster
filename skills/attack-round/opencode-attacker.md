---
description: Read-only attack-round reviewer. Reads files in its folder; no shell, no edits, no web.
mode: primary
permissions:
  # Later rules win. Deny everything, then allow only reading inside the worktree.
  - action: "*"
    resource: "*"
    effect: deny
  - action: read
    resource: "*"
    effect: allow
  - action: glob
    resource: "*"
    effect: allow
  - action: grep
    resource: "*"
    effect: allow
  - action: list
    resource: "*"
    effect: allow
  - action: external_directory
    resource: "*"
    effect: deny
---
