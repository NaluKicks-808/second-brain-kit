#!/usr/bin/env python3
"""
agenda.py - print what is actually open, right now.

WHY THIS IS A COMMAND AND NOT A RULE. A session that reads the ledger at the start of
its work and answers "what are my todos" from that reading three hours later will
report rows that were closed in between. The ledger was never out of sync; the
session was. A session cannot notice from the inside that its own context has gone
stale, and prose cannot fix that - so surfacing the agenda became a command. A
command re-reads the file every time by construction, and it cannot forget the
closure convention the way a reader can.

The rule that follows: never answer "what is outstanding" from a copy of the ledger
read earlier in a session. Run this.

Usage:
    python3 tools/agenda.py                 # everything open
    python3 tools/agenda.py invoice         # only rows mentioning "invoice"
    python3 tools/agenda.py --all           # include closed rows, to see what was dropped

No model call and no network, so it keeps working when everything clever is
unavailable.
"""

import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, 'wiki', '_reminders.md')

# The agenda is the `## Open` table and nothing else. Stopping at the NEXT `## `
# heading rather than at the literal `## Done` is what keeps that true for any
# section a later session adds - standing rules and preferences can live in the same
# file without ever reaching this list. `### ` sub-headings are not matched, so a
# Done table's own archive sub-section still parses as part of Done.
OPEN_HEADING = re.compile(r'(?m)^##\s+Open[ \t]*$')
NEXT_SECTION = re.compile(r'(?m)^## ')
CELL_SPLIT = re.compile(r'(?<!\\)\|')

# ONE definition of "this row is closed". If you write a second reader of this table,
# import this rather than copying it: two copies of a rule agree right up until the
# day they do not.
CLOSED_WORDS = re.compile(r'^\s*(DONE|DROPPED|SUPERSEDED|CANCELLED|CANCELED)\b', re.I)
STRUCK = re.compile(r'~~.+~~')


def is_closed(trigger, what):
    """A row is closed when its trigger or its title says so: a closure word at the
    head of either cell, or a struck-through title. Closed rows stay in the Open
    table as tombstones until somebody moves them, so that the record of what was
    dropped survives - they just never reach the agenda."""
    for cell in (trigger or '', what or ''):
        if CLOSED_WORDS.match(cell) or STRUCK.search(cell):
            return True
    return False


def rows(include_closed=False):
    text = open(LEDGER, encoding='utf-8').read()
    # Both boundaries are matched as HEADINGS, at the start of a line. A plain
    # text.split("## Open") is correct right up until the file's own preamble names
    # its sections in prose, at which point the agenda silently empties.
    head = OPEN_HEADING.search(text)
    if not head:
        return []
    section = NEXT_SECTION.split(text[head.end():], 1)[0]
    out = []
    for line in section.splitlines():
        cells = [c.strip() for c in CELL_SPLIT.split(line)]
        if len(cells) < 5 or cells[2].lower() not in ('date', 'event', 'condition'):
            continue
        trigger, kind, what = cells[1], cells[2].lower(), cells[3]
        closed = is_closed(trigger, what)
        if closed and not include_closed:
            continue
        out.append({'trigger': trigger, 'kind': kind, 'what': what, 'closed': closed})
    return out


def plain(s, width=None):
    s = re.sub(r'^\s*`\[[^\]]*\]`\s*', '', s or '')      # an optional `[area]` tag
    s = re.sub(r'\[\[([^|\]]*\|)?([^\]]*)\]\]', r'\2', s)
    s = s.replace('**', '').replace('~~', '').replace('\\|', '|').strip()
    s = re.sub(r'\s+', ' ', s)
    return s[:width] + '…' if width and len(s) > width else s


def earliest(trigger):
    ds = re.findall(r'(20\d\d)-(\d\d)-(\d\d)', trigger or '')
    if not ds:
        return None
    try:
        return min(datetime(int(y), int(m), int(d)).date() for y, m, d in ds)
    except ValueError:
        return None


def main():
    if not os.path.isfile(LEDGER):
        print("no ledger at %s - create it before asking what is open."
              % os.path.relpath(LEDGER, ROOT))
        return
    args = sys.argv[1:]
    include_closed = '--all' in args
    needles = [a.lower() for a in args if not a.startswith('--')]

    # The clock is read HERE, at the moment of use, never carried forward from
    # earlier in a session: long sessions cross midnight.
    now = datetime.now()
    today = now.date()
    picked = rows(include_closed)
    if needles:
        picked = [r for r in picked
                  if any(n in (r['trigger'] + r['what']).lower() for n in needles)]

    overdue, upcoming, undated = [], [], []
    for r in picked:
        d = earliest(r['trigger']) if r['kind'] == 'date' else None
        (overdue if d and d <= today else upcoming if d else undated).append((d, r))

    label = (' matching %s' % needles) if needles else ''
    print("OPEN%s - read live from wiki/_reminders.md at %s\n"
          % (label, now.strftime('%Y-%m-%d %H:%M')))

    def show(title, group, sort=True):
        if not group:
            return
        print("-- %s (%d) " % (title, len(group)) + "-" * max(0, 50 - len(title)))
        ordered = sorted(group, key=lambda x: (x[0] is None, x[0])) if sort else group
        for d, r in ordered:
            when = ("%s  " % d) if d else ""
            flag = "[CLOSED] " if r['closed'] else ""
            print("  %s%s%s" % (flag, when, plain(r['what'], 150)))
            print("        -> %s" % plain(r['trigger'], 110))
        print()

    show("DUE OR OVERDUE", overdue)
    show("DATED, STILL AHEAD", upcoming)
    show("WAITING ON AN EVENT OR A CONDITION", undated, sort=False)
    if not picked:
        print("  (nothing open)\n")
    print("%d open row(s). Closed rows are excluded unless --all." % len(picked))


if __name__ == '__main__':
    main()
