#!/usr/bin/env python3
# The self-critic - the GROWTH loop. Read-only, and it never edits anything.
#     python3 tools/critic.py
#
# lint.py and connect.py keep the brain CONSISTENT: they are commit gates that block
# bad state. This keeps it GROWING. It is the missing half of "self-improving":
# instead of waiting for you to notice a thin spot, the brain reads itself and
# surfaces its own highest-leverage gaps as a worklist. It only reports. Deepening
# still runs under the constitution - reread the page before editing it, and never
# invent.
#
# WHAT IT REPORTS (advisory; it always exits 0):
#   1. DEEPENING CANDIDATES - pages the vault itself treats as important (many
#      inbound links, many cited sources, lots of un-mined source material) and that
#      are still THIN. Biggest importance-to-depth gaps first. This is the queue.
#   2. OPEN QUESTIONS - every [!question] callout the brain has recorded, gathered
#      into one place: the set of things it already knows it does not know.
#   3. STALE BUT CENTRAL - central pages whose `updated` stamp is oldest, so a life
#      that has moved on is not frozen behind a stale summary.
#   4. UNDER-CONNECTED - pages with at most one inbound link: real, but barely woven
#      into the graph. The linter only fails on a hard zero.
#
# The loop closes when a session runs this, then acts on the top of list 1.

import os
import re
import glob
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIKI = os.path.join(ROOT, 'wiki')
ENTRIES = os.path.join(ROOT, 'raw', 'entries')

# Not real pages: indexes and ledgers. A blank form or a catalog is short by
# definition, which is the one kind of thinness that is correct.
META = set(['_index', 'log', '_reminders', '_postmortems'])

TODAY = datetime.date.today()
THIN_WORDS = 260          # shorter than this is a candidate if the vault leans on it
STALE_DAYS = 120          # a central page older than this is worth a re-look
MIN_NAME = 4              # a name shorter than this is too generic to match on
LINK = re.compile(r'\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]')


def strip(text):
    text = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.S)   # frontmatter
    text = re.sub(r'```.*?```', '', text, flags=re.S)          # code fences
    return re.sub(r'`[^`]*`', '', text)


def frontmatter(text):
    m = re.match(r'^---\n(.*?)\n---', text, flags=re.S)
    return m.group(1) if m else ''


def fm_list_count(fm, field):
    """Items in a YAML list, or 1 for a single inline value."""
    lines = fm.splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r'^%s:\s*(.*)$' % field, ln)
        if not m:
            continue
        inline = m.group(1).strip()
        if inline and inline != '|' and not inline.startswith('#'):
            return 1
        n = 0
        for sub in lines[i + 1:]:
            if re.match(r'^\s*-\s+', sub):
                n += 1
            elif re.match(r'^\w', sub):
                break
        return n
    return 0


def normalize(s):
    """Lowercase a name and reduce every run of punctuation or whitespace to one
    space, so a slug, a title and a frontmatter alias all reduce to one shape."""
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


# WHY THIS MATCHES WHOLE NAMES AND NEVER THE WORDS INSIDE THEM.
#
# The obvious version of the source-material count splits a page's slug and title
# into words, keeps the long ones, and credits the page for every source entry
# containing any one of them. That makes the ranking noise, and the numbers look
# plausible enough that nobody checks: a page named `story-closer-to-the-coast`
# gets credited for every entry containing the word "story", which is a fact about
# the naming convention rather than about importance.
#
# The rule here: an identifier is a page's WHOLE name - the whole slug, a whole
# `aliases:` entry, or a whole title that names something the slug does not. A word
# cut out of a longer name is a fragment and is never matched on its own.
#
# Three details, each of which is why a plainer rule would be wrong:
#   1. "Drop single words" is wrong. A one-word slug for a central person IS their
#      identifier, not a fragment of one, so it keeps its full behaviour.
#   2. "Drop words that appear in many entries" is wrong from the other side: a
#      genuinely central person appears across a large share of the corpus, so
#      filtering on frequency would delete the strongest real signals first.
#      Frequency is not consulted anywhere here.
#   3. The fragment rule applies to the title as well as to the slug, which is where
#      it bites: a one-word title that is a word of its own slug is a display
#      shortening, not a second name. A multi-word title is a whole name and is kept.
# Matching is whole-word and separator-agnostic, so the page `art` does not match
# `start`, and the name `unit economics` matches an entry that wrote `unit-economics`.
def aliases(fm, base, title):
    names = set()
    slug = normalize(base)
    if len(slug) >= MIN_NAME:
        names.add(slug)
    t = normalize(title or '')
    shortening = ' ' not in t and t != slug and t in slug.split()
    if len(t) >= MIN_NAME and not shortening:
        names.add(t)
    m = re.search(r'^aliases:\s*\n((?:\s*-\s+.*\n?)+)', fm, flags=re.M)
    if m:
        for a in re.findall(r'-\s+(.+)', m.group(1)):
            a = normalize(a.strip().strip('"\''))
            if len(a) >= MIN_NAME:
                names.add(a)
    return names


def word_stream(text):
    """A source entry reduced to its words, space-separated and space-padded, so that
    matching a padded name against it is whole-word by construction."""
    toks = re.findall(r'[a-z0-9]+', text.lower())
    return set(toks), ' %s ' % ' '.join(toks)


