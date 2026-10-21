#!/usr/bin/env python3
"""
brain_quiz.py - a scored quiz of the wiki: does it answer real questions correctly?

WHY. lint.py and connect.py check the wiki's shape and critic.py checks its growth.
Nothing asked the question the wiki exists to answer: "ask it something and get the
right answer, from the current page". This runs a fixed set of questions, each with a
gold answer, 2-4 key facts and the pages the gold came from, through a model that
works the way a QUERY session does (find.py first, open only what it points to, cite
pages). Then one tool-less model call grades every answer against gold and facts.

Score = (right + 0.5 * partly) / questions, as a percent. A wrong answer has two
possible causes, so two staleness signals are kept:
  * stale_suspect      - the judge says the answer contradicts gold AND the answer
                         cites a page whose frontmatter `updated:` is newer than the
                         question's `verified` date. The page moved on; the brain may
                         be right and the gold old. A deterministic guard clamps the
                         judge: no newer cited page, no stale_suspect.
  * gold_needs_recheck - any page the gold cites has `updated:` later than `verified`.

MODEL CALLS ARE PLUGGABLE. Nothing here talks to a vendor. Each call runs a shell
command, the prompt arrives on stdin, and the model's reply is read from stdout (the
first JSON object in it). Choose the commands with --answer-cmd / --judge-cmd or the
env vars BRAIN_QUIZ_ANSWER_CMD / BRAIN_QUIZ_JUDGE_CMD. Defaults use Claude headless:
    answer: claude -p --model sonnet --allowedTools "Read,Grep,Glob,Bash(python3 tools/find.py:*),Bash(python3 tools/deepfind.py:*)"
    judge:  claude -p --model sonnet
The answer command runs with the repo root as its working directory. The answer
reply must be {"answer": "...", "cites": ["wiki/x.md"]}; plain text is accepted as an
answer with no cites. The judge reply must be
{"results": [{"id", "verdict": "right|partly|wrong", "stale_suspect": bool, "note"}]}.

Questions live in quiz/questions.jsonl (see quiz/questions.example.jsonl for the
schema; the kit ships none of its own). Output: quiz/runs/YYYY-MM-DD.json and one
appended line in quiz/trend.md. With --file-row, a score under 75% or a drop of 10
points against the previous run files ONE open row in wiki/_reminders.md (bumped in
place if one is already open, never duplicated). A partial run (--limit / --only)
never alarms: it is written as quiz/runs/YYYY-MM-DD.partial.json, stays out of
trend.md and is never the baseline for the next run. A judge failure (non-zero exit,
timeout, missing CLI, no verdicts) aborts the run: no score, no file, no trend line,
no ledger row, exit 1.

Usage:
    python3 tools/brain_quiz.py --dry-run          # print the plan; no calls, no writes
    python3 tools/brain_quiz.py                    # run it
    python3 tools/brain_quiz.py --limit 3 --only some-id --workers 2 --file-row

No network of its own; a model call happens only through the command you configure.
"""

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QDIR = 'quiz'
LEDGER_REL = os.path.join('wiki', '_reminders.md')
DEFAULT_ANSWER_CMD = 'claude -p --model sonnet --allowedTools "Read,Grep,Glob,Bash(python3 tools/find.py:*),Bash(python3 tools/deepfind.py:*)"'
DEFAULT_JUDGE_CMD = 'claude -p --model sonnet'
THRESHOLD = 75.0
DROP = 10.0
ROW_MARK = 'Brain quiz'
TIMEOUT = 420
FIELDS = ('id', 'q', 'gold', 'facts', 'cites', 'verified')

ANSWER_PROMPT = (
    'Answer this question using ONLY this repository (your working directory), following '
    'its QUERY rule: first run `python3 tools/find.py <keywords and obvious synonyms>`, open '
    'only the pages it points to (on a big page grep -n for the term and read the range), '
    'never answer from memory, and if the wiki does not say, say so. Skip pages marked '
    'private. Give the facts plainly in 1-4 sentences. Reply with only JSON: '
    '{{"answer": "...", "cites": ["repo-relative paths of the pages you used"]}}\n\n'
    'Question: {q}')

