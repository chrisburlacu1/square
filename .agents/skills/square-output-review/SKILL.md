---
name: square-output-review
description: >-
  Evaluate and critique outputs from `square triage` and `square analyze` runs
  (`REPORT.md`, `triage_report.json`, and `INV`/`DOM` candidate diffs). Use this
  skill whenever the user asks to review, inspect, grade, or sanity-check a Square
  triage or analyze run, or asks whether proposed skills, rules, scripts, or
  signals match Square's project philosophy.
---

# Reviewing Square Triage & Analyze Outputs

Use this skill to evaluate `square triage` and `square analyze` runs with the same architectural lens across sessions.

---

## 1. Core Architectural Lens: How Square Differs from Harness²

Square adapts the Harness² dual-recursion architecture (`Agent = Model + Harness`, separated into `INV` and `DOM` dimensions across components `C2`–`C8`) from **static benchmarks** to **live, interactive user coding sessions**. That shift creates four critical differences you must check on every run:

1. **Completed Work Persists in the Repo (The Anti-Retrospective Rule):**
   - In a benchmark (Harness²), the workspace resets to $t=0$ after the rollout, so documenting what the agent discovered during the task helps the next retry of that same benchmark.
   - In a real user session, **the feature, bugfix, or migration built during the session is already committed into the codebase (and often added to `GEMINI.md`) by the end of the session**.
   - Therefore, a proposal that merely summarizes or documents the feature that was built during the session is **redundant**. Proposals must only capture **forward-looking invariants, workflows, or tools** that remain non-obvious for *future* tasks.
2. **Macro Abstract Root Causes vs. Micro Symptoms:**
   - A 300–500 turn session often contains multi-turn rework loops (e.g., 3 rewrites of a UI screen). The real fix is rarely "do the rewrite faster" or "don't use literal `20.dp` on `ScreenX`".
   - On the **`INV` (Methodology)** side, the root cause is usually an upfront workflow gap—e.g., defining what success looks like with the user before writing code.
   - On the **`DOM` (Domain/Repo)** side, the root cause is usually an unstated architectural or design-system invariant—e.g., using the project's defined Material 3 theme/shape/color tokens instead of auto-hardcoding literals.
3. **Division of Labor (`gdm` Triage vs. Heavyweight Proposers):**
   - **`gdm` (`gemini-decision-1`) Triage** is a calibrated spotlight. It scores 5 **Macro Session Root-Cause** signals over the full-session Executive Digest and 9 **Micro Turn-Window** signals over 15-turn windows, then routes episodes to `INV` or `DOM` and suggests component levers (`rules_c2`, `skill_c5`, `subagent_c6`, `script_c7`).
   - **The Proposers (`INV` and `DOM`)** are heavy reasoning models. They must **not** blindly implement a literal patch for whatever `gdm` flagged. They should use the `gdm` spotlights + raw transcript slices to diagnose the underlying principle and craft generalizable components.
4. **Multiple Orthogonal Root Causes per Session:**
   - Unlike a 15-turn benchmark task with one failure mode, a multi-hour user session often contains **multiple independent root-cause clusters** within the same dimension (for example, `INV` may have *both* a macro UX spec-elicitation workflow gap *and* 4 micro episodes of repeated manual `.gradle/caches` + `javap` shell toil).
   - Proposers should address **each distinct, orthogonal high-confidence root cause** rather than stopping after a single edit.

---

## 2. Step-by-Step Inspection Procedure

When given a case directory (`~/.square/projects/<project>/cases/<case_id>`) or `REPORT.md`:

1. **Read the Case Artifacts:**
   - Read `<case_dir>/REPORT.md` for the full triage + proposal diff output.
   - If deeper inspection is needed, check `<case_dir>/triage_report.json`, `<case_dir>/candidates/INV/meta.json`, and `<case_dir>/candidates/DOM/meta.json`.
2. **Check the Target Workspace's Existing Surface:**
   - Inspect the target repository's `GEMINI.md` / `AGENTS.md` and `.agents/skills/` to see what was *already* written into the repo during the session and which skills are 3rd-party or user-owned.
3. **Evaluate Triage Quality (Phase 1) and Proposal Quality (Phase 2)** using the rubric below.

---

## 3. The 6-Point Evaluation Rubric

