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
#      frontmatter block again further down, or a heading repeated under the same parent
#      headings in a file where each heading must be unique (CONFIG['unique_heading_files'],
#      the index and the postmortem record by default). Blocking over the files git counts
#      as part of the project; anything else prints as duplicate/warn, because no commit
#      carries a file git ignores. The second rule catches what is left once somebody tidies
#      a pasted copy's header without noticing the blocks under it.
#  11. UNTRACKED - a link whose target is on this disk and not in git's index. It
#      resolves here and nowhere else, so it is a broken link in every other clone.
#  12. STRANDED - a file under raw/entries/ that is on this disk and not in git's
#      index: written work that a clean working tree erases, and that nothing links
#      to, so no other check can see it. Warns, because a sibling session's entry is
#      legitimately in flight for a while.
#  13. LEDGER - a row in the Open table of the reminders ledger that is not four
#      cells, whose Type is outside {Date, Event, Condition}, or whose Trigger and What
#      cells are both empty (and, if CONFIG['ledger_require_tag'] is on, whose What cell
#      has no `[area · size]` tag). Such a row still reads correctly on the page and is
#      invisible to every tool that reads the ledger for you, which is the failure the
#      single-agenda rule exists to prevent.
#  14. ANSWERED - a tick-marked line in wiki/_question-bank.md with no YYYY-MM-DD on it,
#      in the answer line below it, or in its nearest heading. Warns only. Silent when
#      there is no question bank.
#  15. HALFCLOSED - a DONE/DROPPED ledger row ADDED since origin/main whose Trigger does
#      not open with exactly `DONE YYYY-MM-DD via <who> - ` or whose What title is not
#      struck through; a tool that reads closure from the stamp and the strike sees it
#      as still open. Blocks. Reads only added lines, so the ledger's history never
#      floods it; quiet when there is no origin/main.
#  16. TOOLEARLY - a DONE row added since origin/main stamped `via <name>.py` whose own
#      date is still ahead of the close date. A script closes what it can verify
#      happened, and a date still ahead has not. Blocks. Same quiet rule as check 15.
#  17. FIXTURE - a file in tools/tests/ that builds a path out of its own directory.
#      Two test runs over one tree share it and delete each other's fixture mid-assertion.
#      Blocks. A test file that will not parse only warns (fixture/warn).
#  18. DISCOVERY - a .py file in tools/tests/ whose name `unittest discover` ignores
#      (not test*.py) and that does not say NOT A TEST MODULE in its text. It has left the
#      suite and the suite's total does not say so. Blocks.
#  19. RUNNER - a module-level `unittest.main()` that is not the last statement in its
#      file. It ends in sys.exit(), so a direct run stops there and prints OK having
#      skipped everything below. Blocks.
#  20. GUESS - "almost certainly", "clearly", "which is why", "must have", "presumably"
#      or "no doubt" in wiki prose ADDED since origin/main, outside callouts, blockquotes,
#      code and double quotation marks (guess_words.py, beside this file). An inference
#      belongs in a `> [!question]` or under `status: provisional`. Warns only; quiet
#      when there is no origin/main.
#  21. POSTNUM - two headings in wiki/_postmortems.md carrying the same number. Pages
#      cite `[[_postmortems]] #N`, so a shared number makes every citation ambiguous.
#      Blocks. A skipped number only warns (postnum/warn). Silent with no file.
#  22. POSTFAM - an entry numbered CONFIG['postmortem_family_from'] or higher without its
#      **Family:**, **Neighbours:** and **Outcome check:** lines. Blocks, but OFF unless
#      the config is set, because it enforces one particular postmortem template.
#  23. TOPMAP - a directory at the vault root that README.md does not name in backticks
#      (`.git` and CONFIG['topmap_exempt'] excepted). Blocks, gitignored ones too.
#
# Exit 1 on: broken links, graph pollution, orphans counting the index, log-format
# drift, date errors, broken citation anchors, a missing graph filter, a conflict
# marker or a self-paste inside git's project set, an untracked link target, a
# malformed ledger row, a half-closed or script-closed-early ledger row, a test
# fixture, discovery or runner defect, a duplicated postmortem number, a missing
# postmortem family line (when enabled), or an unlisted top-level folder. Checks 4, 12,
# 14 and 20, the date warnings, the unparseable-test-file warning and a skipped
# postmortem number never touch the exit code.
#
# No network. No model call. Pure file reading and arithmetic, so it keeps working
# when everything clever is unavailable.

import os
import re
import sys
import glob
import json
import fnmatch
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

