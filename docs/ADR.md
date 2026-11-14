# Architecture Decision Records (ADR) — Square

This document records the key architectural decisions that shape Square and how it diverges from static benchmark harnesses (Harness²). Update this file whenever a core design decision changes.

---

## ADR-001: Calibrated Decision Triage via `gemini-decision-1` (`gdm`)

* **Date:** 2026-11-12
* **Status:** Accepted
* **Context:**
  * Earlier versions of Square relied on regex/heuristic trajectory slicing (`square/slicer.py`) to detect friction, which either missed semantic user pushback or required expensive heavyweight LLM calls just to decide whether a session was worth analyzing.
* **Decision:**
  * Introduce `square/decision/` powered by Google's `gemini-decision-1` (`gdm`, `/v1beta/decisions`) as the primary triage and routing engine for `square triage` and `square analyze`.
  * Slice sessions into overlapping turn windows (`windowing.py`) plus a full-session `# FULL SESSION EXECUTIVE DIGEST`, and evaluate up to 500 `noul` (yes/no probability) and `choice` questions in a single zero-output-token HTTP request (`~2.5s`, `~$0.01` per 500-turn session).
* **Consequences:**
  * Fast, calibrated (`0.00–1.00`) pre-proposer filtering and `INV`/`DOM` dimension routing.
  * Eliminates `keep_base` from `best_lever` multi-class choices (`LEVER_CRITERIA`) so lever selection does not suffer 6-way probability dilution; threshold gating is handled strictly by `signal >= threshold` and `already_covered < max`.
  * Adjacent windows only merge into a `MergedEpisode` when they share at least one triggered signal key, preventing unrelated half-session mega-episodes.

---

## ADR-002: Dual-Horizon `gdm` Triage (Macro Abstract Root Causes + Micro Turn Spotlights)

* **Date:** 2026-11-12
* **Status:** Accepted
* **Context:**
  * Evaluating only 15-turn micro windows catches localized mechanical errors (e.g., failed edits or shell loops) but misses the abstract, session-wide reason *why* 50+ turns were wasted (for example, going through 3 full UI rewrites because the agent never aligned with the user on what success looked like upfront).
* **Decision:**
  * Run two levels of `gdm` evaluation in the same `/v1beta/decisions` call:
    1. **Macro Session Root-Cause Analysis (`MACRO_SIGNALS` + `macro_dominant_root_cause`):** Evaluates the `# FULL SESSION EXECUTIVE DIGEST` across 5 session-wide patterns (`macro_iterative_rework_loop`, `macro_unverified_claims_or_defaults`, `macro_recurring_manual_toil`, `macro_missing_domain_mental_model`, `macro_verification_blind_spot`).
    2. **Micro Turn-Window Spotlights (`UNIVERSAL_SIGNALS`):** Evaluates individual turn windows for concrete mechanical, workflow, and domain friction, stripping platform artifacts like `.system_generated/logs/transcript` compaction reads.
* **Consequences:**
  * `gdm` flags both the overarching session failure mode (e.g., missing upfront UX specification alignment) and the specific turn windows where friction manifested.

---

## ADR-003: Division of Labor Between `gdm` Triage and Heavyweight Proposers