JUDGE_PROMPT = (
    'You grade answers from a personal knowledge base against gold answers. For EACH item '
    'give a verdict: right (every key fact present and nothing contradicting gold), partly '
    '(some key facts present or right but incomplete), wrong (missing the core or '
    'contradicting gold). Judge substance, not wording; extra true detail is fine. '
    'stale_suspect = true ONLY when the answer contradicts gold AND it cites a page whose '
    '`updated` date (given) is later than the item\'s `verified` date, i.e. the page may have '
    'moved on and the gold may be the old one. Else false. note: one short sentence. Reply '
    'with only JSON: {{"results": [{{"id": "...", "verdict": "right|partly|wrong", '
    '"stale_suspect": false, "note": "..."}}]}} covering all items.\n\nITEMS:\n{items}')


# ---------------------------------------------------------------- questions

def load_questions(path):
    """Questions from a JSONL file. Blank lines and lines starting with # are skipped."""
    out = []
    with open(path, encoding='utf-8') as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            q = json.loads(line)
            missing = [k for k in FIELDS if k not in q]
            if missing:
                raise ValueError('%s line %d: missing %s' % (path, n, ', '.join(missing)))
            out.append(q)
    return out


def updated_of(root, rel):
    """The frontmatter `updated:` date (YYYY-MM-DD) of a page, or None."""
    try:
        with open(os.path.join(root, rel), encoding='utf-8') as f:
            text = f.read()
    except (OSError, ValueError):
        return None
    m = re.match(r'---\n(.*?)\n---', text, re.S)
    if not m:
        return None
    u = re.search(r'^updated:\s*[\'"]?(\d{4}-\d{2}-\d{2})', m.group(1), re.M)
    return u.group(1) if u else None


def gold_recheck(root, q):
    """Cited pages whose `updated:` is later than the question's `verified` date."""
    return [c for c in q.get('cites', []) if (updated_of(root, c) or '') > q['verified']]


def norm_cite(c):
    return str(c).strip().lstrip('./')


# ---------------------------------------------------------------- model calls

def first_json(text):
    """The first JSON object found in text, or None."""
    dec = json.JSONDecoder()
    for m in re.finditer(r'\{', text or ''):
        try:
            obj, _ = dec.raw_decode(text[m.start():])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    return None


def command_caller(cmd, cwd):
    """caller(prompt) -> stdout text. Runs `cmd` with the prompt on stdin."""
    argv = shlex.split(cmd)

    def call(prompt):
        p = subprocess.run(argv, input=prompt, capture_output=True, text=True,
                           timeout=TIMEOUT, cwd=cwd)
        if p.returncode != 0:
            raise RuntimeError('command exited %d: %s' % (p.returncode, (p.stderr or '')[-200:]))
        return p.stdout
    return call


def ask(q, answer_call):
    try:
        out = answer_call(ANSWER_PROMPT.format(q=q['q']))
        doc = first_json(out)
        if doc and 'answer' in doc:
            answer = str(doc.get('answer') or '')
            cites = [norm_cite(c) for c in (doc.get('cites') or [])]
        else:
            answer, cites = (out or '').strip(), []
        return {'id': q['id'], 'answer': answer, 'cites': cites, 'error': None}
    except Exception as e:  # a failed call is a scored zero, never a crashed run
        return {'id': q['id'], 'answer': '', 'cites': [], 'error': str(e)[:300]}


def judge(questions, answers, root, judge_call):
    items = []
    for q in questions:
        a = answers[q['id']]
        items.append({'id': q['id'], 'question': q['q'], 'gold': q['gold'],
                      'key_facts': q['facts'], 'verified': q['verified'],
                      'answer': a['answer'] or '(no answer)',
                      'answer_cites_updated': {c: updated_of(root, c) for c in a['cites']}})
    doc = first_json(judge_call(JUDGE_PROMPT.format(
        items=json.dumps(items, ensure_ascii=False, indent=1)))) or {}
    return {r['id']: r for r in doc.get('results', []) if isinstance(r, dict) and 'id' in r}


# ---------------------------------------------------------------- scoring

def score_of(results):
    n = len(results)
    pts = sum({'right': 1.0, 'partly': 0.5}.get(r['verdict'], 0.0) for r in results)
    return round(100.0 * pts / n, 1) if n else 0.0


def trend_line(run):
    return '| {} | {}% | {} | {} | {} |'.format(
        run['date'], run['score'], run['stale_suspects'], run['gold_rechecks'], run['mean_pages'])


