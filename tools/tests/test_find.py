#!/usr/bin/env python3
"""Tests for tools/find.py and tools/find_rank.py - keyword retrieval.

WHY THESE EXIST
Retrieval by raw mention counts lets the longest ledger win every query. find_rank.py
ranks by BM25 with a title boost and lists ledger pages (underscore files, log.md) in a
block of their own. These tests pin the properties that matter: a page about the term
beats a long ledger that merely mentions it, a title hit counts, a ledger is neither
buried nor allowed to crowd out an article, a two-letter capitalised acronym is a real
term, --deep reaches the source layer and the default does not, and the exit codes.

Every case builds a small vault in a temp directory and runs find.py as a subprocess
copied into that vault's tools/ folder, which is how the tool locates wiki/ at all.
Nothing here reads a real vault.

    python3 tools/tests/test_find.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
import find_rank  # noqa: E402


def make_vault(files):
    root = tempfile.mkdtemp(prefix='kit-find-')
    os.makedirs(os.path.join(root, 'tools'))
    for name in ('find.py', 'find_rank.py'):
        shutil.copy(os.path.join(TOOLS, name), os.path.join(root, 'tools', name))
    for rel, text in files.items():
        fp = os.path.join(root, rel)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(text)
    return root


def run_find(root, *args):
    p = subprocess.run([sys.executable, os.path.join(root, 'tools', 'find.py')] + list(args),
                       capture_output=True, text=True, cwd=root)
    return p.returncode, p.stdout


def ranked_section(out):
    """Lines of the RANKED FILES block, up to the next blank line."""
    lines = out.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith('RANKED FILES'))
    block = []
    for l in lines[start + 1:]:
        if not l.strip():
            break
        block.append(l)
    return '\n'.join(block)


class UsableTerms(unittest.TestCase):
    def test_stopwords_and_short_words_dropped(self):
        self.assertEqual(find_rank.usable_terms(['who', 'runs', 'the', 'shop?']),
                         ['runs', 'shop'])

    def test_all_stopwords_keeps_them(self):
        self.assertEqual(find_rank.usable_terms(['the']), ['the'])

    def test_capitalised_acronym_kept_lowercase_is_not(self):
        self.assertIn('qa', find_rank.usable_terms(['QA', 'plan']))
        self.assertNotIn('qa', find_rank.usable_terms(['qa', 'plan']))

    def test_phrase_stays_one_term_and_duplicates_collapse(self):
        self.assertEqual(find_rank.usable_terms(['winter tune-up', 'Brake', 'brake']),
                         ['winter tune-up', 'brake'])

    def test_short_term_is_whole_word_only(self):
        self.assertEqual(find_rank.count('he said ai is here', 'ai'), 1)
        self.assertEqual(find_rank.count('said', 'ai'), 0)


class IsSystem(unittest.TestCase):
    def test_ledgers_are_system(self):
        for rel in ('wiki/_index.md', 'wiki/_reminders.md', 'wiki/log.md'):
            self.assertTrue(find_rank.is_system(rel), rel)

    def test_articles_are_not(self):
        self.assertFalse(find_rank.is_system('wiki/people/sam-rivera.md'))


class Ranking(unittest.TestCase):
    def test_page_about_term_beats_long_ledger_mentioning_it(self):
        ledger = '# Ledger\n\n' + ('brake filler line about nothing much\n' * 5
                                   + 'unrelated words here\n' * 300)
        root = make_vault({
            'wiki/projects/brake-service.md': '# Brake service\n\nBrake pads and brake fluid.\n',
            'wiki/projects/other.md': '# Other\n\nA brake was mentioned once.\n',
            'wiki/misc/long-notes.md': ledger,
        })
        self.addCleanup(shutil.rmtree, root)
        code, out = run_find(root, 'brake')
        self.assertEqual(code, 0)
        first = ranked_section(out).splitlines()[0]
        self.assertIn('brake-service.md', first)

    def test_title_hit_outranks_equal_body_hits(self):
        root = make_vault({
            'wiki/a/plain.md': '# Plain\n\nCassette cassette once more.\n',
            'wiki/a/cassette.md': '# Cassette\n\nCassette here.\n',
            'wiki/a/filler.md': '# Filler\n\nNothing relevant.\n',
        })
        self.addCleanup(shutil.rmtree, root)
        _, out = run_find(root, 'cassette')
        self.assertIn('cassette.md', ranked_section(out).splitlines()[0])

    def test_ledger_listed_apart_not_in_ranked_files(self):
        root = make_vault({
            'wiki/a/page.md': '# Page\n\nTubeless tires.\n',
            'wiki/_reminders.md': '# Reminders\n\nTubeless tires tubeless tires tubeless.\n',
        })
        self.addCleanup(shutil.rmtree, root)
        _, out = run_find(root, 'tubeless')
        self.assertNotIn('_reminders', ranked_section(out))
        self.assertIn('SYSTEM PAGES', out)
        self.assertIn('_reminders.md', out.split('SYSTEM PAGES')[1])

    def test_only_ledger_matches_still_returns_it_as_result(self):
        root = make_vault({
            'wiki/a/page.md': '# Page\n\nNothing.\n',
            'wiki/log.md': '# Log\n\nRecorded a flywheel.\n',
        })
        self.addCleanup(shutil.rmtree, root)
        code, out = run_find(root, 'flywheel')
        self.assertEqual(code, 0)
        self.assertIn('log.md', ranked_section(out))
        self.assertNotIn('SYSTEM PAGES', out)


class Layers(unittest.TestCase):
    FILES = {
        'wiki/a/page.md': '# Page\n\nSummary only.\n',
        'raw/entries/2026-01-01_visit.md': '# Visit\n\nThe derailleur hanger was bent.\n',
        'data/src-notes.txt': 'derailleur notes\n',
    }

    def test_default_searches_wiki_only(self):
        root = make_vault(self.FILES)
        self.addCleanup(shutil.rmtree, root)
        code, out = run_find(root, 'derailleur')
        self.assertEqual(code, 1)
        self.assertIn('--deep', out)

    def test_deep_reaches_raw_and_data(self):
        root = make_vault(self.FILES)
        self.addCleanup(shutil.rmtree, root)
        code, out = run_find(root, '--deep', 'derailleur')
        self.assertEqual(code, 0)
        self.assertIn('raw/entries/2026-01-01_visit.md', out)
        self.assertIn('data/src-notes.txt', out)

    def test_deepfind_is_find_deep(self):
        root = make_vault(self.FILES)
        self.addCleanup(shutil.rmtree, root)
        shutil.copy(os.path.join(TOOLS, 'deepfind.py'), os.path.join(root, 'tools', 'deepfind.py'))
        p = subprocess.run([sys.executable, os.path.join(root, 'tools', 'deepfind.py'), 'derailleur'],
                           capture_output=True, text=True, cwd=root)
        self.assertEqual(p.returncode, 0)
        self.assertIn('raw/entries/', p.stdout)


class ExitCodes(unittest.TestCase):
    def test_usage_and_help(self):
        root = make_vault({'wiki/a/p.md': '# P\n'})
        self.addCleanup(shutil.rmtree, root)
        self.assertEqual(run_find(root)[0], 2)
        code, out = run_find(root, '--help')
        self.assertEqual(code, 0)
        self.assertIn('usage', out)

    def test_works_from_another_cwd_and_without_semantic_layer(self):
        root = make_vault({'wiki/a/p.md': '# P\n\nSprocket.\n'})
        self.addCleanup(shutil.rmtree, root)
        p = subprocess.run([sys.executable, os.path.join(root, 'tools', 'find.py'), 'sprocket'],
                           capture_output=True, text=True, cwd=tempfile.gettempdir())
        self.assertEqual(p.returncode, 0)
        self.assertIn('keywords', p.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=1)
