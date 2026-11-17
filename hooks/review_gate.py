"""PreToolUse hook: owner's standing review gate for every pull request, in every project.

- `gh pr create` needs a pr-reviewer agent of this session that ended with REVIEW CLEAN for the commit
  it opens: the --head branch, else HEAD. It ran /code-review and /commentdiet.
- `gh pr merge` needs a merge-reviewer agent of this session that ended with REVIEW CLEAN for the
  pull request's head commit, with an issues line. It ran /ponytail-review.
- The gate's own files and its settings.json entry cannot be changed or removed.

A shell command made only of forms on this gate's allowlist (read-only tools, a few file writers,
gh, plain quoting, plain variables, a leading cd, inert here-documents) is judged by what it writes
and runs, so a command that only reads a protected file, or only mentions `gh pr create`, passes.
Every other command keeps the word match on its raw text: it is blocked when it names a protected
file and has a write anywhere in it, and a `gh pr create` or `gh pr merge` in it is checked.

The gate reads the reviewers' own sessions: <transcript_path without .jsonl>/subagents/ holds
agent-<id>.meta.json ("agentType", "finished") and agent-<id>.jsonl (the reviewer's report).
A new commit has a new sha, so every fix needs a new review.
Exit 2 blocks the tool call and shows stderr to the agent; a crash also exits 2.
"""
import glob, itertools, json, os, re, shlex, subprocess, sys, unicodedata

HOME = os.path.expanduser("~")
SETTINGS = os.path.join(HOME, ".claude", "settings.json")
PROTECTED_FILES = {os.path.join(HOME, ".claude", "hooks", n) for n in ("review_gate.py", "test_review_gate.py")}
SETTINGS_IN_SHELL = re.compile(r"(~|\$HOME|\$\{HOME\}|" + re.escape(HOME) + r")/\.claude/settings\.json")
SHELL_WRITE = re.compile(r"\b(rm|mv|cp|ln|unlink|truncate|tee|chmod|dd|install|rsync|ditto|sed\s+-[iI]|perl\s+-\w*i)\b"
                         r"|-delete\b|-exec|>(?!&)")
# The allowlist. Read-only tools: they cannot write a file or run another command.
READERS = {"cat", "head", "tail", "grep", "egrep", "fgrep", "ls", "wc", "cut", "tr", "diff", "cmp", "stat",
           "file", "jq", "echo", "printf", "true", "false", "basename", "dirname", "realpath", "readlink",
           "pwd", "date", "which", "du", "df", "nl", "column", "comm", "shasum", "md5"}
# gh commands that write no local file (create and merge are checked on their own); an alias,
# an extension or a download can do anything, so nothing else is read.
GH_READS = {("pr", s) for s in ("view", "list", "diff", "checks", "status", "create", "new", "merge")} | {
    (c, s) for c in ("issue", "run", "repo", "release") for s in ("view", "list")}
WORD_EDGE = " \t\r\n;&|()<>"
SHELL_NAME = re.compile(r"(^|[\s|;&(])(\S*/)?(bash|sh|zsh|ksh|dash|fish)(?=[\s;|&)]|$)")
WRITERS = {"cp", "mv", "rm", "tee", "mkdir", "touch", "chmod", "truncate", "unlink"}
OPERATORS = {"&&", "||", ";", "|", "\n", "&"}
REDIRECTS = {">", ">>", "&>", ">&", "<"}
NAME_VALUE = re.compile(r"([A-Za-z_]\w*)=(.*)")
FD_NUMBER = re.compile(r"(?<![^\s;&|(])\d+(?=[<>])")
HEREDOC = re.compile(r"(?<!<)<<[ \t]*(['\"]?)([A-Za-z_]\w*)\1(?=[\s;&|)]|$)")
NOT_READ = re.compile(r"\$\(|`|[<>]\(|\(\(|\\|<<<|!|\$\{[^}]*[^\w}]")  # ! also covers zsh >! and history
# shortcut: the flags of `gh pr create` and `gh pr merge` that take a value, from gh 2.101.0; add any new one,
# or its value can pass for --head or for the pull request.
CREATE_VALUE_FLAGS = {"-a", "--assignee", "--attach", "-B", "--base", "-b", "--body", "-F", "--body-file",
                      "-H", "--head", "-l", "--label", "-m", "--milestone", "-p", "--project", "--recover",
                      "-r", "--reviewer", "-T", "--template", "-t", "--title", "-R", "--repo"}
MERGE_VALUE_FLAGS = {"-R", "--repo", "-b", "--body", "-F", "--body-file", "-t", "--subject",
                     "-A", "--author-email", "--match-head-commit"}