def append_trend(root, run):
    p = os.path.join(root, QDIR, 'trend.md')
    new = not os.path.exists(p)
    with open(p, 'a', encoding='utf-8') as f:
        if new:
            f.write('# Brain quiz trend\n\n| date | score | stale suspects | gold rechecks | mean pages/answer |\n'
                    '|---|---|---|---|---|\n')
        f.write(trend_line(run) + '\n')


def previous_score(root, today_name):
    d = os.path.join(root, QDIR, 'runs')
    # Full runs only: a partial run (--limit/--only) is written as YYYY-MM-DD.partial.json
    # and never becomes the baseline a full run is compared against.
    names = sorted(n for n in (os.listdir(d) if os.path.isdir(d) else [])
                   if n.endswith('.json') and not n.endswith('.partial.json') and n != today_name)
    for n in reversed(names):
        try:
            with open(os.path.join(d, n), encoding='utf-8') as f:
                doc = json.load(f)
            if doc.get('partial'):
                continue
            return doc['score']
        except (OSError, ValueError, KeyError, AttributeError):
            continue
    return None


def breach(score, prev):
    if score < THRESHOLD:
        return 'score {}% is under {}%'.format(score, int(THRESHOLD))
    if prev is not None and prev - score >= DROP:
        return 'score fell {} points ({}% to {}%)'.format(round(prev - score, 1), prev, score)
    return ''


def file_row(root, run_rel, score, why, today):
    """ONE open quiz row on the ledger: insert it, or bump the open one in place.
    Returns 'filed' | 'bumped' | 'no-open-table'."""
    path = os.path.join(root, LEDGER_REL)
    with open(path, encoding='utf-8') as f:
        text = f.read()
    row = ('| {} | Date | **{} fell to {}%.** {}. Open {} for the questions that failed, then '
           're-verify the gold or fix the page the brain got wrong. | The weekly quiz is how '
           'the wiki is checked against real questions. Run: {}. |').format(
               today, ROW_MARK, score, why, run_rel, run_rel)
    head = re.search(r'(?m)^##\s+Open[ \t]*$', text)
    if not head:
        return 'no-open-table'
    lines = text.split('\n')
    start = text[:head.end()].count('\n')
    sep = None
    for i in range(start + 1, len(lines)):
        if i > start and re.match(r'^## ', lines[i]):
            break
        s = lines[i].strip()
        if re.match(r'^\|[\s:|-]+\|$', s) and sep is None:
            sep = i
            continue
        # Only the row this tool wrote: its title opens `**Brain quiz fell to`. A hand-written
        # row that merely mentions the quiz is somebody's task and is never overwritten.
        if s.startswith('|') and '**{} fell to '.format(ROW_MARK) in s and not re.match(r'^\|\s*(DONE|DROPPED|SUPERSEDED)\b', s, re.I) \
                and '~~' not in s:
            lines[i] = row
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            return 'bumped'
    if sep is None:
        return 'no-open-table'
    lines.insert(sep + 1, row)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return 'filed'


# ---------------------------------------------------------------- run

