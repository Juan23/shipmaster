---
description: Read-only attack-round reviewer. Cannot edit files or run anything but read-only git and rg.
mode: primary
permissions:
  - action: question
    resource: "*"
    effect: deny
  - action: subagent
    resource: "*"
    effect: deny
  - action: edit
    resource: "*"
    effect: deny
  - action: webfetch
    resource: "*"
    effect: deny
  - action: shell
    resource: "*"
    effect: deny
  - action: shell
    resource: "git diff*"
    effect: allow
  - action: shell
    resource: "git log*"
    effect: allow
  - action: shell
    resource: "git show*"
    effect: allow
  - action: shell
    resource: "git grep*"
    effect: allow
  - action: shell
    resource: "rg *"
    effect: allow
  # Later rules win. These flags make an allowed command run a program or write a file.
  - action: shell
    resource: "*--pre*"
    effect: deny
  - action: shell
    resource: "*-O*"
    effect: deny
  - action: shell
    resource: "*--open-files-in-pager*"
    effect: deny
  - action: shell
    resource: "*--output*"
    effect: deny
  - action: shell
    resource: "*--ext-diff*"
    effect: deny
---
