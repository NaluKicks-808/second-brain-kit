# The constitution

This vault is a second brain: a curated, interlinked, compounding wiki that an assistant compiles from your own data and then maintains forever. This file is its constitution. Any Claude Code session working in this vault reads this file first and obeys it.

Replace this paragraph with one sentence saying whose brain this is and what it currently covers. Scope is worth naming, because a brain that claims to cover everything and covers one project will be trusted about the wrong things.

## The one idea

**You are a writer, not a filing clerk.** The wiki is a map of a mind, not a folder of facts. The question is never "where do I put this?" It is: **what does this mean, and how does it connect to what is already here?** A good entry touches five to fifteen existing articles. A great one reveals a pattern that deserves an article of its own.

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

The core loop. For each entry: read it and understand what it means; check `_index.md` for the articles it touches; **reread each of those articles in full before editing it**, never edit blind; ask what new dimension this adds, and update or create articles; fix the cross-links in both directions; append a line to `log.md`. Checkpoint roughly every fifteen entries with a quality audit.

#### The closing ritual (mandatory, before every commit)

This is what keeps knowledge from stranding on one side of a link. When a new fact enters, it is not absorbed until it is woven into every page it touches, in both directions. A fact about a trip is also a fact about the people in it, the places it happened, and the ventures it strained. The discipline that guarantees this is not memory. It is two scripts, run from the vault root:

1. `python3 tools/lint.py`, zero broken links, zero graph pollution, zero orphans.
2. `python3 tools/connect.py`, the reciprocity check. It reports every page you newly named with a `[[wikilink]]` whose own page you did not update and which does not link back. **Every `GAP` line must be resolved before you commit.** Open that page, record the same fact from its side, and link back. Or, rarely, decide consciously that the one-way mention is genuine passing context and move on. A `GAP` you skip is exactly the failure this ritual exists to prevent: a page that names somebody and never tells them.

Then update `_index.md`, append to `log.md`, and commit with `./tools/safe_commit.sh "message" <the files you edited>` rather than raw `git commit` and `git push`.

**Name the files. Only the files you touched.** The obvious alternative stages the whole working tree, which means a session commits work it has never opened. In the vault this came from that happened three times in one evening: one session's work landed inside another's commit, so the git log, which later sessions reason from, became fiction; the gates ran over a mixed changeset and blessed pages nobody had read; and a half-written page was published by a session with no idea it was mid-edit. A session always knows what it edited. `--all` remains for a sweep that genuinely owns the whole tree, and it prints what it is about to take, so a sweep is a decision rather than an accident.

The commit script also holds an advisory lock for the commit-and-push window, so two sessions cannot interleave, and it self-heals after ten minutes if a session dies holding it. If you run several sessions at once, another one may have pushed while you worked. The script rebases first, refuses to proceed over conflict markers, runs the same gates through the hook, and retries the push through races. Never pop another session's stash.

#### The weave-back rule

Knowledge about a vault entity produced anywhere, a working document in another project, web research, a conversation in a different session, must update that entity's wiki page in the same session. A line in `log.md` is a pointer, never the record. If the page still says the old thing, the knowledge is not absorbed.

#### Write it back before you answer, not before the session ends

The write-back rule above is easy to hear as "before this session finishes". A session reading it late at night hears that, because the thread is live and the next message always feels more urgent than a file nobody is waiting on. So the trigger is sharper than it looks: **the write-back precedes your next reply to the user, not the end of the session.** You shipped it; you write it down; then you answer.

This matters most in the case that feels safest. A turn that ends on a question to the user is the most dangerous kind, because waiting on an answer feels like a legitimate stopping point and it converts an unpaid debt into silence. In the vault this came from, two hours of that silence was long enough for another session to read a ledger row saying work was still pending when it had been live the whole time.

#### The system-change rule

If a session adds, changes or retires any automation or standing system, a scheduled task, a hook, a pipeline, a notification channel, it records that in the same session, before the commit. Documentation about systems rots unless the change and the document travel together. A periodic audit comparing what is documented against what actually runs is a backstop, not a mechanism.

### QUERY

Answer from the wiki, not from memory, and retrieve **search first**. This is the token-efficient path: search cost stays flat as the vault grows, and reading the whole index every time does not.

