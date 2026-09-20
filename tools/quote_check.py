#!/usr/bin/env python3
"""quote_check.py - does a quotation in wiki/ appear in the entry it cites?

    python3 tools/quote_check.py                 the whole wiki, grouped report
    python3 tools/quote_check.py --changed       only wiki files changed against HEAD
    python3 tools/quote_check.py --page wiki/people/sam-rivera.md
    python3 tools/quote_check.py --json          the same findings as JSON
    python3 tools/quote_check.py --all           include _underscore pages and log.md

WHAT IT IS. A string match and nothing else. For every sentence in the wiki that links to
a file under raw/entries/, it takes each double-quoted run of four or more words and looks
for those words in the text of the entries that sentence cites. A quote found in any cited
entry passes. One that is not found is reported, with a second verdict saying whether the
words live in some OTHER entry, which means the citation points at the wrong source, or in
no entry at all.

WHY IT EXISTS. The compiled layer is written by a model reading the source layer, and the
one thing a model does that is both easy to do and hard to catch is tighten a quotation:
drop a hedge, smooth a stumble, merge two sentences somebody said ten minutes apart. None
of that is visible on the page. All of it is visible to a string comparison, and a string
comparison costs nothing and needs no model, so there is no reason to spend judgement on
the question before spending code on it. THIS FILE MAKES NO MODEL CALL AND NO NETWORK
CALL. It reads files and compares strings.

WHY IT WARNS AND NEVER BLOCKS. A reported quote is not proof of an invention. A brain
quotes sources it does not hold: a page read in a browser, a book, a recording whose entry
is a summary rather than a transcript. A quotation can be perfectly accurate and still be
unfindable here, because the brain cannot show its own receipt. That is worth knowing and
it is not worth refusing a commit over, which is why this tool exits 0 always and is not
wired into tools/lint.py. It also never repairs anything: a wrong quotation is fixed on
the page by a session that has reread the source, never by a script rewriting prose.

HOW IT DECIDES WHAT A CITATION IS. A link, never a filename. `[[2026-09-12_slug#^anchor]]`
and `[[2026-09-12_slug]]` both count, with or without a display label; a bare
`2026-09-12_slug.md` written as plain text does not, because the convention is that a
load-bearing claim carries a clickable citation and a plain filename is how data/
originals are named. The target must resolve to a real file under raw/entries/. A link to
an entry that does not exist is the linter's business, not this file's.

HOW IT DECIDES WHAT A QUOTE IS. A run inside a matched pair of straight or curly double
quotes, four words or more. A run joined by an ellipsis is split at the ellipsis and each
piece of four or more words is checked on its own, because the words on either side of an
ellipsis are contiguous in the source and the joined string never is. A quote that sits
inside a citation's own display label is ignored: the label is the wiki quoting the entry
at the link, so matching it against the entry would be checking a string against itself.

WHAT THE MATCH TOLERATES, and nothing else. Whitespace, curly against straight quotes, en
against em dashes, non-breaking spaces, markdown emphasis markers, a markdown backslash
escape, and the full stop or comma a page puts inside its closing quote. All of those are
formatting rather than words, and without that tolerance most of the report is noise.
Nothing that could change WHICH WORDS are present is normalised away: no stemming, no
fuzzy match, no synonyms. A reworded quotation is still a finding.

PRIVACY. An entry whose frontmatter says `private: true` is searched when a sentence cites
it, so a quotation sourced from one passes normally. It is never quoted in output, and it
is named by filename only. A wiki page carrying the same flag is skipped entirely and
counted on the summary line.

KNOWN LIMITS, recorded rather than fixed. A markdown table row is one line and therefore
one unit, so a quote in one cell and a citation in another are read as one sentence; that
direction produces a false pass, never a false report. A quote spanning two lines of a
page is not seen at all, because a page is not hard-wrapped and a quotation that crosses a
paragraph break is not a quotation. An entry reflowed after a page quoted it can report a
miss that is a formatting change rather than a wording change.
"""

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MIN_WORDS = 4          # the shortest run worth checking; below this, coincidence is common
HEAD_WORDS = 10        # how much of a quote the report prints