def mentions(words, stream, names):
    """True when any whole name appears in one source entry. A one-word name is
    settled by the token set outright; a multi-word name is rejected cheaply unless
    every one of its words is present, so the scan only runs where it could win."""
    for name, parts in names:
        if len(parts) == 1:
            if parts[0] in words:
                return True
        elif all(part in words for part in parts) and ' %s ' % name in stream:
            return True
    return False


# ── load every page ───────────────────────────────────────────────────────────
pages = {}
for fp in glob.glob(os.path.join(WIKI, '**', '*.md'), recursive=True):
    base = os.path.splitext(os.path.basename(fp))[0]
    text = open(fp, encoding='utf-8', errors='ignore').read()
    fm = frontmatter(text)
    tm = re.search(r'^#\s+(.+)', text, flags=re.M)
    title = tm.group(1).strip() if tm else base
    updated = re.search(r'^updated:\s*(\d{4}-\d{2}-\d{2})', fm, flags=re.M)
    pages[base] = {
        'rel': os.path.relpath(fp, ROOT), 'text': text, 'fm': fm, 'title': title,
        'words': len(strip(text).split()),
        'sources': fm_list_count(fm, 'sources'),
        'inbound': 0,
        'updated': updated.group(1) if updated else None,
        'aliases': aliases(fm, base, title),
    }

# Inbound links, excluding the index: importance is how much the REST of the brain
# leans on a page, and the index links to everything by construction.
for base, p in pages.items():
    if base == '_index':
        continue
    for m in LINK.finditer(strip(p['text'])):
        tgt = m.group(1).strip().rstrip('\\')
        if tgt in pages and tgt != base:
            pages[tgt]['inbound'] += 1

# Un-mined source material: how many entries name this page, by its whole slug, its
# whole title or a declared alias, matched as a whole word.
raw_texts = []
for fp in glob.glob(os.path.join(ENTRIES, '*.md')):
    raw_texts.append(word_stream(open(fp, encoding='utf-8', errors='ignore').read()))
for base, p in pages.items():
    names = [(n, n.split()) for n in sorted(p['aliases'])]
    p['raw_refs'] = sum(1 for words, stream in raw_texts if mentions(words, stream, names))


def days_old(d):
    try:
        return (TODAY - datetime.date.fromisoformat(d)).days
    except Exception:
        return None


# ── 1. deepening candidates ───────────────────────────────────────────────────
cands = []
for base, p in pages.items():
    if base in META:
        continue
    importance = p['inbound'] + p['sources'] + p['raw_refs']
    if p['words'] < THIN_WORDS and importance >= 4:
        gap = round(importance * 100 / max(p['words'], 40), 1)
        cands.append((gap, importance, p, base))
cands.sort(key=lambda x: -x[0])

print("critic.py - %d pages | %s\n" % (len(pages), TODAY))
print("=== 1. DEEPENING CANDIDATES (important or well-sourced, but thin) ===")
print("  in: inbound wikilinks · src: cited sources · raw: source entries naming the page")
if not cands:
    print("  none - no thin page is carrying heavy importance. The brain is proportionate.")
for gap, imp, p, base in cands[:18]:
    print("  gap %5s  %4dw  in:%2d src:%d raw:%2d  %s"
          % (gap, p['words'], p['inbound'], p['sources'], p['raw_refs'], p['rel']))
print()

# ── 2. open questions ─────────────────────────────────────────────────────────
print("=== 2. OPEN QUESTIONS (the brain's own recorded unknowns) ===")
qn = 0
for base, p in sorted(pages.items()):
    lines = p['text'].splitlines()
    for i, ln in enumerate(lines):
        if '[!question]' in ln:
            tail = re.sub(r'.*\[!question\]\s*', '', ln).strip()
            chunk = [tail] if tail else []
            for nxt in lines[i + 1:]:
                if nxt.lstrip().startswith('>'):
                    chunk.append(nxt.lstrip('> ').strip())
                else:
                    break
            q = ' '.join(c for c in chunk if c)[:200]
            if q:
                qn += 1
                print("  [%s] %s" % (p['rel'].replace('wiki/', ''), q))
if not qn:
    print("  none recorded.")
print()

# ── 3. stale but central ──────────────────────────────────────────────────────
print("=== 3. STALE BUT CENTRAL (central pages not updated in %d+ days) ===" % STALE_DAYS)
stale = []
for base, p in pages.items():
    if base in META:
        continue
    age = days_old(p['updated'])
    if p['inbound'] >= 4 and age is not None and age >= STALE_DAYS:
        stale.append((age, p))
stale.sort(key=lambda x: -x[0])
if not stale:
    print("  none - every central page has been touched within %d days." % STALE_DAYS)
for age, p in stale[:12]:
    print("  %4dd  in:%2d  %s  %s" % (age, p['inbound'], p['updated'], p['rel']))
print()

# ── 4. under-connected ────────────────────────────────────────────────────────
print("=== 4. UNDER-CONNECTED (at most one inbound link - real, barely in the graph) ===")
under = [(p['inbound'], p['rel']) for b, p in pages.items()
         if b not in META and p['inbound'] <= 1]
under.sort()
if not under:
    print("  none.")
for n, rel in under[:20]:
    print("  in:%d  %s" % (n, rel))
print()

print("advisory only - nothing was changed. Feed the top of list 1 into a deepening pass.")
