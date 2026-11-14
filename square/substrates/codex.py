"""CodexSubstrate: `CODEX_SURFACE` and codex thread-item trajectory renderer.

Ported from `reference/harness2/harness2/substrate/codex.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..schemas import Lease, NormalizedTurn, SessionTrace, ToolCallRecord
from ..tree import SurfaceSpec, Tree
from .base import (
    _TRUNC_FMT,
    apply_lease_to_workspace,
    clip_text,
    read_clean_workspace_tree,
    revert_lease_from_workspace,
    text_of,
)

CODEX_SURFACE = SurfaceSpec(
    name="codex",
    always_on=("AGENTS.md",),
    always_on_max=100_000,
    always_on_cap_reason=(
        "AGENTS.md is over the 100,000-character sanity limit and should be modularized"
    ),
    skill_dir=".agents/skills",
    skill_name_rule="overrides_dir",
    trigger_hint=(
        'Fix it by adding a trigger line naming `{name}` to AGENTS.md, e.g. "When '
        "<the situation this skill handles>, read .agents/skills/{name}/SKILL.md "
        'and follow it."'
    ),
    autotrigger_file="AGENTS.md",
    trigger_line="- When {desc}, read .agents/skills/{name}/SKILL.md and follow it.\n",
    subagent_requires_mode=False,
    plugin_dir=None,
    hooks_file=".codex/hooks.json",
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
            "<!-- c5: delegated codex agent roles, each spawned in its OWN context. Add one as "
            "sub_agents/<name>/AGENT.md with frontmatter `description:`; the runner installs it "
            "as a [agents.<name>] role. -->\n",
        ),
        (
            ".codex/README.md",
            "<!-- c8: codex lifecycle hooks -- the only lever that acts INSIDE the tool loop, "
            "so the model cannot skip it. Add ONE file, .codex/hooks.json, Claude-Code hook "
            'schema: {"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": '
            '"command", "command": "..."}]}]}}. A PostToolUse command that prints '
            '{"decision":"block","reason":"..."} feeds the reason back to the model. -->\n',
        ),
        (
            ".agents/skills/README.md",
            "<!-- c6: reusable workflows. Add one as .agents/skills/<name>/SKILL.md with YAML "
            "frontmatter: `description:` is REQUIRED (no frontmatter = skill silently dropped); "
            "`name:` is optional and must match the directory. Only name+description are "
            "advertised to the agent; the body is read on demand. -->\n",
        ),
    ),
)

_AGENTS_MD_TITLE = "# AGENTS.md instructions"


def parse_items(path: Path) -> list[dict]:
    """Read the exec --json stream (junk tolerated), in stream order, thread-items deduped
    by .item.id: last state wins, first-appearance position kept.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [{"type": "_read_error", "message": str(e)}]
    raw = raw.replace("\x00", "")

    events: list[dict] = []
    by_id: dict[str, int] = {}
    for ln in raw.splitlines():
        ln = ln.strip()
        if not (ln.startswith('{"type":') or ln.startswith('{"timestamp":') or ln.startswith("{")):
            continue
        try:
            ev = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        item = ev.get("item")
        iid = item.get("id") if isinstance(item, dict) else None
        if iid is not None:
            if iid in by_id:
                events[by_id[iid]] = ev
                continue
            by_id[iid] = len(events)
        events.append(ev)
    return events


