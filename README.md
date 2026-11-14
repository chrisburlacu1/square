# Square (`~/.square`)

## Core update: offline candidates

### Scan historical sessions with `gemini-decision-1` to find test candidates

To batch-scan your recent sessions across all repositories in a single `gemini-decision-1` call (`~2.5s`, `~$0.005` for 25 sessions) and rank which sessions have the strongest `INV`/`DOM` friction for testing Square:

```powershell
python -m square.cli scan
# Optional flags:
python -m square.cli scan --min-turns 20 --limit 30
```

This prints a ranked table via `glow`, saves `~/.square/scan/SCAN_REPORT.md` and `scan.json`, and outputs ready-to-run `triage` and `analyze` commands for the top-scoring sessions.

### Triage a session with `gemini-decision-1` (isolated scorecard)

To evaluate a session's turn windows against Square's universal Harness² signal checklist using Google's zero-output-token decision model (`gemini-decision-1`) without running heavy proposer agents:

```powershell
$env:GEMINI_API_KEY="your-api-key"
python -m square.cli --repo "C:\path\to\your-project" triage --latest
# Or against a specific transcript:
python -m square.cli --repo "C:\path\to\your-project" triage "C:\path\to\transcript.jsonl"
```

This slices the session into overlapping turn windows plus a full-session **Executive Digest**, evaluates both **Macro Session Root-Cause** signals (`MACRO_SIGNALS` + `macro_dominant_root_cause`) and **Micro Turn-Window** signals (`UNIVERSAL_SIGNALS` + `LEVER_CRITERIA`) in a single `/v1beta/decisions` call (`square/decision/`), renders the Markdown scorecard to the terminal (via `glow` when installed), and saves `TRIAGE.md` and `triage.json` under `~/.square/projects/<slug>/triage/`.

### 1. Review a past session (`square analyze`)

From the Square source directory (or after `pip install -e .`), run:

```powershell
python -m square.cli --repo "C:\path\to\your-project" analyze "C:\path\to\transcript.jsonl"
# Or auto-select the latest Antigravity transcript for the repo:
python -m square.cli --repo "C:\path\to\your-project" analyze --latest
```

- **No-Triage Default:** `analyze` renders the full normalized session trajectory (`base1.md`, bounded read dumps, zero turn truncation) plus intra-session $T_Y / T_{Y+1}$ deliverable patches, and runs `inv1` (`INV`) and `dom1` (`DOM`) in parallel without modifying the target repository.
- **Spotlight-Only `--with-triage`:** Pass `--with-triage` (requires `GEMINI_API_KEY` or `GOOGLE_API_KEY`) to run `gemini-decision-1` strictly as an **attention spotlight** (`threshold >= 0.45`) injected into `MISSION.md` while **never skipping** `inv1` or `dom1`.
- **Cold-Start A/B Benchmarks (`--no-library`):** Pass `--no-library` to suppress mounting `~/.square/library/<substrate>/` during clean cold-start vs. warm-library evaluations.
- **Output:** Saves `REPORT.md` under `~/.square/projects/<slug>/cases/<case_id>/` and records candidate proposals as `AWAITING_TRIAL`, printing ready-to-run `square apply <case_id>` commands. Repeating `analyze` returns the saved report; pass `--retry` to run a fresh pass.

### 2. Adopt & probe candidate proposals (`square apply`)

After reviewing `REPORT.md`, materialize the candidate proposals (or a single dimension) into your workspace as reversible `ACTIVE` probe leases:

```powershell
# Materialize all proposals from the latest (or specified) case:
python -m square.cli --repo "C:\path\to\your-project" apply <case_id>

# Materialize only INV or only DOM:
python -m square.cli --repo "C:\path\to\your-project" apply <case_id> --inv
python -m square.cli --repo "C:\path\to\your-project" apply <case_id> --dom

# Replace an existing active lease in the same dimension slot:
python -m square.cli --repo "C:\path\to\your-project" apply <case_id> --replace

# Cleanly revert active probe leases (removes SQUARE_LEASE tags & prunes empty dirs with zero git residue):
python -m square.cli --repo "C:\path\to\your-project" apply <case_id> --revert
```

