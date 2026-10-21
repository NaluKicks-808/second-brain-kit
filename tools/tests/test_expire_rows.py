#!/usr/bin/env python3
"""Tests for tools/expire_rows.py. Run: python3 tools/tests/test_expire_rows.py"""
import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import expire_rows as er  # noqa: E402

HEAD = "# L\n\n## Open\n\n| Trigger | Type | What to surface | Why it matters |\n|---|---|---|---|\n"
TAIL = "\n## Done\n\n| Trigger | Type | What to surface | Why it matters |\n|---|---|---|---|\n"
NOW = dt.datetime(2026, 10, 21, 12, 0)

PAST = "| 2026-10-20 | Date | **Shop closed right now.** detail | gone soon expires: 2026-10-21T09:00 |"
FUTURE = "| 2026-10-20 | Date | **Call at 3pm.** | expires: 2026-10-21T15:00 |"
PLAIN = "| 2026-10-20 | Date | **No marker.** | nothing |"
BAD = "| 2026-10-20 | Date | **Bad marker.** | expires: 2026-13-45T99:99 |"


def led(*rows):
    return HEAD + "\n".join(rows) + "\n" + TAIL


class Expire(unittest.TestCase):
    def test_only_past_closed(self):
        new, closed = er.expire_text(led(PAST, FUTURE, PLAIN, BAD), NOW)
        self.assertEqual(len(closed), 1)
        lines = new.split("\n")
        hit = [l for l in lines if "Shop closed" in l][0]
        self.assertTrue(hit.startswith("| DROPPED 2026-10-21 via expired - 2026-10-20 |"))
        self.assertIn("**~~Shop closed right now.~~**", hit)
        self.assertIn("expires: 2026-10-21T09:00", hit)
        for row in (FUTURE, PLAIN, BAD):
            self.assertIn(row, lines)

    def test_title_without_bold_is_struck_whole(self):
        row = "| 2026-10-20 | Date | Shop closed right now | expires: 2026-10-21T09:00 |"
        new, closed = er.expire_text(led(row), NOW)
        self.assertEqual(len(closed), 1)
        self.assertIn("| ~~Shop closed right now~~ |", new)

    def test_exact_moment_closes(self):
        _, closed = er.expire_text(led(FUTURE), dt.datetime(2026, 10, 21, 15, 0))
        self.assertEqual(len(closed), 1)

    def test_idempotent(self):
        once, _ = er.expire_text(led(PAST), NOW)
        twice, closed = er.expire_text(once, NOW + dt.timedelta(days=3))
        self.assertEqual(once, twice)
        self.assertEqual(closed, [])

    def test_done_section_untouched(self):
        text = led(PLAIN) + PAST + "\n"
        new, closed = er.expire_text(text, NOW)
        self.assertEqual(closed, [])
        self.assertEqual(new, text)

    def test_closed_row_skipped(self):
        row = PAST.replace("| 2026-10-20 |", "| DONE 2026-10-20 |", 1)
        self.assertEqual(er.expire_text(led(row), NOW)[1], [])

    def test_cli_dry_run_and_write(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.md")
            text = led(PAST)
            open(p, "w").write(text)
            self.assertEqual(er.main(["--ledger", p, "--dry-run"]), 0)
            self.assertEqual(open(p).read(), text)
            # real clock is far past 2026-10-21T09:00 or not; force by an old expiry
            old = text.replace("2026-10-21T09:00", "2000-01-01T00:00")
            open(p, "w").write(old)
            er.main(["--ledger", p])
            self.assertIn("DROPPED", open(p).read())
            snap = open(p).read()
            er.main(["--ledger", p])
            self.assertEqual(open(p).read(), snap)

    def test_missing_ledger(self):
        self.assertEqual(er.main(["--ledger", "/nonexistent/x.md"]), 1)


if __name__ == "__main__":
    unittest.main()