1. **Search, do not read the index.** Run `python3 tools/find.py <keywords and obvious synonyms>`. It ranks the pages that actually mention the terms and prints each one's summary plus the matching lines. That is usually enough to answer outright, or to name the one page worth opening.
2. **Open only what it points to.** Read the top page in full when it is focused. For a large log or journal page where the term is a small fraction of the file, grep to the matching lines instead of reading the whole page.
3. **Fall back to the index only** when the question has no good keyword, or when the search returns nothing.
4. **Synthesize with citations** back to the pages you used. A genuinely useful answer can be filed as a new article.
5. **Never answer "what is outstanding" from a copy of the ledger read earlier in the session.** Run `python3 tools/agenda.py`. A long session outlives its own reads, and it cannot tell from the inside that its copy has gone stale. This is the same bug as reading a clock once and using the number twelve hours later.

### CLEANUP

The health check that keeps the brain honest. Flag contradictions between articles, stale claims that a newer source overturned, orphan articles nothing links to, important entities that have no article yet, and, most important, **hallucinated or forced links**, which is the assistant's own habit of inventing connections. Report. Do not silently fix by guessing.

### CRITIC

The growth loop, and the other half of self-improvement. The linter and the reciprocity check keep the brain consistent; they are gates that block bad state. `python3 tools/critic.py` keeps it growing. It reads the vault and surfaces its own highest-leverage gaps: pages the vault treats as important or well-sourced but that are still thin, every recorded open question gathered into one queue, central pages going stale, and pages barely woven into the graph. It is advisory and never edits. The loop closes when a session runs it and then acts on the top of the deepening list, mining the source layer under the normal absorb discipline.

## Writing standard: an encyclopedia, not a chatbot

This is the anti-slop, anti-hallucination guardrail, and it is not negotiable.

- **Readable prose, not an evidence locker.** Inline source-telling mid-sentence chokes the writing. Keep detailed citations in the `sources:` frontmatter or in one short trailing note, and let the sentences flow. Link generously: a paragraph naming several known entities should carry several `[[wikilinks]]`, not one. Dates belong where they carry meaning, not scattered as confetti.
- **Flat, factual, encyclopedic.** No peacock words (legendary, visionary, groundbreaking, game-changing), no rhetorical questions, no "interestingly", no editorializing.
- **Attribution over assertion.** Write "she decided X because Y" or "the audit found Z", not "brilliantly, X". If a claim came from a source, it should read like it.
- **Every load-bearing claim cites its source**, as an anchored link into `raw/entries/` or as a plain-text `data/` filename. An article with no citations is a red flag.
- **At most two direct quotes per article**, kept for the ones that carry real weight.
- **Summary first.** Every article opens with one sentence saying what it is, so that a query can tell at a glance whether the page is worth opening.
- **Never hard-wrap prose.** Obsidian renders a single newline as a line break, so wrapped lines read as ragged fragments. One paragraph is one line, however long. A blank line between paragraphs. The same inside callouts and list items.

## Anti-patterns

**Anti-cramming.** It is always easier to bolt a paragraph onto a big article than to spin up a new one. Resist. Five bloated articles are worse than thirty focused ones. When a subtopic reaches about three meaningful sentences, it has earned its own page.

**Anti-thinning.** No empty stubs. Every touch should enrich. A one-line placeholder is debt.

**The compiled layer characterises; the source layer stays complete.** Some material is sensitive, and the temptation is to leave it out of the archive. Do not. `raw/entries/` keeps the full text, because total capture is the entire reason the vault is worth anything, and carving an exception for the parts that are uncomfortable is how an archive quietly becomes a curated self-portrait. A `wiki/` page may state plainly what is true about a relationship or a situation without reproducing a line of it. Mark such entries `private: true` in their frontmatter and exclude them from any compiled digest.

**Measure a corpus before you delegate it.** A subagent cannot tell you its slice was too big if nobody measured the slice. Hand a worker more text than fits in its context and it will run out of room partway and write a confident summary of whatever it happened to read, with no way for you to see that from the outside. Every coverage rule tends to govern READING, and none of them govern DELEGATING, because delegation feels like scheduling rather than reading. So: compute the token weight of any corpus before handing it off; partition it to fit; require each worker to report **coverage as a fraction** ("read 1,847 of 1,847") rather than the word "absorbed"; and require a shortfall to be declared before writing rather than footnoted after. Give parallel workers **disjoint write surfaces**, one new file each, with no shared files and no git, because several agents queued behind one blocking commit gate will deadlock. The parent integrates them serially.