def _render_item(item: dict, lines: list[str], obs_trunc: int, args_trunc: int) -> None:
    itype = item.get("type", "")

    if itype == "command_execution":
        cmd = clip_text(item.get("command"), args_trunc)
        lines.append(f"[ACTION] shell: {cmd}")
        status = item.get("status")
        exit_code = item.get("exit_code")
        failed = status == "failed" or (exit_code not in (None, 0))
        obs = clip_text(item.get("aggregated_output"), obs_trunc)
        suffix = "" if exit_code in (None, 0) else f" | exit_code={exit_code}"
        if status == "in_progress" and not obs:
            obs = "(no output captured — command still in_progress at end of stream)"
        lines.append(f"[OBSERVATION{' ERROR' if failed else ''}] {obs}{suffix}")
        return

    if itype == "agent_message":
        txt = item.get("text")
        if isinstance(txt, str) and txt.strip():
            lines.append(f"[ASSISTANT] {clip_text(txt, obs_trunc)}")
        return

    if itype == "reasoning":
        txt = text_of(item)
        if txt.strip():
            lines.append(f"[REASONING] {clip_text(txt, obs_trunc)}")
        return

    if itype == "todo_list":
        rows = item.get("items") or []
        if isinstance(rows, list) and rows:
            plan = " | ".join(
                f"[{'x' if r.get('completed') else ' '}] {clip_text(r.get('text'), 200)}"
                for r in rows
                if isinstance(r, dict)
            )
            lines.append(f"[ASSISTANT] plan: {plan}")
        return

    if itype == "error":
        lines.append(f"[HARNESS] {clip_text(item.get('message'), 1000)}")
        return

    if itype in ("user_message", "message"):
        txt = text_of(item)
        if txt.lstrip().startswith(_AGENTS_MD_TITLE):
            lines.append(f"[HARNESS AGENTS.md] {clip_text(txt, obs_trunc)}")
        elif txt.strip():
            lines.append(f"[USER] {clip_text(txt, obs_trunc)}")
        return

    txt = text_of(item)
    if txt.strip():
        lines.append(f"[HARNESS] {itype or 'item'}: {clip_text(txt, obs_trunc)}")


def _emit(lines: list[str], line: str) -> None:
    if not lines or lines[-1] != line:
        lines.append(line)


def _emit_if(lines: list[str], tag: str, txt: str, trunc: int) -> None:
    if txt.strip():
        _emit(lines, f"[{tag}] {clip_text(txt, trunc)}")


def _emit_user(lines: list[str], txt: str, obs_trunc: int) -> None:
    if txt.lstrip().startswith(_AGENTS_MD_TITLE):
        _emit(lines, f"[HARNESS AGENTS.md] {clip_text(txt, obs_trunc)}")
    else:
        _emit_if(lines, "USER", txt, obs_trunc)


def _render_rollout_payload(
    payload: dict, lines: list[str], obs_trunc: int, args_trunc: int
) -> None:
    ptype = payload.get("type", "")
    if ptype == "function_call":
        args = payload.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                pass
        cmd = args.get("cmd") if isinstance(args, dict) else args
        name = payload.get("name") or "shell"
        _emit(lines, f"[ACTION] {name}: {clip_text(cmd if cmd is not None else args, args_trunc)}")
    elif ptype == "function_call_output":
        out = payload.get("output")
        _emit(lines, f"[OBSERVATION] {clip_text(text_of(out) or out, obs_trunc)}")
    elif ptype == "message":
        role = payload.get("role", "")
        txt = text_of(payload)
        if role == "user":
            _emit_user(lines, txt, obs_trunc)
        elif role == "assistant":
            _emit_if(lines, "ASSISTANT", txt, obs_trunc)
        else:
            _emit_if(lines, f"HARNESS {role or 'message'}", txt, obs_trunc)
    elif ptype == "user_message":
        _emit_user(lines, text_of(payload), obs_trunc)
    elif ptype == "agent_message":
        _emit_if(lines, "ASSISTANT", text_of(payload), obs_trunc)
    elif ptype == "reasoning":
        _emit_if(lines, "REASONING", text_of(payload), obs_trunc)


