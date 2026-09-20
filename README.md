# Second Brain Starter Kit

A repository you clone to get a working, empty second brain that Claude Code writes and maintains for you: a compiled wiki of short, cited, interlinked articles sitting on top of a verbatim archive of everything it was built from. It ships with the gates that keep the wiki honest, so a commit is refused while a link is broken or a fact has only been written down on one side.

Built by Evan Nalu Foster. This is the machinery of my own second brain with my life taken out.

## Start here (non-technical)

You need three things on your computer: git, Python 3, and Claude Code. If you have Claude Code you already have the first two. Obsidian is optional and makes the result nicer to read.

1. **Get the files.** Download or clone this repository into a folder where you keep things you care about. Rename the folder to whatever you want your brain to be called.
2. **Make it a repository of its own.** Open a terminal in that folder and run `git init`, then `git add -A`, then `git commit -m "start"`. This is what makes every later change undoable.
3. **Install the gate.** Run `cp hooks/pre-commit .git/hooks/pre-commit` and then `chmod +x .git/hooks/pre-commit`. From now on, a commit that would leave the brain inconsistent is refused, with a message saying exactly what is wrong.
4. **Check that it works.** Run `python3 tools/lint.py`. You should see a short report ending with no errors. Then run `python3 tools/find.py bike` and you should get the example pages back.
5. **Tell Claude who you are.** Open `CLAUDE.md`, which is the rulebook every Claude Code session reads before it touches anything, and replace the second paragraph with one sentence about whose brain this is and what it covers.
6. **Delete the examples.** The three fictional pages about a bike shop are there so the tools have something to chew on. Delete `wiki/people/sam-rivera.md`, `wiki/projects/riverside-cycle-works.md` and `raw/entries/2026-09-12_shop-visit-notes.md`, and take their lines out of `wiki/_index.md`.
7. **Put something real in.** Drop a source into `data/`: an export from an app, a transcript, a folder of notes, a document you wrote. Anything. Start with one thing rather than everything.
8. **Start Claude Code in the folder and say: "ingest and absorb the file I just put in data/".** It will read the rulebook, split the source into entries under `raw/entries/`, write the wiki pages, link them up, and run the gates before it commits.
9. **Ask it something.** "What does my brain know about X?" It will search rather than read everything, which is what keeps the cost flat as the vault grows.

If something refuses to commit, read the message. The gates are written to say what is wrong and what to do about it, not just that something failed.

## What each tool does

All of them live in `tools/` and run with `python3 tools/<name>.py` from anywhere. None of them touch the network.

**`lint.py`** is the honesty gate. Broken links, links into the source layer that should be plain text, pages nothing points at, citation anchors that land nowhere, unfinished merges left in a file, a page accidentally pasted into itself, dates in the future, a link whose target exists on your disk and in nobody else's clone, and malformed rows in the reminders ledger. It exits non-zero on anything that would make the vault wrong for another reader, which is what the commit hook reads.

**`connect.py`** is the reciprocity gate. It finds every page you newly named this session whose own page you never opened, and refuses to let that sit. It also prints an advisory list of facts you changed that other pages also assert, so a right fact does not stop travelling halfway.

**`find.py`** is retrieval. It searches the compiled wiki, ranks the pages that actually mention your terms, and prints each one's summary plus the matching lines, so most questions are answered without opening a file.

**`deepfind.py`** is the same engine pointed at the full archive instead of the summaries. Reach for it when you need the exact words rather than the gist.

**`critic.py`** is the growth loop. It reads the vault and tells you where it is thin: pages the brain treats as important but has never fleshed out, questions it recorded and never answered, central pages going stale, pages barely connected to anything. It never edits.

**`quote_check.py`** asks one question about every quotation in the wiki: do those words actually appear in the entry the sentence cites? It takes each double-quoted run of four or more words in a sentence that links into `raw/entries/`, and looks for it in the entries that sentence cites. A quote it cannot find is reported with a second verdict saying whether the words are in a different entry, which means the citation points at the wrong source, or in no entry at all. It tolerates formatting and nothing else: curly against straight quotes, emphasis markers, dashes, and the full stop a page puts inside its closing quote, but no stemming and no fuzzy matching, so a reworded quotation is still a finding. A run joined by an ellipsis is split and each piece checked on its own. `--changed` limits it to the wiki files you have edited since the last commit, `--page` to one file, `--json` to a machine-readable dump, and `--all` adds the underscore pages and `log.md`.

