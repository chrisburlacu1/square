# Session Handover — Square (`2026-11-14`)

## 1. Where We Are Right Now

* **Milestone Status:** [**Phase 2 Plan (`docs/phase_2.md`)**](phase_2.md) is **100% Completed** ("Closing the Loop: Adoption, Probing, Composition & Library $\mathcal{R}_t$").
* **Verification Status:**
  * **Unit Test Suite:** `47/47` tests passing (`python -m unittest discover -s tests -v`).
  * **Surface Census:** `python -m square.cli status` passes with `0` warnings.
  * **Live Git Worktree Smoke Test:** Verified end-to-end against real Phase 1 `Hoster` Tier 2 candidates (`cdp_layout_snapshot.py` + `raster_variants.py`) in an isolated disposable worktree — confirmed 3-second `--help` script pre-flight, zero-residue `square apply --revert` (`git status --porcelain == ""`), probe-only `square ingest`, `run_compose()` rebasing onto `live_base_tree`, and leak-proof `INV`-only `~/.square/library/<substrate>/INDEX.md` reflection.
* **Key Documents Updated This Session:**
  * [**Phase 2 Plan (`docs/phase_2.md`)**](phase_2.md): Marked Completed with verification summary.
  * [**Architecture Decision Records (`docs/ADR.md`)**](ADR.md): Added `ADR-007` locking in the Phase 2 closed-loop design.
  * [**README (`README.md`)**](../README.md), [**GEMINI.md (`GEMINI.md`)**](../GEMINI.md), & [**AGENTS.md (`AGENTS.md`)**](../AGENTS.md): Synced CLI flags (`square apply`, `--with-triage`, `--no-library`, `ingest --propose`, `watch --propose`), surface rules, and test inventory.

---

## 2. What Was Implemented in Phase 2 (`ADR-007`)

1. **Streamlined `square analyze` & Surface Fidelity ([`square/cli.py`](../square/cli.py), [`square/engine.py`](../square/engine.py), [`square/tree.py`](../square/tree.py), [`square/prompts.py`](../square/prompts.py), [`square/substrates/antigravity.py`](../square/substrates/antigravity.py), [`square/decision/`](../square/decision/evaluator.py)):**
   * `square analyze` now runs **no-triage by default** across both `INV` and `DOM` in parallel (`--no-triage` kept as a backwards-compatible alias).
   * Optional `--with-triage` runs `gemini-decision-1` strictly as an **attention spotlight** (`threshold=0.45`), injecting turn-window/macro spotlights into `MISSION.md` without ever skipping `inv1` or `dom1` (eliminating the `StackedMedia` `DOM` false negative).
   * Enforced `AGY_SURFACE` parity in `tree.py`: `100,000`-char instruction ceiling, `allow_subagents=False`, mandatory matching `name:` in `SKILL.md` frontmatter, skill-relative `scripts/<file>.py` resolution in `HT.validate()`, `.agents/hooks.json` `"hooks"` array schema checks, and clean CLI flag isolation in `AntigravityAdapter.invoke_agent()`.
   * Populated `at_t_y_diff` and `survival_t_y1_diff` from intra-session `detect_semantic_revert()` / mutation patches.

2. **Explicit `square apply` Gate, Tier 2 Pre-Flight & Reversible Leases ([`square/cli.py`](../square/cli.py), [`square/engine.py`](../square/engine.py), [`square/lease.py`](../square/lease.py)):**
   * Added `square apply [case_id|lease_id] [--inv] [--dom] [--revert] [--replace] [--force]`.
   * Runs a 3-second `python <script> --help` smoke pre-flight on bundled `.py` scripts before touching the target workspace, snapshots overwritten files (`pre_apply_snapshots`), materializes components cleanly, and supports byte-exact `--revert`.

3. **Probe-Only Default Ingestion & Asynchronous Ready-Lease Composition ([`square/engine.py`](../square/engine.py), [`square/lease.py`](../square/lease.py)):**
   * Decoupled active-lease probing from unreviewed auto-proposal (`auto_propose: bool = False` default on `square ingest` and `square watch`; `--propose` opts into slice detection).
   * Reduced `activations_target` default to `1`, excluded raw read-only tool outputs (`tc.output`) from `cue_keywords` trigger matching to prevent false `IGNORED_BY_AGENT` rejections, and updated `process_session()` + `run_compose()` to compose `ready_leases` asynchronously onto `live_base_tree` without blocking on unactivated sibling leases or clobbering uncomposed active leases.

4. **Origin-Tracked `INV`-Only Continual Library $\mathcal{R}_t$ ([`square/library.py`](../square/library.py), [`square/context.py`](../square/context.py), [`square/engine.py`](../square/engine.py)):**
   * Unified `library_for()` across `analyze_session()` and `run_reflect()` under `~/.square/library/<substrate>/`.
   * Mounted `context/library/` (`INDEX.md` + reusable `INV` components) only for `INV` proposers (with `--no-library` bypass for clean A/B benchmarks).
   * Scoped `run_reflect()` strictly to component paths originated by verified `INV` leases — preventing `DOM` skills, repo rules, or private `GEMINI.md` files from ever leaking into `~/.square/library/`.

---

## 3. Environment Note & Recommended Next Steps

* **Known Host Sandbox Quirk on Windows:** On this machine, Antigravity's terminal sandbox has a host-level rule (`readonly .square: non-absolute file path`) that causes sandboxed shell commands to fail before process launch until run outside the sandbox (`BypassSandbox: true`). Square itself creates zero `.square` directories inside workspaces (`ADR-002`).
* **Recommended Next Steps for the Next Session:**
  1. **Commit Phase 1 + Phase 2 Milestone:** Review `git status` / `git diff` and commit the completed Phase 1 + Phase 2 changes cleanly to git history.
  2. **Live Multi-Session Field Trial (`analyze` $\to$ `apply` $\to$ `watch` $\to$ `reflect`):** Apply one or two top Phase 1 candidates (e.g., `Hoster` `runtime-ui-diagnosis` or `Stash` `INV` workflow skill) in a live coding session, run `square ingest` / `square watch` afterward to observe real-world activation probing, composition, and `INDEX.md` promotion, and evaluate cross-project transfer on a second repo (`analyze` with vs. without `--no-library`).
  3. **Evaluate Composer & Library Pruning Ergonomics:** Once `~/.square/library/antigravity/INDEX.md` accumulates multiple real `INV` entries across projects, inspect `square review` / `square status` output and decide whether to add a dedicated `square library` inspection/prune subcommand in Phase 3.
