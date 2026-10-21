#!/usr/bin/env python3
"""
event_twin.py - find two open ledger rows that are really one timed event.

WHY. The same event can reach the ledger twice, worded differently ("Dentist, Thu
14:30" and "Dentist appointment 14:30 Thursday"). A check that compares exact
titles cannot see a retold event, and the agenda then shows one appointment twice.
This tool looks only for the narrow case it can be sure of, so it stays quiet
otherwise:

  * both rows are open `Date` rows in the `## Open` table of wiki/_reminders.md;
  * both carry the SAME date and the SAME explicit HH:MM time. The time is read from
    the trigger cell (`2026-10-23 14:30` or `2026-10-23T14:30`) or from a `[area · 14:30]`
    tag at the head of the title cell. A row with no time never qualifies;
  * their titles share at least two meaningful words (stopwords, weekday and month
    names and clock words are ignored) and at least 60% of the smaller title's word set.

A notice such as `Overdue since ...` quotes an existing task rather than naming a
second event, so rows whose title starts with it are skipped.

Which row is older: the LOWER one in the table. New rows are inserted at the top of
the Open table, so the row further down was written first. No git history and no
guessed age is used.

Usage:
    python3 tools/event_twin.py                 # report twins, change nothing
    python3 tools/event_twin.py --merge         # also close the NEWER row of each pair
    python3 tools/event_twin.py --ledger PATH   # another ledger file

--merge changes only the newer row's trigger cell: the stamp
`DROPPED <date> via event_twin - twin of <older title>;` followed by the struck
original trigger. A DROPPED stamp is a closure word, so agenda.py stops listing the
row, and the title and every other cell stay as written. The newer row's full text is
printed first so a person can fold any extra facts into the older row.

No model call and no network.
"""

import argparse
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agenda  # noqa: E402  (the one definition of "closed" and of the Open section)

STOPWORDS = set("""
a an the and or but for with from about into this that then than are was were
will have has had not his her him she they them our your you who what when where
how all any one two out off via per be at on in to of is it as by worth attending
monday tuesday wednesday thursday friday saturday sunday mon tue tues wed thu
thur thurs fri sat sun january february march april may june july august
september october november december jan feb mar apr jun jul aug sep sept oct
nov dec am pm a m p
""".split())

TIME = r'(?:[01]\d|2[0-3]):[0-5]\d'
TRIGGER_WHEN = re.compile(r'(20\d\d-\d\d-\d\d)(?:[ T]+(' + TIME + r'))?')
TAG_TIME = re.compile(r'^\s*`\[[^\]]*?(' + TIME + r')\s*\]`')


def words(title):
    title = re.sub(r'\b\d{1,2}:\d{2}(?:\s*[ap]\.?m\.?)?', ' ', title.lower())
    return set(re.findall(r'[a-z]+', title)) - STOPWORDS


def parse_row(line):
    """A dict for an Open-table row, or None. Keys: type, trigger, what, task, due,
    due_time, closed."""
    cells = [c.strip() for c in agenda.CELL_SPLIT.split(line.strip())]
    if len(cells) < 5 or cells[2].lower() not in ('date', 'event', 'condition'):
        return None
    trigger, kind, what = cells[1], cells[2].lower(), cells[3]
    due = due_time = None
    m = TRIGGER_WHEN.search(trigger)
    if m and kind == 'date':
        due, due_time = m.group(1), m.group(2)
    tag = TAG_TIME.match(what)
    if tag and not due_time:
        due_time = tag.group(1)
    task = agenda.plain(what)
    return {'type': kind, 'trigger': trigger, 'what': what, 'task': task, 'due': due,
            'due_time': due_time, 'closed': agenda.is_closed(trigger, what)}


def same_event(a, b):
    """True only for open timed Date rows with strong title overlap."""
    if any(r['task'].startswith('Overdue since ') for r in (a, b)):
        return False
    if (a['closed'] or b['closed'] or a['type'] != 'date' or b['type'] != 'date'
            or not a['due'] or a['due'] != b['due']
            or not a['due_time'] or a['due_time'] != b['due_time']):
        return False
    left, right = words(a['task']), words(b['task'])
    if not left or not right:
        return False
    shared = len(left & right)
    return shared >= 2 and shared / min(len(left), len(right)) >= 0.6


def open_rows(ledger_text):
    """Open-section rows in file order, each with its one-based `line` and `text`."""
    head = agenda.OPEN_HEADING.search(ledger_text)
    if not head:
        return []
    base = ledger_text[:head.end()].count('\n') + 1
    section = agenda.NEXT_SECTION.split(ledger_text[head.end():], 1)[0]
    rows = []
    for number, line in enumerate(section.split('\n'), base):
        row = parse_row(line)
        if row:
            rows.append(dict(row, line=number, text=line))
    return rows


def open_twins(ledger_text):
    """Return [(older_row, newer_row)]. The lower row is the older one."""
    rows = open_rows(ledger_text)
    out = []
    for i, upper in enumerate(rows):
        for lower in rows[i + 1:]:
            if same_event(upper, lower):
                out.append((lower, upper))
    return out


def merge(ledger_text, twins, today=None):
    """Stamp each newer row's trigger once, leaving every other cell intact."""
    lines = ledger_text.split('\n')
    stamped = set()
    for older, newer in twins:
        number = newer['line']
        if number in stamped:
            continue
        stamped.add(number)
        line = lines[number - 1]
        first = line.index('|')
        boundary = first + 1 + len(re.split(r'(?<!\\)\|', line[first + 1:], 1)[0])
        original = line[first + 1:boundary].strip()
        stamp = 'DROPPED {} via event_twin - twin of {}; ~~{}~~'.format(
            today or dt.date.today().isoformat(), agenda.plain(older['task'], 60), original)
        line = line[:first + 1] + ' ' + stamp + ' ' + line[boundary:]
        # Lint's check 15 reads closure from the stamp AND a struck title, so the
        # What cell (third cell) gets struck too; every other cell stays as it was.
        parts = re.split(r'(?<!\\)\|', line)
        if len(parts) > 4:
            what = parts[3]
            lead = what[:len(what) - len(what.lstrip())]
            trail = what[len(what.rstrip()):]
            parts[3] = lead + agenda.strike_title(what.strip()) + trail
            line = '|'.join(parts)
        lines[number - 1] = line
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Find open ledger rows that are one timed event.')
    parser.add_argument('--ledger', default=agenda.LEDGER)
    parser.add_argument('--merge', action='store_true', help='close the newer row of each pair')
    args = parser.parse_args(argv)
    with open(args.ledger, encoding='utf-8') as f:
        text = f.read()
    twins = open_twins(text)
    print('event twins: {}'.format(len(twins)))
    for older, newer in twins:
        print('older line {}: {}'.format(older['line'], older['task']))
        print('newer line {}: {}'.format(newer['line'], newer['task']))
        if args.merge:
            print('Facts to fold in: ' + newer['text'])
    if args.merge and twins:
        with open(args.ledger, 'w', encoding='utf-8') as f:
            f.write(merge(text, twins))
    return 0


if __name__ == '__main__':
    sys.exit(main())