For Tier 2 Python scripts (`scripts/*.py` or `<skill_dir>/<name>/scripts/*.py`), `square apply` automatically runs a 3-second compile + `--help` import pre-flight check in an ephemeral directory before touching your repository (pass `--force` to override).

### 3. Live probing, asynchronous composition & `INV`-only library (`square ingest` / `square watch`)

Once an `ACTIVE` lease is materialized in your workspace, work naturally in your coding agent and run `ingest` or `watch`:

```powershell
# Probe active leases against the latest completed session transcript (zero LLM calls if no lease completes):
python -m square.cli --repo "C:\path\to\your-project" ingest --latest

# Or watch transcripts continuously in the background (probe-only by default):
python -m square.cli --repo "C:\path\to\your-project" watch

# Optional: opt in to deterministic slice detection + background AWAITING_TRIAL proposal generation:
python -m square.cli --repo "C:\path\to\your-project" watch --propose
```

When an active lease reaches `activations_target` in a matching session (`ACTIVATED_AND_INVOKED`, `MOUNTED_ALWAYS_ON`, or `IGNORED_BY_AGENT`), Square immediately runs **Contrastive Composer synthesis** (`run_compose`, rebased onto the live workspace harness via `rebase_candidate_tree()` without blocking behind unactivated sibling dimensions), permanently adopts validated improvements into the repository while stripping temporary `<!-- SQUARE_LEASE -->` tags, and reflects strictly **origin-tracked `INV` components** into the cross-project Continual Improvement Library `~/.square/library/<substrate>/` (never leaking repo-specific `DOM` skills, rules, or facts).

**Square** (`square` package, `~/.square/` global root directory) is a standalone, zero-user-input implementation of **Harness²** (_Recursive Agent Harnessing for an Open World_) built for real-world coding agents, with **Antigravity** (`antigravity`) as the default substrate alongside **Claude Code**, **Codex**, and **OpenCode**.

Target repositories stay **100% clean** of internal `.square` folders: Square stores all internal state, leases, compact case evidence, and telemetry under `~/.square/projects/<repo-name>-<hash8>/`, shares its Continual Improvement Library globally at `~/.square/library/<substrate>/`, and only writes materialized native agent components (`GEMINI.md`, `.agents/skills/`, `.agents/rules/`, etc.) into the project workspace.

Instead of running $R = 4k$ parallel benchmark rollouts per task or requiring the user to pass manual `--domain` flags, Square operates **directly on each coding agent's native `SurfaceSpec`** (`AGY_SURFACE`, `CLAUDE_SURFACE`, `CODEX_SURFACE`, `OPENCODE_SURFACE`) and runs **autonomously in the background**:

1. **Deterministic Intra-Session & Cross-Commit Trajectory Slicing ($T_{1 \dots Y-1}, T_Y, T_{Y+1}$)** at zero LLM cost (`square/slicer.py`), storing only compact `slice.json` and `trajectory.md` per case.
2. **Scoped Parallel Orthogonal Editors (`INV` + `DOM`)** operating on an ephemeral in-memory/temp `context/` file tree parameterized by the active substrate's `SurfaceSpec` (`square/substrates/`, `square/prompts.py`, `square/engine.py`), recording single-file `audit/*.meta.json` telemetry.
3. **Asynchronous Event-Driven Activation Probing ($A_1, A_2$)** during natural coding sessions with Two-Bit Situation vs. Invocation detection (`square/lease.py`) and reversible tagged blocks (`<!-- SQUARE_LEASE:id=... -->`).
4. **Multi-Candidate Contrastive Composer Synthesis** ($e^0$ vs. $e^{\text{probe}}$ across both `INV` and `DOM` leases) with safe surface adoption (`tree.apply_tree()`) that never wipes pre-existing untracked user skills.
5. **Unified Continual Improvement Library ($\mathcal{R}_t$) & Strict Evidence Filter Rule** (`square/library.py`): Self-categorized YAML frontmatter (`task_id`, `task_domain`, `deficiency_type`, `applied_components`, `contrast_validation_flag: true`, `trajectory_differential_summary`) and `NO_ENTRY` filtering when an edit did not produce a verified positive trajectory delta.

