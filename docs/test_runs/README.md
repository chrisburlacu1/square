# Square Test Runs — Triage vs. No-Triage Benchmark Log

This directory records side-by-side evaluations of `square analyze` **with `gemini-decision-1` (`gdm`) Triage** vs. **without Triage (`--no-triage`)** across real multi-turn coding sessions, graded against the 6-point rubric in [`.agents/skills/square-output-review/SKILL.md`](../../.agents/skills/square-output-review/SKILL.md).

---

## 1. Cross-Session Summary Scoreboard

| # | Repo & Session | Turns | Condition | Case ID & Report | `gdm` Latency / Cost | Max Proposer Wall (`INV` / `DOM`) | Tool Calls (`INV`+`DOM`) | Uncached Input Tokens | Output Tokens (Reasoning) | Rubric Verdict & Key Takeaway |
| :---: | :--- | :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **1a** | `Stash`<br>`0e4cbcc6` *(Truncated `base1.md` @ T250)* | 505 | **With Triage** | [`0eb99080`](~/.square/projects/Stash-23790e7e/cases/manual_c6535a2a19485d950acb_0eb99080/REPORT.md) | `3.06s` / `$0.0126` | `145.4s` (`145.4s` / `94.5s`) | `27` (`12`+`15`) | `84,170` | `7,795` (`593`) | **Pass on `INV` (`C5`+`C7` script), partial on `DOM`** (turns 250–505 truncated in `base1.md`). |
| **1b** | `Stash`<br>`0e4cbcc6` *(Truncated `base1.md` @ T250)* | 505 | **No Triage** | [`4d07b134`](~/.square/projects/Stash-23790e7e/cases/manual_c6535a2a19485d950acb_4d07b134/REPORT.md) | — | `100.8s` (`100.8s` / `95.7s`) | `17` (`9`+`8`) | `106,409` | `5,619` (`519`) | **Missed `inspect_jvm_artifact.py` (`C7`)**; wrote generic `edit_file` retry prose and retrospective `0.18.0` snippet. |
| **1c** | `Stash`<br>`0e4cbcc6` *(Full `base1.md` T0..505)* | 505 | **With Triage** | [`a356ca7f`](~/.square/projects/Stash-23790e7e/cases/manual_c6535a2a19485d950acb_a356ca7f/REPORT.md) | `3.76s` / `$0.0126` | `172.3s` (`172.3s` / `119.0s`) | `25` (`14`+`11`) | **`88,236`** | `9,685` (**`993`**) | **Full Pass:** Caught all 3 `INV` + 3 `DOM` clusters (`MaterialTheme.shapes`, `ImageBitmapCache`, search contracts, `inspect_jvm_artifact.py`). |
| **1d** | `Stash`<br>`0e4cbcc6` *(Full `base1.md` T0..505)* | 505 | **No Triage** | [`a665b752`](~/.square/projects/Stash-23790e7e/cases/manual_c6535a2a19485d950acb_a665b752/REPORT.md) | — | `164.6s` (`164.6s` / `118.4s`) | `20` (`11`+`9`) | `88,897` | `9,245` (`1,180`) | **Full Pass (~90% converged with 1c):** Caught same 6 components once `base1.md` truncation was fixed (minor: omitted `name:` in `INV` skill frontmatter). |
| **1e** | `Stash`<br>`0e4cbcc6` *(GPT 6 Luna, Full `base1.md`)* | 505 | **With Triage** | [`3a455821`](~/.square/projects/Stash-23790e7e/cases/manual_c6535a2a19485d950acb_3a455821/REPORT.md) | `3.32s` / `$0.0126` | `98.1s` (`88.0s` / `98.1s`) | `17` (`7`+`10`) | **`65,311`** | `8,522` (`2,338`) | **Clear Win for With Triage (`-12.5%` uncached tokens):** Produced `scripts/inspect_aar_api.py` (`C7`), general `shift_left_spec` (`C5`), `semantic-search` (`C5`), and `GEMINI.md` Material 3 rule (missed `ImageBitmapCache`). |
| **1f** | `Stash`<br>`0e4cbcc6` *(GPT 6 Luna, Full `base1.md`)* | 505 | **No Triage** | [`5f39be27`](~/.square/projects/Stash-23790e7e/cases/manual_c6535a2a19485d950acb_5f39be27/REPORT.md) | — | `65.7s` (`65.7s` / `62.3s`) | `16` (`8`+`8`) | `74,614` | `5,693` (`1,334`) | **Regressed without Triage:** Missed `C7` script (wrote prose `external-api-verification`), overfit alignment to UI cards (`ui-implementation-alignment`), and dropped `GEMINI.md` Material 3 rule. |
| **2a** | `structure.ai`<br>`882e5095` | 97 | **With Triage** | [`33cc26a8`](~/.square/projects/structure.ai-406dc38d/cases/manual_247f51f45b671134a137_33cc26a8/REPORT.md) | `1.19s` / `$0.0046` | `129.5s` (`104.1s` / `129.5s`) | **`18` (`8`+`10`)** | **`74,917`** | `7,627` (**`485`**) | **Edge to With Triage:** `-10%` uncached tokens, `-30%` reasoning tokens; cleanly split `screenplay-ux-contract` & `screenplay-pdf-contract` and caught `NIGHT` stripping bug + `sceneId: null`. |
| **2b** | `structure.ai`<br>`882e5095` | 97 | **No Triage** | [`c6f62505`](~/.square/projects/structure.ai-406dc38d/cases/manual_247f51f45b671134a137_c6f62505/REPORT.md) | — | `113.7s` (`100.8s` / `113.7s`) | `21` (`12`+`9`) | `83,154` | `6,407` (`697`) | **Strong Pass:** Caught same core clusters, but merged UX + PDF parsing into one skill, missed `NIGHT` regex trap, and put tool-failure recovery into always-on `GEMINI.md` instead of a skill. |
| **3a** | `Hoster`<br>`59e731ca` | 349 | **With Triage** | [`772f2624`](~/.square/projects/Hoster-92b8f71c/cases/manual_1d8e8b4d901bf14b3307_772f2624/REPORT.md) | `3.39s` / `$0.0125` | **`162.4s`** (`162.4s` / `88.2s`) | **`20` (`10`+`10`)** | **`84,383`** | **`8,301`** (`1,462`) | **Clear Win for With Triage:** Passed `HT.validate()` on 1st try; caught both `DOM` clusters (`GEMINI.md` branding/hierarchy rules + `hoster-thumbnails` geometry skill) + `raster_variants.py` (`C7`). |
| **3b** | `Hoster`<br>`59e731ca` | 349 | **No Triage** | [`4b5cd1a4`](~/.square/projects/Hoster-92b8f71c/cases/manual_1d8e8b4d901bf14b3307_4b5cd1a4/REPORT.md) | — | `207.7s` (`207.7s`* / `54.6s`) | `25` (`18`*+`7`) | `99,947` | `9,172` (`1,042`) | **`inv1` failed `a1` validation** (`+56.4s` retry, `+18.4%` uncached tokens), omitted `name:` in both `INV` skills, and `DOM` missed the WebView thumbnail aspect-ratio contract (`T288`). Did find `cdp_layout_snapshot.py` (`T585`). |
| **4a** | `StackedMedia`<br>`c00de98b` | 95 (`251`) | **With Triage** | [`8a55bc12`](~/.square/projects/StackedMedia-26c6cfbe/cases/manual_12be1cad6a87f97b06f0_8a55bc12/REPORT.md) | `1.46s` / `$0.0068` | `124.6s` (`124.6s` / **skipped**) | **`12` (`12`+`0`)** | **`46,330`** | `3,807` (`432`) | **Great `INV`, Missed `DOM` (False Negative in Triage Routing):** `w13` (`0.55`) & `w14` (`0.46`) scored below `0.65` on `DOM`, so Triage routed to `INV` only and skipped `dom1` (`-46%` tokens, but missed `media-widget-interactions`). |
| **4b** | `StackedMedia`<br>`c00de98b` | 95 (`251`) | **No Triage** | [`a2cca708`](~/.square/projects/StackedMedia-26c6cfbe/cases/manual_12be1cad6a87f97b06f0_a2cca708/REPORT.md) | — | **`122.6s`** (`122.6s` / `92.2s`) | `25` (`11`+`14`) | `85,541` | `7,005` (`717`) | **Clear Win for No Triage:** Running `dom1` in parallel (`0s` wall-time penalty) captured `.agents/skills/media-widget-interactions/SKILL.md` (Android 14+ Glance activity-launch & stale `sessionActivity` contract, `T222–241`) + `GEMINI.md` compactness rules (`T190, T242`). |