# A wikilink, with an optional #anchor inside the target and an optional |label after it.
# The backslash before the pipe is how a link survives inside a markdown table cell.
ANY_LINK = re.compile(r'\[\[([^\[\]|]+?)(?:\\?\|(.*?))?\]\]')
SENT_END = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"“‘(\[])')
QUOTE_PAIRS = {'"': '"', '“': '”'}
# ..., . . ., the ellipsis character, and any of those in brackets, which is how an
# editorial cut is marked.
ELLIPSIS = re.compile(r'\s*(?:\[\s*)?(?:\.\s*\.\s*\.|…)(?:\s*\])?\s*')
HEADING_OR_LIST = re.compile(r'^\s*(?:[-*+]\s+|\d+[.)]\s+|>+\s*|#{1,6}\s+)+')
FENCE = re.compile(r'^\s*```')


# ---- reading, and the two frontmatter facts ---------------------------------

def read_text(path):
    with open(path, encoding='utf-8', errors='replace') as fh:
        return fh.read()


def frontmatter_private(text):
    """`private: true` in the opening frontmatter block.

    The flag often carries a trailing YAML comment saying why, so the value is read up to
    the first `#` rather than compared whole.
    """
    if not text.startswith('---'):
        return False
    end = text.find('\n---', 3)
    if end == -1:
        return False
    for line in text[3:end].split('\n'):
        m = re.match(r'^private:\s*(.*)$', line)
        if not m:
            continue
        value = m.group(1).split('#')[0].strip().strip('"').strip("'").lower()
        if value in ('true', 'yes', 'y', '1', ''):
            return True
    return False


# ---- turning a markdown line into prose -------------------------------------

def strip_markers(line):
    """Drop the list bullet, blockquote arrow, ordinal or heading hashes at the front."""
    return HEADING_OR_LIST.sub('', line)


def plain(text):
    """Markdown to prose. Links become their display text, emphasis and anchors go."""
    def link(m):
        target, display = m.group(1), m.group(2)
        if display:
            return display
        return target.split('#')[0].replace('-', ' ').replace('_', ' ')
    text = ANY_LINK.sub(link, text)
    text = re.sub(r'!\[\[.*?\]\]', ' ', text)
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = text.replace('`', '')
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'(?<!\S)\^[A-Za-z0-9][A-Za-z0-9_-]*(?!\S)', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def sentences(line):
    """Split into sentences WITHOUT cutting inside a [[wikilink]] or inside a quotation.

    Both exceptions matter. A citation's display label is often a quote carrying its own
    full stops, and splitting naively cuts the link in half, after which neither piece is
    recognised as a citation at all. A quotation carries full stops for the same reason,
    an ellipsis or two sentences of somebody talking, and a run cut in half has an
    unmatched quote character at each end, so it is not recognised as a quotation either
    and the check passes over it in silence.

    Links are masked first, so a quote sitting inside a label is already hidden when the
    quotation pass runs and is not masked twice.
    """
    links, quotes = [], []

    def mask_link(m):
        links.append(m.group(0))
        return '\x00%d\x00' % (len(links) - 1)

    masked = ANY_LINK.sub(mask_link, line)
    pieces, last = [], 0
    for open_at, close_at in quote_spans(masked):
        pieces.append(masked[last:open_at])
        quotes.append(masked[open_at:close_at + 1])
        pieces.append('\x01%d\x01' % (len(quotes) - 1))
        last = close_at + 1
    pieces.append(masked[last:])
    masked = ''.join(pieces)
    parts = [p.strip() for p in SENT_END.split(masked) if p.strip()]
    parts = parts or ([masked.strip()] if masked.strip() else [])
    out = []
    for part in parts:
        part = re.sub(r'\x01(\d+)\x01', lambda m: quotes[int(m.group(1))], part)
        out.append(re.sub(r'\x00(\d+)\x00', lambda m: links[int(m.group(1))], part))
    return out


