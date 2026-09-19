#!/usr/bin/env python3
# Retrieval - search-first answering, in one cheap call.
#     python3 tools/find.py brake service
#     python3 tools/find.py --deep "winter tune-up"
#     python3 tools/find.py "two words" another
#
# TWO LAYERS, BOTH QUERYABLE. That split is the whole point of the brain.
#   * The default searches wiki/, the compiled SUMMARY layer. Fast, and usually
#     enough to answer outright.
#   * --deep ALSO searches the FULL-CONTEXT layer: raw/entries/ and data/. Reach for
#     it when a summary will not do and you need the exact words - a dispute, a
#     record, documentation, or a summary that simply is not specific enough.
#
# It ranks files by how much they mention the terms and prints, for the top hits, a
# one-line label plus the matching lines. Open the top file or two; grep a big file
# down to its lines rather than reading the whole thing. Search cost stays flat as
# the vault grows. Reading the index every time does not.
#
# Each argument that is not a flag is one term, matched case-insensitively and OR-ed
# with the others. Quote a term that contains a space.

import os
import re
import sys
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEEP = ('--deep' in sys.argv) or ('--full' in sys.argv)
TERMS = [t.lower() for t in sys.argv[1:] if not t.startswith('--')]
if not TERMS:
    print("usage: python3 tools/find.py [--deep] <term> [term ...]")
    sys.exit(2)

TOP_FILES, SNIPPET_FILES, SNIPPETS_PER, LINE_CAP = 10, 5, 5, 220

# (layer label, roots, filename patterns). The order sets the tie-break preference.
LAYERS = [('wiki', [os.path.join(ROOT, 'wiki')], ('*.md',))]
if DEEP:
    LAYERS += [
        ('raw', [os.path.join(ROOT, 'raw')], ('*.md', '*.txt')),
        ('data', [os.path.join(ROOT, 'data')], ('*.md', '*.txt')),
    ]


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


def hits(text):
    low = text.lower()
    return sum(low.count(t) for t in TERMS)


found = []
for lname, roots, globs in LAYERS:
    for root in roots:
        for g in globs:
            for fp in glob.glob(os.path.join(root, '**', g), recursive=True):
                try:
                    text = open(fp, encoding='utf-8', errors='ignore').read()
                except Exception:
                    continue
                h = hits(text)
                if h:
                    found.append((h, lname, label(fp), text))
found.sort(key=lambda p: -p[0])

if not found:
    scope = "the wiki and full-context layers" if DEEP else "the wiki"
    print("no matches for %s in %s." % (TERMS, scope)
          + ("" if DEEP else " Try --deep to search the source layer too, or fall back "
                             "to wiki/_index.md."))
    sys.exit(1)

scope = "wiki + full-context (raw/data)" if DEEP else "wiki (summary layer)"
print("find.py - %d hit(s) for %s across %d file(s) - searching %s\n"
      % (sum(p[0] for p in found), TERMS, len(found), scope))
print("RANKED FILES (open the top one or two; grep big files to lines rather than "
      "reading whole):")
for h, lname, rel, text in found[:TOP_FILES]:
    print("  %3d  [%s]  %s" % (h, lname, rel))
    s = summary(text) if lname in ('wiki', 'raw') else ''
    if s:
        print("       └ %s" % s)
if not DEEP:
    print("\n(only the summary layer was searched - add --deep to also search the source "
          "layer)")
print()

pat = re.compile('|'.join(re.escape(t) for t in TERMS), re.I)
for h, lname, rel, text in found[:SNIPPET_FILES]:
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
