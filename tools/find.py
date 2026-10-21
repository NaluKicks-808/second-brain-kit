#!/usr/bin/env python3
# Retrieval - search-first answering, in one cheap call.
#     python3 tools/find.py brake service
#     python3 tools/find.py --deep "winter tune-up"
#     python3 tools/find.py "two words" another
#     python3 tools/find.py --help
#
# TWO LAYERS, BOTH QUERYABLE. That split is the whole point of the brain.
#   * The default searches wiki/, the compiled SUMMARY layer. Fast, and usually
#     enough to answer outright.
#   * --deep ALSO searches the FULL-CONTEXT layer: raw/ and data/. Reach for it when
#     a summary will not do and you need the exact words - a dispute, a record,
#     documentation, or a summary that simply is not specific enough.
#
# RANKING (find_rank.py, standard library). BM25 with a title boost: a rarer term
# counts for more, repeats add less and less, long files are not favoured for being
# long, and a term in the H1 title or path counts double. Plain mention counts let
# the longest ledgers win. Stopwords and words under three letters are dropped when
# other terms remain, except a capitalised two-letter acronym (AI, QA), which is
# matched as a whole word. RANKED FILES holds only files containing a term; the
# number beside each is its raw hit count.
#
# Underscore files and log.md (the ledgers) are listed in a SYSTEM PAGES block of
# their own, ranked by raw hits, so a ledger neither crowds out an article nor
# vanishes.
#
# No semantic or embedding layer ships with the kit: ranking is keyword-only on
# purpose, so it needs no install and no model. A larger vault can add one behind
# this same output shape.
#
# Each argument that is not a flag is one term, matched case-insensitively and OR-ed
# with the others. Quote a term that contains a space. Exit 0 = found, 1 = no file
# holds a term, 2 = usage.

import os
import re
import sys
import glob

sys.dont_write_bytecode = True   # importing find_rank must not leave __pycache__/ in the vault
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import find_rank

HELP = """find.py - search the brain, search-first.

usage: python3 tools/find.py [--deep] <term> [term ...]

  <term>   each argument is one term, OR-ed; quote a phrase ("winter tune-up")
  --deep   also search raw/ and data/ (the full-context layer)

Ranking: BM25 + title boost. Ledger pages (underscore files, log.md) are listed apart.
Exit 0 = found, 1 = no file holds a term, 2 = usage."""

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARGS = sys.argv[1:]
if '--help' in ARGS or '-h' in ARGS:
    print(HELP)
    sys.exit(0)
DEEP = ('--deep' in ARGS) or ('--full' in ARGS)
TERMS = find_rank.usable_terms([t for t in ARGS if not t.startswith('--')])
if not TERMS:
    print("usage: python3 tools/find.py [--deep] <term> [term ...]   (--help for more)")
    sys.exit(2)

TOP_FILES, SNIPPET_FILES, SNIPPETS_PER, LINE_CAP = 10, 5, 5, 220
SYSTEM_FILES = 3   # how many ledger pages the SYSTEM PAGES block lists

# (layer label, roots, filename patterns). The order sets the tie-break preference.
LAYERS = [('wiki', [os.path.join(ROOT, 'wiki')], ('*.md',))]
if DEEP:
    LAYERS += [
        ('raw', [os.path.join(ROOT, 'raw')], ('*.md', '*.txt')),
        ('data', [os.path.join(ROOT, 'data')], ('*.md', '*.txt')),
    ]

pat = find_rank.pattern(TERMS)
SEARCHED = [0]   # files read: BM25's N (how rare a term is across the search)


def label(fp):
    try:
        return os.path.relpath(fp, ROOT)
    except ValueError:
        return fp


def summary(text):
    body = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.S)
    for line in body.splitlines():
        s = line.strip()
        if s and not s.startswith('#') and not s.startswith('>'):
            return (s[:160] + '…') if len(s) > 160 else s
    return ''


def walk(roots, globs):
    """Every readable file under roots matching globs that mentions a term, as
    (hits, path, text). An unreadable file is skipped, never fatal. Order is
    roots, then globs, then sorted paths, which the stable sorts below rely on."""
    for root in roots:
        for g in globs:
            for fp in sorted(glob.glob(os.path.join(root, '**', g), recursive=True)):
                try:
                    text = open(fp, encoding='utf-8', errors='ignore').read()
                except Exception:
                    continue
                SEARCHED[0] += 1
                h = find_rank.hits(text.lower(), TERMS)
                if h:
                    yield h, fp, text


found = []
for lname, roots, globs in LAYERS:
    for h, fp, text in walk(roots, globs):
        found.append((h, lname, label(fp), text))

if not found:
    scope = "the wiki and full-context layers" if DEEP else "the wiki"
    print("no matches for %s in %s." % (TERMS, scope)
          + ("" if DEEP else " Try --deep to search the source layer too, or fall back "
                             "to wiki/_index.md."))
    sys.exit(1)

total_hits = sum(p[0] for p in found)
order = find_rank.bm25_order([(p[2], p[3]) for p in found], TERMS, SEARCHED[0])
ranked = [found[i] for i in order]
articles = [p for p in ranked if not find_rank.is_system(p[2])]
# Ledgers go by raw hits: BM25 over long ledgers favours the index and trackers.
system_pages = sorted([p for p in found if find_rank.is_system(p[2])],
                      key=lambda p: -p[0])[:SYSTEM_FILES]
if not articles:            # only ledgers mention the terms: they are the results, no block
    articles, system_pages = ranked, []

scope = "wiki + full-context (raw/data)" if DEEP else "wiki (summary layer)"
print("find.py - %d hit(s) for %s across %d file(s) - searching %s"
      % (total_hits, TERMS, len(found), scope))
print("ranked by keywords (BM25 + title boost)")
print("\nRANKED FILES (open the top one or two; grep big files to lines rather than "
      "reading whole):")
for h, lname, rel, text in articles[:TOP_FILES]:
    print("  %3d  [%s]  %s" % (h, lname, rel))
    s = summary(text) if lname in ('wiki', 'raw') else ''
    if s:
        print("       └ %s" % s)
if system_pages:
    print("\nSYSTEM PAGES (the ledger, postmortems, the log; grep these to the matching rows):")
    for h, lname, rel, text in system_pages:
        print("  %3d  [%s]  %s" % (h, lname, rel))
if not DEEP:
    print("\n(only the summary layer was searched - add --deep to also search the source "
          "layer)")
print()

shown_files = (articles[:SNIPPET_FILES - 1] + system_pages[:1]) if system_pages \
    else articles[:SNIPPET_FILES]
for h, lname, rel, text in shown_files:
    print("── [%s] %s - matching lines ──" % (lname, rel))
    lines = text.splitlines()
    shown = 0
    for i, line in enumerate(lines, 1):
        if pat.search(line):
            s = line.strip()
            print("  %d: %s" % (i, (s[:LINE_CAP] + '…') if len(s) > LINE_CAP else s))
            shown += 1
            if shown >= SNIPPETS_PER:
                extra = sum(1 for l in lines if pat.search(l)) - shown
                if extra > 0:
                    print("  … +%d more matching line(s) in this file" % extra)
                break
    print()
