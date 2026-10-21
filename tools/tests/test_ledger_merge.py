#!/usr/bin/env python3
"""Two writers adding ledger rows at the same spot merge instead of jamming.

Upstream adds two rows, a local uncommitted row sits at the same spot, and the autostash pop
conflicts. These tests rebuild that with a bare origin and two clones, all in a temp directory
(never this repository's own .git).

    python3 tools/tests/test_ledger_merge.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import ledger_merge as lm  # noqa: E402

LEDGER = """# Reminders

## Open

| Due | Area | What | Why |
|---|---|---|---|
| 2026-10-12 | now | **Old row.** | x |
| 2026-10-13 | date | **Journal.** | y |
"""
AFTER = "| 2026-10-12 | now | **Old row.** | x |\n"
ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
       "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t", "HOME": tempfile.gettempdir(), "GIT_TERMINAL_PROMPT": "0"}


class Resolve(unittest.TestCase):
    def test_two_pure_insertions_become_ours_then_theirs(self):
        text = "a\n<<<<<<< ours\nmine\n||||||| base\n=======\ntheirs1\ntheirs2\n>>>>>>> theirs\nb"
        out, left = lm.resolve(text)
        self.assertEqual((out, left), ("a\nmine\ntheirs1\ntheirs2\nb", 0))

    def test_the_same_row_added_on_both_sides_is_kept_once(self):
        text = "<<<<<<< ours\nrow\n||||||| base\n=======\nrow\n>>>>>>> theirs"
        self.assertEqual(lm.resolve(text), ("row", 0))

    def test_rows_added_above_a_row_the_other_side_closed_keep_both(self):
        """Upstream closed a row; the local stash had inserted its own rows just above that row."""
        text = ("<<<<<<< ours\n| DONE Closed |\n||||||| base\n| Closed |\n=======\n"
                "| now 1 |\n| now 2 |\n| Closed |\n>>>>>>> theirs")
        self.assertEqual(lm.resolve(text), ("| now 1 |\n| now 2 |\n| DONE Closed |", 0))

    def test_the_mirror_case_keeps_both_too(self):
        text = ("<<<<<<< ours\n| mine |\n| Closed |\n||||||| base\n| Closed |\n=======\n"
                "| DONE Closed |\n>>>>>>> theirs")
        self.assertEqual(lm.resolve(text), ("| mine |\n| DONE Closed |", 0))

    def test_an_edit_on_both_sides_keeps_its_markers(self):
        text = "<<<<<<< ours\nrow DONE\n||||||| base\nrow\n=======\nrow edited\n>>>>>>> theirs"
        out, left = lm.resolve(text)
        self.assertEqual(left, 1)
        self.assertIn("<<<<<<< ours", out)


class TwoClones(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = Path(self.tmp.name)
        self.origin, self.a, self.b = r / "origin.git", r / "a", r / "b"
        self.git(r, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(r, "clone", "-q", str(self.origin), str(self.a))
        (self.a / "wiki").mkdir()
        (self.a / "tools").mkdir()
        shutil.copy(str(TOOLS / "ledger_merge.py"), str(self.a / "tools/ledger_merge.py"))
        (self.a / ".gitattributes").write_text("wiki/_reminders.md merge=ledger-rows\n")
        (self.a / "wiki/_reminders.md").write_text(LEDGER)
        self.git(self.a, "add", "-A")
        self.git(self.a, "commit", "-qm", "base")
        self.git(self.a, "push", "-q", "origin", "HEAD:main")
        self.git(r, "clone", "-q", str(self.origin), str(self.b))

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, cwd, *args, check=True):
        p = subprocess.run(["git", *args], cwd=str(cwd), env=ENV, capture_output=True, text=True)
        if check and p.returncode:
            raise AssertionError("git {} failed: {}{}".format(args, p.stdout, p.stderr))
        return p

    def register(self, repo):
        self.git(repo, "config", "merge.ledger-rows.driver",
                 "{} tools/ledger_merge.py %O %A %B".format(sys.executable))

    def add_row(self, repo, row, after=AFTER):
        f = repo / "wiki/_reminders.md"
        f.write_text(f.read_text().replace(after, after + row, 1))

    def jam(self, register):
        """B pushes two rows; A has its own uncommitted row at the same spot and pulls."""
        self.add_row(self.b, "| 2026-10-14 | later | **Upstream row one.** | z |\n"
                             "| 2026-10-16 | later | **Upstream row two.** | z |\n")
        self.git(self.b, "commit", "-qam", "upstream rows")
        self.git(self.b, "push", "-q", "origin", "HEAD:main")
        if register:
            self.register(self.a)
        self.add_row(self.a, "| 2026-10-13 | now | **The local now row.** | w |\n")
        return self.git(self.a, "pull", "-q", "--rebase", "--autostash", "origin", "main", check=False)

    def unmerged(self, repo):
        return self.git(repo, "ls-files", "-u").stdout.strip()

    def test_with_the_driver_both_writers_rows_land_and_nothing_jams(self):
        self.jam(register=True)
        self.assertEqual(self.unmerged(self.a), "")
        text = (self.a / "wiki/_reminders.md").read_text()
        for row in ("Upstream row one", "Upstream row two", "The local now row", "Old row", "Journal"):
            self.assertEqual(text.count(row), 1, row)
        self.assertNotIn("<<<<<<<", text)

    def test_without_the_driver_the_same_pull_jams(self):
        """The jam, reproduced: this is what the driver changes."""
        self.jam(register=False)
        self.assertIn("wiki/_reminders.md", self.unmerged(self.a))

    def test_a_real_conflict_on_one_row_still_stops(self):
        f = self.b / "wiki/_reminders.md"
        f.write_text(f.read_text().replace("**Old row.** | x", "**Old row.** | closed by B"))
        self.git(self.b, "commit", "-qam", "b edits")
        self.git(self.b, "push", "-q", "origin", "HEAD:main")
        self.register(self.a)
        f = self.a / "wiki/_reminders.md"
        f.write_text(f.read_text().replace("**Old row.** | x", "**Old row.** | closed by A"))
        self.git(self.a, "pull", "-q", "--rebase", "--autostash", "origin", "main", check=False)
        self.assertIn("wiki/_reminders.md", self.unmerged(self.a))
        self.assertIn("<<<<<<<", (self.a / "wiki/_reminders.md").read_text())


if __name__ == "__main__":
    unittest.main()
