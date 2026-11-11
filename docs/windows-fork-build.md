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
- Error messages (KR2): implemented and tested, see the KR2 section. Windows build workflow (KR4): written, not yet run; see "Building the installer".

## OpenRouter error cases (KR2)

Case list fixed 2026-11-10 (applies to LLM polish, Ask, the connection tests and STT). Status codes verified
against the OpenRouter docs; the unknown-model body was also confirmed with one live call.

Implemented 2026-11-11 (uncommitted at the time of writing): `src-tauri/src/llm/http_error.rs` classifies a failure
from the HTTP status and the provider's `error.message`. The Rust side sends a stable code; the frontend turns it
into text (`src/lib/llmError.ts`, `errors.*` and `capsule.errors.*` in all 10 locales).

| # | Case | HTTP | Code (LLM / STT) | What the user sees |
|---|---|---|---|---|
| 1 | Bad or disabled key | 401 | `llm_invalid_key` / `stt_invalid_key` | Capsule "Check AI key", plus a toast: the provider rejected the key, replace it in AI settings |
| 2 | No credit | 402 (also OpenAI-style `insufficient_quota`) | `llm_no_credit` / `stt_no_credit` | "AI: add credit", plus a toast pointing to openrouter.ai/settings/credits |
| 3 | Unknown model | 400 "not a valid model ID", 404 | `llm_unknown_model` / `stt_unknown_model` | "Unknown AI model", plus a toast: choose a model from the list |
| 4 | Rate limited | 429 | `llm_rate_limited` / `stt_rate_limited` | One automatic retry for polish when `Retry-After` is 5 s or less, then "AI rate limited" |
| extra | Model down / no provider | 502 / 503 | `llm_model_unavailable` | "AI model down" |
| extra | Moderation block | 403 with moderation wording | `llm_moderated` | "AI blocked it" |
| extra | Error mid-stream (HTTP 200 plus `error` event) | 200 | same codes via the error's own `code` | Reported as the matching failure; previously ignored and could return empty text |

Where each surface gets it:

- Dictation polish: `pipeline:error` carries the code; the capsule shows the short label and a toast shows the guidance.
- Ask: the message arrives as `[llm_no_credit] <provider message>` and `AskPanel` shows the translated text.
- Settings and Onboarding "Test" buttons: same coded string, shown as the translated text. Onboarding now shows the reason, not just "failed".
- Speech-to-text (OpenRouter and other providers): `AppError::to_user_error` maps the same cases to `stt_*` codes.

Not changed: Ask does not retry on 429 (one user-triggered request); STT does not retry on 429. Unclassified failures
keep their previous wording. These cases are covered by Rust and Vitest tests; they have not yet been checked in the
running Windows app (see the checklist below).

## Building the installer (KR4)

Workflow: `.github/workflows/windows-build.yml` ("Windows build (unsigned, fork)"), written 2026-11-11 and
**not yet run**. It runs `tauri build --bundles nsis` on `windows-latest` with the override
`src-tauri/tauri.fork.conf.json`, then uploads the installer as the artifact `opentypeless-windows-installer`
(kept 30 days) with its SHA-256 in the run summary. It uses no secrets and publishes nothing.

How to start a build:

1. After this file is on the fork's default branch: Actions > "Windows build (unsigned, fork)" > Run workflow,
   choosing the branch. GitHub only lists the button once the file exists on the default branch.
2. Or without merging: push a tag named `fork-build-<anything>` on the commit to build. Pushing a tag needs the
   owner's approval each time.

What the build changes compared with upstream's release:

- Unsigned: no Windows certificate is used, so SmartScreen warns on first run. Signing stays out of scope.
- The updater is off (`createUpdaterArtifacts: false`) and its endpoint points at this fork's releases, where no
  `latest.json` exists. The app's update check (`src/components/UpdatePrompt.tsx`) catches the failed request and
  only logs a warning, so users see nothing. The bundled public key is still upstream's, which is harmless without
  updater artifacts.
- File name: `OpenTypeless_<version>-openrouter_x64-setup.exe`, so it cannot be confused with the 1.1.61 baseline.
  The version comes from `package.json` (1.1.64 today), not from the installer's own file name.

Not verified until the first run: that the `--config` override merges as intended (Tauri merges it as a JSON merge
patch, so the endpoint list is replaced), that exactly one NSIS installer is produced, and the real build time.
`actions/upload-artifact` is pinned to the `v4` tag rather than a commit SHA because no SHA could be verified
offline; CI's other actions use SHAs. Pin it before relying on this beyond the fork.

Do not include this workflow or `tauri.fork.conf.json` in a pull request to `tover0314-w/opentypeless`.

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