*\*In `3b` (`4b5cd1a4`), `inv1.a1` (`151.3s`, `10` tools) failed `HT.validate()` due to an ambiguous script path reference (`scripts/cdp_layout_snapshot.py`), requiring `inv1.a2` (`56.4s`, `8` tools).*

---

## 2. Detailed Session Writeups

1. [**Run 01 — `Stash` (`0e4cbcc6`, 505 turns)**](01_stash_0e4cbcc6.md): Android Kotlin / Compose / Room FTS5 / LiteRT-LM (`EmbeddingGemma 2`) integration & search UX redesign.
2. [**Run 02 — `structure.ai` (`882e5095`, 97 turns)**](02_structure_ai_882e5095.md): Next.js / TypeScript screenplay timeline redesign & PDF shooting-script parser fixes.
3. [**Run 03 — `Hoster` (`59e731ca`, 349 turns)**](03_hoster_59e731ca.md): Android Jetpack Compose / WebView HTML5 app host (`com.example.hoster`) UX alignment, icon raster pipeline, WebView thumbnail aspect ratio, and runtime CDP inspection.
4. [**Run 04 — `StackedMedia` (`c00de98b`, 95 turns)**](04_stackedmedia_c00de98b.md): Android 14+ Jetpack Glance media widget review, settings UI simplification, and closed-app launch regression (`actionStartActivity` vs `actionRunCallback` / stale `sessionActivity`).

