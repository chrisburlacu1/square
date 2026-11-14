"""The evidence tree an agentic proposer reads. The only way evidence reaches a model.

Adapted from `reference/harness2/harness2/core/context.py`.
Implements Invariant #2 (Full `harness2` Prompt Core + $T_Y / T_{Y+1}$ as Deliverable Evidence):
    context/task.md                  the task / user request as the agent received it
    context/rollouts/<label>.md      full trajectory -- no prompt-budget truncation
    context/deliverables/<label>/    the git diff at T_Y, survival diff at T_{Y+1}, and slice summary
    context/harness/<rel>            the c1..c8 tree being edited
    context/library/INDEX.md         earlier cases in this domain + their full harnesses + EDITOR_LESSONS.md
    context/pool/<label>/            candidate harness + its harness.diff + probe rollout (compose / reflect)
    MISSION.md                       what to do with all of it
"""

from __future__ import annotations

import difflib
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from . import library as harness_library
from . import tree as harness_tree
from .substrates.antigravity import AGY_SURFACE
from .tree import SurfaceSpec

INLINE_FILE_MAX_CHARS = 32_000


@dataclass
class RolloutEvidence:
    """One session execution (either base $e^0$ or activation probe $e^{\\text{probe}}$)."""

    label: str
    trajectory_md: str
    deliverable_files: dict[str, str] = field(default_factory=dict)
    produced_summary: str = ""


@dataclass
class PoolEntry:
    """One candidate harness in `context/pool/<label>/` plus its activation probe rollout."""

    label: str
    candidate_dir: Path | None = None
    probe_rollout: RolloutEvidence | None = None
    candidate_tree: harness_tree.Tree | None = None


@dataclass
class ContextTree:
    """A built evidence tree, plus what actually landed in it."""

    root: Path
    case_id: str
    rollouts: list[str]
    deliverables: list[str]
    harness_files: int
    library: bool
    pool: list[str]
    failed: list[str] = field(default_factory=list)
    decisions: int = 0
    unmanaged_skills: list[dict[str, str]] = field(default_factory=list)

    @property
    def layout(self) -> str:
        """The evidence-layout listing that goes in the mission; only mentions what exists."""
        lines = ["context/task.md                  the user request / session task"]
        if self.decisions:
            lines.append("context/decisions/              earlier edits and composition decisions")
        if self.rollouts:
            names = ", ".join(f"{r}.md" for r in self.rollouts[:6])
            more = f" (+{len(self.rollouts) - 6} more)" if len(self.rollouts) > 6 else ""
            lines.append(f"context/rollouts/               FULL session trajectories: {names}{more}")
        if self.deliverables:
            lines.append(
                "context/deliverables/<label>/    deliverable evidence at T_Y and survival diff at T_{Y+1} "
                "(browse INDEX.md for the set)"
            )
        if self.harness_files:
            lines.append(
                f"context/harness/                the harness you are editing "
                f"({self.harness_files} files)"
            )
        if self.pool:
            lines.append(
                f"context/pool/                   {len(self.pool)} candidate(s), each "
                f"with its `harness/`, `harness.diff`, and activation probe `rollout.md`"
            )
        if self.library:
            lines.append(
                "context/library/                Continual Improvement Library -- browse "
                "INDEX.md first, then open harnesses/<id>/EXPERIENCE.md that look relevant"
            )
        return "\n".join(lines)


