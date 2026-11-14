"""Substrate protocol and shared helpers for native agent SurfaceSpecs, transcript readers,
and reversible lease materializers (Invariant #3 & Invariant #9).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Protocol, Sequence, runtime_checkable

from .. import tree as HT
from ..schemas import FileMutation, Lease, NormalizedTurn, SessionTrace, ToolCallRecord
from ..tree import SurfaceSpec, Tree

_TRUNC_FMT = "…(+{n} chars — render truncation)"

_LEASE_BLOCK_FMT = (
    "<!-- SQUARE_LEASE:id={lease_id} dim={dimension} -->\n"
    "{body}\n"
    "<!-- /SQUARE_LEASE:id={lease_id} -->"
)


def _is_under_tempdir(path: Path) -> bool:
    try:
        resolved = str(path.resolve()).replace("\\", "/").lower()
        tmp_root = str(Path(tempfile.gettempdir()).resolve()).replace("\\", "/").rstrip("/").lower()
        return resolved == tmp_root or resolved.startswith(tmp_root + "/")
    except OSError:
        return False


def default_square_home(repo_root: Path | str | None = None) -> Path:
    """Root `~/.square` directory (or `SQUARE_HOME` override).
    When `repo_root` is an ephemeral `tempfile` directory in unit tests and `SQUARE_HOME`
    is not set, routes to a temporary `.square` root so tests neither pollute `~/.square`
    nor create `<repo>/.square`.
    """
    env_home = os.environ.get("SQUARE_HOME", "").strip()
    if env_home:
        return Path(env_home).expanduser().resolve()
    if repo_root is not None:
        rp = Path(repo_root)
        if _is_under_tempdir(rp):
            return Path(tempfile.gettempdir()).resolve() / ".square-test-home"
    return Path.home() / ".square"


def project_square_dir(repo_root: Path | str, square_home: Path | str | None = None) -> Path:
    """Return `~/.square/projects/<repo-name>-<hash8>` for `repo_root` so Square never
    writes internal state into the target repository's working tree.
    """
    rp = Path(repo_root).resolve()
    home = Path(square_home).resolve() if square_home else default_square_home(rp)
    norm = str(rp).replace("\\", "/").rstrip("/").lower()
    if _is_under_tempdir(rp):
        with contextlib.suppress(OSError):
            norm = f"{norm}@{rp.stat().st_ctime_ns}"
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:8]
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", rp.name or "root").strip("-") or "repo"
    proj_dir = home / "projects" / f"{safe_name}-{digest}"
    return proj_dir


@runtime_checkable
class Substrate(Protocol):
    """Everything `SquareEngine` needs of a coding agent substrate (`codex`, `opencode`, `claude`, `antigravity`)."""

    name: str

    def surface(self) -> SurfaceSpec:
        """The native editable c1..c8 tree schema + validators for this substrate."""

    def default_tree(self) -> Tree:
        """Initial valid component tree when the repository has no existing harness files."""

    def read_workspace_tree(self, repo_root: Path) -> Tree:
        """Read the current adopted harness tree from `repo_root` (stripping any active lease blocks)."""

    def read_trajectory(
        self,
        path: Path | str,
        *,
        session_id: str | None = None,
        domain: str = "default",
        workspace_root: str = "",
        obs_trunc: int = 50_000,
        max_chars: int = 400_000,
    ) -> SessionTrace:
        """Parse a session transcript file into a `SessionTrace` and render its `[ACTION]/[OBSERVATION]` markdown."""

    def materialise_lease(self, repo_root: Path, lease: Lease) -> list[Path]:
        """Materialize a Tier 1 lease into the repository's native files using tagged blocks and managed copies."""

    def revert_lease(self, repo_root: Path, lease_id: str, lease: Lease | None = None) -> list[Path]:
        """Revert a leased candidate from the repository's native files."""


def clip_text(s: Any, n: int) -> str:
    s_str = "" if s is None else str(s)
    s_str = s_str.replace("\x00", "")
    if n <= 0 or len(s_str) <= n:
        return s_str
    return s_str[:n] + _TRUNC_FMT.format(n=len(s_str) - n)


