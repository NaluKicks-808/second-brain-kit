#!/usr/bin/env python3
# Vault linter - the honesty gate. Run it before every commit, from anywhere:
#     python3 tools/lint.py
#
# It answers one question: is the brain still internally honest? It never edits
# anything and it never guesses. Every finding names a file and a line.
#
# CHECKS
#   1. BROKEN wikilinks - [[target]] in wiki/ that resolves to no wiki page and to
#      no entry under raw/entries/.
#   2. POLLUTE - a wikilink whose target names a file in data/. Originals are cited
#      as plain text, never linked, so they stay out of the graph view.
#   3. ORPHAN - a wiki page with no inbound link from any other wiki page. Reported
#      twice: counting the index's links (blocks) and excluding them (warns).
#   4. FM - a page missing type/updated/sources in its frontmatter. Warns.
#   5. CITE - a citation anchor that lands nowhere: [[entry#^id]] whose ^id is not
#      in the entry, or [[entry#Heading]] whose heading is not there. A citation
#      that looks precise and is not is worse than no citation.
#   6. GRAPH - the Obsidian graph filter that keeps raw/ and data/ out of the graph
#      view. Linking into raw/entries/ is only safe while that filter is there, so
#      its absence is an error rather than a shrug.
#   7. LOGFMT - a log entry written as a bold-date paragraph instead of a
#      "## [YYYY-MM-DD]" heading. Such an entry is swallowed by the heading above it
#      and every structural read of the log reports the whole span as missing.
#   8. DATE - a stamp in the future anywhere; a raw entry whose filename date and
#      frontmatter date disagree. Plus warnings: an `updated:` far behind the file's
#      own modification time, and a log written today whose newest entry is older
#      than yesterday (the shape of a session reading the last commit, not a clock).
#   9. CONFLICT - an unfinished merge left on disk: a line that starts with seven
#      less-than signs AND a line that starts with seven greater-than signs, in one
#      file. Blocking over the files git counts as part of the project; anything
#      else prints as conflict/warn, because no git command could clear a file git
#      does not track.
#  10. DUPLICATE - a file pasted into itself: a page that starts its own opening
#      frontmatter block again further down. Same blocking rule as check 9.
#  11. UNTRACKED - a link whose target is on this disk and not in git's index. It
#      resolves here and nowhere else, so it is a broken link in every other clone.
#  12. STRANDED - a file under raw/entries/ that is on this disk and not in git's
#      index: written work that a clean working tree erases, and that nothing links
#      to, so no other check can see it. Warns, because a sibling session's entry is
#      legitimately in flight for a while.
#  13. LEDGER - a row in the Open table of the reminders ledger that is not four
#      cells, or whose Type is outside {Date, Event, Condition}. Such a row still
#      reads correctly on the page and is invisible to every tool that reads the
#      ledger for you, which is the failure the single-agenda rule exists to prevent.
#
# Exit 1 on: broken links, graph pollution, orphans counting the index, log-format
# drift, date errors, broken citation anchors, a missing graph filter, a conflict
# marker or a self-paste inside git's project set, an untracked link target, or a
# malformed ledger row. Checks 4 and 12 and the date warnings never touch the exit
# code.
#
# No network. No model call. Pure file reading and arithmetic, so it keeps working
# when everything clever is unavailable.

import os
import re
import sys
import glob
import json
import datetime
import subprocess
from pathlib import Path

# The vault root is found from this script's own location, never from the working
# directory, so the gate reads the vault it ships with rather than whichever folder
# a shell happens to be standing in.
ROOT = str(Path(__file__).resolve().parent.parent)
WIKI = os.path.join(ROOT, 'wiki')
ENTRIES = os.path.join(ROOT, 'raw', 'entries')

# Pages that are machinery rather than articles: they are exempt from the orphan
# and frontmatter checks. Add your own here if you grow another ledger.
META = {'_index', 'log', '_reminders', '_postmortems'}

