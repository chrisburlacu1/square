# Test Run 01 — `Stash` (`0e4cbcc6-7214-4360-b1c1-dffab3f75b95`)

* **Repository:** `~/projects/android/Stash` (Android / Kotlin / Jetpack Compose / Room FTS5 / LiteRT-LM `EmbeddingGemma 2`)
* **Session Length:** `505` normalized turns
* **Session Summary:** Integrated on-device `EmbeddingGemma 2` semantic search via LiteRT-LM (`0.18.0` $\rightarrow$ `0.18.1`), hit multiple `javap` / `.gradle/caches` AAR inspection loops, went through 3 UX/relevance rework cycles on `FeedSearch.kt` and `RoomStashRepository.kt`, diagnosed a `1024` vs `8192` static TFLite signature limit in `.litertlm`, fixed blurry thumbnails caused by shared path-keyed `ImageBitmapCache` entries, and replaced hardcoded `.dp` corner radii with `MaterialTheme.shapes`.

---

## Part A: Post-Fix Comparison (Full 505-Turn `base1.md`)

* **With Triage Case:** [`manual_c6535a2a19485d950acb_a356ca7f/REPORT.md`](~/.square/projects/Stash-23790e7e/cases/manual_c6535a2a19485d950acb_a356ca7f/REPORT.md)
* **Without Triage Case:** [`manual_c6535a2a19485d950acb_a665b752/REPORT.md`](~/.square/projects/Stash-23790e7e/cases/manual_c6535a2a19485d950acb_a665b752/REPORT.md)

### 1. Timing & Token Usage (`a356ca7f` vs. `a665b752`)

| Metric | With Triage (`a356ca7f`) | Without Triage (`a665b752`) | Delta (With vs. Without) |
| :--- | :---: | :---: | :---: |
| **`gdm` Triage Latency / Cost** | `3.76s` API (`14.9s` w/ windowing) / `$0.0126` | `0s` / `$0.00` | `+14.9s` / `+$0.0126` |
| **`inv1` Elapsed (`wall_s`)** | `172.3s` (1 attempt) | `164.6s` (1 attempt) | `+7.7s` (`+4.7%`) |
| **`dom1` Elapsed (`wall_s`)** | `119.0s` (1 attempt) | `118.4s` (1 attempt) | `+0.6s` (`+0.5%`) |
| **Total End-to-End Wall Clock** | **`197.3s` (~3m 17s)** | **`173.9s` (~2m 54s)** | `+23.4s` (`+13.5%`) |
| **`inv1` Tool Calls** | `14` | `11` | `+3` |
| **`dom1` Tool Calls** | `11` | `9` | `+2` |
| **`inv1` Input Tokens (Cached / Uncached)** | `479,384` (`434,176` / **`45,208`**) | `422,802` (`379,392` / **`43,410`**) | `+1,798` uncached |
| **`dom1` Input Tokens (Cached / Uncached)** | `427,924` (`384,896` / **`43,028`**) | `431,535` (`386,048` / **`45,487`**) | **`-2,459` uncached** |
| **Total Uncached Input Tokens (`INV`+`DOM`)** | **`88,236`** (`90.3%` cache hit) | **`88,897`** (`89.6%` cache hit) | **`-661` uncached (`-0.7%`)** |
| **`inv1` Output Tokens (Reasoning)** | `6,213` (`715` reasoning) | `6,034` (`605` reasoning) | `+179` (`+110` reasoning) |
| **`dom1` Output Tokens (Reasoning)** | `3,472` (**`278` reasoning**) | `3,211` (**`575` reasoning**) | `+261` (**`-297` reasoning [`-51.7%`]**) |
| **Total Output Tokens (Reasoning)** | **`9,685` (`993` reasoning)** | **`9,245` (`1,180` reasoning)** | `+440` (**`-187` reasoning [`-15.8%`]**) |

### 2. Proposed Components & Rubric Evaluation (`a356ca7f` vs. `a665b752`)

