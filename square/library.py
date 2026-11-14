"""The Continual Improvement Library R_t: what earlier cases across tasks produced.

Adapted from `reference/harness2/harness2/core/library.py` and `harness2-summary.md` Section 4.2:
    <root>/INDEX.md
    <root>/harnesses/<case_id>/harness/<rel>   the full adopted tree
    <root>/harnesses/<case_id>/EXPERIENCE.md   YAML frontmatter + why picked + edits + transferable lesson
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from . import tree as harness_tree
from .substrates.antigravity import AGY_SURFACE
from .tree import SurfaceSpec


def slug(task_id: str) -> str:
    return task_id.replace("/", "__").replace("\\", "__")


def has_experience(experience: dict | None) -> bool:
    """Strict Evidence Filter Rule: require non-empty `cue`, `lesson`, and `evidence`
    and reject `NO_ENTRY`.
    """
    if not isinstance(experience, dict):
        return False
    if experience.get("no_entry"):
        return False
    for key in ("cue", "lesson", "evidence"):
        val = experience.get(key)
        if not isinstance(val, str) or not val.strip() or val.strip().upper() == "NO_ENTRY":
            return False
    return True


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse YAML frontmatter `---\\n...\\n---\\n` at the start of `text`.
    Returns `(frontmatter_dict, remaining_body)`.
    """
    norm = text.replace("\r\n", "\n")
    if not norm.startswith("---\n"):
        return {}, text
    end = norm.find("\n---\n", 4)
    if end == -1:
        return {}, text
    fm: dict[str, str] = {}
    for line in norm[4:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            k, v = line.split(":", 1)
            val = v.strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            fm[k.strip()] = val
    return fm, norm[end + 5 :]


@dataclass
class Library:
    """Unified Continual Improvement Library R_t for a substrate: read before each case,
    appended after composition & reflection when and only when the Strict Evidence Filter passes.
    """

    root: Path
    surface: SurfaceSpec = field(default_factory=lambda: AGY_SURFACE)

    @property
    def dir(self) -> Path:
        return Path(self.root)

    @property
    def index(self) -> Path:
        return self.dir / "INDEX.md"

    def entry_dir(self, case_id: str) -> Path:
        return self.dir / "harnesses" / slug(case_id)

    def exists(self) -> bool:
        return self.index.is_file()

    def context_dir(self) -> Path | None:
        """The directory handed to an improver session, or None when the library is empty."""
        has_content = any(self.dir.rglob("EXPERIENCE.md")) if self.dir.is_dir() else False
        return self.dir if has_content else None

    def entries(self) -> list[str]:
        d = self.dir / "harnesses"
        return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.is_dir() else []

    def tree_of(self, case_id: str) -> harness_tree.Tree:
        return harness_tree.read_tree(self.surface, self.entry_dir(case_id) / "harness")

    def forget(self, case_ids: Sequence[str]) -> None:
        """Drop the entries for these cases and rebuild INDEX.md; unknown cases are ignored."""
        removed = False
        for cid in case_ids:
            d = self.entry_dir(cid)
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
                removed = True
        if removed:
            self.rebuild_index()

    def retain(self, case_ids: Sequence[str]) -> None:
        """Keep only the entries preceding the current case in this stream."""
        keep = {slug(cid) for cid in case_ids}
        self.forget([entry for entry in self.entries() if entry not in keep])

    def add(
        self,
        case_id: str,
        harness: harness_tree.Tree,
        *,
        why: str = "",
        label: str = "",
        run_id: str = "",
        experience: dict | None = None,
        applied_components: Sequence[str] | None = None,
        extra_files: dict[str, str] | None = None,
    ) -> Path | None:
        """Store one adopted harness plus its self-categorized YAML frontmatter and transferable
        lesson, and rebuild INDEX.md from disk.
        Enforces the Strict Evidence Filter Rule: returns None if `has_experience(experience)` is False.
        """
        if not has_experience(experience):
            return None
        d = self.entry_dir(case_id)

        shutil.rmtree(d / "harness", ignore_errors=True)
        (d / "harness").mkdir(parents=True, exist_ok=True)
        harness_tree.write_tree(
            self.surface,
            harness,
            d / "harness",
            stubs=False,
            ensure_always_on=False,
        )
        for rel_extra, body_extra in (extra_files or {}).items():
            if body_extra.strip():
                p_ex = d / rel_extra
                p_ex.parent.mkdir(parents=True, exist_ok=True)
                p_ex.write_text(body_extra, encoding="utf-8")

        exp = experience or {}
        task_domain = str(exp.get("task_domain") or "general").strip()
        deficiency_type = str(exp.get("deficiency_type") or "workflow_friction").strip()
        diff_summary_str = str(
            exp.get("trajectory_differential_summary") or exp.get("evidence") or ""
        ).strip()
        comps = list(applied_components) if applied_components else sorted(harness.keys())
        comps_yaml = "[" + ", ".join(f'"{c}"' for c in comps) + "]"

        lines = [
            "---",
            f"task_id: {case_id}",
            f"task_domain: {task_domain}",
            f"deficiency_type: {deficiency_type}",
            f"applied_components: {comps_yaml}",
            "contrast_validation_flag: true",
            f"trajectory_differential_summary: {_yaml_escape(diff_summary_str)}",
            "---",
            "",
            f"# {case_id}",
            "",
            f"- adopted: `{label}`" + (f"  (run `{run_id}`)" if run_id else ""),
            f"- task_domain: `{task_domain}`",
            f"- deficiency_type: `{deficiency_type}`",
            f"- applied_components: {', '.join(f'`{c}`' for c in comps)}",
            f"- components: {_inventory(self.surface, harness)}",
            "",
        ]
        if why.strip():
            lines += ["## Why this was chosen", why.strip(), ""]
        if exp.get("edits"):
            lines += ["## What each edit did", str(exp["edits"]).strip(), ""]
        lines += ["## Transferable lesson"]
        lines += [
            f"- **{f}**: {str(exp[f]).strip()}"
            for f in (
                "cue",
                "lesson",
                "evidence",
                "confidence",
                "task_domain",
                "deficiency_type",
                "trajectory_differential_summary",
            )
            if exp.get(f)
        ]
        lines += [""]
        (d / "EXPERIENCE.md").write_text("\n".join(lines), encoding="utf-8")

        self.rebuild_index()
        return d

    def rebuild_index(self) -> Path:
        """Regenerate INDEX.md from what is on disk."""
        rows = [
            f"# Continual Improvement Library ({self.surface.name})",
            "",
            "Each entry is an earlier verified case whose harness was synthesized, validated via "
            "contrastive execution, and stored with its FULL component tree and transferable lesson. "
            "Browse this index by `task_domain`, `deficiency_type`, and `cue`, then open the entries "
            "that look relevant to the matter in front of you.",
            "",
        ]
        names = self.entries()
        if not names:
            rows.append("_(no adopted case harnesses yet)_")
        for name in names:
            ed = self.dir / "harnesses" / name
            exp_path = ed / "EXPERIENCE.md"
            cue = _field(exp_path, "cue")
            t_dom = _frontmatter_or_field(exp_path, "task_domain")
            def_type = _frontmatter_or_field(exp_path, "deficiency_type")
            diff_sum = _frontmatter_or_field(exp_path, "trajectory_differential_summary")
            tree = harness_tree.read_tree(self.surface, ed / "harness")
            ao_delta_path = ed / "ALWAYS_ON_DELTA.md"
            ao_delta_chars = (
                len(ao_delta_path.read_text(encoding="utf-8", errors="replace"))
                if ao_delta_path.is_file()
                else 0
            )
            rows += [
                f"## `harnesses/{name}/`",
                f"- harness: `harnesses/{name}/harness/` — {_inventory(self.surface, tree, extra_always_on_chars=ao_delta_chars)}",
                f"- experience: `harnesses/{name}/EXPERIENCE.md`",
            ]
            if t_dom:
                rows.append(f"- task_domain: `{t_dom}`")
            if def_type:
                rows.append(f"- deficiency_type: `{def_type}`")
            if cue:
                rows.append(f"- cue: {cue}")
            if diff_sum:
                rows.append(f"- trajectory_differential: {diff_sum}")
            rows.append("")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index.write_text("\n".join(rows), encoding="utf-8")
        return self.index


def _yaml_escape(val: str) -> str:
    clean = " ".join(val.splitlines()).strip()
    if any(ch in clean for ch in (":", "#", "[", "]", "{", "}", '"')):
        return '"' + clean.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return clean


def _inventory(
    surface: SurfaceSpec, tree: harness_tree.Tree, *, extra_always_on_chars: int = 0
) -> str:
    """A one-line census of the components actually in this harness."""
    st: dict[str, int] = {"skills": 0, "sub_agents": 0, "scripts": 0}
    skill_prefix = surface.skill_dir + "/"
    plugin_prefix = None if surface.plugin_dir is None else surface.plugin_dir + "/"
    rules_prefix = None if surface.rules_dir is None else surface.rules_dir + "/"
    hooks_file = surface.hooks_file
    for rel in tree:
        if rel.startswith(skill_prefix) and rel.endswith("SKILL.md"):
            st["skills"] += 1
        elif rel.startswith("sub_agents/"):
            st["sub_agents"] += 1
        elif rel.startswith("scripts/"):
            st["scripts"] += 1
        elif plugin_prefix is not None and rel.startswith(plugin_prefix):
            st["plugins"] = st.get("plugins", 0) + 1
        elif rules_prefix is not None and rel.startswith(rules_prefix):
            st["rules"] = st.get("rules", 0) + 1
        elif rel == hooks_file:
            st["hooks"] = st.get("hooks", 0) + 1
    on = len(harness_tree.always_on_text(surface, tree)) + extra_always_on_chars
    bits = [f"{v} {k}" for k, v in st.items() if v] or ["always-on edits only"]
    return f"{', '.join(bits)}; {on:,} always-on chars"


def _field(path: Path, name: str) -> str:
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(f"- **{name}**:"):
            return line.split(":", 1)[1].strip()
    return ""


def _frontmatter_or_field(path: Path, name: str) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                if line.startswith(f"{name}:"):
                    val = line.split(":", 1)[1].strip()
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1].replace('\\"', '"').replace("\\\\", "\\")
                    return val
    return _field(path, name)