It is **advisory and deliberately not wired into the commit gate.** A quotation that cannot be found here is not proof that anything was invented: a brain quotes sources it does not hold, including pages read in a browser, books, and recordings whose entry is a summary rather than a transcript. The tool exits 0 always. Run it after an absorb, read the list, and fix the ones that are wrong on the page itself, under the normal absorb rules, by rereading the source. Nothing here rewrites your prose. An entry marked `private: true` is searched like any other, so a quotation taken from one passes, and it is named by filename only and never quoted back at you.

The example pages that ship with this kit paraphrase their source rather than quoting it, so a first run reports nothing. To watch the tool work, add this line to `wiki/people/sam-rivera.md` and run it again. The citation link at the end matters: the tool only checks quotations in sentences that cite an entry.

```
Sam called the clipboard "the only system that never lies" ([[2026-09-12_shop-visit-notes#^bench-fits-two]]).
```

Those seven words are not in the entry, so the tool reports them. Change the quotation to "the bench only fits two", which is there, and it passes.

**`agenda.py`** prints what is still outstanding, read live from the ledger every time you run it.

**`safe_commit.sh`** is how a session commits. It takes a message and the list of files you actually edited, waits its turn behind any other session, pulls in whatever they pushed, refuses to proceed over an unfinished merge, runs the gates, commits, and retries the push through races.

## The ideas that make this different from a folder of notes

**Two permanent layers, not one.** Most note systems make you choose between keeping everything, which becomes unsearchable, and keeping a summary, which quietly becomes a curated self-portrait. This keeps both. `raw/entries/` holds the full text of every source forever. `wiki/` holds short compiled articles that cite it. A wiki page can say what a source means in two sentences and link to the exact paragraph it rests on, so the summary is the fast path and the full record is one click away when the stakes are high.

**Search first, so the cost stays flat.** The naive way to answer a question from a knowledge base is to read the index and then read the pages. That gets more expensive every week you use it. Here, every question starts as a search that ranks pages by how much they actually mention the terms and prints the matching lines. A vault ten times the size costs about the same to query.

**Honesty gates that block a commit.** Two scripts stand in front of every commit. One refuses a broken link, an orphan page, a citation anchor that lands nowhere, or a link to a file only your laptop has. The other refuses a one-way fact: if you wrote that two people worked on something and only updated one of their pages, it names the other and stops. A rule in a document gets skipped on the night it matters. A gate does not.

**Several Claude sessions, one folder.** `safe_commit.sh` exists because people run several sessions at once and plain git does not protect you from that. It holds an advisory lock so two commits cannot interleave, and it breaks the lock by itself if the holder dies. It makes you name the files you edited, because staging the whole tree means committing work you never opened and letting the gates bless pages nobody read. When another session pushes first, it replays your commit onto theirs entirely in memory rather than touching a file somebody else has open.

**One agenda.** Anything you ask to be reminded of goes into `wiki/_reminders.md`, keyed to a date, an event or a condition, and that file is the only list. A second list in a project folder is invisible to the brain, so the two drift apart and neither gets trusted. Closed rows stay in place as tombstones so the record of what was dropped survives, and `agenda.py` reads the file live every time, because a session that read it two hours ago is answering from a copy it cannot tell has gone stale.

**Postmortems as a first-class file.** `wiki/_postmortems.md` is not an appendix. Every time the brain gets something wrong and you catch it, it gets an entry answering four questions, and the entry is not finished until a fix is installed in the same session. Most of the checks in the linter exist because something on a page like that needed a mechanism rather than a resolution. A failure you only describe will happen again.

## Layout

```
CLAUDE.md          the rulebook every Claude Code session reads first
README.md          this file
LICENSE            MIT
hooks/pre-commit   the gate, to be copied into .git/hooks/
tools/             lint, connect, find, deepfind, critic, quote_check, agenda, safe_commit
tools/tests/       the test suite for the tools, run with python3 on each file
wiki/              the compiled brain, plus the index, ledger, log and postmortems
raw/entries/       normalized full text, one file per source chunk
data/              the immutable originals
.obsidian/         a graph filter that keeps the source layer out of the graph view
```

## Notes

The two-layer idea is not original to this kit. Several people have described a similar pattern publicly for keeping a language-model-maintained wiki over a raw archive. What is here is one working implementation of it, along with the gates that a couple of years of getting it wrong turned out to require.

Everything in `tools/` is plain Python 3 and bash with no dependencies to install. Nothing calls a model and nothing touches the network, so the gates keep working when the clever parts are unavailable.