**Anything the owner wrote gets normalized WHOLE.** Absorb quarries facts, and a primary source in the owner's own voice is not a quarry. The failure this prevents is specific and expensive: an application essay was absorbed by a pass looking for events, the events were mined out correctly, and the essay itself was left as a PDF plus a handful of excerpts, with the rest deferred to a curator who did not exist. Six weeks later the owner asked their own brain for their personal statement and it returned no matches, while phrases they had actually written appeared on zero pages. So: when the source is something the owner wrote or said, an essay, an application, a talk, a letter, a voice memo, the full text goes into `raw/entries/` verbatim before any mining begins, split by its own headings with block anchors, and the wiki quarries from there. Facts are what the vault concludes. The owner's writing is evidence, and evidence is kept whole. A deferral note naming a curator who does not exist is a tombstone, not a plan.

**Re-read the clock before writing any date.** A clock reading goes stale; a fact does not. Long sessions cross midnight, and a session that read the date at the start and uses it at the end will stamp files with yesterday. Two rules follow. The clock is the one input that must be re-read at the moment of use and never carried forward. And a relative word, today, tomorrow, this week, must be resolved against a fresh reading and then written as an absolute date, never left relative in a file. Note also that a correction can cause the next error: a session burned for using tomorrow's date will be primed to treat that date as wrong long after it has become today's.

**An artifact is not a fact.** A meeting notetaker has two layers and they are not equal evidence. The **transcript** is what people said. The **summary, the action items and the assignees are the tool's tidy reading of it**, and tidying is exactly where a hypothetical, a conditional and a "we were just spitballing" get promoted into decisions. Cite the transcript. Treat a generated bullet as a lead to verify, never as the fact. Four specific traps, each of which has been paid for:

- **The assignee is metadata about whose account recorded the call**, not evidence of who owns the task. Most tools attribute to the account holder.
- **A recorder does not stop when the other side hangs up.** Late transcript material is often the team talking privately. A number, a commitment or an opinion in the last minute may never have been said to the client at all, so never write "quoted", "agreed" or "priced at" from a recording without asking the owner.
- **An unattributed summary bullet reads as consensus, and usually is not.** A summary strips the "I think we should" off a sentence and leaves something that sounds like a resolution the room reached. A bullet with no speaker is evidence that a topic came up. It is never evidence of whose idea it was, and never evidence that anybody agreed.
- **A generated action item is the notetaker's inference, not a promise anybody made.** A session once absorbed a notetaker's checkbox as an obligation nobody had made, gave it a deadline the summary did not carry, and escalated it into a brief. The transcript underneath showed somebody volunteering the thing and being thanked for it. An offer is not an obligation, a courtesy is not a deadline, and "sounds good" is not a request. Before a generated checkbox becomes a ledger row, read the sentence that produced it and record who wanted it and how strongly. The tell that this has gone wrong is the owner reading their own ledger and asking where an item came from.

**When a transcript cannot settle who said something, say so instead of inferring.** Speaker labels are unreliable across every notetaker, and a recording with more than one voice and no working speaker separation is not evidence of who said what. Attribution inferred from content is a reading, and a reading hardens the moment three pages cite it. Where it matters, show the owner the least certain passages with their surrounding text and let them settle each one in a sentence each. Where it cannot be settled, the vault writes "one of them said". It never picks.

**One agenda.** `wiki/_reminders.md` is the only list of what is still outstanding. Never create a second one in a project folder. A task file beside some code is invisible to the brain, so the two drift and neither gets trusted. Split it instead: what is outstanding and when it fires goes in a ledger row, and how to do it, the commands, the checks, goes in that project's runbook. Writing the ledger AND a second copy is not compliance; duplicating into a new home is the failure, not the remedy for it.

## Article shapes

Guides, not cages.

- **Person**, organized by role and relationship phase, not chronology.
- **Concept or pattern**, thesis, how it works, where it applies, open questions.
- **Decision**, situation, options, reasoning, what was chosen, how it has held up.
- **Project**, what it is, status, architecture, the live risks, what is next.
- **Playbook**, a living how-to that compounds, such as objections and what actually landed.

## Golden rules

1. **The owner curates what enters `data/`; the assistant does all the upkeep.** That division is the whole point.
2. **Never invent. Blank beats wrong.** Uncited synthesis that sounds right is the failure mode, and it is very hard to detect later.
3. **Frontmatter on every article:** `type`, `updated` as YYYY-MM-DD, and `sources` as a list. Use `[[wikilinks]]` throughout.
4. **The `data/` originals are immutable.** Corrections happen in `wiki/`, with a note, never by rewriting history.
5. **A rule that fails twice becomes a gate.** Write the failure into `wiki/_postmortems.md`, and install something mechanical in the same session. Prose is the weakest possible fix, because a session reads this file once and then works for hours.
