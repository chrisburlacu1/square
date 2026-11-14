"""Lease state machine, Tier 1/Tier 2 classification on any `SurfaceSpec`, Windows-safe file
locking, and deterministic Two-Bit `ActivationTrigger` matcher ($A_1, A_2$).

Enforces Invariant #5 (Parallel Lease Slots `lease_inv`, `lease_dom`),
Invariant #7 (Situation-Based `ActivationTrigger` Matching & `OUTCOME: IGNORED_BY_AGENT`),
and Invariant #9 (Windows-Safe File Locking via `msvcrt` / `fcntl`).
"""

from __future__ import annotations

import contextlib
import fnmatch
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Iterator

from . import tree as HT
from .schemas import (
    ActivationResult,
    ActivationTrigger,
    Dimension,
    Lease,
    LeaseTier,
    SessionTrace,
)
from .substrates import SURFACE_MAP
from .substrates.antigravity import AGY_SURFACE
from .tree import SurfaceSpec, Tree

_THREAD_LOCK = threading.RLock()


@contextlib.contextmanager
def file_lock(lock_path: Path | str) -> Iterator[None]:
    """Portable cross-process and intra-process lock using `threading.RLock` + `msvcrt`/`fcntl`."""
    p = Path(lock_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK:
        fh = p.open("a+b")
        try:
            fh.seek(0)
            if os.name == "nt":
                import msvcrt

                locked = False
                for _ in range(50):
                    try:
                        fh.seek(0)
                        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                        locked = True
                        break
                    except OSError:
                        time.sleep(0.01)
                if not locked:
                    raise TimeoutError(f"Could not acquire lock: {p}")
                try:
                    yield
                finally:
                    if locked:
                        try:
                            fh.seek(0)
                            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                        except OSError:
                            pass
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def classify_tier(changed_paths: list[str], surface: SurfaceSpec = AGY_SURFACE) -> LeaseTier:
    """Classify proposed diff on `surface` into Tier 1 (pure markdown in `always_on` or
    `<skill_dir>/*/SKILL.md` -> auto-leased immediately into the repo's native harness files)
    vs. Tier 2 (`scripts/*.py`, `hooks_file`, `plugin_dir`, `sub_agents/*.md`, or skill scripts
    -> staged in `.square/drafts/<lease_id>/` until approved).
    """
    for rel in changed_paths:
        norm = HT.normalize_rel(rel)
        if (
            norm.startswith("scripts/")
            or norm.startswith("sub_agents/")
            or (surface.hooks_file is not None and norm == surface.hooks_file)
            or (surface.plugin_dir is not None and norm.startswith(surface.plugin_dir + "/"))
            or "/scripts/" in norm
            or norm.endswith((".py", ".ts", ".json"))
        ):
            return "TIER_2"
    return "TIER_1"


def match_activation(
    trace: SessionTrace,
    lease: Lease,
    surface: SurfaceSpec | None = None,
) -> ActivationResult:
    """Evaluate the Two-Bit Activation Check (Invariant #7) on a SessionTrace:
      1. `situation_matched`: Did the session touch `path_globs`, run `command_regex`, or mention `cue_keywords`?
      2. `component_invoked`: Did the agent invoke the leased skill/script/hook or apply the leased pattern?

    If `situation_matched == False`: Unrelated session; lease clock does NOT tick (`UNRELATED_SESSION`).
    If `situation_matched == True` and `component_invoked == True`: `ACTIVATED_AND_INVOKED`.
    If `situation_matched == True` and `component_invoked == False`: `IGNORED_BY_AGENT`.
    """
    if surface is None:
        surface = SURFACE_MAP.get(lease.substrate_name, AGY_SURFACE)

    trig = lease.trigger
    matched_reasons: list[str] = []
    invoked_reasons: list[str] = []

    touched = trace.touched_paths
    commands = trace.executed_commands
    cue_parts: list[str] = [trace.task_prompt]
    cue_parts.extend(commands)
    cue_parts.extend(touched)
    for t in trace.turns:
        cue_parts.append(t.text)
        cue_parts.append(t.reasoning)
    if not trace.turns and trace.raw_trajectory_md:
        cue_parts.append(trace.raw_trajectory_md)
    full_corpus = "\n".join(p for p in cue_parts if p)
    full_corpus_lower = full_corpus.lower()

    # 1. Check situation_matched
    for glob_pat in trig.path_globs:
        pat = glob_pat.replace("\\", "/").lstrip("./")
        for tp in touched:
            norm_tp = tp.replace("\\", "/")
            if (
                fnmatch.fnmatch(norm_tp, pat)
                or ("/" not in pat and fnmatch.fnmatch(Path(norm_tp).name, pat))
                or (pat.startswith("**/") and fnmatch.fnmatch(norm_tp, pat[3:]))
            ):
                matched_reasons.append(f"path_glob:{glob_pat} matched {norm_tp}")
                break

    if trig.command_regex:
        try:
            rx = re.compile(trig.command_regex, re.I)
            for cmd in commands:
                if rx.search(cmd):
                    matched_reasons.append(f"command_regex matched `{cmd[:80]}`")
                    break
        except re.error:
            pass

    for kw in trig.cue_keywords:
        if kw.lower() in full_corpus_lower:
            matched_reasons.append(f"cue_keyword:{kw!r}")

    situation_matched = bool(matched_reasons)
    if not situation_matched:
        return ActivationResult(
            lease_id=lease.lease_id,
            situation_matched=False,
            component_invoked=False,
            outcome="UNRELATED_SESSION",
        )

    # 2. Check component_invoked
    skill_prefix = surface.skill_dir.rstrip("/") + "/"
    always_on_reasons: list[str] = []
    has_on_demand_component = False

    for comp_path in lease.component_paths:
        norm = HT.normalize_rel(comp_path)
        if norm.startswith(skill_prefix) and norm.endswith("/SKILL.md"):
            has_on_demand_component = True
            skill_name = norm[len(skill_prefix) :].split("/")[0]
            skill_rel_lower = norm.lower()
            skill_scripts_prefix = f"{skill_prefix}{skill_name}/scripts/".lower()
            matched_skill = False

            for t in trace.turns:
                if t.role != "assistant":
                    continue
                for tc in t.tool_calls:
                    tname_low = tc.tool_name.lower()
                    target_norm = (tc.command_or_target or "").replace("\\", "/").lower()
                    args_norm = json.dumps(tc.arguments).replace("\\\\", "/").lower()
                    combined_tc = f"{target_norm} {args_norm}"

                    # 1. Reading or targeting `<skill_dir>/<name>/SKILL.md`
                    if skill_rel_lower in combined_tc or f"/{skill_name.lower()}/skill.md" in combined_tc:
                        invoked_reasons.append(
                            f"skill `{norm}` read/targeted via `{tc.tool_name}`"
                        )
                        matched_skill = True
                        break

                    # 2. Dedicated `skill` / `use_skill` tool naming `<name>`
                    if tname_low in ("skill", "use_skill", "load_skill", "invoke_skill") and (
                        skill_name.lower() in combined_tc
                    ):
                        invoked_reasons.append(
                            f"skill {skill_name!r} invoked via `{tc.tool_name}`"
                        )
                        matched_skill = True
                        break

                    # 3. Executing a bundled script under `<skill_dir>/<name>/scripts/`
                    if skill_scripts_prefix in combined_tc:
                        invoked_reasons.append(
                            f"bundled script under `{skill_prefix}{skill_name}/scripts/` executed"
                        )
                        matched_skill = True
                        break
                if matched_skill:
                    break

        elif (norm.startswith("scripts/") or "/scripts/" in norm) and norm.endswith(".py"):
            has_on_demand_component = True
            script_base = Path(norm).name
            for cmd in commands:
                cmd_norm = cmd.replace("\\", "/")
                if norm in cmd_norm or script_base in cmd_norm:
                    invoked_reasons.append(f"script `{norm}` executed")
                    break

        elif norm.startswith("sub_agents/") and norm.endswith("/AGENT.md"):
            has_on_demand_component = True
            agent_name = norm.split("/")[1]
            for t in trace.turns:
                if t.role != "assistant":
                    continue
                for tc in t.tool_calls:
                    if agent_name.lower() in (
                        f"{tc.tool_name} {tc.command_or_target} {json.dumps(tc.arguments)}"
                    ).lower():
                        invoked_reasons.append(f"sub_agent {agent_name!r} invoked")
                        break

        elif (surface.hooks_file and norm == surface.hooks_file) or (
            surface.plugin_dir and norm.startswith(surface.plugin_dir + "/")
        ):
            has_on_demand_component = True
            invoked_reasons.append("hook/plugin active in tool loop")

        elif norm in surface.always_on or (
            surface.rules_dir is not None and norm.startswith(surface.rules_dir + "/")
        ):
            always_on_reasons.append(f"always-on rule `{norm}` mounted in prompt")

    if invoked_reasons:
        return ActivationResult(
            lease_id=lease.lease_id,
            situation_matched=True,
            component_invoked=True,
            outcome="ACTIVATED_AND_INVOKED",
            matched_reasons=matched_reasons,
            invoked_reasons=invoked_reasons + always_on_reasons,
        )

    if always_on_reasons and not has_on_demand_component:
        return ActivationResult(
            lease_id=lease.lease_id,
            situation_matched=True,
            component_invoked=True,
            outcome="MOUNTED_ALWAYS_ON",
            matched_reasons=matched_reasons,
            invoked_reasons=always_on_reasons,
        )

    return ActivationResult(
        lease_id=lease.lease_id,
        situation_matched=True,
        component_invoked=False,
        outcome="IGNORED_BY_AGENT",
        matched_reasons=matched_reasons,
        invoked_reasons=[],
    )


def _extract_added_lines(before: str, after: str) -> str:
    b_set = {ln.strip() for ln in before.splitlines() if ln.strip()}
    added = [ln.strip() for ln in after.splitlines() if ln.strip() and ln.strip() not in b_set]
    return "\n".join(added)


def _distinctive_tokens(text: str) -> list[str]:
    stop = {
        "when",
        "load",
        "read",
        "follow",
        "skill",
        "always",
        "never",
        "before",
        "after",
        "with",
        "from",
        "that",
        "this",
        "workspace",
        "invariants",
        "guardrails",
        "workflow",
        "domain",
        "architecture",
        "must",
        "should",
        "check",
        "verify",
        "file",
        "files",
        "agents",
        "claude",
        "gemini",
    }
    words = re.findall(r"[A-Za-z0-9_.\-/]{4,}", text)
    out: list[str] = []
    for w in words:
        clean = w.strip("._-/")
        if len(clean) >= 4 and clean.lower() not in stop and clean not in out:
            out.append(clean)
    return out


class LeaseStore:
    """Manages `.square/leases.json` and `.square/drafts/<lease_id>/`."""

    def __init__(self, square_dir: Path | str):
        self.square_dir = Path(square_dir)
        self.leases_path = self.square_dir / "leases.json"
        self.lock_path = self.square_dir / "leases.lock"
        self.drafts_dir = self.square_dir / "drafts"

    def load_all(self) -> list[Lease]:
        with file_lock(self.lock_path):
            return self._read_unlocked()

    def _read_unlocked(self) -> list[Lease]:
        if not self.leases_path.is_file():
            return []
        try:
            raw = json.loads(self.leases_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return [Lease.from_dict(item) for item in raw if isinstance(item, dict)]
        except (json.JSONDecodeError, KeyError):
            pass
        return []

    def _write_unlocked(self, leases: list[Lease]) -> None:
        self.square_dir.mkdir(parents=True, exist_ok=True)
        self.leases_path.write_text(
            json.dumps([l.to_dict() for l in leases], indent=2), encoding="utf-8"
        )

    def save_all(self, leases: list[Lease]) -> None:
        with file_lock(self.lock_path):
            self._write_unlocked(leases)

    def active_leases(self, domain: str | None = None, substrate_name: str | None = None) -> list[Lease]:
        del domain
        return [
            l
            for l in self.load_all()
            if l.status == "ACTIVE"
            and (substrate_name is None or l.substrate_name == substrate_name)
        ]

    def staged_leases(self, domain: str | None = None) -> list[Lease]:
        del domain
        return [l for l in self.load_all() if l.status == "STAGED_TIER_2"]

    def has_active_slot(
        self, domain: str | None = None, dimension: Dimension = "INV", substrate_name: str | None = None
    ) -> bool:
        del domain
        return any(
            l.status == "ACTIVE"
            and l.dimension == dimension
            and (substrate_name is None or l.substrate_name == substrate_name)
            for l in self.load_all()
        )

    def create_lease(
        self,
        *,
        case_id: str,
        domain: str = "default",
        dimension: Dimension,
        base_tree: Tree,
        candidate_tree: Tree,
        trigger: ActivationTrigger,
        surface: SurfaceSpec = AGY_SURFACE,
        proposer_notes: str = "",
        activations_target: int = 1,
    ) -> Lease | None:
        """Create and persist a Lease if `candidate_tree` differs from `base_tree` on `surface`.
        Tier 1 leases become `ACTIVE` immediately; Tier 2 leases are staged in `.square/drafts/<lease_id>/`.
        """
        diff = HT.diff_summary(surface, base_tree, candidate_tree)
        changed = sorted(set(diff["added"]) | set(diff["removed"]) | set(diff["modified"]))
        if not changed:
            return None

        tier = classify_tier(changed, surface)
        status = "ACTIVE" if tier == "TIER_1" else "STAGED_TIER_2"
        lease_id = f"{case_id}_{dimension.lower()}"

        lease = Lease(
            lease_id=lease_id,
            case_id=case_id,
            domain=domain,
            dimension=dimension,
            tier=tier,
            status=status,
            component_paths=changed,
            trigger=trigger,
            substrate_name=surface.name,
            candidate_tree=dict(candidate_tree),
            base_tree=dict(base_tree),
            proposer_notes=proposer_notes,
            activations_completed=0,
            activations_target=activations_target,
        )

        with file_lock(self.lock_path):
            all_leases = [l for l in self._read_unlocked() if l.lease_id != lease_id]
            all_leases.append(lease)
            self._write_unlocked(all_leases)

        if tier == "TIER_2":
            draft_dir = self.drafts_dir / lease_id
            HT.write_tree(surface, candidate_tree, draft_dir / "harness", stubs=False)
            (draft_dir / "meta.json").write_text(
                json.dumps(lease.to_dict(), indent=2), encoding="utf-8"
            )

        return lease

    def approve_tier2(self, lease_id: str) -> Lease:
        """Promote a `STAGED_TIER_2` lease to `ACTIVE` so it enters live probing."""
        with file_lock(self.lock_path):
            leases = self._read_unlocked()
            for l in leases:
                if l.lease_id == lease_id:
                    l.status = "ACTIVE"
                    self._write_unlocked(leases)
                    return l
        raise KeyError(f"No lease found with id {lease_id!r}")

    def update_lease(self, updated: Lease) -> None:
        with file_lock(self.lock_path):
            leases = self._read_unlocked()
            for i, l in enumerate(leases):
                if l.lease_id == updated.lease_id:
                    leases[i] = updated
                    break
            else:
                leases.append(updated)
            self._write_unlocked(leases)
