#!/usr/bin/env python3
"""Tests for tools/lint.py: the checks added after the first thirteen, plus the old ones'
extensions (heading repeats in check 10, empty ledger rows in check 13), and one test that
the original honesty checks still catch a broken link.

HOW IT RUNS. lint.py finds the vault root from its own location, so each test builds a
small throwaway vault under a temp directory, copies lint.py and guess_words.py into its
tools/, and runs `python3 tools/lint.py` there as a subprocess. Nothing touches the real
vault. Checks that read origin/main get a real bare remote next to the throwaway vault, so
"added since origin/main" means exactly what it means in life.

EVERY NEW CHECK gets a positive case (it fires, and a blocking one makes the exit code 1)
and a negative case (the nearest honest input stays quiet), because a check that never
fires and a check that always fires both print a tidy report.

Run it directly:   python3 tools/tests/test_lint.py
"""
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
GIT = shutil.which("git")
TODAY = datetime.date.today().isoformat()

README = (
    "# Test vault\n\n`wiki/` holds pages, `raw/entries/` holds sources, `tools/` holds "
    "the gates.\n"
)
PAGE = "---\ntype: topic\nupdated: %s\nsources: none\n---\n\n# Page\n\nA plain sentence.\n" % TODAY
INDEX = "---\ntype: index\nupdated: %s\nsources: none\n---\n\n# Index\n\n## Pages\n\n- [[page]] - a page\n" % TODAY
LOG = "---\ntype: log\nupdated: %s\nsources: none\n---\n\n# Log\n\n## [%s] absorb | start\n" % (TODAY, TODAY)
LEDGER_HEAD = (
    "---\ntype: ledger\nupdated: %s\nsources: none\n---\n\n# Reminders\n\n## Open\n\n"
    "| Trigger | Type | What to surface | Why it matters |\n|---|---|---|---|\n" % TODAY
)
POSTMORTEMS_HEAD = "---\ntype: postmortems\nupdated: %s\nsources: none\n---\n\n# Postmortems\n\n## Entries\n\n" % TODAY


class Vault:
    """A throwaway vault with lint.py installed, optionally with an origin/main."""

    def __init__(self, test):
        self.root = Path(tempfile.mkdtemp(prefix="lint-test-"))
        test.addCleanup(shutil.rmtree, str(self.root), ignore_errors=True)
        for rel, text in {
            "README.md": README,
            "wiki/_index.md": INDEX,
            "wiki/log.md": LOG,
            "wiki/page.md": PAGE,
        }.items():
            self.write(rel, text)
        (self.root / "raw" / "entries").mkdir(parents=True)
        (self.root / "tools" / "tests").mkdir(parents=True)
        for name in ("lint.py", "guess_words.py"):
            shutil.copy(str(TOOLS / name), str(self.root / "tools" / name))
        self.remote = None

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def append(self, rel, text):
        with open(str(self.root / rel), "a", encoding="utf-8") as fh:
            fh.write(text)

    def git(self, *args, cwd=None):
        return subprocess.run(
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=t"] + list(args),
            cwd=str(cwd or self.root), capture_output=True, text=True)

    def init_git(self):
        self.git("init", "-q")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")

    def commit_all(self):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "snapshot")

    def push_origin(self):
        """Commit what is here and publish it as origin/main."""
        self.init_git()
        self.commit_all()
        self.remote = Path(tempfile.mkdtemp(prefix="lint-test-remote-"))
        self.git("init", "-q", "--bare", cwd=self.remote)
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-q", "origin", "main")
        self.git("fetch", "-q", "origin")

    def run(self, env=None, edit_lint=None):
        """Commit the tree (so only genuinely untracked things are untracked), run lint."""
        if (self.root / ".git").exists():
            self.commit_all()
        if edit_lint:
            path = self.root / "tools" / "lint.py"
            text = path.read_text(encoding="utf-8")
            for old, new in edit_lint:
                assert old in text, old
                text = text.replace(old, new)
            path.write_text(text, encoding="utf-8")
        full_env = dict(os.environ)
        full_env.pop("LINT_POSTMORTEM_FAMILY_FROM", None)
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            full_env.pop(key, None)
        full_env.update(env or {})
        out = subprocess.run([sys.executable, str(self.root / "tools" / "lint.py")],
                             cwd=str(self.root), capture_output=True, text=True, env=full_env)
        return out.returncode, out.stdout + out.stderr


