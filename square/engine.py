"""Core autonomous pipeline for Square (`.square`): Ingest -> Propose -> Probe -> Compose -> Reflect.

Enforces all 9 architectural invariants from Plan v2:
- Invariant #1: Frozen Editor Prompts + Data-Driven Level 2 Recursion (`EDITOR_LESSONS.md`)
- Invariant #2: Full `harness2` Prompt Core + $T_Y / T_{Y+1}$ as Deliverable Evidence
- Invariant #3: Native Substrate `SurfaceSpec`s (`CODEX_SURFACE`, `OPENCODE_SURFACE`, `CLAUDE_SURFACE`, `AGY_SURFACE`)
- Invariant #4: In-place file-tree editing with validation retry (`run_stage`)
- Invariant #5: Scoped parallel leasing for `INV` and `DOM` (`validate_dimension_scope`)
- Invariant #6: Contrastive Composer synthesis (`run_compose`)
- Invariant #7: Situation-Based `ActivationTrigger` matching (`match_activation`)
- Invariant #8: Two-Horizon $T_{Y+1}$ detection (`slicer.py`)
- Invariant #9: Windows-safe file locking & reversible tagged lease blocks
"""

from __future__ import annotations

import difflib
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

from . import context, prompts, slicer
from . import tree as HT
from .context import PoolEntry, RolloutEvidence
from .decision import (
    DecisionClient,
    GeminiDecisionClient,
    SessionTriageService,
    TriageReport,
    format_proposer_brief,
    render_triage_markdown,
    resolve_gemini_api_key,
)
from .evidence import EvidenceStore, fingerprint
from .lease import LeaseStore, classify_tier, file_lock, match_activation
from .library import Library
from .prompts import BenchPrompts
from .proposer import Proposer, ProposerError
from .schemas import (
    ActivationResult,
    ActivationTrigger,
    Dimension,
    Lease,
    SessionTrace,
    TrajectorySlice,
)
from .substrates import (
    Substrate,
    default_global_library_root,
    get_substrate,
    project_square_dir,
)
from .substrates.base import (
    list_unmanaged_workspace_skills,
    read_clean_workspace_tree,
    record_square_managed_components,
)
from .tree import SurfaceSpec, Tree

STAGE_ATTEMPTS = 2


@dataclass
class StageOutcome:
    """Result of one agentic editing stage (`INV`, `DOM`, or `COMPOSE`)."""

    label: str
    dim: str
    tree: Tree
    kept_base: bool = False
    fell_back: bool = False
    error: str = ""
    usd: float = 0.0
    attempts: int = 0
    cached: bool = False
    notes: str = ""
    trigger: ActivationTrigger = field(default_factory=ActivationTrigger)


@dataclass
class SessionReport:
    """Summary of what `SquareEngine.process_session` did on one ingested session."""

    session_id: str
    substrate_name: str
    domain: str
    activations: list[ActivationResult] = field(default_factory=list)
    composed_leases: list[str] = field(default_factory=list)
    reflected_cases: list[str] = field(default_factory=list)
    slices_detected: list[TrajectorySlice] = field(default_factory=list)
    created_leases: list[Lease] = field(default_factory=list)


def _accept_tree(
    surface: SurfaceSpec,
    dim: str,
    new: Tree,
    fallback: Tree,
    label: str,
) -> tuple[bool, str]:
    """Repair skill triggers, validate `surface`, and check `INV`/`DOM` scope if applicable.
    Pre-existing skills in `fallback` are excluded from the new-skill trigger-line check so
    unreferenced user skills already on disk do not block candidate validation.
    """
    del label
    skill_prefix = surface.skill_dir + "/"
    pre_existing_skills = {
        rel: content
        for rel, content in fallback.items()
        if rel.startswith(skill_prefix) and rel.endswith("SKILL.md")
    }
    new_only_for_trigger = {
        rel: content for rel, content in new.items() if rel not in pre_existing_skills
    }
    HT.autotrigger(surface, new_only_for_trigger)
    for ao in surface.always_on:
        if ao in new_only_for_trigger:
            new[ao] = new_only_for_trigger[ao]
    changed = HT.diff_summary(surface, fallback, new)
    kept = not (changed["added"] or changed["removed"] or changed["modified"])
    try:
        effective_cap = max(surface.always_on_max, len(HT.always_on_text(surface, fallback)) + 4_000)
        HT.validate(
            surface,
            new_only_for_trigger,
            allow_subagents=surface.allow_subagents,
            always_on_max=effective_cap,
        )
        if dim in ("INV", "DOM"):
            HT.validate_dimension_scope(surface, dim, fallback, new)
    except ValueError as exc:
        return kept, str(exc)
    return kept, ""


