#!/usr/bin/env python3
# The reciprocity gate - the "did you weave it in?" check. Run it at the end of
# every absorb, just before committing:
#     python3 tools/connect.py
#
# THE PROBLEM IT CATCHES. A page you just wrote MENTIONS somebody - [[sam-rivera]] -
# but you never opened THEIR page to record the same fact from their side, and their
# page never links back. The new knowledge sits on one side of a one-way street. The
# link is not broken, so the linter cannot see it. This can.
#
# It is surgical. A link counts as "newly named" only if the target was not linked
# from this page BEFORE this session and is now: a set difference between the old
# and new file, rather than a line diff, which would over-report because the writing
# standard puts one paragraph on one line, so any edit to a paragraph re-adds every
# link in it. For each genuinely new link S -> T it asks one question: was T ALSO
# edited this session, or does T already link back to S? If neither, T heard about
# S's new material and did not absorb it. Resolve it - usually by updating T; now and
# then by deciding the one-way mention is genuine passing context.
#
# SCOPE. Uncommitted changes, which is the whole absorb before you commit. When the
# tree is clean it falls back to the last commit, which across a multi-commit session
# can show residual cross-commit flags; the signal that matters is the run you do
# immediately before committing.
#
# MODES:
#     python3 tools/connect.py            # this session's changes
#     python3 tools/connect.py --all      # every one-way link in the whole vault
#
# EXIT: 1 when a HIGH-VALUE target is un-woven or a new page is linked from nowhere.
# Those are real gates. 0 otherwise; the softer advisories still print.

import os
import re
import sys
import glob
import subprocess

# Found from this script's own location, never from the working directory.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIKI = os.path.join(ROOT, 'wiki')

# Machinery, not articles. A mention of the index is not a fact that needs weaving.
META = set(['_index', 'log', '_reminders', '_postmortems'])

# The folders where a one-way mention is a real gap rather than a note. These are
# the pages that describe an entity with its own side of the story - a person, a
# venture - so a fact about them written anywhere else belongs on their page too.
# Widen this as your taxonomy grows.
HIGH_VALUE = ('wiki/people/', 'wiki/projects/')

LINK = re.compile(r'\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]')


def git(*args):
    return subprocess.run(['git'] + list(args), capture_output=True, text=True,
                          cwd=ROOT).stdout


def links_in(text):
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    return set(m.group(1).strip().rstrip('\\')
               for m in LINK.finditer(re.sub(r'`[^`]*`', '', text)))


def session_changes():
    """{relpath: set of newly introduced link targets}, the set of brand-new pages,
    and a label saying where that reading came from."""
    def newlinks(old_body, new_body):
        return links_in(new_body) - links_in(old_body)

    changed, new = {}, set()
    porcelain = git('status', '--porcelain', '--', 'wiki').splitlines()
    if porcelain:
        for line in porcelain:
            status, path = line[:2], line[3:].strip()
            if ' -> ' in path:
                path = path.split(' -> ')[-1]
            if not (path.startswith('wiki/') and path.endswith('.md')):
                continue
            if 'D' in status:
                # Deleted on disk: no new body, so nothing new to weave. Without this
                # the gate crashes, and a hook that only greps for GAP lines then lets
                # the commit through.
                continue
            new_body = open(os.path.join(ROOT, path), encoding='utf-8').read()
            if '?' in status or 'A' in status:      # untracked or newly added
                old_body = ''
                new.add(path)
            else:
                old_body = git('show', 'HEAD:%s' % path)
            changed[path] = newlinks(old_body, new_body)
        return changed, new, 'uncommitted changes'

    for path in git('diff', '--name-only', 'HEAD~1', 'HEAD', '--', 'wiki').splitlines():
        if path.startswith('wiki/') and path.endswith('.md'):
            changed[path] = newlinks(git('show', 'HEAD~1:%s' % path),
                                     git('show', 'HEAD:%s' % path))
    for path in git('diff', '--name-only', '--diff-filter=A', 'HEAD~1', 'HEAD',
                    '--', 'wiki').splitlines():
        if path.startswith('wiki/') and path.endswith('.md'):
            new.add(path)
    return changed, new, 'the last commit (HEAD~1..HEAD)'


# Every page's full outbound links, so a back-reference can be tested.
pages, outbound = {}, {}
for fp in glob.glob(os.path.join(WIKI, '**', '*.md'), recursive=True):
    pages[os.path.splitext(os.path.basename(fp))[0]] = os.path.relpath(fp, ROOT)
for base, rel in pages.items():
    body = open(os.path.join(ROOT, rel), encoding='utf-8').read()
    outbound[base] = links_in(body)