| Dimension / Check | With Triage (`a356ca7f`) | Without Triage (`a665b752`) | Notes |
| :--- | :--- | :--- | :--- |
| **`INV` Skill 1 (UX / Spec Alignment)** | `.agents/skills/align-feature-change/SKILL.md` | `.agents/skills/feature-alignment/SKILL.md` | Both capture concrete positive/negative retrieval & UI sketches before coding. |
| **`INV` Skill 2 + Script (JVM API Inspection)** | `.agents/skills/inspect-installed-api/SKILL.md` + `scripts/inspect_jvm_artifact.py` | `.agents/skills/runtime-api-investigation/SKILL.md` + `scripts/inspect_jvm_artifact.py` | Both bundle a clean, parameterized `javap` / `.aar` inspection CLI script (`C7`) and runtime error classification workflow. |
| **`INV` Always-On (`GEMINI.md`)** | `## Working Procedure` (3 bullets: edit retry, history recovery, build vs runtime verification) | `## Editing Procedure` (1 bullet: edit retry & diff inspection) | `a356ca7f` included a bullet triggered by `.system_generated/logs/transcript` reads at Turns 446–454 (subsequently filtered out in `slicer.py`). |
| **`DOM` Always-On (`GEMINI.md`)** | 1. **Theme contracts across screens** (`MaterialTheme.shapes`, `colorScheme`, `typography`, `motionScheme`)<br>2. **Shared image-cache contract** (`ImageBitmapCache.kt` path-keyed LRU) | 1. **Theme contract across Compose UI** (`MaterialTheme.shapes`, `colorScheme`, `typography`, `motionScheme`)<br>2. **Shared image quality contract** (`ImageBitmapCache` path-keyed LRU) | **100% convergence** on both repo-wide `GEMINI.md` rules once turns 250–505 were visible in `base1.md`. |
| **`DOM` Skill (Search & Embedding Contract)** | `.agents/skills/stash-search-contracts/SKILL.md` (separates `StashEntity.content` vs Nano metadata, FTS5 possessive `'s` bug, `1024` vs `8192` signature mismatch, highlight explanations) | `.agents/skills/semantic-search-contract/SKILL.md` (6-row query evaluation table, `maxInputLength` `1024` vs `8192` signature selection, vector normalization) | Both pass the Anti-Retrospective test and capture the core retrieval + LiteRT-LM signature invariants. |

---

## Part B: Pre-Fix Comparison (Truncated `base1.md` @ Turn ~250)

* **With Triage Case:** [`manual_c6535a2a19485d950acb_0eb99080/REPORT.md`](~/.square/projects/Stash-23790e7e/cases/manual_c6535a2a19485d950acb_0eb99080/REPORT.md)
* **Without Triage Case:** [`manual_c6535a2a19485d950acb_4d07b134/REPORT.md`](~/.square/projects/Stash-23790e7e/cases/manual_c6535a2a19485d950acb_4d07b134/REPORT.md)

| Metric / Outcome | With Triage (`0eb99080`) | Without Triage (`4d07b134`) | Why It Happened |
| :--- | :--- | :--- | :--- |
| **Max Proposer Wall Time** | `145.4s` (`inv1=145.4s`, `dom1=94.5s`) | `100.8s` (`inv1=100.8s`, `dom1=95.7s`) | `4d07b134` finished faster because it missed the `inspect_jvm_artifact.py` script. |
| **Uncached Input Tokens** | **`84,170`** (`797,770` total) | `106,409` (`574,761` total) | Without triage spent `+22.2k` more uncached input tokens searching the noisy 400KB `base1.md`. |
| **`INV` Outcome** | Proposed `align-feature-behavior/SKILL.md` **and** `scripts/inspect_jvm_artifact.py`. | Proposed `feature-alignment/SKILL.md` + generic `GEMINI.md` edit-retry bullets; **missed `inspect_jvm_artifact.py`**. | When `base1.md` was noisy and truncated, `gdm`'s `automatable_manual_work (0.89)` spotlight was what enabled `INV` to spot the `javap` script opportunity. |
| **`DOM` Outcome** | Proposed forward-looking `stash-search-quality/SKILL.md`, but missed `MaterialTheme.shapes` and `ImageBitmapCache`. | Proposed `stash-semantic-search/SKILL.md` (with retrospective `0.18.0` snippet), and missed `MaterialTheme.shapes` and `ImageBitmapCache`. | `base1.md` ended at line 6,561 (`…(+375483 chars — render truncation)`), hiding Turns 250–505 from both proposers. |

---

## Part C: Lesser-Model Comparison (GPT 6 Luna, Full 505-Turn `base1.md`)

* **With Triage Case:** [`manual_c6535a2a19485d950acb_3a455821/REPORT.md`](~/.square/projects/Stash-23790e7e/cases/manual_c6535a2a19485d950acb_3a455821/REPORT.md) (`gdm` latency `3.32s`, `$0.0126`, `294` questions / `36` windows, `PROPOSE (INV, DOM)`)
* **Without Triage Case:** [`manual_c6535a2a19485d950acb_5f39be27/REPORT.md`](~/.square/projects/Stash-23790e7e/cases/manual_c6535a2a19485d950acb_5f39be27/REPORT.md)

Unlike GPT 6.1 Sol (`a356ca7f` vs `a665b752`), where both runs converged on the same 6 components, **removing triage on GPT 6 Luna caused clear regressions across both `INV` and `DOM`:**