LINK = re.compile(r'\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]')
# A raw entry filename: {date}_{slug}. Two checks read it - the date gate, which
# makes the filename and the frontmatter agree, and check 1's message, which says
# something different when a link that resolves to nothing is shaped like an entry.
ENTRY_NAME = re.compile(r'^(\d{4}-\d{2}-\d{2})_')

TODAY = datetime.date.today()
STAMP_LAG_DAYS = 2


def strip_code(text):
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    return re.sub(r'`[^`]*`', '', text)


# ── the page index ────────────────────────────────────────────────────────────
pages = {}   # basename -> path relative to the vault root
for fp in glob.glob(os.path.join(WIKI, '**', '*.md'), recursive=True):
    pages[os.path.splitext(os.path.basename(fp))[0]] = os.path.relpath(fp, ROOT)

# raw/entries/ is a LEGAL wikilink target and data/ is not. The point of allowing
# the first is a blue link that lands on the exact passage a claim rests on, rather
# than a filename to go hunting for. What makes it safe is the graph filter checked
# further down, so that filter is load-bearing and its absence fails the gate.
data_names, entry_names, entry_paths = set(), set(), {}
for fp in glob.glob(os.path.join(ROOT, 'data', '*')):
    data_names.add(os.path.splitext(os.path.basename(fp))[0])
for fp in glob.glob(os.path.join(ENTRIES, '*')):
    _base = os.path.splitext(os.path.basename(fp))[0]
    entry_names.add(_base)
    entry_paths.setdefault(_base, os.path.relpath(fp, ROOT))

broken, pollution, cite_links = [], [], []
# Check 11 rides this same pass rather than parsing links a second time: every link
# that RESOLVES to a real file records (citing page, target path) here. A self-link
# is left out on purpose.
link_targets = set()
broken_entry_shaped = 0
inbound_all = dict((b, 0) for b in pages)
inbound_noindex = dict((b, 0) for b in pages)
missing_fm = []

for base, rel in sorted(pages.items()):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        text = f.read()
    body = strip_code(text)
    is_index = (base == '_index')
    for m in LINK.finditer(body):
        # A markdown table escapes the alias pipe as [[page\|label]]; strip the
        # trailing backslash so a correctly written table row is not called broken.
        # A gate that cries wolf is a gate that gets bypassed.
        tgt = m.group(1).strip().rstrip('\\')
        if tgt in data_names and tgt not in pages:
            pollution.append("%s: [[%s]] (source-layer link - cite data/ as plain text)"
                             % (rel, tgt))
            continue
        if tgt in entry_names:
            cite_links.append((rel, tgt, m.group(0)))
            link_targets.add((rel, entry_paths[tgt]))
            continue
        if tgt not in pages:
            if tgt.upper() in ('CLAUDE', 'CLAUDE.MD'):
                broken.append("%s: [[%s]] - CLAUDE.md is the root constitution, not a "
                              "wiki page. Write it as plain prose, never a wikilink." % (rel, tgt))
            else:
                broken.append("%s: [[%s]]" % (rel, tgt))
                if ENTRY_NAME.match(tgt):
                    broken_entry_shaped += 1
            continue
        if tgt != base:
            link_targets.add((rel, pages[tgt]))
            inbound_all[tgt] += 1
            if not is_index:
                inbound_noindex[tgt] += 1
    if base not in META:
        fm = re.match(r'^---\n(.*?)\n---', text, flags=re.S)
        fields = set(re.findall(r'^(\w+):', fm.group(1), flags=re.M)) if fm else set()
        need = set(['type', 'updated', 'sources']) - fields
        if need:
            missing_fm.append("%s: missing %s" % (rel, sorted(need)))

orphans_all = [pages[b] for b in sorted(pages) if b not in META and inbound_all[b] == 0]
orphans_noidx = [pages[b] for b in sorted(pages) if b not in META and inbound_noindex[b] == 0]

