---
paths:
  - "wiki/**"
  - "raw/**"
---

# Writing the wiki

Claude Code loads this file automatically whenever a session reads or edits anything under `wiki/` or `raw/`, so the constitution stays short and these rules still arrive exactly when they matter. A session that writes vault pages any other way (a script, a worker brief, a tool that edits pages remotely) reads this file first.

## Writing standard: an encyclopedia, not a chatbot

This is the anti-slop, anti-hallucination guardrail, and it is not negotiable.

- **Readable prose, not an evidence locker.** Inline source-telling mid-sentence chokes the writing. Keep detailed citations in the `sources:` frontmatter or in one short trailing note, and let the sentences flow. Link generously: a paragraph naming several known entities should carry several `[[wikilinks]]`, not one. Dates belong where they carry meaning, not scattered as confetti.
- **Flat, factual, encyclopedic.** No peacock words (legendary, visionary, groundbreaking, game-changing), no rhetorical questions, no "interestingly", no editorializing.
- **Attribution over assertion.** Write "she decided X because Y" or "the audit found Z", not "brilliantly, X". If a claim came from a source, it should read like it.
- **Every load-bearing claim cites its source**, as an anchored link into `raw/entries/` or as a plain-text `data/` filename. An article with no citations is a red flag.
- **A guess is labelled as a guess.** A fact inferred from metadata, from a single summary, from a ledger row or from a speaker label goes in as a `> [!question]` callout or under `status: provisional`, never as a plain sentence, and no automation keys off a provisional field. `tools/lint.py` warns on guess words such as "presumably", "almost certainly" or "must have" outside a callout; the session that reads the warning answers it, either by citing the fact or by turning the sentence into a question.
- **At most two direct quotes per article**, kept for the ones that carry real weight.
- **Summary first.** Every article opens with one sentence saying what it is, so that a query can tell at a glance whether the page is worth opening.

## Sources, evidence and anti-patterns

- **Anti-cramming.** It is always easier to bolt a paragraph onto a big article than to spin up a new one. Resist. When a subtopic reaches about three meaningful sentences, it has earned its own page.
- **Anti-thinning.** No empty stubs. Every touch should enrich. A one-line placeholder is debt.
- **Anything the owner wrote gets normalized WHOLE.** Absorb quarries facts, and a primary source in the owner's own voice is not a quarry. When the source is something the owner wrote or said (an essay, an application, a talk, a letter, a voice memo) the full text goes into `raw/entries/` verbatim before any mining begins, split by its own headings with block anchors, and the wiki quarries from there. Otherwise the events get mined out correctly and the writing itself is lost: the owner later asks their brain for their own essay and it returns nothing. A deferral note naming a curator who does not exist is a tombstone, not a plan.
- **The compiled layer characterises; the source layer stays complete.** `raw/entries/` keeps the full text, because total capture is the reason the vault is worth anything, and carving an exception for the uncomfortable parts is how an archive quietly becomes a curated self-portrait. A `wiki/` page may state plainly what is true about a relationship or a situation without quoting a line of it. Give such entries `private: true` in their frontmatter and exclude them from every compiled digest.
- **An artifact is not a fact.** A meeting notetaker has two layers and they are not equal evidence. The **transcript** is what people said. The **summary, the action items and the assignees are the tool's tidy reading of it**, and tidying is exactly where a hypothetical gets promoted into a decision. Cite the transcript. Treat a generated bullet as a lead to verify.
  - **The assignee is whose account recorded the call**, not who owns the task.
  - **A recorder keeps running after the other side hangs up**, so late material is often the team talking privately. "Quoted", "agreed" or "priced at" from a recording stays provisional until the owner confirms it.
  - **An unattributed summary bullet shows a topic came up**, not whose idea it was or that anybody agreed.
  - **A generated action item is an inference, not a promise.** Before it becomes a ledger row, read the sentence that produced it and record who wanted it and how strongly. An offer is not an obligation, a courtesy is not a deadline, and "sounds good" is not a request.
  - **Speaker labels are unreliable across every notetaker.** When the transcript cannot settle who spoke, write "one of them said"; never pick. A name spoken in the conversation identifies who was addressed, not who was speaking. Check any speaker-separation output before trusting it.
  - **Attribution inferred from content is a reading**, and a reading hardens the moment three pages cite it. Write it as provisional and keep going; ask the owner only when who said it changes a decision, money or an obligation.

## Article shapes (guides, not cages)

- **Person**: organized by role and relationship phase, not chronology.
- **Era or event**: a lead, then sections by topic or period, in the order things happened; a day-by-day shape is right for a trip.
- **Concept or pattern**: thesis, how it works, where it applies, open questions.
- **Decision**: situation, options, reasoning, what was chosen, how it has held up.
- **Project**: what it is, status, architecture, the live risks, what is next.
- **Playbook**: a living how-to that compounds, such as objections and what actually landed.

**Every shape shares four rules.** A lead of one to three short paragraphs. Headings name subjects or periods of a life, never the date a fact reached the vault. The article never narrates its own edit history or speaks to future sessions: corrections, unresolved contradictions, operational notes and `[!question]` callouts live in a last section, `## Notes and open questions`, which is the page's talk page. And at most one timeline, at the end. **Length is a soft cap:** past about 3,000 words (or 800 in one section), move the biggest sections to their own pages, leaving a summary and a `Main article: [[...]]` line. Day-by-day trip pages are exempt.

**Integrate, never append.** A new fact is submitted to the page, not stapled to it: rewrite the passage where it belongs and remove what it makes stale. A page that reads as a stack of dated deliveries has been appended to, not written. Before replacing a whole page, list every citation and every `[[link]]` it carries, and check the rewrite (plus any pages split off from it) still carries each one.

## Formatting (hard rule)

**Never hard-wrap prose.** Obsidian renders a single newline as a line break, so wrapped lines read as ragged fragments. One paragraph is one line, however long; a blank line between paragraphs; the same inside callouts (one `>` line per paragraph) and list items (one `-` line per item, no indented continuation lines).

## Frontmatter

**Frontmatter on every article:** `type`, `updated` (YYYY-MM-DD) and `sources` (a list). Use `[[wikilinks]]` throughout.

**Structured fields by type**, written only when the page itself states the fact:

- a person: `relationship` (a list from family, partner, friend, school, work, business, client, mentor, teacher, community, acquaintance), `met`, `met-where`, `born`, `lives`, `works`, `last-contact`;
- a project or client: `state` (active, paused, done, abandoned, idea, declined; for a client: prospect, active, paused, churned, declined, done), `started`, `ended`, `owner-role`, `people`;
- an era or event: `start`, `end`, `people`;
- a decision: `decided`, `state` (holding, revisited, reversed, pending).

Dates are quoted ISO, and partial dates are allowed (`"2024-08"`). When an absorb changes one of these facts in the prose, it changes the field in the same edit. The fields are what an Obsidian Bases view (a people table, a project board, a timeline) reads, so a field that disagrees with its own page is a visible bug. Adding fields alone does not bump `updated`.