# ── whole-vault audit: every one-way peer link there is ───────────────────────
# For backfilling gaps that predate the tool. Noisy by nature: triage, do not
# mass-fix. A forced link is worse than a missing one.
if '--all' in sys.argv:
    hard, soft = [], []
    for base in sorted(pages):
        if base in META:
            continue
        for tgt in sorted(outbound.get(base, ())):
            if tgt not in pages or tgt == base or tgt in META:
                continue
            if base in outbound.get(tgt, ()):
                continue
            row = "%s  ->  [[%s]]   (%s has no back-link)" % (pages[base], tgt, pages[tgt])
            (hard if pages[tgt].startswith(HIGH_VALUE) else soft).append(row)
    print("connect.py --all - whole-vault reciprocity audit (%d pages)\n" % len(pages))
    if hard:
        print("ONE-WAY into %s (%d) - the high-value backfill candidates:"
              % (' or '.join(HIGH_VALUE), len(hard)))
        for r in hard:
            print("  ", r)
        print()
    if soft:
        print("ONE-WAY into other folders (%d) - mostly legitimate context links:" % len(soft))
        for r in soft:
            print("  ", r)
        print()
    print("summary: %d high-value, %d other. Backfill only where the target genuinely "
          "benefits." % (len(hard), len(soft)))
    sys.exit(0)


changed, new, src = session_changes()
touched_rel = set(changed)

hard, soft, orphans = [], [], []
for rel, new_targets in sorted(changed.items()):
    base = os.path.splitext(os.path.basename(rel))[0]
    if base not in META:
        for tgt in sorted(new_targets):
            if tgt not in pages or tgt == base or tgt in META:
                continue
            t_rel = pages[tgt]
            if t_rel in touched_rel:              # both sides edited - good
                continue
            if base in outbound.get(tgt, ()):     # the target already links back
                continue
            row = "%s  ->  [[%s]]   (%s not updated, no back-link)" % (rel, tgt, t_rel)
            (hard if t_rel.startswith(HIGH_VALUE) else soft).append(row)
    if rel in new and not any(base in outbound.get(b, ()) for b in pages if b != base):
        orphans.append(rel)


# ── claim reciprocity (advisory, never blocks) ────────────────────────────────
# The check above catches a one-way LINK. This one catches a one-way FACT: you
# changed a line that asserts something, and other pages assert the same thing and
# still say the old version. It is deliberately NOT "is this a contradiction",
# which cannot be computed and would false-positive into being ignored. It answers
# only: here are the other places that talk about this. That is the whole of what a
# session needs in order not to miss one.
#
# It is noisy by nature, so it never touches the exit code. A noisy blocking gate is
# a gate that gets bypassed.
_PHRASE = re.compile(r'\b([A-Z][a-z0-9]+(?:[ -][A-Z][a-z0-9]+){1,3})\b')
_TICKED = re.compile(r'`([A-Za-z0-9_./-]{4,})`')
_FILE = re.compile(r'\b([a-z][a-z0-9_-]{2,}\.(?:py|sh|json|md))\b')
_HYPHEN = re.compile(r'\b([a-z]{3,}(?:-[a-z]{3,}){1,2})\b')
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]{3,}")
_STOP = set(['The', 'This', 'That', 'There', 'These', 'Those', 'It', 'But', 'And',
             'For', 'When', 'What', 'Read', 'Write', 'Note', 'See', 'Source',
             'Sources', 'Claude', 'Obsidian'])
_STOPW = set(['that', 'this', 'with', 'from', 'have', 'been', 'were', 'they', 'their',
              'which', 'would', 'about', 'there', 'these', 'those', 'than', 'then',
              'when', 'what', 'into', 'only', 'also', 'because', 'before', 'after',
              'still', 'every', 'some', 'same', 'such', 'more', 'most', 'page',
              'pages', 'file', 'files', 'vault', 'wiki', 'claude', 'session',
              'sessions'])
CLAIM_MAX_FILES = 12     # a term in more files than this is vocabulary, not a claim
CLAIM_MAX_ROWS = 16