# ---- the match --------------------------------------------------------------

def normalise(text):
    """Whitespace, quote characters, dashes and hard spaces. Nothing that changes words."""
    text = (text.replace('“', '"').replace('”', '"')
                .replace('‘', "'").replace('’', "'")
                .replace('\u2013', '-').replace('\u2014', '-')
                .replace(' ', ' '))
    return re.sub(r'\s+', ' ', text).strip()


def strip_emphasis(text):
    return re.sub(r'[*_]', '', text)


def split_ellipsis(run):
    """A quoted run cut at its ellipses. One piece when there is no ellipsis in it."""
    return [p for p in (x.strip() for x in ELLIPSIS.split(run)) if p]


def quote_spans(text):
    """(opening index, closing index) of every matched pair of double quotes, in order.

    PAIRING IS POSITIONAL, the first quote character with the second and the third with
    the fourth, and never a regex looking for a run of at least so many characters. A
    regex with a length floor inside it SKIPS a short quotation like "AI" and then pairs
    that quotation's closing quote with the next quotation's opening one, handing back the
    ordinary prose in between as though the page had quoted it. The length floor belongs
    on the run, after the pairing. A quote character with no partner is skipped rather
    than shifting every pair after it.
    """
    out, i, n = [], 0, len(text)
    while i < n:
        closer = QUOTE_PAIRS.get(text[i])
        if closer is None:
            i += 1
            continue
        close_at = text.find(closer, i + 1)
        if close_at == -1:
            i += 1
            continue
        out.append((i, close_at))
        i = close_at + 1
    return out


def quoted_runs(claim):
    """Every quoted run of MIN_WORDS words or more in a sentence already made plain."""
    out = []
    for open_at, close_at in quote_spans(claim):
        run = claim[open_at + 1:close_at].strip()
        if len(run.split()) >= MIN_WORDS:
            out.append(run)
    return out


def quote_variants(quote):
    """The forms of a quote that all mean the same words.

    Markdown escaping, the full stop or comma a page puts inside its closing quote, and
    emphasis markers are formatting rather than words.
    """
    base = normalise(quote)
    seen, out = set(), []
    for v in (base, base.replace('\\', '')):
        for w in (v, v.strip(' .,;:!?-\u2014\u2013"\'\\')):
            for x in (w, strip_emphasis(w)):
                if len(x.split()) < MIN_WORDS or x in seen:
                    continue
                seen.add(x)
                out.append(x.lower())
    return out


def quote_in_text(quote, text_lower, text_lower_noemph):
    """Exact substring, tolerant only of the things that are not content."""
    for v in quote_variants(quote):
        if v in text_lower or v in text_lower_noemph:
            return True
    return False


# ---- the source layer -------------------------------------------------------

CORPUS_JOIN = ' \x00 '     # no quote can contain a NUL, so nothing matches across a join


