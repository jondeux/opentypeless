# Project memory

Index of this repo's committed memory. One short line per entry; detail lives in the linked files, read on demand. Keep this file under 200 lines and 25KB (`memory.py lint` checks). Facts, not instructions: rules belong in AGENTS.md.

Pending candidates: 0 (see [candidates](candidates.md); the user approves with "approve all" or "approve 1,3")

## Files
- [State](state.md): measured snapshot, known issues, work in flight. Rewrite it; don't append.
- [Goal progress](goal-progress.md): key-result status with dates and evidence.
- [Decisions](decisions.md): what was decided, why, and how to undo it.
- [Candidates](candidates.md): proposed rules waiting for the user's approval.

## Elsewhere
- `handoff.md` and `docs/*-spec.md`: stale July 2026 handoff and dated design records; history only, not current state.

## Entries
<!-- One line each: "- <fact or pointer> (updated YYYY-MM-DD)". Merge or drop stale lines. -->
- Branch `OpenTypeLess-OpenRouter-Edits` is for OpenRouter edits on the jondeux fork (updated 2026-11-10)
- Cloud container needs `apt-get install` of the Linux dev libs (AGENTS.md Gotchas) and `npm ci` per fresh session before cargo or frontend checks run (updated 2026-11-10)