# The knobs. Everything here is a decision about YOUR setup, so it lives in one place.
CONFIG = {
    # Files in which every heading must be unique under its parent headings (check 10).
    # One block per thing is the contract of an index; a repeat means a paste.
    'unique_heading_files': ('wiki/_index.md', 'wiki/_postmortems.md'),
    # Check 13: demand an `[area · size]` tag on every ledger row's What cell. OFF: only
    # useful if something you run reads those tags (a board, a mirror, a push job).
    'ledger_require_tag': False,
    # Check 22: the first postmortem number that must carry Family / Neighbours / Outcome
    # check lines. None = off. Set a number, or LINT_POSTMORTEM_FAMILY_FROM=<n> in the
    # environment, once you adopt that template. Earlier entries stay grandfathered.
    'postmortem_family_from': int(os.environ.get('LINT_POSTMORTEM_FAMILY_FROM', '') or 0) or None,
    # Check 23: top-level folders README.md need not name. `.git` is always exempt.
    'topmap_exempt': ('.obsidian', '.claude', 'hooks'),
}

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

# Rule two of check 10: in the files that must hold one block per thing, no heading
# repeats under the same chain of parent headings. Keyed on the chain, not the bare line,
# so an index may have "Other" under two different categories.
_DUP_HEADING = re.compile(r'^(#{1,6})[ \t]+\S')
for _rel in CONFIG['unique_heading_files']:
    try:
        _hl = open(os.path.join(ROOT, _rel), encoding='utf-8', errors='replace').read().split('\n')
    except OSError:
        continue
    _seen, _chain = {}, []
    for _i, _ln in _unfenced(_hl, _frontmatter_end(_hl)):
        _hm = _DUP_HEADING.match(_ln)
        if not _hm:
            continue
        _lvl = len(_hm.group(1))
        _chain = [c for c in _chain if c[0] < _lvl] + [(_lvl, _ln.rstrip())]
        _key = tuple(c[1] for c in _chain)
        if _key in _seen:
            _msg = ("%s:%d repeats the heading at line %d: %s"
                    % (_rel, _i + 1, _seen[_key] + 1, _ln.rstrip()[:100]))
            (DUP_BAD if _git_project is None or _rel in _git_project else DUP_WARN).append(_msg)
        else:
            _seen[_key] = _i

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


TAG_RX = re.compile(r'\[[^\]\[]*·[^\]\[]*\]')
ledger_bad = []
_ledger = os.path.join(WIKI, '_reminders.md')
_open_lines = None      # (line offset, lines of the Open table), shared with checks 15 and 16
if os.path.isfile(_ledger):
    try:
        _ltext = open(_ledger, encoding='utf-8', errors='replace').read()
        _lhead = OPEN_HEADING.search(_ltext)
        if _lhead:
            _lbase = _ltext[:_lhead.end()].count('\n')
            _lbody = NEXT_SECTION.split(_ltext[_lhead.end():], 1)[0].split('\n')
            _open_lines = (_lbase, _lbody)
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
                        "to surface | Why it matters). Either a cell is missing, an "
                        "unescaped pipe - usually inside a [[page|alias]] link, which must "
                        "be written [[page\\|alias]] in a table - has split one cell into "
                        "two and shifted every cell after it, or two rows share one line: %s"
                        % (_at, len(_cells), LEDGER_CELLS, _what))
                    continue
                if _plain(_cells[1]).lower() not in LEDGER_TYPES:
                    ledger_bad.append(
                        "%s has type %r, and the Open table knows Date, Event and "
                        "Condition. A row of any other type is skipped by every reader of "
                        "this file: %s" % (_at, _plain(_cells[1])[:40], _what))
                    continue
                if CONFIG['ledger_require_tag'] and not TAG_RX.search(_cells[2]):
                    ledger_bad.append(
                        "%s carries no `[area · size]` tag on its What cell, and "
                        "CONFIG['ledger_require_tag'] is on: %s" % (_at, _what))
                    continue
                if not _plain(_cells[0]) and not _plain(_cells[2]):
                    ledger_bad.append(
                        "%s is four cells with a known type and an empty Trigger and an "
                        "empty What, so there is nothing for a reader to surface: %s"
                        % (_at, _what))
    except Exception as _e:
        # A check that silently stops checking is the failure it exists to prevent.
        ledger_bad.append('CHECK COULD NOT RUN: %s: %s' % (type(_e).__name__, _e))

