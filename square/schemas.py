"""Core data models and schemas for Square (`.square`).

Defines normalized trajectory representations (`ToolCallRecord`, `FileMutation`,
`NormalizedTurn`, `SessionTrace`), deterministic pre-slicing outputs
(`TrajectorySlice`), and asynchronous leasing / activation probing models
(`ActivationTrigger`, `Lease`, `ActivationResult`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ThrashType = Literal[
    "MANUAL_REVIEW",
    "MECHANICAL_THRASH",
    "SEMANTIC_REVERT_INTRA",
    "SEMANTIC_REVERT_GIT",
]

Dimension = Literal["INV", "DOM"]

LeaseTier = Literal["TIER_1", "TIER_2"]

LeaseStatus = Literal[
    "AWAITING_TRIAL",
    "ACTIVE",
    "STAGED_TIER_2",
    "COMPOSED",
    "REVERTED",
    "EXPIRED",
]

ProbeOutcome = Literal[
    "ACTIVATED_AND_INVOKED",
    "IGNORED_BY_AGENT",
    "UNRELATED_SESSION",
    "MOUNTED_ALWAYS_ON",
]


@dataclass
class ToolCallRecord:
    """Normalized record of a single tool invocation within an assistant turn."""

    tool_name: str
    command_or_target: str
    arguments: dict[str, Any] = field(default_factory=dict)
    output: str = ""
    exit_code: int | None = None
    is_error: bool = False


@dataclass
class FileMutation:
    """Normalized record of a file write/edit within an assistant turn."""

    path: str
    before_content: str | None = None
    after_content: str = ""
    added_lines: list[str] = field(default_factory=list)
    removed_lines: list[str] = field(default_factory=list)


@dataclass
class NormalizedTurn:
    """One turn in a coding agent session."""

    turn_index: int
    role: Literal["user", "assistant", "system"]
    text: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    file_mutations: list[FileMutation] = field(default_factory=list)
    timestamp: str = ""

    @property
    def has_errors(self) -> bool:
        return any(tc.is_error or tc.exit_code not in (None, 0) for tc in self.tool_calls)

    @property
    def has_green_validation(self) -> bool:
        """True if this turn ran a build/test/compile command that exited 0."""
        for tc in self.tool_calls:
            if tc.exit_code == 0 and not tc.is_error:
                cmd = tc.command_or_target.lower()
                if any(
                    kw in cmd
                    for kw in (
                        "pytest",
                        "unittest",
                        "gradle",
                        "gradlew",
                        "cargo test",
                        "cargo check",
                        "npm test",
                        "npm run build",
                        "pnpm test",
                        "pnpm build",
                        "tsc",
                        "py_compile",
                        "go test",
                        "mvn test",
                    )
                ):
                    return True
        return False


@dataclass
class SessionTrace:
    """Complete normalized session transcript from an agent substrate."""

    session_id: str
    agent_kind: str = "antigravity"  # "antigravity" | "claude" | "codex" | "opencode"
    domain: str = "default"
    workspace_root: str = ""
    task_prompt: str = ""
    turns: list[NormalizedTurn] = field(default_factory=list)
    final_files: dict[str, str] = field(default_factory=dict)
    raw_trajectory_md: str = ""

    @property
    def touched_paths(self) -> list[str]:
        paths: set[str] = set()
        for t in self.turns:
            for fm in t.file_mutations:
                paths.add(fm.path.replace("\\", "/"))
            for tc in t.tool_calls:
                for key in ("path", "file_path", "Path", "target_file"):
                    val = tc.arguments.get(key)
                    if isinstance(val, str) and val.strip():
                        paths.add(val.replace("\\", "/"))
        return sorted(paths)

    @property
    def executed_commands(self) -> list[str]:
        cmds: list[str] = []
        for t in self.turns:
            for tc in t.tool_calls:
                if tc.command_or_target:
                    cmds.append(tc.command_or_target)
        return cmds


@dataclass
class TrajectorySlice:
    """A friction slice extracted deterministically from a SessionTrace ($T_{1..Y-1}, T_Y, T_{Y+1}$)."""

    slice_id: str
    session_id: str
    domain: str
    thrash_type: ThrashType
    t_start: int
    t_y: int
    t_y1: int
    turn_count: int
    error_count: int
    survival_ratio: float | None
    summary: str = ""
    touched_files: list[str] = field(default_factory=list)
    at_t_y_diff: str = ""
    survival_t_y1_diff: str = ""
    user_nudge_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActivationTrigger:
    """Machine-checkable situation cues emitted alongside a candidate harness edit."""

    path_globs: list[str] = field(default_factory=list)
    command_regex: str = ""
    cue_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ActivationTrigger:
        if not isinstance(data, dict):
            return cls()
        return cls(
            path_globs=[str(x) for x in (data.get("path_globs") or []) if str(x).strip()],
            command_regex=str(data.get("command_regex") or "").strip(),
            cue_keywords=[str(x) for x in (data.get("cue_keywords") or []) if str(x).strip()],
        )


@dataclass
class Lease:
    """An active or staged candidate edit leased into the live workspace for probing ($A_1, A_2$)."""

    lease_id: str
    case_id: str
    domain: str
    dimension: Dimension
    tier: LeaseTier
    status: LeaseStatus
    component_paths: list[str]
    trigger: ActivationTrigger
    substrate_name: str = "antigravity"
    candidate_tree: dict[str, str] = field(default_factory=dict)
    base_tree: dict[str, str] = field(default_factory=dict)
    proposer_notes: str = ""
    activations_completed: int = 0
    activations_target: int = 1
    probe_sessions: list[str] = field(default_factory=list)
    probe_outcomes: list[str] = field(default_factory=list)
    unrelated_sessions_seen: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["trigger"] = self.trigger.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Lease:
        trig = ActivationTrigger.from_dict(data.get("trigger"))
        return cls(
            lease_id=str(data["lease_id"]),
            case_id=str(data["case_id"]),
            domain=str(data.get("domain", "default")),
            dimension=data["dimension"],
            tier=data.get("tier", "TIER_1"),
            status=data.get("status", "ACTIVE"),
            component_paths=list(data.get("component_paths") or []),
            trigger=trig,
            substrate_name=str(data.get("substrate_name", "antigravity")),
            candidate_tree=dict(data.get("candidate_tree") or {}),
            base_tree=dict(data.get("base_tree") or {}),
            proposer_notes=str(data.get("proposer_notes") or ""),
            activations_completed=int(data.get("activations_completed", 0)),
            activations_target=int(data.get("activations_target", 1)),
            probe_sessions=list(data.get("probe_sessions") or []),
            probe_outcomes=list(data.get("probe_outcomes") or []),
            unrelated_sessions_seen=int(data.get("unrelated_sessions_seen", 0)),
        )


@dataclass
class ActivationResult:
    """Two-bit activation evaluation for a Lease against a new SessionTrace."""

    lease_id: str
    situation_matched: bool
    component_invoked: bool
    outcome: ProbeOutcome
    matched_reasons: list[str] = field(default_factory=list)
    invoked_reasons: list[str] = field(default_factory=list)
