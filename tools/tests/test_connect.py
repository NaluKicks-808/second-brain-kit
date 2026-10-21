#!/usr/bin/env python3
"""Tests for tools/connect.py - the reciprocity gate.

WHY THESE EXIST
connect.py exists to catch a one-way street: a page newly names [[someone]] and the
someone's page neither changed nor links back. The link is not broken, so the linter
cannot see it. Two ways this check can be wrong, and both are tested: it can miss a real
gap (a gate that prints nothing is also what a broken gate prints), or it can flag noise
(a paragraph edit re-adds every link on its line, so a line diff would over-report; the
tool uses a set difference of link targets instead).

Each case builds a throwaway git repository, commits a baseline, makes an uncommitted
change, and runs connect.py from a copy inside that repo. Nothing touches a real vault.

    python3 tools/tests/test_connect.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(root, *args):
    subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com'] + list(args),
                   cwd=root, check=True, capture_output=True)


def write(root, rel, text):
    fp = os.path.join(root, rel)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, 'w', encoding='utf-8') as f:
        f.write(text)


def page(title, body):
    return '---\ntype: note\nupdated: 2026-10-01\n---\n# %s\n\n%s\n' % (title, body)


def make_repo():
    root = tempfile.mkdtemp(prefix='kit-connect-')
    os.makedirs(os.path.join(root, 'tools'))
    shutil.copy(os.path.join(TOOLS, 'connect.py'), os.path.join(root, 'tools', 'connect.py'))
    git(root, 'init', '-q')
    write(root, 'wiki/people/ana.md', page('Ana', 'Runs the front desk.'))
    write(root, 'wiki/projects/shop.md', page('Shop', 'A bike shop.'))
    write(root, 'wiki/misc/note.md', page('Note', 'A plain note.'))
    write(root, 'wiki/_index.md', page('Index', '[[ana]] [[shop]] [[note]]'))
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', 'baseline')
    return root


def run_connect(root):
    p = subprocess.run([sys.executable, os.path.join(root, 'tools', 'connect.py')],
                       capture_output=True, text=True, cwd=tempfile.gettempdir())
    return p.returncode, p.stdout


class Reciprocity(unittest.TestCase):
    def setUp(self):
        self.root = make_repo()
        self.addCleanup(shutil.rmtree, self.root)

    def test_one_way_link_to_person_is_a_gap(self):
        write(self.root, 'wiki/misc/note.md', page('Note', 'Talked with [[ana]] about hours.'))
        code, out = run_connect(self.root)
        self.assertEqual(code, 1, out)
        self.assertIn('GAP', out)
        self.assertIn('ana', out)

    def test_target_also_edited_is_woven(self):
        write(self.root, 'wiki/misc/note.md', page('Note', 'Talked with [[ana]] about hours.'))
        write(self.root, 'wiki/people/ana.md', page('Ana', 'Runs the front desk. Talked hours in [[note]].'))
        code, out = run_connect(self.root)
        self.assertEqual(code, 0, out)
        self.assertNotIn('GAP', out)

    def test_target_already_links_back_is_woven(self):
        write(self.root, 'wiki/people/ana.md', page('Ana', 'Runs the front desk. See [[note]].'))
        git(self.root, 'commit', '-q', '-am', 'ana links note')
        write(self.root, 'wiki/misc/note.md', page('Note', 'Talked with [[ana]] about hours.'))
        code, out = run_connect(self.root)
        self.assertEqual(code, 0, out)

    def test_link_already_present_before_is_not_new(self):
        write(self.root, 'wiki/misc/note.md', page('Note', 'Met [[ana]].'))
        git(self.root, 'commit', '-q', '-am', 'old link')
        # Edit the same paragraph without adding a new target: no new link, no gap.
        write(self.root, 'wiki/misc/note.md', page('Note', 'Met [[ana]] again on Tuesday.'))
        code, out = run_connect(self.root)
        self.assertEqual(code, 0, out)
        self.assertNotIn('GAP', out)

    def test_low_value_target_is_advisory_only(self):
        write(self.root, 'wiki/people/ana.md', page('Ana', 'Runs the front desk. See [[note]].'))
        code, out = run_connect(self.root)
        self.assertEqual(code, 0, out)

    def test_meta_pages_never_need_weaving(self):
        write(self.root, 'wiki/misc/note.md', page('Note', 'Listed in [[_index]].'))
        code, out = run_connect(self.root)
        self.assertEqual(code, 0, out)

    def test_code_span_link_is_not_a_link(self):
        write(self.root, 'wiki/misc/note.md', page('Note', 'Syntax is `[[ana]]`.'))
        code, out = run_connect(self.root)
        self.assertEqual(code, 0, out)
        self.assertNotIn('GAP', out)

    def test_deleted_page_does_not_crash(self):
        os.remove(os.path.join(self.root, 'wiki/misc/note.md'))
        code, out = run_connect(self.root)
        self.assertNotIn('Traceback', out)

    def test_new_page_linked_from_nowhere_fails(self):
        write(self.root, 'wiki/misc/orphan.md', page('Orphan', 'Nobody links here.'))
        code, out = run_connect(self.root)
        self.assertEqual(code, 1, out)


if __name__ == '__main__':
    unittest.main(verbosity=1)