RULE = ("This is the owner's standing, non-negotiable review gate. Do not argue with it, work around "
        "it, or edit or delete it. Do what it asks, then retry.")


def block(msg):
    print(f"{RULE}\n\n{msg}", file=sys.stderr)
    sys.exit(2)


def final_report(path):
    """The reviewer's last words: a SubagentHandback message or its last text."""
    last = ""
    try:
        with open(path) as f:
            for line in f:
                entry = json.loads(line)
                if entry.get("type") != "assistant":
                    continue
                for c in (entry.get("message") or {}).get("content") or []:
                    if c.get("type") == "text" and c.get("text"):
                        last = c["text"]
                    elif c.get("type") == "tool_use" and c.get("name") == "SubagentHandback":
                        last = (c.get("input") or {}).get("message") or last
    except (OSError, ValueError, AttributeError):
        pass
    return last


def field(text, key):
    m = re.search(rf"^[ \t]*{key}:[ \t]*(.+?)[ \t]*$", text, re.M)
    return m.group(1) if m else None


def signed_off(transcript, agent_type, sha, needs_issues=False):
    """True if a finished reviewer of this type, in this session, ended with REVIEW CLEAN for sha."""
    if not transcript:
        block("Claude Code sent no transcript_path, so the gate cannot find this session's reviewers.")
    parent = os.path.dirname(transcript)
    # A worker agent's own transcript already sits in the session's subagents folder.
    folder = parent if os.path.basename(parent) == "subagents" else os.path.join(os.path.splitext(transcript)[0], "subagents")
    for meta_path in glob.glob(os.path.join(glob.escape(folder), "agent-*.meta.json")):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        if meta.get("agentType") != agent_type or meta.get("finished") is not True:
            continue
        report = final_report(meta_path[:-len(".meta.json")] + ".jsonl")
        clean = list(re.finditer(r"^[ \t]*REVIEW CLEAN[ \t]*$", report, re.M))
        if not clean or "REVIEW FINDINGS" in report:
            continue
        tail = report[clean[-1].end():]  # the block ends the report
        if field(tail, "commit") == sha and (not needs_issues or field(tail, "issues")):
            return True
    return False


def git_head(cwd):
    p = subprocess.run(["git", "-C", cwd, "rev-parse", "HEAD"], capture_output=True, text=True)
    if p.returncode:
        block(f"Could not read HEAD in {cwd}: {p.stderr.strip()}")
    return p.stdout.strip()


def pr_head(args, cwd):
    if os.environ.get("REVIEW_GATE_PR_SHA"):
        return os.environ["REVIEW_GATE_PR_SHA"]
    selector, repo, i = [], [], 0
    while i < len(args):
        a = args[i]
        if a in MERGE_VALUE_FLAGS:
            if a in ("-R", "--repo"):
                repo = args[i:i + 2]
            i += 2
            continue
        if not a.startswith("-") and not selector:
            selector = [a]
        i += 1
    view = ["gh", "pr", "view", *selector, *repo]
    p = subprocess.run(view + ["--json", "headRefOid", "-q", ".headRefOid"], cwd=cwd,
                       capture_output=True, text=True)
    if p.returncode or not p.stdout.strip():
        block(f"Could not read the pull request's head commit ({' '.join(view)}): {p.stderr.strip()}")
    return p.stdout.strip()


def open_quote(text):
    """The quote character text ends inside, or None."""
    quote = None
    for c in text:
        if quote:
            quote = None if c == quote else quote
        elif c in "'\"":
            quote = c
    return quote


def without_inert_heredocs(command):
    """The command line without here-document text the shell neither expands nor runs, and the delimiters
    of the documents it dropped. A document whose text the shell expands, or a shell reads, stays."""
    kept, end, dropped = [], None, []
    for line in command.split("\n"):
        if end is not None:
            body.append(line)
            if line == end:
                if quoted or not re.search(r"[$`\\]", "\n".join(body)):
                    dropped.append(end)
                else:
                    kept.extend(body)
                end = None
            continue
        m = HEREDOC.search(line)
        # A quote may have opened on an earlier line, so the whole text so far decides.
        # A quote after the marker may run past the line break, and the document starts after it.
        if (m and not open_quote("\n".join(kept + [line[:m.start()]])) and not re.search(r"['\"]", line[m.end():])
                and not SHELL_NAME.search(line)):
            end, quoted, body = m.group(2), bool(m.group(1)), []
        kept.append(line)
    if end is not None:
        kept.extend(body)  # no end line: the shell reads to the end, so keep it all
    return "\n".join(kept), dropped


