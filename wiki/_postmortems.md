---
type: ledger
updated: 2026-09-19
---

# Postmortems

A first-class file, not an appendix. Every time the brain gets something wrong and you catch it, it gets an entry here, and the entry is not finished until a fix is installed in the same session.

The point is not the apology. It is that a failure you only describe will happen again, and a failure you convert into a gate will not. Most of the checks in `tools/lint.py` exist because something on a page like this one needed a mechanism rather than a resolution.

## The four questions

Every entry answers these, in order, and nothing else is required.

1. **What happened?** The specific, observable thing, what was written, read or shipped, and when.
2. **Why did it happen?** Not "the model hallucinated". The systemic gap: which rule was missing, which rule existed and was unreachable from where the session was standing, or which two sources of truth were allowed to disagree.
3. **What is the fix, and is it mechanical?** A rule in prose is the weakest possible fix, because a session reads a constitution once and then works for hours. A gate, a script, or a command that has to be run is a fix. Prose is a fix only when nothing mechanical is possible, and then say so.
4. **Did the fix land this session?** Yes or no. A postmortem whose fix is deferred to a curator who does not exist is a tombstone, not a plan.

## Entries

### #1 (2026-09-19): an action item was absorbed as an obligation nobody had made

**What happened.** A meeting notetaker's summary listed a checkbox reading that the owner would send a document to a client. A session absorbed the checkbox as a commitment, wrote it into a wiki page as something owed, gave it a deadline the summary did not carry, and put it on the agenda. The transcript underneath showed the opposite: somebody had offered the document unprompted, and been thanked. An offer is not an obligation, and a courtesy is not a deadline.

**Why it happened.** A notetaker has two layers and they are not equal evidence. The transcript is what people said; the summary, the action items and the assignees are the tool's tidy reading of it, and tidying is exactly where a hypothetical gets promoted into a decision. Nothing in the absorb rules distinguished the two, so the tidier layer, being shorter and easier to read, won every time.

**The fix.** The constitution now says that a generated bullet is a lead to verify and never a fact, that an unattributed summary line is evidence a topic came up and nothing more, and that before a generated checkbox becomes a ledger row a session must read the sentence that produced it and record who wanted it and how strongly. It is prose rather than a gate, because no script can tell a decision from a hypothetical. The tell that it has gone wrong again is you reading your own ledger and asking where an item came from.

**Landed this session.** Yes.