# ── check 7: log entry format ─────────────────────────────────────────────────
log_drift = []
_log = os.path.join(WIKI, 'log.md')
_log_text = ''
if os.path.exists(_log):
    _log_text = open(_log, encoding='utf-8', errors='replace').read()
    for i, line in enumerate(_log_text.splitlines(), 1):
        if re.match(r'^\*\*20\d\d-\d\d-\d\d', line):
            log_drift.append("wiki/log.md:%d: entry has no '## [date]' heading -> %s"
                             % (i, line[:60]))

# ── check 8: dates ────────────────────────────────────────────────────────────
# A future stamp is arithmetic, so it fails. A stale stamp is a heuristic, so it
# warns: machine-written files legitimately lag.
DATE_RX = re.compile(r'(\d{4})-(\d{2})-(\d{2})')
FM_DATE = re.compile(r'^(updated|date)\s*:\s*(.+)$', re.M)
LOG_HEADING = re.compile(r'^##\s*\[(\d{4}-\d{2}-\d{2})\]')


def _as_date(s):
    m = DATE_RX.search(s or '')
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


date_bad, date_warn = [], []
for d in (WIKI, ENTRIES):
    for fp in sorted(glob.glob(os.path.join(d, '**', '*.md'), recursive=True)):
        rel = os.path.relpath(fp, ROOT)
        try:
            text = open(fp, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        fm = re.match(r'^---\n(.*?)\n---', text, flags=re.S)
        stamps = {}
        if fm:
            for key, raw in FM_DATE.findall(fm.group(1)):
                dt = _as_date(raw)
                if dt:
                    stamps.setdefault(key, dt)
        for key, dt in sorted(stamps.items()):
            if dt > TODAY:
                date_bad.append("%s: %s: %s is in the future (today is %s)"
                                % (rel, key, dt, TODAY))
        # Entries are named {date}_{slug}.md, and the two dates must agree, or a
        # source lands on the wrong day of the spine and every date query misses it.
        if os.path.dirname(fp) == ENTRIES:
            fn = ENTRY_NAME.match(os.path.basename(fp))
            fn_date = _as_date(fn.group(1)) if fn else None
            if fn_date and fn_date > TODAY:
                date_bad.append("%s: filename dated %s, which is in the future" % (rel, fn_date))
            if fn_date and stamps.get('date') and fn_date != stamps['date']:
                date_bad.append("%s: filename says %s, frontmatter date says %s"
                                % (rel, fn_date, stamps['date']))
        if 'updated' in stamps:
            mt = datetime.date.fromtimestamp(os.path.getmtime(fp))
            if (mt - stamps['updated']).days > STAMP_LAG_DAYS:
                date_warn.append("%s: updated: %s but the file changed %s"
                                 % (rel, stamps['updated'], mt))

for i, line in enumerate(_log_text.splitlines(), 1):
    m = LOG_HEADING.match(line)
    if m and _as_date(m.group(1)) and _as_date(m.group(1)) > TODAY:
        date_bad.append("wiki/log.md:%d: entry dated %s, which is in the future"
                        % (i, m.group(1)))

# The future rule above catches a clock read a day AHEAD. The failure that is just
# as common is a day BEHIND - a session anchoring on the newest commit instead of
# on the clock. The log heading is the one stamp with no legitimate backdate, since
# it is appended during the session it records. This WARNS rather than blocks,
# because a fresh clone gives every file today's modification time while the log's
# newest entry is however old the kit is, and a starter kit must not fail its own
# gate the minute somebody clones it.
if _log_text and os.path.exists(_log):
    if datetime.date.fromtimestamp(os.path.getmtime(_log)) == TODAY:
        _heads = []
        for _i, _l in enumerate(_log_text.splitlines(), 1):
            _m = LOG_HEADING.match(_l)
            if _m and _as_date(_m.group(1)):
                _heads.append((_i, _as_date(_m.group(1))))
        if _heads:
            _i, _newest = _heads[-1]
            # A pass that starts late can cross local midnight, so yesterday is fine.
            if (TODAY - _newest).days > 1:
                date_warn.append(
                    "wiki/log.md:%d: log.md was written today (%s) but its newest entry "
                    "is dated %s - if this session wrote it, it is reading the last "
                    "commit rather than the clock" % (_i, TODAY, _newest))

# ── checks 5 and 6: citation anchors, and the graph filter that makes them safe ──
cite_bad, graph_bad = [], []
_anchor_cache = {}
for rel, tgt, raw_link in cite_links:
    inner = raw_link[2:-2].split('|')[0]
    if '#' not in inner:
        continue
    anchor_txt = inner.split('#', 1)[1].strip().rstrip('\\')
    if not anchor_txt:
        continue
    if tgt not in _anchor_cache:
        _hit = glob.glob(os.path.join(ENTRIES, tgt + '.*'))
        _anchor_cache[tgt] = (open(_hit[0], encoding='utf-8', errors='replace').read()
                              if _hit else '')
    body_txt = _anchor_cache[tgt]
    if anchor_txt.startswith('^'):
        ok = re.search(r'(?m)' + re.escape(anchor_txt) + r'\s*$', body_txt)
        kind = 'block id'
    else:
        ok = re.search(r'(?mi)^#{1,6}\s*' + re.escape(anchor_txt) + r'\s*$', body_txt)
        kind = 'heading'
    if not ok:
        cite_bad.append("%s: %s - no %s `%s` in raw/entries/%s.md"
                        % (rel, raw_link, kind, anchor_txt, tgt))

_gj = os.path.join(ROOT, '.obsidian', 'graph.json')
if os.path.exists(_gj):
    try:
        _search = json.load(open(_gj, encoding='utf-8')).get('search', '')
    except Exception:
        _search = ''
    for _need in ('-path:raw', '-path:data'):
        if _need not in _search:
            graph_bad.append(
                ".obsidian/graph.json: the filter is missing `%s` (it currently reads %r). "
                "Wiki pages cite raw/entries directly, and that filter is what keeps the "
                "source layer out of the graph view. Re-add it in Obsidian: Graph view, "
                "then Filters, then the search box." % (_need, _search))

# ── git's view of this tree, used by checks 9 to 12 ───────────────────────────
# Both readings are refused unless git's top level IS this vault. A vault sitting
# inside somebody else's repository would otherwise have every one of its files
# reported as untracked, and the gate would jam for a reason that has nothing to do
# with the vault.
def _git_toplevel_is_root():
    try:
        out = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=ROOT,
                             capture_output=True, text=True, timeout=60)
    except Exception:
        return False
    if out.returncode != 0 or not out.stdout.strip():
        return False
    return os.path.realpath(out.stdout.strip()) == os.path.realpath(ROOT)


