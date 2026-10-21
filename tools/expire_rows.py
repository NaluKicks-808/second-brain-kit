#!/usr/bin/env python3
"""
expire_rows.py - close open ledger rows whose moment has passed.

WHY. A time-bound row ("the shop is closed right now", "waiting on the 3pm call")
outlives its moment because nothing carried the moment with it. Two days later the
agenda still states it as current, which is a wrong statement. A row can now carry its
own end: put `expires: YYYY-MM-DDTHH:MM` (local time) in the last cell ("Why it
matters"). Once that moment is past, this tool closes the row.

Closing is DROPPED, not DONE: nobody did the work, the moment simply passed. The
stamp is `DROPPED <date> via expired - ` at the head of the trigger cell, and the
first bold title in the "What to surface" cell is struck through. Both make agenda.py
treat the row as closed. The row stays in the table as a tombstone.

Rules:
  * only rows in the `## Open` table, only rows not already closed;
  * a row with no `expires:` marker, a malformed one, or a future one is never touched;
  * time is the machine's local clock, read at the moment of use;
  * idempotent: a closed row is skipped, so a second run changes nothing.

Usage:
    python3 tools/expire_rows.py             # close expired rows in wiki/_reminders.md
    python3 tools/expire_rows.py --dry-run   # list what would close, write nothing
    python3 tools/expire_rows.py --ledger PATH

No model call and no network.
"""

import argparse
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agenda  # noqa: E402

EXPIRES = re.compile(r'\bexpires:\s*(\d{4}-\d\d-\d\dT\d\d:\d\d)\b')


def row_expiry(why):
    """The datetime in a why cell's `expires:` marker, or None if absent or not a real moment."""
    m = EXPIRES.search(why or '')
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1), '%Y-%m-%dT%H:%M')
    except ValueError:
        return None


def expire_text(ledger_text, now):
    """Return (new_text, [closed titles]). Pure: reads no clock and no file."""
    head = agenda.OPEN_HEADING.search(ledger_text)
    if not head:
        return ledger_text, []
    start = ledger_text[:head.end()].count('\n')
    lines = ledger_text.split('\n')
    closed = []
    for i in range(start, len(lines)):
        if i > start and re.match(r'^## ', lines[i]):
            break
        line = lines[i].strip()
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in agenda.CELL_SPLIT.split(line)]
        # ['', trigger, type, what, why, '']
        if len(cells) != 6 or cells[2].lower() not in ('date', 'event', 'condition'):
            continue
        trigger, what, why = cells[1], cells[3], cells[4]
        if agenda.is_closed(trigger, what):
            continue
        moment = row_expiry(why)
        if not moment or now < moment:
            continue
        cells[1] = 'DROPPED {} via expired - {}'.format(now.strftime('%Y-%m-%d'), trigger)
        cells[3] = re.sub(r'\*\*(.+?)\*\*', lambda mm: '**~~{}~~**'.format(mm.group(1)), what, count=1)
        lines[i] = '| ' + ' | '.join(cells[1:5]) + ' |'
        closed.append(agenda.plain(what, 80))
    return '\n'.join(lines), closed


def main(argv=None):
    parser = argparse.ArgumentParser(description='Close open ledger rows past their expires: moment.')
    parser.add_argument('--ledger', default=agenda.LEDGER)
    parser.add_argument('--dry-run', action='store_true', help='list what would close; write nothing')
    args = parser.parse_args(argv)
    if not os.path.isfile(args.ledger):
        print('no ledger at {}'.format(args.ledger))
        return 1
    with open(args.ledger, encoding='utf-8') as f:
        text = f.read()
    new, closed = expire_text(text, dt.datetime.now())   # local time, read now
    verb = 'would close' if args.dry_run else 'closed'
    print('{} {} expired row(s)'.format(verb, len(closed)))
    for title in closed:
        print('  - ' + title)
    if closed and not args.dry_run:
        with open(args.ledger, 'w', encoding='utf-8') as f:
            f.write(new)
    return 0


if __name__ == '__main__':
    sys.exit(main())