# ── check 14: an answered question with no date ───────────────────────────────
# A tick-marked line in wiki/_question-bank.md says an open question was answered.
# When it was answered is half the fact: whatever reads the bank to decide what is
# still open cannot age an answer with no date, or order it against the question it
# settles. The date may sit on the line, one indented line below it, or in the nearest
# heading, because all three are ordinary ways to write an answer down. Warns only:
# the file is free prose nobody was ever required to format, and a gate that can jam
# every commit over a tick mark is not worth the date it recovers. Silent with no file.
ANSWERED_MARK = re.compile(r'^\s*(?:[-*+]\s+)?(?:\*\*)?✅')
ISO_ANYWHERE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b')
qbank_warn = []
_qbank = os.path.join(WIKI, '_question-bank.md')
if os.path.isfile(_qbank):
    try:
        _qlines = open(_qbank, encoding='utf-8', errors='replace').read().split('\n')
        _qhead = ''
        for _i, _line in enumerate(_qlines):
            if re.match(r'^#{1,6}[ \t]+\S', _line):
                _qhead = _line
            if not ANSWERED_MARK.match(_line):
                continue
            if ISO_ANYWHERE.search(_line) or ISO_ANYWHERE.search(_qhead):
                continue
            _below = _qlines[_i + 1] if _i + 1 < len(_qlines) else ''
            if _below[:1] in (' ', '\t') and ISO_ANYWHERE.search(_below):
                continue
            qbank_warn.append("wiki/_question-bank.md:%d is marked answered and no YYYY-MM-DD "
                              "date says when, on the line, in the answer below it or in its "
                              "heading: %s" % (_i + 1, _line.strip()[:90]))
    except Exception as _e:
        qbank_warn.append('CHECK COULD NOT RUN: %s: %s' % (type(_e).__name__, _e))

