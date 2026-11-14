# Test Run 02 — `structure.ai` (`882e5095-e7c9-42d1-913f-e04e1aa1cb94`)

* **Repository:** `~/projects/structure.ai` (Next.js / React / TypeScript screenplay structure visualizer & PDF shooting-script parser)
* **Session Length:** `97` normalized turns (up to step index `231`)
* **Session Summary:** Audited and redesigned the cluttered screenplay analysis UI (`ux_and_design_blueprint.md`, `DESIGN.md`, `globals.css`), hit tool friction running `npx modern-web-guidance` and cancelled a Next.js build without checking logs, iterated on a bottom workbench that required too much scrolling (`T79`) before moving to a full-screen split workspace (`T107`), untangled `script.scenes` vs. `analysis.beats` navigation and demo motif overfitting (`T108–T115`), fixed Beats layer toggling shifting timeline coordinates (`T132`), and fixed numbered shooting-script PDF extraction (`Anora` returning 0 scenes due to marginal scene numbers shifting `headingX` and a suffix rule stripping `NIGHT`, plus `0..N-1` vs. `1..52` scene index mismatches at `T139–T231`).
* **With Triage Case:** [`manual_247f51f45b671134a137_33cc26a8/REPORT.md`](~/.square/projects/structure.ai-406dc38d/cases/manual_247f51f45b671134a137_33cc26a8/REPORT.md)
* **Without Triage Case:** [`manual_247f51f45b671134a137_c6f62505/REPORT.md`](~/.square/projects/structure.ai-406dc38d/cases/manual_247f51f45b671134a137_c6f62505/REPORT.md)

---

## 1. Timing & Token Usage (`33cc26a8` With Triage vs. `c6f62505` Without Triage)

| Metric | With Triage (`33cc26a8`) | Without Triage (`c6f62505`) | Delta (With vs. Without) |
| :--- | :---: | :---: | :---: |
| **`gdm` Triage Latency / Cost** | `1.19s` API (`16` windows, `134` questions) / `$0.0046` | `0s` / `$0.00` | `+1.19s` / `+$0.0046` |
| **`inv1` Elapsed (`wall_s`)** | `104.1s` (1 attempt) | `100.8s` (1 attempt) | `+3.3s` |
| **`dom1` Elapsed (`wall_s`)** | `129.5s` (1 attempt) | `113.7s` (1 attempt) | `+15.8s` (wrote 2 skills vs 1) |
| **Max Parallel Proposer Wall Time** | **`129.5s` (~2m 10s)** | **`113.7s` (~1m 54s)** | `+15.8s` |
| **`inv1` Tool Calls** | **`8`** | `12` | **`-4` tool calls (`-33.3%`)** |
| **`dom1` Tool Calls** | `10` | `9` | `+1` tool call |
| **`inv1` Input Tokens (Cached / Uncached)** | `307,063` (`270,848` / **`36,215`**) | `321,320` (`278,784` / **`42,536`**) | **`-6,321` uncached (`-14.9%`)** |
| **`dom1` Input Tokens (Cached / Uncached)** | `409,006` (`370,304` / **`38,702`**) | `340,522` (`299,904` / **`40,618`**) | **`-1,916` uncached (`-4.7%`)** |
| **Total Uncached Input Tokens (`INV`+`DOM`)** | **`74,917`** (`89.5%` cache hit) | **`83,154`** (`87.4%` cache hit) | **`-8,237` uncached (`-9.9%`)** |
| **`inv1` Output Tokens (Reasoning)** | `3,367` (`214` reasoning) | `3,215` (`198` reasoning) | `+152` (`+16` reasoning) |
| **`dom1` Output Tokens (Reasoning)** | `4,260` (**`271` reasoning**) | `3,192` (**`499` reasoning**) | `+1,068` (**`-228` reasoning [`-45.7%`]**) |
| **Total Output Tokens (Reasoning)** | **`7,627` (`485` reasoning)** | **`6,407` (`697` reasoning)** | `+1,220` (**`-212` reasoning [`-30.4%`]**) |

---

## 2. Proposed Components & 6-Point Rubric Comparison

| Rubric Check | With Triage (`33cc26a8`) | Without Triage (`c6f62505`) | Winner & Why |
| :--- | :--- | :--- | :--- |
| **1. Triage Signal & Consolidation** | `macro_iterative_rework_loop = 0.96`; 4 consolidated episodes: `ep1` (`T30..42`, `tool_env_friction=0.94`), `ep2` (`T74..85`, `intent_or_domain_divergence=0.89`), `ep3` (`T94..133`, `intent_or_domain_divergence=0.92`), `ep4` (`T132..152`, `tool_env_friction=0.83`). | N/A | **Pass** |
| **2. Orthogonal Cluster Coverage** | **Pass:**<br>- `INV`: `.agents/skills/ux-change-alignment/SKILL.md` + `.agents/skills/tool-failure-recovery/SKILL.md`<br>- `DOM`: `GEMINI.md` (2 UI rules) + `.agents/skills/screenplay-ux-contract/SKILL.md` + `.agents/skills/screenplay-pdf-contract/SKILL.md` | **Pass:**<br>- `INV`: `.agents/skills/ux-change-alignment/SKILL.md` + `GEMINI.md` (`## Tool results and completion`, 3 bullets)<br>- `DOM`: `GEMINI.md` (2 UI rules) + `.agents/skills/screenplay-contracts/SKILL.md` | **Edge to With Triage** — Splitting `screenplay-ux-contract` (UI/timeline) from `screenplay-pdf-contract` (PDF parser) matches the actual module boundaries (`src/lib/timeline.ts` vs `src/lib/parse/pdf/*`), and keeping `tool-failure-recovery` as a skill preserves `GEMINI.md` budget. |
| **3. Anti-Retrospective Test (`DOM`)** | **Pass:** Encodes checkable data-to-label, coordinate stability (`axisY`, `canvasHeight`, `pageScale`), and PDF slugline geometry contracts rather than summarizing the completed split-screen redesign. | **Pass:** Also strictly forward-looking. | **Tie (Both Pass)** |
| **4. Sharp-Edge Precision** | Caught **both** the permissive suffix rule stripping `NIGHT` from sluglines when removing marginal scene numbers (`14A*` at `T139–149`) **and** preserving whole-script observations (`sceneId: null` at `T32`). | Caught `headingX` vs marginal scene numbers and `0..N-1` vs `1..52` fixture indices, but missed the `NIGHT` stripping bug and `sceneId: null`. | **With Triage** — Spotlighting `ep4` (`T132..152`) led `DOM` directly to the `NIGHT` stripping regression in `classify.ts`/`scenes.ts`. |
| **5. Dimension Boundary & Lever Fit** | **Pass:** `INV` touched zero `GEMINI.md` lines (2 portable skills); `DOM` added 2 concise `GEMINI.md` bullets + 2 subsystem skills. Both recognized that `scripts/check-scenes.mjs` and `scripts/check-classify.mjs` already existed so no redundant `C7` script was needed. | **Pass (with heavier `GEMINI.md` footprint):** `INV` added 6 lines to `GEMINI.md` instead of using a skill. | **With Triage** |
| **6. 3rd-Party Skill Preservation** | **Pass** | **Pass** | **Tie** |

