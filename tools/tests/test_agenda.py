#!/usr/bin/env python3
"""Tests for tools/agenda.py - what is actually open, read live from the ledger.

WHY THESE EXIST
agenda.py is a command rather than a rule so that an answer to "what is outstanding"
is never drawn from a stale reading of the ledger. Two ways it can go wrong silently:
it can show a closed row as live, or (worse, because nobody sees it) it can HIDE a live
row. The second happens if "struck-through text anywhere in the row" counts as closed:
a live row that quotes a superseded sentence in its detail prose vanishes. A closed
row is struck at the head of its title or carries a closure word at the head of a cell.

    python3 tools/tests/test_agenda.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LEDGER = """---
type: ledger
---
# Reminders

The `## Open` table below is the agenda.

## Open

| Trigger | Type | What to surface | Why it matters |
|---|---|---|---|
| 2026-01-05 | Date | Live dated row | why |
| DONE 2026-01-02 | Date | Finished row | why |
| after the launch | Condition | ~~Struck title~~ dropped | why |
| after the launch | Condition | **Live** row that quotes ~~an old sentence~~ in prose | why |
| when stock arrives | Event | `[shop · quick]` Tagged live row | why |
| DROPPED | Event | Dropped by trigger | why |

## Standing

| Trigger | Type | What to surface | Why it matters |
|---|---|---|---|
| always | Condition | Standing rule that must not reach the agenda | why |
"""


def make_vault(ledger=LEDGER):
    root = tempfile.mkdtemp(prefix='kit-agenda-')
    os.makedirs(os.path.join(root, 'tools'))
    os.makedirs(os.path.join(root, 'wiki'))
    shutil.copy(os.path.join(TOOLS, 'agenda.py'), os.path.join(root, 'tools', 'agenda.py'))
    if ledger is not None:
        with open(os.path.join(root, 'wiki', '_reminders.md'), 'w') as f:
            f.write(ledger)
    return root


def agenda(root, *args):
    p = subprocess.run([sys.executable, os.path.join(root, 'tools', 'agenda.py')] + list(args),
                       capture_output=True, text=True, cwd=tempfile.gettempdir())
    return p.returncode, p.stdout


class Agenda(unittest.TestCase):
    def setUp(self):
        self.root = make_vault()
        self.addCleanup(shutil.rmtree, self.root)

    def test_closed_rows_hidden(self):
        _, out = agenda(self.root)
        for gone in ('Finished row', 'Struck title', 'Dropped by trigger'):
            self.assertNotIn(gone, out)

    def test_live_rows_shown(self):
        _, out = agenda(self.root)
        self.assertIn('Live dated row', out)
        self.assertIn('Tagged live row', out)
        self.assertNotIn('`[shop', out)          # the tag is metadata, not printed

    def test_live_row_with_struck_prose_not_hidden(self):
        _, out = agenda(self.root)
        self.assertIn('Live row that quotes', out)

    def test_standing_section_never_reaches_agenda(self):
        _, out = agenda(self.root)
        self.assertNotIn('Standing rule', out)

    def test_all_flag_shows_closed_marked(self):
        _, out = agenda(self.root, '--all')
        self.assertIn('[CLOSED] ', out)
        self.assertIn('Finished row', out)

    def test_needle_filters_including_tag(self):
        _, out = agenda(self.root, 'quick')
        self.assertIn('Tagged live row', out)
        self.assertNotIn('Live dated row', out)

    def test_prose_mention_of_heading_does_not_empty_agenda(self):
        # The preamble names "## Open" in backticks; a plain string split would cut there.
        _, out = agenda(self.root)
        self.assertIn('Live dated row', out)

    def test_missing_ledger_is_reported_not_crash(self):
        root = make_vault(ledger=None)
        self.addCleanup(shutil.rmtree, root)
        code, out = agenda(root)
        self.assertEqual(code, 0)
        self.assertIn('no ledger', out)

    def test_is_closed_function(self):
        sys.path.insert(0, TOOLS)
        import agenda as mod
        self.assertTrue(mod.is_closed('DONE', 'x'))
        self.assertTrue(mod.is_closed('later', '**~~old~~** gone'))
        self.assertTrue(mod.is_closed('later', '`[a · b]` ~~old~~'))
        self.assertFalse(mod.is_closed('later', 'keep ~~old~~ text'))


if __name__ == '__main__':
    unittest.main(verbosity=1)
