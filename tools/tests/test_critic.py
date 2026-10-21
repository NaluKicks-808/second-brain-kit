#!/usr/bin/env python3
"""Tests for tools/critic.py - the growth loop's ranking.

WHY THESE EXIST
The DEEPENING CANDIDATES list is only useful if its numbers mean something. A naive
count credits a page for every source entry containing ANY word of its slug, so a page
named `story-closer-to-the-coast` inherits every entry that says "story" or "the", and
the ranking becomes a fact about the naming convention. The fix matches WHOLE names
only. The tests are built around the two ways that fix could be wrong: a page whose
one-word slug really is its name must keep every entry it had, and a page whose slug is
a sentence must stop collecting entries that merely contain its words. Both are asserted
on the same fixture vault.

Also covered: the SHAPE section (long pages that read as a stack of dated deliveries)
and that a short page with heavy inbound links is a deepening candidate.

Nothing here reads a real vault. critic.py finds wiki/ from its own location, so each
case copies it into a temp vault and runs it as a subprocess.

    python3 tools/tests/test_critic.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def page(title, body, extra_fm=''):
    return ('---\ntype: note\nupdated: 2026-10-01\nsources:\n  - a\n  - b\n%s---\n# %s\n\n%s\n'
            % (extra_fm, title, body))


def make_vault(files):
    root = tempfile.mkdtemp(prefix='kit-critic-')
    os.makedirs(os.path.join(root, 'tools'))
    shutil.copy(os.path.join(TOOLS, 'critic.py'), os.path.join(root, 'tools', 'critic.py'))
    for rel, text in files.items():
        fp = os.path.join(root, rel)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(text)
    return root


def run_critic(root):
    p = subprocess.run([sys.executable, os.path.join(root, 'tools', 'critic.py')],
                       capture_output=True, text=True, cwd=tempfile.gettempdir())
    return p.returncode, p.stdout


def section(out, n):
    parts = re.split(r'^=== ', out, flags=re.M)
    for p in parts:
        if p.startswith('%d. ' % n):
            return p
    raise AssertionError('no section %d in:\n%s' % (n, out))


def raw_refs(out, rel):
    for line in section(out, 1).splitlines():
        if line.rstrip().endswith(rel):
            return int(re.search(r'raw:\s*(\d+)', line).group(1))
    raise AssertionError('%s not in candidates:\n%s' % (rel, section(out, 1)))


def fixture():
    files = {
        'wiki/people/maren.md': page('Maren', 'Short.'),
        'wiki/stories/story-closer-to-the-coast.md': page('Closer to the coast', 'Short.'),
        'wiki/_index.md': page('Index', '[[maren]] [[story-closer-to-the-coast]]'),
    }
    # four pages link to each so they clear the importance floor
    for i in range(4):
        files['wiki/misc/linker-%d.md' % i] = page(
            'Linker %d' % i, 'See [[maren]] and [[story-closer-to-the-coast]]. ' + 'word ' * 280)
    for i in range(6):
        files['raw/entries/2026-01-0%d_e.md' % (i + 1)] = (
            '---\ndate: 2026-01-0%d\n---\nMaren came by. The story was long, closer to home.\n' % (i + 1))
    files['raw/entries/2026-02-01_n.md'] = '---\n---\nNothing about anyone, just a story.\n'
    return files


class RawCount(unittest.TestCase):
    def setUp(self):
        self.root = make_vault(fixture())
        self.addCleanup(shutil.rmtree, self.root)
        self.code, self.out = run_critic(self.root)

    def test_exit_zero_advisory(self):
        self.assertEqual(self.code, 0)

    def test_one_word_slug_keeps_every_entry(self):
        self.assertEqual(raw_refs(self.out, 'wiki/people/maren.md'), 6)

    def test_sentence_slug_does_not_inherit_its_words(self):
        # 7 entries contain "story", 6 contain "closer"; none names the page as a whole.
        self.assertEqual(raw_refs(self.out, 'wiki/stories/story-closer-to-the-coast.md'), 0)


class WholeNameAlias(unittest.TestCase):
    def test_declared_alias_is_honoured(self):
        files = fixture()
        files['wiki/stories/story-closer-to-the-coast.md'] = page(
            'Closer to the coast', 'Short.', extra_fm='aliases:\n  - Coastline\n')
        files['raw/entries/2026-03-01_c.md'] = '---\n---\nWe walked the coastline at dusk.\n'
        root = make_vault(files)
        self.addCleanup(shutil.rmtree, root)
        _, out = run_critic(root)
        self.assertEqual(raw_refs(out, 'wiki/stories/story-closer-to-the-coast.md'), 1)


class Shape(unittest.TestCase):
    def long_page(self, heads, words=2300):
        body = 'Opening line.\n\n' + ''.join('## %s\n\n%s\n\n' % (h, 'word ' * (words // len(heads)))
                                             for h in heads)
        return page('Long', body)

    def test_stack_of_dated_deliveries_flagged(self):
        root = make_vault({
            'wiki/eras/stacked.md': self.long_page(
                ['2026-01-01 update', '2026-02-03 update', '2026-03-04 update']),
            'wiki/_index.md': page('Index', '[[stacked]]'),
        })
        self.addCleanup(shutil.rmtree, root)
        _, out = run_critic(root)
        self.assertIn('wiki/eras/stacked.md', section(out, 5))

    def test_well_shaped_long_page_not_flagged(self):
        root = make_vault({
            'wiki/eras/article.md': self.long_page(['Background', 'Work', 'Outcome']),
            'wiki/_index.md': page('Index', '[[article]]'),
        })
        self.addCleanup(shutil.rmtree, root)
        _, out = run_critic(root)
        self.assertNotIn('article.md', section(out, 5))

    def test_page_past_soft_cap_flagged(self):
        root = make_vault({
            'wiki/eras/huge.md': self.long_page(['Background', 'Work', 'Outcome'], words=3300),
            'wiki/_index.md': page('Index', '[[huge]]'),
        })
        self.addCleanup(shutil.rmtree, root)
        _, out = run_critic(root)
        self.assertIn('wiki/eras/huge.md', section(out, 5))

    def test_journal_pages_exempt(self):
        root = make_vault({
            'wiki/eras/trip-journal.md': self.long_page(
                ['2026-01-01', '2026-01-02', '2026-01-03'], words=3300),
            'wiki/_index.md': page('Index', '[[trip-journal]]'),
        })
        self.addCleanup(shutil.rmtree, root)
        _, out = run_critic(root)
        self.assertNotIn('trip-journal', section(out, 5))


class NoVaultSpecificDeps(unittest.TestCase):
    def test_runs_standalone_with_no_helper_modules(self):
        root = make_vault({'wiki/_index.md': page('Index', 'Nothing.')})
        self.addCleanup(shutil.rmtree, root)
        code, out = run_critic(root)
        self.assertEqual(code, 0)
        self.assertNotIn('Traceback', out)


if __name__ == '__main__':
    unittest.main(verbosity=1)
