# State

measured: 2026-11-10

Volatile facts, re-measured rather than remembered. Replace stale lines; history is in git.

## Snapshot
- Frontend on `main` (f5ad602): `npx tsc --noEmit`, `npx eslint src/`, `npx prettier --check src/` pass; `npx vitest run` = 51 files, 489 tests pass (cloud container, Node 22.23.4, 2026-11-10).
- `cargo fmt --check --manifest-path src-tauri/Cargo.toml` passes.
- Local checks 2026-11-10 with the OpenRouter STT work in the tree (uncommitted): `tsc`, `eslint`, `prettier --check` clean; `npx vitest run` = 52 files, 512 tests; `cargo fmt --check` ok; `cargo clippy -- -D warnings` (CI form, without `--all-targets`) clean; `cargo test --lib` = 632 passed (2026-11-11, after the error-clarity work). `cargo clippy --all-targets -- -D warnings` fails on `native_hotkey.rs:152` (`monitored_bindings_for_base` unused on Linux), not caused by this work.
- Cargo needs the Linux dev libs; they were installed with apt in-session (the list is in AGENTS.md Gotchas) and are lost with the container. A setup script (deferred: setup-script-architect) would persist them.
- App version 1.1.64 (`package.json`).

## Known issues
- (none measured yet)

## In flight
- Branch `OpenTypeLess-OpenRouter-Edits` is pushed to origin up to `63c7c35` (2026-11-10): Phase 0 baselines, GOAL v1.1.0, OpenRouter STT provider and model picker, installer moved to `docs/baseline/`. Origin is `jondeux/opentypeless`; upstream is `tover0314-w/opentypeless`.
- Uncommitted (2026-11-11): error-clarity work for KR2. Rust `llm/http_error.rs`, mid-stream error handling, one 429 retry, coded Ask and test errors, STT codes; frontend `lib/llmError.ts`, capsule keys, toast, Ask/Settings/Onboarding display, strings in 10 locales; tests for each.
- KR4 workflow `.github/workflows/windows-build.yml` plus `src-tauri/tauri.fork.conf.json` written (uncommitted, not yet run; the owner is asked again before it is pushed).
- Next: a draft PR from a branch without the installer commit so CI runs on the Rust changes; then the owner's Windows run (KR1, KR2 manual half, KR3).
- Not run anywhere yet: `ci.yml` has not run on this branch's Rust changes (it triggers only on `main` and PRs).
- Deferred: continuous-learning-architect, setup-script-architect (Linux build libs for cargo).