def lines_with(out, tag):
    return [l for l in out.split("\n") if l.startswith("  " + tag + " ")]


class BaselineTests(unittest.TestCase):
    def test_clean_vault_passes(self):
        v = Vault(self)
        v.init_git()
        rc, out = v.run()
        self.assertEqual(rc, 0, out)

    def test_old_check_still_fires(self):
        v = Vault(self)
        v.append("wiki/page.md", "\nSee [[nowhere-at-all]].\n")
        rc, out = v.run()
        self.assertEqual(rc, 1, out)
        self.assertTrue(lines_with(out, "BROKEN"), out)


class DuplicateHeadingTests(unittest.TestCase):
    """Check 10, second rule."""

    def test_repeated_heading_blocks(self):
        v = Vault(self)
        v.append("wiki/_index.md", "\n## Pages\n\n- [[page]] again\n")
        v.init_git()
        rc, out = v.run()
        self.assertEqual(rc, 1, out)
        self.assertTrue(any("repeats the heading" in l for l in lines_with(out, "DUPLICATE")), out)

    def test_same_heading_under_different_parents_is_fine(self):
        v = Vault(self)
        v.write("wiki/_index.md", INDEX + "\n### Other\n\n- [[page]] one\n\n## More\n\n### Other\n\n- [[page]] two\n")
        v.init_git()
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertFalse(lines_with(out, "DUPLICATE"), out)

    def test_repeat_inside_a_fence_is_ignored(self):
        v = Vault(self)
        v.append("wiki/_index.md", "\n```\n## Pages\n```\n")
        v.init_git()
        rc, out = v.run()
        self.assertEqual(rc, 0, out)


class LedgerShapeTests(unittest.TestCase):
    """Check 13 extensions."""

    def test_empty_row_blocks(self):
        v = Vault(self)
        v.write("wiki/_reminders.md", LEDGER_HEAD + "|  | Date |  | because |\n")
        rc, out = v.run()
        self.assertEqual(rc, 1, out)
        self.assertTrue(any("empty Trigger" in l for l in lines_with(out, "LEDGER")), out)

    def test_filled_row_passes(self):
        v = Vault(self)
        v.write("wiki/_reminders.md", LEDGER_HEAD + "| 2099-01-01 | Date | Do the thing | because |\n")
        rc, out = v.run()
        self.assertEqual(rc, 0, out)

    def test_tag_required_only_when_configured(self):
        v = Vault(self)
        v.write("wiki/_reminders.md", LEDGER_HEAD + "| 2099-01-01 | Date | Do the thing | because |\n")
        rc, out = v.run()
        self.assertEqual(rc, 0, out)                       # default: tags not demanded
        rc, out = v.run(edit_lint=[("'ledger_require_tag': False", "'ledger_require_tag': True")])
        self.assertEqual(rc, 1, out)
        self.assertTrue(any("[area" in l for l in lines_with(out, "LEDGER")), out)
        v.write("wiki/_reminders.md",
                LEDGER_HEAD + "| 2099-01-01 | Date | [shop · small] Do the thing | because |\n")
        rc, out = v.run()
        self.assertEqual(rc, 0, out)


