---
type: ledger
updated: 2026-09-19
---

# Reminders: the commitment ledger

This is the ONE list of what is still outstanding. Not a second one in a project folder, not a TODO.md beside some code, not a note in a chat. Two lists drift, and then neither is trusted. If you need to write down HOW to do something, the commands, the checks, that belongs in a runbook next to the thing it operates. What is outstanding, and what fires it, belongs here.

Claude writes to this file the moment you say "remind me". Saving the commitment is the assistant's job, never yours.

Surface it by RUNNING it, never by remembering it: `python3 tools/agenda.py`. A session that read this file two hours ago is reading a copy, and it cannot tell from the inside that its copy has gone stale.

A trigger is a date, an event, or a condition. Closed rows stay here as tombstones, prefix the trigger with DONE, DROPPED or SUPERSEDED, or strike the title through, so the record of what was dropped survives. They never reach the agenda.

The row below is a fictional example. Delete it once you have a real one.

## Open

| Trigger | Type | What to surface | Why it matters |
|---|---|---|---|
| 2026-10-01 | Date | Ask whether the winter tune-up price held, or whether it quietly went back to what it was | A price set once and never checked is a guess wearing a decision's clothes |

## Done

| Trigger | Type | What to surface | Why it matters |
|---|---|---|---|

## Standing

Notes, preferences and standing rules that are context rather than work. They live in this file so there is one place to look, and the agenda tool stops at the next heading so they never appear as tasks.