### 1. Timing & Token Usage (`3a455821` vs. `5f39be27`)

| Metric | With Triage (`3a455821`) | Without Triage (`5f39be27`) | Delta (With vs. Without) |
| :--- | :---: | :---: | :---: |
| **`gdm` Triage Latency / Cost** | `3.32s` API / `$0.0126` | `0s` / `$0.00` | `+3.32s` / `+$0.0126` |
| **`inv1` Elapsed (`wall_s`)** | `88.0s` (1 attempt) | `65.7s` (1 attempt) | `+22.3s` (`+33.9%`) |
| **`dom1` Elapsed (`wall_s`)** | `98.1s` (1 attempt) | `62.3s` (1 attempt) | `+35.8s` (`+57.5%`) |
| **Max Proposer Wall (`INV` / `DOM`)** | **`98.1s`** | **`65.7s`** | `+32.4s` (`+49.3%`) |
| **`inv1` Tool Calls** | `7` | `8` | `-1` |
| **`dom1` Tool Calls** | `10` | `8` | `+2` |
| **`inv1` Input Tokens (Cached / Uncached)** | `283,227` (`244,480` / **`38,747`**) | `239,578` (`200,576` / **`39,002`**) | `-255` uncached |
| **`dom1` Input Tokens (Cached / Uncached)** | `303,172` (`276,608` / **`26,564`**) | `330,908` (`295,296` / **`35,612`**) | **`-9,048` uncached** |
| **Total Uncached Input Tokens (`INV`+`DOM`)** | **`65,311`** (`88.9%` cache hit) | **`74,614`** (`86.9%` cache hit) | **`-9,303` uncached (`-12.5%`)** |
| **`inv1` Output Tokens (Reasoning)** | `4,057` (`769` reasoning) | `2,795` (`657` reasoning) | `+1,262` (`+112` reasoning) |
| **`dom1` Output Tokens (Reasoning)** | `4,465` (`1,569` reasoning) | `2,898` (`677` reasoning) | `+1,567` (`+892` reasoning) |
| **Total Output Tokens (Reasoning)** | **`8,522` (`2,338` reasoning)** | **`5,693` (`1,334` reasoning)** | `+2,829` (`+1,004` reasoning) |

### 2. Proposed Components & Rubric Evaluation (`3a455821` vs. `5f39be27`)

| Dimension / Check | With Triage (`3a455821`) | Without Triage (`5f39be27`) | Rubric Verdict |
| :--- | :--- | :--- | :--- |
| **`INV` Skill 1 (Alignment)** | `.agents/skills/shift_left_spec/SKILL.md` (general upfront scope, UX & acceptance alignment) | `.agents/skills/ui-implementation-alignment/SKILL.md` (narrowed to UI list/card layout, truncation, & tokens) | **With Triage wins (Check 4 Abstraction):** `3a455821` stayed general; `5f39be27` overfit to UI cards. |
| **`INV` Component 2 (JVM API Inspection)** | `scripts/inspect_aar_api.py` (`C7` CLI: extracts `classes.jar` from AAR, runs `javap`, `--private`, `--timeout`, structured stderr) | `.agents/skills/external-api-verification/SKILL.md` (prose-only advice to "inspect the resolved artifact") | **With Triage wins (Check 5 Lever Fit):** `gdm`'s `automatable_manual_work` (`0.79–0.89`) + `script_c7` drove Luna to build the `C7` script; without triage it fell back to prose. |
| **`DOM` Always-On (`GEMINI.md`)** | Added **Material 3 consistency** rule (`MaterialTheme` shape, typography, color, spacing) | **Missed completely** | **With Triage wins (Check 2 Orthogonal Coverage):** Without triage, Luna stopped after one `DOM` skill. |
| **`DOM` Skill (Semantic Search)** | `.agents/skills/semantic-search/SKILL.md` (`StashEntity.content` vs taxonomy, pos/neg/no-match set, cutoffs, summary presentation) | `.agents/skills/semantic-search/SKILL.md` (vector vs FTS5 vs no-match empirical calibration, asymmetric formatting) | **Tie (Check 3 Anti-Retrospective):** Both avoided recapping completed code; neither Luna run caught the `ImageBitmapCache` LRU rule that Sol found. |

*(Minor note: `3a455821`'s `inv1` outcome notes contained a minor template-echo glitch at the top, though its proposed file diffs were clean.)*

**Takeaway:** Triage acts as a **capability multiplier** for smaller/lesser models. A frontier model (GPT 6.1 Sol) had enough long-context attention to find the `C7` script, general alignment principle, and `GEMINI.md` theme rule without spotlights; GPT 6 Luna needed `gdm`'s episode spotlights to hit the same structural bar.