class AnsweredQuestionTests(unittest.TestCase):
    """Check 14."""

    FM = "---\ntype: bank\nupdated: %s\nsources: none\n---\n" % TODAY

    def bank(self, v, body):
        v.write("wiki/_question-bank.md", self.FM + body)
        v.append("wiki/_index.md", "- [[_question-bank]] - questions\n")

    def test_undated_answer_warns_without_blocking(self):
        v = Vault(self)
        self.bank(v, "# Questions\n\n\u2705 Is the shop open on Sundays? Yes.\n")
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(lines_with(out, "qbank/warn")), 1, out)

    def test_dated_answers_are_quiet(self):
        v = Vault(self)
        self.bank(v,
                "# Questions\n\n"
                "✅ Is the shop open on Sundays? Yes, 2026-05-01.\n"
                "- ✅ Who pays for parts?\n  - **A (2026-05-02):** the shop.\n\n"
                "## Resolved 2026-05-03\n\n✅ Which brand?\n")
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertFalse(lines_with(out, "qbank/warn"), out)

    def test_no_question_bank_is_silent(self):
        v = Vault(self)
        rc, out = v.run()
        self.assertFalse(lines_with(out, "qbank/warn"), out)


@unittest.skipUnless(GIT, "git not installed")
class ClosingStampTests(unittest.TestCase):
    """Checks 15 and 16, which read ledger lines added since origin/main."""

    def base(self):
        v = Vault(self)
        v.write("wiki/_reminders.md", LEDGER_HEAD)
        v.push_origin()
        return v

    def test_half_closed_row_blocks(self):
        v = self.base()
        v.append("wiki/_reminders.md",
                 "| DONE 2026-09-01 by hand | Date | **Send the quote** | because |\n")
        rc, out = v.run()
        self.assertEqual(rc, 1, out)
        found = lines_with(out, "HALFCLOSED")
        self.assertEqual(len(found), 1, out)
        self.assertIn("struck through", found[0])
        self.assertIn("DONE YYYY-MM-DD via", found[0])

    def test_properly_closed_row_passes(self):
        v = self.base()
        v.append("wiki/_reminders.md",
                 "| DONE 2026-09-01 via sam — **2026-08-30** | Date | **~~Send the quote~~** | because |\n")
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertFalse(lines_with(out, "HALFCLOSED"), out)

    def test_old_half_closed_row_is_not_read(self):
        v = Vault(self)
        v.write("wiki/_reminders.md",
                LEDGER_HEAD + "| DONE 2026-09-01 by hand | Date | **Send the quote** | because |\n")
        v.push_origin()                                   # already on origin/main: legacy
        rc, out = v.run()
        self.assertEqual(rc, 0, out)

    def test_no_origin_is_quiet(self):
        v = Vault(self)
        v.write("wiki/_reminders.md",
                LEDGER_HEAD + "| DONE 2026-09-01 by hand | Date | **Send the quote** | because |\n")
        v.init_git()
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertIn("not checked", out)

    def test_script_closing_a_future_row_blocks(self):
        v = self.base()
        v.append("wiki/_reminders.md",
                 "| DONE 2026-09-01 via sync.py — **2026-09-20** | Date | **~~Renew the lease~~** | because |\n")
        rc, out = v.run()
        self.assertEqual(rc, 1, out)
        found = lines_with(out, "TOOLEARLY")
        self.assertEqual(len(found), 1, out)
        self.assertIn("sync.py", found[0])

    def test_script_closing_a_due_row_passes(self):
        v = self.base()
        v.append("wiki/_reminders.md",
                 "| DONE 2026-09-21 via sync.py — **2026-09-20** | Date | **~~Renew the lease~~** | because |\n")
        rc, out = v.run()
        self.assertEqual(rc, 0, out)

    def test_person_closing_early_passes(self):
        v = self.base()
        v.append("wiki/_reminders.md",
                 "| DONE 2026-09-01 via sam — **2026-09-20** | Date | **~~Renew the lease~~** | because |\n")
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertFalse(lines_with(out, "TOOLEARLY"), out)