def text_of(obj: Any) -> str:
    """Best-effort text extraction from a message-ish payload (str, .text, content list)."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        for k in ("text", "message", "content", "summary", "output"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v
            if isinstance(v, (list, dict)):
                t = text_of(v)
                if t.strip():
                    return t
        return ""
    if isinstance(obj, list):
        return "\n".join(t for t in (text_of(x) for x in obj) if t.strip())
    return ""


def parse_jsonl_lines(path: Path | str) -> list[dict]:
    p = Path(path)
    if not p.is_file():
        return []
    raw = p.read_text(encoding="utf-8", errors="replace").replace("\x00", "")
    items: list[dict] = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            ev = json.loads(ln)
            if isinstance(ev, dict):
                items.append(ev)
        except json.JSONDecodeError:
            continue
    return items


def extract_mutation_from_tool_call(
    tool_name: str,
    args: dict[str, Any],
    file_states: dict[str, str],
    fms: list[FileMutation],
) -> None:
    low = tool_name.lower()
    path = str(
        args.get("Path") or args.get("file_path") or args.get("filePath") or args.get("path") or ""
    ).replace("\\", "/")
    if not path:
        return

    if low in ("write_file", "write", "create_file"):
        content = str(args.get("Content") or args.get("content") or "")
        before = file_states.get(path)
        file_states[path] = content
        fms.append(
            FileMutation(
                path=path,
                before_content=before,
                after_content=content,
                added_lines=content.splitlines(),
            )
        )
    elif low in ("edit_file", "edit", "replace_in_file"):
        target = str(args.get("Target") or args.get("old_string") or args.get("oldString") or "")
        replacement = str(
            args.get("Replacement") or args.get("new_string") or args.get("newString") or ""
        )
        before = file_states.get(path, target)
        after = before.replace(target, replacement) if target and target in before else replacement
        file_states[path] = after
        fms.append(
            FileMutation(
                path=path,
                before_content=before,
                after_content=after,
                added_lines=replacement.splitlines(),
                removed_lines=target.splitlines(),
            )
        )


def render_trace_to_grammar(
    trace: SessionTrace,
    *,
    obs_trunc: int = 50_000,
    max_chars: int = 400_000,
    args_trunc: int = 2_000,
) -> str:
    """Render a `SessionTrace` into `[USER] / [ASSISTANT] / [REASONING] / [ACTION] / [OBSERVATION]`."""
    lines: list[str] = []
    for t in trace.turns:
        if t.role == "user":
            if t.text.strip():
                lines.append(f"[USER] {clip_text(t.text.strip(), obs_trunc)}")
            continue
        if t.reasoning.strip():
            lines.append(f"[REASONING] {clip_text(t.reasoning.strip(), obs_trunc)}")
        if t.text.strip():
            lines.append(f"[ASSISTANT] {clip_text(t.text.strip(), obs_trunc)}")
        for tc in t.tool_calls:
            cmd = clip_text(tc.command_or_target, args_trunc)
            lines.append(f"[ACTION] {tc.tool_name}: {cmd}")
            failed = tc.is_error or tc.exit_code not in (None, 0)
            obs = clip_text(tc.output, obs_trunc)
            suffix = "" if tc.exit_code == 0 else f" | exit_code={tc.exit_code}"
            lines.append(f"[OBSERVATION{' ERROR' if failed else ''}] {obs}{suffix}")
        if not t.tool_calls:
            for fm in t.file_mutations:
                lines.append(f"[ACTION] write_file: {fm.path}")
    rendered = "\n".join(lines).strip()
    if not rendered:
        return "(no parseable events in trajectory)"
    if len(rendered) > max_chars:
        dropped = len(rendered) - max_chars
        rendered = rendered[:max_chars] + "\n" + _TRUNC_FMT.format(n=dropped)
    return rendered


def strip_lease_blocks(content: str, lease_id: str | None = None) -> str:
    """Remove `<!-- SQUARE_LEASE:id=... -->` blocks from markdown text.
    If `lease_id` is None, strips all lease blocks.
    """
    if lease_id is None:
        pat = r"\n*<!-- SQUARE_LEASE:id=[^\n]+? -->.*?<!-- /SQUARE_LEASE:id=[^\n]+? -->\n*"
    else:
        esc = re.escape(lease_id)
        pat = rf"\n*<!-- SQUARE_LEASE:id={esc}\b[^\n]*? -->.*?<!-- /SQUARE_LEASE:id={esc} -->\n*"
    cleaned = re.sub(pat, "\n", content, flags=re.S)
    return cleaned.rstrip() + ("\n" if cleaned.strip() else "")


def _square_managed_skill_prefixes(surface: SurfaceSpec, repo_root: Path) -> set[str]:
    """Return skill directory prefixes (`<skill_dir>/<name>/`) that were created/managed by Square
    (recorded in `~/.square/projects/<slug>/leases.json` or `managed_components.json`).
    Pre-existing or third-party skills (e.g. Anthropic `frontend-design`, Vercel `next-best-practices`,
    Google `litert-lm`) are excluded from Square's editable tree so proposers never overwrite or read 3rd-party skills.
    """
    skill_prefix = surface.skill_dir.rstrip("/") + "/"
    managed: set[str] = set()
    sq_dir = project_square_dir(repo_root)
    leases_path = sq_dir / "leases.json"
    if leases_path.is_file():
        try:
            doc = json.loads(leases_path.read_text(encoding="utf-8", errors="replace"))
            items = doc.get("leases", []) if isinstance(doc, dict) else (doc if isinstance(doc, list) else [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("status") not in ("ACTIVE", "COMPOSED", "TRIAL_ACTIVE", "PROMOTED"):
                    continue
                base_tree = item.get("base_tree") or {}
                for cp in item.get("component_paths") or []:
                    norm = HT.normalize_rel(str(cp))
                    if norm in base_tree and "<!-- square-managed -->" not in str(base_tree.get(norm, "")):
                        continue
                    if norm.startswith(skill_prefix):
                        parts = norm[len(skill_prefix) :].split("/", 1)
                        if parts and parts[0]:
                            managed.add(f"{skill_prefix}{parts[0]}/")
        except Exception:
            pass
    managed_path = sq_dir / "managed_components.json"
    if managed_path.is_file():
        try:
            paths = json.loads(managed_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(paths, list):
                for cp in paths:
                    norm = HT.normalize_rel(str(cp))
                    if norm.startswith(skill_prefix):
                        parts = norm[len(skill_prefix) :].split("/", 1)
                        if parts and parts[0]:
                            managed.add(f"{skill_prefix}{parts[0]}/")
        except Exception:
            pass
    return managed


def list_unmanaged_workspace_skills(surface: SurfaceSpec, repo_root: Path) -> list[dict[str, str]]:
    """Return a compact read-only inventory (`path`, `name`, `description`) of pre-existing or
    third-party `<skill_dir>/*/SKILL.md` files on disk that are excluded from Square's editable tree.
    """
    from .. import library as harness_library

    repo_root = Path(repo_root)
    raw_tree = HT.read_tree(surface, repo_root)
    skill_prefix = surface.skill_dir.rstrip("/") + "/"
    managed_skill_prefixes = _square_managed_skill_prefixes(surface, repo_root)
    out: list[dict[str, str]] = []
    for rel in sorted(raw_tree):
        if not (rel.startswith(skill_prefix) and rel.endswith("/SKILL.md")):
            continue
        content = raw_tree[rel]
        if any(rel.startswith(mp) for mp in managed_skill_prefixes) or "<!-- square-managed -->" in content:
            continue
        dir_name = rel[len(skill_prefix) :].split("/", 1)[0]
        fm, _ = harness_library.parse_frontmatter(content)
        name = str(fm.get("name") or dir_name).strip()
        desc = " ".join(str(fm.get("description") or "").splitlines()).strip()
        out.append({"path": rel, "name": name, "description": desc})
    return out


def record_square_managed_components(
    repo_root: Path, paths: Sequence[str], square_dir: Path | None = None
) -> None:
    """Persistently record component paths adopted by Square in `~/.square/projects/<slug>/managed_components.json`."""
    sq_dir = Path(square_dir) if square_dir else project_square_dir(repo_root)
    sq_dir.mkdir(parents=True, exist_ok=True)
    managed_path = sq_dir / "managed_components.json"
    existing: set[str] = set()
    if managed_path.is_file():
        try:
            data = json.loads(managed_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, list):
                existing.update(HT.normalize_rel(str(x)) for x in data)
        except Exception:
            pass
    for p in paths:
        existing.add(HT.normalize_rel(str(p)))
    managed_path.write_text(json.dumps(sorted(existing), indent=2) + "\n", encoding="utf-8")


def read_clean_workspace_tree(
    surface: SurfaceSpec,
    repo_root: Path,
    default_tree: Tree,
    *,
    materialize_missing: bool = True,
) -> Tree:
    """Read the substrate's tree from `repo_root`, stripping any active lease blocks from always-on files
    and excluding pre-existing/third-party skills that are not managed by Square.
    """
    repo_root = Path(repo_root)
    if materialize_missing and not HT.is_tree(surface, repo_root):
        for rel, content in default_tree.items():
            p = repo_root / rel
            if not p.is_file():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
    raw_tree = HT.read_tree(surface, repo_root)
    skill_prefix = surface.skill_dir.rstrip("/") + "/"
    managed_skill_prefixes = _square_managed_skill_prefixes(surface, repo_root)
    tree: Tree = {}
    for rel, content in raw_tree.items():
        if rel.startswith(skill_prefix):
            if not any(rel.startswith(mp) for mp in managed_skill_prefixes) and "<!-- square-managed -->" not in content:
                continue
        tree[rel] = content
    for ao in surface.always_on:
        if ao in tree:
            tree[ao] = strip_lease_blocks(tree[ao])
        elif materialize_missing:
            tree[ao] = default_tree.get(ao, "")
    return tree


def apply_lease_to_workspace(surface: SurfaceSpec, repo_root: Path, lease: Lease) -> list[Path]:
    """Materialize a Tier 1 `Lease` directly into `repo_root` on `surface` using tagged blocks
    (`<!-- SQUARE_LEASE:id=... --> ... <!-- /SQUARE_LEASE:id=... -->`) and managed skill copies.
    """
    repo_root = Path(repo_root)
    touched: list[Path] = []

    for rel in lease.component_paths:
        norm = HT.normalize_rel(rel)
        target = repo_root / norm
        target.parent.mkdir(parents=True, exist_ok=True)

        if norm in surface.always_on:
            cur = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
            cur = strip_lease_blocks(cur, lease_id=lease.lease_id)
            before = lease.base_tree.get(norm, "")
            after = lease.candidate_tree.get(norm, "")
            b_set = {ln.strip() for ln in before.splitlines() if ln.strip()}
            added = [ln for ln in after.splitlines() if ln.strip() and ln.strip() not in b_set]
            if added:
                block = _LEASE_BLOCK_FMT.format(
                    lease_id=lease.lease_id,
                    dimension=lease.dimension,
                    body="\n".join(added),
                )
                new_body = (cur.rstrip() + "\n\n" + block + "\n") if cur.strip() else (block + "\n")
                target.write_text(new_body, encoding="utf-8")
                touched.append(target)
        elif norm in lease.candidate_tree:
            body = lease.candidate_tree[norm]
            skill_prefix = surface.skill_dir.rstrip("/") + "/"
            if (
                norm.startswith(skill_prefix)
                and norm.endswith("/SKILL.md")
                and norm not in lease.base_tree
                and "<!-- square-managed -->" not in body
            ):
                body = body.rstrip() + "\n\n<!-- square-managed -->\n"
            target.write_text(body, encoding="utf-8")
            touched.append(target)

    return touched


def _prune_empty_parents(path: Path, stop_at: Path) -> None:
    """Remove empty parent directories starting at `path.parent` up to (but not including) `stop_at`."""
    cur = path.parent
    stop_resolved = stop_at.resolve()
    while True:
        try:
            cur_resolved = cur.resolve()
        except OSError:
            break
        if cur_resolved == stop_resolved or not str(cur_resolved).startswith(str(stop_resolved)):
            break
        try:
            if cur.is_dir() and not any(cur.iterdir()):
                cur.rmdir()
                cur = cur.parent
            else:
                break
        except OSError:
            break


def revert_lease_from_workspace(
    surface: SurfaceSpec,
    repo_root: Path,
    lease_id: str,
    lease: Lease | None = None,
) -> list[Path]:
    """Remove tagged lease blocks and any newly added leased files from `repo_root`."""
    repo_root = Path(repo_root)
    touched: list[Path] = []

    for ao in surface.always_on:
        p = repo_root / ao
        if p.is_file():
            orig = p.read_text(encoding="utf-8", errors="replace")
            cleaned = strip_lease_blocks(orig, lease_id=lease_id)
            if cleaned != orig:
                p.write_text(cleaned, encoding="utf-8")
                touched.append(p)

    if lease is not None:
        for rel in lease.component_paths:
            norm = HT.normalize_rel(rel)
            if norm in surface.always_on:
                continue
            p = repo_root / norm
            if norm not in lease.base_tree:
                if p.is_file():
                    p.unlink()
                    touched.append(p)
                _prune_empty_parents(p, repo_root)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(lease.base_tree[norm], encoding="utf-8")
                touched.append(p)

    return touched
