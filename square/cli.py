"""CLI entrypoint, background watcher/daemon, and candidate adoption gate for Square (`square`).

Commands:
- `square analyze [transcript]`: Retrospective session review across `INV` and `DOM` (default no-triage; `--with-triage` adds spotlight brief).
- `square apply [case_id|lease_id]`: Materialize reviewed proposals as reversible `ACTIVE` workspace leases (or `--revert` them cleanly).
- `square ingest [transcript]`: Probe active leases against a session transcript and compose/reflect ready leases (`--propose` opts into background slice detection).
- `square watch [watch_dir]`: Background watcher monitoring transcript directories (probe-only by default; `--propose` opts into slice detection).
- `square status`: Inspect harness census, active leases, stale/orphaned lease warnings, and candidate apply commands.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

from . import tree as HT
from .decision import (
    DecisionAPIError,
    render_scan_markdown,
    render_triage_markdown,
    scan_candidate_sessions,
)
from .engine import SquareEngine
from .lease import LeaseStore
from .proposer import ChannelSpec, Proposer
from .schemas import Dimension
from .substrates import (
    default_agy_brain_dir,
    default_agy_global_config_dir,
    default_global_library_root,
    default_square_home,
    get_substrate,
    parse_session_trace,
    project_square_dir,
)
from .substrates.base import list_unmanaged_workspace_skills


def _print_markdown(md_text: str, *, use_glow: bool = True) -> None:
    """Render Markdown to the terminal via `glow` when available, falling back to plain stdout."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    glow_bin = shutil.which("glow") if use_glow else None
    if glow_bin:
        try:
            width = str(shutil.get_terminal_size().columns)
            res = subprocess.run(
                [glow_bin, "-w", width, "-"],
                input=md_text,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if res.returncode == 0:
                return
        except OSError:
            pass
    print(md_text)


def _resolve_repo_and_library(args: argparse.Namespace) -> tuple[Path, Path | None]:
    if getattr(args, "global_surface", False):
        repo = default_agy_global_config_dir()
        return repo, default_global_library_root(repo)
    repo = Path(getattr(args, "repo", ".")).resolve()
    return repo, default_global_library_root(repo)


def _make_engine(args: argparse.Namespace) -> SquareEngine:
    repo, lib_root = _resolve_repo_and_library(args)
    channel = getattr(args, "channel", "codex_cli")
    model = getattr(args, "model", "")
    substrate_name = getattr(args, "substrate", "antigravity")
    if substrate_name == "auto":
        substrate_name = "antigravity"
    spec = ChannelSpec(kind=channel, model=model) if model else ChannelSpec(kind=channel)
    sq_root = project_square_dir(repo)
    audit_dir = sq_root / "audit"
    prop = Proposer(spec=spec, audit_dir=audit_dir)
    return SquareEngine(
        repo_root=repo,
        proposer=prop,
        substrate=substrate_name,
        library_root=lib_root,
        square_root=sq_root,
        use_library=not bool(getattr(args, "no_library", False)),
    )


def _trace_belongs_to_repo(
    trace_ws: str,
    touched_paths: list[str],
    repo_root: Path,
    task_prompt: str = "",
) -> bool:
    """When watching a global brain directory (e.g. `~/.gemini/antigravity/brain`),
    check whether the transcript's primary workspace belongs to `repo_root`.
    Excludes `.square/` inspection paths and Square review/proposer internal sessions.
    """
    prompt_low = (task_prompt or "").lower()
    if (
        "square-reviewer" in prompt_low
        or "/square_review" in prompt_low
        or "read `mission.md` in the current working directory" in prompt_low
    ):
        return False

    repo_norm = str(repo_root.resolve()).replace("\\", "/").rstrip("/").lower()
    abs_paths: list[str] = []
    saw_any_abs = False
    for c in touched_paths:
        norm = str(c).replace("\\", "/").lower()
        if ":" in norm or norm.startswith("/"):
            saw_any_abs = True
            if "/.gemini/" in norm or "/.square/" in norm or norm.endswith("/.square"):
                continue
            abs_paths.append(norm)

    if abs_paths:
        in_repo = sum(1 for p in abs_paths if p == repo_norm or p.startswith(repo_norm + "/"))
        # Require the majority of touched workspace paths to belong to `repo_root` so that
        # another repo's session that merely inspected a file here does not hijack `--latest`.
        return in_repo > 0 and (in_repo * 2 >= len(abs_paths))

    if trace_ws:
        ws_norm = str(trace_ws).replace("\\", "/").rstrip("/").lower()
        if ":" in ws_norm or ws_norm.startswith("/"):
            saw_any_abs = True
            if "/.gemini/" not in ws_norm and "/.square/" not in ws_norm:
                return ws_norm == repo_norm or ws_norm.startswith(repo_norm + "/")
            return False

    # If the transcript had absolute paths (e.g. only inside /.gemini/ or /.square/) and none matched repo_root, reject it
    if saw_any_abs or not task_prompt.strip():
        return False

    # If the transcript has only relative paths and a real task prompt (e.g. unit test fixtures), accept it
    return True


def _find_latest_repo_transcript(
    watch_dir: Path,
    repo_root: Path,
    *,
    substrate: str | None = None,
    global_surface: bool = False,
) -> Path | None:
    """Find the most recently modified session transcript in `watch_dir` that belongs to `repo_root`."""
    candidates: list[tuple[float, Path]] = []
    for p in _iter_watch_transcripts(watch_dir):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        candidates.append((mtime, p))
    candidates.sort(key=lambda item: item[0], reverse=True)

    for _, p in candidates:
        if global_surface:
            return p
        try:
            _, trace = parse_session_trace(
                p,
                substrate=(substrate if substrate != "auto" else None),
                workspace_root="",
            )
        except Exception:
            continue
        if _trace_belongs_to_repo(
            trace.workspace_root, trace.touched_paths, repo_root, trace.task_prompt
        ):
            return p
    return None


def cmd_ingest(args: argparse.Namespace) -> int:
    engine = _make_engine(args)
    if getattr(args, "latest", False) or not getattr(args, "transcript", None):
        brain_dir = (
            Path(args.watch_dir).resolve()
            if getattr(args, "watch_dir", None)
            else default_agy_brain_dir()
        )
        t_path = _find_latest_repo_transcript(
            brain_dir,
            engine.repo_root,
            substrate=args.substrate,
            global_surface=getattr(args, "global_surface", False),
        )
        if t_path is None:
            print(
                f"Error: no session transcript found for repo {engine.repo_root} in {brain_dir}",
                file=sys.stderr,
            )
            return 1
        print(f"[square] Found latest transcript: {t_path}", file=sys.stderr, flush=True)
    else:
        t_path = Path(args.transcript).resolve()
        if not t_path.is_file():
            print(f"Error: transcript file not found: {t_path}", file=sys.stderr)
            return 1

    sub, trace = parse_session_trace(
        t_path,
        substrate=(args.substrate if args.substrate != "auto" else None),
        workspace_root=str(engine.repo_root),
    )
    print(
        f"[square] Processing session `{trace.session_id[:12]}` ({len(trace.turns)} turns)...",
        file=sys.stderr,
        flush=True,
    )
    if getattr(args, "triage_only", False):
        try:
            triage_report, triage_path = engine.triage_session(
                trace,
                substrate=sub,
                window_size=getattr(args, "window_size", 8),
                stride=getattr(args, "stride", 6),
                signal_threshold=getattr(args, "threshold", 0.65),
            )
        except (ValueError, DecisionAPIError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        _print_markdown(
            render_triage_markdown(triage_report),
            use_glow=not getattr(args, "no_glow", False),
        )
        print(f"Saved triage report: {triage_path}")
        return 0
    if getattr(args, "analyze", False):
        use_triage = bool(getattr(args, "with_triage", False)) and not bool(
            getattr(args, "no_triage", False)
        )
        try:
            report_path = engine.analyze_session(
                trace,
                substrate=sub,
                retry=getattr(args, "retry", False),
                use_triage=use_triage,
                force_propose=getattr(args, "force_propose", False),
            )
        except (ValueError, DecisionAPIError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        if report_path.is_file():
            _print_markdown(
                report_path.read_text(encoding="utf-8-sig", errors="replace"),
                use_glow=not getattr(args, "no_glow", False),
            )
        case_id = report_path.parent.name
        awaiting = [
            l
            for l in engine.lease_store.load_all()
            if l.case_id == case_id and l.status in ("AWAITING_TRIAL", "STAGED_TIER_2")
        ]
        footer = f"\nReview ready: {report_path}\nProposals only; no project harness files changed."
        if awaiting:
            footer += f"\nAdopt & probe proposals: square apply {case_id}"
        print(footer)
        return 0
    report = engine.process_session(
        trace,
        substrate=sub,
        propose=bool(getattr(args, "propose", False)),
    )
    print(
        json.dumps(
            {
                "session_id": report.session_id,
                "substrate": report.substrate_name,
                "transcript": str(t_path),
                "activations": [
                    {
                        "lease_id": a.lease_id,
                        "situation_matched": a.situation_matched,
                        "component_invoked": a.component_invoked,
                        "outcome": a.outcome,
                    }
                    for a in report.activations
                ],
                "composed_leases": report.composed_leases,
                "reflected_cases": report.reflected_cases,
                "slices_detected": [s.slice_id for s in report.slices_detected],
                "created_leases": [l.lease_id for l in report.created_leases],
            },
            indent=2,
        )
    )
    return 0


def _iter_watch_transcripts(watch_dir: Path) -> list[Path]:
    """Return actual session transcript JSONL files inside `watch_dir`, skipping internal
    Antigravity chunk files (`logs/chunks/transcript/0000000*.jsonl`), `transcript_full.jsonl`,
    and unreadable/locked system folders.
    """
    if not watch_dir.is_dir():
        return []
    out: list[Path] = []
    seen: set[Path] = set()

    # Fast-path for Antigravity brain directory layout: <watch_dir>/<conv_id>/.system_generated/logs/transcript.jsonl
    try:
        children = sorted(watch_dir.iterdir())
    except OSError:
        return []

    for child in children:
        try:
            if child.is_file() and child.suffix == ".jsonl" and child.name != "transcript_full.jsonl":
                out.append(child)
                seen.add(child)
            elif child.is_dir():
                agy_log = child / ".system_generated" / "logs" / "transcript.jsonl"
                if agy_log.is_file():
                    out.append(agy_log)
                    seen.add(agy_log)
                else:
                    # Custom nested folder of transcripts (excluding `.system_generated/logs/chunks`)
                    for p in sorted(child.rglob("*.jsonl")):
                        if p in seen or p.name == "transcript_full.jsonl":
                            continue
                        if "chunks" in p.parts:
                            continue
                        out.append(p)
                        seen.add(p)
        except OSError:
            continue
    return out


def cmd_watch(args: argparse.Namespace) -> int:
    engine = _make_engine(args)
    watch_dir = (
        Path(args.watch_dir).resolve()
        if getattr(args, "watch_dir", None)
        else default_agy_brain_dir()
    )
    settle_s = float(getattr(args, "settle", 10.0))
    if getattr(args, "max_iterations", 0) == 1 and getattr(args, "watch_dir", None):
        settle_s = 0.0
    seen_mtimes: dict[Path, float] = {}
    print(
        f"Watching {watch_dir} for session transcripts "
        f"(interval={args.interval}s, settle={settle_s}s, channel={engine.proposer.spec.kind})..."
    )

    iterations = 0
    while True:
        now = time.time()
        for p in _iter_watch_transcripts(watch_dir):
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if seen_mtimes.get(p) == mtime:
                continue
            if settle_s > 0 and (now - mtime) < settle_s:
                # Transcript is actively streaming; wait until it settles before slicing/proposing
                continue
            seen_mtimes[p] = mtime
            sub, trace = parse_session_trace(
                p,
                substrate=(args.substrate if args.substrate != "auto" else None),
                workspace_root="",
            )
            if not getattr(args, "global_surface", False) and not _trace_belongs_to_repo(
                trace.workspace_root, trace.touched_paths, engine.repo_root, trace.task_prompt
            ):
                continue
            if not trace.workspace_root:
                trace.workspace_root = str(engine.repo_root)
            print(
                f"[square] Inspecting session `{trace.session_id[:12]}` ({len(trace.turns)} turns)...",
                file=sys.stderr,
                flush=True,
            )
            report = engine.process_session(
                trace,
                substrate=sub,
                propose=bool(getattr(args, "propose", False)),
            )
            print(
                f"[square] Done session={report.session_id[:12]}: "
                f"slices={len(report.slices_detected)}, "
                f"leases_created={len(report.created_leases)}, "
                f"activations={len(report.activations)}, "
                f"composed={len(report.composed_leases)}",
                file=sys.stderr,
                flush=True,
            )
        iterations += 1
        if args.max_iterations and iterations >= args.max_iterations:
            break
        time.sleep(args.interval)
    return 0


def _detect_lease_hygiene_warnings(
    repo: Path, surface: HT.SurfaceSpec, active_ids: set[str]
) -> list[str]:
    warnings: list[str] = []
    marker_re = re.compile(r"<!--\s*SQUARE_LEASE:id=([^\s>]+)")
    for ao in surface.always_on:
        p = repo / ao
        if p.is_file():
            txt = p.read_text(encoding="utf-8", errors="replace")
            for mid in marker_re.findall(txt):
                if mid not in active_ids:
                    warnings.append(
                        f"Orphaned SQUARE_LEASE marker '{mid}' found in {ao} on disk (no matching ACTIVE lease)."
                    )
        try:
            head_proc = subprocess.run(
                ["git", "show", f"HEAD:{ao}"],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if head_proc.returncode == 0 and "SQUARE_LEASE:id=" in (head_proc.stdout or ""):
                warnings.append(
                    f"Temporary SQUARE_LEASE marker is committed in git HEAD:{ao}. Remove or revert before pushing."
                )
            idx_proc = subprocess.run(
                ["git", "diff", "--cached", "--", ao],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if idx_proc.returncode == 0 and "+<!-- SQUARE_LEASE:id=" in (idx_proc.stdout or ""):
                warnings.append(
                    f"Temporary SQUARE_LEASE marker is staged in git index for {ao}. Unstage before committing."
                )
        except OSError:
            pass
    return warnings


def cmd_status(args: argparse.Namespace) -> int:
    repo, _ = _resolve_repo_and_library(args)
    sq_root = project_square_dir(repo)
    sub = get_substrate(args.substrate if args.substrate != "auto" else "antigravity")
    surface = sub.surface()
    base_tree = HT.read_tree(surface, repo) or sub.default_tree()
    try:
        census: dict = HT.validate(
            surface, base_tree, allow_subagents=surface.allow_subagents
        )
    except ValueError as exc:
        census = {"valid": False, "error": str(exc)}
    unmanaged = list_unmanaged_workspace_skills(surface, repo)
    store = LeaseStore(sq_root)
    leases = store.load_all()
    active = [l for l in leases if l.status == "ACTIVE"]
    active_ids = {l.lease_id for l in active}
    warnings = _detect_lease_hygiene_warnings(repo, surface, active_ids)
    for l in active:
        if l.unrelated_sessions_seen >= 10:
            warnings.append(
                f"Active lease '{l.lease_id}' ({l.dimension}) has gone {l.unrelated_sessions_seen} unrelated sessions without matching (`square apply {l.lease_id} --revert` to clean up)."
            )

    awaiting = [l for l in leases if l.status in ("AWAITING_TRIAL", "STAGED_TIER_2")]
    apply_cmds = list(dict.fromkeys(f"square apply {l.case_id}" for l in awaiting))

    status_payload = {
        "repo": str(repo),
        "square_root": str(sq_root),
        "substrate": sub.name,
        "awaiting_trial": [l.lease_id for l in leases if l.status == "AWAITING_TRIAL"],
        "recommended_apply_commands": apply_cmds,
        "harness_census": census,
        "unmanaged_skills": [u["name"] for u in unmanaged],
        "active_leases": [
            {
                "lease_id": l.lease_id,
                "case_id": l.case_id,
                "substrate": l.substrate_name,
                "dimension": l.dimension,
                "tier": l.tier,
                "components": l.component_paths,
                "activations": f"{l.activations_completed}/{l.activations_target}",
                "unrelated_sessions_seen": l.unrelated_sessions_seen,
                "stale": l.unrelated_sessions_seen >= 10,
            }
            for l in active
        ],
        "staged_tier2_leases": [
            {
                "lease_id": l.lease_id,
                "case_id": l.case_id,
                "substrate": l.substrate_name,
                "dimension": l.dimension,
                "components": l.component_paths,
            }
            for l in leases
            if l.status == "STAGED_TIER_2"
        ],
        "warnings": warnings,
    }
    for w in warnings:
        print(f"[square] Warning: {w}", file=sys.stderr)
    print(json.dumps(status_payload, indent=2))
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    engine = _make_engine(args)
    dim_set: set[Dimension] = set()
    if getattr(args, "inv", False):
        dim_set.add("INV")
    if getattr(args, "dom", False):
        dim_set.add("DOM")
    dims: set[Dimension] | None = dim_set or None
    target = getattr(args, "target", None) or getattr(args, "lease_id", None)

    if getattr(args, "revert", False):
        reverted = engine.revert_active_leases(
            target,
            dims=dims,
            substrate=(args.substrate if args.substrate != "auto" else None),
        )
        print(
            json.dumps(
                {
                    "action": "reverted",
                    "reverted_leases": [l.lease_id for l in reverted],
                    "components_removed": [p for l in reverted for p in l.component_paths],
                },
                indent=2,
            )
        )
        return 0

    try:
        applied = engine.apply_case_leases(
            target,
            dims=dims,
            replace=bool(getattr(args, "replace", False)),
            force=bool(getattr(args, "force", False)),
            substrate=(args.substrate if args.substrate != "auto" else None),
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "action": "applied",
                "applied_leases": [
                    {
                        "lease_id": l.lease_id,
                        "case_id": l.case_id,
                        "dimension": l.dimension,
                        "tier": l.tier,
                        "components": l.component_paths,
                    }
                    for l in applied
                ],
            },
            indent=2,
        )
    )
    return 0


cmd_approve = cmd_apply


def cmd_review(args: argparse.Namespace) -> int:
    """Deterministic, zero-latency Markdown summary of the latest `.square` run in `repo`."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    repo, _ = _resolve_repo_and_library(args)
    sq_root = project_square_dir(repo)
    if not sq_root.is_dir() and (repo / ".square").is_dir():
        sq_root = repo / ".square"
    if not sq_root.is_dir():
        print(f"No Square project directory found for {repo} (expected {sq_root})", file=sys.stderr)
        return 1

    cases_dir = sq_root / "cases"
    audit_dir = sq_root / "audit"
    store = LeaseStore(sq_root)
    leases = store.load_all()

    case_dirs = sorted(
        [d for d in cases_dir.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    ) if cases_dir.is_dir() else []

    if not case_dirs:
        print(f"No cases found in {cases_dir}", file=sys.stderr)
        return 1

    latest_case = case_dirs[0]
    case_id = latest_case.name
    slice_path = latest_case / "slice.json"
    if not slice_path.is_file():
        slice_path = latest_case / "slice_meta.json"
    slice_doc = json.loads(slice_path.read_text(encoding="utf-8", errors="replace")) if slice_path.is_file() else {}

    print(f"## Square Run Review: `{case_id}`\n")
    print(f"- **State Root**: [`{sq_root.name}`](file:///{sq_root.as_posix()})")
    if slice_doc:
        s_uri = slice_path.as_posix()
        print(
            f"- **Friction Slice**: [`{case_id}`](file:///{s_uri}) "
            f"(`{slice_doc.get('slice_type')}`, turns `{slice_doc.get('turn_range')}`, "
            f"thrash_score={slice_doc.get('thrash_score')})"
        )
        print(f"- **Summary**: {slice_doc.get('summary', '')}\n")

    # Gather audit meta files for this case
    metas: list[tuple[str, Path, dict]] = []
    if audit_dir.is_dir():
        for mp in sorted(audit_dir.glob(f"{case_id}.*.meta.json")):
            try:
                mdoc = json.loads(mp.read_text(encoding="utf-8", errors="replace"))
                stage = str(mdoc.get("stage") or mp.stem.split(".")[1])
                metas.append((stage, mp, mdoc))
            except Exception:
                continue

    if metas:
        print("### 1. Telemetry & Tool-Call Breakdown\n")
        print("| Stage | Channel | Model | Elapsed (s) | Turns | Tool Calls | Input Tokens | Cached Tokens | Output Tokens | Audit Meta |")
        print("| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |")
        for stage, mp, mdoc in metas:
            tel = mdoc.get("telemetry") or {}
            usage = tel.get("usage") or {}
            in_tok = usage.get("input_tokens", tel.get("input_tokens", "-"))
            cached_tok = usage.get("cached_input_tokens", tel.get("cached_tokens", "-"))
            out_tok = usage.get("output_tokens", tel.get("output_tokens", "-"))
            turns = tel.get("num_turns", "-")
            t_calls = tel.get("tool_calls_count", len(tel.get("tool_calls") or []))
            wall_s = mdoc.get("wall_s", mdoc.get("elapsed_s", "-"))
            mp_uri = mp.as_posix()
            in_str = f"{in_tok:,}" if isinstance(in_tok, int) else str(in_tok)
            cached_str = f"{cached_tok:,}" if isinstance(cached_tok, int) else str(cached_tok)
            out_str = f"{out_tok:,}" if isinstance(out_tok, int) else str(out_tok)
            print(
                f"| **`{stage}`** | `{mdoc.get('channel')}` | `{mdoc.get('model')}` | "
                f"**{wall_s}s** | {turns} | {t_calls} | "
                f"{in_str} | {cached_str} | {out_str} | "
                f"[`{mp.name}`](file:///{mp_uri}) |"
            )
        print()
        for stage, mp, mdoc in metas:
            tel = mdoc.get("telemetry") or {}
            tc_list = tel.get("tool_calls") or []
            if tc_list:
                print(f"**`{stage}` Tool Calls ({len(tc_list)})**:")
                for idx, tc in enumerate(tc_list, 1):
                    cmd_str = str(tc.get("detail") or tc.get("command") or tc.get("type") or "").strip().replace("\n", " ")
                    if len(cmd_str) > 140:
                        cmd_str = cmd_str[:137] + "..."
                    print(f"  {idx}. `{cmd_str}`")
                print()

    print("### 2. Proposer Outputs (`INV` & `DOM`)\n")
    for stage_name, dim_label in (("inv1", "INV (Mechanics)"), ("dom1", "DOM (Domain / Architecture)")):
        print(f"#### `{stage_name}` — {dim_label}")
        found_resp = False
        for stage, mp, mdoc in metas:
            if stage == stage_name and mdoc.get("response"):
                mp_uri = mp.as_posix()
                print(f"- **Audit Meta**: [`{mp.name}`](file:///{mp_uri})")
                print(f"```markdown\n{str(mdoc['response']).strip()}\n```\n")
                found_resp = True
        if not found_resp and audit_dir.is_dir():
            for rp in sorted(audit_dir.glob(f"{case_id}.{stage_name}.*.response.md")):
                rp_uri = rp.as_posix()
                print(f"- **Response**: [`{rp.name}`](file:///{rp_uri})")
                print(f"```markdown\n{rp.read_text(encoding='utf-8-sig', errors='replace').strip()}\n```\n")

    print("### 3. Active & Staged Leases\n")
    if not leases:
        print("_No leases in `leases.json`._")
    else:
        for l in leases:
            print(f"- **`{l.lease_id}`** (`{l.dimension}`, `{l.tier}`, status=`{l.status}`)")
            for cp in l.component_paths:
                full_cp = (repo / cp).as_posix()
                print(f"  - Component: [`{cp}`](file:///{full_cp})")
                p_disk = repo / cp
                if p_disk.is_file():
                    body = p_disk.read_text(encoding="utf-8-sig", errors="replace").strip()
                    print(f"```markdown\n{body}\n```")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """Scan historical sessions across local transcripts with `gemini-decision-1` and rank
    the best benchmark/test candidates for Square.
    """
    watch_dir = (
        Path(args.watch_dir).resolve()
        if getattr(args, "watch_dir", None)
        else default_agy_brain_dir()
    )
    if not watch_dir.is_dir():
        print(f"Transcript directory not found: {watch_dir}", file=sys.stderr)
        return 1

    min_turns = int(getattr(args, "min_turns", 15))
    limit = int(getattr(args, "limit", 25))
    include_self = bool(getattr(args, "include_self", False))
    repo_only = bool(getattr(args, "repo_only", False)) or (getattr(args, "repo", ".") != ".")
    target_repo, _ = _resolve_repo_and_library(args)
    square_repo_dir = Path(__file__).resolve().parent.parent

    transcript_files = sorted(
        _iter_watch_transcripts(watch_dir),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    candidates: list[tuple[str, object]] = []
    for p in transcript_files:
        if len(candidates) >= limit:
            break
        try:
            _, trace = parse_session_trace(
                p,
                substrate=(args.substrate if args.substrate != "auto" else None),
                workspace_root="",
            )
        except Exception:
            continue
        if len(trace.turns) < min_turns:
            continue
        if not include_self and _trace_belongs_to_repo(
            trace.workspace_root, trace.touched_paths, square_repo_dir, trace.task_prompt
        ):
            continue
        if repo_only and not _trace_belongs_to_repo(
            trace.workspace_root, trace.touched_paths, target_repo, trace.task_prompt
        ):
            continue
        candidates.append((str(p), trace))

    if not candidates:
        print(
            f"No matching session transcripts with >= {min_turns} turns found in {watch_dir}",
            file=sys.stderr,
        )
        return 1

    print(
        f"[square] Scanning {len(candidates)} session(s) (>= {min_turns} turns) with gemini-decision-1...",
        file=sys.stderr,
        flush=True,
    )
    try:
        report = scan_candidate_sessions(
            candidates,  # type: ignore[arg-type]
            signal_threshold=float(getattr(args, "threshold", 0.60)),
        )
    except DecisionAPIError as exc:
        print(f"[square] Decision scan error: {exc}", file=sys.stderr)
        return 1

    md_text = render_scan_markdown(report)
    scan_dir = default_square_home() / "scan"
    scan_dir.mkdir(parents=True, exist_ok=True)
    md_path = scan_dir / "SCAN_REPORT.md"
    json_path = scan_dir / "scan.json"
    md_path.write_text(md_text, encoding="utf-8")
    json_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")

    _print_markdown(md_text, use_glow=not getattr(args, "no_glow", False))
    print(f"\n[square] Saved scan report: {md_path}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="square",
        description="Square (.square): Standalone Recursive Agent Harnessing",
    )
    p.add_argument("--repo", default=".", help="Path to repository root (default: current dir)")
    p.add_argument(
        "--global-surface",
        action="store_true",
        help="Target global Antigravity surface (~/.gemini/config) and global Continual Improvement Library",
    )
    p.add_argument(
        "--no-library",
        action="store_true",
        help="Disable reading from Continual Improvement Library R_t (for clean A/B benchmarks)",
    )
    p.add_argument(
        "--substrate",
        default="antigravity",
        choices=["auto", "antigravity", "codex", "opencode", "claude"],
        help="Target agent substrate SurfaceSpec (default: antigravity)",
    )
    p.add_argument(
        "--channel",
        default="codex_cli",
        choices=["codex_cli", "agy_cli", "claude_cli", "opencode"],
        help="Proposer CLI channel (default: codex_cli)",
    )
    p.add_argument("--model", default="", help="Proposer model identifier (optional)")
    p.add_argument(
        "--latest",
        action="store_true",
        help="Find and process the latest session transcript for the current repo and exit",
    )
    p.add_argument(
        "--watch-dir",
        default=None,
        help="Optional brain/transcript directory override when using --latest",
    )

    sub = p.add_subparsers(dest="subcommand", required=False)

    p_ing = sub.add_parser(
        "ingest",
        help="Probe active leases on a session transcript and compose ready leases (--propose opts into slice detection)",
    )
    p_ing.add_argument(
        "transcript",
        nargs="?",
        default=None,
        help="Path to transcript .jsonl file (optional if --latest is set)",
    )
    p_ing.add_argument(
        "--latest",
        action="store_true",
        help="Automatically find and ingest the latest transcript for this repo",
    )
    p_ing.add_argument(
        "--propose",
        action="store_true",
        help="Opt in to deterministic slice detection and background proposal generation on unleased dimensions",
    )
    p_ing.add_argument(
        "--no-library",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Disable reading from Continual Improvement Library R_t",
    )
    p_ing.add_argument(
        "--watch-dir",
        default=None,
        help="Directory containing transcripts when using --latest (default: ~/.gemini/antigravity/brain)",
    )
    p_ing.set_defaults(func=cmd_ingest)

    p_analyze = sub.add_parser(
        "analyze",
        help="Review one past session across INV and DOM and save untested proposals; no live edits",
    )
    p_analyze.add_argument("transcript", nargs="?", help="Transcript JSONL path; omit to find latest")
    p_analyze.add_argument("--latest", action="store_true")
    p_analyze.add_argument(
        "--retry",
        action="store_true",
        help="Start another pass instead of returning the saved report (uses model calls)",
    )
    p_analyze.add_argument(
        "--with-triage",
        action="store_true",
        help="Run gemini-decision-1 strictly as an attention spotlight (never skips INV or DOM)",
    )
    p_analyze.add_argument(
        "--no-triage",
        action="store_true",
        help="Skip gemini-decision-1 triage (default)",
    )
    p_analyze.add_argument(
        "--no-library",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Disable reading from Continual Improvement Library R_t (for clean A/B benchmarks)",
    )
    p_analyze.add_argument("--force-propose", action="store_true", help=argparse.SUPPRESS)
    p_analyze.add_argument(
        "--no-glow",
        action="store_true",
        help="Print raw Markdown instead of piping through glow",
    )
    p_analyze.add_argument("--watch-dir", default=None)
    p_analyze.set_defaults(func=cmd_ingest, analyze=True)

    p_triage = sub.add_parser(
        "triage",
        help="Run gemini-decision-1 triage in isolation on a session transcript and print the scorecard",
    )
    p_triage.add_argument("transcript", nargs="?", help="Transcript JSONL path; omit to find latest")
    p_triage.add_argument("--latest", action="store_true")
    p_triage.add_argument("--window-size", type=int, default=8, help="Number of turns per evaluation window (default: 8)")
    p_triage.add_argument("--stride", type=int, default=6, help="Turn step between windows (default: 6)")
    p_triage.add_argument("--threshold", type=float, default=0.65, help="Probability threshold to flag a signal (default: 0.65)")
    p_triage.add_argument("--no-glow", action="store_true", help="Print raw Markdown instead of piping through glow")
    p_triage.add_argument("--watch-dir", default=None)
    p_triage.set_defaults(func=cmd_ingest, triage_only=True)

    p_scan = sub.add_parser(
        "scan",
        help="Batch-scan historical sessions with gemini-decision-1 and rank the best test cases for Square",
    )
    p_scan.add_argument(
        "--min-turns",
        type=int,
        default=15,
        help="Minimum number of turns required to include a session (default: 15)",
    )
    p_scan.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum number of recent sessions to scan (default: 25)",
    )
    p_scan.add_argument(
        "--threshold",
        type=float,
        default=0.60,
        help="Probability threshold for macro signal flags (default: 0.60)",
    )
    p_scan.add_argument(
        "--repo-only",
        action="store_true",
        help="Only scan sessions belonging to --repo (by default scans across all repos)",
    )
    p_scan.add_argument(
        "--include-self",
        action="store_true",
        help="Include sessions on the square repository itself (excluded by default)",
    )
    p_scan.add_argument("--no-glow", action="store_true", help="Print raw Markdown instead of piping through glow")
    p_scan.add_argument("--watch-dir", default=None, help="Directory of transcripts to scan (default: ~/.gemini/antigravity/brain)")
    p_scan.set_defaults(func=cmd_scan)

    p_wat = sub.add_parser(
        "watch",
        help="Watch a directory of session transcripts (probe-only by default; --propose opts into slice detection)",
    )
    p_wat.add_argument(
        "watch_dir",
        nargs="?",
        default=None,
        help="Directory containing .jsonl transcripts (default: ~/.gemini/antigravity/brain)",
    )
    p_wat.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    p_wat.add_argument(
        "--settle",
        type=float,
        default=10.0,
        help="Seconds a transcript must be idle before processing (default: 10.0s)",
    )
    p_wat.add_argument(
        "--max-iterations", type=int, default=0, help="Stop after N polls (0 = infinite)"
    )
    p_wat.add_argument(
        "--propose",
        action="store_true",
        help="Opt in to deterministic slice detection and background proposal generation on unleased dimensions",
    )
    p_wat.add_argument(
        "--no-library",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Disable reading from Continual Improvement Library R_t",
    )
    p_wat.set_defaults(func=cmd_watch)

    p_st = sub.add_parser("status", help="Show harness census and active/staged leases")
    p_st.set_defaults(func=cmd_status)

    p_app = sub.add_parser(
        "apply",
        aliases=["approve"],
        help="Materialize candidate proposals as active workspace leases (or --revert them cleanly)",
    )
    p_app.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Case ID or Lease ID to apply/revert (defaults to latest awaiting case, or all active leases with --revert)",
    )
    p_app.add_argument("--inv", action="store_true", help="Apply or revert only the INV dimension")
    p_app.add_argument("--dom", action="store_true", help="Apply or revert only the DOM dimension")
    p_app.add_argument("--revert", action="store_true", help="Cleanly revert matching active leases from the workspace")
    p_app.add_argument("--replace", action="store_true", help="Revert any conflicting active lease in the same dimension slot before applying")
    p_app.add_argument("--force", action="store_true", help="Bypass Tier 2 Python script pre-flight checks")
    p_app.set_defaults(func=cmd_apply)

    p_rev = sub.add_parser(
        "review", help="Print an instant Markdown summary of the latest .square run in --repo"
    )
    p_rev.set_defaults(func=cmd_review)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        if getattr(args, "latest", False):
            return int(cmd_ingest(args))
        parser.print_help(sys.stderr)
        return 2
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
