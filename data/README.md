# data/: the originals, and they are immutable

This is where a source lands exactly as it arrived: an export, a transcript, a PDF, a pasted thread, a set of notes. Name each one `src-<what>`, for example `src-shop-visit-2026-09-12`.

Three rules, and they are short because they are absolute.

**Nothing in here is ever edited after it lands.** A correction happens in `wiki/`, with a note saying what was corrected and why. Rewriting an original destroys the only thing that makes the rest of the vault checkable.

**Nothing in here is ever linked with a wikilink.** Cite a file in here as plain text. The linter treats a wikilink whose target names a file in this folder as an error, because those links would drag the source layer into the graph view and bury the map of ideas under a pile of filenames. The layer above this one, `raw/entries/`, IS a legal link target, so cite the normalized entry when you want a clickable citation.

**Large archives stay outside the vault.** A chat database, a full mail export, a folder of video, keep those wherever they live and put only a small manifest in here saying what exists and where. A repository you cannot clone in under a minute stops being a brain and becomes a backup.

You curate what enters this folder. The assistant does everything downstream of it. That division is the whole point: a human decides what is worth keeping, and the machine does the upkeep forever.
