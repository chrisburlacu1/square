"""The c1..c8 component tree: read, validate, write, diff — parametrised by SurfaceSpec.

Ported directly from `reference/harness2/harness2/core/tree.py`, plus
`validate_dimension_scope(surface, dim, before, after)` for scoped parallel
`INV` + `DOM` leasing (Invariant #3 & Invariant #5).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

Tree = dict[str, str]


RESERVED_SCRIPTS = frozenset({"read_doc.py", "pack.py", "unpack.py"})


_NAME = r"[a-z0-9][a-z0-9_\-]*"


@dataclass(frozen=True)
class SurfaceSpec:
    """The editable surface of one agent framework: paths, caps and per-surface rules."""

    name: str
    always_on: tuple[str, ...]
    always_on_max: int
    always_on_cap_reason: str
    skill_dir: str
    skill_name_rule: str
    trigger_hint: str
    autotrigger_file: str
    trigger_line: str
    subagent_requires_mode: bool
    plugin_dir: str | None
    hooks_file: str | None
    hook_events: frozenset[str] = frozenset()
    rules_dir: str | None = None
    compile_skill_scripts: bool = False
    reject_empty_always_on: bool = False
    require_skill_triggers_in_always_on: bool = True
    allow_subagents: bool = True

    stubs: tuple[tuple[str, str], ...] = ()


@lru_cache(maxsize=8)
def _res(
    surface_name: str, skill_dir: str, plugin_dir: str | None, rules_dir: str | None = None
) -> dict[str, re.Pattern]:
    sd = re.escape(skill_dir)
    out = {
        "skill": re.compile(rf"{sd}/({_NAME})/SKILL\.md"),
        "skill_script": re.compile(rf"{sd}/{_NAME}/scripts/[A-Za-z0-9_.\-]+"),
        "subagent": re.compile(rf"sub_agents/({_NAME})/AGENT\.md"),
        "script": re.compile(r"scripts/[a-z0-9_][a-z0-9_]*\.py"),
        "script_ref": re.compile(rf"(?:python3?\s+)((?:{sd}/[\w\-]+/)?scripts/[\w.\-]+\.py)"),
    }
    if plugin_dir is not None:
        out["plugin"] = re.compile(rf"{re.escape(plugin_dir)}/({_NAME})\.ts")
    if rules_dir is not None:
        out["rule"] = re.compile(rf"{re.escape(rules_dir)}/({_NAME})\.md")
    return out


def _rx(surface: SurfaceSpec) -> dict[str, re.Pattern]:
    return _res(surface.name, surface.skill_dir, surface.plugin_dir, surface.rules_dir)


def normalize_rel(rel: str) -> str:
    """Normalise a relative path, rejecting escapes before it is joined to a directory."""
    r = str(rel).strip().replace("\\", "/")
    if r.startswith("/") or ".." in r.split("/"):
        raise ValueError(f"path escapes the harness: {rel!r}")
    while r.startswith("./"):
        r = r[2:]
    return r.strip("/")


def is_allowed(surface: SurfaceSpec, rel: str) -> bool:
    """Whether this path is on the editable surface. A predicate: it never raises."""
    try:
        rel = normalize_rel(rel)
    except ValueError:
        return False
    if rel in surface.always_on:
        return True
    if surface.hooks_file is not None and rel == surface.hooks_file:
        return True
    r = _rx(surface)
    if r["subagent"].fullmatch(rel):
        return surface.allow_subagents
    if (
        r["skill"].fullmatch(rel)
        or r["skill_script"].fullmatch(rel)
        or r["script"].fullmatch(rel)
    ):
        return True
    if "rule" in r and r["rule"].fullmatch(rel):
        return True
    return "plugin" in r and bool(r["plugin"].fullmatch(rel))


def skill_names(surface: SurfaceSpec, tree: Tree) -> list[str]:
    rx = _rx(surface)["skill"]
    return sorted({m.group(1) for rel in tree if (m := rx.fullmatch(rel))})


def subagent_names(surface: SurfaceSpec, tree: Tree) -> list[str]:
    rx = _rx(surface)["subagent"]
    return sorted({m.group(1) for rel in tree if (m := rx.fullmatch(rel))})


def _stub_paths(surface: SurfaceSpec) -> frozenset[str]:
    return frozenset(rel for rel, _ in surface.stubs)


def read_tree(surface: SurfaceSpec, d: Path | str, *, rejected: list[str] | None = None) -> Tree:
    """rel -> content for every file on the editable surface, README stubs excluded.

    Pass `rejected` to collect paths that exist on disk but are off the surface.
    """
    d = Path(d)
    out: Tree = {}
    if not d.is_dir():
        return out
    stubs = _stub_paths(surface)
    for p in sorted(d.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        rel = normalize_rel(str(p.relative_to(d)))
        if rel in stubs:
            continue
        if not is_allowed(surface, rel):
            if rejected is not None:
                rejected.append(rel)
            continue
        out[rel] = p.read_text(encoding="utf-8", errors="replace")
    return out


def is_tree(surface: SurfaceSpec, d: Path | str) -> bool:
    d = Path(d)
    return d.is_dir() and any((d / a).is_file() for a in surface.always_on)


def write_tree(
    surface: SurfaceSpec,
    tree: Tree,
    dest: Path | str,
    *,
    stubs: bool = True,
    ensure_always_on: bool = True,
) -> Path:
    """Materialise an exact editable tree, with always-on files and optional stubs present.

    Files outside the editable surface are preserved; editable files already there are not.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    stub_set = _stub_paths(surface)
    for p in sorted(dest.rglob("*"), reverse=True):
        if not p.is_file():
            continue
        rel = normalize_rel(str(p.relative_to(dest)))
        if is_allowed(surface, rel) or rel in stub_set:
            p.unlink()
    if ensure_always_on:
        for a in surface.always_on:
            p = dest / a
            p.parent.mkdir(parents=True, exist_ok=True)
            if a not in tree and not p.exists():
                p.write_text("", encoding="utf-8")
    for rel, content in tree.items():
        p = dest / normalize_rel(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    if stubs:
        for rel, body in surface.stubs:
            p = dest / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                p.write_text(body, encoding="utf-8")
    return dest


def apply_tree(surface: SurfaceSpec, base: Tree, new: Tree, dest: Path | str) -> Path:
    """Safely apply `new` over `base` onto `dest` without deleting pre-existing untracked
    skills, rules, or scripts on disk that were not removed between `base` and `new`.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    removed = set(base) - set(new)
    for rel in sorted(removed):
        p = dest / normalize_rel(rel)
        if p.is_file():
            p.unlink()
    for a in surface.always_on:
        p = dest / a
        p.parent.mkdir(parents=True, exist_ok=True)
        if a not in new and not p.exists():
            p.write_text("", encoding="utf-8")
    for rel, content in new.items():
        p = dest / normalize_rel(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return dest


def always_on_text(surface: SurfaceSpec, tree: Tree) -> str:
    return "\n\n".join(tree.get(a, "") for a in surface.always_on)


def autotrigger(surface: SurfaceSpec, tree: Tree, *, always_on_max: int | None = None) -> list[str]:
    """Give every skill a trigger line in always-on text; return the names repaired.

    A line that would push the body over the always-on cap is skipped instead.
    Skipped entirely on surfaces where skills are natively auto-discovered by frontmatter
    (`require_skill_triggers_in_always_on == False`).
    """
    if not surface.require_skill_triggers_in_always_on:
        return []
    cap = surface.always_on_max if always_on_max is None else always_on_max
    body = always_on_text(surface, tree)
    fixed: list[str] = []
    for name in skill_names(surface, tree):
        if name in body:
            continue
        fm = tree.get(f"{surface.skill_dir}/{name}/SKILL.md", "")[:600]
        m = re.search(r"^description:\s*(.+)$", fm, re.M)
        desc = m.group(1).strip().rstrip(".") if m else f"the {name} workflow applies"
        line = surface.trigger_line.format(name=name, desc=desc)
        cur = tree.get(surface.autotrigger_file, "")
        if len(always_on_text(surface, tree)) + len(line) + 2 > cap:
            continue
        tree[surface.autotrigger_file] = (cur.rstrip() + "\n" + line) if cur.strip() else line
        body = always_on_text(surface, tree)
        fixed.append(name)
    return fixed


def check_hooks(surface: SurfaceSpec, src: str, errs: list[str]) -> None:
    """Validate the hooks file against the schema the framework dispatches; a malformed one
    never fires rather than erroring, so the shape is enforced where the proposer sees it.
    """
    hf = surface.hooks_file
    try:
        doc = json.loads(src)
    except json.JSONDecodeError as exc:
        errs.append(f"{hf} is not valid JSON: {exc}")
        return
    hooks = doc.get("hooks") if isinstance(doc, dict) else None
    if not isinstance(hooks, dict) or not hooks:
        errs.append(f'{hf} needs a top-level {{"hooks": {{"<Event>": [...]}}}} object')
        return
    for event, entries in hooks.items():
        if event not in surface.hook_events:
            errs.append(
                f"{hf}: unknown event {event!r}; the framework dispatches "
                f"{', '.join(sorted(surface.hook_events))} (PascalCase)"
            )
            continue
        if not isinstance(entries, list):
            errs.append(f"{hf}: {event} must map to a LIST of matcher entries")
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                errs.append(f"{hf}: {event}[{i}] needs a `hooks` list")
                continue
            for h in entry["hooks"]:
                if not isinstance(h, dict) or h.get("type") != "command":
                    errs.append(
                        f'{hf}: {event}[{i}] hook type must be "command" — '
                        f"async/prompt/agent hooks are skipped as 'not supported yet'"
                    )
                elif not str(h.get("command", "")).strip():
                    errs.append(f"{hf}: {event}[{i}] has an empty `command`")


def _py_compiles(rel: str, src: str, errs: list[str]) -> None:
    try:
        compile(src, rel, "exec")
    except (SyntaxError, ValueError) as exc:
        detail = (
            f"{type(exc).__name__}: {exc.msg} (line {exc.lineno})"
            if isinstance(exc, SyntaxError)
            else f"{type(exc).__name__}: {exc}"
        )
        errs.append(f"{rel} does not compile: {detail[:160]}")


def _check_skills(surface: SurfaceSpec, tree: Tree, body: str, errs: list[str]) -> list[str]:
    """Append every skill-frontmatter and untriggered-skill problem; return the skill names."""
    skills = skill_names(surface, tree)
    for name in skills:
        fm = tree[f"{surface.skill_dir}/{name}/SKILL.md"][:600]
        if not re.search(r"^description:\s*\S", fm, re.M):
            errs.append(
                f"{surface.skill_dir}/{name}/SKILL.md needs a `description:` in its "
                f"frontmatter, or the skill is dropped SILENTLY at load"
            )
        m_name = re.search(r"^name:\s*(\S+)\s*$", fm, re.M)
        if surface.skill_name_rule == "must_match":
            if not (m_name and m_name.group(1) == name):
                errs.append(
                    f"{surface.skill_dir}/{name}/SKILL.md needs frontmatter "
                    f"`name: {name}` matching its directory (a mismatch is dropped "
                    f"SILENTLY at load)"
                )
        elif m_name and m_name.group(1) != name:
            errs.append(
                f"{surface.skill_dir}/{name}/SKILL.md frontmatter `name: "
                f"{m_name.group(1)}` OVERRIDES the directory name at load, so every "
                f"trigger line naming `{name}` stops matching; drop the `name:` line "
                f"or make it `name: {name}`"
            )
        if surface.require_skill_triggers_in_always_on and name not in body:
            errs.append(
                f"skill '{name}' is never named in the always-on text, so the agent "
                f"will not know to invoke it — an untriggered skill is dead weight. "
                + surface.trigger_hint.format(name=name)
            )
    return skills


def _check_subagents(
    surface: SurfaceSpec, tree: Tree, allow_subagents: bool, errs: list[str]
) -> list[str]:
    """Append every sub-agent problem; return the sub-agent names."""
    subs = subagent_names(surface, tree)
    if subs and not allow_subagents:
        errs.append(f"sub_agents are not available on this deployment: {subs}")
    for name in subs:
        fm = tree[f"sub_agents/{name}/AGENT.md"][:600]
        if surface.subagent_requires_mode and not re.search(r"^mode:\s*subagent\s*$", fm, re.M):
            errs.append(f"sub_agents/{name}/AGENT.md needs frontmatter `mode: subagent`")
        if not re.search(r"^description:\s*\S", fm, re.M):
            errs.append(f"sub_agents/{name}/AGENT.md needs a `description:`")
    return subs


def _check_script_refs(
    surface: SurfaceSpec,
    tree: Tree,
    r: dict[str, re.Pattern],
    reserved_scripts: frozenset[str] | set[str],
    errs: list[str],
) -> None:
    """Append a problem for every script a skill or always-on file invokes but does not ship."""
    have = {rel for rel in tree if r["script"].fullmatch(rel) or r["skill_script"].fullmatch(rel)}
    for rel, src in tree.items():
        m_skill = r["skill"].fullmatch(rel)
        if not (m_skill or rel in surface.always_on):
            continue
        skill_dir_prefix = f"{surface.skill_dir}/{m_skill.group(1)}/" if m_skill else ""
        for ref in r["script_ref"].findall(src):
            if ref.rsplit("/", 1)[-1] in reserved_scripts:
                continue
            if ref in have:
                continue
            if skill_dir_prefix and ref.startswith("scripts/") and (skill_dir_prefix + ref) in have:
                continue
            errs.append(f"{rel} invokes `{ref}` but that file is not in the harness")


def validate(
    surface: SurfaceSpec,
    tree: Tree,
    *,
    allow_subagents: bool | None = None,
    always_on_max: int | None = None,
    reserved_scripts: frozenset[str] | set[str] = RESERVED_SCRIPTS,
) -> dict:
    """Raise ValueError listing every problem; return a census of the validated tree."""
    errs: list[str] = []
    r = _rx(surface)
    effective_allow_subs = surface.allow_subagents if allow_subagents is None else allow_subagents
    cap = surface.always_on_max if always_on_max is None else always_on_max
    body = always_on_text(surface, tree)

    if len(body) > cap:
        errs.append(
            f"always-on content is {len(body)} chars, over the {cap} cap; "
            f"{surface.always_on_cap_reason}"
        )
    if surface.reject_empty_always_on and not body.strip():
        errs.append(
            f"{surface.always_on[0]} is empty — it is the only always-on file on "
            f"this framework, so an empty one is a harness that does not exist"
        )

    skills = _check_skills(surface, tree, body, errs)
    subs = _check_subagents(surface, tree, effective_allow_subs, errs)

    for rel, src in tree.items():
        if r["script"].fullmatch(rel) or (
            surface.compile_skill_scripts
            and r["skill_script"].fullmatch(rel)
            and rel.endswith(".py")
        ):
            _py_compiles(rel, src, errs)

    if surface.hooks_file is not None and surface.hooks_file in tree:
        check_hooks(surface, tree[surface.hooks_file], errs)

    _check_script_refs(surface, tree, r, reserved_scripts, errs)

    if errs:
        raise ValueError(" | ".join(errs))
    out = {
        "always_on_chars": len(body),
        "n_files": len(tree),
        "skills": len(skills),
        "sub_agents": len(subs),
        "scripts": sum(
            1
            for rel in tree
            if r["script"].fullmatch(rel)
            or (r["skill_script"].fullmatch(rel) and rel.endswith(".py"))
        ),
    }
    if surface.plugin_dir is not None:
        out["plugins"] = sum(1 for rel in tree if r["plugin"].fullmatch(rel))
    if surface.hooks_file is not None:
        out["hooks"] = 1 if surface.hooks_file in tree else 0
    if surface.rules_dir is not None and "rule" in r:
        out["rules"] = sum(1 for rel in tree if r["rule"].fullmatch(rel))
    return out


def diff_summary(surface: SurfaceSpec, before: Tree, after: Tree) -> dict:
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(rel for rel in set(before) & set(after) if before[rel] != after[rel])
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "always_on_char_delta": (
            len(always_on_text(surface, after)) - len(always_on_text(surface, before))
        ),
    }


def diversity(trees: dict[str, Tree]) -> dict:
    """Pairwise line-Jaccard over candidate trees, so collapse to one body is visible."""
    names = sorted(trees)
    if len(names) < 2:
        return {"n": len(names), "n_distinct": len(names), "mean_line_jaccard": 1.0}

    def lines(t: Tree) -> set[str]:
        return {f"{rel}:{ln}" for rel, c in t.items() for ln in c.splitlines() if ln.strip()}

    sets = {n: lines(trees[n]) for n in names}
    sims = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            u = sets[a] | sets[b]
            sims.append(len(sets[a] & sets[b]) / len(u) if u else 1.0)
    distinct = len({tuple(sorted(t.items())) for t in trees.values()})
    return {
        "n": len(names),
        "n_distinct": distinct,
        "mean_line_jaccard": round(sum(sims) / len(sims), 4),
    }


def is_path_allowed_for_dimension(surface: SurfaceSpec, dim: str, rel: str) -> bool:
    """Check whether `rel` on `surface` is within `dim` ('INV' or 'DOM') writable scope (Invariant #5).

    - `INV` (Invariant / Mechanics Editor) owns:
      - `scripts/*.py`
      - `sub_agents/*/AGENT.md`
      - `hooks_file` (`.agents/hooks.json`, `.codex/hooks.json`, `.claude/hooks.json`) or `plugin_dir/*.ts` (`plugin/*.ts`)
      - Skills (`<skill_dir>/<name>/SKILL.md` and `<skill_dir>/<name>/scripts/*`)
      - Always-on files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `systemprompt.md`, `guardrails.md`,
        `tool_descriptions/tool_guidance.md`), EXCEPT `LongTermMEMORY.md` on multi-file surfaces.
    - `DOM` (Domain / Architecture Editor) owns:
      - Skills (`<skill_dir>/<name>/SKILL.md` and `<skill_dir>/<name>/scripts/*`)
      - Rules (`<rules_dir>/<name>.md`, e.g. `.agents/rules/<name>.md`)
      - Always-on memory / rules (`LongTermMEMORY.md`, `guardrails.md`, or the single always-on file
        `AGENTS.md` / `CLAUDE.md` / `GEMINI.md`), EXCEPT `tool_descriptions/tool_guidance.md` and
        `systemprompt.md` on multi-file surfaces.
    """
    rel = normalize_rel(rel)
    r = _rx(surface)

    if dim == "INV":
        if r["script"].fullmatch(rel):
            return True
        if r["subagent"].fullmatch(rel):
            return surface.allow_subagents
        if surface.hooks_file is not None and rel == surface.hooks_file:
            return True
        if "plugin" in r and r["plugin"].fullmatch(rel):
            return True
        if r["skill"].fullmatch(rel) or r["skill_script"].fullmatch(rel):
            return True
        if rel in surface.always_on:
            # On multi-file OPENCODE_SURFACE, LongTermMEMORY.md belongs strictly to DOM
            if len(surface.always_on) > 1 and rel == "LongTermMEMORY.md":
                return False
            return True
        return False

    if dim == "DOM":
        if r["skill"].fullmatch(rel) or r["skill_script"].fullmatch(rel):
            return True
        if "rule" in r and r["rule"].fullmatch(rel):
            return True
        if rel in surface.always_on:
            if len(surface.always_on) > 1 and rel in (
                "tool_descriptions/tool_guidance.md",
                "systemprompt.md",
            ):
                return False
            return True
        return False

    raise ValueError(f"Unknown dimension {dim!r}; expected 'INV' or 'DOM'")


def validate_dimension_scope(
    surface: SurfaceSpec, dim: str, before: Tree, after: Tree
) -> None:
    """Enforce Invariant #5 (`INV` vs. `DOM` component ownership on any `SurfaceSpec`)."""
    if dim not in ("INV", "DOM"):
        raise ValueError(f"Unknown dimension {dim!r}; expected 'INV' or 'DOM'")

    diff = diff_summary(surface, before, after)
    changed = sorted(set(diff["added"]) | set(diff["removed"]) | set(diff["modified"]))
    errs: list[str] = []

    for rel in changed:
        if not is_path_allowed_for_dimension(surface, dim, rel):
            if dim == "INV":
                errs.append(
                    f"INV editor cannot modify `{rel}` on surface `{surface.name}`. "
                    f"INV owns `scripts/*.py`, `sub_agents/*/AGENT.md`, `{surface.hooks_file or surface.plugin_dir}`, "
                    f"`{surface.skill_dir}/<name>/SKILL.md`, and procedural always-on guidance."
                )
            else:
                errs.append(
                    f"DOM editor cannot modify `{rel}` on surface `{surface.name}`. "
                    f"DOM owns `{surface.skill_dir}/<name>/SKILL.md`, "
                    + (f"`{surface.rules_dir}/<name>.md`, " if surface.rules_dir else "")
                    + "and domain facts/rules in always-on memory/guardrails."
                )

    if errs:
        raise ValueError(" | ".join(errs))


def merge_parallel_trees(
    surface: SurfaceSpec, base: Tree, inv_tree: Tree | None, dom_tree: Tree | None
) -> Tree:
    """Merge non-overlapping `INV` and `DOM` candidate trees over `base` for any `SurfaceSpec`."""
    merged = dict(base)

    for dim, cand in (("INV", inv_tree), ("DOM", dom_tree)):
        if cand is None:
            continue
        diff = diff_summary(surface, base, cand)
        for rel in diff["added"]:
            if is_path_allowed_for_dimension(surface, dim, rel):
                merged[rel] = cand[rel]
        for rel in diff["removed"]:
            if is_path_allowed_for_dimension(surface, dim, rel):
                merged.pop(rel, None)
        for rel in diff["modified"]:
            if not is_path_allowed_for_dimension(surface, dim, rel):
                continue
            if rel in surface.always_on:
                # Merge added lines into always-on file so prior or sibling dimension rules are preserved
                cur_lines = merged.get(rel, "").splitlines()
                cand_lines = cand.get(rel, "").splitlines()
                for ln in cand_lines:
                    if ln not in cur_lines:
                        cur_lines.append(ln)
                merged[rel] = "\n".join(cur_lines).rstrip() + "\n"
            else:
                merged[rel] = cand[rel]

    return merged


def rebase_candidate_tree(
    surface: SurfaceSpec, live_base: Tree, old_base: Tree, old_candidate: Tree
) -> Tree:
    """Rebase `old_candidate` (originally proposed over `old_base`) onto `live_base` so
    intermediate edits or earlier sibling compositions in `live_base` are preserved.
    """
    rebased = dict(live_base)
    diff = diff_summary(surface, old_base, old_candidate)

    for rel in diff["added"]:
        rebased[rel] = old_candidate[rel]

    for rel in diff["removed"]:
        # Only remove if unchanged since old_base
        if rel in rebased and rebased.get(rel) == old_base.get(rel):
            rebased.pop(rel, None)

    for rel in diff["modified"]:
        if rel in surface.always_on:
            old_b_lines = old_base.get(rel, "").splitlines()
            old_c_lines = old_candidate.get(rel, "").splitlines()
            old_b_set = {ln.strip() for ln in old_b_lines if ln.strip()}
            old_c_set = {ln.strip() for ln in old_c_lines if ln.strip()}
            removed_stripped = old_b_set - old_c_set
            added_lines = [ln for ln in old_c_lines if ln.strip() and ln.strip() not in old_b_set]

            cur_lines = [
                ln
                for ln in rebased.get(rel, "").splitlines()
                if not (ln.strip() and ln.strip() in removed_stripped)
            ]
            cur_set = {ln.strip() for ln in cur_lines if ln.strip()}
            for ln in added_lines:
                if ln.strip() not in cur_set:
                    cur_lines.append(ln)
                    cur_set.add(ln.strip())
            rebased[rel] = ("\n".join(cur_lines).rstrip() + "\n") if cur_lines else ""
        else:
            rebased[rel] = old_candidate[rel]

    return rebased
