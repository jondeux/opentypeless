# State

measured: 2026-11-10

Volatile facts, re-measured rather than remembered. Replace stale lines; history is in git.

## Snapshot
- Frontend on `main` (f5ad602): `npx tsc --noEmit`, `npx eslint src/`, `npx prettier --check src/` pass; `npx vitest run` = 51 files, 489 tests pass (cloud container, Node 22.23.4, 2026-11-10).
- `cargo fmt --check --manifest-path src-tauri/Cargo.toml` passes.
- `cargo clippy` / `cargo test` not run in the cloud container: `webkit2gtk-4.1` and `alsa` dev libraries are missing (`pkg-config` check). CI installs them (see `.github/workflows/ci.yml`).
- App version 1.1.64 (`package.json`).

## Known issues
- (none measured yet)

## In flight
- Branch `OpenTypeLess-OpenRouter-Edits` (renamed 2026-11-10 from `claude/inspiring-rubin-nuwpwk`, same commit as `main`): intended for OpenRouter-related edits; no edits made yet. Origin is `jondeux/opentypeless`; upstream is `tover0314-w/opentypeless`.
- Workspace setup (AGENTS.md, memory, agent-memory, hooks, goal) written 2026-11-10; awaiting commit. Deferred: continuous-learning-architect, setup-script-architect (Linux build libs for cargo).