class TestHygieneTests(unittest.TestCase):
    """Checks 17, 18 and 19."""

    GOOD = ("import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n"
            "        self.assertTrue(True)\n\n\nif __name__ == '__main__':\n    unittest.main()\n")

    def test_good_file_passes_all_three(self):
        v = Vault(self)
        v.write("tools/tests/test_good.py", self.GOOD)
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        for tag in ("FIXTURE", "DISCOVERY", "RUNNER"):
            self.assertFalse(lines_with(out, tag), out)

    def test_fixture_in_own_directory_blocks(self):
        v = Vault(self)
        v.write("tools/tests/test_bad.py",
                "import os\nimport unittest\nFIX = os.path.join(os.path.dirname(__file__), '_tmp.json')\n"
                "if __name__ == '__main__':\n    unittest.main()\n")
        rc, out = v.run()
        self.assertEqual(rc, 1, out)
        self.assertTrue(any("_tmp.json" in l for l in lines_with(out, "FIXTURE")), out)

    def test_pathlib_fixture_in_own_directory_blocks(self):
        v = Vault(self)
        v.write("tools/tests/test_bad2.py",
                "from pathlib import Path\nimport unittest\nHERE = Path(__file__).resolve().parent\n"
                "FIX = HERE / '_tmp.json'\nif __name__ == '__main__':\n    unittest.main()\n")
        rc, out = v.run()
        self.assertEqual(rc, 1, out)
        self.assertTrue(lines_with(out, "FIXTURE"), out)

    def test_climbing_to_the_tools_directory_is_not_a_fixture(self):
        v = Vault(self)
        v.write("tools/tests/test_up.py",
                "from pathlib import Path\nimport os, unittest\nA = Path(__file__).resolve().parent.parent\n"
                "B = os.path.join(os.path.dirname(__file__), '..')\nC = Path(__file__).resolve().parent / '..'\n"
                "if __name__ == '__main__':\n    unittest.main()\n")
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertFalse(lines_with(out, "FIXTURE"), out)

    def test_unparseable_test_file_only_warns(self):
        v = Vault(self)
        v.write("tools/tests/test_half.py", "def (:\n")
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertTrue(lines_with(out, "fixture/warn"), out)

    def test_file_outside_the_pattern_blocks(self):
        v = Vault(self)
        v.write("tools/tests/check_things.py", self.GOOD)
        rc, out = v.run()
        self.assertEqual(rc, 1, out)
        self.assertTrue(lines_with(out, "DISCOVERY"), out)

    def test_declared_helper_is_allowed(self):
        v = Vault(self)
        v.write("tools/tests/helpers.py", '"""Shared fixtures. NOT A TEST MODULE."""\nX = 1\n')
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertFalse(lines_with(out, "DISCOVERY"), out)

    def test_runner_not_last_blocks(self):
        v = Vault(self)
        v.write("tools/tests/test_early.py",
                "import unittest\n\n\nclass A(unittest.TestCase):\n    def test_a(self):\n        pass\n\n\n"
                "if __name__ == '__main__':\n    unittest.main()\n\n\n"
                "class B(unittest.TestCase):\n    def test_b(self):\n        pass\n")
        rc, out = v.run()
        self.assertEqual(rc, 1, out)
        found = lines_with(out, "RUNNER")
        self.assertEqual(len(found), 1, out)
        self.assertIn("never reaches", found[0])

    def test_runner_inside_a_method_or_function_is_ignored(self):
        v = Vault(self)
        v.write("tools/tests/test_deferred.py",
                "import unittest\n\n\ndef go():\n    unittest.main()\n\n\n"
                "class A(unittest.TestCase):\n    def test_a(self):\n        pass\n")
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertFalse(lines_with(out, "RUNNER"), out)

    def test_no_tests_directory_is_skipped(self):
        v = Vault(self)
        shutil.rmtree(str(v.root / "tools" / "tests"))
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertIn("no tests directory", out)


