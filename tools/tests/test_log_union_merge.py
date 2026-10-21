#!/usr/bin/env python3
"""Tests for the .gitattributes rule `wiki/log.md merge=union`.

WHY IT EXISTS. wiki/log.md is append-only, and several sessions run at once, so two of them
appending a block to its end within minutes of each other is the ordinary day. Without a merge
rule git sees two edits at the same place - the end of the file - and writes conflict markers,
which lint.py then refuses and safe_commit.sh stops on. A union merge keeps both sides.

WHAT IS PINNED. The rule is read from the REAL .gitattributes at the repository root, never
retyped here, and put into a throwaway repository where two clones really append different
blocks. Both ways a session meets the collision are exercised: a merge, and the `pull --rebase`
that safe_commit.sh actually runs. And the rule's limit is pinned too: any OTHER file must still
conflict, because a union merge that kept both halves of a genuine disagreement in a wiki page
would be silent corruption. Everything is built in a temporary directory.

    python3 tools/tests/test_log_union_merge.py
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
REAL_ATTRS = ROOT / ".gitattributes"
HEAD = "# change log (append-only)\n\n## [2026-09-29] build | the entry both sides share\n"
MINE = "\n## [2026-09-30] absorb | this session's block\n\nIts body.\n"
THEIRS = "\n## [2026-09-30] fix | the other session's block\n\nIts body.\n"


def _env():
    env = dict(os.environ)
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                 "GIT_OBJECT_DIRECTORY", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT"):
        env.pop(name, None)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


class UnionMergeCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="log-union-test-"))
        self.env = _env()
        self.origin = self.tmp / "origin.git"
        self.a = self.tmp / "a"
        self.b = self.tmp / "b"
        self.git(self.tmp, "-c", "init.defaultBranch=main", "init", "--quiet", "--bare", str(self.origin))
        self.git(self.tmp, "clone", "--quiet", str(self.origin), str(self.a))
        self.git(self.a, "symbolic-ref", "HEAD", "refs/heads/main")
        for repo in (self.a,):
            self.ident(repo)
        (self.a / "wiki").mkdir()
        (self.a / "wiki" / "log.md").write_text(HEAD, encoding="utf-8")
        (self.a / "wiki" / "page.md").write_text("one line\n", encoding="utf-8")
        if REAL_ATTRS.exists():
            shutil.copy(str(REAL_ATTRS), str(self.a / ".gitattributes"))
        self.git(self.a, "add", "-A")
        self.git(self.a, "commit", "--quiet", "-m", "base")
        self.git(self.a, "push", "--quiet", "origin", "main")
        self.git(self.tmp, "clone", "--quiet", str(self.origin), str(self.b))
        self.ident(self.b)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, cwd, *args, check=True):
        proc = subprocess.run(["git"] + list(args), cwd=str(cwd), env=self.env,
                              capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise AssertionError("git %s failed:\n%s%s" % (" ".join(args), proc.stdout, proc.stderr))
        return proc

    def ident(self, repo):
        self.git(repo, "config", "user.email", "t@example.com")
        self.git(repo, "config", "user.name", "T")

    def append(self, repo, rel, text, msg):
        with open(repo / rel, "a", encoding="utf-8") as f:
            f.write(text)
        self.git(repo, "commit", "--quiet", "-am", msg)

    def both_sides_appended(self, rel="wiki/log.md", mine=MINE, theirs=THEIRS):
        self.append(self.b, rel, theirs, "the other session")
        self.git(self.b, "push", "--quiet", "origin", "main")
        self.append(self.a, rel, mine, "this session")

    def assert_clean_union(self, repo):
        log = (repo / "wiki" / "log.md").read_text(encoding="utf-8")
        for marker in ("<<<<<<< ", "=======\n", ">>>>>>> "):
            self.assertNotIn(marker, log)
        self.assertIn("this session's block", log)
        self.assertIn("the other session's block", log)
        self.assertTrue(log.startswith(HEAD), log)


class TheRuleIsThere(unittest.TestCase):

    def test_the_vault_declares_log_md_a_union_merge(self):
        self.assertTrue(REAL_ATTRS.exists(), "no .gitattributes at the repository root")
        lines = [l.split() for l in REAL_ATTRS.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.lstrip().startswith("#")]
        self.assertIn(["wiki/log.md", "merge=union"], lines)

    def test_only_log_md_is_a_union_merge(self):
        """Union is safe in an append-only file and nowhere else."""
        text = REAL_ATTRS.read_text(encoding="utf-8") if REAL_ATTRS.exists() else ""
        unions = [l.split()[0] for l in text.splitlines()
                  if "merge=union" in l and not l.lstrip().startswith("#")]
        self.assertEqual(unions, ["wiki/log.md"])


class TwoAppendsMerge(UnionMergeCase):

    def test_a_merge_keeps_both_blocks_without_markers(self):
        self.both_sides_appended()
        self.git(self.a, "fetch", "--quiet")
        proc = self.git(self.a, "merge", "--no-edit", "origin/main", check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assert_clean_union(self.a)

    def test_the_pull_rebase_safe_commit_runs_keeps_both_blocks(self):
        self.both_sides_appended()
        proc = self.git(self.a, "pull", "--rebase", "--quiet", check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assert_clean_union(self.a)
        log = (self.a / "wiki" / "log.md").read_text(encoding="utf-8")
        self.assertLess(log.index("the other session's block"), log.index("this session's block"),
                        "the rebased block lands after the one already pushed")

    def test_any_other_file_still_conflicts(self):
        self.both_sides_appended(rel="wiki/page.md", mine="mine\n", theirs="theirs\n")
        self.git(self.a, "fetch", "--quiet")
        proc = self.git(self.a, "merge", "--no-edit", "origin/main", check=False)
        self.assertNotEqual(proc.returncode, 0, "a wiki page must never union-merge")
        self.assertIn("<<<<<<< ", (self.a / "wiki" / "page.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
