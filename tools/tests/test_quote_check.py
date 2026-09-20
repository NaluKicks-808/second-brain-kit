#!/usr/bin/env python3
"""Tests for tools/quote_check.py.

WHY THESE EXIST
quote_check.py answers one question with a string comparison: does a quotation on a wiki
page appear in the entry that sentence cites? A string comparison has two failure modes
and only one of them is visible. If it reports too much, the report is a wall of warnings,
people stop reading it, and the one real problem in the pile is invisible, which is the
failure the tool exists to prevent reproduced inside the fix. If it reports too little it
says nothing at all, and a report of zero is exactly what a check that has quietly stopped
working also prints.

So the fixtures below are mostly about the boundaries: the four-word floor, the ellipsis,
curly quotes, emphasis markers, a quote that lives inside the citation's own label, a
sentence carrying two citations, and a private entry, which must be searched as a source
and never appear in output beyond its filename.

EXPECTATIONS ARE DERIVED FROM THE FIXTURES, never typed twice. A quote that is supposed to
be found is sliced out of the entry text in the test itself, and a quote that is supposed
to be missing is asserted absent from that text before it is used. A hand-typed fixture
plus a hand-typed expectation is two copies of one belief, and both can be wrong together.

THE MATCHER IS PROVEN LOAD-BEARING. `StubbedMatcher` replaces quote_in_text with a
function that always returns True and asserts the finding then disappears. Without it,
every test here would pass against a tool that reported nothing.

HOW TO RUN IT
    python3 tools/tests/test_quote_check.py
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent

_spec = importlib.util.spec_from_file_location("quote_check", TOOLS / "quote_check.py")
qc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qc)

GIT = shutil.which("git")

# The sentences are the fixture. The entry files are built out of them, and every quote a
# test uses is sliced out of one of these strings rather than typed a second time.
ENTRY_S1 = ("The clipboard by the stand had nineteen tickets on it and the booking "
            "software had four.")
ENTRY_S2 = ("Asked how long a ticket usually waits, the owner said it depends entirely "
            "on whether the part is in the drawer.")
OTHER_S1 = "Labour is charged in half-hour blocks and has not moved in two years."
PRIVATE_S1 = "The bench only fits two people and the third one left in August."
PRIVATE_SECRET = ("Everything else on this page is a sentence the report must never "
                  "reproduce anywhere.")

ENTRY_BODY = "# A fixture entry\n\n%s ^backlog\n\n%s ^waiting\n" % (ENTRY_S1, ENTRY_S2)
OTHER_BODY = "# A second fixture entry\n\n%s ^blocks\n" % OTHER_S1
PRIVATE_BODY = ("# A fixture entry nobody may quote\n\n%s ^bench\n\n%s\n"
                % (PRIVATE_S1, PRIVATE_SECRET))

ALL_SOURCE_TEXT = (ENTRY_BODY + OTHER_BODY + PRIVATE_BODY).lower()


def words(text, start, count):
    """`count` consecutive words of `text`, starting at word `start`."""
    return " ".join(text.split()[start:start + count])


class VaultCase(unittest.TestCase):
    """A throwaway brain per test: wiki/ over raw/entries/, and nothing else."""

    def setUp(self):
        self.vault = Path(tempfile.mkdtemp(prefix="quotecheck-test-"))
        (self.vault / "wiki").mkdir()
        (self.vault / "raw" / "entries").mkdir(parents=True)
        self.entry("2026-09-12_fixture-entry", ENTRY_BODY)
        self.entry("2026-09-13_other-entry", OTHER_BODY)
        self.entry("2026-09-14_private-entry", PRIVATE_BODY, private=True)

    def tearDown(self):
        shutil.rmtree(str(self.vault), ignore_errors=True)

    def entry(self, stem, body, private=False):
        head = ["---", "date: " + stem[:10], "source: a fixture", "type: notes",
                "tags: [fixture]"]
        if private:
            head.append("private: true   # a fixture, and the flag carries a comment")
        head += ["---", ""]
        path = self.vault / "raw" / "entries" / (stem + ".md")
        path.write_text("\n".join(head) + body, encoding="utf-8")
        return path

    def page(self, name, body):
        path = self.vault / "wiki" / name
        path.write_text("---\ntype: note\nupdated: 2026-09-20\nsources: []\n---\n\n"
                        "# A fixture page\n\n" + body + "\n", encoding="utf-8")
        return path

    def run_check(self, **kw):
        return qc.check_vault(root=str(self.vault), **kw)

    def findings(self, **kw):
        return self.run_check(**kw)["findings"]


class QuoteIsFound(VaultCase):

    def test_a_quote_present_in_the_cited_entry_passes(self):
        quote = words(ENTRY_S1, 0, 8)
        self.assertIn(quote.lower(), ENTRY_BODY.lower())
        self.page("a.md", 'The shop kept a list: "%s" '
                          '([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        result = self.run_check()
        self.assertEqual(result["counts"]["quotes_checked"], 1)
        self.assertEqual(result["findings"], [])

    def test_an_unanchored_citation_is_a_citation(self):
        quote = words(ENTRY_S1, 0, 8)
        self.page("a.md", 'The shop kept a list: "%s" ([[2026-09-12_fixture-entry]]).'
                  % quote)
        result = self.run_check()
        self.assertEqual(result["counts"]["quotes_checked"], 1)
        self.assertEqual(result["findings"], [])

    def test_a_plain_filename_is_not_a_citation(self):
        """Links only. A sentence naming its source as text carries no citation to check."""
        quote = "these six words are not anywhere"
        self.assertNotIn(quote.lower(), ENTRY_BODY.lower())
        self.page("a.md", 'The shop kept a list: "%s" (2026-09-12_fixture-entry.md).'
                  % quote)
        result = self.run_check()
        self.assertEqual(result["counts"]["quotes_checked"], 0)
        self.assertEqual(result["findings"], [])


class QuoteIsMissing(VaultCase):

    def test_a_quote_in_no_entry_is_reported(self):
        quote = "the owner priced every repair on a whiteboard"
        self.assertNotIn(quote.lower(), ALL_SOURCE_TEXT)
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        found = self.findings()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["verdict"], "not-found")
        self.assertIsNone(found[0]["found_in"])
        self.assertIsNone(found[0]["private_entry_holds"])
        self.assertEqual(found[0]["cited"], ["2026-09-12_fixture-entry"])
        self.assertEqual(found[0]["page"], "wiki/a.md")
        self.assertEqual(found[0]["quote"], quote)

    def test_the_line_number_is_the_line_the_quote_sits_on(self):
        quote = "the owner priced every repair on a whiteboard"
        body = ("One.\n\nTwo.\n\nHe said \"%s\" ([[2026-09-12_fixture-entry#^backlog]])."
                % quote)
        path = self.page("a.md", body)
        found = self.findings()
        self.assertEqual(len(found), 1)
        lines = path.read_text(encoding="utf-8").split("\n")
        self.assertIn(quote, lines[found[0]["line"] - 1])

    def test_a_quote_from_another_entry_is_reported_as_the_wrong_source(self):
        quote = words(OTHER_S1, 0, 9)
        self.assertIn(quote.lower(), OTHER_BODY.lower())
        self.assertNotIn(quote.lower(), ENTRY_BODY.lower())
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        found = self.findings()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["verdict"], "wrong-source")
        self.assertEqual(found[0]["found_in"], "2026-09-13_other-entry")

    def test_a_quote_only_a_private_entry_holds_is_named_by_filename(self):
        quote = words(PRIVATE_S1, 0, 8)
        self.assertIn(quote.lower(), PRIVATE_BODY.lower())
        self.assertNotIn(quote.lower(), (ENTRY_BODY + OTHER_BODY).lower())
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        found = self.findings()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["verdict"], "not-found")
        self.assertEqual(found[0]["private_entry_holds"], "2026-09-14_private-entry")


class Boundaries(VaultCase):

    def test_a_three_word_quote_is_not_checked(self):
        quote = "not anywhere whatsoever"
        self.assertEqual(len(quote.split()), 3)
        self.assertNotIn(quote.lower(), ALL_SOURCE_TEXT)
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        result = self.run_check()
        self.assertEqual(result["counts"]["quotes_checked"], 0)
        self.assertEqual(result["findings"], [])

    def test_a_four_word_quote_is_checked(self):
        quote = "not anywhere whatsoever ever"
        self.assertEqual(len(quote.split()), 4)
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        result = self.run_check()
        self.assertEqual(result["counts"]["quotes_checked"], 1)
        self.assertEqual(len(result["findings"]), 1)

    def test_a_quote_inside_a_citation_label_is_ignored(self):
        """The label is the page quoting the entry AT the link. Checking it against that
        entry is checking a string against itself, and when the label is a paraphrase the
        finding is about the page's own display text rather than about a claim."""
        quote = "words that are in no entry at all"
        self.assertNotIn(quote.lower(), ALL_SOURCE_TEXT)
        self.page("a.md", 'He put it plainly [[2026-09-12_fixture-entry#^backlog|"%s"]].'
                  % quote)
        result = self.run_check()
        self.assertEqual(result["counts"]["quotes_checked"], 0)
        self.assertEqual(result["findings"], [])

    def test_a_quote_beside_a_citation_label_is_still_checked(self):
        """The label is excluded; the rest of the sentence is not."""
        quote = "words that are in no entry at all"
        self.page("a.md", 'He said "%s" [[2026-09-12_fixture-entry#^backlog|his own '
                          'words]].' % quote)
        result = self.run_check()
        self.assertEqual(result["counts"]["quotes_checked"], 1)
        self.assertEqual(len(result["findings"]), 1)

    def test_a_short_quotation_does_not_leak_the_prose_that_follows_it(self):
        """Quote characters pair positionally, so a quotation under the word floor is
        dropped WITH its own closing quote rather than leaving it to pair with the next
        quotation's opener and hand back the prose in between."""
        prose = "the words between two quotations are not themselves a quotation"
        self.assertNotIn(prose.lower(), ALL_SOURCE_TEXT)
        quote = words(ENTRY_S1, 0, 8)
        self.page("a.md", 'He called it "AI", %s, and then "%s" '
                          '([[2026-09-12_fixture-entry#^backlog]]).' % (prose, quote))
        result = self.run_check()
        self.assertEqual(result["counts"]["quotes_checked"], 1)
        self.assertEqual(result["findings"], [])

    def test_an_unmatched_quote_character_does_not_shift_the_pairs_after_it(self):
        quote = words(ENTRY_S1, 0, 8)
        self.page("a.md", 'The gap was 5" across. He said “%s” '
                          '([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        result = self.run_check()
        self.assertEqual(result["counts"]["quotes_checked"], 1)
        self.assertEqual(result["findings"], [])

    def test_a_sentence_with_two_citations_passes_if_either_entry_holds_it(self):
        quote = words(OTHER_S1, 0, 9)
        self.assertNotIn(quote.lower(), ENTRY_BODY.lower())
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]], '
                          '[[2026-09-13_other-entry#^blocks]]).' % quote)
        result = self.run_check()
        self.assertEqual(result["counts"]["quotes_checked"], 1)
        self.assertEqual(result["findings"], [])

    def test_a_sentence_with_two_citations_reports_both_when_neither_holds_it(self):
        quote = "the owner priced every repair on a whiteboard"
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]], '
                          '[[2026-09-13_other-entry#^blocks]]).' % quote)
        found = self.findings()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["cited"],
                         ["2026-09-12_fixture-entry", "2026-09-13_other-entry"])

    def test_a_private_cited_entry_is_searched_like_any_other(self):
        quote = words(PRIVATE_S1, 0, 8)
        self.page("a.md", 'He said "%s" ([[2026-09-14_private-entry#^bench]]).' % quote)
        result = self.run_check()
        self.assertEqual(result["counts"]["quotes_checked"], 1)
        self.assertEqual(result["findings"], [])

    def test_a_private_wiki_page_is_skipped(self):
        quote = "the owner priced every repair on a whiteboard"
        path = self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).'
                         % quote)
        path.write_text(path.read_text(encoding="utf-8")
                        .replace("type: note", "type: note\nprivate: true"),
                        encoding="utf-8")
        result = self.run_check()
        self.assertEqual(result["counts"]["private_wiki_pages_skipped"], 1)
        self.assertEqual(result["findings"], [])

    def test_a_fenced_code_block_is_not_prose(self):
        quote = "the owner priced every repair on a whiteboard"
        self.page("a.md", '```\nHe said "%s" ([[2026-09-12_fixture-entry#^backlog]]).\n```'
                  % quote)
        result = self.run_check()
        self.assertEqual(result["counts"]["quotes_checked"], 0)