---

## Native Agent Substrates (`square/substrates/`)

| Substrate                                    | `SurfaceSpec`      | Always-On Files                                                                                            | Rules Directory                  | Skills Directory                                | Sub-Agents                                      | Scripts              | Hooks / Plugins      |
| :---                                         | :---               | :---                                                                                                       | :---                             | :---                                            | :---                                            | :---                 | :---                 |
| **Antigravity (Default)** (`antigravity.py`) | `AGY_SURFACE`      | `GEMINI.md` (100,000 cap)                                                                                  | `.agents/rules/<name>.md`        | `.agents/skills/<name>/SKILL.md` (`name:` req.) | — (`allow_subagents=False`)                     | `scripts/<name>.py`  | `.agents/hooks.json` |
| **Claude Code** (`claude.py`)                | `CLAUDE_SURFACE`   | `CLAUDE.md` (8,000 cap)                                                                                    | —                                | `.claude/skills/<name>/SKILL.md`                | `sub_agents/<name>/AGENT.md`                    | `scripts/<name>.py`  | `.claude/hooks.json` |
| **Codex** (`codex.py`)                       | `CODEX_SURFACE`    | `AGENTS.md` (8,000 cap)                                                                                    | —                                | `.agents/skills/<name>/SKILL.md`                | `sub_agents/<name>/AGENT.md`                    | `scripts/<name>.py`  | `.codex/hooks.json`  |
| **OpenCode** (`opencode.py`)                 | `OPENCODE_SURFACE` | `systemprompt.md`, `guardrails.md`, `LongTermMEMORY.md`, `tool_descriptions/tool_guidance.md` (20,000 cap) | —                                | `skills/<name>/SKILL.md`                        | `sub_agents/<name>/AGENT.md` (`mode: subagent`) | `scripts/<name>.py`  | `plugin/<name>.ts`   |

---

## Repository Structure