def _git_paths(*args):
    """A set of paths git names, relative to the vault root. None means git could
    not answer - no git on PATH, not a repository, or this vault is not the
    repository's top level."""
    if not _git_toplevel_is_root():
        return None
    try:
        out = subprocess.run(['git'] + list(args), cwd=ROOT,
                             capture_output=True, text=True, timeout=60)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return set(p.replace(os.sep, '/') for p in out.stdout.split('\0') if p)


# Tracked, PLUS untracked and not ignored: git's own idea of what belongs to the
# project. The same question the commit script asks before it stages anything.
_git_project = _git_paths('ls-files', '-c', '-o', '--exclude-standard', '-z')
# The index alone: tracked files, including ones staged this second. That is the
# honest reading for a file mid-commit.
_git_indexed = _git_paths('ls-files', '-z')

# ── check 9: conflict markers ─────────────────────────────────────────────────
# Built from pieces rather than written out, so no line of THIS file can start with
# a marker and jam the vault's own gate.
_MARK_OPEN = b'<' * 7 + b' '
_MARK_CLOSE = b'>' * 7 + b' '


def _owns_a_line(blob, mark):
    """True when `mark` starts a line of `blob`, including the first line."""
    return blob.startswith(mark) or (b'\n' + mark) in blob


CONFLICTED, CONFLICT_WARN = [], []
for _p in sorted(Path(ROOT).rglob('*')):
    if not _p.is_file() or '.git/' in str(_p):
        continue
    try:
        with open(str(_p), 'rb') as _fh:
            _head = _fh.read(8192)
            if b'\0' in _head:          # binary, skipped unread, the way grep -I decides it
                continue
            _blob = _head + _fh.read()
    except OSError:
        continue
    if _owns_a_line(_blob, _MARK_OPEN) and _owns_a_line(_blob, _MARK_CLOSE):
        _rel = str(_p.relative_to(ROOT)).replace(os.sep, '/')
        if _git_project is None or _rel in _git_project:
            CONFLICTED.append(_rel)
        else:
            CONFLICT_WARN.append(_rel)

