# Goal progress

Status of each key result in the project goal. Source: [docs/setup/GOAL.md](../../docs/setup/GOAL.md); targets are copied from there, never edited here. Update with evidence, not estimates.

| Key result | Target | Status | Evidence | Updated |
|---|---|---|---|---|
| KR1 OpenRouter setup on Windows | 3 of 3 steps by 2027-02-10 | 0 of 3 (baseline: not yet run on Windows) | checklist in [windows-fork-build.md](../../docs/windows-fork-build.md) | 2026-11-10 |
| KR2 OpenRouter error clarity | 4 of 4 listed cases by 2027-02-10 (LLM polish, Ask and STT) | 0 of 4 actionable (cases listed: 401 bad key, 402 no credit, 400/404 unknown model, 429 rate limit; all show generic text today, from code reading, not yet run in the app) | case table in [windows-fork-build.md](../../docs/windows-fork-build.md) | 2026-11-10 |
| KR3 OpenRouter speech-to-text | 1 verified dictation via an in-app-chosen OpenRouter STT model on Windows by 2027-02-10 | 0 of 1 verified on Windows. Implemented and tested locally 2026-11-10 (uncommitted): provider `openrouter-stt`, live model picker, shared key; Rust 620 tests and Vitest 498 pass, clippy clean. Not yet run against a real recording or on Windows. Endpoint `POST /api/v1/audio/transcriptions` verified 2026-11-10: one real call with 2 s of silence returned `{"text":"","usage":{"seconds":2,"cost":0.00000666}}`; 31 models with output `transcription` in the catalog | [windows-fork-build.md](../../docs/windows-fork-build.md) | 2026-11-10 |
| KR4 Windows installer from this branch | 1 built and installed by 2027-02-10 | 0 built. Baseline installer 1.1.61 inspected: identifier `com.opentypeless.app`, upstream updater endpoint; diff vs source stand-in `72914e8` listed | [windows-fork-build.md](../../docs/windows-fork-build.md) | 2026-11-10 |
