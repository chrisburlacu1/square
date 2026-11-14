"""Deterministic Intra-Session Trajectory Slicer ($T_{1..Y-1}, T_Y, T_{Y+1}$).

Implements Invariant #2 (Zero-Cost Wake-Up Gate & Deliverable Evidence) and
Invariant #8 (Two-Horizon $T_{Y+1}$ Detection: Intra-Session Rewrites + Cross-Commit Git Survival).
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path

from .schemas import FileMutation, NormalizedTurn, SessionTrace, TrajectorySlice

_INSPECTION_CMD_PATTERNS = re.compile(
    r"\b(javap|jar\s+tf|unzip\s+-l|nm|objdump|strings)\b",
    re.I,
)
_SHELL_TOOL_NAMES = {"bash", "run_command", "shell", "cmd", "exec"}


def _line_hash(line: str) -> str:
    return hashlib.sha1(line.strip().encode("utf-8", errors="replace")).hexdigest()[:12]


def _unified_diff(before: str, after: str, path: str, label_a: str = "a", label_b: str = "b") -> str:
    return "".join(
        difflib.unified_diff(
            (before or "").splitlines(keepends=True),
            (after or "").splitlines(keepends=True),
            fromfile=f"{label_a}/{path}",
            tofile=f"{label_b}/{path}",
        )
    )


def _command_family(cmd: str) -> str:
    """Group commands by their leading tool/binary or target file."""
    tokens = cmd.strip().split()
    if not tokens:
        return "unknown"
    head = Path(tokens[0]).stem.lower()
    if head in ("python", "python3", "bash", "sh", "pwsh", "powershell", "./gradlew", "gradlew"):
        if len(tokens) > 1:
            return f"{head}:{tokens[1].lower()}"
    return head


def detect_mechanical_thrash(
    trace: SessionTrace,
    *,
    min_consecutive_steps: int = 4,
    min_errors: int = 2,
    min_repetitive_inspections: int = 4,
) -> list[TrajectorySlice]:
    """Scan `trace.turns` for runs of >= K consecutive tool steps without user intervention
    that either:
      1. Produce >= 2 non-zero exit codes / [OBSERVATION ERROR] events on the same command
         family or file before achieving exit code 0 at T_Y, OR
      2. Execute >= 4 repetitive inspection/search commands (e.g., javap, jar tf, grep,
         read_file) culminating in a synthesis turn T_Y.
    """
    slices: list[TrajectorySlice] = []
    n = len(trace.turns)
    i = 0

    while i < n:
        turn = trace.turns[i]
        if turn.role != "assistant" or not turn.tool_calls:
            i += 1
            continue

        # Collect consecutive assistant turns (without a substantive user rewrite in between)
        run_start = i
        j = i
        total_tool_steps = 0
        error_count = 0
        shell_inspection_count = 0
        target_read_counts: dict[str, int] = {}
        family_errors: dict[str, int] = {}
        t_y = i
        touched: set[str] = set()

        while j < n and trace.turns[j].role == "assistant":
            t = trace.turns[j]
            total_tool_steps += len(t.tool_calls)
            for fm in t.file_mutations:
                touched.add(fm.path.replace("\\", "/"))
            for tc in t.tool_calls:
                t_name = tc.tool_name.lower()
                target = (tc.command_or_target or "").strip()
                if tc.is_error or tc.exit_code not in (None, 0):
                    error_count += 1
                    fam = _command_family(target or tc.tool_name)
                    family_errors[fam] = family_errors.get(fam, 0) + 1
                if t_name in _SHELL_TOOL_NAMES and _INSPECTION_CMD_PATTERNS.search(target):
                    shell_inspection_count += 1
                elif t_name in ("read_file", "grep", "grep_search", "find_by_name") and target:
                    norm_target = target.replace("\\", "/").lower()
                    target_read_counts[norm_target] = target_read_counts.get(norm_target, 0) + 1
            t_y = j
            j += 1

        max_same_target_reads = max(target_read_counts.values(), default=0)
        inspection_count = max(shell_inspection_count, max_same_target_reads)
        has_repeated_family_error = any(cnt >= min_errors for cnt in family_errors.values()) or (
            error_count >= min_errors
        )
        has_inspection_thrash = inspection_count >= min_repetitive_inspections

        if total_tool_steps >= min_consecutive_steps and (
            has_repeated_family_error or has_inspection_thrash
        ):
            # Find T_Y (the convergence turn at the end of the run) and T_{Y+1}
            t_y1 = min(t_y + 1, n - 1)
            at_ty_patch = _build_mutations_patch(trace.turns[run_start : t_y + 1])
            slice_id = f"{trace.session_id}_mech_{run_start}_{t_y}"
            slices.append(
                TrajectorySlice(
                    slice_id=slice_id,
                    session_id=trace.session_id,
                    domain=trace.domain,
                    thrash_type="MECHANICAL_THRASH",
                    t_start=trace.turns[run_start].turn_index,
                    t_y=trace.turns[t_y].turn_index,
                    t_y1=trace.turns[t_y1].turn_index,
                    turn_count=(t_y - run_start + 1),
                    error_count=error_count,
                    survival_ratio=1.0,
                    summary=(
                        f"Mechanical thrash over {total_tool_steps} tool steps "
                        f"({error_count} errors, {inspection_count} inspections) "
                        f"converging at turn {trace.turns[t_y].turn_index}."
                    ),
                    touched_files=sorted(touched),
                    at_t_y_diff=at_ty_patch,
                    survival_t_y1_diff="",
                )
            )
            i = j
        else:
            i = max(i + 1, j)

    return slices


def _is_substantive_line(line: str) -> bool:
    s = line.strip()
    if not s or s in ("{", "}", "};", ");", ")"):
        return False
    return True


def detect_semantic_revert(
    trace: SessionTrace,
    *,
    overwrite_threshold: float = 0.40,
) -> list[TrajectorySlice]:
    """Intra-Session $T_{Y+1}^{\\text{intra}}$ Detector (Invariant #8).

    Tracks file content snapshots at each intermediate mechanical convergence turn $T_Y^{(i)}$
    (where a file edit is followed by a green build/test or a turn boundary returning control
    to the user). Compares the substantive lines newly written at $T_Y^{(i)}$ against the final
    state of that file at $T_{\\text{end}}$ of the same session after subsequent user prompts.
    If >= 40% of the agent-written lines at $T_Y^{(i)}$ were overwritten or deleted in later
    turns $T_{>Y}$ after user nudges, flags `SEMANTIC_REVERT_INTRA`.
    """
    slices: list[TrajectorySlice] = []
    n = len(trace.turns)
    if n < 2:
        return slices

    # Build final file states at T_end
    final_state: dict[str, str] = dict(trace.final_files)
    for t in trace.turns:
        for fm in t.file_mutations:
            norm_path = fm.path.replace("\\", "/")
            if norm_path not in final_state or fm.after_content:
                final_state[norm_path] = fm.after_content

    # Identify candidate convergence turns T_Y^(i) that wrote files and were followed by a user turn
    for idx, turn in enumerate(trace.turns):
        if turn.role != "assistant" or not turn.file_mutations:
            continue

        # Check if there is a subsequent user turn and a subsequent assistant rewrite
        later_user_turns = [
            t for t in trace.turns[idx + 1 :] if t.role == "user" and t.text.strip()
        ]
        if not later_user_turns:
            continue

        # Did this turn (or the immediate next assistant turn before the user turn) converge?
        is_convergence = turn.has_green_validation or (
            idx + 1 < n and trace.turns[idx + 1].role == "user"
        )
        if not is_convergence:
            continue

        for fm in turn.file_mutations:
            norm_path = fm.path.replace("\\", "/")
            # Check if later assistant turns modified this same file after a user prompt
            later_mutations = [
                m
                for t in trace.turns[idx + 1 :]
                if t.role == "assistant"
                for m in t.file_mutations
                if m.path.replace("\\", "/") == norm_path
            ]
            if not later_mutations:
                continue

            before_lines = {
                ln.strip() for ln in (fm.before_content or "").splitlines() if _is_substantive_line(ln)
            }
            raw_ty_lines = [
                ln.strip()
                for ln in fm.after_content.splitlines()
                if _is_substantive_line(ln)
            ]
            # Focus on newly authored lines at T_Y if before_content existed, else all substantive lines
            ty_lines = [ln for ln in raw_ty_lines if ln not in before_lines] or raw_ty_lines
            if not ty_lines:
                continue

            end_content = final_state.get(norm_path, later_mutations[-1].after_content)
            end_line_set = {
                ln.strip() for ln in end_content.splitlines() if _is_substantive_line(ln)
            }

            surviving = sum(1 for ln in ty_lines if ln in end_line_set)
            survival_ratio = round(surviving / len(ty_lines), 4)
            overwritten_ratio = 1.0 - survival_ratio

            if overwritten_ratio >= overwrite_threshold:
                t_start = trace.turns[0].turn_index
                t_y = turn.turn_index
                t_y1 = trace.turns[-1].turn_index
                at_ty_diff = _unified_diff(
                    fm.before_content or "", fm.after_content, norm_path, "before", "at_T_Y"
                )
                survival_diff = _unified_diff(
                    fm.after_content, end_content, norm_path, "at_T_Y", "at_T_Y1"
                )
                user_nudges = "\n---\n".join(ut.text.strip() for ut in later_user_turns)
                slice_id = f"{trace.session_id}_sem_intra_{t_y}_{Path(norm_path).stem}"
                slices.append(
                    TrajectorySlice(
                        slice_id=slice_id,
                        session_id=trace.session_id,
                        domain=trace.domain,
                        thrash_type="SEMANTIC_REVERT_INTRA",
                        t_start=t_start,
                        t_y=t_y,
                        t_y1=t_y1,
                        turn_count=len(trace.turns),
                        error_count=sum(1 for t in trace.turns if t.has_errors),
                        survival_ratio=survival_ratio,
                        summary=(
                            f"Intra-session semantic revert on `{norm_path}`: turn {t_y} "
                            f"converged cleanly, but {overwritten_ratio:.0%} of written lines "
                            f"were overwritten by turn {t_y1} after {len(later_user_turns)} "
                            f"user nudge(s)."
                        ),
                        touched_files=[norm_path],
                        at_t_y_diff=at_ty_diff,
                        survival_t_y1_diff=survival_diff,
                        user_nudge_text=user_nudges,
                    )
                )
                break  # One slice per convergence file per session is sufficient

        if slices:
            break

    return slices


def record_pending_git_survival(
    trace: SessionTrace,
    workspace_dir: Path,
) -> Path | None:
    """Save hunk/line hashes of final agent-authored changes in `.square/workspace/pending_survival.json`
    for cross-commit $T_{Y+1}^{\\text{git}}$ survival checking on the next session.
    """
    file_records: dict[str, dict] = {}
    for t in trace.turns:
        for fm in t.file_mutations:
            norm_path = fm.path.replace("\\", "/")
            if fm.after_content:
                lines = [ln.strip() for ln in fm.after_content.splitlines() if ln.strip()]
                if lines:
                    file_records[norm_path] = {
                        "after_content": fm.after_content,
                        "line_hashes": [_line_hash(ln) for ln in lines],
                    }
    if not file_records:
        return None

    workspace_dir = Path(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    pending_path = workspace_dir / "pending_survival.json"
    existing: list[dict] = []
    if pending_path.is_file():
        try:
            existing = json.loads(pending_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = []

    existing.append(
        {
            "session_id": trace.session_id,
            "domain": trace.domain,
            "workspace_root": trace.workspace_root,
            "files": file_records,
        }
    )
    pending_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return pending_path


def evaluate_pending_git_survival(
    workspace_dir: Path,
    repo_root: Path | None = None,
    *,
    overwrite_threshold: float = 0.40,
) -> list[TrajectorySlice]:
    """Evaluate cross-commit $T_{Y+1}^{\\text{git}}$ survival against the current working tree / HEAD."""
    pending_path = Path(workspace_dir) / "pending_survival.json"
    if not pending_path.is_file():
        return []

    try:
        entries = json.loads(pending_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    slices: list[TrajectorySlice] = []
    for entry in entries:
        session_id = entry.get("session_id", "prev")
        domain = entry.get("domain", "default")
        root = Path(repo_root or entry.get("workspace_root") or ".")
        files: dict[str, dict] = entry.get("files") or {}

        for rel_path, meta in files.items():
            hashes = meta.get("line_hashes") or []
            ty_content = meta.get("after_content") or ""
            if not hashes:
                continue
            disk_path = root / rel_path
            if not disk_path.is_file():
                # In synthetic transcripts where files were not materialized on disk, skip
                continue
            current_content = disk_path.read_text(encoding="utf-8", errors="replace")
            current_hashes = {
                _line_hash(ln) for ln in current_content.splitlines() if ln.strip()
            }

            surviving = sum(1 for h in hashes if h in current_hashes)
            survival_ratio = round(surviving / len(hashes), 4)
            if (1.0 - survival_ratio) >= overwrite_threshold:
                diff = _unified_diff(ty_content, current_content, rel_path, "at_T_Y", "git_HEAD")
                slices.append(
                    TrajectorySlice(
                        slice_id=f"{session_id}_sem_git_{Path(rel_path).stem}",
                        session_id=session_id,
                        domain=domain,
                        thrash_type="SEMANTIC_REVERT_GIT",
                        t_start=0,
                        t_y=1,
                        t_y1=2,
                        turn_count=1,
                        error_count=0,
                        survival_ratio=survival_ratio,
                        summary=(
                            f"Post-session git survival revert on `{rel_path}`: "
                            f"only {survival_ratio:.0%} of agent-authored lines survived in the working tree."
                        ),
                        touched_files=[rel_path],
                        at_t_y_diff="",
                        survival_t_y1_diff=diff,
                    )
                )

    pending_path.unlink(missing_ok=True)
    return slices


def detect_slices(trace: SessionTrace) -> list[TrajectorySlice]:
    """Run both deterministic detectors on `trace` at zero LLM cost."""
    out: list[TrajectorySlice] = []
    out.extend(detect_semantic_revert(trace))
    out.extend(detect_mechanical_thrash(trace))
    return out


def _build_mutations_patch(
    turns: list[NormalizedTurn],
    *,
    max_file_diff_chars: int = 3_000,
    max_total_chars: int = 24_000,
) -> str:
    """Build a compact unified diff of the net before -> after changes across `turns`."""
    first_before: dict[str, str] = {}
    last_after: dict[str, str] = {}
    for t in turns:
        for fm in t.file_mutations:
            norm_path = fm.path.replace("\\", "/")
            if norm_path not in first_before:
                first_before[norm_path] = fm.before_content or ""
            last_after[norm_path] = fm.after_content

    diffs: list[str] = []
    total_chars = 0
    for norm_path, after in last_after.items():
        before = first_before.get(norm_path, "")
        d = _unified_diff(before, after, norm_path, "before", "at_T_Y")
        if not d:
            continue
        if max_file_diff_chars and len(d) > max_file_diff_chars:
            half = max_file_diff_chars // 2
            d = (
                f"{d[:half]}\n"
                f"... [truncated {len(d) - max_file_diff_chars} chars in {norm_path} diff] ...\n"
                f"{d[-half:]}\n"
            )
        if max_total_chars and total_chars + len(d) > max_total_chars:
            diffs.append(f"... [remaining file diffs truncated after {max_total_chars} chars] ...")
            break
        diffs.append(d)
        total_chars += len(d)
    return "\n".join(diffs)


_READ_ONLY_TOOLS = frozenset(
    {"read_file", "read", "view_file", "cat", "grep", "grep_search", "find_by_name", "list_dir"}
)


def render_trace_markdown(
    trace: SessionTrace,
    slice_obj: TrajectorySlice | None = None,
    *,
    obs_trunc: int = 2_500,
    read_obs_trunc: int = 350,
    max_chars: int = 36_000,
    context_turns_before: int = 2,
    context_turns_after: int = 2,
) -> str:
    """Render a `SessionTrace` (or the relevant slice window `[t_start .. t_y1]`) into the shared
    `[USER] / [ASSISTANT] / [REASONING] / [ACTION] / [OBSERVATION] / [OBSERVATION ERROR]` grammar.
    """
    turns = trace.turns
    if slice_obj is not None and turns:
        min_idx = max(0, slice_obj.t_start - context_turns_before)
        max_idx = slice_obj.t_y1 + context_turns_after
        window = [
            t
            for t in turns
            if t.turn_index == 0 or (min_idx <= t.turn_index <= max_idx)
        ]
        # If the slice window spans > 16 turns, focus on the initial user prompt,
        # the turns around each error, and the final convergence + T_{Y+1} turns
        if len(window) > 16:
            error_positions = {
                idx for idx, t in enumerate(window) if t.has_errors or t.role == "user"
            }
            keep_positions: set[int] = {0, 1, len(window) - 3, len(window) - 2, len(window) - 1}
            for ep in error_positions:
                for offset in (-1, 0, 1):
                    if 0 <= ep + offset < len(window):
                        keep_positions.add(ep + offset)
            turns = [window[idx] for idx in sorted(keep_positions) if 0 <= idx < len(window)]
        elif window:
            turns = window
    elif not turns and trace.raw_trajectory_md.strip():
        return trace.raw_trajectory_md

    lines: list[str] = []
    for t in turns:
        tag = t.role.upper()
        if t.reasoning.strip():
            lines.append(f"[REASONING] (turn {t.turn_index}) {t.reasoning.strip()}")
        if t.text.strip():
            lines.append(f"[{tag}] (turn {t.turn_index}) {t.text.strip()}")
        for tc in t.tool_calls:
            norm_target = tc.command_or_target.replace("\\", "/").lower()
            if "/.system_generated/logs/" in norm_target and "/transcript" in norm_target:
                continue
            lines.append(f"[ACTION] (turn {t.turn_index}) {tc.tool_name}: {tc.command_or_target}")
            is_err = tc.is_error or tc.exit_code not in (None, 0)
            obs_tag = "OBSERVATION ERROR" if is_err else "OBSERVATION"
            suffix = f" | exit_code={tc.exit_code}" if tc.exit_code not in (None, 0) else ""
            out = tc.output.strip()
            limit = (
                read_obs_trunc
                if (not is_err and tc.tool_name.lower() in _READ_ONLY_TOOLS)
                else obs_trunc
            )
            if limit and len(out) > limit:
                half = limit // 2
                out = (
                    f"{out[:half]}\n... [truncated {len(out) - limit} chars] ...\n{out[-half:]}"
                )
            lines.append(f"[{obs_tag}] {out}{suffix}")
        if not t.tool_calls:
            for fm in t.file_mutations:
                lines.append(f"[ACTION] (turn {t.turn_index}) write_file: {fm.path}")

    rendered = "\n".join(lines)
    if max_chars and len(rendered) > max_chars:
        half = max_chars // 2
        rendered = (
            f"{rendered[:half]}\n\n"
            f"... [truncated {len(rendered) - max_chars} chars of middle trajectory turns] ...\n\n"
            f"{rendered[-half:]}"
        )
    return rendered


def populate_case_workspace(
    case_dir: Path,
    trace: SessionTrace,
    slice_obj: TrajectorySlice,
) -> Path:
    """When a trigger fires, creates a lightweight case record in `cases/case_<id>/` containing:
      - `slice.json` (metadata, task prompt, and `at_t_y_diff` / `survival_t_y1_diff`)
      - `trajectory.md` (rendered slice window)
    """
    case_dir = Path(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)

    task_md = trace.task_prompt.strip()
    if not task_md:
        first_users = [t.text.strip() for t in trace.turns if t.role == "user" and t.text.strip()]
        task_md = first_users[0] if first_users else f"Interactive coding session {trace.session_id}"

    slice_payload = slice_obj.to_dict()
    slice_payload["task_prompt"] = task_md
    (case_dir / "slice.json").write_text(
        json.dumps(slice_payload, indent=2), encoding="utf-8"
    )

    traj_md = render_trace_markdown(trace, slice_obj=slice_obj)
    (case_dir / "trajectory.md").write_text(traj_md, encoding="utf-8")
    return case_dir