def _preflight_python_scripts(tree: Tree, paths: Sequence[str], *, timeout_s: float = 3.0) -> list[str]:
    """Run a fast Tier 2 pre-flight check (`compile` + `python <script> --help`) on `.py` scripts
    in an ephemeral directory before materializing them into the user's workspace.
    Returns a list of human-readable warning/error messages (empty if all scripts pass).
    """
    py_paths = [HT.normalize_rel(p) for p in paths if HT.normalize_rel(p).endswith(".py") and HT.normalize_rel(p) in tree]
    if not py_paths:
        return []
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="square-preflight-") as tmp:
        root = Path(tmp)
        for rel, content in tree.items():
            dest = root / HT.normalize_rel(rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        for rel in py_paths:
            src = tree[rel]
            try:
                compile(src, rel, "exec")
            except SyntaxError as exc:
                errors.append(f"`{rel}` has a syntax error on line {exc.lineno}: {exc.msg}")
                continue
            try:
                proc = subprocess.run(
                    [sys.executable, str(root / rel), "--help"],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                errors.append(f"`{rel} --help` timed out after {timeout_s:.1f}s")
                continue
            except OSError as exc:
                errors.append(f"`{rel}` could not be executed: {exc}")
                continue

            combined_err = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
            if "ModuleNotFoundError" in combined_err or "ImportError" in combined_err or "SyntaxError" in combined_err:
                tail = " ".join(combined_err.splitlines()[-3:])[:240]
                errors.append(f"`{rel}` failed import pre-flight: {tail}")
            elif proc.returncode not in (0, 1, 2) or (proc.returncode != 0 and "Traceback (most recent call last)" in combined_err):
                tail = " ".join(combined_err.splitlines()[-3:])[:240]
                errors.append(f"`{rel} --help` exited with code {proc.returncode}: {tail}")
    return errors


def run_stage(
    *,
    surface: SurfaceSpec,
    label: str,
    dim: str,
    job: str,
    fallback: Tree,
    prop: Proposer,
    case_id: str,
    task_md: str,
    rollouts: Sequence[RolloutEvidence],
    harness: Tree | None = None,
    harness_dir: Path | None = None,
    ctx_dir: Path | None = None,
    library_dir: Path | None = None,
    pool: Sequence[PoolEntry] = (),
    decisions: dict[str, str] | None = None,
    fallback_touched_files: list[str] | None = None,
    unmanaged_skills: Sequence[dict[str, str]] = (),
) -> StageOutcome:
    """Build evidence tree in an ephemeral workspace, run proposer in-place on `context/harness/`,
    validate against `surface`, and retry once with `# YOUR PREVIOUS ATTEMPT WAS REJECTED\\n\\n<error>` if invalid.
    """
    del ctx_dir
    tmp_ctx_root = Path(tempfile.mkdtemp(prefix=f"square-ctx-{label}-"))
    try:
        try:
            ctx_tree = context.build(
                tmp_ctx_root / label,
                case_id,
                task_md,
                rollouts,
                surface=surface,
                harness_dir=harness_dir,
                harness=harness if harness is not None else (fallback if harness_dir is None else None),
                library_dir=library_dir,
                pool=pool,
                decisions=decisions,
                unmanaged_skills=unmanaged_skills,
            )
            mission_str = context.mission(ctx_tree, job=job)
        except Exception as exc:
            err_msg = f"could not build evidence: {type(exc).__name__}: {exc}"[:400]
            print(f"[square] Stage {case_id}.{label} fell back: {err_msg}", file=sys.stderr, flush=True)
            return StageOutcome(
                label=label,
                dim=dim,
                tree=dict(fallback),
                fell_back=True,
                error=err_msg,
                attempts=0,
            )

        err = ""
        spent_usd = 0.0
        spent_calls = 0
        all_cached = True

        for attempt in range(1, STAGE_ATTEMPTS + 1):
            try:
                reply = prop.call(
                    mission_str
                    + (
                        f"\n\n# YOUR PREVIOUS ATTEMPT WAS REJECTED\n\n{err}\n\n"
                        f"Fix it in `context/harness/` and reply again."
                        if err
                        else ""
                    ),
                    ctx_tree.root,
                    f"{case_id}.{label}.a{attempt}",
                    harvest="context/harness",
                )
            except ProposerError as exc:
                err = str(exc)
                spent_calls += exc.attempts or 1
                spent_usd += exc.cost_usd
                all_cached = False
                break

            spent_usd += reply.cost_usd
            spent_calls += 0 if reply.cached else max(1, reply.attempts)
            all_cached = all_cached and reply.cached

            if reply.workspace is None:
                err = (
                    "the harness directory did not come back from the session; edit the files "
                    "in `context/harness/` in place"
                )
                continue

            rejected: list[str] = []
            try:
                new = HT.read_tree(surface, reply.workspace, rejected=rejected)
            finally:
                if reply.workspace.name.startswith(("square-harvest-", "scripted-")):
                    shutil.rmtree(reply.workspace, ignore_errors=True)

            if not new:
                err = "`context/harness/` came back empty -- edit the files, do not delete them all"
                continue
            if rejected:
                err = (
                    "these files are off the editable surface and were not applied: "
                    + ", ".join(sorted(rejected)[:6])
                    + ". Component names must be lowercase letters, digits, `_` or `-` "
                    f"(e.g. `{surface.skill_dir}/review/SKILL.md`, "
                    f"`{surface.skill_dir}/api_check/SKILL.md`, `scripts/check.py`)."
                )
                continue

            kept, err = _accept_tree(surface, dim, new, fallback, label)
            if err:
                HT.write_tree(surface, new, ctx_tree.root / "harness")
                continue

            notes = prompts.extract_notes(reply.text)
            trig = prompts.extract_trigger(reply.text, fallback_files=fallback_touched_files)
            return StageOutcome(
                label=label,
                dim=dim,
                tree=new,
                kept_base=kept,
                usd=spent_usd,
                attempts=spent_calls,
                cached=all_cached,
                notes=notes,
                trigger=trig,
            )

        print(f"[square] Stage {case_id}.{label} fell back after {spent_calls} attempt(s): {err[:400]}", file=sys.stderr, flush=True)
        return StageOutcome(
            label=label,
            dim=dim,
            tree=dict(fallback),
            fell_back=True,
            error=err[:400],
            usd=spent_usd,
            attempts=spent_calls,
            cached=all_cached,
        )
    finally:
        shutil.rmtree(tmp_ctx_root, ignore_errors=True)


class SquareEngine:
    """Autonomous background engine orchestrating `~/.square/projects/<slug>/` (`cases/`,
    `leases.json`, `audit/`, `pending_survival.json`) and the global Continual Improvement
    Library `~/.square/library/<substrate>/` across native agent substrates.
    """

    def __init__(
        self,
        repo_root: Path | str,
        proposer: Proposer,
        *,
        substrate: Substrate | str = "antigravity",
        profile: BenchPrompts | None = None,
        activations_target: int = 1,
        library_root: Path | str | None = None,
        square_root: Path | str | None = None,
        live_workspace: bool = False,
        use_library: bool = True,
        decision_client: DecisionClient | None = None,
    ):
        self.live_workspace = live_workspace
        self.use_library = use_library
        self.decision_client = decision_client
        self.repo_root = Path(repo_root)
        self.square_root = (
            Path(square_root) if square_root else project_square_dir(self.repo_root)
        )
        self.cases_dir = self.square_root / "cases"
        self.library_root = (
            Path(library_root)
            if library_root
            else default_global_library_root(self.repo_root)
        )

        self.default_substrate = (
            substrate if isinstance(substrate, Substrate) else get_substrate(substrate)
        )
        self.proposer = proposer
        if getattr(self.proposer, "audit_dir", None) is None:
            self.proposer.audit_dir = self.square_root / "audit"
        self.profile = profile or BenchPrompts()
        self.activations_target = activations_target

        self.square_root.mkdir(parents=True, exist_ok=True)
        proj_meta = self.square_root / "project.json"
        if not proj_meta.is_file():
            proj_meta.write_text(
                json.dumps(
                    {
                        "repo_root": str(self.repo_root.resolve()),
                        "repo_name": self.repo_root.resolve().name,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

        self.lease_store = LeaseStore(self.square_root)
        self.evidence = EvidenceStore(self.square_root)
        # Ensure initial native harness exists on disk for the default substrate
        if self.live_workspace:
            self.default_substrate.read_workspace_tree(self.repo_root)

    def _resolve_substrate(
        self, substrate: Substrate | str | None, trace: SessionTrace | None = None
    ) -> Substrate:
        if isinstance(substrate, Substrate):
            return substrate
        if isinstance(substrate, str) and substrate.strip():
            return get_substrate(substrate)
        if trace is not None and trace.agent_kind in ("codex", "opencode", "claude", "antigravity"):
            return get_substrate(trace.agent_kind)
        return self.default_substrate

    def current_harness(self, substrate: Substrate | str | None = None) -> Tree:
        sub = self._resolve_substrate(substrate)
        surface = sub.surface()
        t = (
            sub.read_workspace_tree(self.repo_root)
            if self.live_workspace
            else read_clean_workspace_tree(
                surface, self.repo_root, sub.default_tree(), materialize_missing=False
            )
        )
        for lease in self.lease_store.active_leases(substrate_name=sub.name):
            for rel in lease.component_paths:
                norm = HT.normalize_rel(rel)
                if norm in surface.always_on:
                    continue
                if norm not in lease.base_tree:
                    t.pop(norm, None)
                else:
                    t[norm] = lease.base_tree[norm]
        return t

    def library_for(
        self, domain: str = "default", substrate: Substrate | str | None = None
    ) -> Library:
        del domain
        sub = self._resolve_substrate(substrate)
        return Library(
            root=self.library_root / sub.name,
            surface=sub.surface(),
        )

    def apply_case_leases(
        self,
        target_id: str | None = None,
        *,
        dims: set[Dimension] | None = None,
        replace: bool = False,
        force: bool = False,
        substrate: Substrate | str | None = None,
    ) -> list[Lease]:
        """Promote selected `AWAITING_TRIAL` / `STAGED_TIER_2` leases to `ACTIVE`, running a
        Tier 2 `.py` pre-flight check, rebasing onto `current_harness()`, and materializing
        native substrate files into `self.repo_root`.
        """
        all_leases = self.lease_store.load_all()
        eligible_statuses = {"AWAITING_TRIAL", "STAGED_TIER_2"}
        eligible = [l for l in all_leases if l.status in eligible_statuses]
        if not eligible:
            raise ValueError("No candidate leases awaiting adoption (status AWAITING_TRIAL or STAGED_TIER_2)")

        selected: list[Lease]
        if target_id:
            by_lease = [l for l in eligible if l.lease_id == target_id]
            if by_lease:
                selected = by_lease
            else:
                by_case = [l for l in eligible if l.case_id == target_id]
                if not by_case:
                    raise ValueError(
                        f"No AWAITING_TRIAL or STAGED_TIER_2 lease found matching {target_id!r}"
                    )
                selected = by_case
        else:
            latest_case_id = eligible[-1].case_id
            selected = [l for l in eligible if l.case_id == latest_case_id]

        if dims:
            selected = [l for l in selected if l.dimension in dims]
        if not selected:
            raise ValueError("No matching candidate leases for the requested dimension filter")

        # 1. Check slot conflicts before mutating workspace
        conflicts: list[Lease] = []
        for cand in selected:
            sub = self._resolve_substrate(substrate or cand.substrate_name)
            for act in self.lease_store.active_leases(substrate_name=sub.name):
                if act.dimension == cand.dimension and act.lease_id != cand.lease_id:
                    conflicts.append(act)
        if conflicts and not replace:
            conflict_ids = ", ".join(f"`{c.lease_id}` ({c.dimension})" for c in conflicts)
            raise ValueError(
                f"Active lease slot conflict with {conflict_ids}. "
                "Pass `--replace` to revert the existing active lease first, or run `square apply --revert`."
            )

        # 2. Tier 2 `.py` pre-flight check before touching repo_root
        for cand in selected:
            sub = self._resolve_substrate(substrate or cand.substrate_name)
            surface = sub.surface()
            live_base = self.current_harness(sub) or sub.default_tree()
            rebased_cand = HT.rebase_candidate_tree(
                surface, live_base, cand.base_tree, cand.candidate_tree
            )
            diff = HT.diff_summary(surface, live_base, rebased_cand)
            changed = sorted(set(diff["added"]) | set(diff["removed"]) | set(diff["modified"]))
            preflight_errs = _preflight_python_scripts(rebased_cand, changed)
            if preflight_errs and not force:
                raise ValueError(
                    f"Tier 2 script pre-flight failed for `{cand.lease_id}`: "
                    + "; ".join(preflight_errs)
                    + " (pass `--force` to apply anyway)"
                )

        # 3. Revert replaced active leases if `--replace`
        if conflicts and replace:
            seen_rev: set[str] = set()
            for act in conflicts:
                if act.lease_id in seen_rev:
                    continue
                seen_rev.add(act.lease_id)
                sub_act = self._resolve_substrate(substrate or act.substrate_name)
                sub_act.revert_lease(self.repo_root, act.lease_id, act)
                act.status = "REVERTED"
                self.lease_store.update_lease(act)

        # 4. Rebase onto live harness, mark ACTIVE, and materialize into repo_root
        applied: list[Lease] = []
        for cand in selected:
            sub = self._resolve_substrate(substrate or cand.substrate_name)
            surface = sub.surface()
            live_base = self.current_harness(sub)
            if not live_base:
                live_base = sub.default_tree()
                for ao, content in live_base.items():
                    p_ao = self.repo_root / ao
                    if not p_ao.is_file():
                        p_ao.parent.mkdir(parents=True, exist_ok=True)
                        p_ao.write_text(content, encoding="utf-8")
            rebased_cand = HT.rebase_candidate_tree(
                surface, live_base, cand.base_tree, cand.candidate_tree
            )
            diff = HT.diff_summary(surface, live_base, rebased_cand)
            changed = sorted(set(diff["added"]) | set(diff["removed"]) | set(diff["modified"]))
            cand.base_tree = dict(live_base)
            cand.candidate_tree = rebased_cand
            cand.component_paths = changed or cand.component_paths
            cand.tier = classify_tier(cand.component_paths, surface)
            cand.status = "ACTIVE"
            self.lease_store.update_lease(cand)
            sub.materialise_lease(self.repo_root, cand)
            applied.append(cand)

        return applied

    def revert_active_leases(
        self,
        target_id: str | None = None,
        *,
        dims: set[Dimension] | None = None,
        substrate: Substrate | str | None = None,
    ) -> list[Lease]:
        """Revert active leases matching `target_id` / `dims` cleanly from `self.repo_root`."""
        sub_filter = self._resolve_substrate(substrate).name if substrate else None
        active = self.lease_store.active_leases(substrate_name=sub_filter)
        if target_id:
            active = [l for l in active if l.lease_id == target_id or l.case_id == target_id]
        if dims:
            active = [l for l in active if l.dimension in dims]
        reverted: list[Lease] = []
        for lease in active:
            sub = self._resolve_substrate(lease.substrate_name)
            sub.revert_lease(self.repo_root, lease.lease_id, lease)
            lease.status = "REVERTED"
            self.lease_store.update_lease(lease)
            reverted.append(lease)
        return reverted

    def process_session(
        self,
        trace: SessionTrace,
        substrate: Substrate | str | None = None,
        *,
        propose: bool | None = None,
    ) -> SessionReport:
        """Process an ingested `SessionTrace` on `substrate`:
        1. Always probe any `ACTIVE` leases against `trace` (`situation_matched` vs. `component_invoked`),
           increment `unrelated_sessions_seen` on unrelated sessions, record probe rollouts on matched
           sessions, and compose any ready leases (`activations_completed >= activations_target`) via
           `run_compose()` -> `run_reflect()`.
        2. When `propose=True` (or legacy `self.live_workspace=True`), also run deterministic slice
           detection on unleased dimensions to generate new proposals.
        """
        sub = self._resolve_substrate(substrate, trace)
        should_propose = self.live_workspace if propose is None else propose
        surface = sub.surface()
        report = SessionReport(
            session_id=trace.session_id,
            substrate_name=sub.name,
            domain=trace.domain,
        )

        # Step 1: Check active leases for this substrate (always runs when active leases exist)
        active = self.lease_store.active_leases(substrate_name=sub.name)
        activated_situation = False
        touched_case_ids: list[str] = []
        for lease in active:
            act = match_activation(trace, lease, surface=surface)
            report.activations.append(act)
            if not act.situation_matched:
                lease.unrelated_sessions_seen += 1
                self.lease_store.update_lease(lease)
                continue
            if trace.session_id in lease.probe_sessions:
                continue

            activated_situation = True
            self._record_probe_rollout(lease, trace, act)
            lease.activations_completed += 1
            lease.probe_sessions.append(trace.session_id)
            lease.probe_outcomes.append(act.outcome)
            self.lease_store.update_lease(lease)
            if lease.case_id not in touched_case_ids:
                touched_case_ids.append(lease.case_id)

        # Compose any ready leases immediately without blocking behind an unactivated sibling dimension,
        # while batching INV + DOM together when both reach activations_target in the same session.
        if touched_case_ids:
            current_active = self.lease_store.active_leases(substrate_name=sub.name)
            for cid in touched_case_ids:
                case_leases = [l for l in current_active if l.case_id == cid]
                ready_leases = [
                    l for l in case_leases if l.activations_completed >= l.activations_target
                ]
                if ready_leases:
                    comp_stage, live_base_tree = self._run_compose_with_base(
                        cid, ready_leases, substrate=sub
                    )
                    report.composed_leases.extend(l.lease_id for l in ready_leases)
                    if not comp_stage.kept_base:
                        reflected = self.run_reflect(
                            cid,
                            ready_leases,
                            comp_stage,
                            substrate=sub,
                            live_base_tree=live_base_tree,
                        )
                        if reflected and not reflected.get("no_entry"):
                            report.reflected_cases.append(cid)

        # Step 2: Background slice detection & proposal (opt-in via `propose=True` or legacy `live_workspace=True`)
        if should_propose and not activated_situation:
            if not self.live_workspace:
                offline_rep = self._process_offline(trace, sub)
                report.slices_detected.extend(offline_rep.slices_detected)
                report.created_leases.extend(offline_rep.created_leases)
                return report

            git_slices = slicer.evaluate_pending_git_survival(self.square_root, self.repo_root)
            intra_slices = slicer.detect_slices(trace)
            all_slices = git_slices + intra_slices
            report.slices_detected.extend(all_slices)

            unprocessed_slices = [
                s for s in all_slices if not (self.cases_dir / f"case_{s.slice_id}").exists()
            ]
            if unprocessed_slices:
                primary_slice = unprocessed_slices[0]
                case_id = f"case_{primary_slice.slice_id}"
                case_dir = self.cases_dir / case_id
                slicer.populate_case_workspace(case_dir, trace, primary_slice)
                new_leases = self.run_propose(
                    case_id=case_id,
                    domain=trace.domain,
                    substrate=sub,
                    touched_files=primary_slice.touched_files or trace.touched_paths,
                )
                report.created_leases.extend(new_leases)
                if not new_leases:
                    (case_dir / "decision.json").write_text(
                        json.dumps({"status": "no_change", "session_id": trace.session_id}),
                        encoding="utf-8",
                    )
            slicer.record_pending_git_survival(trace, self.square_root)

        return report

    def _process_offline(self, trace: SessionTrace, sub: Substrate) -> SessionReport:
        """Ingest source evidence without treating it as a trial of a future change."""
        report = SessionReport(session_id=trace.session_id, substrate_name=sub.name, domain=trace.domain)
        source = self.evidence.put("sources", {"schema_version": 1, "trace": asdict(trace)})
        with file_lock(self.square_root / "ingest.lock"):
            journal = self.square_root / "processed_sources.json"
            processed = json.loads(journal.read_text(encoding="utf-8")) if journal.exists() else []
            if source in processed:
                return report
            slices = slicer.detect_slices(trace)
            report.slices_detected.extend(slices)
            for item in slices:
                case_id = f"case_{item.slice_id}"
                case_dir = self.cases_dir / case_id
                marker = case_dir / "processed.json"
                if marker.exists():
                    continue
                slicer.populate_case_workspace(case_dir, trace, item)
                (case_dir / "source.json").write_text(json.dumps({"source": source}), encoding="utf-8")
                leases = self.run_propose(case_id, domain=trace.domain, substrate=sub,
                    touched_files=item.touched_files or trace.touched_paths)
                report.created_leases.extend(leases)
                marker.write_text(json.dumps({"source": source, "status": "proposed" if leases else "no_change"}), encoding="utf-8")
            processed.append(source)
            tmp = journal.with_suffix(".tmp")
            tmp.write_text(json.dumps(processed), encoding="utf-8")
            tmp.replace(journal)
        return report

    def triage_session(
        self,
        trace: SessionTrace,
        substrate: Substrate | str | None = None,
        *,
        decision_client: DecisionClient | None = None,
        window_size: int = 8,
        stride: int = 6,
        signal_threshold: float = 0.65,
        already_covered_max: float = 0.75,
    ) -> tuple[TriageReport, Path]:
        """Run `gemini-decision-1` triage in isolation across `trace` and save `TRIAGE.md` + `triage.json`."""
        if not trace.turns and not trace.raw_trajectory_md.strip():
            raise ValueError("No readable session events found in this transcript")
        sub = self._resolve_substrate(substrate, trace)
        surface = sub.surface()
        harness = self.current_harness(sub)
        unmanaged = list_unmanaged_workspace_skills(surface, self.repo_root)
        source = self.evidence.put("sources", {"schema_version": 1, "trace": asdict(trace)})
        client = decision_client or self.decision_client or GeminiDecisionClient()
        svc = SessionTriageService(
            client=client,
            window_size=window_size,
            stride=stride,
            signal_threshold=signal_threshold,
            already_covered_max=already_covered_max,
        )
        report = svc.evaluate(
            trace, surface=surface, harness=harness, unmanaged_skills=unmanaged
        )
        triage_dir = self.square_root / "triage" / f"triage_{source[:20]}"
        triage_dir.mkdir(parents=True, exist_ok=True)
        (triage_dir / "triage.json").write_text(
            json.dumps(report.to_dict(), indent=2),
            encoding="utf-8",
        )
        md_path = triage_dir / "TRIAGE.md"
        md_path.write_text(render_triage_markdown(report), encoding="utf-8")
        return report, md_path

    def analyze_session(
        self,
        trace: SessionTrace,
        substrate=None,
        *,
        retry: bool = False,
        use_triage: bool | None = False,
        force_propose: bool = False,
    ) -> Path:
        """One bounded retrospective pass across `INV` and `DOM` (default no-triage; optional
        `use_triage=True` runs `gemini-decision-1` strictly as an attention spotlight without
        skipping either dimension).
        """
        del force_propose
        if not trace.turns and not trace.raw_trajectory_md.strip():
            raise ValueError("No readable session events found in this transcript")
        sub = self._resolve_substrate(substrate, trace)
        source = self.evidence.put("sources", {"schema_version": 1, "trace": asdict(trace)})
        case_id = f"manual_{source[:20]}"
        if retry:
            import uuid
            case_id += "_" + uuid.uuid4().hex[:8]
        case_dir = self.cases_dir / case_id
        with file_lock(self.square_root / "manual.lock"):
            report_path = case_dir / "REPORT.md"
            if report_path.exists():
                return report_path
            case_dir.mkdir(parents=True, exist_ok=True)
            end = trace.turns[-1].turn_index if trace.turns else 0
            reverts = slicer.detect_semantic_revert(trace)
            mut_patch = slicer._build_mutations_patch(trace.turns)
            at_t_y = ""
            surv_diff = ""
            nudge = ""
            surv_ratio: float | None = None
            if reverts:
                at_t_y = reverts[0].at_t_y_diff
                surv_diff = reverts[0].survival_t_y1_diff
                nudge = reverts[0].user_nudge_text
                surv_ratio = reverts[0].survival_ratio
            elif mut_patch:
                at_t_y = mut_patch

            item = TrajectorySlice(
                slice_id=case_id,
                session_id=trace.session_id,
                domain=trace.domain,
                thrash_type="MANUAL_REVIEW",
                t_start=0,
                t_y=end,
                t_y1=end,
                turn_count=len(trace.turns),
                error_count=sum(t.has_errors for t in trace.turns),
                survival_ratio=surv_ratio,
                summary="Manual review: look for useful reusable work as well as problems. No failure or improvement is assumed.",
                touched_files=trace.touched_paths,
                at_t_y_diff=at_t_y,
                survival_t_y1_diff=surv_diff,
                user_nudge_text=nudge,
            )
            slicer.populate_case_workspace(case_dir, trace, item)
            (case_dir / "source.json").write_text(json.dumps({"source": source}), encoding="utf-8")
            # Render all normalized turns with bounded read_file dumps so proposers see the entire
            # session (turns 0..N) with `(turn k)` anchors instead of hitting raw_trajectory_md truncation.
            (case_dir / "trajectory.md").write_text(
                slicer.render_trace_markdown(
                    trace, obs_trunc=4_000, read_obs_trunc=1_200, max_chars=0
                ),
                encoding="utf-8",
            )

            triage_report: TriageReport | None = None
            if bool(use_triage):
                triage_report, _ = self.triage_session(trace, substrate=sub)
                (case_dir / "triage.json").write_text(
                    json.dumps(triage_report.to_dict(), indent=2),
                    encoding="utf-8",
                )

            leases = self.run_propose(
                case_id,
                domain=trace.domain,
                substrate=sub,
                touched_files=trace.touched_paths,
                triage_report=triage_report,
                spotlight_only=True,
                respect_active_slots=False,
            )

            lines = [
                "# Square session review",
                "",
                f"Session: `{trace.session_id}`  |  Case ID: `{case_id}`",
                "",
                "These are untested proposals. No project harness files were changed and no generated scripts were executed.",
                "",
            ]
            if triage_report is not None:
                lines += [render_triage_markdown(triage_report), ""]
            for lease in leases:
                lines += [
                    f"## {lease.dimension} proposal (`{lease.lease_id}`)",
                    "",
                    lease.proposer_notes or "No explanation returned.",
                    "",
                    "### Proposed file changes",
                    "",
                ]
                for rel in lease.component_paths:
                    before = lease.base_tree.get(rel, "")
                    after = lease.candidate_tree.get(rel, "")
                    lines += [
                        f"**{rel}**",
                        "",
                        "````diff",
                        "".join(
                            difflib.unified_diff(
                                before.splitlines(True),
                                after.splitlines(True),
                                fromfile="before/" + rel,
                                tofile="proposed/" + rel,
                            )
                        ),
                        "````",
                        "",
                    ]
            outcomes = []
            for path in sorted(case_dir.glob("*.outcome.json")):
                outcome = json.loads(path.read_text(encoding="utf-8"))
                outcomes.append(outcome)
                lines += [
                    f"## {outcome['label']} outcome",
                    "",
                    outcome["status"],
                    "",
                    outcome.get("error") or outcome.get("notes") or "",
                    "",
                ]
            if not leases:
                lines += [
                    "No candidate files were produced. Check the stage outcomes below/above for no-change decisions or errors.",
                    "",
                ]
            else:
                lines += [
                    "## Adopt & Probe",
                    "",
                    f"- Materialize all proposals for live probing: `square apply {case_id}`",
                ]
                dims_present = {l.dimension for l in leases}
                if "INV" in dims_present:
                    lines.append(f"- Materialize `INV` only: `square apply {case_id} --inv`")
                if "DOM" in dims_present:
                    lines.append(f"- Materialize `DOM` only: `square apply {case_id} --dom`")
                lines.append(f"- Revert active probe leases cleanly: `square apply {case_id} --revert`")
                lines.append("")
            if any(o["status"] == "failed" for o in outcomes):
                lines += [
                    "**One or more editor stages failed. This is not evidence that the session needed no improvement.**",
                    "",
                ]
            lines += [
                "## Evidence",
                "",
                f"Full saved source: `{self.evidence.root / 'sources' / (source + '.json')}`",
                "",
                "Candidate versions and stage outcomes are saved beside this report.",
            ]
            report_path.write_text("\n".join(lines), encoding="utf-8")
            return report_path

    def _load_base_rollout(self, case_dir: Path) -> tuple[str, RolloutEvidence]:
        slice_path = case_dir / "slice.json"
        if not slice_path.is_file():
            slice_path = case_dir / "slice_meta.json"
        meta: dict = {}
        if slice_path.is_file():
            try:
                meta = json.loads(slice_path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                meta = {}
        task_md = str(meta.get("task_prompt") or "")
        if not task_md:
            task_md = (
                (case_dir / "task.md").read_text(encoding="utf-8")
                if (case_dir / "task.md").is_file()
                else f"# Case {case_dir.name}\n"
            )
        traj_path = case_dir / "trajectory.md"
        if not traj_path.is_file():
            traj_path = case_dir / "runs" / "base1" / "trajectory.md"
        traj = traj_path.read_text(encoding="utf-8") if traj_path.is_file() else ""

        deliv_files: dict[str, str] = {}
        if meta:
            if meta.get("at_t_y_diff"):
                deliv_files["at_T_Y.patch"] = str(meta["at_t_y_diff"])
            if meta.get("survival_t_y1_diff"):
                deliv_files["git_survival.patch"] = str(meta["survival_t_y1_diff"])
            if meta.get("user_nudge_text"):
                deliv_files["user_nudge.txt"] = str(meta["user_nudge_text"])
            if meta.get("summary"):
                deliv_files["slice_summary.md"] = str(meta["summary"])
        else:
            deliv_dir = case_dir / "runs" / "base1" / "deliverables"
            if deliv_dir.is_dir():
                for p in sorted(deliv_dir.iterdir()):
                    if p.is_file():
                        deliv_files[p.name] = p.read_text(encoding="utf-8", errors="replace")
        return task_md, RolloutEvidence(
            label="base1",
            trajectory_md=traj,
            deliverable_files=deliv_files,
        )

    def _record_probe_rollout(
        self,
        lease: Lease,
        trace: SessionTrace,
        act: ActivationResult,
    ) -> Path:
        case_dir = self.cases_dir / lease.case_id
        probe_dir = case_dir / "probes" / lease.lease_id
        probe_dir.mkdir(parents=True, exist_ok=True)

        traj_md = slicer.render_trace_markdown(
            trace, obs_trunc=4_000, read_obs_trunc=1_200, max_chars=0
        )
        header = (
            f"<!-- PROBE SESSION: {trace.session_id} | LEASE: {lease.lease_id} | "
            f"OUTCOME: {act.outcome} | MATCHED: {', '.join(act.matched_reasons)} | "
            f"INVOKED: {', '.join(act.invoked_reasons) or 'none'} -->\n\n"
        )
        (probe_dir / "rollout.md").write_text(header + traj_md, encoding="utf-8")

        intra_reverts = slicer.detect_semantic_revert(trace)
        mech_thrash = slicer.detect_mechanical_thrash(trace)
        survival_ratio = intra_reverts[0].survival_ratio if intra_reverts else 1.0

        produced_lines = [
            f"# Activation Probe Summary (`{lease.lease_id}`)",
            f"- **Session ID**: `{trace.session_id}`",
            f"- **Outcome**: `OUTCOME: {act.outcome}`",
            f"- **Situation Matched**: `{act.situation_matched}` ({', '.join(act.matched_reasons)})",
            f"- **Component Invoked**: `{act.component_invoked}` ({', '.join(act.invoked_reasons) or 'NOT INVOKED'})",
            f"- **Mechanical Thrash Slices in Probe**: `{len(mech_thrash)}`",
            f"- **Semantic Reverts in Probe**: `{len(intra_reverts)}`",
            f"- **Probe Survival Ratio at $T_{{Y+1}}$**: `{survival_ratio:.2%}`",
        ]
        (probe_dir / "produced.md").write_text("\n".join(produced_lines) + "\n", encoding="utf-8")
        return probe_dir

    def run_propose(
        self,
        case_id: str,
        domain: str = "default",
        substrate: Substrate | str | None = None,
        touched_files: list[str] | None = None,
        triage_report: TriageReport | None = None,
        *,
        spotlight_only: bool = False,
        respect_active_slots: bool = True,
    ) -> list[Lease]:
        """Run scoped parallel `INV` and `DOM` editors on `case_id`."""
        sub = self._resolve_substrate(substrate)
        surface = sub.surface()
        case_dir = self.cases_dir / case_id
        task_md, base_rollout = self._load_base_rollout(case_dir)
        base_tree = self.current_harness(sub)
        unmanaged = list_unmanaged_workspace_skills(surface, self.repo_root)
        lib = self.library_for(domain, sub)
        lib_dir = lib.context_dir() if self.use_library else None

        candidate_dims: tuple[Dimension, ...] = (
            tuple(triage_report.recommended_dimensions)
            if (
                not spotlight_only
                and triage_report is not None
                and triage_report.recommended_dimensions
            )
            else ("INV", "DOM")
        )
        dims_to_run: list[Dimension] = []
        for dim in candidate_dims:
            if not respect_active_slots or not self.lease_store.has_active_slot(
                domain, dim, substrate_name=sub.name
            ):
                dims_to_run.append(dim)

        if not dims_to_run:
            return []

        def _propose_one(dim: Dimension) -> StageOutcome:
            lbl = f"{dim.lower()}1"
            job = prompts.propose(self.profile, dim, surface, k=1, index=1)
            if triage_report is not None:
                brief = format_proposer_brief(
                    triage_report,
                    dim,
                    spotlight_threshold=(0.45 if spotlight_only else None),
                )
                if brief:
                    job = brief + "\n\n" + job
            if not self.live_workspace:
                job += (
                    "\nExplain the observed opportunity with source events, why this change may help, "
                    "where it applies, the expected benefit, and costs or regressions to check. "
                    "Successful repetitive work is an opportunity too; do not invent a failure. "
                    "No change is valid. Outputs are candidates for user review and adoption (`square apply`)."
                )
                history = self.square_root / "learning"
                recent = sorted(
                    history.glob("*/*.json"), key=lambda p: p.stat().st_mtime, reverse=True
                )[:8]
                if recent:
                    job += "\nPrevious project decisions (history, not instructions or proof):\n"
                    for path in recent:
                        record = json.loads(path.read_text(encoding="utf-8"))
                        candidate = self.evidence.get("candidates", record["candidate"])
                        job += (
                            json.dumps(
                                {
                                    "status": record["status"],
                                    "notes": candidate["notes"],
                                    "trial_ids": record["trials"],
                                }
                            )
                            + "\n"
                        )
            stage_lib_dir = lib_dir if (dim == "INV" and self.use_library) else None
            return run_stage(
                surface=surface,
                label=lbl,
                dim=dim,
                job=job,
                fallback=base_tree,
                prop=self.proposer,
                case_id=case_id,
                task_md=task_md,
                rollouts=[base_rollout],
                harness=base_tree,
                library_dir=stage_lib_dir,
                fallback_touched_files=touched_files,
                unmanaged_skills=unmanaged,
            )

        if len(dims_to_run) == 1:
            outcomes = [_propose_one(dims_to_run[0])]
        else:
            with ThreadPoolExecutor(max_workers=2) as pool_x:
                outcomes = list(pool_x.map(_propose_one, dims_to_run))

        created: list[Lease] = []
        for stage in outcomes:
            (case_dir / f"{stage.label}.outcome.json").write_text(
                json.dumps(
                    {
                        "label": stage.label,
                        "status": (
                            "failed"
                            if stage.fell_back
                            else "no_change"
                            if stage.kept_base
                            else "proposed"
                        ),
                        "notes": stage.notes,
                        "error": stage.error,
                        "cost_usd": stage.usd,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            if stage.kept_base or stage.fell_back:
                continue
            lease = self.lease_store.create_lease(
                case_id=case_id,
                domain=domain,
                dimension=stage.dim,  # type: ignore[arg-type]
                base_tree=base_tree,
                candidate_tree=stage.tree,
                trigger=stage.trigger,
                surface=surface,
                proposer_notes=stage.notes,
                activations_target=self.activations_target,
            )
            if lease is not None:
                if not self.live_workspace:
                    lease.status = "AWAITING_TRIAL"
                    version = self.evidence.candidate(
                        stage.tree,
                        case_id=case_id,
                        notes=stage.notes,
                    )
                    (case_dir / f"{stage.label}.candidate.json").write_text(
                        json.dumps({"candidate_version": version, "status": "awaiting_trial"}),
                        encoding="utf-8",
                    )
                    self.lease_store.update_lease(lease)
                elif lease.status == "ACTIVE":
                    sub.materialise_lease(self.repo_root, lease)
                created.append(lease)

        return created

    def _run_compose_with_base(
        self,
        case_id: str,
        completed_leases: Lease | Sequence[Lease],
        substrate: Substrate | str | None = None,
    ) -> tuple[StageOutcome, Tree]:
        leases = (
            [completed_leases]
            if isinstance(completed_leases, Lease)
            else list(completed_leases)
        )
        if not leases:
            raise ValueError(f"run_compose called with empty leases for {case_id!r}")
        first = leases[0]
        sub = self._resolve_substrate(substrate or first.substrate_name)
        surface = sub.surface()
        case_dir = self.cases_dir / case_id
        task_md, base_rollout = self._load_base_rollout(case_dir)

        # Revert all temporary lease blocks for this composition batch from the workspace
        for lease in leases:
            sub.revert_lease(self.repo_root, lease.lease_id, lease)
        live_base_tree = self.current_harness(sub) or sub.default_tree()
        unmanaged = list_unmanaged_workspace_skills(surface, self.repo_root)
        lib = self.library_for(first.domain, sub)

        pool_entries: list[PoolEntry] = []
        decisions: dict[str, str] = {}
        for lease in leases:
            probe_dir = case_dir / "probes" / lease.lease_id
            probe_traj = (
                (probe_dir / "rollout.md").read_text(encoding="utf-8")
                if (probe_dir / "rollout.md").is_file()
                else ""
            )
            probe_prod = (
                (probe_dir / "produced.md").read_text(encoding="utf-8")
                if (probe_dir / "produced.md").is_file()
                else ""
            )
            probe_ev = RolloutEvidence(
                label=lease.lease_id,
                trajectory_md=probe_traj,
                produced_summary=probe_prod,
            )
            rebased_cand = HT.rebase_candidate_tree(
                surface, live_base_tree, lease.base_tree, lease.candidate_tree
            )
            pool_entries.append(
                PoolEntry(
                    label=lease.lease_id,
                    candidate_tree=rebased_cand,
                    probe_rollout=probe_ev,
                )
            )
            decisions[lease.lease_id] = lease.proposer_notes

        label_suffix = "_".join(l.dimension.lower() for l in leases)
        comp_stage = run_stage(
            surface=surface,
            label=f"compose_{label_suffix}",
            dim="COMPOSE",
            job=prompts.aggregate(self.profile, surface, k=len(pool_entries), index=1),
            fallback=live_base_tree,
            prop=self.proposer,
            case_id=case_id,
            task_md=task_md,
            rollouts=[base_rollout],
            harness=live_base_tree,
            library_dir=(lib.context_dir() if self.use_library else None),
            pool=pool_entries,
            decisions=decisions,
            unmanaged_skills=unmanaged,
        )

        # Safely apply the permanently adopted tree directly into repo_root without wiping untracked user skills
        HT.apply_tree(surface, live_base_tree, comp_stage.tree, self.repo_root)
        comp_diff = HT.diff_summary(surface, live_base_tree, comp_stage.tree)
        adopted_changed = sorted(set(comp_diff["added"]) | set(comp_diff["modified"]))
        skill_prefix = surface.skill_dir + "/"
        for rel in adopted_changed:
            if rel.startswith(skill_prefix) and rel.endswith("/SKILL.md"):
                p_skill = self.repo_root / rel
                if p_skill.is_file():
                    txt = p_skill.read_text(encoding="utf-8", errors="replace")
                    if "<!-- square-managed -->" not in txt:
                        stamped = txt.rstrip() + "\n\n<!-- square-managed -->\n"
                        p_skill.write_text(stamped, encoding="utf-8")
                        comp_stage.tree[rel] = stamped

        if adopted_changed:
            record_square_managed_components(
                self.repo_root, adopted_changed, square_dir=self.square_root
            )

        for lease in leases:
            lease.status = "REVERTED" if comp_stage.kept_base else "COMPOSED"
            self.lease_store.update_lease(lease)

        # Re-apply any other still-active leases on this substrate so their tagged blocks remain present
        for rem in self.lease_store.active_leases(substrate_name=sub.name):
            sub.materialise_lease(self.repo_root, rem)

        return comp_stage, live_base_tree

    def run_compose(
        self,
        case_id: str,
        completed_leases: Lease | Sequence[Lease],
        substrate: Substrate | str | None = None,
    ) -> StageOutcome:
        """Run Contrastive Composer synthesis ($e^0$ vs. $e^{\\text{probe}}$) across all completed
        candidate leases (`INV` and/or `DOM`) for `case_id`, reverting temporary lease tags and
        safely adopting the synthesized tree into the repository's native substrate files (Invariant #6).
        """
        comp_stage, _ = self._run_compose_with_base(
            case_id, completed_leases, substrate=substrate
        )
        return comp_stage

    def try_candidate(self, version: str, input_id: str, runner) -> str:
        """Run a caller-supplied checker in a disposable exact candidate tree.

        The runner is trusted application code, not generated shell text. It receives
        (workspace, input_id) and returns completed/correct/helped/regression/details.
        """
        candidate = self.evidence.get("candidates", version)
        with tempfile.TemporaryDirectory(prefix="square-trial-") as tmp:
            root = Path(tmp)
            for rel, content in candidate["tree"].items():
                dest = (root / rel).resolve()
                if not dest.is_relative_to(root.resolve()):
                    raise ValueError("Candidate path escapes trial workspace")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
            try:
                result = runner(root, input_id)
            except Exception as exc:
                result = dict(
                    completed=False,
                    correct=None,
                    helped=None,
                    regression=None,
                    details=f"Runner failed: {type(exc).__name__}: {exc}",
                )
        return self.evidence.trial(
            version,
            input_id=input_id,
            runner=getattr(runner, "__name__", type(runner).__name__),
            **result,
        )

    def assess_candidate(self, version: str, trials: list[str]) -> dict:
        """Save all decisions; supported files stay in Square, never in the repository."""
        decision = self.evidence.assess(version, trials)
        directory = self.square_root / "learning" / decision["status"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{decision['id']}.json").write_text(
            json.dumps(decision, indent=2), encoding="utf-8"
        )
        return decision

    def compose_candidates(
        self, case_id: str, candidates: dict[str, list[str]], substrate=None
    ) -> str:
        """Compose explicitly assessed versions; output always requires its own trials."""
        sub = self._resolve_substrate(substrate)
        task, base = self._load_base_rollout(self.cases_dir / case_id)
        pool = []
        decisions = {}
        for version, trials in candidates.items():
            decision = self.evidence.assess(version, trials)
            if decision["status"] != "supported_in_recorded_trials":
                raise ValueError("Composition requires supported candidate trials")
            candidate = self.evidence.get("candidates", version)
            observations = [self.evidence.get("trials", t) for t in trials]
            pool.append(
                PoolEntry(
                    label=version,
                    candidate_tree=candidate["tree"],
                    probe_rollout=RolloutEvidence(
                        label=version, trajectory_md=json.dumps(observations, indent=2)
                    ),
                )
            )
            decisions[version] = candidate["notes"]
        if not pool:
            raise ValueError("No candidates supplied")
        current = self.current_harness(sub)
        stage = run_stage(
            surface=sub.surface(),
            label="compose",
            dim="COMPOSE",
            job=prompts.aggregate(self.profile, sub.surface(), k=len(pool)),
            fallback=current,
            prop=self.proposer,
            case_id=case_id,
            task_md=task,
            rollouts=[base],
            harness=current,
            pool=pool,
            decisions=decisions,
        )
        if stage.fell_back:
            raise ValueError(stage.error)
        return self.evidence.candidate(stage.tree, case_id=case_id, notes=stage.notes)

    def run_reflect(
        self,
        case_id: str,
        completed_leases: Lease | Sequence[Lease],
        comp_stage: StageOutcome,
        substrate: Substrate | str | None = None,
        *,
        live_base_tree: Tree | None = None,
    ) -> dict:
        """Run Level 2 Experience Reflection ($I_t \\to I_{t+1}$) strictly on `INV`-originated
        cross-project reusable components when `not comp_stage.kept_base`.
        """
        if comp_stage.kept_base:
            return {"no_entry": True}
        leases = (
            [completed_leases]
            if isinstance(completed_leases, Lease)
            else list(completed_leases)
        )
        inv_leases = [l for l in leases if l.dimension == "INV"]
        if not inv_leases:
            return {"no_entry": True}

        first = inv_leases[0]
        sub = self._resolve_substrate(substrate or first.substrate_name)
        surface = sub.surface()
        ref_base = live_base_tree if live_base_tree is not None else first.base_tree

        diff = HT.diff_summary(surface, ref_base, comp_stage.tree)
        changed_rels = sorted(set(diff["added"]) | set(diff["modified"]))

        # Compute origin-tracked `inv_delta_tree` so DOM skills/rules/facts never leak into R_t
        skill_prefix = surface.skill_dir + "/"
        skill_depth = len(surface.skill_dir.split("/")) + 1
        inv_origin_paths = {HT.normalize_rel(p) for l in inv_leases for p in l.component_paths}
        inv_skill_prefixes = {
            "/".join(p.split("/")[:skill_depth]) + "/"
            for p in inv_origin_paths
            if p.startswith(skill_prefix) and len(p.split("/")) >= skill_depth
        }
        dom_leases = [l for l in leases if l.dimension == "DOM"]
        dom_origin_paths = {HT.normalize_rel(p) for l in dom_leases for p in l.component_paths}
        dom_skill_names = {
            p.split("/")[skill_depth - 1]
            for p in dom_origin_paths
            if p.startswith(skill_prefix) and len(p.split("/")) >= skill_depth
        }

        inv_delta_tree: Tree = {}
        ao_deltas: list[str] = []
        for rel in changed_rels:
            if rel in surface.always_on:
                base_lines = {ln.strip() for ln in ref_base.get(rel, "").splitlines() if ln.strip()}
                comp_lines = comp_stage.tree.get(rel, "").splitlines()
                if not dom_leases:
                    added_ao = [
                        ln
                        for ln in comp_lines
                        if ln.strip() and ln.strip() not in base_lines
                    ]
                else:
                    inv_cand_lines: set[str] = set()
                    for il in inv_leases:
                        il_base = {
                            ln.strip()
                            for ln in il.base_tree.get(rel, "").splitlines()
                            if ln.strip()
                        }
                        for ln in il.candidate_tree.get(rel, "").splitlines():
                            if ln.strip() and ln.strip() not in il_base:
                                inv_cand_lines.add(ln.strip())
                    added_ao = [
                        ln
                        for ln in comp_lines
                        if ln.strip()
                        and ln.strip() not in base_lines
                        and (
                            ln.strip() in inv_cand_lines
                            or any(pref.rstrip("/") in ln for pref in inv_skill_prefixes)
                        )
                        and not any(
                            f"/{dn}/" in ln or f"`{dn}`" in ln for dn in dom_skill_names
                        )
                    ]
                if added_ao:
                    ao_deltas.append(f"## `{rel}` (`INV` procedural delta)\n\n" + "\n".join(added_ao))
            elif rel.startswith(skill_prefix):
                if any(rel.startswith(pref) for pref in inv_skill_prefixes):
                    inv_delta_tree[rel] = comp_stage.tree[rel]
            elif HT.is_path_allowed_for_dimension(
                surface, "INV", rel
            ) and not HT.is_path_allowed_for_dimension(surface, "DOM", rel):
                inv_delta_tree[rel] = comp_stage.tree[rel]
            elif rel in inv_origin_paths and rel not in dom_origin_paths:
                inv_delta_tree[rel] = comp_stage.tree[rel]

        extra_files: dict[str, str] = {}
        if ao_deltas:
            extra_files["ALWAYS_ON_DELTA.md"] = "\n\n".join(ao_deltas).rstrip() + "\n"

        if not inv_delta_tree and not extra_files:
            return {"no_entry": True}

        case_dir = self.cases_dir / case_id
        task_md, base_rollout = self._load_base_rollout(case_dir)

        refl_id = "_".join(l.lease_id for l in inv_leases)
        tmp_refl_dir = Path(tempfile.mkdtemp(prefix=f"square-refl-{case_id}-"))
        try:
            refl_root = tmp_refl_dir / refl_id
            pool_entries: list[PoolEntry] = []
            decisions: dict[str, str] = {comp_stage.label: comp_stage.notes}
            for lease in inv_leases:
                probe_dir = case_dir / "probes" / lease.lease_id
                probe_ev = RolloutEvidence(
                    label=lease.lease_id,
                    trajectory_md=(
                        (probe_dir / "rollout.md").read_text(encoding="utf-8")
                        if (probe_dir / "rollout.md").is_file()
                        else ""
                    ),
                    produced_summary=(
                        (probe_dir / "produced.md").read_text(encoding="utf-8")
                        if (probe_dir / "produced.md").is_file()
                        else ""
                    ),
                )
                pool_entries.append(
                    PoolEntry(
                        label=lease.lease_id,
                        candidate_tree=lease.candidate_tree,
                        probe_rollout=probe_ev,
                    )
                )
                decisions[lease.lease_id] = lease.proposer_notes

            ctx_tree = context.build(
                refl_root,
                case_id,
                task_md,
                [base_rollout],
                surface=surface,
                harness=inv_delta_tree,
                pool=pool_entries,
                decisions=decisions,
            )
            for fname, fcontent in extra_files.items():
                (refl_root / "harness" / fname).write_text(fcontent, encoding="utf-8")
            HT.write_tree(
                surface,
                ref_base,
                refl_root / "base_harness",
                stubs=False,
                ensure_always_on=False,
            )
            (refl_root / "adoption.json").write_text(
                json.dumps(
                    {
                        "case_id": case_id,
                        "lease_ids": [l.lease_id for l in inv_leases],
                        "substrate": sub.name,
                        "dimensions": ["INV"],
                        "kept_base": comp_stage.kept_base,
                        "composer_notes": comp_stage.notes,
                        "probe_outcomes": {l.lease_id: l.probe_outcomes for l in inv_leases},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            lease_summary = ", ".join(
                f"`{l.lease_id}` ({l.dimension}, sessions={l.probe_sessions}, outcomes={l.probe_outcomes})"
                for l in inv_leases
            )
            mission_str = "\n\n".join(
                [
                    prompts.experience(self.profile),
                    "# WHAT HAPPENED\n\n"
                    f"Candidate INV lease(s) {lease_summary} on `{sub.name}` surface were probed in live sessions.\n"
                    f"Composer decision (`kept_base={comp_stage.kept_base}`):\n\n{comp_stage.notes}\n\n"
                    "Compare `context/harness/` (adopted cross-project INV delta) with `context/base_harness/` and "
                    "`context/pool/`. Record strictly reusable cross-project operational mechanics (never repo-specific DOM facts).\n\n"
                    + ctx_tree.layout,
                ]
            )

            try:
                reply = self.proposer.call(
                    mission_str,
                    refl_root,
                    f"experience.{case_id}.{refl_id}",
                )
            except ProposerError:
                return {}
        finally:
            shutil.rmtree(tmp_refl_dir, ignore_errors=True)

        parsed = prompts.parse_reflection_reply(reply.text)
        applied_inv_comps = sorted(inv_delta_tree.keys()) + sorted(extra_files.keys())
        inv_why = (
            "; ".join(l.proposer_notes for l in inv_leases if l.proposer_notes)
            if dom_leases
            else comp_stage.notes
        ) or comp_stage.notes
        lib = self.library_for(first.domain, sub)
        lib.add(
            case_id,
            inv_delta_tree,
            why=inv_why,
            label=comp_stage.label,
            run_id=refl_id,
            experience=parsed,
            applied_components=applied_inv_comps,
            extra_files=extra_files,
        )
        return parsed
