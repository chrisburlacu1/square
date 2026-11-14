# Square

Square is a self-improving harness tool for coding agents (**Antigravity** by default, alongside **Claude Code**, **Codex**, and **OpenCode**), built on the **Harness²** (_Recursive Agent Harnessing for an Open World_) architecture.

Instead of relying on manual prompt tuning or static offline benchmarks, Square analyzes your coding-agent session transcripts to spot recurring friction, proposes targeted edits to instructions, rules, skills, and helper scripts, and trials them in your workspace as reversible leases. Target repositories stay completely free of internal `.square` folders—all Square state, leases, reports, and shared experience live under `~/.square/`.

---

## How It Works

### Two Orthogonal Dimensions

Square splits every harness improvement into two independent tracks so project knowledge never leaks across unrelated codebases:

- **`INV` (Harness Invariants):** General agentic workflows, tool-failure recovery, and reusable Python helper scripts (`scripts/<name>.py`) that transfer across repositories via `~/.square/library/`.
- **`DOM` (Domain Knowledge):** Project-specific architecture rules, UI conventions, and subsystem contracts that stay strictly scoped to the target repository.

### The 4-Step Loop

1. **Analyze (`square analyze`):** Reads a completed session transcript in read-only mode, runs parallel `INV` and `DOM` proposers, and writes a reviewable `REPORT.md` with proposed file diffs (`AWAITING_TRIAL`).
2. **Apply (`square apply`):** Materializes chosen proposals into your workspace as tagged, reversible probe leases (`<!-- SQUARE_LEASE:... -->`). Bundled Python scripts automatically go through a 3-second compile + `--help` check before touching your repo.
3. **Probe & Compose (`square ingest` / `square watch`):** Watches subsequent coding sessions to verify whether active leases were matched and actually used. Once validated, Square strips the temporary lease tags and permanently adopts the edits into your repository.
4. **Reflect:** Promotes verified `INV` components into the shared cross-project library (`~/.square/library/<substrate>/`) so future sessions in other repositories benefit automatically.

---

## Installation

Square requires **Python 3.11+** and has **zero external runtime dependencies**:

```bash
python -m pip install -e .
```

All commands below work with either `square ...` (after editable install) or `python -m square.cli ...`.

---

## Quick Start

### 1. Analyze a past session

Run read-only analysis on the latest transcript for a repository (or pass an explicit `.jsonl` transcript path):

```bash
square --repo /path/to/project analyze --latest
# Or analyze a specific transcript:
square --repo /path/to/project analyze /path/to/transcript.jsonl
```

This writes `REPORT.md` under `~/.square/projects/<repo-slug>/cases/<case_id>/` without modifying your project files. Pass `--retry` to regenerate an existing report, or `--no-library` for clean cold-start A/B comparisons without mounting `~/.square/library/`.

### 2. Apply or revert proposals

Once you have reviewed `REPORT.md`, materialize the candidate proposals (or a single dimension) into your workspace as active probe leases:

```bash
# Materialize both INV and DOM proposals:
square --repo /path/to/project apply <case_id>

# Materialize only INV or only DOM:
square --repo /path/to/project apply <case_id> --inv
square --repo /path/to/project apply <case_id> --dom

# Replace an existing active lease in the same dimension slot:
square --repo /path/to/project apply <case_id> --replace

# Cleanly revert active probe leases (removes tags and empty dirs with zero residue):
square --repo /path/to/project apply <case_id> --revert
```

### 3. Probe active leases in subsequent sessions

After working naturally with your coding agent, probe active leases against the new session transcript:

```bash
# One-shot check against the latest completed transcript (no LLM calls unless a lease finishes):
square --repo /path/to/project ingest --latest

# Or watch transcript directories continuously (probe-only by default):
square --repo /path/to/project watch

# Opt in to deterministic slice detection and background proposal generation:
square --repo /path/to/project watch --propose
```

### 4. Inspect status and review runs

```bash
# View native agent surface census, active leases, and awaiting proposals:
square --repo /path/to/project status

# Print a Markdown summary of the latest Square run:
square --repo /path/to/project review
```