# ── checks 15 and 16: closing stamps, read from the lines ADDED since origin/main ──
# Both read only ledger lines added since origin/main, so a ledger with history never
# floods them and every NEW stamp is still checked. With no origin/main (a fresh clone
# without a remote, a repo never pushed) they say so on their count line and stay quiet.
def _ledger_added_rows():
    """Stripped lines added to wiki/_reminders.md since origin/main, or None when git
    cannot say (no git, no origin/main, not the repository's top level)."""
    if not _git_toplevel_is_root():
        return None
    try:
        out = subprocess.run(['git', '-C', ROOT, 'diff', '--unified=0', 'origin/main', '--',
                              'wiki/_reminders.md'], capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return {l[1:].strip() for l in out.stdout.split('\n')
            if l.startswith('+') and not l.startswith('+++')}


DONE_STAMP = re.compile(r'^\s*(?:DONE|DROPPED) \d{4}-\d{2}-\d{2} via .*?—\s*')
STRUCK_TITLE = re.compile(r'^\s*(?:\*\*)?\s*~~')
half_closed, tool_early = [], []
_added = _ledger_added_rows()
_added_note = '' if _added is not None else ' (no diff against origin/main - not checked)'
if _added and _open_lines is not None:
    _hc_base, _hc_lines = _open_lines
    try:
        for _i, _line in enumerate(_hc_lines):
            _t = _line.strip()
            if _t not in _added or not re.match(r'^\|\s*(?:DONE|DROPPED)\b', _t):
                continue
            _cells = _split_row(_t)
            _why = []
            if not DONE_STAMP.match(_cells[0] if _cells else ''):
                _why.append("the Trigger must open with exactly `DONE YYYY-MM-DD via <who> — ` "
                            "(no clock time, no em dash inside the via text)")
            if len(_cells) < 3 or not STRUCK_TITLE.match(_cells[2]):
                _why.append("the What title must be struck through, `**~~title~~**`")
            if _why:
                half_closed.append(
                    "wiki/_reminders.md:%d: %s; otherwise a tool that reads closure from the "
                    "stamp and the strike sees the row as still open"
                    % (_hc_base + _i + 1, '; '.join(_why)))
            # Check 16 rides the same rows: a script's `via <name>.py` stamp on a row whose
            # own date is still ahead. A script closes what it can verify happened, and a
            # date still ahead has not happened. A person may close early; a script may not.
            _tm = re.match(r'^\|\s*DONE (\d{4}-\d\d-\d\d) via ([^|]*?\.py)\b[^|]*?—\s*\*\*(\d{4}-\d\d-\d\d)', _t)
            if _tm and _tm.group(3) > _tm.group(1):
                tool_early.append(
                    "wiki/_reminders.md:%d: closed %s via %s but due %s. A script closes only "
                    "what it can verify happened; reopen the row, or close it by hand."
                    % (_hc_base + _i + 1, _tm.group(1), _tm.group(2).strip(), _tm.group(3)))
    except Exception as _e:
        half_closed.append('CHECK COULD NOT RUN: %s: %s' % (type(_e).__name__, _e))

# ── checks 17, 18 and 19: test hygiene over tools/tests/ ───────────────────────
# Three ways a test suite goes green while testing air, all readable from the files.
#   17. FIXTURE ISOLATION: no test file may build a path out of its own directory. Two
#       test runs over one tree share that directory, so a fixed fixture name in it is a
#       race between them, and the failure lands on whichever module is slowest, which
#       accuses code that did not change. Use tempfile.TemporaryDirectory() per test.
#       `.parent.parent` (the tools directory) is deliberately not matched: resolving the
#       module under test that way is the universal idiom and a source read.
#   18. MODULE DISCOVERY: every .py file there matches `unittest discover`'s pattern
#       (test*.py) or says NOT A TEST MODULE in its own text. A file renamed out of the
#       pattern simply stops running, and a suite total that keeps rising never says so.
#   19. RUNNER PLACEMENT: a module-level `unittest.main()` ends in sys.exit(), so it must
#       be the last statement in its file. Anywhere else, a direct run of the file stops
#       at it and prints OK having skipped everything below, while `discover` runs it all
#       and the suite total hides the gap. A file with no runner is fine.
# All three BLOCK: they cannot fire on honest work, and a warning line printed above `OK`
# is the same silence in a different colour. A test file that will not PARSE only warns,
# because another session's half-saved edit must not become a commit gate on this one.
# Silent when there is no tools/tests/. Pure syntax reading: nothing is imported or run.
DISCOVER_PATTERN = 'test*.py'          # unittest's default; nothing here passes -p
HELPER_MARKER = 'NOT A TEST MODULE'

fixture_bad, fixture_warn, _fixture_read = [], [], 0
discover_bad, _discover_seen, _discover_ok = [], 0, 0
runner_bad, _runner_parsed, _runner_last = [], 0, 0
_tests_dir = os.path.join(ROOT, 'tools', 'tests')
if os.path.isdir(_tests_dir):
    try:
        import ast as _ast

        def _dotted(node):
            """`os.path.join` for an attribute chain; '' for anything else."""
            bits = []
            while isinstance(node, _ast.Attribute):
                bits.append(node.attr)
                node = node.value
            if not isinstance(node, _ast.Name):
                return ''
            bits.append(node.id)
            return '.'.join(reversed(bits))

        def _names_file(node):
            """__file__, bare or wrapped in abspath/realpath."""
            if isinstance(node, _ast.Name) and node.id == '__file__':
                return True
            if isinstance(node, _ast.Call) and _dotted(node.func).split('.')[-1] in (
                    'abspath', 'realpath'):
                return bool(node.args) and _names_file(node.args[0])
            return False

        def _is_path_call(node):
            return (isinstance(node, _ast.Call)
                    and _dotted(node.func).split('.')[-1] == 'Path'
                    and bool(node.args) and _names_file(node.args[0]))

        def _self_path(node):
            """`Path(__file__)`, with an optional .resolve()/.absolute() peeled off.

            Needed for the sibling spellings: `Path(__file__).with_name('x.json')`
            names a file beside this one without ever mentioning a directory.
            """
            if (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)
                    and node.func.attr in ('resolve', 'absolute')):
                node = node.func.value
            return _is_path_call(node)

        def _own_dir(node):
            """This file's OWN directory — exactly one step up from __file__.

            Two steps is the tools directory and is not this check's business, so
            `Path(__file__).resolve().parent.parent` falls through: its inner value is
            an Attribute rather than the Path(...) call, and _is_path_call says no.
            """
            if isinstance(node, _ast.Call):
                return (_dotted(node.func).split('.')[-1] == 'dirname'
                        and bool(node.args) and _names_file(node.args[0]))
            if isinstance(node, _ast.Attribute) and node.attr == 'parent':
                base = node.value
                if (isinstance(base, _ast.Call) and isinstance(base.func, _ast.Attribute)
                        and base.func.attr in ('resolve', 'absolute')):
                    base = base.func.value
                return _is_path_call(base)
            return False

        def _rhs(node):
            return node.value if isinstance(node, _ast.Constant) and isinstance(
                node.value, str) else '<expression>'

        # ── check 11's two helpers ──
        _DEFERRED = (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef, _ast.Lambda)

        def _runner_spellings(tree):
            """How THIS module spells unittest.main, read off its own imports.

            `unittest` itself is always in the set, even when the import is not at
            module level: `unittest.main()` means the runner wherever the name came
            from. A bare `main()` counts only when `from unittest import main` bound
            it, so an ordinary CLI helper's `main()` is not mistaken for the runner.
            """
            mods, bare = {'unittest'}, set()
            for n in _ast.walk(tree):
                if isinstance(n, _ast.Import):
                    for a in n.names:
                        if a.name == 'unittest':
                            mods.add(a.asname or 'unittest')
                elif isinstance(n, _ast.ImportFrom) and n.module == 'unittest':
                    for a in n.names:
                        if a.name == 'main':
                            bare.add(a.asname or 'main')
            return mods, bare

        def _runs_the_suite(node, mods, bare):
            """A unittest.main() call inside `node`, not behind a def/class/lambda.

            The boundary is what makes "reaches" mean reaches. A call written inside a
            function defined here is deferred until something calls that function, and
            whether anything does is not a question about this file's syntax.
            """
            for child in _ast.iter_child_nodes(node):
                if isinstance(child, _DEFERRED):
                    continue
                if isinstance(child, _ast.Call):
                    _d = _dotted(child.func)
                    if _d in bare or (_d.count('.') == 1 and _d.endswith('.main')
                                      and _d.split('.')[0] in mods):
                        return True
                if _runs_the_suite(child, mods, bare):
                    return True
            return False

        for _tf in sorted(glob.glob(os.path.join(_tests_dir, '*.py'))):
            _rel = os.path.join('tools/tests', os.path.basename(_tf))
            _src = open(_tf, encoding='utf-8').read()

            # ── check 10, on the name, before anything needs the file to parse ──
            _discover_seen += 1
            if fnmatch.fnmatch(os.path.basename(_tf), DISCOVER_PATTERN):
                _discover_ok += 1
            elif HELPER_MARKER not in _src:
                discover_bad.append(
                    "%s: `unittest discover` collects `%s`, and this name does not "
                    "match — so the file contributes no tests and the suite total says "
                    "nothing about its absence. Rename it to test_*.py if "
                    "it is a test, or write `%s` in it to declare it a helper."
                    % (_rel, DISCOVER_PATTERN, HELPER_MARKER))

            try:
                _tree = _ast.parse(_src, filename=_tf)
            except SyntaxError as _se:
                fixture_warn.append('%s: could not be parsed, so it was not checked '
                                    '(line %s: %s)' % (_rel, _se.lineno, _se.msg))
                continue
            _fixture_read += 1
            # A name bound to the own-directory expression stands in for it, because
            # the original three all went through one: `here = Path(__file__)...parent`
            # and then `here / "_tmp_ls_ics.json"` two lines later.
            _own_names = set()
            for _n in _ast.walk(_tree):
                _val = getattr(_n, 'value', None)
                if isinstance(_n, _ast.Assign) and _own_dir(_val):
                    for _t in _n.targets:
                        if _dotted(_t):
                            _own_names.add(_dotted(_t))
                elif isinstance(_n, _ast.AnnAssign) and _val is not None and _own_dir(_val):
                    if _dotted(_n.target):
                        _own_names.add(_dotted(_n.target))

            def _is_own(node, _names=_own_names):
                return _own_dir(node) or (_dotted(node) and _dotted(node) in _names)

            for _n in _ast.walk(_tree):
                _named = None
                if (isinstance(_n, _ast.BinOp) and isinstance(_n.op, _ast.Div)
                        and _is_own(_n.left)):
                    _named = _rhs(_n.right)
                elif (isinstance(_n, _ast.Call) and _dotted(_n.func).split('.')[-1] == 'join'
                      and _n.args and _is_own(_n.args[0])):
                    _named = _rhs(_n.args[1]) if len(_n.args) > 1 else '<expression>'
                elif (isinstance(_n, _ast.Call) and isinstance(_n.func, _ast.Attribute)
                      and _n.func.attr == 'joinpath' and _is_own(_n.func.value)):
                    # `HERE.joinpath("x.json")` — the same thing the / operator does.
                    _named = _rhs(_n.args[0]) if _n.args else '<expression>'
                elif (isinstance(_n, _ast.Call) and isinstance(_n.func, _ast.Attribute)
                      and _n.func.attr in ('with_name', 'with_stem')
                      and _self_path(_n.func.value)):
                    # `Path(__file__).with_name("x.json")` — a sibling of this file,
                    # which is a file in this directory however it is spelled.
                    _named = _rhs(_n.args[0]) if _n.args else '<expression>'
                # `<own dir> / '..'` climbs OUT of the tests directory (to the tools
                # directory, to load the module under test): a source read, the same
                # idiom as `.parent.parent`, and not a fixture.
                if _named == '..':
                    _named = None
                if _named is not None:
                    fixture_bad.append(
                        "%s:%d: builds `%s` inside the tests directory. Two "
                        "`unittest discover` runs share that path and delete each "
                        "other's fixture mid-assertion. Give each test a "
                        "tempfile.TemporaryDirectory(), as the other files here do."
                        % (_rel, _n.lineno, _named))

            # ── check 11, on the same tree: the runner must be the last statement ──
            _runner_parsed += 1
            _mods, _bare = _runner_spellings(_tree)
            _body = _tree.body
            _hits = [_i for _i, _s in enumerate(_body)
                     if not isinstance(_s, _DEFERRED)
                     and _runs_the_suite(_s, _mods, _bare)]
            if _hits == [len(_body) - 1]:      # exactly one runner, and it is last
                _runner_last += 1
            for _i in _hits:
                if _i == len(_body) - 1:
                    continue
                runner_bad.append(
                    "%s:%d: `unittest.main()` runs here and ends in sys.exit(), so a "
                    "direct `python3 %s` run stops at this statement and never reaches "
                    "the %d top-level statement(s) below it (the last is line %d) — it "
                    "prints OK having skipped them. `unittest discover` never sets "
                    "__name__ to \"__main__\", so it runs everything and the suite "
                    "total hides the gap. Move this to the end of the file."
                    % (_rel, _body[_i].lineno, _rel, len(_body) - 1 - _i,
                       _body[-1].lineno))
    except Exception as _e:
        # A check that silently stops checking is the failure it exists to prevent.
        # All three checks ride this one pass, so all three say so when it dies.
        fixture_bad.append('CHECK COULD NOT RUN: %s: %s' % (type(_e).__name__, _e))
        discover_bad.append('CHECK COULD NOT RUN: %s: %s' % (type(_e).__name__, _e))
        runner_bad.append('CHECK COULD NOT RUN: %s: %s' % (type(_e).__name__, _e))


