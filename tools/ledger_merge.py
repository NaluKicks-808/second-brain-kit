#!/usr/bin/env python3
"""ledger_merge.py - git merge driver for wiki/_reminders.md: two sides that each ADD rows merge.

WHY. The ledger is written by several sessions at once. One leaves a fresh row uncommitted, its
next `git pull --rebase --autostash` brings in another writer's rows inserted at the same spot,
and the stash pop conflicts: both sides added a line after the same table row, which git's line
merge cannot order. The merge then jams until someone resolves it by hand.

WHAT. Registered in .gitattributes as `merge=ledger-rows` for wiki/_reminders.md only. git calls
it as `ledger_merge.py %O %A %B` (base, ours - written in place - and theirs). It runs git's own
three-way merge (`git merge-file --diff3`), then resolves exactly one kind of conflict hunk:
the BASE side is empty, so both sides only inserted lines. Those become ours then theirs, with
lines that appear on both sides kept once. Every other conflict (an edit to the same row on both
sides, an edit against an insert) keeps git's markers and the driver exits 1, so it is reported
as a conflict exactly as before. This is NOT `merge=union`: union keeps both halves of a real
conflict, which is why union is allowed only on the append-only log. Here a real conflict still
stops.

REGISTRATION. A merge driver is per clone: git never copies it with the repository.
    git config merge.ledger-rows.driver "python3 tools/ledger_merge.py %O %A %B"
safe_commit.sh runs that for you on every commit. A clone that has not registered the driver
falls back to git's normal merge, so the attribute alone can never make things worse.
"""

import subprocess
import sys
from pathlib import Path

OURS, BASE, THEIRS, END = "<<<<<<< ", "||||||| ", "=======", ">>>>>>> "


def _around(side, base):
    """(before, after) when `side` is `base` left intact with lines added around it, else None."""
    n = len(base)
    for k in range(len(side) - n + 1):
        if side[k:k + n] == base:
            return side[:k], side[k + n:]
    return None


def _once(rows):
    seen, out = set(), []
    for x in rows:
        if x.strip() and x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def combine(ours, base, theirs):
    """The merged lines of one conflict hunk, or None when it is a real conflict.

    Safe cases only:
      - both sides only inserted (base empty): ours then theirs;
      - one side left the base rows intact and only added rows around them, while the other side
        changed them (upstream closed a row, the other side had inserted new rows just above it): the added rows around the other side's version;
      - both sides left the base intact and only added around it.
    """
    if not any(b.strip() for b in base):
        return _once(ours + theirs)
    o, t = _around(ours, base), _around(theirs, base)
    if o and t:
        return _once(o[0] + t[0] + base + o[1] + t[1])
    if t:
        return _once(t[0] + ours + t[1])
    if o:
        return _once(o[0] + theirs + o[1])
    return None


def resolve(text):
    """Resolve pure-insertion conflict hunks in diff3 output. Returns (text, unresolved_count)."""
    out, left = [], 0
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        l = lines[i]
        if not l.startswith(OURS):
            out.append(l)
            i += 1
            continue
        ours, base, theirs, j, part = [], [], [], i + 1, "ours"
        while j < len(lines):
            m = lines[j]
            if part == "ours" and m.startswith(BASE):
                part = "base"
            elif part in ("ours", "base") and m == THEIRS:
                part = "theirs"
            elif part == "theirs" and m.startswith(END):
                break
            else:
                {"ours": ours, "base": base, "theirs": theirs}[part].append(m)
            j += 1
        if j >= len(lines):           # malformed: leave the rest as it was
            out.extend(lines[i:])
            return "\n".join(out), left + 1
        merged = combine(ours, base, theirs)
        if merged is None:
            left += 1
            out.extend(lines[i:j + 1])
        else:
            out.extend(merged)
        i = j + 1
    return "\n".join(out), left


def merge(base_path, ours_path, theirs_path):
    p = subprocess.run(["git", "merge-file", "-p", "--diff3", "-L", "ours", "-L", "base", "-L", "theirs",
                        ours_path, base_path, theirs_path], capture_output=True)
    text = p.stdout.decode("utf-8", "replace")
    if p.returncode == 0:
        Path(ours_path).write_text(text, encoding="utf-8")
        return 0
    if p.returncode < 0 or p.returncode > 127:
        return 2
    merged, left = resolve(text)
    Path(ours_path).write_text(merged, encoding="utf-8")
    return 1 if left else 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("usage: ledger_merge.py BASE OURS THEIRS", file=sys.stderr)
        sys.exit(2)
    sys.exit(merge(sys.argv[1], sys.argv[2], sys.argv[3]))