def unquote(token):
    """A word without its quotes, or None if its quoting is more than one plain quoted string."""
    if not re.search(r"['\"]", token):
        return token
    q = token[0]
    if len(token) > 1 and q in "'\"" and token[-1] == q and q not in token[1:-1] \
            and not (q == '"' and re.search(r"[$`\\]", token)):
        return token[1:-1]
    return None


def parse(command):
    """(simple commands as (words, files written by redirects, separator), True if every operator, word
    and here-document is a plain form). Raises ValueError on unbalanced quotes."""
    text, heredocs = without_inert_heredocs(command)
    allowed = not NOT_READ.search(text)
    text = FD_NUMBER.sub("", text)
    lex = shlex.shlex(text, posix=False, punctuation_chars="();<>|&\n")
    lex.whitespace, lex.whitespace_split, lex.commenters = " \t\r", True, ""
    commands, words, files, redirect, end = [], [], [], None, 0
    for token in lex:
        start = text.find(token, end)
        end = start + len(token)
        if re.search(r"['\"]", token) and not (text[start - 1:start] + text[end:end + 1]).strip(WORD_EDGE) == "":
            allowed = False  # 'a'b is one word to the shell but two tokens here
        if set(token) <= set(lex.punctuation_chars):  # an operator, never a quoted word
            token = token.strip("\n") or "\n"  # a blank line is one line break
            if redirect or not (token in OPERATORS or token in REDIRECTS or token == "<<"):
                allowed = False
            if token in OPERATORS or token in "()":
                commands.append((words, files, token))
                words, files = [], []
            else:
                redirect = token
            continue
        word = unquote(token)
        if word is None:
            allowed, word = False, token
        if token.startswith("#") or (word == token and re.search(r"[{*?\[]", token)) \
                or (word.startswith("~") and not re.match(r"~(/|$)", word)):
            allowed = False  # a comment, an unquoted pattern, or ~user, ~+ and ~-
        if redirect == "<<":
            if word not in heredocs:
                allowed = False  # a here-document whose text the shell expands or runs
        elif redirect:
            if ">" in redirect and not (redirect == ">&" and word.isdigit()):
                files.append(word)
        else:
            words.append(word)
        redirect = None
    commands.append((words, files, ""))
    return commands, allowed


def home(path):
    return re.sub(r"^(~|\$HOME|\$\{HOME\})(?=/|$)", lambda _: HOME, path)


def read_shell(command, cwd):
    """(simple commands, paths the command writes, True if the gate read every part of it).
    Raises ValueError on unbalanced quotes."""
    commands, allowed = parse(command)
    targets, here = [], cwd
    for n, (words, files, separator) in enumerate(commands):
        words, files = [home(w) for w in words], [home(f) for f in files]
        verb, rest = (words[0], words[1:]) if words else ("", [])
        if verb == "cd":  # only a leading `cd <plain path> &&` with no `||` after it, so it surely ran
            allowed &= (n == 0 and len(rest) == 1 and bool(re.match(r"(/|~/|\./|~$)", rest[0]))  # CDPATH
                        and ".." not in rest[0].split("/")
                        and all(s in ("&&", "|", "") for _, _, s in commands))  # nothing runs after a failed cd
            here = os.path.join(here, rest[0]) if rest else here
            continue
        if verb in WRITERS:  # every word is a path it may change, flags too; cp changes only its last
            if verb in ("cp", "mv") and any(re.match(r"-[^-]*t|--target", w) for w in rest):  # GNU -t, -at
                allowed = False
            dest = rest[-1] if rest else ""
            files = files + (rest[-1:] if verb == "cp" else rest) + [os.path.join(dest, os.path.basename(s))
                                                                    for s in rest[:-1]]
        elif verb == "sed":  # sed writes with -i, -I, w and e: only `sed -n <lines>p` is read
            allowed &= rest[:1] == ["-n"] and len(rest) > 1 and bool(re.fullmatch(r"[\d$,]+p", rest[1]))
        elif verb == "gh":
            allowed &= tuple(rest[:2]) in GH_READS
        elif verb not in READERS or (verb == "printf" and "-v" in rest):  # printf -v sets a variable
            allowed = False  # also NAME=value: the gate does not follow variables
        for t in files:
            if "$" in t or not t.isascii():  # the disk folds some letters (ſ to s) that Python keeps
                allowed = False
            else:
                targets.append(os.path.join(here, t))
    return commands, targets, allowed


