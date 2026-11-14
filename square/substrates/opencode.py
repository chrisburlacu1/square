"""OpencodeSubstrate: `OPENCODE_SURFACE` and opencode event-stream trajectory renderer.

Ported from `reference/harness2/harness2/substrate/opencode.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..schemas import FileMutation, Lease, NormalizedTurn, SessionTrace, ToolCallRecord
from ..tree import SurfaceSpec, Tree
from .base import (
    _TRUNC_FMT,
    apply_lease_to_workspace,
    clip_text,
    extract_mutation_from_tool_call,
    parse_jsonl_lines,
    read_clean_workspace_tree,
    revert_lease_from_workspace,
)

OPENCODE_SURFACE = SurfaceSpec(
    name="opencode",
    always_on=(
        "systemprompt.md",
        "guardrails.md",
        "LongTermMEMORY.md",
        "tool_descriptions/tool_guidance.md",
    ),
    always_on_max=100_000,
    always_on_cap_reason="always-on files exceed the 100,000-character sanity limit",
    skill_dir="skills",
    skill_name_rule="must_match",
    trigger_hint=(
        "Fix it by adding a trigger line naming `{name}` to systemprompt.md or "
        'guardrails.md, e.g. "When <the situation this skill handles>, load the '
        '`{name}` skill."'
    ),
    autotrigger_file="guardrails.md",
    trigger_line="- When {desc}, load the `{name}` skill.\n",
    subagent_requires_mode=True,
    plugin_dir="plugin",
    hooks_file=None,
    stubs=(
        (
            "scripts/README.md",
            "<!-- c7: deterministic helpers, run as `python3 scripts/<name>.py`. "
            "Add one by emitting scripts/<name>.py. -->\n",
        ),
        (
            "sub_agents/README.md",
            "<!-- c5: delegated subagents, invoked with the `task` tool in their OWN context. "
            "Add one as sub_agents/<name>/AGENT.md with frontmatter `mode: subagent` and "
            "`description:`. -->\n",
        ),
        (
            "plugin/README.md",
            "<!-- c8: OpenCode plugins. Acts INSIDE the tool loop -- the only lever that can "
            "enforce something the model cannot skip. Add one as plugin/<name>.ts. -->\n",
        ),
        (
            "skills/README.md",
            "<!-- c6: reusable workflows loaded on demand via the `skill` tool. Add one as "
            "skills/<name>/SKILL.md with frontmatter `name:` matching the directory and a "
            "`description:`. -->\n",
        ),
    ),
)


def render_events(
    path: Path, *, obs_trunc: int = 50_000, max_chars: int = 400_000, args_trunc: int = 400
) -> str:
    """Render OpenCode's `--format json` JSONL event stream into the shared grammar."""
    text_tags = {"text": "ASSISTANT", "reasoning": "THINKING"}
    args_cap = int(args_trunc)
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"(failed to read trajectory: {e})"
    lines: list[str] = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            ev = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        err = ev.get("error")
        if isinstance(err, dict):
            msg = (
                (err.get("data") or {}).get("message")
                or err.get("message")
                or json.dumps(err)[:300]
            )
            lines.append(f"[ERROR] {clip_text(msg, 300)}")
            continue
        part = ev.get("part") if isinstance(ev.get("part"), dict) else ev
        ptype = part.get("type", ev.get("type"))
        if ptype in text_tags:
            txt = part.get("text") or part.get("content")
            if isinstance(txt, str) and txt.strip():
                lines.append(f"[{text_tags[ptype]}] {clip_text(txt, obs_trunc)}")
        elif ptype in ("tool", "tool_use", "tool_call", "tool-invocation"):
            name = (
                part.get("tool")
                or ev.get("tool")
                or part.get("name")
                or (part.get("toolInvocation") or {}).get("toolName")
                or "tool"
            )
            state = part.get("state") if isinstance(part.get("state"), dict) else part
            status = state.get("status", "")
            tin = state.get("input") or part.get("input") or part.get("args")
            tout = state.get("output") or state.get("result") or part.get("output")
            args = json.dumps(tin, default=str, ensure_ascii=False) if tin is not None else ""
            lines.append(f"[ACTION] {name}({clip_text(args, args_cap)})")
            if status == "error":
                lines.append(f"[OBSERVATION ERROR] {clip_text(state.get('error'), obs_trunc)}")
            elif tout is not None:
                lines.append(f"[OBSERVATION] {clip_text(tout, obs_trunc)}")
    rendered = "\n".join(lines).strip()
    if not rendered:
        return "(no parseable events in trajectory)"
    if len(rendered) > max_chars:
        dropped = len(rendered) - max_chars
        rendered = rendered[:max_chars] + "\n" + _TRUNC_FMT.format(n=dropped)
    return rendered