def render_events(
    path: Path, *, obs_trunc: int = 50_000, max_chars: int = 400_000, args_trunc: int = 2000
) -> str:
    """Render a codex exec/rollout stream into the shared grammar."""
    lines: list[str] = []
    for ev in parse_items(Path(path)):
        et = ev.get("type", "")
        if et == "_read_error":
            return f"(failed to read trajectory: {ev.get('message')})"

        item = ev.get("item")
        if isinstance(item, dict):
            _render_item(item, lines, obs_trunc, args_trunc)
            continue

        payload = ev.get("payload")
        if isinstance(payload, dict):
            _render_rollout_payload(payload, lines, obs_trunc, args_trunc)
            continue

        if et == "turn.completed":
            usage = ev.get("usage")
            if isinstance(usage, dict):
                lines.append(
                    "[HARNESS] turn completed | tokens in={i} cached={c} out={o} "
                    "reasoning={r}".format(
                        i=usage.get("input_tokens"),
                        c=usage.get("cached_input_tokens"),
                        o=usage.get("output_tokens"),
                        r=usage.get("reasoning_output_tokens"),
                    )
                )
            continue

        if et in ("turn.failed", "error") or isinstance(ev.get("error"), (dict, str)):
            msg = text_of(ev.get("error")) or text_of(ev) or json.dumps(ev)[:300]
            lines.append(f"[ERROR] {clip_text(msg, 1000)}")
            continue

    rendered = "\n".join(lines).strip()
    if not rendered:
        return "(no parseable events in trajectory)"
    if len(rendered) > max_chars:
        dropped = len(rendered) - max_chars
        rendered = rendered[:max_chars] + "\n" + _TRUNC_FMT.format(n=dropped)
    return rendered


class CodexSubstrate:
    """Codex substrate behind the unified Square `Substrate` interface."""

    name = "codex"

    def surface(self) -> SurfaceSpec:
        return CODEX_SURFACE

    def default_tree(self) -> Tree:
        return {"AGENTS.md": "# Repository Guidelines & Agent Instructions\n"}

    def read_workspace_tree(self, repo_root: Path) -> Tree:
        return read_clean_workspace_tree(CODEX_SURFACE, Path(repo_root), self.default_tree())

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
        events = parse_items(p)
        turns: list[NormalizedTurn] = []
        task_prompt = ""
        turn_idx = 0

        for ev in events:
            item = ev.get("item") if isinstance(ev.get("item"), dict) else ev.get("payload")
            if not isinstance(item, dict):
                continue
            itype = item.get("type", "")
            if itype in ("user_message", "message") and item.get("role", "user") == "user":
                txt = text_of(item)
                if txt.strip() and not txt.lstrip().startswith(_AGENTS_MD_TITLE):
                    if not task_prompt:
                        task_prompt = txt.strip()
                    turns.append(NormalizedTurn(turn_index=turn_idx, role="user", text=txt))
                    turn_idx += 1
            elif itype == "command_execution":
                cmd = str(item.get("command") or "")
                exit_code = int(item["exit_code"]) if item.get("exit_code") is not None else None
                failed = item.get("status") == "failed" or exit_code not in (None, 0)
                obs = str(item.get("aggregated_output") or "")
                turns.append(
                    NormalizedTurn(
                        turn_index=turn_idx,
                        role="assistant",
                        tool_calls=[
                            ToolCallRecord(
                                tool_name="shell",
                                command_or_target=cmd,
                                output=obs,
                                exit_code=exit_code,
                                is_error=failed,
                            )
                        ],
                    )
                )
                turn_idx += 1
            elif itype in ("agent_message", "reasoning"):
                txt = text_of(item)
                turns.append(
                    NormalizedTurn(
                        turn_index=turn_idx,
                        role="assistant",
                        text=(txt if itype == "agent_message" else ""),
                        reasoning=(txt if itype == "reasoning" else ""),
                    )
                )
                turn_idx += 1

        raw_md = render_events(p, obs_trunc=obs_trunc, max_chars=max_chars)
        return SessionTrace(
            session_id=sid,
            agent_kind="codex",
            domain=domain,
            workspace_root=workspace_root,
            task_prompt=task_prompt,
            turns=turns,
            raw_trajectory_md=raw_md,
        )

    def materialise_lease(self, repo_root: Path, lease: Lease) -> list[Path]:
        return apply_lease_to_workspace(CODEX_SURFACE, Path(repo_root), lease)

    def revert_lease(
        self, repo_root: Path, lease_id: str, lease: Lease | None = None
    ) -> list[Path]:
        return revert_lease_from_workspace(CODEX_SURFACE, Path(repo_root), lease_id, lease)