@unittest.skipUnless(GIT, "git not installed")
class GuessWordTests(unittest.TestCase):
    """Check 20."""

    def test_new_guess_word_warns_without_blocking(self):
        v = Vault(self)
        v.push_origin()
        v.append("wiki/page.md", "\nShe has clearly decided to leave.\n")
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        found = lines_with(out, "guess/warn")
        self.assertEqual(len(found), 1, out)
        self.assertIn("clearly", found[0])

    def test_quoted_callout_and_code_are_exempt(self):
        v = Vault(self)
        v.push_origin()
        v.append("wiki/page.md",
                 '\nHe said "this is clearly broken" in the note.\n\n'
                 "> [!question] Did she presumably leave?\n\n`must have` is a code span.\n")
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertFalse(lines_with(out, "guess/warn"), out)

    def test_old_guess_word_is_not_read(self):
        v = Vault(self)
        v.append("wiki/page.md", "\nIt was clearly a mistake.\n")
        v.push_origin()                                   # already on origin/main
        rc, out = v.run()
        self.assertFalse(lines_with(out, "guess/warn"), out)

    def test_no_origin_is_quiet(self):
        v = Vault(self)
        v.append("wiki/page.md", "\nIt was clearly a mistake.\n")
        v.init_git()
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertFalse(lines_with(out, "guess/warn"), out)
        self.assertIn("skipped", out)

    def test_missing_module_is_silent(self):
        v = Vault(self)
        (v.root / "tools" / "guess_words.py").unlink()
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertIn("no guess_words.py", out)


class PostmortemTests(unittest.TestCase):
    """Checks 21 and 22."""

    def entry(self, n, extra="", style="###"):
        return "%s #%d (2026-01-0%d): something broke\n\n**What happened.** It broke.\n\n%s\n" % (
            style, n, n, extra)

    def test_duplicate_number_blocks(self):
        v = Vault(self)
        v.write("wiki/_postmortems.md", POSTMORTEMS_HEAD + self.entry(1) + "\n" + self.entry(2) + "\n" + self.entry(2))
        rc, out = v.run()
        self.assertEqual(rc, 1, out)
        found = lines_with(out, "POSTNUM")
        self.assertEqual(len(found), 1, out)
        self.assertIn("#2", found[0])

    def test_duplicate_number_in_the_dotted_style_blocks(self):
        v = Vault(self)
        v.write("wiki/_postmortems.md", POSTMORTEMS_HEAD + "## 1. one\n\ntext\n\n## 1. again\n\ntext\n")
        rc, out = v.run()
        self.assertEqual(rc, 1, out)
        self.assertTrue(lines_with(out, "POSTNUM"), out)

    def test_unique_numbers_pass(self):
        v = Vault(self)
        v.write("wiki/_postmortems.md", POSTMORTEMS_HEAD + self.entry(1) + "\n" + self.entry(2))
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertFalse(lines_with(out, "POSTNUM"), out)
        self.assertFalse(lines_with(out, "postnum/warn"), out)

    def test_gap_only_warns(self):
        v = Vault(self)
        v.write("wiki/_postmortems.md", POSTMORTEMS_HEAD + self.entry(1) + "\n" + self.entry(3))
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        found = lines_with(out, "postnum/warn")
        self.assertEqual(len(found), 1, out)
        self.assertIn("#2", found[0])

    def test_number_in_prose_or_fence_is_not_a_heading(self):
        v = Vault(self)
        v.write("wiki/_postmortems.md",
                POSTMORTEMS_HEAD + self.entry(1, "Compare #1 and #1 in prose.\n\n```\n### #1 (x): fenced\n```\n"))
        rc, out = v.run()
        self.assertEqual(rc, 0, out)

    def test_no_file_is_silent(self):
        v = Vault(self)
        rc, out = v.run()
        self.assertFalse(lines_with(out, "POSTNUM"), out)
        self.assertIn("no wiki/_postmortems.md here", out)

    FAMILY = ("**Family:** a price was wrong\n\n**Neighbours:** none: searched price, quote\n\n"
              "**Outcome check:** compare the page to the shop sheet; it exists\n")

    def test_family_lines_are_off_by_default(self):
        v = Vault(self)
        v.write("wiki/_postmortems.md", POSTMORTEMS_HEAD + self.entry(1))
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertIn("off", out)

    def test_missing_family_lines_block_when_enabled(self):
        v = Vault(self)
        v.write("wiki/_postmortems.md", POSTMORTEMS_HEAD + self.entry(1) + "\n" + self.entry(2))
        rc, out = v.run(env={"LINT_POSTMORTEM_FAMILY_FROM": "2"})
        self.assertEqual(rc, 1, out)
        found = lines_with(out, "POSTFAM")
        self.assertEqual(len(found), 1, out)                # #1 is grandfathered
        self.assertIn("#2", found[0])
        for label in ("Family", "Neighbours", "Outcome check"):
            self.assertIn("**%s:**" % label, found[0])

    def test_complete_family_lines_pass_when_enabled(self):
        v = Vault(self)
        v.write("wiki/_postmortems.md", POSTMORTEMS_HEAD + self.entry(1) + "\n" + self.entry(2, self.FAMILY))
        rc, out = v.run(env={"LINT_POSTMORTEM_FAMILY_FROM": "2"})
        self.assertEqual(rc, 0, out)
        self.assertFalse(lines_with(out, "POSTFAM"), out)

    def test_neighbours_needs_a_number_or_a_search(self):
        v = Vault(self)
        weak = self.FAMILY.replace("none: searched price, quote", "nothing similar")
        v.write("wiki/_postmortems.md", POSTMORTEMS_HEAD + self.entry(1, weak))
        rc, out = v.run(env={"LINT_POSTMORTEM_FAMILY_FROM": "1"})
        self.assertEqual(rc, 1, out)
        self.assertTrue(any("Neighbours" in l for l in lines_with(out, "POSTFAM")), out)

    def test_empty_label_counts_as_missing(self):
        v = Vault(self)
        v.write("wiki/_postmortems.md", POSTMORTEMS_HEAD + self.entry(1, "**Family:**\n\n**Neighbours:** #1\n\n**Outcome check:** x\n"))
        rc, out = v.run(env={"LINT_POSTMORTEM_FAMILY_FROM": "1"})
        self.assertEqual(rc, 1, out)

    def test_subheading_inside_an_entry_does_not_end_it(self):
        v = Vault(self)
        body = "#### Detail\n\nmore\n\n" + self.FAMILY
        v.write("wiki/_postmortems.md", POSTMORTEMS_HEAD + self.entry(1, body))
        rc, out = v.run(env={"LINT_POSTMORTEM_FAMILY_FROM": "1"})
        self.assertEqual(rc, 0, out)