# ── check 10: a file pasted into itself ───────────────────────────────────────
# A hand-written splice that misses its end marker rewrites a file as everything
# above the block, the new block, and then the entire file again. The page still
# renders, and a reader can take a fact from either copy, one of them frozen.
_DUP_FENCE = re.compile(r'^[ \t]*(```|~~~)')
DUP_BAD, DUP_WARN = [], []


def _frontmatter_end(lines):
    """Index of the first line after an opening frontmatter block, or 0 when the
    file does not open with one. The block's first line is lines[1]."""
    if len(lines) < 3 or lines[0].rstrip() != '---':
        return 0
    for k in range(1, min(len(lines), 200)):
        if lines[k].rstrip() == '---':
            return k + 1
    return 0


def _unfenced(lines, start):
    inside = False
    for i in range(start, len(lines)):
        if _DUP_FENCE.match(lines[i]):
            inside = not inside
            continue
        if not inside:
            yield i, lines[i]


for _d in (WIKI, ENTRIES):
    for _fp in sorted(glob.glob(os.path.join(_d, '**', '*.md'), recursive=True)):
        _rel = os.path.relpath(_fp, ROOT).replace(os.sep, '/')
        try:
            _lines = open(_fp, encoding='utf-8', errors='replace').read().split('\n')
        except OSError:
            continue
        _body = _frontmatter_end(_lines)
        _first = _lines[1].rstrip() if _body >= 3 else ''
        if not _first.strip():
            continue
        _again = [_i + 1 for _i, _ln in _unfenced(_lines, _body)
                  if _ln.rstrip() == '---' and _i + 1 < len(_lines)
                  and _lines[_i + 1].rstrip() == _first]
        if _again:
            _msg = ("%s:%d starts the file's own frontmatter again (%s) - the file was "
                    "pasted into itself" % (_rel, _again[0], _first[:60]))
            if len(_again) > 1:
                _msg += ", %d times in all" % len(_again)
            (DUP_BAD if _git_project is None or _rel in _git_project else DUP_WARN).append(_msg)

# ── check 11: a link target git does not know about ───────────────────────────
untracked_links, untracked_link_paths = [], set()
if _git_indexed is not None:
    for _rel, _tgt in sorted(link_targets):
        _tgt = _tgt.replace(os.sep, '/')
        if _tgt not in _git_indexed:
            untracked_link_paths.add(_tgt)
            untracked_links.append(
                "%s -> %s: the target exists here and git does not track it; stage it in "
                "this same commit or the link breaks in every other clone"
                % (_rel.replace(os.sep, '/'), _tgt))

