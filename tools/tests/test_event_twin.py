#!/usr/bin/env python3
"""Tests for tools/event_twin.py. Run: python3 tools/tests/test_event_twin.py"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import event_twin as et  # noqa: E402

HEAD = "# L\n\n## Open\n\n| Trigger | Type | What to surface | Why it matters |\n|---|---|---|---|\n"


def ledger(*rows):
    return HEAD + "\n".join(rows) + "\n\n## Done\n\n| Trigger | Type | What to surface | Why it matters |\n|---|---|---|---|\n"


A = "| 2026-10-23 14:30 | Date | **Dentist checkup downtown clinic** | because |"
B = "| 2026-10-23 14:30 | Date | `[health · quick]` **Downtown clinic dentist visit** | again |"


class Twins(unittest.TestCase):
    def test_pair_found_lower_is_older(self):
        t = et.open_twins(ledger(A, B))
        self.assertEqual(len(t), 1)
        older, newer = t[0]
        self.assertIn("Downtown clinic dentist", older["task"])
        self.assertIn("Dentist checkup", newer["task"])

    def test_different_time_or_date_no_pair(self):
        self.assertEqual(et.open_twins(ledger(A, B.replace("14:30", "15:30"))), [])
        self.assertEqual(et.open_twins(ledger(A, B.replace("10-23", "10-24"))), [])

    def test_no_time_no_pair(self):
        a = A.replace(" 14:30", "")
        b = B.replace(" 14:30", "")
        self.assertEqual(et.open_twins(ledger(a, b)), [])

    def test_tag_time_counts(self):
        a = "| 2026-10-23 | Date | `[x · quick · 14:30]` **Dentist checkup downtown clinic** | w |"
        b = "| 2026-10-23 | Date | `[x · quick · 14:30]` **Downtown clinic dentist visit** | w |"
        self.assertEqual(len(et.open_twins(ledger(a, b))), 1)

    def test_weak_overlap_no_pair(self):
        b = "| 2026-10-23 14:30 | Date | **Dentist payroll review** | w |"
        self.assertEqual(et.open_twins(ledger(A, b)), [])

    def test_closed_and_overdue_notices_skipped(self):
        closed = B.replace("| 2026-10-23 14:30 |", "| DONE 2026-10-23 |", 1)
        self.assertEqual(et.open_twins(ledger(A, closed)), [])
        struck = B.replace("**Downtown clinic dentist visit**", "**~~Downtown clinic dentist visit~~**")
        self.assertEqual(et.open_twins(ledger(A, struck)), [])
        overdue = "| 2026-10-23 14:30 | Date | **Overdue since Monday: dentist checkup downtown clinic** | w |"
        self.assertEqual(et.open_twins(ledger(A, overdue)), [])

    def test_event_type_rows_and_done_section_ignored(self):
        e = A.replace("| Date |", "| Event |")
        self.assertEqual(et.open_twins(ledger(A, e)), [])
        text = ledger(A) + B + "\n"   # B sits after ## Done
        self.assertEqual(et.open_twins(text), [])

    def test_merge_stamps_only_newer_trigger(self):
        text = ledger(A, B)
        t = et.open_twins(text)
        out = et.merge(text, t, today="2026-10-20")
        newer_line = [l for l in out.split("\n") if "Dentist checkup" in l][0]
        self.assertTrue(newer_line.startswith("| DROPPED 2026-10-20 via event_twin - twin of"))
        self.assertIn("~~2026-10-23 14:30~~", newer_line)
        self.assertIn("**~~Dentist checkup downtown clinic~~** | because |", newer_line)
        self.assertIn(B, out)
        self.assertEqual(et.open_twins(out), [])      # closed now: idempotent
        self.assertEqual(et.merge(out, et.open_twins(out), "2026-10-21"), out)

    def test_cli_reports_and_merges(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.md")
            open(p, "w").write(ledger(A, B))
            self.assertEqual(et.main(["--ledger", p]), 0)
            self.assertNotIn("DROPPED", open(p).read())
            et.main(["--ledger", p, "--merge"])
            self.assertIn("via event_twin", open(p).read())


if __name__ == "__main__":
    unittest.main()
