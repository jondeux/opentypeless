# Windows build of the OpenRouter fork

Working document for the goal in [GOAL.md](setup/GOAL.md). Status per key result lives in
[`claude/memory/goal-progress.md`](../claude/memory/goal-progress.md).

## Baseline installer (1.1.61)

- File: `docs/baseline/OpenTypeless_1.1.61_x64-setup.exe`, 4,964,818 bytes.
- SHA-256: `1f3914d5aaac45324274661b4ec5c84a484417969b5dd38a34d86caf7f1f53c8`.
- Added to the branch by commit `6c79cc0` ("Add files via upload"), then moved here. Its provenance beyond that
  is not verified: no official hash was available to compare against.
- Never run it in CI or the cloud container. Inspected only by unpacking with 7-Zip into a temporary directory
  and reading strings from the bundled `opentypeless.exe` (no execution).

What the unpacked app contains (measured 2026-11-10):

| Item | Value | Consequence |
|---|---|---|
| Format | NSIS self-extracting installer, x86 PE | Same format `tauri build --bundles nsis` produces. |
| Product / version | `OpenTypeless` / `1.1.61` | Branch is at 1.1.64, so the new build spans three versions. |
| Bundle identifier | `com.opentypeless.app` | Identical to `src-tauri/tauri.conf.json` on this branch, so a new NSIS build should upgrade in place. Confirm in the Windows run. |
| Updater endpoint | `https://github.com/tover0314-w/opentypeless/releases/latest/download/latest.json` | The baseline updates itself from upstream. A user on 1.1.61 may already have been moved to an upstream release before installing our build. The fork build overrides this (see plan, Phase 3). |
| Updater public key | upstream's minisign key | Fork builds cannot publish updates that this key would accept. |
| Default LLM | `https://openrouter.ai/api/v1`, `google/gemini-2.5-flash` | Already the default in 1.1.61. |

Not measured: NSIS install mode (per-user or per-machine), install path, and uninstall behaviour. Read these from
the Windows run, not from strings.

## Changes since 1.1.61

Source stand-in: commit `72914e8` ("prepare v1.1.61 source", a version bump only). It is not proven to be the exact
source of the downloadable installer. The repository is a shallow clone with no tags, so the exact tag diff was not
possible. `git diff 72914e8 HEAD` covers 84 files (+8,591 / -1,859) and 19 commits. Upstream commits in that range
(no workspace or documentation commits):

- `f3a0334` fix: isolate cancelled desktop sign-in flows (#137)
- `0cbef12` chore: prepare v1.1.62 login recovery release (#139)
- `678e049` fix(release): pin AppImage plugin and prepare v1.1.63 (#140)
- `e32f7d2` fix: align cloud deadlines and reject truncated managed audio (#143)
- `c3dd860` fix: clear remaining client development dependency advisories (#144)
- `4f83f54` fix: keep rotated provider keys across settings saves
- `1b37b18` fix: preserve speech finalization and cancel stale Ask sessions
- `8a4eec8` fix: center capsules and recover their recording and error placement
- `b98fe2f` fix: expose the existing start-minimized preference
- `64f3b51` chore: update audio capture to CPAL 0.18.2
- `7faa39f` fix: reject stale Ask results after cancellation
- `0347500` fix: preserve native cloud capability across settings saves
- `8a0118a` fix: restore maximized main window and normal bounds
- `6d8f0e9` fix: translate settings scenes and account messages in eight locales

OpenRouter-relevant: `4f83f54` (provider keys survive settings saves), `7faa39f` and `1b37b18` (Ask cancellation).
No upstream commit in this range changes OpenRouter error handling. Changes made on this branch for the goal are
listed below as they land.

### Changes on this branch (OpenRouter goal)

- OpenRouter speech-to-text (KR3), uncommitted: provider `openrouter-stt` (`src-tauri/src/stt/openrouter.rs`), shared OpenRouter key (`credentials.rs::stt_secret_scope`), live model list (`fetch_openrouter_stt_models`), model picker in the STT pane, strings in 10 locales, new setting `stt_openrouter_model`.
  - Endpoint and response shape verified with one real call on 2026-11-10 (2 s of silence, `openai/whisper-large-v3-turbo`): `{"text":"","usage":{"seconds":2,"cost":0.00000666}}`.
  - Not verified: the `language` field (not sent; the model auto-detects), request size limits (recording is capped at 120 s recommended, 720 s maximum), and WAV support for each of the 31 models. Check these in the Windows run with at least two models.
- Error messages (KR2) and the Windows build workflow (KR4): not started.

## OpenRouter error cases (KR2)

Case list fixed 2026-11-10 (applies to LLM polish, Ask and STT). Status code and behaviour verified against the OpenRouter docs; the unknown-model body
was also confirmed with one live call.

| # | Case | HTTP | Today (measured by reading code) | Target |
|---|---|---|---|---|
| 1 | Bad or disabled key | 401 | Polish: "AI failed" capsule. Ask: raw `Ask request failed (401): ...`. Settings test: raw `HTTP 401 ...`. | Message names the key and where to fix it |
| 2 | No credit | 402 | Same generic messages | Message says credit is exhausted and links to the OpenRouter credits page |
| 3 | Unknown model | 400 (`... is not a valid model ID`), sometimes 404 | Same generic messages | Message names the model and points to the model list |
| 4 | Rate limited | 429 | Same generic messages, no retry | One retry honouring a short `Retry-After`, then a rate-limit message |
| extra | Model down / no provider | 502 / 503 | Same generic messages (5xx is retried) | Clear "model unavailable" message |
| extra | Error mid-stream (HTTP 200 + `error` event) | 200 | Ignored; polish may return empty text | Reported as an error |

KR2 counts cases 1 to 4.

## Windows run checklist (KR1, owner)

Record each result in `claude/memory/goal-progress.md`. Steps 2 to 4 are the three KR1 steps.

1. Install the 1.1.61 baseline if the machine doesn't have it, then install the new build over it. Confirm settings
   and the OpenRouter key survived. Note the SmartScreen warning: the new build is unsigned.
2. Key entry: paste an OpenRouter key in Settings and save (one key is shared by STT and polish).
3. Connection test: press Test and note the latency or the message.
4. Dictation with polish: dictate one sentence and check the polished text lands in the target app.
5. Ask: ask one question and check the answer.
6. Error cases: bad key (change one character), unknown model (`foo/bar`), no credit (a zero-credit key, if you
   have one). Note the message shown for each. Rate limit is covered by unit tests only.

Baseline result, 2026-11-10: **0 of 3**, not yet run on Windows.