def run_quiz(root=ROOT, questions_path=None, answer_call=None, judge_call=None, today=None,
             limit=None, only=None, workers=4, file_ledger_row=False):
    qs = load_questions(questions_path or os.path.join(root, QDIR, 'questions.jsonl'))
    total = len(qs)
    if only:
        qs = [q for q in qs if q['id'] == only]
    if limit:
        qs = qs[:limit]
    partial = len(qs) != total
    today = today or dt.date.today().isoformat()
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        answers = dict((a['id'], a) for a in ex.map(lambda q: ask(q, answer_call), qs))
    judge_error = ''
    try:
        verdicts = judge(qs, answers, root, judge_call)
    except Exception as e:
        verdicts = {}
        judge_error = '{}: {}'.format(type(e).__name__, e)
    if not verdicts and any(not answers[q['id']]['error'] for q in qs) and not judge_error:
        judge_error = 'the judge returned no verdicts'
    results = []
    for q in qs:
        a, v = answers[q['id']], verdicts.get(q['id'], {})
        newer = [c for c in a['cites'] if (updated_of(root, c) or '') > q['verified']]
        verdict = v.get('verdict', 'wrong') if not a['error'] else 'wrong'
        if verdict not in ('right', 'partly', 'wrong'):
            verdict = 'wrong'
        stale = bool(v.get('stale_suspect')) and verdict != 'right' and bool(newer)
        results.append({'id': q['id'], 'q': q['q'], 'gold': q['gold'], 'verdict': verdict,
                        'stale_suspect': stale, 'gold_needs_recheck': gold_recheck(root, q),
                        'note': v.get('note', '') if not a['error'] else 'call failed: ' + a['error'],
                        'answer': a['answer'], 'cites': a['cites'], 'pages': len(a['cites'])})
    n = len(results) or 1
    run = {'date': today, 'n': len(results), 'score': score_of(results),
           'stale_suspects': sum(r['stale_suspect'] for r in results),
           'gold_rechecks': sum(bool(r['gold_needs_recheck']) for r in results),
           'mean_pages': round(sum(r['pages'] for r in results) / n, 1), 'results': results}
    if judge_error:
        # No answer was graded, so there is no score: writing 0% would file a false alarm and
        # make the next good run look like a jump. The run is aborted and nothing is written.
        print('judge failed, run aborted, nothing written: {}'.format(judge_error), file=sys.stderr)
        run.update({'score': None, 'aborted': judge_error, 'threshold': '', 'previous_score': None})
        return run
    run['partial'] = partial
    run_rel = '{}/runs/{}{}.json'.format(QDIR, today, '.partial' if partial else '')
    prev = previous_score(root, today + '.json')
    run['previous_score'] = prev
    why = breach(run['score'], prev) if results and not partial else ''
    run['threshold'] = why
    os.makedirs(os.path.join(root, QDIR, 'runs'), exist_ok=True)
    with open(os.path.join(root, run_rel), 'w', encoding='utf-8') as f:
        f.write(json.dumps(run, indent=1, ensure_ascii=False) + '\n')
    if not partial:
        append_trend(root, run)       # the trend is full runs only
    if why and file_ledger_row:
        run['ledger'] = file_row(root, run_rel, run['score'], why, today)
    return run


def main(argv=None):
    ap = argparse.ArgumentParser(description='Scored quiz of the wiki.')
    ap.add_argument('--root', default=ROOT)
    ap.add_argument('--questions', help='default: <root>/quiz/questions.jsonl')
    ap.add_argument('--answer-cmd', default=os.environ.get('BRAIN_QUIZ_ANSWER_CMD', DEFAULT_ANSWER_CMD))
    ap.add_argument('--judge-cmd', default=os.environ.get('BRAIN_QUIZ_JUDGE_CMD', DEFAULT_JUDGE_CMD))
    ap.add_argument('--dry-run', action='store_true', help='print the plan; no model calls, no writes')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--only')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--file-row', action='store_true', help='file/bump one ledger row on a threshold breach')
    a = ap.parse_args(argv)
    qpath = a.questions or os.path.join(a.root, QDIR, 'questions.jsonl')
    if not os.path.isfile(qpath):
        print('no questions file at {}. Copy quiz/questions.example.jsonl to quiz/questions.jsonl '
              'and add your own.'.format(qpath))
        return 1
    qs = load_questions(qpath)
    if a.only:
        qs = [q for q in qs if q['id'] == a.only]
    if a.limit:
        qs = qs[:a.limit]
    if a.dry_run:
        print('DRY: {} questions, answer cmd: {}, judge cmd: {}, cwd {}'.format(
            len(qs), a.answer_cmd, a.judge_cmd, a.root))
        for q in qs:
            print('  {:16} recheck={} {}'.format(q['id'], gold_recheck(a.root, q) or '-', q['q']))
        print('would write {}/runs/{}.json and append {}/trend.md'.format(QDIR, dt.date.today(), QDIR))
        return 0
    if not qs:
        print('0 questions in {}; nothing to run.'.format(qpath))
        return 1
    with tempfile.TemporaryDirectory() as scratch:
        run = run_quiz(a.root, qpath, command_caller(a.answer_cmd, a.root),
                       command_caller(a.judge_cmd, scratch), limit=a.limit, only=a.only,
                       workers=a.workers, file_ledger_row=a.file_row)
    if run.get('aborted'):
        print('ABORTED: {} - no score, no trend line, no ledger row'.format(run['aborted']))
        return 1
    print(trend_line(run) + (' (partial run: not in trend.md, never a baseline)' if run.get('partial') else ''))
    if run.get('threshold'):
        print('THRESHOLD: {} -> ledger {}'.format(run['threshold'], run.get('ledger', 'not filed (use --file-row)')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