```text
square/
├── pyproject.toml                  # Standalone Python >=3.11 package (`square`)
├── docs/
│   ├── ADR.md                      # Architectural Decision Records (ADR-001..ADR-007)
│   ├── harness2-summary.md         # Harness² architecture & mathematical specification
│   ├── phase_2.md                  # Phase 2 closed-loop adoption, probing & composition plan
│   ├── handover.md                 # Session-to-session context handover
│   └── test_runs/                  # Triage vs. no-triage benchmark evaluations
├── square/
│   ├── __init__.py
│   ├── schemas.py                  # NormalizedTurn, SessionTrace, TrajectorySlice, Lease, ActivationTrigger
│   ├── tree.py                     # SurfaceSpec, read_tree, write_tree, apply_tree, validate, autotrigger, validate_dimension_scope
│   ├── library.py                  # Unified Continual Improvement Library R_t (INDEX.md, EXPERIENCE.md with YAML frontmatter)
│   ├── context.py                  # Evidence tree builder (ContextTree, build, mission)
│   ├── evidence.py                 # Content-addressed candidate, source, trial, and decision ledger
│   ├── proposer.py                 # Agentic session runner (agy_cli, claude_cli, codex_cli, opencode) + caching
│   ├── prompts.py                  # Full harness2 INV, DOM, Composer, and Reflector prompts + interactive coding extensions
│   ├── slicer.py                   # Deterministic T_{1..Y-1}, T_Y, and two-horizon T_{Y+1} detector
│   ├── lease.py                    # Lease state machine & deterministic ActivationTrigger matcher (A_1, A_2)
│   ├── engine.py                   # Core autonomous pipeline (Ingest -> Analyze -> Apply -> Probe -> Compose -> Reflect)
│   ├── decision/
│   │   ├── __init__.py
│   │   ├── client.py               # gemini-decision-1 (/v1beta/decisions) client
│   │   ├── evaluator.py            # Macro + micro triage evaluator and episode consolidation
│   │   ├── signals.py              # Universal Harness² triage signal schemas
│   │   └── windowing.py            # Turn-window slicer for triage evaluation
│   ├── substrates/
│   │   ├── __init__.py             # Substrate registry, auto-detection, and transcript dispatcher
│   │   ├── base.py                 # Substrate protocol, lease block materializer/reverter, and trace renderer
│   │   ├── antigravity.py          # AGY_SURFACE (default) + Antigravity brain transcript.jsonl reader
│   │   ├── claude.py               # CLAUDE_SURFACE + Claude Code JSONL transcript reader
│   │   ├── codex.py                # CODEX_SURFACE + Codex JSONL transcript reader
│   │   └── opencode.py             # OPENCODE_SURFACE + OpenCode JSONL transcript reader
│   └── cli.py                      # Zero-config CLI entrypoint (analyze, apply, triage, scan, ingest, watch, status, review)
└── tests/
    ├── test_decision.py
    ├── test_evidence.py
    ├── test_substrates_and_tree.py
    ├── test_slicer.py
    ├── test_lease_activation.py
    └── test_engine_loop.py
```

---

## Quick Start & CLI Usage

### Run the Test Suite

```bash
python -m unittest discover -s tests -v
```

### CLI Commands (Antigravity Default, Zero User Configuration)

```bash
# 1. Check native Antigravity component census and active/staged leases in the current repo
python -m square.cli status

# 2. Process the latest session transcript for the current repo immediately (no watcher loop needed)
python -m square.cli --latest
# (or: python -m square.cli ingest --latest)

# 3. Zero-config background watcher: automatically monitors ~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl
#    and processes transcripts belonging to the current workspace (--repo .)
python -m square.cli watch

# 4. Ingest a specific completed session transcript (.jsonl)
python -m square.cli ingest ~/.gemini/antigravity/brain/<conv-id>/.system_generated/logs/transcript.jsonl

# 5. Review the latest Square run (telemetry, tool calls, proposer outputs, and active leases)
python -m square.cli --repo <path> review

# 6. Target Antigravity's GLOBAL customization surface (~/.gemini/config) and global library (~/.square/library)
python -m square.cli --global-surface --latest

# 7. Apply or revert candidate proposals (`--inv`, `--dom`, `--revert`, `--replace`, `--force`)
python -m square.cli apply <case_id>
python -m square.cli apply <case_id> --revert
```

---

## Global `~/.square/` State Layout

```text
~/.square/
├── library/
│   └── antigravity/                # Shared Continual Improvement Library R_t across repos
│       ├── INDEX.md
│       └── harnesses/<case_id>/EXPERIENCE.md
└── projects/
    └── <repo-name>-<hash8>/        # Per-repository Square state (target repo stays clean)
        ├── project.json
        ├── leases.json             # Active/composed leases (stores base_tree, candidate_tree, notes)
        ├── managed_components.json # Component paths adopted by Square
        ├── pending_survival.json   # Cross-commit T_{Y+1} git survival tracker
        ├── audit/
        │   └── <case_id>.<stage>.a1.<hash>.meta.json  # Single-file telemetry + proposer response
        └── cases/
            └── <case_id>/
                ├── slice.json      # Consolidated slice metadata + task prompt + T_Y/T_{Y+1} diffs
                ├── trajectory.md   # Normalized [ACTION]/[OBSERVATION] session transcript
                └── probes/         # Populated when an active lease is probed in a later session
```
