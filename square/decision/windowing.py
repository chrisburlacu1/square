"""Turn-window slicing, batching, and shared context formatting for `gemini-decision-1`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .. import library as harness_library
from ..schemas import NormalizedTurn, SessionTrace
from ..tree import SurfaceSpec, Tree


@dataclass(frozen=True)
class TurnWindow:
    """A contiguous slice of session turns labeled for parallel decision evaluation."""

    window_id: str
    t_start: int
    t_end: int
    turns: tuple[NormalizedTurn, ...]
    preview: str
    rendered_text: str
    turn_digest: tuple[str, ...] = ()

    @property
    def turn_span(self) -> str:
        return f"Turns {self.t_start}..{self.t_end}"


def _clip(text: str, limit: int) -> str:
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit] + f"... [+{len(s) - limit} chars]"


def _is_compaction_log_read(tc_target: str) -> bool:
    norm = (tc_target or "").replace("\\", "/").lower()
    return ".system_generated/logs/transcript" in norm


def _render_single_turn(turn: NormalizedTurn, *, obs_limit: int = 1200) -> str:
    role = turn.role.upper()
    parts: list[str] = [f"[Turn {turn.turn_index} - {role}]"]
    if turn.reasoning.strip():
        parts.append(f"  [THINKING] {_clip(turn.reasoning, 400)}")
    if turn.text.strip():
        parts.append(f"  {_clip(turn.text, 1000)}")
    for tc in turn.tool_calls:
        status = (
            f"ERROR(exit={tc.exit_code})"
            if (tc.is_error or tc.exit_code not in (None, 0))
            else f"ok(exit={tc.exit_code})" if tc.exit_code is not None else "ok"
        )
        raw_target = tc.command_or_target or tc.tool_name
        cmd = _clip(raw_target, 300)
        if _is_compaction_log_read(raw_target):
            continue
        parts.append(f"  [TOOL {tc.tool_name} -> {status}] {cmd}")
        if tc.output.strip():
            parts.append(f"    [OUTPUT] {_clip(tc.output, obs_limit)}")
    for fm in turn.file_mutations:
        parts.append(
            f"  [FILE EDIT] {fm.path} (+{len(fm.added_lines)}/-{len(fm.removed_lines)} lines)"
        )
    if len(parts) == 1:
        return ""
    return "\n".join(parts)


def _build_turn_digest(turns: Sequence[NormalizedTurn]) -> tuple[str, ...]:
    """Build a compact 1-line-per-event digest for human inspection in `TRIAGE.md`."""
    lines: list[str] = []
    for t in turns:
        if t.role == "user" and t.text.strip():
            clean = " ".join(t.text.strip().split())
            lines.append(f"[T{t.turn_index} USER] {_clip(clean, 140)}")
        elif t.role == "assistant":
            for tc in t.tool_calls:
                raw_target = tc.command_or_target or tc.tool_name
                if _is_compaction_log_read(raw_target):
                    continue
                is_err = tc.is_error or tc.exit_code not in (None, 0)
                badge = f"ERR(exit={tc.exit_code})" if is_err else "ok"
                cmd = " ".join(raw_target.strip().split())
                out_hint = ""
                if is_err and tc.output.strip():
                    first_err = " ".join(tc.output.strip().splitlines()[-1].split())
                    out_hint = f" -> {_clip(first_err, 90)}"
                lines.append(f"[T{t.turn_index} {tc.tool_name}:{badge}] {_clip(cmd, 110)}{out_hint}")
            for fm in t.file_mutations:
                lines.append(
                    f"[T{t.turn_index} EDIT] {fm.path} (+{len(fm.added_lines)}/-{len(fm.removed_lines)})"
                )
            if not t.tool_calls and not t.file_mutations and t.text.strip():
                clean = " ".join(t.text.strip().split())
                lines.append(f"[T{t.turn_index} ASST] {_clip(clean, 120)}")
    return tuple(lines[:18])


def _summarize_window_preview(turns: Sequence[NormalizedTurn]) -> str:
    """Create a 1-line human-readable digest of what occurred in `turns`."""
    user_snippets: list[str] = []
    tool_count = 0
    err_count = 0
    tools_seen: list[str] = []
    for t in turns:
        if t.role == "user" and t.text.strip():
            first_line = t.text.strip().splitlines()[0].strip()
            user_snippets.append(_clip(first_line, 60))
        for tc in t.tool_calls:
            tool_count += 1
            if tc.is_error or tc.exit_code not in (None, 0):
                err_count += 1
            label = tc.tool_name
            if label not in tools_seen:
                tools_seen.append(label)

    bits: list[str] = []
    if user_snippets:
        bits.append(f'User: "{user_snippets[0]}"')
    bits.append(f"{tool_count} tool call(s)")
    if err_count:
        bits.append(f"{err_count} error(s)")
    if tools_seen:
        bits.append("tools=" + ",".join(tools_seen[:4]))
    return " | ".join(bits)


def slice_into_windows(
    trace: SessionTrace,
    *,
    window_size: int = 8,
    stride: int = 6,
    max_windows: int | None = None,
) -> list[TurnWindow]:
    """Slice `trace.turns` into overlapping `TurnWindow`s for fine-grained signal localization."""
    turns = list(trace.turns)
    if not turns:
        if trace.raw_trajectory_md.strip():
            return [
                TurnWindow(
                    window_id="w0",
                    t_start=0,
                    t_end=0,
                    turns=(),
                    preview="Raw trajectory text (no parsed turn list)",
                    rendered_text=_clip(trace.raw_trajectory_md, 40_000),
                    turn_digest=("[T0] Raw trajectory text",),
                )
            ]
        return []

    w_size = max(2, int(window_size))
    step = max(1, int(stride))
    n = len(turns)
    windows: list[TurnWindow] = []

    idx = 0
    w_num = 0
    while idx < n and (max_windows is None or w_num < max_windows):
        chunk = turns[idx : idx + w_size]
        if not chunk:
            break
        wid = f"w{w_num}"
        t_start = chunk[0].turn_index
        t_end = chunk[-1].turn_index
        rendered = "\n".join(_render_single_turn(t) for t in chunk)
        windows.append(
            TurnWindow(
                window_id=wid,
                t_start=t_start,
                t_end=t_end,
                turns=tuple(chunk),
                preview=_summarize_window_preview(chunk),
                rendered_text=rendered,
                turn_digest=_build_turn_digest(chunk),
            )
        )
        w_num += 1
        if idx + w_size >= n:
            break
        idx += step

    return windows


def summarize_current_harness(
    surface: SurfaceSpec,
    harness: Tree,
    unmanaged_skills: Sequence[dict[str, str]] = (),
) -> str:
    """Format a compact summary of the current repository harness for `# CURRENT HARNESS SUMMARY`."""
    if not harness and not unmanaged_skills:
        return "(empty harness)"
    lines: list[str] = [f"Substrate: `{surface.name}`"]
    for rel in sorted(harness):
        body = harness[rel]
        if rel in surface.always_on:
            lines.append(f"## Always-On File `{rel}` ({len(body):,} chars)\n{_clip(body, 6_000)}")
        elif rel.endswith("SKILL.md"):
            fm, _ = harness_library.parse_frontmatter(body)
            desc = str(fm.get("description") or "").strip().replace("\n", " ")
            lines.append(f"- Skill `{rel}` ({len(body):,} chars): {_clip(desc, 300)}")
        else:
            lines.append(f"- Component `{rel}` ({len(body):,} chars): {_clip(body, 600)}")
    if unmanaged_skills:
        ro_lines = [
            f"- Read-Only Skill `{s.get('name') or s.get('path')}` (`{s.get('path')}`): {_clip(str(s.get('description') or ''), 300)}"
            for s in unmanaged_skills
        ]
        lines.append("## Pre-existing Read-Only Workspace Skills\n" + "\n".join(ro_lines))
    return "\n\n".join(lines)


def format_executive_digest(all_windows: Sequence[TurnWindow], *, max_chars: int = 24_000) -> str:
    """Build a compact start-to-finish digest across all windows for macro root-cause questions."""
    seen: set[str] = set()
    lines: list[str] = []
    for w in all_windows:
        lines.append(f"--- {w.window_id} ({w.turn_span}): {w.preview} ---")
        for item in w.turn_digest:
            if item not in seen:
                seen.add(item)
                lines.append(f"  {item}")
    return _clip("\n".join(lines), max_chars)


def format_shared_input(
    trace: SessionTrace,
    windows: Sequence[TurnWindow],
    *,
    surface: SurfaceSpec,
    harness: Tree,
    all_windows: Sequence[TurnWindow] | None = None,
    unmanaged_skills: Sequence[dict[str, str]] = (),
    max_total_chars: int = 350_000,
) -> str:
    """Assemble the single shared `input` string sent to `gemini-decision-1`."""
    sections: list[str] = [
        "# CURRENT HARNESS SUMMARY\n"
        + summarize_current_harness(surface, harness, unmanaged_skills=unmanaged_skills),
        "# TASK / INITIAL USER REQUEST\n" + _clip(trace.task_prompt or "(none)", 4_000),
    ]
    if all_windows:
        sections.append(
            "# FULL SESSION EXECUTIVE DIGEST\n" + format_executive_digest(all_windows)
        )
    sections.append("# SESSION TRANSCRIPT WINDOWS")
    for w in windows:
        sections.append(
            f"=== WINDOW {w.window_id} ({w.turn_span}) | {w.preview} ===\n{w.rendered_text}"
        )
    full_text = "\n\n".join(sections)
    return _clip(full_text, max_total_chars)


def batch_windows_for_input(
    windows: Sequence[TurnWindow],
    *,
    max_batch_window_chars: int = 260_000,
    max_windows_per_batch: int = 20,
) -> list[list[TurnWindow]]:
    """Group `windows` into batches so no window's rendered text is ever clipped by the input cap."""
    batches: list[list[TurnWindow]] = []
    cur_batch: list[TurnWindow] = []
    cur_chars = 0

    for w in windows:
        w_len = len(w.rendered_text) + 200
        if cur_batch and (
            len(cur_batch) >= max_windows_per_batch
            or (cur_chars + w_len > max_batch_window_chars)
        ):
            batches.append(cur_batch)
            cur_batch = []
            cur_chars = 0
        cur_batch.append(w)
        cur_chars += w_len

    if cur_batch:
        batches.append(cur_batch)
    return batches
