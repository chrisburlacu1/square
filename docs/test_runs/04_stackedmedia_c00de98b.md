# Run 04 — `StackedMedia` (`c00de98b-69ad-4cc8-a576-0a873dd1748b`)

- **Date:** 2026-04-19
- **Project:** `StackedMedia` (`~/projects/android/StackedMedia`) — Native Android 14+ (Kotlin, Jetpack Compose, Jetpack Glance, `MediaSessionManager`) Pixel-style home screen media player widget
- **Session Size:** `95` conversational turns (`step` / turn indices `0..251`), `base1.md` = `198,710` chars, pre-existing `GEMINI.md` = `13,072` chars
- **With Triage Case:** [`manual_12be1cad6a87f97b06f0_8a55bc12`](~/.square/projects/StackedMedia-26c6cfbe/cases/manual_12be1cad6a87f97b06f0_8a55bc12/REPORT.md) (`16` windows, `2` consolidated episodes `ep1`–`ep2`, routed **only to `INV`**)
- **Without Triage Case (`--no-triage`):** [`manual_12be1cad6a87f97b06f0_a2cca708`](~/.square/projects/StackedMedia-26c6cfbe/cases/manual_12be1cad6a87f97b06f0_a2cca708/REPORT.md) (ran both `INV` and `DOM`)

---

## Executive Summary

- **First session where `Without Triage` (`a2cca708`) clearly beat `With Triage` (`8a55bc12`) on overall recall — because `gdm` Triage gated off `DOM` (`Verdict: PROPOSE (INV)`):**
  - During the late session (`T190..251`, windows `w11..w15`), there were **zero tool errors**, so the interaction looked smooth on the surface, but two real domain/UX regressions happened:
    1. **`T222–241` (Closed-app widget launch regression):** The user reported that tapping the widget no longer opened a closed Spotify app (`T222`). At `T241`, the agent traced this to an Android 14+ / Jetpack Glance boundary: using `actionRunCallback` to start an activity from a BroadcastReceiver hits Android 14+ background activity launch (BAL) restrictions, and cached `controller.sessionActivity` `PendingIntent`s go stale when the player closes (requiring `actionStartActivity(launchIntent)` or a live `MediaController` check + package-launch fallback).
    2. **`T190, T221, T242–251` (Settings screen copy & header compactness):** The user pushed back on verbose feature-inventory cards on the settings screen (`T190`) and excessive top whitespace caused by `LargeTopAppBar` (`T242`).
  - In `gdm` Triage (`8a55bc12`), windows `w13` (`T219..229`) and `w14` (`T227..243`) scored `Intent/Domain (DOM) = 0.55` and `0.46` — elevated, but **below the `0.65` trigger threshold** (and `macro_missing_domain_mental_model` was `0.23`, likely dampened because `GEMINI.md` already had `13,072` chars of architecture docs mentioning `launchActiveSession`).
  - Because `triage.recommended_dimensions` was `["INV"]`, **`With Triage` skipped `dom1` completely** — missing `.agents/skills/media-widget-interactions/SKILL.md` and the `GEMINI.md` `## Product UI Invariants` rules that `Without Triage` (`a2cca708`) extracted cleanly!
- **On `INV` (`inv1` vs. `inv1`), both runs found the exact same 3 clusters — even the ones outside `ep1` and `ep2`:**
  - `gdm` Triage only highlighted `ep1` (`T30..74`, git push denial + whole-file write cleanup) and `ep2` (`T156..189`, Gradle daemon failure).
  - Yet `inv1` in `With Triage` (`8a55bc12`) still grepped `^[USER|ASSISTANT|ACTION|OBSERVATION ERROR]` across `base1.md` and found `T7/14` (missing path guesses), `T59/84` (blank write observations), `T173–177` (Gradle daemon retry loop), **and** `T222/242` (post-build interactive/layout regressions), producing `GEMINI.md` (`## Editing procedure`), `recover-command-failure/SKILL.md`, and `verify-interactive-change/SKILL.md`.
  - `inv1` in `Without Triage` (`a2cca708`) found the exact same events (`T7/14/80`, `T59/84`, `T173–177`, `T190`, `T222/241`, `T242`) and packaged them into `GEMINI.md` (`## Working Procedure`) + a unified `change-existing-software/SKILL.md`.

---

## Timing & Token / Tool Usage Metrics

| Metric | With Triage (`8a55bc12`) | Without Triage (`a2cca708`) | Delta (`Without` vs `With`) |
| :--- | :---: | :---: | :---: |
| **`gdm` Triage Step (`16` windows, `134` Qs)** | `1.46s` API / `$0.0068` | `0s` (skipped) | `-1.46s` API |
| **`inv1` Wall Time & Tool Calls** | `124.6s` (`12` tools) | `122.6s` (`11` tools) | `-2.0s` (`-1` tool) |
| **`inv1` Input Tokens (Total / Cached / Uncached)** | `400,890` (`354,560` / **`46,330`**) | `515,418` (`469,632` / **`45,786`**) | `-1.2%` uncached (`-544`) |
| **`inv1` Output Tokens (Total / Reasoning)** | `3,807` (`432` reasoning) | `4,036` (`484` reasoning) | `+229` output (`+52` reasoning) |
| **`dom1` Wall Time & Tool Calls** | **Skipped by Triage (`0s`)** | `92.2s` (`14` tools) | `+92.2s` (parallel) / `+14` tools |
| **`dom1` Input Tokens (Total / Cached / Uncached)** | `0` | `369,995` (`330,240` / **`39,755`**) | `+39,755` uncached |
| **`dom1` Output Tokens (Total / Reasoning)** | `0` | `2,969` (`233` reasoning) | `+2,969` output (`+233` reasoning) |
| **Combined Proposer Wall Time (parallel max)** | `124.6s` | **`122.6s`** (`max(122.6s, 92.2s)`) | **`-2.0s` (no wall-time penalty for running `dom1` in parallel!)** |
| **Combined Proposer Tool Calls (`inv1` + `dom1`)** | **`12` tool calls** (`inv1` only) | **`25` tool calls** (`11` + `14`) | `+13` tool calls |
| **Combined Proposer Uncached Input Tokens** | **`46,330`** (`400,890` total) | **`85,541`** (`885,413` total) | **`+39,211` uncached (`+84.6%` because `dom1` ran)** |
| **Combined Proposer Output Tokens** | **`3,807`** (`432` reasoning) | **`7,005`** (`717` reasoning) | `+3,198` output (`+285` reasoning) |