# ── check 20: guess words in new wiki prose ───────────────────────────────────
# "almost certainly", "clearly", "which is why", "must have", "presumably", "no doubt".
# These are how an inferred fact most often slips into a page as a plain sentence and is
# read back later as settled; an inference belongs in a `> [!question]` callout or under
# `status: provisional`. No pattern can tell a guess from knowledge, so only the WORDS are
# flagged, and only on lines ADDED since origin/main, so the existing wiki never floods
# the report. guess_words.py holds the rule and sits beside this file. Warns only, capped
# at eight lines. Silent with no guess_words.py or no origin/main.
guess_warn = []
_guess_read = ' (no guess_words.py beside this file - skipped)'
_guess_tool = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'guess_words.py')
if os.path.isfile(_guess_tool):
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import guess_words as _gw
        guess_warn, _guess_note = _gw.scan(ROOT)
        _guess_read = ' (%s)' % _guess_note
    except Exception as _e:
        _guess_read = ' (the check did not finish - see the finding)'
        guess_warn = ['CHECK COULD NOT RUN: %s: %s' % (type(_e).__name__, _e)]

# ── checks 21 and 22: the numbered postmortem record ──────────────────────────
# wiki/_postmortems.md numbers its entries, and a number is an EXTERNAL identifier: pages
# cite an entry as `[[_postmortems]] #N` with nothing but the number to say which one.
# A heading is `## N.` or `### #N (date): title`; only headings count, anchored at the
# start of a line, outside frontmatter and fenced code, so a callout that mentions "#7"
# in prose is never read as a section.
#   21. NUMBERING. A DUPLICATE number BLOCKS: two sessions that each read "the highest
#       heading plus one" at the same moment both write the same number, and every
#       citation to it is ambiguous; the fix is to renumber whichever was published later
#       and repoint its citations. A SKIPPED number only WARNS: nothing is ambiguous about
#       a gap, and an old file may have one nobody can explain.
#   22. FAMILY LINES. From entry number POSTFAM_FROM on, every entry must carry three bold
#       labels: **Family:** (what went wrong, as the owner saw it), **Neighbours:** (earlier
#       entries of the same family as #N, or "none: searched <terms>") and **Outcome
#       check:** (a check on the visible result that catches this entry and its neighbours
#       without knowing the cause). A label with nothing after it counts as missing. OFF
#       unless CONFIG['postmortem_family_from'] is set, because it enforces one particular
#       postmortem template; earlier entries are grandfathered by design.
# Both silent with no file; an unreadable file degrades the same way instead of raising.
POSTNUM_FILE = 'wiki/_postmortems.md'
_POSTNUM_HEADING = re.compile(r'^#{2,3}[ \t]+#?(\d+)(?:[.:)\s]|$)')
postnum_bad, postnum_warn, postfam_bad = [], [], []
_pn_read = ' (no {} here - skipped)'.format(POSTNUM_FILE)
_pf_read = ' (off - set CONFIG["postmortem_family_from"] to enable)'
_pn_path = os.path.join(ROOT, POSTNUM_FILE)
if os.path.isfile(_pn_path):
    _pn_lines = None
    try:
        _pn_lines = open(_pn_path, encoding='utf-8', errors='replace').read().split('\n')
    except OSError as _e:
        _pn_read = (' ({} could not be read ({}) - nothing reported rather than everything)'
                    .format(POSTNUM_FILE, type(_e).__name__))
        if CONFIG['postmortem_family_from'] is not None:
            _pf_read = ' ({} could not be read)'.format(POSTNUM_FILE)
    if _pn_lines is not None:
        _pn_seen, _pn_count = {}, 0
        _pf_sections = []      
        for _i, _ln in _unfenced(_pn_lines, _frontmatter_end(_pn_lines)):
            _pn_m = _POSTNUM_HEADING.match(_ln)
            if _pn_m:
                _pn_count += 1
                _pn_n = int(_pn_m.group(1))
                _pf_sections.append([_pn_n, _i + 1, [], len(_ln) - len(_ln.lstrip('#'))])
                if _pn_n in _pn_seen:
                    postnum_bad.append(
                        "%s:%d numbers a section #%d and line %d already did. Pages cite an "
                        "entry as `[[_postmortems]] #%d` with nothing but the number to say "
                        "which one they mean, so every such citation is now ambiguous. Renumber "
                        "whichever of the two was published LATER (file order is not publication "
                        "order) to the highest number here plus one, then repoint the citations "
                        "that meant it (`grep -rn '#%d' wiki`)."
                        % (POSTNUM_FILE, _i + 1, _pn_n, _pn_seen[_pn_n], _pn_n, _pn_n))
                else:
                    _pn_seen[_pn_n] = _i + 1
            elif re.match(r'^#{1,6}[ \t]', _ln) and (
                    not _pf_sections
                    or len(_ln) - len(_ln.lstrip('#')) <= _pf_sections[-1][3]):
                # a heading at the same or a shallower level ends the entry; a deeper one
                # is a sub-heading inside it and stays part of its body
                _pf_sections.append([None, _i + 1, [], len(_ln) - len(_ln.lstrip('#'))])
            elif _pf_sections:
                _pf_sections[-1][2].append(_ln)
        _pn_read = ' ({} numbered section{} read{})'.format(
            _pn_count, '' if _pn_count == 1 else 's',
            ', highest #%d' % max(_pn_seen) if _pn_seen else '')
        for _pn_n in ([n for n in range(1, max(_pn_seen) + 1) if n not in _pn_seen]
                      if _pn_seen else []):
            postnum_warn.append(
                "%s has no numbered heading for #%d, so the numbering skips it (%d numbered "
                "section%s read, highest #%d). Nothing is ambiguous when a number is skipped, "
                "so this warns and never blocks. Leave the gap alone unless you know what was "
                "deleted; the next entry takes the highest number plus one, never a gap."
                % (POSTNUM_FILE, _pn_n, _pn_count, '' if _pn_count == 1 else 's', max(_pn_seen)))
        _pf_from = CONFIG['postmortem_family_from']
        if _pf_from is not None:
            _pf_checked = 0
            for _pf_n, _pf_line, _pf_body, _pf_lvl in _pf_sections:
                if _pf_n is None or _pf_n < _pf_from:
                    continue
                _pf_checked += 1
                _pf_text = '\n'.join(_pf_body)
                _pf_missing = []
                for _lab in ('Family', 'Neighbours', 'Outcome check'):
                    _m = re.search(r'\*\*' + re.escape(_lab) + r':\*\*[ \t]*(\S[^\n]*)', _pf_text)
                    if not _m:
                        _pf_missing.append(_lab)
                    elif _lab == 'Neighbours' and not re.search(r'#\d+|none: searched \S', _m.group(1)):
                        _pf_missing.append('Neighbours (needs #N, or "none: searched <terms>")')
                if _pf_missing:
                    postfam_bad.append(
                        "%s:%d postmortem #%d has no %s. Every entry from #%d on names its "
                        "Family (what went wrong, as the owner saw it), its Neighbours (earlier "
                        "entries of the same family as #N, or \"none: searched <terms>\") and "
                        "its Outcome check (the check on the visible result that catches this "
                        "AND its neighbours without knowing the cause; say whether it exists)."
                        % (POSTNUM_FILE, _pf_line, _pf_n,
                           ', '.join('**%s:**' % x for x in _pf_missing), _pf_from))
            _pf_read = ' ({} section{} from #{} on checked)'.format(
                _pf_checked, '' if _pf_checked == 1 else 's', _pf_from)

