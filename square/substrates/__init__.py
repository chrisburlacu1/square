"""Per-agent Substrate registry (`CODEX_SURFACE`, `OPENCODE_SURFACE`, `CLAUDE_SURFACE`, `AGY_SURFACE`)
and automatic transcript substrate detection.
"""

from __future__ import annotations

from pathlib import Path

from ..schemas import SessionTrace
from .antigravity import (
    AGY_SURFACE,
    AntigravitySubstrate,
    default_agy_brain_dir,
    default_agy_global_config_dir,
    default_global_library_root,
)
from .base import Substrate, default_square_home, parse_jsonl_lines, project_square_dir
from .claude import CLAUDE_SURFACE, ClaudeSubstrate
from .codex import CODEX_SURFACE, CodexSubstrate
from .opencode import OPENCODE_SURFACE, OpencodeSubstrate

SUBSTRATE_MAP: dict[str, Substrate] = {
    "codex": CodexSubstrate(),
    "opencode": OpencodeSubstrate(),
    "claude": ClaudeSubstrate(),
    "antigravity": AntigravitySubstrate(),
}

SURFACE_MAP = {
    "codex": CODEX_SURFACE,
    "opencode": OPENCODE_SURFACE,
    "claude": CLAUDE_SURFACE,
    "antigravity": AGY_SURFACE,
}


def get_substrate(name: str) -> Substrate:
    norm = name.strip().lower()
    if norm in ("claude_code", "claude-code"):
        norm = "claude"
    elif norm in ("agy", "gemini"):
        norm = "antigravity"
    elif norm in ("cx", "codex_cli"):
        norm = "codex"
    elif norm == "oc":
        norm = "opencode"
    if norm not in SUBSTRATE_MAP:
        raise ValueError(f"Unknown substrate {name!r}; expected one of {sorted(SUBSTRATE_MAP)}")
    return SUBSTRATE_MAP[norm]


def detect_substrate_from_jsonl(path: Path | str, default: str = "antigravity") -> Substrate:
    """Inspect the first lines of a JSONL transcript to select its native `Substrate`."""
    events = parse_jsonl_lines(path)
    for ev in events[:15]:
        if "step_index" in ev or ev.get("type") in ("USER_INPUT", "PLANNER_RESPONSE"):
            return SUBSTRATE_MAP["antigravity"]
        if isinstance(ev.get("message"), dict) and ev.get("type") in ("user", "assistant"):
            return SUBSTRATE_MAP["claude"]
        if "item" in ev or "payload" in ev or str(ev.get("type", "")).startswith("turn."):
            return SUBSTRATE_MAP["codex"]
        if "part" in ev:
            return SUBSTRATE_MAP["opencode"]
    return get_substrate(default)


def parse_session_trace(
    path: Path | str,
    *,
    substrate: str | Substrate | None = None,
    session_id: str | None = None,
    domain: str = "default",
    workspace_root: str = "",
    obs_trunc: int = 50_000,
) -> tuple[Substrate, SessionTrace]:
    """Detect or resolve the `Substrate` for `path` and parse its `SessionTrace`."""
    sub = (
        substrate
        if isinstance(substrate, Substrate)
        else (get_substrate(substrate) if substrate else detect_substrate_from_jsonl(path))
    )
    trace = sub.read_trajectory(
        path,
        session_id=session_id,
        domain=domain,
        workspace_root=workspace_root,
        obs_trunc=obs_trunc,
    )
    return sub, trace


__all__ = [
    "Substrate",
    "CodexSubstrate",
    "OpencodeSubstrate",
    "ClaudeSubstrate",
    "AntigravitySubstrate",
    "CODEX_SURFACE",
    "OPENCODE_SURFACE",
    "CLAUDE_SURFACE",
    "AGY_SURFACE",
    "SUBSTRATE_MAP",
    "SURFACE_MAP",
    "get_substrate",
    "detect_substrate_from_jsonl",
    "parse_session_trace",
    "default_agy_brain_dir",
    "default_agy_global_config_dir",
    "default_global_library_root",
    "default_square_home",
    "project_square_dir",
]