def build(
    dest: Path | str,
    case_id: str,
    task_md: str,
    rollouts: Sequence[RolloutEvidence] = (),
    *,
    surface: SurfaceSpec = AGY_SURFACE,
    harness: harness_tree.Tree | None = None,
    harness_dir: Path | None = None,
    library_dir: Path | None = None,
    pool: Sequence[PoolEntry] = (),
    decisions: Mapping[str, str] | None = None,
    unmanaged_skills: Sequence[Mapping[str, str]] = (),
) -> ContextTree:
    """Write the evidence tree; return what landed, so the mission describes only that."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    (dest / "task.md").write_text(task_md or f"# Case {case_id}\n", encoding="utf-8")

    for label, notes in (decisions or {}).items():
        path = dest / "decisions" / f"{label}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(notes or "No decision notes returned.", encoding="utf-8")

    got_r: list[str] = []
    got_d: list[str] = []
    if rollouts:
        (dest / "rollouts").mkdir(exist_ok=True)
        (dest / "deliverables").mkdir(exist_ok=True)

    for r in rollouts:
        (dest / "rollouts" / f"{r.label}.md").write_text(
            r.trajectory_md or "(empty trajectory)", encoding="utf-8"
        )
        got_r.append(r.label)
        _write_deliverables(dest, r)
        got_d.append(r.label)

    n_h = 0
    if harness is not None:
        harness_tree.write_tree(surface, harness, dest / "harness", stubs=True)
        n_h = len(harness)
    elif harness_dir and Path(harness_dir).is_dir():
        n_h = _copy_tree(Path(harness_dir), dest / "harness")

    got_p = _write_pool(dest, pool, surface)

    lib = False
    if library_dir and Path(library_dir).is_dir() and any(Path(library_dir).iterdir()):
        shutil.copytree(library_dir, dest / "library", dirs_exist_ok=True)
        lib = True

    return ContextTree(
        root=dest,
        case_id=case_id,
        rollouts=got_r,
        deliverables=got_d,
        harness_files=n_h,
        library=lib,
        pool=got_p,
        decisions=len(decisions or {}),
        unmanaged_skills=[dict(s) for s in unmanaged_skills],
    )


def _write_deliverables(dest: Path, r: RolloutEvidence) -> None:
    d = dest / "deliverables" / r.label
    d.mkdir(parents=True, exist_ok=True)
    files = dict(r.deliverable_files)
    if not files:
        files = {"summary.txt": r.produced_summary or "(no deliverable patch recorded)"}
    for name, body in files.items():
        safe = str(name).replace("/", "__").replace("\\", "__") or "unnamed.txt"
        suffix = "" if safe.endswith((".txt", ".md", ".patch", ".diff")) else ".txt"
        (d / f"{safe}{suffix}").write_text(str(body), encoding="utf-8")
    (d / "INDEX.md").write_text(
        f"# {r.label} deliverable & survival evidence ({len(files)} file(s))\n\n"
        + "\n".join(f"- `{n}`  ({len(str(b)):,} chars)" for n, b in files.items())
        + "\n\nIn interactive coding, `at_T_Y.patch.txt` shows what the agent produced at "
        "mechanical convergence ($T_Y$), and `git_survival_T_Y1.patch.txt` shows whether "
        "those lines survived user pushback or subsequent edits ($T_{Y+1}$).\n",
        encoding="utf-8",
    )


def _write_pool(
    dest: Path,
    pool: Sequence[PoolEntry],
    surface: SurfaceSpec,
) -> list[str]:
    """Write each pool candidate's harness, `harness.diff`, and activation probe rollout."""
    got: list[str] = []
    for entry in pool:
        d = dest / "pool" / entry.label
        d.mkdir(parents=True, exist_ok=True)
        candidate: harness_tree.Tree | None = None
        if entry.candidate_tree is not None:
            candidate = dict(entry.candidate_tree)
            harness_tree.write_tree(surface, candidate, d / "harness", stubs=False)
        elif entry.candidate_dir and Path(entry.candidate_dir).is_dir():
            _copy_tree(Path(entry.candidate_dir), d / "harness")
            candidate = harness_tree.read_tree(surface, entry.candidate_dir)
        if candidate is not None:
            reference = harness_tree.read_tree(surface, dest / "harness")
            diff = "".join(
                line
                for name in sorted(reference.keys() | candidate.keys())
                for line in difflib.unified_diff(
                    reference.get(name, "").splitlines(keepends=True),
                    candidate.get(name, "").splitlines(keepends=True),
                    fromfile=f"current/{name}",
                    tofile=f"{entry.label}/{name}",
                )
            )
            (d / "harness.diff").write_text(diff, encoding="utf-8")
        if entry.probe_rollout is not None:
            (d / "rollout.md").write_text(
                entry.probe_rollout.trajectory_md or "(empty probe trajectory)",
                encoding="utf-8",
            )
            produced = entry.probe_rollout.produced_summary
            if not produced and entry.probe_rollout.deliverable_files:
                produced = "\n\n".join(
                    f"## {k}\n{v}" for k, v in entry.probe_rollout.deliverable_files.items()
                )
            (d / "produced.md").write_text(produced or "(nothing produced)", encoding="utf-8")
        got.append(entry.label)
    return got


def _copy_tree(src: Path, dst: Path) -> int:
    """Copy a component tree, dropping byte-compiled files; return the file count."""
    n = 0
    for p in sorted(src.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        t = dst / p.relative_to(src)
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, t)
        n += 1
    return n


def _summarize_harness_for_mission(harness_dir: Path) -> str:
    """Build an inline digest of `context/harness/` so the proposer sees `GEMINI.md` (or always-on files),
    rules, and every existing skill's `name`, `description`, and section headings up front without
    burning 6-10 sequential `read_file` turns inspecting unrelated skills.
    """
    if not harness_dir.is_dir():
        return ""
    lines: list[str] = []
    for p in sorted(harness_dir.rglob("*")):
        if not p.is_file() or p.name == "README.md" or "__pycache__" in p.parts:
            continue
        rel = str(p.relative_to(harness_dir)).replace("\\", "/")
        body = p.read_text(encoding="utf-8", errors="replace")
        if rel.endswith("SKILL.md") and len(body) > 1_200:
            fm, rest = harness_library.parse_frontmatter(body)
            desc = str(fm.get("description") or "").strip().replace("\n", " ")
            headings = [
                ln.strip()
                for ln in rest.splitlines()
                if ln.strip().startswith("#")
            ][:10]
            lines.append(
                f"### `context/harness/{rel}` ({len(body):,} chars -- on-demand skill summary)\n"
                f"- **description**: {desc}\n"
                f"- **headings**: {', '.join(f'`{h}`' for h in headings) or '(none)'}\n"
                f"*(Open `context/harness/{rel}` ONLY if you intend to edit or extend this specific skill.)*"
            )
        else:
            lines.append(f"### `context/harness/{rel}` ({len(body):,} chars -- full content)\n```markdown\n{body.strip()}\n```")
    return "\n\n".join(lines)