# ── check 12: a raw entry nothing points at and git has never seen ────────────
ENTRIES_PREFIX = os.path.relpath(ENTRIES, ROOT).replace(os.sep, '/') + '/'
stranded_entries, _stranded_left_to_11 = [], 0
_stranded_ok = _git_indexed is not None and _git_project is not None
if _stranded_ok:
    for _rel in sorted(_git_project - _git_indexed):
        if not _rel.startswith(ENTRIES_PREFIX):
            continue
        if _rel in untracked_link_paths:
            _stranded_left_to_11 += 1          # check 11 names it and blocks on it
            continue
        stranded_entries.append(
            "%s: written here and not in git - it exists on this machine only, and a "
            "clean working tree erases it. Commit it, or say in wiki/log.md why it "
            "should not be." % _rel)

# ── check 13: the reminders ledger's Open table ───────────────────────────────
# A row that is not four cells, or whose Type is unknown, still READS correctly on
# the page and is invisible to every tool that surfaces the agenda for you.
LEDGER_CELLS = 4
LEDGER_TYPES = ('date', 'event', 'condition')
OPEN_HEADING = re.compile(r'(?m)^##\s+Open[ \t]*$')
NEXT_SECTION = re.compile(r'(?m)^## ')
CELL_SPLIT = re.compile(r'(?<!\\)\|')


def _split_row(line):
    cells = [c.strip() for c in CELL_SPLIT.split(line)]
    if cells and cells[0] == '':
        cells = cells[1:]
    if cells and cells[-1] == '':
        cells = cells[:-1]
    return cells


def _is_separator(cells):
    return bool(cells) and all(re.match(r'^:?-{2,}:?$', c or '') for c in cells)


def _plain(s):
    s = re.sub(r'\[\[([^|\]]*\|)?([^\]]*)\]\]', r'\2', s or '')
    return re.sub(r'\s+', ' ', s.replace('**', '').replace('~~', '')).strip()


ledger_bad = []
_ledger = os.path.join(WIKI, '_reminders.md')
if os.path.isfile(_ledger):
    try:
        _ltext = open(_ledger, encoding='utf-8', errors='replace').read()
        _lhead = OPEN_HEADING.search(_ltext)
        if _lhead:
            _lbase = _ltext[:_lhead.end()].count('\n')
            _lbody = NEXT_SECTION.split(_ltext[_lhead.end():], 1)[0].split('\n')
            for _i, _line in enumerate(_lbody):
                _t = _line.strip()
                if not _t.startswith('|'):
                    continue
                _cells = _split_row(_t)
                if _is_separator(_cells):
                    continue
                _nxt = _lbody[_i + 1].strip() if _i + 1 < len(_lbody) else ''
                if _nxt.startswith('|') and _is_separator(_split_row(_nxt)):
                    continue                    # the header, sitting above its separator
                _at = 'wiki/_reminders.md:%d' % (_lbase + _i + 1)
                _what = _plain(_t)[:70]
                if len(_cells) != LEDGER_CELLS:
                    ledger_bad.append(
                        "%s has %d cells and the Open table has %d (Trigger | Type | What "
                        "to surface | Why it matters). Either a cell is missing, or an "
                        "unescaped pipe - usually inside a [[page|alias]] link, which must "
                        "be written [[page\\|alias]] in a table - has split one cell into "
                        "two and shifted every cell after it: %s"
                        % (_at, len(_cells), LEDGER_CELLS, _what))
                    continue
                if _plain(_cells[1]).lower() not in LEDGER_TYPES:
                    ledger_bad.append(
                        "%s has type %r, and the Open table knows Date, Event and "
                        "Condition. A row of any other type is skipped by every reader of "
                        "this file: %s" % (_at, _plain(_cells[1])[:40], _what))
    except Exception as _e:
        # A check that silently stops checking is the failure it exists to prevent.
        ledger_bad.append('CHECK COULD NOT RUN: %s: %s' % (type(_e).__name__, _e))

# ── report ────────────────────────────────────────────────────────────────────
# Every blocking finding prints an UPPER-CASE tag and every warning a lower-case
# one. The commit script's record reads that convention, so keep it if you add a
# check of your own.
print("pages: %d" % len(pages))