---

## Side-by-Side Proposal Comparison

### 1. `INV` (Harness-Level Invariant) Proposals

| Aspect | With Triage (`8a55bc12`) | Without Triage (`a2cca708`) |
| :--- | :--- | :--- |
| **`GEMINI.md` Procedural Rules (`C1`)** | `## Editing procedure` (`2` bullets):<br>- Locate existing path/symbol before guessing filenames (`T7, T14`); read missing range if truncated.<br>- Use focused patches instead of whole-file rewrites for comment cleanup (`T59, T84`); inspect diff after blank write responses. | `## Working Procedure` (`3` bullets):<br>- Discover paths after missing-file error (`T7, T14, T80`).<br>- Read complete affected region and patch spans instead of reconstructing whole files (`T59, T84, T90–106`).<br>- Classify tool failures and bound retries (`T173, T175, T177`). |
| **Workflow Skills (`C6`)** | **2 focused skills:**<br>1. `.agents/skills/recover-command-failure/SKILL.md`: Classify bad input, permission denial (`T55` git commit user redirect), service/daemon startup failure (`T173–177` Gradle daemon), and background task timeouts.<br>2. `.agents/skills/verify-interactive-change/SKILL.md`: Trace entry point + fallback for external-app launches (`T222` closed Spotify) and inspect viewport/top spacing for layout edits (`T242` whitespace). | **1 consolidated skill:**<br>1. `.agents/skills/change-existing-software/SKILL.md`: Covers review-only scope vs implementation, resolving material UX choices upfront (`T190` settings copy, `T242` compact vs spacious layout), preserving fallback behavior across execution contexts (`T162/189, T222, T241` closed player launch), and verifying at the runtime boundary. |

### 2. `DOM` (Project-Specific Domain) Proposals

| Aspect | With Triage (`8a55bc12`) | Without Triage (`a2cca708`) |
| :--- | :--- | :--- |
| **`GEMINI.md` Rules (`C1`)** | *(Skipped — `gdm` did not route to `DOM`)* | Added `## Product UI Invariants`:<br>- Settings/config screens use concise, action-focused copy (`T190, T221`).<br>- Prefer compact `TopAppBar` over `LargeTopAppBar` on utility screens (`T242–251`). |
| **Domain Skill (`C2`)** | *(Skipped — `gdm` did not route to `DOM`)* | Added `.agents/skills/media-widget-interactions/SKILL.md` (`name: media-widget-interactions`):<br>- Distinguishes opening the music app (`actionStartActivity(launchIntent)`) from receiver `actionRunCallback` (blocked by Android 14+ background activity launch restrictions, `T222–241`).<br>- Distinguishes cached metadata (`sessionActivity` `PendingIntent` may be stale when closed) from a live `MediaController`, requiring a package-launch fallback (`T241`).<br>- Preserves parent widget launch vs nested transport button taps across `StackedMediaWidget.kt`, `WidgetActionCallbacks.kt`, `MediaSessionRepository.kt`, and `MainActivity.kt`. |

---

## 6-Point Rubric Breakdown (`square-output-review`)

| Criterion | With Triage (`8a55bc12`) | Without Triage (`a2cca708`) | Winner & Notes |
| :--- | :---: | :---: | :--- |
| **1. Evidence Grounding & Turn Citations** | **Strong on `INV`** (`T7, T14, T55, T59, T84, T90, T106, T173–177, T182, T222, T242`) | **Strong on both `INV` & `DOM`** (`T7, T14, T17, T59, T80, T84, T90–106, T162–190, T221–251`) | **Without Triage (`a2cca708`)** — Covered both dimensions thoroughly. |
| **2. `INV` vs `DOM` Boundary** | **Clean** | **Clean** | **Tie** — Neither leaked repo-specific Android package names into `INV`. |
| **3. Structural Packaging (`C1`–`C7`)** | **Pass** (`name:` + `description:` present in both `INV` skills; preserved 13KB `GEMINI.md`) | **Pass** (`name:` + `description:` present in both `INV` and `DOM` skills; preserved 13KB `GEMINI.md`) | **Tie** |
| **4. Generality & Overfitting Check** | **Pass** | **Pass** | **Tie** — `media-widget-interactions` is genuinely reusable for future widget work, not a retrospective changelog. |
| **5. Triage-to-Proposal Alignment** | **False Negative in Triage `DOM` Routing** (`w13=0.55`, `w14=0.46` missed the `0.65` cutoff, suppressing `dom1`) | **Full Recall** (`dom1` ran unconditionally and captured `T190, T222–241, T242–251`) | **Without Triage (`a2cca708`)** — Triage hard-gating `DOM` dropped the most valuable domain skill in the session. |
| **6. Net Signal-to-Noise** | **7.5 / 10** (Great `INV`, `0` `DOM`) | **9.5 / 10** (Great `INV` + Great `DOM`) | **Without Triage (`a2cca708`)** |