def folded(path):
    """The path as the macOS disk compares names: case and Unicode forms ignored."""
    return unicodedata.normalize("NFD", os.path.realpath(path)).casefold()


def is_protected(path):
    """True for a protected file or any folder that holds one."""
    real = folded(path).rstrip("/") + "/"
    return any((folded(p) + "/").startswith(real) for p in PROTECTED_FILES | {SETTINGS})


def is_help(args, value_flags):
    """True if gh only prints help: -h or --help that is no other flag's value."""
    return any(a in ("-h", "--help") and (k == 0 or args[k - 1] not in value_flags) for k, a in enumerate(args))


def gh_pr_calls(commands, subcommands, value_flags):
    """(index of the simple command, its arguments) for each `gh pr <subcommand>` the parsed line runs."""
    calls = []
    for n, (words, _, _) in enumerate(commands):
        words = list(itertools.dropwhile(NAME_VALUE.fullmatch, words))
        if (len(words) > 2 and os.path.basename(words[0]) == "gh" and words[1] == "pr" and words[2] in subcommands
                and not is_help(words[3:], value_flags)):
            calls.append((n, words[3:]))
    return calls


def mentions(command, subcommands, value_flags):
    """True if the raw text holds a `gh pr <subcommand>` that is not only asking for help.
    Quotes are dropped first (gh pr 'm'erge), and gh's own flags may come before pr (gh -R o/r pr merge)."""
    text = re.sub(r"['\"]", "", command)
    return any(not is_help(m.group(2).split(), value_flags) for m in re.finditer(
        rf"\bgh\s+(?:-\S+\s+(?:[^-\s]\S*\s+)?)*pr\s+({subcommands})\b([^;&|\n]*)", text))


def head_flag(args):
    """The -H/--head value as gh reads it (the last one wins), or None."""
    head, i = None, 0
    while i < len(args):
        a, i = args[i], i + 1
        if a.startswith("--"):
            name, attached, value = a.partition("=")
            if name not in CREATE_VALUE_FLAGS:
                continue
        elif a.startswith("-"):  # short flags can be joined: -dH branch, -Hbranch
            at = next((k for k in range(1, len(a)) if "-" + a[k] in CREATE_VALUE_FLAGS), 0)
            if not at:
                continue
            name, attached = "-" + a[at], a[at + 1:]
            value = attached[attached.startswith("="):]
        else:
            continue
        if not attached:
            value, i = (args[i] if i < len(args) else ""), i + 1
        if name in ("-H", "--head"):
            head = value
    return head


def create_heads(commands, calls, cwd):
    """The commit each `gh pr create` in the command will open."""
    first, _, separator = commands[0]
    shas = []
    for n, args in calls:
        repo = cwd
        # Only a `cd` that gh certainly runs under counts: the first command, with gh right after it.
        if n == 1 and len(first) == 2 and first[0] == "cd" and separator in ("&&", ";", "\n"):
            repo = os.path.join(cwd, home(first[1]))
        head = head_flag(args)
        if head is None:
            shas.append(git_head(repo))
            continue
        branch = head.split(":")[-1]  # owner:branch
        p = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}"],
                           capture_output=True, text=True)
        if p.returncode:
            block(f"Could not find the branch {branch!r} of --head in {repo}, so the gate cannot tell which "
                  "commit this pull request opens. Fetch or create the branch there, then retry.")
        shas.append(p.stdout.strip())
    return shas


def check_create(shas, transcript):
    for sha in shas:
        if signed_off(transcript, "pr-reviewer", sha):
            continue
        block(f"Have you run /code-review and /commentdiet on commit {sha}? No reviewer in this session "
              "signed it off.\n"
              "1. Spawn a new pr-reviewer agent (Agent tool, subagent_type \"pr-reviewer\"). Brief it with the "
              "repository path and the base branch.\n"
              "2. If it reports findings, fix them all, commit, and spawn a new pr-reviewer for the new commit. "
              "Brief it with the last reviewed commit and its findings.\n"
              "3. When it reports REVIEW CLEAN for this commit, retry. Never write reviewer files yourself.")


def check_merge(args, cwd, transcript):
    sha = pr_head(args, cwd)
    if not signed_off(transcript, "merge-reviewer", sha, needs_issues=True):
        block(f"Have you reviewed this pull request with /ponytail-review? No reviewer in this session "
              f"signed off its head commit {sha}.\n"
              "1. Spawn a new merge-reviewer agent (Agent tool, subagent_type \"merge-reviewer\"). Brief it "
              "with the repository path and the pull request number.\n"
              "2. Fix every finding related to the task now, push, and spawn a new merge-reviewer.\n"
              "3. Investigate every finding not related to the task, then open an issue for it.\n"
              "4. When it reports REVIEW CLEAN for this commit, retry. Never write reviewer files yourself.")


