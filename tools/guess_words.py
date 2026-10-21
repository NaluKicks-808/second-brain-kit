#!/usr/bin/env python3
"""guess_words.py - words that dress a guess up as a fact, in NEW wiki prose.

    python3 tools/guess_words.py          # lines changed since origin/main (what lint.py warns on)
    python3 tools/guess_words.py --all    # every line of the current wiki (to judge noise)

WHY IT EXISTS. The most lasting harm a brain does itself is a guess written into a page as
a plain sentence: a fact inferred from a notetaker's assignee, one summary, one row or one
speaker label, stated flat, then read back by a later session as settled. The rule is that
such a fact goes in as a `> [!question]` or under `status: provisional`. The words below are
the ones that most often carry a guess across that line: "almost certainly", "clearly",
"which is why", "must have", "presumably", "no doubt".

WHAT IT CAN AND CANNOT SEE. The finding that matters, a guess about a PERSON, a ROLE, an
OUTCOME or an OBLIGATION, is not detectable by pattern, so this does not pretend to: it flags
the words and leaves the judgement to the session reading the line. To keep that bearable it
reads only lines ADDED since origin/main (the working tree against origin/main, plus
untracked wiki pages), never the existing wiki, and skips what is not the vault's own voice:
frontmatter, fenced and inline code, blockquotes and `> [!...]` callouts (where a question or
a quotation belongs), and anything inside double quotation marks. Underscore pages and
log.md are skipped, as quote_check.py skips them: they are indexes, a ledger and a log.
With no origin/main to compare against it says so and reports nothing.

lint.py imports this and prints each finding as `guess/warn`. It warns and never blocks.
"""
import glob
import os
import re
import subprocess
import sys

PHRASES = ("almost certainly", "clearly", "which is why", "must have", "presumably", "no doubt")
PATTERN = re.compile(r"\b(" + "|".join(re.escape(p) for p in PHRASES) + r")\b", re.I)
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
INLINE_CODE = re.compile(r"`[^`\n]*`")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def in_scope(rel):
    rel = rel.replace(os.sep, "/")
    base = os.path.basename(rel)
    return (rel.startswith("wiki/") and rel.endswith(".md")
            and not base.startswith("_") and base != "log.md")


def prose_lines(text):
    """(line number, prose with code and quotations removed) for the vault's own sentences."""
    lines = text.split("\n")
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    fenced = False
    for i in range(start, len(lines)):
        line = lines[i]
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            fenced = not fenced
            continue
        if fenced or line.lstrip().startswith(">"):
            continue
        yield i + 1, QUOTED.sub("", INLINE_CODE.sub("", line))


def hits_in(text, only=None):
    out = []
    for n, prose in prose_lines(text):
        if only is not None and n not in only:
            continue
        for m in PATTERN.finditer(prose):
            lo = max(m.start() - 50, 0)
            snippet = prose[lo:m.end() + 50].strip()
            out.append((n, m.group(1).lower(), snippet))
    return out


def _git(root, *args):
    return subprocess.run(["git", "-c", "core.quotepath=off"] + list(args), cwd=root,
                          capture_output=True, text=True)


def changed_lines(root, base="origin/main"):
    """{rel: {line numbers added since `base`}} over wiki/, or None when git cannot say."""
    if _git(root, "rev-parse", "--verify", "-q", base + "^{commit}").returncode != 0:
        return None
    diff = _git(root, "diff", "-U0", "--no-color", "--no-ext-diff", base, "--", "wiki")
    if diff.returncode != 0:
        return None
    added, current = {}, None
    for line in diff.stdout.split("\n"):
        if line.startswith("+++ "):
            target = line[4:].strip()
            current = target[2:] if target.startswith("b/") else None
            continue
        m = HUNK.match(line)
        if m and current:
            first, count = int(m.group(1)), int(m.group(2) or 1)
            added.setdefault(current, set()).update(range(first, first + count))
    untracked = _git(root, "ls-files", "-o", "--exclude-standard", "--", "wiki")
    for rel in untracked.stdout.split("\n"):
        if rel.strip():
            added[rel.strip()] = None                  # None = every line is new
    return added


def scan(root, whole=False, base="origin/main"):
    """(findings, note). Each finding is 'wiki/x.md:12: "clearly" — …snippet…'."""
    if whole:
        targets = {os.path.relpath(p, root): None
                   for p in glob.glob(os.path.join(root, "wiki", "**", "*.md"), recursive=True)}
        note = "the whole wiki"
    else:
        targets = changed_lines(root, base)
        if targets is None:
            return [], "no %s here to compare against — skipped" % base
        note = "lines added since %s" % base
    findings, pages = [], 0
    for rel in sorted(targets):
        if not in_scope(rel):
            continue
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            continue
        pages += 1
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        for n, phrase, snippet in hits_in(text, targets[rel]):
            findings.append('%s:%d: "%s" — …%s… — if this is inferred, write it as a > [!question] '
                            'or mark it status: provisional' % (rel, n, phrase, snippet))
    return findings, "%s, %d page(s) read" % (note, pages)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if any(a not in ("--all",) for a in argv):
        print(__doc__.split("\n\n")[1])
        return 2
    findings, note = scan(os.getcwd(), whole="--all" in argv)
    for f in findings:
        print("  " + f)
    print("guess words: %d (%s)" % (len(findings), note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