class OpencodeSubstrate:
    """OpenCode substrate behind the unified Square `Substrate` interface."""

    name = "opencode"

    def surface(self) -> SurfaceSpec:
        return OPENCODE_SURFACE

    def default_tree(self) -> Tree:
        return {
            "systemprompt.md": "# System Role & Procedure\n",
            "guardrails.md": "# Standing Guardrails\n",
            "LongTermMEMORY.md": "# Durable Workspace Memory\n",
            "tool_descriptions/tool_guidance.md": "# Tool Guidance\n",
        }

    def read_workspace_tree(self, repo_root: Path) -> Tree:
        return read_clean_workspace_tree(OPENCODE_SURFACE, Path(repo_root), self.default_tree())

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
            part = ev.get("part") if isinstance(ev.get("part"), dict) else ev
            ptype = part.get("type", ev.get("type"))
            if ptype in ("text", "reasoning"):
                txt = str(part.get("text") or part.get("content") or "")
                if txt.strip():
                    turns.append(
                        NormalizedTurn(
                            turn_index=turn_idx,
                            role="assistant",
                            text=(txt if ptype == "text" else ""),
                            reasoning=(txt if ptype == "reasoning" else ""),
                        )
                    )
                    turn_idx += 1
            elif ptype in ("tool", "tool_use", "tool_call", "tool-invocation"):
                name = str(part.get("tool") or ev.get("tool") or part.get("name") or "tool")
                state = part.get("state") if isinstance(part.get("state"), dict) else part
                tin = state.get("input") or part.get("input") or part.get("args") or {}
                if not isinstance(tin, dict):
                    tin = {"raw": tin}
                tout = str(state.get("output") or state.get("result") or part.get("output") or "")
                is_err = state.get("status") == "error"
                target = str(
                    tin.get("command")
                    or tin.get("filePath")
                    or tin.get("path")
                    or json.dumps(tin, default=str)[:200]
                )
                fms: list[FileMutation] = []
                extract_mutation_from_tool_call(name, tin, file_states, fms)
                turns.append(
                    NormalizedTurn(
                        turn_index=turn_idx,
                        role="assistant",
                        tool_calls=[
                            ToolCallRecord(
                                tool_name=name,
                                command_or_target=target,
                                arguments=tin,
                                output=tout,
                                exit_code=(1 if is_err else 0),
                                is_error=is_err,
                            )
                        ],
                        file_mutations=fms,
                    )
                )
                turn_idx += 1

        raw_md = render_events(p, obs_trunc=obs_trunc, max_chars=max_chars)
        return SessionTrace(
            session_id=sid,
            agent_kind="opencode",
            domain=domain,
            workspace_root=workspace_root,
            task_prompt=task_prompt,
            turns=turns,
            final_files=file_states,
            raw_trajectory_md=raw_md,
        )

    def materialise_lease(self, repo_root: Path, lease: Lease) -> list[Path]:
        return apply_lease_to_workspace(OPENCODE_SURFACE, Path(repo_root), lease)

    def revert_lease(
        self, repo_root: Path, lease_id: str, lease: Lease | None = None
    ) -> list[Path]:
        return revert_lease_from_workspace(OPENCODE_SURFACE, Path(repo_root), lease_id, lease)