### Check 1: Triage Signal & Consolidation Sanity (`gdm`)
* **Macro Signals (`0.00–1.00`):** Did the Macro Session Root-Cause section (`macro_iterative_rework_loop`, `macro_unverified_claims_or_defaults`, `macro_recurring_manual_toil`, `macro_missing_domain_mental_model`, `macro_verification_blind_spot`) accurately capture the big-picture session friction?
* **Micro Episodes:** Were adjacent windows only merged when they shared a triggered signal? Did `gdm` avoid false positives on platform artifacts (such as `.system_generated/logs/transcript` compaction recovery reads)?
* **Routing & Levers:** Does each consolidated episode's `INV`/`DOM` route and aligned lever (`rules_c2`, `skill_c5`, `subagent_c6`, `script_c7`) match the actual friction?

### Check 2: Orthogonal Cluster Coverage (No Single-Edit Bottleneck)
* Compare the distinct root-cause clusters in `REPORT.md` against the files changed by `INV` and `DOM`.
* **Pass:** If `INV` was routed both a high-confidence workflow/rework root cause (`skill_c5`) *and* a repeated mechanical toil cluster (`script_c7`, e.g., 3–4 episodes of manual archive/bytecode inspection), `INV` proposed both the workflow skill and the `scripts/<name>.py` helper.
* **Fail:** A proposer addressed one cluster and ignored another orthogonal high-confidence cluster.

### Check 3: The Anti-Retrospective Test (Critical for `DOM`)
* Ask: *"Is this proposed edit teaching a future agent something non-obvious it will need on the NEXT task, or is it just summarizing the feature/migration that was already finished in THIS session?"*
* **Pass:** Encoding reusable design-system rules (e.g., "use `MaterialTheme.shapes` and `colorScheme` tokens rather than hardcoded `.dp`/`Color` literals"), build/test commands, or non-obvious library sharp edges (e.g., static TFLite signature constraints vs. high-level GenAI wrappers).
* **Fail:** Writing a retrospective architectural summary of how today's feature was implemented when that code (and `GEMINI.md` summary) already exists in the repo.

### Check 4: Abstraction Level (Principles vs. Hyper-Specific Overfitting)
* **Pass:** Rules, skills, and scripts abstract away one-off task literals and capture the underlying decision boundary or parameterized tool workflow.
* **Fail:** Hyper-specific rules tied to a single screen or literal from the session without the general principle.

### Check 5: Dimension Boundary & Lever Fit (`INV` vs. `DOM`)
* **`INV` Purity:** `INV` edits must contain **zero** repository-specific paths, package names, or domain framework assumptions—they must be portable to any software project in the global library (`~/.square/library/`).
* **`DOM` Focus:** `DOM` edits should stay concise (`GEMINI.md` / `AGENTS.md` or Square-owned domain skills/scripts) and avoid repeating generic coding advice.
* **Lever Selection:** Repeated multi-step shell inspection/parsing (`automatable_manual_work`) should become an executable `scripts/<name>.py` (`C7`), not a wall of prose instructions.

### Check 6: User & 3rd-Party Skill Preservation
* **Strict Invariant:** Square must **never** modify pre-existing user-owned or 3rd-party skills in `.agents/skills/` (such as skills with `author:` frontmatter or skills without `<!-- square-managed -->`). Any diff touching a 3rd-party skill is an immediate bug.

---

## 4. How to Format Your Review for the User

Start with an **ADHD-friendly high-level bullet summary** at the top covering:
1. **What Worked:** Which macro/micro signals and proposed components hit the mark and why.
2. **What Missed / Needs Tuning:** Any missed orthogonal clusters, retrospective `DOM` recaps, overfitted rules, or surface boundary leaks.
3. **Actionable Next Step:** Whether the issue is in **Phase 1 (`gdm` triage criteria/windowing)** or **Phase 2 (`prompts.py` / `evaluator.py` proposer brief)**, and the targeted adjustment to test next.

> **Guardrail Against Prompt Overfitting:** When recommending or making an adjustment to `square/prompts.py` or `square/decision/signals.py` after reviewing a run, **never** inject session-specific artifacts, paths, tools, or framework names (such as `.gradle/caches`, `javap`, `MaterialTheme`, etc.) into Square's prompts. Keep all prompt adjustments strictly at the structural/meta level (e.g., matching lever choice to reuse frequency, covering orthogonal root-cause clusters, or filtering retrospective summaries).