* **Date:** 2026-11-12
* **Status:** Accepted
* **Context:**
  * A decision model (`gdm`) excels at fast, calibrated symptom spotlighting, but cannot reason deeply about code architecture or nuance (e.g., recognizing that a user's pushback on a hardcoded `20.dp` corner radius means "follow the project's Material 3 theme tokens rather than auto-hardcoding literals").
* **Decision:**
  * Treat `gdm` outputs strictly as **symptom spotlights**, not literal patch instructions.
  * Pass the macro root-cause scores and consolidated micro episodes to the heavyweight `INV` and `DOM` proposers (`format_proposer_brief`), instructing them to diagnose the underlying principle from the raw transcript slices rather than creating hyper-specific rules for individual flagged turns.
* **Consequences:**
  * Avoids brittle, hyper-specific rules while keeping proposer context focused on high-signal episodes.

---

## ADR-004: Adapting Harness² Proposers from Static Benchmarks to Live User Sessions

* **Date:** 2026-11-12
* **Status:** Accepted
* **Context:**
  * Harness² was designed for short (15–30 turn) static benchmarks where:
    1. Each task has a single failure mode, so proposers are told to commit to a single edit (*"Prefer, in order: 1. USER REWORK, 2. mechanical failure... Do not try to cover every base"*).
    2. The workspace resets to $t=0$ after each rollout, so recording what was built during the run helps the next retry of that same benchmark.
  * In Square, user sessions are 100–500+ turns long and mutate the live git repository permanently:
    1. A single session often contains **multiple orthogonal root causes** in the same dimension (e.g., an upfront UX alignment workflow gap *and* a recurring manual `.jar`/`javap` shell toil cluster).
    2. By the end of the session, the feature/migration built during the session **already persists in the codebase and `GEMINI.md`**.
* **Decision:**
  * **Multi-Cluster Coverage:** Instruct `INV` and `DOM` proposers to group symptoms into **distinct, orthogonal root-cause clusters** and propose the appropriate component for *each* distinct cluster rather than stopping after one edit.
  * **Anti-Retrospective Rule (`DOM`):** Never write a retrospective recap of a feature or migration that was already completed during the session. Only extract forward-looking, reusable domain, library, or design-system invariants for *future* tasks.
  * **Match Lever to Reuse Frequency (`DOM`):** Repo-wide design-system, theme, and architectural invariants that apply to almost every future change belong as concise bullets in always-on instructions (`GEMINI.md` / `AGENTS.md`), whereas multi-step subsystem workflows belong in on-demand skills (`.agents/skills/<name>/SKILL.md`).
* **Consequences:**
  * Prevents `INV` from dropping `scripts/<name>.py` helpers when a `SKILL.md` is also needed, and prevents `DOM` from writing redundant recaps of finished work or dropping repo-wide design-system rules.

---

## ADR-005: Strict Isolation of User-Owned & 3rd-Party Workspace Skills

* **Date:** 2026-11-12
* **Status:** Accepted
* **Context:**
  * Target repositories often contain pre-existing user-authored skills or 3rd-party skills (e.g., Google `litert-lm`, `android-profiler`). In offline `analyze` mode (`live_workspace=False`), `current_harness()` previously bypassed `read_clean_workspace_tree()`, exposing 3rd-party skills to the `DOM` proposer.
* **Decision:**
  * `current_harness()` must always route through `read_clean_workspace_tree(..., materialize_missing=False)` even when `live_workspace=False`.
  * A skill under `.agents/skills/` is only included in Square's editable harness tree if it carries `<!-- square-managed -->` or was created by an active/promoted Square lease (`managed_components.json`), never from unapplied `AWAITING_TRIAL` leases or pre-existing files.
* **Consequences:**
  * User-owned skills (including `.agents/skills/square-output-review/SKILL.md`) and 3rd-party skills are 100% invisible to and untouched by Square proposers.

---

## ADR-006: Clean Full-Session Trajectory Rendering (`base1.md`) vs. Decision-Model Triage

* **Date:** 2026-11-13
* **Status:** Accepted (Supersedes ADR-001/ADR-002/ADR-003 for `square analyze` pre-proposer gating)
* **Context:**
  * Previously, `slicer.render_trace_markdown(trace)` short-circuited to `trace.raw_trajectory_md` (`obs_trunc=50_000, max_chars=400_000`) whenever `slice_obj is None`. On 300–500 turn sessions (`Stash`, `Hoster`), this filled `base1.md` with ~300KB of `read_file` source dumps and silently truncated the trajectory around Turn 250 (`…(+375483 chars — render truncation)`).
  * Because `base1.md` was truncated and bloated, `gemini-decision-1` (`gdm`) Triage (`windowing.py`) appeared indispensable simply because it was the only place in the proposer prompt that contained a compact summary of turns `250..505`.
  * After fixing `render_trace_markdown()` to render directly from `trace.turns` (`obs_trunc=4_000, read_obs_trunc=1_200, max_chars=0`, `(turn N)` labels, and stripping `.system_generated/logs/transcript` compaction reads), we benchmarked **With Triage vs. Without Triage (`--no-triage`)** across 4 real sessions (`Stash`, `structure.ai`, `Hoster`, `StackedMedia` — recorded in [`docs/test_runs/`](test_runs/README.md)).
* **Findings & Decision:**
  1. **Clean `base1.md` + `gpt-6.1-sol` makes window-level decision triage redundant:** Once `base1.md` is compact (~145KB–230KB for 100–500 turns) and complete (`T0..N`), `gpt-6.1-sol` inspects the full session directly via `rg -n '^\[(USER|ASSISTANT|ACTION|OBSERVATION ERROR)\]' context/rollouts/base1.md` on Turn 1.
  2. **Hard probability cutoffs (`0.65`) cause False Negatives on quiet domain bugs:** On `StackedMedia` (`c00de98b`), a critical Android 14+ / Jetpack Glance closed-app launch regression (`T222–241`) had zero CLI tool errors, so `gdm` scored `Intent/Domain (DOM) = 0.55` (`< 0.65`) and skipped `dom1` completely — losing the highest-value `media-widget-interactions` skill that `--no-triage` extracted with zero wall-clock penalty (since `inv1` and `dom1` run in parallel).
* **Consequences:**
  * Always render `base1.md` from normalized `trace.turns` with bounded read observations (`read_obs_trunc=1_200, max_chars=0`).
  * Decision models (`gemini-decision-1`) are not the right mechanism for slicing or gating `INV`/`DOM` proposers inside `square analyze`; next session should simplify `square analyze` around the direct clean-trajectory path (`--no-triage` as default or removing window-triage from `analyze`).

---

## ADR-007: Closing the Loop — Adoption Gate (`square apply`), Probe-Only Ingestion, Asynchronous Composition & Leak-Proof `INV`-Only Library ($\mathcal{R}_t$)

* **Date:** 2026-11-14
* **Status:** Accepted
* **Context:**
  * Phase 1 solved single-session extraction (`transcript.jsonl` $\to$ `REPORT.md`), while the downstream adoption, probing, composition, and library reflection pipeline remained gated behind a legacy `live_workspace: bool` toggle, waited synchronously on both sibling dimensions (`INV` and `DOM`) before composing, counted raw `read_file` tool-output dumps in `cue_keywords`, and passed the full composed repository tree (`INV` + `DOM`) into the global cross-project library `~/.square/library/<substrate>/`.
* **Decisions:**
  1. **No-Triage Default + Spotlight-Only `--with-triage` in `square analyze`:** `square analyze` defaults to `use_triage=False`, running `inv1` and `dom1` in parallel directly on clean `base1.md`. When `--with-triage` is passed, `gemini-decision-1` runs strictly as an **attention spotlight** (`spotlight_threshold=0.45`), injecting episode/window/macro highlights into `MISSION.md` while **never skipping** `inv1` or `dom1`.
  2. **Read-Only Unmanaged Skill Manifest (`ADR-005` Refinement):** Pre-existing user or 3rd-party skills remain 100% locked out of the editable `context/harness/` tree, while a compact read-only manifest (`name` + `description`) is listed in `MISSION.md` and `summarize_current_harness()` so proposers never mint duplicate skills.
  3. **Explicit `square apply` Gate + Tier 2 Script Pre-Flight:** Reviewing `REPORT.md` is the human adoption gate. `square apply [case_id|lease_id] [--inv] [--dom] [--revert] [--replace] [--force]` promotes selected `AWAITING_TRIAL` / `STAGED_TIER_2` candidates to `ACTIVE`, runs a 3s compile + `--help` import pre-flight on any `.py` scripts before touching the workspace, stamps `<!-- square-managed -->` on newly leased `SKILL.md` files, and prunes empty directories cleanly on `--revert` with zero git residue.
  4. **Probe-Only Default for `ingest` / `watch` + Asynchronous Rebasing Composition:** `square ingest` and `square watch` evaluate `active_leases` by default (`--propose` opts into background slice detection). `match_activation()` excludes raw `tc.output` from `cue_keywords`, requires actual tool reads/invocations/script execution for `SKILL.md`, and returns `MOUNTED_ALWAYS_ON` for always-on rules. Ready leases compose immediately without waiting on unactivated sibling dimensions, rebasing candidate trees via `HT.rebase_candidate_tree()` onto `live_base_tree`.
  5. **Strict `AGY_SURFACE` Fidelity & Leak-Proof `INV`-Only Library ($\mathcal{R}_t$):** `AGY_SURFACE` enforces `skill_name_rule="must_match"` and `allow_subagents=False`, and `_check_script_refs()` accepts skill-relative `scripts/<helper>.py` paths. `library_for()` resolves to `~/.square/library/<substrate>/` (`--no-library` disables mounting for clean A/B benchmarks), mounts library context strictly for `INV`, and computes an origin-tracked `inv_delta_tree` against `live_base_tree` in `run_reflect()` (storing `INV` always-on additions in `ALWAYS_ON_DELTA.md`, omitting empty `GEMINI.md` stubs via `ensure_always_on=False`, and preventing any `DOM` skills/rules/facts from leaking across projects).
* **Consequences:**
  * Standard CLI usage (`square analyze` $\to$ `square apply` $\to$ `square ingest` / `square watch`) executes the full recursive Harness² loop safely, reversibly, and without cross-project domain contamination.