def _terms(lines):
    """Two kinds of candidate. CERTAIN: proper-noun phrases, backticked identifiers,
    bare filenames, hyphenated compounds - distinctive on their face. MEASURED:
    ordinary lowercase bigrams, emitted without guessing which ones matter and left
    for the file-count threshold below to sort out. Guessing is hopeless and a
    curated lexicon decays."""
    certain, measured = set(), set()
    for ln in lines:
        for m in _TICKED.finditer(ln):
            certain.add(m.group(1))
        for m in _FILE.finditer(ln):
            certain.add(m.group(1))
        for m in _HYPHEN.finditer(ln):
            certain.add(m.group(1))
        for m in _PHRASE.finditer(ln):
            w = m.group(1).replace('-', ' ').split()
            while w and w[0] in _STOP:
                w.pop(0)
            while w and w[-1] in _STOP:
                w.pop()
            if len(w) >= 2 and len(' '.join(w)) >= 6:
                certain.add(' '.join(w))
        ws = [w.lower() for w in _WORD.findall(ln)]
        for a, b in zip(ws, ws[1:]):
            if a in _STOPW or b in _STOPW:
                continue
            measured.add('%s %s' % (a, b))
    return certain, measured


def _surfaces():
    """Every file that holds state about this vault. The log is left out on purpose:
    it is append-only history, so it mentions everything forever and would drown
    every real hit."""
    out = glob.glob(os.path.join(WIKI, '**', '*.md'), recursive=True)
    out.append(os.path.join(ROOT, 'CLAUDE.md'))
    skip = ('wiki/log.md', 'wiki/_postmortems.md')
    return [f for f in out if os.path.exists(f)
            and not any(f.replace(os.sep, '/').endswith(s) for s in skip)]


def _changed_lines(path):
    rel = os.path.relpath(path, ROOT).replace(os.sep, '/')
    old = git('show', 'HEAD:%s' % rel)
    if not old and not os.path.exists(path):
        return []
    new_text = open(path, encoding='utf-8', errors='replace').read()
    return [l for l in set(new_text.splitlines()) - set(old.splitlines())
            if len(l.strip()) > 30]


def claim_reciprocity():
    edited = []
    for l in git('status', '--porcelain').splitlines():
        p = l[3:].strip().split(' -> ')[-1]
        if p.endswith('.md') and (p.startswith('wiki/') or p == 'CLAUDE.md'):
            edited.append(os.path.join(ROOT, p))
    edited = [p for p in edited if os.path.exists(p) and not p.endswith('log.md')]
    if not edited:
        return []
    certain, measured = set(), set()
    for p in edited:
        c, m = _terms(_changed_lines(p))
        certain |= c
        measured |= m
    if not (certain or measured):
        return []
    corpus = {}
    for f in _surfaces():
        try:
            corpus[f] = open(f, encoding='utf-8', errors='replace').read()
        except OSError:
            pass
    edited_set = set(edited)

    def pretty(w):
        return os.path.relpath(w, ROOT) if w.startswith(ROOT) else w

    def first_line(body, term):
        for ln in body.splitlines():
            if term in ln:
                ln = ln.strip()
                return (ln[:118] + '…') if len(ln) > 118 else ln
        return ''

    hits = []
    for term in sorted(certain | measured):
        where = [f for f, body in corpus.items() if term in body and f not in edited_set]
        if not where or len(where) > CLAIM_MAX_FILES:
            continue
        hits.append((term, [(pretty(f), first_line(corpus[f], term)) for f in where]))
    # Ascending: a claim asserted in two or three other places is the drift case. A
    # term in eleven is closer to vocabulary, so it sinks.
    return sorted(hits, key=lambda h: len(h[1]))[:CLAIM_MAX_ROWS]


print("connect.py - reviewing %d touched wiki page(s) from %s\n" % (len(changed), src))
if orphans:
    print("NEW PAGES NOT LINKED FROM ANYWHERE (add them to the index and to a page that "
          "should mention them):")
    for r in orphans:
        print("  NEW  ", r)
    print()
if hard:
    print("UN-WOVEN - pages you newly named but did not update (resolve each):")
    for r in hard:
        print("  GAP  ", r)
    print()
if soft:
    print("ADVISORY - other new one-way links (update the target, or confirm it is just "
          "context):")
    for r in soft:
        print("  note ", r)
    print()
if not (hard or soft or orphans):
    print("All newly added links are woven in - every named peer was updated or links back.")

_claims = claim_reciprocity()
if _claims:
    print("CLAIM RECIPROCITY - you changed a line mentioning these, and these other files")
    print("also mention them. Check each is still true there. (Advisory - never blocks.)")
    for term, where in _claims:
        print("  claim  %s" % term)
        for w, line in where[:4]:
            print("           also in  %s" % w)
            if line:
                print("                    %s" % line)
        if len(where) > 4:
            print("           ...and %d more" % (len(where) - 4))
    print()

print("summary: %d un-woven, %d advisory, %d unlinked new page(s)"
      % (len(hard), len(soft), len(orphans)))
print("         %d claim(s) asserted in more than one place" % len(_claims))
sys.exit(1 if (hard or orphans) else 0)
