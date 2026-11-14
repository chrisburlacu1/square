"""AntigravitySubstrate: `AGY_SURFACE` (`GEMINI.md`, `.agents/rules/`, `.agents/skills/`,
`.agents/hooks.json`, `sub_agents/`, `scripts/`), global/project surface helpers, and
Antigravity `transcript.jsonl` renderer.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..schemas import FileMutation, Lease, NormalizedTurn, SessionTrace, ToolCallRecord
from ..tree import SurfaceSpec, Tree
from .base import (
    apply_lease_to_workspace,
    default_square_home,
    extract_mutation_from_tool_call,
    parse_jsonl_lines,
    project_square_dir,
    read_clean_workspace_tree,
    render_trace_to_grammar,
    revert_lease_from_workspace,
)

AGY_HOOK_EVENTS = frozenset(
    {
        "PreToolUse",
        "PostToolUse",
        "SessionStart",
        "Stop",
        "SubagentStop",
        "PreModel",
        "PostModel",
        "BeforeAgent",
        "AfterAgent",
        "BeforeTool",
        "AfterTool",
    }
)

AGY_SURFACE = SurfaceSpec(
    name="antigravity",
    always_on=("GEMINI.md",),
    always_on_max=100_000,
    always_on_cap_reason=(
        "GEMINI.md is over the 100,000-character sanity limit and should be modularized"
    ),
    skill_dir=".agents/skills",
    skill_name_rule="must_match",
    trigger_hint=(
        'Fix it by adding a trigger line naming `{name}` to GEMINI.md, e.g. "When '
        "<the situation this skill handles>, read .agents/skills/{name}/SKILL.md "
        'and follow it."'
    ),
    autotrigger_file="GEMINI.md",
    trigger_line="- When {desc}, read .agents/skills/{name}/SKILL.md and follow it.\n",
    subagent_requires_mode=False,
    plugin_dir=None,
    hooks_file=".agents/hooks.json",
    hook_events=AGY_HOOK_EVENTS,
    rules_dir=".agents/rules",
    compile_skill_scripts=True,
    reject_empty_always_on=True,
    require_skill_triggers_in_always_on=False,
    allow_subagents=False,
    stubs=(
        (
            "scripts/README.md",
            "<!-- c7: deterministic helpers, run as `python3 scripts/<name>.py`. "
            "Add one by emitting scripts/<name>.py. -->\n",
        ),
        (
            ".agents/skills/README.md",
            "<!-- c6: reusable workflows. Add one as .agents/skills/<name>/SKILL.md with YAML "
            "frontmatter: both `name:` (matching the directory) and `description:` are REQUIRED. -->\n",
        ),
        (
            ".agents/rules/README.md",
            "<!-- Modular workspace/domain rules. Add one as .agents/rules/<name>.md. -->\n",
        ),
    ),
)

_USER_REQ_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.S)
_ADD_META_RE = re.compile(r"<ADDITIONAL_METADATA>\s*(.*?)\s*</ADDITIONAL_METADATA>", re.S)
_EXIT_CODE_RE = re.compile(r"(?:Command exited with code|Exit code)\s+(-?\d+)", re.I)
_DOC_PATH_RE = re.compile(r"([A-Za-z]:[/\\][^\r\n]+|/[^\r\n]+)")


def default_agy_brain_dir() -> Path:
    """Default directory where Antigravity stores conversation transcripts."""
    return Path.home() / ".gemini" / "antigravity" / "brain"


def default_agy_global_config_dir() -> Path:
    """Global Antigravity customization root (`~/.gemini/config`)."""
    return Path.home() / ".gemini" / "config"


def default_global_library_root(repo_root: Path | str | None = None) -> Path:
    """Default global Continual Improvement Library root (`~/.square/library`)."""
    if repo_root is not None:
        return project_square_dir(repo_root).parent.parent / "library"
    return default_square_home() / "library"


def _unwrap_arg_val(val: Any) -> Any:
    if isinstance(val, str):
        s = val.strip()
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("{") and s.endswith("}")) or (
            s.startswith("[") and s.endswith("]")
        ):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return val
    return val


def _extract_user_request_and_workspace(content: str) -> tuple[str, list[str]]:
    """Strip `<USER_REQUEST>` wrapper from real Antigravity `USER_INPUT` content and
    extract any workspace file paths mentioned in `<ADDITIONAL_METADATA>`.
    """
    m_req = _USER_REQ_RE.search(content)
    clean_text = m_req.group(1).strip() if m_req else content.strip()
    doc_paths: list[str] = []
    m_meta = _ADD_META_RE.search(content)
    if m_meta:
        for line in m_meta.group(1).splitlines():
            line_s = line.strip()
            if (
                line_s.startswith("Active Document:")
                or line_s.startswith("Command Working Directory:")
                or line_s.startswith("- ")
            ):
                m_path = _DOC_PATH_RE.search(line_s)
                if m_path:
                    raw_p = m_path.group(1).strip()
                    # Strip trailing parenthetical metadata like `(modified, 245 lines, ...)`
                    raw_p = re.sub(r"\s+\([^)]*\)\s*$", "", raw_p).strip()
                    if raw_p:
                        doc_paths.append(raw_p)
    return clean_text, doc_paths


def _infer_session_id_from_path(p: Path) -> str:
    """If reading `.../brain/<conv-id>/.system_generated/logs/transcript.jsonl`,
    return `<conv-id>` instead of `transcript`.
    """
    if p.name in ("transcript.jsonl", "transcript_full.jsonl"):
        if p.parent.name == "logs" and p.parent.parent.name == ".system_generated":
            conv_id = p.parent.parent.parent.name
            if conv_id:
                return conv_id
    return p.stem


class AntigravitySubstrate:
    """Antigravity substrate behind the unified Square `Substrate` interface."""

    name = "antigravity"

    def surface(self) -> SurfaceSpec:
        return AGY_SURFACE

    def default_tree(self) -> Tree:
        return {"GEMINI.md": "# Antigravity Workspace Rules & Instructions\n"}

    def read_workspace_tree(self, repo_root: Path) -> Tree:
        return read_clean_workspace_tree(AGY_SURFACE, Path(repo_root), self.default_tree())

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
        p = Path(path)
        sid = session_id or _infer_session_id_from_path(p)
        events = parse_jsonl_lines(p)
        turns: list[NormalizedTurn] = []
        file_states: dict[str, str] = {}
        task_prompt = ""
        detected_doc_paths: list[str] = []

        # Track tool calls from the latest PLANNER_RESPONSE awaiting subsequent GENERIC outputs
        pending_tcs: list[ToolCallRecord] = []
        pending_tc_cursor = 0

        for idx, ev in enumerate(events):
            step_idx = int(ev.get("step_index", idx))
            stype = ev.get("type", "")
            content = str(ev.get("content") or "")
            thinking = str(ev.get("thinking") or "")

            if stype == "USER_INPUT" or ev.get("source") == "USER_EXPLICIT" or ev.get("role") == "user":
                pending_tcs = []
                pending_tc_cursor = 0
                clean_text, meta_paths = _extract_user_request_and_workspace(content)
                detected_doc_paths.extend(meta_paths)
                if not task_prompt and clean_text:
                    task_prompt = clean_text
                turns.append(
                    NormalizedTurn(
                        turn_index=step_idx,
                        role="user",
                        text=clean_text,
                        timestamp=str(ev.get("created_at") or ""),
                    )
                )
                continue

            # In real Antigravity transcripts, tool execution outputs appear as consecutive
            # `"type": "GENERIC"` steps immediately following a `"PLANNER_RESPONSE"` step.
            if stype == "GENERIC" and not ev.get("tool_calls") and pending_tc_cursor < len(pending_tcs):
                tc = pending_tcs[pending_tc_cursor]
                pending_tc_cursor += 1
                if content and not tc.output:
                    tc.output = content
                m_ec = _EXIT_CODE_RE.search(content)
                if m_ec:
                    tc.exit_code = int(m_ec.group(1))
                if (
                    ev.get("status") == "ERROR"
                    or tc.exit_code not in (None, 0)
                    or "Encountered error in tool execution" in content
                ):
                    tc.is_error = True
                continue

            tcs: list[ToolCallRecord] = []
            fms: list[FileMutation] = []
            for raw_tc in ev.get("tool_calls") or []:
                if not isinstance(raw_tc, dict):
                    continue
                tname = str(raw_tc.get("name") or raw_tc.get("tool_name") or "tool")
                raw_args = raw_tc.get("arguments") or raw_tc.get("args") or {}
                if isinstance(raw_args, str):
                    try:
                        raw_args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        raw_args = {"raw": raw_args}
                if not isinstance(raw_args, dict):
                    raw_args = {}
                args = {k: _unwrap_arg_val(v) for k, v in raw_args.items()}

                cmd_or_target = str(
                    args.get("CommandLine")
                    or args.get("command")
                    or args.get("Path")
                    or args.get("path")
                    or args.get("query")
                    or tname
                )
                out = str(raw_tc.get("output") or raw_tc.get("result") or "")
                exit_code = int(raw_tc["exit_code"]) if raw_tc.get("exit_code") is not None else None
                m_ec = _EXIT_CODE_RE.search(out)
                if m_ec and exit_code in (None, 0):
                    exit_code = int(m_ec.group(1))
                is_err = bool(
                    raw_tc.get("is_error")
                    or ev.get("status") == "ERROR"
                    or exit_code not in (None, 0)
                    or "Encountered error in tool execution" in out
                )
                tcs.append(
                    ToolCallRecord(
                        tool_name=tname,
                        command_or_target=cmd_or_target,
                        arguments=args,
                        output=out,
                        exit_code=exit_code,
                        is_error=is_err,
                    )
                )
                extract_mutation_from_tool_call(tname, args, file_states, fms)

            if tcs:
                pending_tcs = tcs
                pending_tc_cursor = 0
            else:
                pending_tcs = []
                pending_tc_cursor = 0

            if content.strip() or thinking.strip() or tcs or fms:
                turns.append(
                    NormalizedTurn(
                        turn_index=step_idx,
                        role="assistant",
                        text=content,
                        reasoning=thinking,
                        tool_calls=tcs,
                        file_mutations=fms,
                        timestamp=str(ev.get("created_at") or ""),
                    )
                )

        resolved_ws = workspace_root
        if not resolved_ws:
            # Infer workspace path from metadata paths or file tool calls
            candidate_paths = list(detected_doc_paths) + list(file_states.keys())
            for t in turns:
                for tc in t.tool_calls:
                    for key in ("Path", "path", "file_path", "target_file"):
                        v = tc.arguments.get(key)
                        if isinstance(v, str) and v.strip():
                            candidate_paths.append(v.strip())
            for cp in candidate_paths:
                norm_cp = cp.replace("\\", "/")
                if "/.gemini/" in norm_cp or "/.square/" in norm_cp or norm_cp.endswith("/.square"):
                    continue
                resolved_ws = cp
                break

        trace = SessionTrace(
            session_id=sid,
            agent_kind="antigravity",
            domain=domain,
            workspace_root=resolved_ws,
            task_prompt=task_prompt,
            turns=turns,
            final_files=file_states,
        )
        trace.raw_trajectory_md = render_trace_to_grammar(
            trace, obs_trunc=obs_trunc, max_chars=max_chars
        )
        return trace

    def materialise_lease(self, repo_root: Path, lease: Lease) -> list[Path]:
        return apply_lease_to_workspace(AGY_SURFACE, Path(repo_root), lease)

    def revert_lease(
        self, repo_root: Path, lease_id: str, lease: Lease | None = None
    ) -> list[Path]:
        return revert_lease_from_workspace(AGY_SURFACE, Path(repo_root), lease_id, lease)
