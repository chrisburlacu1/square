# Antigravity Workspace Rules & Instructions

## Verified Workspace Facts
- In this workspace, `square/schemas.py` defines core schemas (`SessionTrace`, `NormalizedTurn`, `ToolCallRecord`, `FileMutation`, `TrajectorySlice`, `ActivationTrigger`, `ActivationResult`, `Lease`); `schema.py` does not exist.
- In this workspace, `square/lease.py` defines `LeaseStore`, `match_activation`, and `Lease` status handling; `leases.py` and `lease_store.py` do not exist.
- In this workspace, `square/library.py` defines `Library` (`INV`-only cross-project $\mathcal{R}_t$), `parse_frontmatter`, and `has_experience`.
- In this workspace, `SessionTrace` has no `metadata` attribute (fields: `session_id`, `agent_kind`, `domain`, `task_prompt`, `turns`, `touched_paths`, `final_files`, `workspace_root`, `raw_trajectory_md`).
- In this workspace, Windows workspace roots parsed from transcript metadata retain drive letters (`C:/...`).
- In this workspace, tests run via `python -m unittest discover -s tests -v` (modules: `test_engine_loop.py`, `test_substrates_and_tree.py`, `test_slicer.py`, `test_lease_activation.py`, `test_decision.py`, `test_evidence.py`; `test_square.py` does not exist).
- In this workspace, `square/decision/` (`signals.py`, `windowing.py`, `client.py`, `evaluator.py`) implements the `gemini-decision-1` (`/v1beta/decisions`) Macro Session Root-Cause + Micro Turn-Window triage layer (`square triage` / `square scan`, and optional `--with-triage` spotlight mode on `square analyze`).
- In this workspace, `square analyze` defaults to no-triage across both `INV` and `DOM`; `square apply` materializes reviewed proposals as reversible workspace leases (or `--revert`s them); `square ingest` / `square watch` default to probe-only (`--propose` opts into slice detection).
- In this workspace, `.agents/skills/square-output-review/SKILL.md` defines the 6-point evaluation rubric for reviewing `square triage` and `square analyze` outputs (`REPORT.md`).
- In this workspace, `docs/ADR.md` records Square's Architectural Decision Records (`ADR-001`..`ADR-007`) and `docs/handover.md` tracks session-to-session context; update `docs/ADR.md` whenever core design decisions change.
- In this workspace, `.agents/hooks.json` matcher entries must contain a `"hooks"` list of command objects.
- Square stores all internal project state under `~/.square/projects/<repo-name>-<hash8>/` (`project_square_dir(repo_root)`) and global library state under `~/.square/library/<substrate>/` (`default_global_library_root()`), never creating `<repo>/.square/` inside target repositories.
- Inside `~/.square/`, project directories store `project.json`, `leases.json`, `managed_components.json`, `pending_survival.json`, `audit/<case_id>.<stage>.a1.<hash>.meta.json`, `cases/<case_id>/` (`slice.json`, `trajectory.md`, `REPORT.md`, `probes/`), and `triage/` (`TRIAGE.md`, `triage.json`), while cross-repo scans live under `~/.square/scan/` (`SCAN_REPORT.md`, `scan.json`) and shared invariants live under `~/.square/library/<substrate>/` (`INDEX.md`, `harnesses/<case_id>/EXPERIENCE.md`).