class Ellipsis(VaultCase):

    def joined(self):
        first = words(ENTRY_S1, 0, 7)
        second = words(ENTRY_S2, 0, 7)
        joined = first + "… " + second
        self.assertIn(first.lower(), ENTRY_BODY.lower())
        self.assertIn(second.lower(), ENTRY_BODY.lower())
        self.assertNotIn(qc.normalise(joined).lower(), qc.normalise(ENTRY_BODY).lower())
        return first, second, joined

    def test_an_ellipsis_joined_quote_is_split_and_both_pieces_pass(self):
        _first, _second, joined = self.joined()
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % joined)
        result = self.run_check()
        self.assertEqual(result["counts"]["runs_split_at_an_ellipsis"], 1)
        self.assertEqual(result["counts"]["quotes_checked"], 2)
        self.assertEqual(result["findings"], [])

    def test_three_dots_are_an_ellipsis_too(self):
        first, second, _joined = self.joined()
        self.page("a.md", 'He said "%s ... %s" ([[2026-09-12_fixture-entry#^backlog]]).'
                  % (first, second))
        result = self.run_check()
        self.assertEqual(result["counts"]["quotes_checked"], 2)
        self.assertEqual(result["findings"], [])

    def test_a_quotation_is_not_cut_in_half_by_the_sentence_splitter(self):
        """An ellipsis followed by a capital looks exactly like a sentence boundary.

        Cut there, each half carries one unmatched quote character and neither is
        recognised as a quotation at all, so the check passes over the whole thing in
        silence, which is the worse of the two failure directions.
        """
        first, second, _joined = self.joined()
        line = ('He said "%s ... %s" ([[2026-09-12_fixture-entry#^backlog]]).'
                % (first, second))
        self.assertTrue(second[0].isupper(), "the fixture must trigger the splitter")
        self.assertEqual(len(qc.sentences(line)), 1)

    def test_only_the_missing_piece_is_reported(self):
        first, _second, _joined = self.joined()
        absent = "and nobody wrote any of it down"
        self.assertNotIn(absent.lower(), ENTRY_BODY.lower())
        self.page("a.md", 'He said "%s… %s" ([[2026-09-12_fixture-entry#^backlog]]).'
                  % (first, absent))
        found = self.findings()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["quote"], absent)

    def test_a_piece_under_four_words_is_dropped_not_reported(self):
        first, _second, _joined = self.joined()
        self.page("a.md", 'He said "%s… nope nope nope" '
                          '([[2026-09-12_fixture-entry#^backlog]]).' % first)
        result = self.run_check()
        self.assertEqual(result["counts"]["pieces_too_short_to_check"], 1)
        self.assertEqual(result["counts"]["quotes_checked"], 1)
        self.assertEqual(result["findings"], [])