class SourceLayer:
    """raw/entries, read lazily. An entry is loaded the first time it is asked for.

    The whole-corpus search is built only when something is actually missing, because on
    a clean wiki nothing has to be searched and the run stays cheap.
    """

    def __init__(self, root):
        self.dir = os.path.join(root, 'raw', 'entries')
        self.paths = {}
        if os.path.isdir(self.dir):
            for name in sorted(os.listdir(self.dir)):
                if name.endswith('.md'):
                    self.paths[name[:-3]] = os.path.join(self.dir, name)
        self._cache = {}
        self._private = {}
        self._corpus = {}

    def has(self, stem):
        return stem in self.paths

    def get(self, stem):
        """(private, lowered normalised text, lowered normalised text without emphasis)."""
        if stem not in self._cache:
            text = read_text(self.paths[stem])
            norm = normalise(text)
            private = frontmatter_private(text)
            self._private[stem] = private
            self._cache[stem] = (private, norm.lower(), strip_emphasis(norm).lower())
        return self._cache[stem]

    def is_private(self, stem):
        """The flag alone, read from the head of the file rather than all of it.

        The privacy of every entry is needed to count them and to build a corpus. The TEXT
        of one is needed only when something is actually being searched for.
        """
        if stem in self._private:
            return self._private[stem]
        with open(self.paths[stem], encoding='utf-8', errors='replace') as fh:
            self._private[stem] = frontmatter_private(fh.read(8192))
        return self._private[stem]

    def private_count(self):
        return sum(1 for s in self.paths if self.is_private(s))

    def stems(self, private):
        return [s for s in sorted(self.paths) if self.is_private(s) is private]

    def _corpus_for(self, private):
        if private not in self._corpus:
            plain_parts, noemph_parts = [], []
            for stem in self.stems(private):
                _p, low, low_ne = self.get(stem)
                plain_parts.append(low)
                noemph_parts.append(low_ne)
            self._corpus[private] = (CORPUS_JOIN.join(plain_parts),
                                     CORPUS_JOIN.join(noemph_parts))
        return self._corpus[private]

    def find(self, quote, private, exclude=()):
        """The first entry of that privacy class holding the quote, or None.

        One pass over the joined corpus decides whether any entry holds it at all; only
        then is the per-file loop run to name which one. That is what keeps a clean run to
        one scan of the archive instead of one scan per file per quote.
        """
        corpus_lower, corpus_noemph = self._corpus_for(private)
        if not quote_in_text(quote, corpus_lower, corpus_noemph):
            return None
        for stem in self.stems(private):
            if stem in exclude:
                continue
            _p, low, low_ne = self.get(stem)
            if quote_in_text(quote, low, low_ne):
                return stem
        return None


# ---- the scan ---------------------------------------------------------------

def cited_entries(sentence, source):
    """The raw/entries stems this sentence links to, in order, without repeats."""
    out = []
    for m in ANY_LINK.finditer(sentence):
        stem = m.group(1).split('#')[0].strip()
        if source.has(stem) and stem not in out:
            out.append(stem)
    return out


def strip_citations(sentence, source):
    """The sentence with every citation link removed, label and all.

    A quote inside a citation's display label is the page quoting the entry AT the link,
    so checking it against that entry is checking a string against itself. Links to other
    wiki pages are left alone: their display text is ordinary prose.
    """
    def repl(m):
        stem = m.group(1).split('#')[0].strip()
        return ' ' if source.has(stem) else m.group(0)
    return ANY_LINK.sub(repl, sentence)


def head_of(quote):
    words = quote.split()
    if len(words) <= HEAD_WORDS:
        return ' '.join(words)
    return ' '.join(words[:HEAD_WORDS]) + ' ...'


def wiki_pages(root, include_all=False):
    out = []
    for base, _dirs, names in os.walk(os.path.join(root, 'wiki')):
        for name in sorted(names):
            if not name.endswith('.md'):
                continue
            if not include_all and (name.startswith('_') or name == 'log.md'):
                continue
            out.append(os.path.relpath(os.path.join(base, name), root))
    return sorted(out)


def changed_wiki_pages(root, include_all=False):
    """Wiki files changed against HEAD: staged, unstaged, or newly written.

    Untracked files that git is not ignoring count too, because a page written this
    session is the likeliest place for a quotation nobody has checked and it is neither
    staged nor unstaged until it is added. Returns None when git cannot answer, which the
    caller reports rather than treating as "nothing changed".
    """
    def git(args):
        try:
            done = subprocess.run(['git', '-C', root] + args, capture_output=True,
                                  text=True)
        except (OSError, ValueError):
            return None
        if done.returncode != 0:
            return None
        return [l.strip() for l in done.stdout.split('\n') if l.strip()]

    if git(['rev-parse', '--is-inside-work-tree']) is None:
        return None
    names = git(['diff', '--name-only', 'HEAD', '--', 'wiki'])
    if names is None:                      # a repository with no commit yet
        names = git(['diff', '--name-only', '--cached', '--', 'wiki']) or []
    others = git(['ls-files', '--others', '--exclude-standard', '--', 'wiki']) or []
    out = []
    for rel in sorted(set(names) | set(others)):
        if not rel.endswith('.md'):
            continue
        name = os.path.basename(rel)
        if not include_all and (name.startswith('_') or name == 'log.md'):
            continue
        if os.path.isfile(os.path.join(root, rel)):
            out.append(rel)
    return out


