# Decisions

One entry per decision that code and git history can't explain on their own.

<!-- ## D<n> <title> (2026-11-10)
- decided: ...
- why: ...
- rejected: ...
- undo: ... -->

## D1 Windows installer route (2026-11-10)
- decided: build an unsigned NSIS installer with a new manual `workflow_dispatch` workflow; disable the updater in the fork build via a build-time config override only; verify Rust changes through a draft PR to fork `main`.
- why: upstream deleted its release workflows (commit `fdeeeb5`); CI runs only on `main` and PRs; fork builds would otherwise update themselves to upstream; cargo cannot run in the cloud container.
- rejected: local-only Windows build; leaving the updater on; own signing key (signing and publishing are out of scope).
- undo: delete the workflow and `src-tauri/tauri.fork.conf.json`.

## D2 Baseline installer location (2026-11-10)
- decided: move `OpenTypeless_1.1.61_x64-setup.exe` to `docs/baseline/` and ignore other `*.exe`/`*.msi`; keep it out of PRs to `main`.
- why: 5 MB binary in the repo root bloats PRs and upstream merges; it stays as the KR3 diff baseline.
- undo: `git mv` it back and remove the `.gitignore` lines.

## D3 OpenRouter speech-to-text added to the goal (2026-11-10)
- decided: GOAL v1.0.0 -> v1.1.0. Scope adds OpenRouter STT via `POST /api/v1/audio/transcriptions`; new KR3 (verified STT dictation on Windows); installer KR renumbered to KR4; KR2 error cases also cover STT. One shared OpenRouter key for STT and LLM. STT model list fetched live from `/models?output_modalities=transcription`, with a short built-in fallback.
- why: the app's STT providers did not accept OpenRouter keys; the owner wants OpenRouter's transcription models in-app. 31 such models exist (Whisper, GPT-4o transcribe, Nova-3, Scribe v2, Voxtral, Parakeet and others).
- rejected: separate STT key (more setup); curated-only model list (goes stale); no goal change (STT would sit outside scope).
- undo: revert the GOAL.md edit and delete `src-tauri/src/stt/openrouter.rs` and its registrations.