class TopLevelMapTests(unittest.TestCase):
    """Check 23."""

    def test_unlisted_folder_blocks(self):
        v = Vault(self)
        (v.root / "scratch").mkdir()
        v.write("scratch/notes.txt", "x\n")
        rc, out = v.run()
        self.assertEqual(rc, 1, out)
        found = lines_with(out, "TOPMAP")
        self.assertEqual(len(found), 1, out)
        self.assertIn("scratch/", found[0])

    def test_listed_folder_passes(self):
        v = Vault(self)
        (v.root / "scratch").mkdir()
        v.write("scratch/notes.txt", "x\n")
        v.append("README.md", "\n`scratch/` is where loose notes wait.\n")
        rc, out = v.run()
        self.assertEqual(rc, 0, out)
        self.assertFalse(lines_with(out, "TOPMAP"), out)

    def test_a_path_inside_backticks_names_its_folder(self):
        v = Vault(self)
        (v.root / "inbox").mkdir()
        v.write("inbox/a.txt", "x\n")
        v.append("README.md", "\nDrop things in `inbox/today/`.\n")
        rc, out = v.run()
        self.assertEqual(rc, 0, out)

    def test_gitignored_folder_still_blocks(self):
        v = Vault(self)
        v.write(".gitignore", "private/\n")
        (v.root / "private").mkdir()
        v.write("private/secret.txt", "x\n")
        v.init_git()
        rc, out = v.run()
        self.assertEqual(rc, 1, out)
        self.assertTrue(any("private/" in l for l in lines_with(out, "TOPMAP")), out)

    def test_exempt_and_git_folders_are_ignored(self):
        v = Vault(self)
        for d in (".obsidian", "hooks", ".claude"):
            (v.root / d).mkdir()
            v.write(d + "/x.txt", "x\n")
        v.init_git()
        rc, out = v.run()
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