print("conflict markers: %d%s" % (
    len(CONFLICTED),
    "" if _git_project is not None
    else " (git could not be consulted - every scanned file is treated as blocking)"))
for x in CONFLICTED:
    print("  CONFLICT", x, "- an unfinished merge; this BLOCKS the commit, fix it before anything reads this file")
print("conflict markers outside git (warning, does not block): %d" % len(CONFLICT_WARN))
for x in CONFLICT_WARN:
    print("  conflict/warn", x)

print("duplicated sections: %d%s" % (
    len(DUP_BAD),
    "" if _git_project is not None
    else " (git could not be consulted - every finding is treated as blocking)"))
for x in DUP_BAD:
    print("  DUPLICATE", x)
if DUP_BAD:
    print("  (merge the two copies into one, keeping the newer facts from each and every "
          "line only one copy has, then delete the second)")
print("duplicated sections outside git (warning, does not block): %d" % len(DUP_WARN))
for x in DUP_WARN:
    print("  duplicate/warn", x)

print("broken links: %d%s" % (
    len(broken),
    "" if not broken_entry_shaped else
    " (%d of them name a raw/entries entry that is not in this clone - most likely "
    "written and never committed on the machine that wrote it, so get it committed "
    "rather than deleting the citation)" % broken_entry_shaped))
for x in broken:
    print("  BROKEN", x)

print("graph pollution: %d" % len(pollution))
for x in pollution:
    print("  POLLUTE", x)

print("orphans (counting index links): %d" % len(orphans_all))
for x in orphans_all:
    print("  ORPHAN", x)
print("orphans (excluding index links): %d" % len(orphans_noidx))
for x in orphans_noidx:
    print("  orphan/no-idx", x)

print("log entries missing a heading: %d" % len(log_drift))
for x in log_drift:
    print("  LOGFMT", x)

print("frontmatter warnings: %d" % len(missing_fm))
for x in missing_fm:
    print("  FM", x)

print("citation anchors broken: %d" % len(cite_bad))
for x in cite_bad:
    print("  CITE", x)

print("graph filter: %s" % ('ok' if not graph_bad else 'BROKEN'))
for x in graph_bad:
    print("  GRAPH", x)

print("untracked link targets: %d%s" % (
    len(untracked_links),
    "" if _git_indexed is not None
    else " (git could not be consulted - nothing reported rather than everything)"))
for x in untracked_links[:20]:
    print("  UNTRACKED", x)
if len(untracked_links) > 20:
    print("  UNTRACKED ... and %d more" % (len(untracked_links) - 20))

print("stranded raw entries: %d%s" % (
    len(stranded_entries),
    " (git could not be consulted - nothing reported rather than everything)"
    if not _stranded_ok else
    (" (+%d also cited from wiki/ - printed above as UNTRACKED, where they block)"
     % _stranded_left_to_11 if _stranded_left_to_11 else "")))
for x in stranded_entries[:20]:
    print("  STRANDED", x)
if len(stranded_entries) > 20:
    print("  STRANDED ... and %d more" % (len(stranded_entries) - 20))
if stranded_entries:
    print("  (a warning, not a block - another session's entry is legitimately in flight "
          "for a while)")

print("ledger row shape: %d" % len(ledger_bad))
for x in ledger_bad:
    print("  LEDGER", x)

print("date errors: %d" % len(date_bad))
for x in date_bad:
    print("  DATE", x)
print("date warnings: %d" % len(date_warn))
for x in date_warn[:10]:
    print("  date/warn", x)
if len(date_warn) > 10:
    print("  date/warn ... and %d more" % (len(date_warn) - 10))

sys.exit(1 if (broken or pollution or orphans_all or log_drift or date_bad or cite_bad
               or graph_bad or CONFLICTED or DUP_BAD or untracked_links
               or ledger_bad) else 0)