def scan_page(rel, root, source, findings, counts):
    text = read_text(os.path.join(root, rel))
    if frontmatter_private(text):
        counts['private_wiki_pages_skipped'] += 1
        return
    counts['wiki_pages_read'] += 1
    in_fence = False
    for lineno, line in enumerate(text.split('\n'), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or '[[' not in line or ('"' not in line and '“' not in line):
            continue
        for sentence in sentences(strip_markers(line)):
            cited = cited_entries(sentence, source)
            if not cited:
                continue
            claim = plain(strip_citations(sentence, source))
            runs = quoted_runs(claim)
            if not runs:
                continue
            counts['sentences_with_quotes'] += 1
            counts['quoted_runs_seen'] += len(runs)
            for run in runs:
                pieces = split_ellipsis(run)
                if len(pieces) > 1:
                    counts['runs_split_at_an_ellipsis'] += 1
                for piece in pieces:
                    if len(piece.split()) < MIN_WORDS:
                        counts['pieces_too_short_to_check'] += 1
                        continue
                    counts['quotes_checked'] += 1
                    if any(quote_in_text(piece, *source.get(s)[1:]) for s in cited):
                        continue
                    counts['not_in_the_cited_entry'] += 1
                    elsewhere = source.find(piece, private=False, exclude=cited)
                    held_privately = None
                    if elsewhere is None:
                        held_privately = source.find(piece, private=True, exclude=cited)
                        counts['nowhere_in_the_non_private_source_layer'] += 1
                        if held_privately:
                            counts['held_by_a_private_entry'] += 1
                    else:
                        counts['wrong_source'] += 1
                    findings.append({
                        'page': rel,
                        'line': lineno,
                        'quote': piece,
                        'head': head_of(piece),
                        'cited': cited,
                        'verdict': 'wrong-source' if elsewhere else 'not-found',
                        'found_in': elsewhere,
                        'private_entry_holds': held_privately,
                    })


def check_vault(root=None, pages=None, changed=False, include_all=False, page=None):
    """The whole check. Returns a dict of findings, counts and what was read.

    `pages` is an explicit list of relative wiki paths; `page` is one of them; `changed`
    asks git. None of them ever reaches outside wiki/.
    """
    root = os.path.abspath(root or ROOT)
    source = SourceLayer(root)
    note = ''
    if page is not None:
        rel = os.path.relpath(os.path.abspath(page), root)
        # This tool reads the compiled layer only. A --page pointing at an entry or at
        # something outside the brain is refused out loud rather than quietly scanned,
        # because the report's whole meaning is "a wiki page quotes an entry".
        if rel != 'wiki' and not rel.startswith('wiki' + os.sep):
            pages = []
            note = '--page must name a file under wiki/, and %s is not' % rel
        else:
            pages = [rel]
    elif changed:
        pages = changed_wiki_pages(root, include_all=include_all)
        if pages is None:
            pages, note = [], 'git could not answer which wiki files changed'
    elif pages is None:
        pages = wiki_pages(root, include_all=include_all)

    counts = dict(wiki_pages_read=0, private_wiki_pages_skipped=0, sentences_with_quotes=0,
                  quoted_runs_seen=0, runs_split_at_an_ellipsis=0,
                  pieces_too_short_to_check=0, quotes_checked=0,
                  not_in_the_cited_entry=0, wrong_source=0,
                  nowhere_in_the_non_private_source_layer=0, held_by_a_private_entry=0)
    findings = []
    for rel in pages:
        if os.path.isfile(os.path.join(root, rel)):
            scan_page(rel, root, source, findings, counts)
    return {
        'root': root,
        'note': note,
        'pages_requested': len(pages),
        'entries_indexed': len(source.paths),
        'private_entries': source.private_count(),
        'counts': counts,
        'findings': findings,
    }


# ---- output -----------------------------------------------------------------

def one_line(finding):
    """One line per finding. Never prints the text of an entry, private or not."""
    where = '%s:%d' % (finding['page'], finding['line'])
    cited = ', '.join(finding['cited'])
    if finding['verdict'] == 'wrong-source':
        return ('%s quotes "%s" citing %s, and those words are in %s instead. The citation '
                'points at the wrong entry.'
                % (where, finding['head'], cited, finding['found_in']))
    tail = ''
    if finding['private_entry_holds']:
        tail = (' The private entry %s does hold them, so the citation may simply name the '
                'wrong file.' % finding['private_entry_holds'])
    return ('%s quotes "%s" citing %s, and those words are in no non-private entry. Check '
            'the wording against the source, or say where the quote came from.%s'
            % (where, finding['head'], cited, tail))


def print_report(result):
    c = result['counts']
    by_page = {}
    for f in result['findings']:
        by_page.setdefault(f['page'], []).append(f)
    for page in sorted(by_page):
        print('')
        print('%s (%d)' % (page, len(by_page[page])))
        for f in sorted(by_page[page], key=lambda x: x['line']):
            if f['verdict'] == 'wrong-source':
                verdict = 'WRONG SOURCE: those words are in %s' % f['found_in']
            elif f['private_entry_holds']:
                verdict = ('NOT FOUND in any non-private entry; the private entry %s holds '
                           'them' % f['private_entry_holds'])
            else:
                verdict = 'NOT FOUND in the non-private source layer'
            print('  %s:%d  "%s"  cited: %s  ->  %s'
                  % (f['page'], f['line'], f['head'], ', '.join(f['cited']), verdict))
    print('')
    if result['note']:
        print('note: %s' % result['note'])
    print('quote check: %d wiki page(s) read of %d asked for; %d entr%s indexed (%d private)'
          % (c['wiki_pages_read'], result['pages_requested'], result['entries_indexed'],
             'y' if result['entries_indexed'] == 1 else 'ies', result['private_entries']))
    print('  quoted runs seen: %d   quotes checked: %d   split at an ellipsis: %d   '
          'pieces under %d words: %d'
          % (c['quoted_runs_seen'], c['quotes_checked'], c['runs_split_at_an_ellipsis'],
             MIN_WORDS, c['pieces_too_short_to_check']))
    print('  not in the cited entry: %d   of those, wrong source: %d   nowhere in the '
          'non-private source layer: %d (%d held by a private entry)'
          % (c['not_in_the_cited_entry'], c['wrong_source'],
             c['nowhere_in_the_non_private_source_layer'], c['held_by_a_private_entry']))
    if c['private_wiki_pages_skipped']:
        print('  wiki pages skipped for private: true: %d' % c['private_wiki_pages_skipped'])
    print('  this tool reports and never blocks; a quote may be accurate and live in a '
          'source this brain does not hold.')


USAGE = __doc__.split('\n\nWHAT IT IS')[0]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = changed = include_all = False
    page = None
    while argv:
        arg = argv.pop(0)
        if arg == '--json':
            as_json = True
        elif arg == '--changed':
            changed = True
        elif arg == '--all':
            include_all = True
        elif arg == '--page':
            if not argv:
                print('--page needs a path', file=sys.stderr)
                return 0
            page = argv.pop(0)
        elif arg in ('-h', '--help'):
            print(USAGE)
            return 0
        else:
            print('unknown argument: %s' % arg, file=sys.stderr)
            print(USAGE, file=sys.stderr)
            return 0
    result = check_vault(changed=changed, include_all=include_all, page=page)
    if as_json:
        print(json.dumps(result, indent=1, ensure_ascii=False))
    else:
        print_report(result)
    # Always 0. This tool reports; it is not a gate and it never refuses a commit.
    return 0


if __name__ == '__main__':
    sys.exit(main())