class Tolerance(VaultCase):

    def test_curly_quotes_around_the_run_are_read(self):
        quote = words(ENTRY_S1, 0, 8)
        self.page("a.md", 'He said “%s” ([[2026-09-12_fixture-entry#^backlog]]).'
                  % quote)
        result = self.run_check()
        self.assertEqual(result["counts"]["quotes_checked"], 1)
        self.assertEqual(result["findings"], [])

    def test_a_curly_apostrophe_inside_the_run_matches_a_straight_one(self):
        self.entry("2026-09-15_apostrophe", "# Apostrophe\n\n"
                   "The owner's list of tickets was longer than the software's. ^a\n")
        quote = "The owner’s list of tickets was longer"
        self.page("a.md", 'He said “%s” ([[2026-09-15_apostrophe#^a]]).' % quote)
        self.assertEqual(self.findings(), [])

    def test_emphasis_markers_in_the_page_are_tolerated(self):
        quote = words(ENTRY_S1, 0, 8)
        emphasised = "*" + " ".join(quote.split()[:3]) + "* " + " ".join(quote.split()[3:])
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).'
                  % emphasised)
        self.assertEqual(self.findings(), [])

    def test_emphasis_markers_in_the_entry_are_tolerated(self):
        self.entry("2026-09-16_emphasised", "# Emphasised\n\n"
                   "The clipboard had **nineteen tickets** on it that morning. ^a\n")
        quote = "The clipboard had nineteen tickets on it"
        self.page("a.md", 'He said "%s" ([[2026-09-16_emphasised#^a]]).' % quote)
        self.assertEqual(self.findings(), [])

    def test_a_trailing_full_stop_inside_the_closing_quote_is_tolerated(self):
        quote = words(ENTRY_S1, 0, 8) + "."
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        self.assertEqual(self.findings(), [])

    def test_an_em_dash_matches_an_en_dash(self):
        self.entry("2026-09-17_dashes", "# Dashes\n\n"
                   "The bench \u2014 two people wide \u2014 was the constraint. ^a\n")
        quote = "The bench \u2013 two people wide \u2013 was the constraint"
        self.page("a.md", 'He said "%s" ([[2026-09-17_dashes#^a]]).' % quote)
        self.assertEqual(self.findings(), [])

    def test_a_reworded_quote_is_still_reported(self):
        """The tolerance is formatting only. Different WORDS are still a finding."""
        quote = "The clipboard by the stand held nineteen tickets"   # held, not had
        self.assertNotIn(quote.lower(), ENTRY_BODY.lower())
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        self.assertEqual(len(self.findings()), 1)