# ── check 23: the top-level map ───────────────────────────────────────────────
# Every directory at the vault root must be named in backticks in README.md (`wiki/`,
# `raw/entries/` and `.obsidian` all count). A folder nobody explained is where stray
# exports, scratch copies and tool output pile up until the owner opens the folder and
# asks what it is. Every unlisted directory BLOCKS, gitignored ones too: a warning-only
# rule for ignored folders would miss exactly the case it exists for. `.git` is exempt,
# as is anything in CONFIG['topmap_exempt']. With no README.md every directory is
# unlisted, which is the point.
TOPMAP_FILE = 'README.md'
topmap_bad = []
_tm_readme = ''
try:
    _tm_readme = open(os.path.join(ROOT, TOPMAP_FILE), encoding='utf-8', errors='replace').read()
except OSError:
    pass
_tm_dirs = sorted(d for d in os.listdir(ROOT)
                  if d != '.git' and d not in CONFIG['topmap_exempt']
                  and os.path.isdir(os.path.join(ROOT, d)))
for _d in _tm_dirs:
    if re.search(r'`' + re.escape(_d) + r'(?:/[^`]*)?`', _tm_readme):
        continue
    topmap_bad.append("%s/ sits at the vault's top level and %s does not name it (as `%s/`). "
                      "Add one plain line saying what it is, or move it out of the vault "
                      "(archive, never delete)." % (_d, TOPMAP_FILE, _d))

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

