"""ClaudeSubstrate: `CLAUDE_SURFACE` (`CLAUDE.md`, `.claude/skills/`, `sub_agents/`,
`scripts/`, `.claude/hooks.json`) and Claude Code JSONL transcript renderer.
"""

from __future__ import annotations

from pathlib import Path

from ..schemas import FileMutation, Lease, NormalizedTurn, SessionTrace, ToolCallRecord
from ..tree import SurfaceSpec, Tree
from .base import (
    apply_lease_to_workspace,
    extract_mutation_from_tool_call,
    parse_jsonl_lines,
    read_clean_workspace_tree,
    render_trace_to_grammar,
    revert_lease_from_workspace,
    text_of,
)

CLAUDE_SURFACE = SurfaceSpec(
    name="claude",
    always_on=("CLAUDE.md",),
    always_on_max=100_000,
    always_on_cap_reason=(
        "CLAUDE.md is over the 100,000-character sanity limit and should be modularized"
    ),
    skill_dir=".claude/skills",
    skill_name_rule="overrides_dir",
    trigger_hint=(
        'Fix it by adding a trigger line naming `{name}` to CLAUDE.md, e.g. "When '
        "<the situation this skill handles>, read .claude/skills/{name}/SKILL.md "
        'and follow it."'
    ),
    autotrigger_file="CLAUDE.md",
    trigger_line="- When {desc}, read .claude/skills/{name}/SKILL.md and follow it.\n",
    subagent_requires_mode=False,
    plugin_dir=None,
    hooks_file=".claude/hooks.json",
    hook_events=frozenset(
        {
            "PreToolUse",
            "PostToolUse",
            "PermissionRequest",
            "PreCompact",
            "PostCompact",
            "SessionStart",
            "SubagentStart",
            "SubagentStop",
            "UserPromptSubmit",
            "Stop",
        }
    ),
    compile_skill_scripts=True,
    reject_empty_always_on=True,
    stubs=(
        (
            "scripts/README.md",
            "<!-- c7: deterministic helpers, run as `python3 scripts/<name>.py`. "
            "Add one by emitting scripts/<name>.py. -->\n",
        ),
        (
            "sub_agents/README.md",
            "<!-- c5: delegated Claude Code subagents, spawned in their OWN context. Add one as "
            "sub_agents/<name>/AGENT.md with frontmatter `description:`. -->\n",
        ),
        (
            ".claude/README.md",
            "<!-- c8: Claude Code lifecycle hooks -- the only lever that acts INSIDE the tool loop, "
            "so the model cannot skip it. Add ONE file, .claude/hooks.json, Claude-Code hook "
            'schema: {"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": '
            '"command", "command": "..."}]}]}}. -->\n',
        ),
        (
            ".claude/skills/README.md",
            "<!-- c6: reusable workflows. Add one as .claude/skills/<name>/SKILL.md with YAML "
            "frontmatter: `description:` is REQUIRED; `name:` is optional and must match the directory. -->\n",
        ),
    ),
)


class ClaudeSubstrate:
    """Claude Code substrate behind the unified Square `Substrate` interface."""

    name = "claude"

    def surface(self) -> SurfaceSpec:
        return CLAUDE_SURFACE

    def default_tree(self) -> Tree:
        return {"CLAUDE.md": "# Claude Code Repository Instructions\n"}

    def read_workspace_tree(self, repo_root: Path) -> Tree:
        return read_clean_workspace_tree(CLAUDE_SURFACE, Path(repo_root), self.default_tree())

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
        sid = session_id or p.stem
        events = parse_jsonl_lines(p)
        turns: list[NormalizedTurn] = []
        file_states: dict[str, str] = {}
        task_prompt = ""
        turn_idx = 0

        for ev in events:
            role = ev.get("type") or (ev.get("message") or {}).get("role")
            msg = ev.get("message") if isinstance(ev.get("message"), dict) else ev
            content = msg.get("content")

            if role == "user":
                txt = text_of(content)
                if txt.strip():
                    if not task_prompt:
                        task_prompt = txt.strip()
                    turns.append(NormalizedTurn(turn_index=turn_idx, role="user", text=txt))
                    turn_idx += 1
            elif role == "assistant":
                txt_parts: list[str] = []
                reasoning_parts: list[str] = []
                tcs: list[ToolCallRecord] = []
                fms: list[FileMutation] = []

                blocks = (
                    content
                    if isinstance(content, list)
                    else [{"type": "text", "text": str(content or "")}]
                )
                for b in blocks:
                    if not isinstance(b, dict):
                        continue
                    btype = b.get("type")
                    if btype == "text" and b.get("text"):
                        txt_parts.append(str(b["text"]))
                    elif btype == "thinking" and b.get("thinking"):
                        reasoning_parts.append(str(b["thinking"]))
                    elif btype == "tool_use":
                        tname = str(b.get("name") or "tool")
                        args = b.get("input") if isinstance(b.get("input"), dict) else {}
                        target = str(
                            args.get("command")
                            or args.get("file_path")
                            or args.get("path")
                            or tname
                        )
                        tcs.append(
                            ToolCallRecord(
                                tool_name=tname,
                                command_or_target=target,
                                arguments=args,
                                output=str(b.get("output") or ""),
                                exit_code=int(b["exit_code"]) if b.get("exit_code") is not None else None,
                                is_error=bool(b.get("is_error")),
                            )
                        )
                        extract_mutation_from_tool_call(tname, args, file_states, fms)

                turns.append(
                    NormalizedTurn(
                        turn_index=turn_idx,
                        role="assistant",
                        text="\n".join(txt_parts),
                        reasoning="\n".join(reasoning_parts),
                        tool_calls=tcs,
                        file_mutations=fms,
                    )
                )
                turn_idx += 1

        trace = SessionTrace(
            session_id=sid,
            agent_kind="claude",
            domain=domain,
            workspace_root=workspace_root,
            task_prompt=task_prompt,
            turns=turns,
            final_files=file_states,
        )
        trace.raw_trajectory_md = render_trace_to_grammar(
            trace, obs_trunc=obs_trunc, max_chars=max_chars
        )
        return trace

    def materialise_lease(self, repo_root: Path, lease: Lease) -> list[Path]:
        return apply_lease_to_workspace(CLAUDE_SURFACE, Path(repo_root), lease)

    def revert_lease(
        self, repo_root: Path, lease_id: str, lease: Lease | None = None
    ) -> list[Path]:
        return revert_lease_from_workspace(CLAUDE_SURFACE, Path(repo_root), lease_id, lease)