class Selection(VaultCase):

    def test_underscore_pages_and_the_log_are_skipped_by_default(self):
        quote = "the owner priced every repair on a whiteboard"
        for name in ("_index.md", "log.md"):
            self.page(name, 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        self.assertEqual(self.findings(), [])
        self.assertEqual(len(self.findings(include_all=True)), 2)

    def test_page_limits_the_run_to_one_file(self):
        quote = "the owner priced every repair on a whiteboard"
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        self.page("b.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        self.assertEqual(len(self.findings()), 2)
        found = self.findings(page=str(self.vault / "wiki" / "b.md"))
        self.assertEqual([f["page"] for f in found], ["wiki/b.md"])

    def test_page_refuses_anything_outside_the_wiki(self):
        """The report's whole meaning is that a wiki page quotes an entry, so an entry
        handed to --page is refused out loud rather than quietly scanned."""
        entry = str(self.vault / "raw" / "entries" / "2026-09-12_fixture-entry.md")
        result = self.run_check(page=entry)
        self.assertEqual(result["findings"], [])
        self.assertIn("must name a file under wiki/", result["note"])


@unittest.skipUnless(GIT, "git is not on this machine")
class ChangedOnly(VaultCase):

    def git(self, *args):
        return subprocess.run([GIT, "-C", str(self.vault)] + list(args),
                              capture_output=True, text=True)

    def commit_everything(self):
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.com")
        self.git("config", "user.name", "Fixture")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "fixture", "--no-verify")

    def test_an_unchanged_tree_reports_nothing(self):
        quote = "the owner priced every repair on a whiteboard"
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        self.assertEqual(len(self.findings()), 1)         # the whole-wiki run sees it
        self.commit_everything()
        result = self.run_check(changed=True)
        self.assertEqual(result["pages_requested"], 0)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["note"], "")

    def test_a_changed_page_is_the_one_reported(self):
        good = words(ENTRY_S1, 0, 8)
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % good)
        self.page("b.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % good)
        self.commit_everything()
        quote = "the owner priced every repair on a whiteboard"
        self.page("b.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        found = self.findings(changed=True)
        self.assertEqual([f["page"] for f in found], ["wiki/b.md"])

    def test_a_new_untracked_page_counts_as_changed(self):
        self.commit_everything()
        quote = "the owner priced every repair on a whiteboard"
        self.page("c.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        found = self.findings(changed=True)
        self.assertEqual([f["page"] for f in found], ["wiki/c.md"])

    def test_no_repository_says_so_rather_than_reporting_nothing(self):
        quote = "the owner priced every repair on a whiteboard"
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        result = self.run_check(changed=True)       # never git init'd
        self.assertEqual(result["findings"], [])
        self.assertIn("git could not answer", result["note"])


class Output(VaultCase):

    def test_the_report_prints_path_line_and_the_head_of_the_quote(self):
        quote = "the owner priced every single repair of any kind on a whiteboard"
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        result = self.run_check()
        head = " ".join(quote.split()[:qc.HEAD_WORDS])
        self.assertEqual(result["findings"][0]["head"], head + " ...")
        line = qc.one_line(result["findings"][0])
        self.assertIn("wiki/a.md:", line)
        self.assertIn(head, line)
        self.assertNotIn(quote, line)          # the tail is cut, not printed whole

    def test_a_wrong_source_line_names_the_entry_that_holds_the_words(self):
        quote = words(OTHER_S1, 0, 9)
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        line = qc.one_line(self.findings()[0])
        self.assertIn("2026-09-13_other-entry", line)
        self.assertIn("wrong entry", line)

    def test_a_private_entry_is_never_quoted_in_output(self):
        self.assertIn(PRIVATE_SECRET, PRIVATE_BODY)
        quote = words(PRIVATE_S1, 0, 8)
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        line = qc.one_line(self.findings()[0])
        self.assertIn("2026-09-14_private-entry", line)      # the filename is allowed
        self.assertNotIn(PRIVATE_SECRET, line)               # its text is not


class ShippedExample(unittest.TestCase):
    """The tool, run end to end over the pages this kit ships with.

    Two things at once: the command works from a cold start, and the example pages do not
    quote anything their own entry does not contain. A starter kit whose worked example
    fails its own check teaches the wrong lesson on the first run.
    """

    def cli(self, *args):
        proc = subprocess.run([sys.executable, str(TOOLS / "quote_check.py")] + list(args),
                              capture_output=True, text=True)
        return proc.returncode, proc.stdout

    def test_the_exit_code_is_zero_and_the_summary_is_printed(self):
        code, out = self.cli()
        self.assertEqual(code, 0)
        self.assertIn("quote check:", out)
        self.assertIn("this tool reports and never blocks", out)

    def test_json_mode_is_parseable(self):
        code, out = self.cli("--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        for key in ("findings", "counts", "entries_indexed", "pages_requested"):
            self.assertIn(key, payload)

    def test_the_example_pages_quote_only_what_their_entry_holds(self):
        payload = json.loads(self.cli("--all", "--json")[1])
        self.assertEqual(payload["findings"], [])


class StubbedMatcher(VaultCase):
    """The proof that the matcher is what produces a finding.

    Every other test here would pass against a tool that reported nothing, and most would
    pass against one that reported everything. This one swaps quote_in_text for a function
    that always says the quote is present and asserts the finding disappears, so a change
    that quietly neuters the comparison turns this red.
    """

    def test_the_finding_comes_from_the_comparison_and_not_from_the_fixture(self):
        quote = "the owner priced every repair on a whiteboard"
        self.page("a.md", 'He said "%s" ([[2026-09-12_fixture-entry#^backlog]]).' % quote)
        self.assertEqual(len(self.findings()), 1)
        real = qc.quote_in_text
        try:
            qc.quote_in_text = lambda *a, **k: True
            self.assertEqual(self.findings(), [],
                             "with the matcher stubbed to always match, a finding must "
                             "not survive; it would mean the report is coming from "
                             "somewhere other than the comparison")
        finally:
            qc.quote_in_text = real
        self.assertEqual(len(self.findings()), 1)


if __name__ == "__main__":
    unittest.main()