---

## 3. Running Observations Across All 4 Sessions (`Stash`, `structure.ai`, `Hoster`, `StackedMedia`)

1. **Cleaning `base1.md` (`slicer.render_trace_markdown`) was the single biggest baseline unlock:**
   * Before fixing `render_trace_markdown()`, `base1.md` used `trace.raw_trajectory_md` (`obs_trunc=50_000, max_chars=400_000`), which filled the first 400KB with redundant `read_file` source dumps and truncated sessions around Turn 250.
   * Rendering from `trace.turns` with `obs_trunc=4_000, read_obs_trunc=1_200, max_chars=0` and stripping `.system_generated/logs/transcript` compaction reads allowed both With-Triage and Without-Triage runs to see all turns (`0..N`) with `(turn k)` anchors.
2. **When Triage runs both dimensions (`Stash`, `structure.ai`, `Hoster`), `With Triage` beats `Without Triage` on both efficiency and multi-cluster completeness:**
   * On high-friction sessions (`Stash`, `structure.ai`, `Hoster`), `ep1..epN` act as an explicit checklist that prevents `dom1` from stopping early after finding only the first obvious rule (e.g., catching `NIGHT` regex stripping in `structure.ai` and catching `hoster-thumbnails` geometry in `Hoster`).
   * Across those 3 sessions, `With Triage` used fewer uncached input tokens every time (`-0.7%` on `Stash`, `-9.9%` on `structure.ai`, `-15.6%` on `Hoster`).
3. **When friction is subtle / error-free (`StackedMedia` `T190..251`), Triage's hard `0.65` dimension gate can cause a False Negative on `DOM`:**
   * In `StackedMedia`, the late-session closed-Spotify launch regression (`T222–241`) and settings whitespace complaint (`T242`) had **zero tool errors**, and `GEMINI.md` already contained 13KB of architectural docs. As a result, `gdm` scored `w13` at `Intent/Domain (DOM) = 0.55` and `w14` at `0.46` (below the `0.65` cutoff) and skipped `dom1`.
   * Meanwhile, `Without Triage` ran `dom1` in parallel with `inv1` (`92.2s` vs `122.6s`, **zero wall-clock penalty** and `~39.8k` uncached tokens) and extracted `.agents/skills/media-widget-interactions/SKILL.md` (the Android 14+ Glance `actionStartActivity` vs `actionRunCallback` + stale `sessionActivity` contract), which was the highest-value domain insight of the session.
   * Similarly, even within `INV` on `StackedMedia`, `inv1` in `With Triage` (`8a55bc12`) found `T222` and `T242` by grepping `base1.md` directly — even though Triage only highlighted `ep1` (`T30..74`) and `ep2` (`T156..189`).
4. **Triage is a capability multiplier for smaller/lesser proposer models (`Stash` GPT 6 Luna `1e` vs `1f`):**
   * On GPT 6.1 Sol (`1c` vs `1d`), `With Triage` and `Without Triage` converged ~90% on the full 505-turn `base1.md`.
   * On GPT 6 Luna (`1e` vs `1f`), removing triage caused Luna to miss the `C7` `inspect_aar_api.py` script (falling back to prose), overfit `INV` alignment to UI cards, and drop the `GEMINI.md` Material 3 invariant.

