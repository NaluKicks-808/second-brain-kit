# The constitution

This vault is a second brain: a curated, interlinked, compounding wiki that an assistant compiles from your own data and then maintains forever. This file is its constitution. Any Claude Code session working in this vault reads this file first and obeys it.

Replace this paragraph with one sentence saying whose brain this is and what it currently covers. Scope is worth naming, because a brain that claims to cover everything and covers one project will be trusted about the wrong things.

## The one idea

**You are a writer, not a filing clerk.** The wiki is a map of a mind, not a folder of facts. The question is never "where do I put this?" It is: **what does this mean, and how does it connect to what is already here?** Connect a new fact to every page it genuinely touches, and to no page it does not. A forced link is worse than a missing one. A recurring pattern deserves an article of its own.

## Structure

Three layers: **sources, then normalized entries, then the wiki.**

```
data/           # SOURCE layer: immutable originals, named src-<what>. Never edited after
                #   ingest. Large archives stay OUTSIDE the vault; only small manifests
                #   live here.
raw/entries/    # ENTRY layer: one normalized .md per source chunk, named {date}_{slug}.md
                #   with YAML frontmatter. This is the full text, kept whole.
wiki/           # KNOWLEDGE layer: the brain itself. Compiled, cited, interlinked articles.
                #   The assistant owns this folder entirely.
  _index.md     #   every article, by category, one line each. Updated every absorb.
  _reminders.md #   the commitment ledger. The ONLY list of what is outstanding.
  _postmortems.md #  every caught failure, its cause, and the fix installed for it.
  log.md        #   append-only: "## [YYYY-MM-DD] absorb | what happened"
  people/ projects/ decisions/ events/ places/ tensions/ throughlines/   # the taxonomy
```