def _inline_evidence_bundle(root: Path, unmanaged_skills: Sequence[Mapping[str, str]] = ()) -> str:
    """Pre-pack `task.md`, `slice_summary.md`, compact rollouts, and the harness digest directly
    into `MISSION.md` so the proposer can immediately edit `context/harness/` without spending
    10+ sequential tool calls reading small files one by one.
    """
    sections: list[str] = []
    task_p = root / "task.md"
    if task_p.is_file():
        sections.append(f"## `context/task.md`\n```markdown\n{task_p.read_text(encoding='utf-8', errors='replace').strip()}\n```")

    deliv_root = root / "deliverables"
    if deliv_root.is_dir():
        for sub in sorted(deliv_root.iterdir()):
            if not sub.is_dir():
                continue
            seen_deliv: set[str] = set()
            for fname in (
                "slice_summary.md",
                "slice_summary.txt",
                "git_survival.patch",
                "git_survival_T_Y1.patch.txt",
                "at_T_Y.patch",
                "at_T_Y.patch.txt",
                "user_nudge.txt",
            ):
                fp = sub / fname
                if not fp.is_file() or fname in seen_deliv:
                    continue
                seen_deliv.add(fname)
                txt = fp.read_text(encoding="utf-8", errors="replace").strip()
                fence = "diff" if "patch" in fname else "markdown"
                if len(txt) <= INLINE_FILE_MAX_CHARS:
                    sections.append(
                        f"## `context/deliverables/{sub.name}/{fname}` ({len(txt):,} chars)\n"
                        f"```{fence}\n{txt}\n```"
                    )
                else:
                    sections.append(
                        f"## `context/deliverables/{sub.name}/{fname}` ({len(txt):,} chars -- truncated preview; full file on disk)\n"
                        f"```{fence}\n{txt[:8_000]}\n... [truncated; read file on disk if full diff needed] ...\n```"
                    )

    rollout_root = root / "rollouts"
    if rollout_root.is_dir():
        for rp in sorted(rollout_root.glob("*.md")):
            rtxt = rp.read_text(encoding="utf-8", errors="replace").strip()
            if len(rtxt) <= INLINE_FILE_MAX_CHARS:
                sections.append(
                    f"## `context/rollouts/{rp.name}` ({len(rtxt):,} chars -- full trajectory)\n"
                    f"```markdown\n{rtxt}\n```"
                )
            else:
                sections.append(
                    f"## `context/rollouts/{rp.name}` ({len(rtxt):,} chars -- preview; full file on disk)\n"
                    f"```markdown\n{rtxt[:12_000]}\n... [truncated; read `context/rollouts/{rp.name}` for remaining turns] ...\n```"
                )

    harness_digest = _summarize_harness_for_mission(root / "harness")
    if harness_digest:
        sections.append(f"## Current Harness Overview (`context/harness/`)\n\n{harness_digest}")

    if unmanaged_skills:
        skill_lines = [
            f"- `{s.get('name') or s.get('path')}` (`{s.get('path')}`): {s.get('description') or '(no description)'}"
            for s in unmanaged_skills
        ]
        sections.append(
            "## Pre-existing Read-Only Workspace Skills — Do Not Edit or Duplicate\n\n"
            "These user-owned or third-party skills are already installed in the repository "
            "(excluded from editable `context/harness/`). Do NOT recreate, shadow, or duplicate them:\n\n"
            + "\n".join(skill_lines)
        )

    return "\n\n".join(sections)


def mission(tree: ContextTree, *, job: str) -> str:
    """The pointer to the evidence on disk plus pre-packed inline evidence so the proposer
    does not waste 10+ sequential tool turns reading small files one by one.
    """
    inline_bundle = _inline_evidence_bundle(tree.root, tree.unmanaged_skills)
    parts = [
        job.strip(),
        "",
        "# YOUR EVIDENCE",
        "",
        "It is on disk, in `context/`, AND pre-packed below so you do NOT need to re-read files "
        "that are already shown in full below. Do not waste tool turns calling `read_file` on "
        "files whose full content is already inlined below or on unrelated skills you are not editing.",
        "",
        tree.layout,
        "",
        "Every trajectory EVENT is present: the trajectory was not clipped to fit this "
        "mission. If `context/library/INDEX.md` is present, browse it before proposing any change. "
        "Cite the specific trajectory moment behind every change; one you cannot trace to a "
        "moment is speculation.",
    ]
    if inline_bundle:
        parts.extend(
            [
                "",
                "# PRE-PACKED EVIDENCE & HARNESS SNAPSHOT (NO NEED TO RE-READ)",
                "",
                inline_bundle,
            ]
        )
    return "\n".join(parts)