def edited_text(tool, ti, path):
    """The file's text after this Write or Edit."""
    if tool == "Write":
        return ti.get("content", "")
    try:
        with open(path) as f:
            text = f.read()
    except OSError:
        text = ""
    for e in ti.get("edits") or [ti]:
        old, new = e.get("old_string", ""), e.get("new_string", "")
        text = text.replace(old, new) if e.get("replace_all") else text.replace(old, new, 1)
    return text


def turns_hooks_off(text):
    try:
        return bool(json.loads(text).get("disableAllHooks"))
    except (ValueError, AttributeError):
        return "disableallhooks" in text.lower()  # not a JSON object yet: judged by its words


def check_file_edit(tool, ti):
    path = os.path.realpath(os.path.expanduser(ti.get("file_path", "")))
    if folded(path) in {folded(p) for p in PROTECTED_FILES}:
        block(f"{path} is the review gate. It must not be changed or deleted.")
    if re.fullmatch(r"settings(\.local)?\.json", os.path.basename(path), re.I) and turns_hooks_off(
            edited_text(tool, ti, path)):
        block("Settings may not turn hooks off (disableAllHooks): the review gate must keep running.")
    if folded(path) != folded(SETTINGS):
        return
    if tool == "Write" and "review_gate.py" not in ti.get("content", ""):
        block("This write would remove the review gate hook from settings.json. Keep that entry.")
    for e in ti.get("edits") or [ti]:
        if e.get("old_string", "").count("review_gate") > e.get("new_string", "").count("review_gate"):
            block("This edit would remove the review gate hook from settings.json. Keep that entry.")


def main():
    data = json.load(sys.stdin)
    tool, ti, cwd = data.get("tool_name"), data.get("tool_input") or {}, data.get("cwd") or os.getcwd()
    if tool in ("Edit", "Write", "MultiEdit"):
        check_file_edit(tool, ti)
        return
    if tool != "Bash":
        return
    command = ti.get("command", "")
    try:
        commands, writes, allowed = read_shell(command, cwd)
    except ValueError:  # unbalanced quotes
        commands, writes, allowed = None, [], False
    names_protected = "review_gate" in command or SETTINGS_IN_SHELL.search(command)
    if any(map(is_protected, writes)) or (not allowed and names_protected and SHELL_WRITE.search(command)):
        block("Shell commands may not change the review gate or ~/.claude/settings.json. "
              "Edit settings.json with the Edit tool and keep the review gate entry.\n"
              "If this command only reads those files: use the Read tool, or run the read as a plain command "
              "of its own (no $(...), loop, script or here-document), and send any output to a file "
              "with > in that plain command.")
    mentions_create = mentions(command, "create|new", CREATE_VALUE_FLAGS)
    mentions_merge = mentions(command, "merge", MERGE_VALUE_FLAGS)
    if commands is None:
        if mentions_create or mentions_merge:
            block("The review gate could not read this command (unbalanced quotes). Run gh pr create or "
                  "gh pr merge as a simple command of its own, with --body-file for the body.")
        return
    transcript = data.get("transcript_path") or ""
    # shortcut: a create is checked for its --head branch, else a leading `cd <dir> &&`, else the session's cwd;
    # a merge is looked up from the session's cwd. Any other way to change folder is not followed: use --head or -R.
    merges = gh_pr_calls(commands, ("merge",), MERGE_VALUE_FLAGS)
    creates = gh_pr_calls(commands, ("create", "new"), CREATE_VALUE_FLAGS)
    check_create(create_heads(commands, creates, cwd), transcript)
    if mentions_create and not allowed and not creates and not signed_off(transcript, "pr-reviewer", git_head(cwd)):
        block("This command holds the words gh pr create in a form the gate cannot read, so it is checked "
              "as if it opened a pull request from this folder's HEAD, and no reviewer signed that off.\n"
              "If it opens no pull request: put that text in a file, or in a plain command of its own "
              "(no $(...), loop, script or here-document fed to a shell).\n"
              "If it does: run gh pr create as a simple command of its own, after a clean pr-reviewer.")
    for _, args in merges:
        check_merge(args, cwd, transcript)
    if mentions_merge and not allowed and not merges:
        block("The review gate cannot tell which pull request this command merges. "
              "Run gh pr merge <number> as a simple command of its own.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        block(f"The review gate crashed, so the call is blocked: {e!r}")
