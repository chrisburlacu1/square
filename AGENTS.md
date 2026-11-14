# Repository Guidelines

## Project Structure & Module Organization

Square is a Python 3.11+ package for recursive coding-agent harness improvement, with no declared runtime dependencies. Source lives in `square/`: `cli.py` exposes commands (`analyze`, `apply`, `ingest`, `triage`, `watch`, `status`, `review`), `engine.py` coordinates the pipeline, `square/decision/` implements `gemini-decision-1` window slicing, universal Harness² signal schemas, and `/v1beta/decisions` evaluation, and `slicer.py`, `lease.py`, `tree.py`, and `library.py` handle trajectory analysis, activation, agent surfaces, and shared experience. Keep agent-specific adapters in `square/substrates/` (Antigravity, Claude, Codex, OpenCode).

Tests live in `tests/`. Consult `README.md` for usage and `docs/ADR.md` and `docs/phase_2.md` for architecture. `reference/` contains reference material; there is no dedicated application-assets directory.

## Build, Test, and Development Commands

Run commands from the repository root:

- `python -m pip install -e .` installs the package in editable mode and exposes the `square` command.
- `python -m pip wheel . --no-deps` builds a distributable wheel using setuptools.
- `python -m unittest discover -s tests -v` runs the full test suite.
- `python -m square.cli --help` displays available CLI options.
- `python -m square.cli status` inspects the current repository's agent surface and leases.
- `python -m square.cli watch` monitors transcripts and processes sessions; use a disposable workspace when exercising changes that materialize agent components.

## Coding Style & Naming Conventions

Follow existing Python style: four-space indentation, `snake_case` functions and modules, `PascalCase` classes, and uppercase constants such as `CODEX_SURFACE`. Use type annotations, `pathlib.Path`, and small helpers consistent with neighboring code. No formatter or linter is configured in `pyproject.toml`; avoid unrelated formatting changes.

## Testing Guidelines

Use `unittest.TestCase`, `test_*.py` files, and descriptive `test_*` methods. Add regression tests beside the affected subsystem. Use temporary directories and deterministic scripted proposers to isolate filesystem changes and avoid live agent calls. Cover surface preservation, lease activation, and pipeline behavior when relevant. No minimum coverage threshold is configured.

## Commit & Pull Request Guidelines

Use semantic commit prefixes (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`) followed by concise, imperative summaries. Keep changes focused. PR descriptions should explain the behavior change, link relevant issues, and report test commands and outcomes. Include sample CLI output when changing user-visible behavior.

## Agent-Specific Instructions

When `.codegraph/` exists, use CodeGraph before searching or reading code: `codegraph explore "<symbol or question>"`. On PowerShell systems that block script shims, use `codegraph.cmd`. Keep internal state under `~/.square/` and preserve existing user-owned agent components.