---

## Optional: Fast Triage & Session Scanning (`gemini-decision-1`)

If you set `GEMINI_API_KEY` or `GOOGLE_API_KEY` (in your environment or `~/.square/.env`), Square can use `gemini-decision-1` (`/v1beta/decisions`) for fast, low-cost friction scoring:

- **Batch-scan recent sessions across repositories** to find high-friction candidates worth analyzing:
  ```bash
  square scan
  # Optional filters:
  square scan --min-turns 20 --limit 30
  ```
- **Triage a single session** into a turn-window scorecard (`TRIAGE.md`) without running heavy proposer agents:
  ```bash
  square --repo /path/to/project triage --latest
  ```
- **Add triage spotlights to `analyze`** by passing `--with-triage`, which injects high-signal turn windows into `MISSION.md` while still running both `INV` and `DOM` proposers:
  ```bash
  square --repo /path/to/project analyze --latest --with-triage
  ```

---

## Supported Coding Agents

Square operates directly on each agent's native configuration surface (`square/substrates/`):

| Agent | `SurfaceSpec` | Always-On Files | Rules Directory | Skills Directory | Sub-Agents | Scripts | Hooks / Plugins |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Antigravity (Default)** | `AGY_SURFACE` | `GEMINI.md` (100k cap) | `.agents/rules/<name>.md` | `.agents/skills/<name>/SKILL.md` (`name:` req.) | — | `scripts/<name>.py` | `.agents/hooks.json` |
| **Claude Code** | `CLAUDE_SURFACE` | `CLAUDE.md` (8k cap) | — | `.claude/skills/<name>/SKILL.md` | `sub_agents/<name>/AGENT.md` | `scripts/<name>.py` | `.claude/hooks.json` |
| **Codex** | `CODEX_SURFACE` | `AGENTS.md` (8k cap) | — | `.agents/skills/<name>/SKILL.md` | `sub_agents/<name>/AGENT.md` | `scripts/<name>.py` | `.codex/hooks.json` |
| **OpenCode** | `OPENCODE_SURFACE` | `systemprompt.md`, `guardrails.md`, `LongTermMEMORY.md`, `tool_descriptions/tool_guidance.md` (20k cap) | — | `skills/<name>/SKILL.md` | `sub_agents/<name>/AGENT.md` (`mode: subagent`) | `scripts/<name>.py` | `plugin/<name>.ts` |

---

## Project Structure & Development

```text
square/
├── pyproject.toml                  # Python >=3.11 package definition (`square` CLI)
├── docs/                           # Architecture decisions, phase plans, handover notes, and test run logs
├── square/
│   ├── cli.py                      # CLI entrypoint (analyze, apply, ingest, triage, scan, watch, status, review)
│   ├── engine.py                   # Pipeline orchestration (Analyze -> Apply -> Probe -> Compose -> Reflect)
│   ├── slicer.py                   # Deterministic session trajectory slicing and turnaround detection
│   ├── lease.py                    # Lease state machine and activation trigger matching
│   ├── tree.py                     # Agent surface census, validation, and safe workspace adoption
│   ├── library.py                  # INV-only cross-project Continual Improvement Library
│   ├── context.py                  # Ephemeral evidence tree builder for proposers
│   ├── evidence.py                 # Content-addressed candidate, source, trial, and decision ledger
│   ├── proposer.py                 # Proposer CLI runner (Antigravity, Claude, Codex, OpenCode)
│   ├── prompts.py                  # INV, DOM, Composer, and Reflector prompts
│   ├── schemas.py                  # Core dataclasses (SessionTrace, Lease, ActivationTrigger, etc.)
│   ├── decision/                   # gemini-decision-1 client, signal schemas, windowing, and evaluator
│   └── substrates/                 # Surface definitions and transcript parsers per coding agent
└── tests/                          # Unit test suite (`unittest`)
```

Run the unit test suite from the repository root:

```bash
python -m unittest discover -s tests -v
```