print("answered questions with no date (warning, does not block): %d" % len(qbank_warn))
for x in qbank_warn[:10]:
    print("  qbank/warn", x)
if len(qbank_warn) > 10:
    print("  qbank/warn ... and %d more" % (len(qbank_warn) - 10))

print("closing stamps a reader cannot see: %d%s" % (len(half_closed), _added_note))
for x in half_closed:
    print("  HALFCLOSED", x)

print("rows a script closed before their date: %d%s" % (len(tool_early), _added_note))
for x in tool_early:
    print("  TOOLEARLY", x)

print("test fixture isolation: {}{}".format(
    len(fixture_bad),
    " (no tests directory - skipped)" if not os.path.isdir(_tests_dir)
    else " ({} test file(s) read)".format(_fixture_read)))
for x in fixture_bad:
    print("  FIXTURE", x)
for x in fixture_warn:
    print("  fixture/warn", x)

print("test module discovery: {}{}".format(
    len(discover_bad),
    " (no tests directory - skipped)" if not os.path.isdir(_tests_dir)
    else " ({} of {} .py file(s) match {})".format(_discover_ok, _discover_seen, DISCOVER_PATTERN)))
for x in discover_bad:
    print("  DISCOVERY", x)

print("test runner placement: {}{}".format(
    len(runner_bad),
    " (no tests directory - skipped)" if not os.path.isdir(_tests_dir)
    else " ({} of {} parsed file(s) end in their runner)".format(_runner_last, _runner_parsed)))
for x in runner_bad:
    print("  RUNNER", x)

print("guess words in new wiki prose (warning, does not block): {}{}".format(
    len(guess_warn), _guess_read))
for x in guess_warn[:8]:
    print("  guess/warn", x)
if len(guess_warn) > 8:
    print("  guess/warn ... and %d more" % (len(guess_warn) - 8))

print("postmortem numbering: {}{}".format(len(postnum_bad), _pn_read))
for x in postnum_bad[:20]:
    print("  POSTNUM", x)
print("postmortem numbering (warning, does not block): %d" % len(postnum_warn))
for x in postnum_warn[:20]:
    print("  postnum/warn", x)
print("postmortem family lines: {}{}".format(len(postfam_bad), _pf_read))
for x in postfam_bad[:20]:
    print("  POSTFAM", x)

print("top-level folders missing from README.md: {} ({} folders read)".format(
    len(topmap_bad), len(_tm_dirs)))
for x in topmap_bad:
    print("  TOPMAP", x)

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
               or ledger_bad or half_closed or tool_early or fixture_bad or discover_bad
               or runner_bad or postnum_bad or postfam_bad or topmap_bad) else 0)
