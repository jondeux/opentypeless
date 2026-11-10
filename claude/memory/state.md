# State

measured: 2026-11-10

Volatile facts, re-measured rather than remembered. Replace stale lines; history is in git.

## Snapshot
- Frontend on `main` (f5ad602): `npx tsc --noEmit`, `npx eslint src/`, `npx prettier --check src/` pass; `npx vitest run` = 51 files, 489 tests pass (cloud container, Node 22.23.4, 2026-11-10).
- `cargo fmt --check --manifest-path src-tauri/Cargo.toml` passes.
- Local checks 2026-11-10 with the OpenRouter STT work in the tree (uncommitted): `tsc`, `eslint`, `prettier --check` clean; `npx vitest run` = 51 files, 498 tests; `cargo fmt --check` ok; `cargo clippy -- -D warnings` (CI form, without `--all-targets`) clean; `cargo test --lib` = 620 passed. `cargo clippy --all-targets -- -D warnings` fails on `native_hotkey.rs:152` (`monitored_bindings_for_base` unused on Linux), not caused by this work.
- Cargo needs the Linux dev libs; they were installed with apt in-session (the list is in AGENTS.md Gotchas) and are lost with the container. A setup script (deferred: setup-script-architect) would persist them.
- App version 1.1.64 (`package.json`).

## Known issues
- (none measured yet)

## In flight
- Phase 0 baselines done locally 2026-11-10 (uncommitted): `docs/windows-fork-build.md`, installer moved to `docs/baseline/`, `.gitignore` blocks new `*.exe`/`*.msi`. GOAL bumped to v1.1.0 (OpenRouter STT, uncommitted). STT provider (`src-tauri/src/stt/openrouter.rs`), shared-key resolution, model-list command, STT pane picker and 10 locales are written and passing locally (uncommitted). Next: error classification (Phase 1/2), then the Windows build workflow, then the Windows run.
- Branch `OpenTypeLess-OpenRouter-Edits` (renamed 2026-11-10 from `claude/inspiring-rubin-nuwpwk`, same commit as `main`): intended for OpenRouter-related edits; no edits made yet. Origin is `jondeux/opentypeless`; upstream is `tover0314-w/opentypeless`.
- Workspace setup (AGENTS.md, memory, agent-memory, hooks, goal) written 2026-11-10; awaiting commit. Deferred: continuous-learning-architect, setup-script-architect (Linux build libs for cargo).
