#!/usr/bin/env python3
"""Tests for tools/safe_commit.sh: the four faults the 2026-10-21 review found.

HOW IT RUNS. Each test copies this kit's tracked files (as they are on disk) into a throwaway
repository with a bare origin next to it, so pushes, fetches and replays happen for real.
Global and system git config are switched off, so nothing on this machine leaks in. Nothing
touches the real kit.

WHAT IS PINNED.
  1. A hooks folder outside the repository (core.hooksPath) is never written to; the gate is
     run in front of the commit instead.
  2. --commit-before-pull: the tree that is actually pushed (origin's main plus this commit,
     replayed in memory) is gated, and a broken link it would publish refuses the push.
  3. --no-verify stages only the block it appended to wiki/log.md, never another session's
     uncommitted lines in that file.
  4. With SECOND_BRAIN_COMMIT_BEFORE_PULL=1 exported, the rerun command printed after a replay
     conflict switches commit-first off, so the rerun pulls.

    python3 -m unittest tools.tests.test_safe_commit
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent.parent

PAT = ("---\ntype: person\nupdated: 2026-10-21\nsources: none\n---\n\n# Pat\n\n"
       "Pat works the weekend shift at [[riverside-cycle-works]].\n")


def _env(extra=None):
    env = dict(os.environ)
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                 "GIT_OBJECT_DIRECTORY", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
                 "SECOND_BRAIN_COMMIT_BEFORE_PULL"):
        env.pop(name, None)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.update(extra or {})
    return env


class SafeCommitCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="safe-commit-test-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.origin = self.tmp / "origin.git"
        self.a = self.tmp / "a"
        self.git(self.tmp, "-c", "init.defaultBranch=main", "init", "-q", "--bare", str(self.origin))
        self.git(self.tmp, "-c", "init.defaultBranch=main", "init", "-q", str(self.a))
        self.ident(self.a)
        files = subprocess.run(["git", "-C", str(KIT), "ls-files", "-z"], capture_output=True,
                               check=True, env=_env()).stdout.decode().split("\0")
        for rel in filter(None, files):
            src = KIT / rel
            if not src.is_file():
                continue
            dst = self.a / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
        (self.a / "wiki" / "people" / "pat.md").write_text(PAT, encoding="utf-8")
        idx = self.a / "wiki" / "_index.md"
        idx.write_text(idx.read_text(encoding="utf-8").replace(
            "## Projects", "- [[pat]], weekend mechanic.\n\n## Projects"), encoding="utf-8")
        self.git(self.a, "add", "-A")
        self.git(self.a, "commit", "-q", "--no-verify", "-m", "base")
        self.git(self.a, "remote", "add", "origin", str(self.origin))
        self.git(self.a, "push", "-q", "origin", "main")
        self.git(self.a, "fetch", "-q", "origin")
        self.git(self.a, "branch", "-q", "--set-upstream-to=origin/main", "main")

    def git(self, cwd, *args, check=True):
        r = subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True, text=True, env=_env())
        if check and r.returncode != 0:
            self.fail("git %s failed: %s%s" % (" ".join(args), r.stdout, r.stderr))
        return r.stdout.strip()

    def ident(self, repo):
        self.git(repo, "config", "user.name", "Test")
        self.git(repo, "config", "user.email", "test@example.com")

    def clone_b(self):
        b = self.tmp / "b"
        self.git(self.tmp, "clone", "-q", str(self.origin), str(b))
        self.ident(b)
        return b

    def safe_commit(self, *args, env=None):
        r = subprocess.run(["bash", "tools/safe_commit.sh"] + list(args), cwd=str(self.a),
                           capture_output=True, text=True, env=_env(env), timeout=200)
        return r.returncode, r.stdout + r.stderr

    def edit(self, repo, rel, old, new):
        p = repo / rel
        text = p.read_text(encoding="utf-8")
        self.assertIn(old, text)
        p.write_text(text.replace(old, new, 1), encoding="utf-8")

    def origin_main(self):
        return self.git(self.tmp, "--git-dir", str(self.origin), "rev-parse", "main")


class HooksOutsideTheRepo(SafeCommitCase):
    def test_shared_hooks_folder_is_never_written(self):
        shared = self.tmp / "shared-hooks"
        shared.mkdir()
        self.git(self.a, "config", "core.hooksPath", str(shared))
        self.edit(self.a, "wiki/people/sam-rivera.md", "Owner and lead", "Owner and head")
        rc, out = self.safe_commit("edit sam", "wiki/people/sam-rivera.md")
        self.assertEqual(rc, 0, out)
        self.assertIn("✓ pushed", out)
        self.assertIn("outside this repository", out)
        self.assertEqual(list(shared.iterdir()), [], out)

    def test_hooks_inside_the_repo_are_installed(self):
        self.edit(self.a, "wiki/people/sam-rivera.md", "Owner and lead", "Owner and head")
        rc, out = self.safe_commit("edit sam", "wiki/people/sam-rivera.md")
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.a / ".git" / "hooks" / "pre-commit").is_file(), out)


class CommitFirstGatesThePushedTree(SafeCommitCase):
    def test_broken_link_from_replay_is_refused(self):
        b = self.clone_b()
        (b / "wiki" / "people" / "pat.md").unlink()
        self.edit(b, "wiki/_index.md", "- [[pat]], weekend mechanic.\n\n", "")
        self.git(b, "add", "-A")
        self.git(b, "commit", "-q", "-m", "remove pat")
        self.git(b, "push", "-q", "origin", "main")
        theirs = self.origin_main()
        self.edit(self.a, "wiki/projects/riverside-cycle-works.md",
                  "with one part-time mechanic on weekends",
                  "with one part-time mechanic, [[pat]], on weekends")
        rc, out = self.safe_commit("--commit-before-pull", "link pat",
                                   "wiki/projects/riverside-cycle-works.md")
        self.assertEqual(rc, 1, out)
        self.assertIn("NOT PUBLISHED", out)
        self.assertEqual(self.origin_main(), theirs, out)

    def test_clean_replay_is_published(self):
        b = self.clone_b()
        self.edit(b, "wiki/people/sam-rivera.md", "Owner and lead", "Owner and head")
        self.git(b, "commit", "-q", "-am", "theirs")
        self.git(b, "push", "-q", "origin", "main")
        self.edit(self.a, "wiki/projects/riverside-cycle-works.md",
                  "with one part-time mechanic on weekends",
                  "with one part-time mechanic at weekends")
        rc, out = self.safe_commit("--commit-before-pull", "mine",
                                   "wiki/projects/riverside-cycle-works.md")
        self.assertEqual(rc, 0, out)
        self.assertIn("replayed tree gated clean", out)
        self.assertIn("✓ pushed", out)


class NoVerifyStagesOnlyItsBlock(SafeCommitCase):
    def test_other_sessions_log_lines_stay_unstaged(self):
        with open(str(self.a / "wiki" / "log.md"), "a", encoding="utf-8") as fh:
            fh.write("\n## [2026-10-21] absorb | ANOTHER SESSION, NOT YET COMMITTED\n")
        self.edit(self.a, "wiki/people/sam-rivera.md", "Owner and lead", "Owner and head")
        rc, out = self.safe_commit("--no-verify=testing that only the override block is staged here",
                                   "edit sam", "wiki/people/sam-rivera.md")
        self.assertEqual(rc, 0, out)
        committed = self.git(self.a, "show", "HEAD:wiki/log.md")
        self.assertNotIn("ANOTHER SESSION", committed, out)
        self.assertIn("testing that only the override block is staged here", committed)
        on_disk = (self.a / "wiki" / "log.md").read_text(encoding="utf-8")
        self.assertIn("ANOTHER SESSION", on_disk)


class CommitFirstRerunPulls(SafeCommitCase):
    def test_rerun_command_switches_commit_first_off(self):
        b = self.clone_b()
        self.edit(b, "wiki/people/sam-rivera.md", "Owner and lead", "Owner and chief")
        self.git(b, "commit", "-q", "-am", "theirs")
        self.git(b, "push", "-q", "origin", "main")
        self.edit(self.a, "wiki/people/sam-rivera.md", "Owner and lead", "Owner and head")
        rc, out = self.safe_commit("same line", "wiki/people/sam-rivera.md",
                                   env={"SECOND_BRAIN_COMMIT_BEFORE_PULL": "1"})
        self.assertEqual(rc, 1, out)
        self.assertIn("CANNOT PUBLISH", out)
        self.assertIn("SECOND_BRAIN_COMMIT_BEFORE_PULL=0 ./tools/safe_commit.sh", out)


class PreCommitCrashDetection(unittest.TestCase):
    """hooks/pre-commit reads a crash from a Traceback header at line start, never from the
    word inside an echoed wiki line (review 2026-10-21)."""

    def run_hook(self, connect_body):
        tmp = Path(tempfile.mkdtemp(prefix="pre-commit-test-"))
        self.addCleanup(shutil.rmtree, str(tmp), True)
        subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(tmp)],
                       check=True, env=_env())
        (tmp / "tools").mkdir()
        (tmp / "tools" / "lint.py").write_text("print('lint clean')\n", encoding="utf-8")
        (tmp / "tools" / "connect.py").write_text(connect_body, encoding="utf-8")
        r = subprocess.run(["bash", str(KIT / "hooks" / "pre-commit")], cwd=str(tmp),
                           capture_output=True, text=True, env=_env())
        return r.returncode, r.stdout + r.stderr

    def test_echoed_wiki_line_mentioning_traceback_passes(self):
        rc, out = self.run_hook("print('CLAIM RECIPROCITY')\n"
                                "print('                    the script died with a Traceback on import')\n")
        self.assertEqual(rc, 0, out)

    def test_real_crash_is_refused(self):
        rc, out = self.run_hook("print('starting')\nraise SystemExit(__import__('nonexistent_mod_xyz'))\n")
        self.assertEqual(rc, 1, out)
        self.assertIn("crashed", out)


if __name__ == "__main__":
    unittest.main()