Folder meanings, as a starting point rather than a cage: **projects/** are things made; **decisions/** are important choices with their reasoning; **events/** are bounded episodes; **tensions/** are unresolved value conflicts; **throughlines/** are deep threads that cut across everything else. New folders emerge from content, never from a plan drawn up before there is any.

**Two layers, both permanent, both queryable. This is a core promise, not an implementation detail.** The `wiki/` summaries are what you reach for almost always: fast, compiled, cited. Underneath them the full-context layer (`raw/entries/` transcripts and normalized text, and the `data/` originals) is never discarded and stays searchable, so the complete record is there when the stakes are high: a dispute, documentation, a record somebody may have to stand behind, or simply a summary that is not specific enough. Retrieval honours the split. `tools/find.py` searches the summary layer and is the default. `tools/deepfind.py` is the separate, deliberate door to the full-context layer.

**`raw/entries/` is a legal wikilink target and `data/` is not.** Cite a heavy source as `[[2026-09-12_some-entry#^an-anchor]]` so that summary to full text is one click, and leave `data/` filenames as plain text. What makes that safe is the Obsidian graph filter in `.obsidian/graph.json`, which keeps `raw` and `data` out of the graph view, and the linter fails if that filter ever disappears. The precaution is mechanical rather than prohibitive, because the thing a citation is for is a blue link that lands on the exact passage a claim rests on, rather than a filename to go hunting for.

A note on why that paragraph is written so plainly: in the vault this kit came from, the constitution said the opposite of its own gate for eighteen days. The cost was measured rather than hypothetical. A deepening pass was briefed from the wrong sentence and produced the vault's heaviest page with zero clickable citations, while its two sibling pages carried dozens. **A constitution that contradicts its own gate is worse than one that is silent, because a session obeys the constitution.** If you change a rule here, change the gate in the same session, or say in this file that the gate disagrees and which one wins.

## The operations

### INGEST

Turn a raw source into normalized entries. Auto-detect the format: an export, a message log, an archive, email, notes, a pasted debrief. Write one `raw/entries/{date}_{slug}.md` per meaningful chunk, with frontmatter carrying `date`, `source`, `type` and `tags`. Never invent. If a fact is not in the source, it does not exist.

### ABSORB

The core loop. For each entry: read it and understand what it means; check `_index.md` for the articles it touches; **read the passage you are changing before you change it, and the whole page before a substantial rewrite**, never edit blind; ask what new dimension this adds, and update or create articles; fix the cross-links in both directions; append a line to `log.md`.

#### The closing ritual (mandatory, before every commit)

This is what keeps knowledge from stranding on one side of a link. When a new fact enters, it is not absorbed until it is woven into every page it touches, in both directions. A fact about a trip is also a fact about the people in it, the places it happened, and the ventures it strained. The discipline that guarantees this is not memory. It is two scripts, run from the vault root:

1. `python3 tools/lint.py`, zero broken links, zero graph pollution, zero orphans.
2. `python3 tools/connect.py`, the reciprocity check. It reports every page you newly named with a `[[wikilink]]` whose own page you did not update and which does not link back. **Every `GAP` line must be resolved before you commit.** Open that page, record the same fact from its side, and link back. Or, rarely, decide consciously that the one-way mention is genuine passing context and move on. A `GAP` you skip is exactly the failure this ritual exists to prevent: a page that names somebody and never tells them.

Then update `_index.md`, append to `log.md`, and commit with `./tools/safe_commit.sh "message" <the files you edited>` rather than raw `git commit` and `git push`.

**Name the files. Only the files you touched.** The obvious alternative stages the whole working tree, which means a session commits work it has never opened. In the vault this came from that happened three times in one evening: one session's work landed inside another's commit, so the git log, which later sessions reason from, became fiction; the gates ran over a mixed changeset and blessed pages nobody had read; and a half-written page was published by a session with no idea it was mid-edit. A session always knows what it edited. `--all` remains for a sweep that genuinely owns the whole tree, and it prints what it is about to take, so a sweep is a decision rather than an accident.

The commit script also holds an advisory lock for the commit-and-push window, so two sessions cannot interleave, and it self-heals after ten minutes if a session dies holding it. If you run several sessions at once, another one may have pushed while you worked. The script rebases first, refuses to proceed over conflict markers, runs the same gates through the hook, and retries the push through races. Never pop another session's stash. `wiki/log.md` merges by union and `wiki/_reminders.md` through `tools/ledger_merge.py` (both set in `.gitattributes`); no other file joins those rules, because a union merge keeps both halves of a real conflict. Skipping the gate with `--no-verify` is allowed only with a reason, and the script writes that reason and the findings it accepted into `log.md` with the commit, so an override is a record rather than a secret.

#### The weave-back rule

Knowledge about a vault entity produced anywhere, a working document in another project, web research, a conversation in a different session, must update that entity's wiki page in the same session. A line in `log.md` is a pointer, never the record. If the page still says the old thing, the knowledge is not absorbed.

#### Write it back before you answer, not before the session ends

The write-back rule above is easy to hear as "before this session finishes". A session reading it late at night hears that, because the thread is live and the next message always feels more urgent than a file nobody is waiting on. So the trigger is sharper than it looks: **the write-back precedes your next reply to the user, not the end of the session.** You shipped it; you write it down; then you answer.

This matters most in the case that feels safest. A turn that ends on a question to the user is the most dangerous kind, because waiting on an answer feels like a legitimate stopping point and it converts an unpaid debt into silence. In the vault this came from, two hours of that silence was long enough for another session to read a ledger row saying work was still pending when it had been live the whole time.

#### The system-change rule

If a session adds, changes or retires any automation or standing system, a scheduled task, a hook, a pipeline, a notification channel, it records that in the same session, before the commit. Documentation about systems rots unless the change and the document travel together. A periodic audit comparing what is documented against what actually runs is a backstop, not a mechanism. The same holds for a change that never touches git at all, such as a database migration, an environment variable on a host, a scheduled job loaded or unloaded: it has no commit to remind anyone, so it is written on its page before the next reply that reports it.

### QUERY

Answer from the wiki, not from memory, and retrieve **search first**. This is the token-efficient path: search cost stays flat as the vault grows, and reading the whole index every time does not.

1. **Search, do not read the index.** Run `python3 tools/find.py <keywords and obvious synonyms>`. It ranks the pages that actually mention the terms and prints each one's summary plus the matching lines. That is usually enough to answer outright, or to name the one page worth opening.
2. **Open only what it points to.** Read the top page in full when it is focused. For a large log or journal page where the term is a small fraction of the file, grep to the matching lines instead of reading the whole page.
3. **Fall back to the index only** when the question has no good keyword, or when the search returns nothing.
4. **Synthesize with citations** back to the pages you used. A genuinely useful answer can be filed as a new article.
5. **Never answer "what is outstanding" from a copy of the ledger read earlier in the session.** Run `python3 tools/agenda.py`. A long session outlives its own reads, and it cannot tell from the inside that its copy has gone stale. This is the same bug as reading a clock once and using the number twelve hours later.
6. **Check the brain, not just the pages.** `python3 tools/brain_quiz.py` asks a fixed set of questions you wrote, with their right answers, and scores what the brain answers. A drop in the score is the first sign a rewrite lost something.

### CLEANUP

The health check that keeps the brain honest. Flag contradictions between articles, stale claims that a newer source overturned, orphan articles nothing links to, important entities that have no article yet, and, most important, **hallucinated or forced links**, which is the assistant's own habit of inventing connections. Report. Do not silently fix by guessing.

### CRITIC

The growth loop, and the other half of self-improvement. The linter and the reciprocity check keep the brain consistent; they are gates that block bad state. `python3 tools/critic.py` keeps it growing. It reads the vault and surfaces its own highest-leverage gaps: pages the vault treats as important or well-sourced but that are still thin, every recorded open question gathered into one queue, central pages going stale, and pages barely woven into the graph. It is advisory and never edits. The loop closes when a session runs it and then acts on the top of the deepening list, mining the source layer under the normal absorb discipline.

### THE ACTIVE LAYER (optional)

Some owners add automation on top of the brain: a morning brief, a nightly pass, phone notifications, a dashboard. If you do, give its working files their own folder and keep one rule: **that folder holds machinery and indexes, never knowledge.** Facts about the owner's life go into `wiki/` pages. A status file the automation keeps is an index that points at pages, one line per item, and a paragraph of fact found there is a bug, because it is the second copy that drifts. Every automated pass is bound by this constitution first and its own prompt second, runs the closing ritual before it commits, and is listed somewhere a session can find it.

## Evidence, delegation and dates (every session)

**Measure a corpus before you delegate it.** A subagent cannot tell you its slice was too big if nobody measured the slice. Hand a worker more text than fits in its context and it will run out of room partway and write a confident summary of whatever it happened to read, with no way for you to see that from the outside. Every coverage rule tends to govern READING, and none of them govern DELEGATING, because delegation feels like scheduling rather than reading. So: compute the token weight of any corpus before handing it off; partition it to fit; require each worker to report **coverage as a fraction** ("read 1,847 of 1,847") rather than the word "absorbed"; and require a shortfall to be declared before writing rather than footnoted after. Give parallel workers **disjoint write surfaces**, one new file each, with no shared files and no git, because several agents queued behind one blocking commit gate will deadlock. The parent integrates them serially.

**Local models where they are good enough, cloud where they are better.** This is a cost preference, not a privacy rule, unless the owner says otherwise in the second paragraph of this file. Free local transcription and vision first; a cloud model when quality decides.

**Re-read the clock before writing any date.** A clock reading goes stale; a fact does not. Long sessions cross midnight, and a session that read the date at the start and uses it at the end will stamp files with yesterday. Two rules follow. The clock is the one input that must be re-read at the moment of use and never carried forward. And a relative word, today, tomorrow, this week, must be resolved against a fresh reading and then written as an absolute date, never left relative in a file. Note also that a correction can cause the next error: a session burned for using tomorrow's date will be primed to treat that date as wrong long after it has become today's.

**One agenda.** `wiki/_reminders.md` is the only list of what is still outstanding. Never create a second one in a project folder. A row that is only true until a moment ("waiting on the 3pm call") carries `expires: YYYY-MM-DDTHH:MM` in its last cell, and `tools/expire_rows.py` closes it once that moment passes, so the agenda never states a stale moment as current. A task file beside some code is invisible to the brain, so the two drift and neither gets trusted. Split it instead: what is outstanding and when it fires goes in a ledger row, and how to do it, the commands, the checks, goes in that project's runbook. Writing the ledger AND a second copy is not compliance; duplicating into a new home is the failure, not the remedy for it.

## Writing the wiki

The writing standard, the evidence and anti-pattern rules, the article shapes, the frontmatter fields and the no-hard-wrap formatting rule live in `.claude/rules/wiki-writing.md`. Claude Code loads that file automatically whenever a session reads or edits anything under `wiki/` or `raw/`, so it costs nothing in a session that never touches a page. A session that writes vault pages any other way (a script, a worker brief) reads it first. One rule from it holds everywhere in the vault: never hard-wrap prose; one paragraph is one line.

## Golden rules

1. **The owner curates what enters `data/`; the assistant does all the upkeep.** That division is the whole point.
2. **Never invent. Blank beats wrong.** Uncited synthesis that sounds right is the failure mode, and it is very hard to detect later.
3. **Frontmatter on every article:** `type`, `updated` as YYYY-MM-DD, and `sources` as a list, plus the structured fields by type listed in `.claude/rules/wiki-writing.md`. Use `[[wikilinks]]` throughout.
4. **The `data/` originals are immutable.** Corrections happen in `wiki/`, with a note, never by rewriting history.
5. **A rule that fails twice becomes a gate.** Write the failure into `wiki/_postmortems.md`, and install something mechanical in the same session. Prose is the weakest possible fix, because a session reads this file once and then works for hours.
