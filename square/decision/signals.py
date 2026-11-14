"""Universal Harness² signal taxonomy and question builders for `gemini-decision-1`.

Signals are strictly derived from the Harness² `INV` (execution mechanics) and `DOM`
(practitioner/workspace knowledge) dimensions and the c1..c8 component archetypes,
avoiding task-specific or session-overfitted rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

DimensionKind = Literal["INV", "DOM"]


@dataclass(frozen=True)
class SignalSpec:
    """One universal boolean (`noul`) signal evaluated on each turn window."""

    key: str
    title: str
    dimension: DimensionKind
    target_components: tuple[str, ...]
    question_template: str

    def format_question(self, window_id: str, turn_span: str) -> dict[str, Any]:
        return {
            "type": "noul",
            "instructions": self.question_template.format(
                window_id=window_id,
                turn_span=turn_span,
            ),
        }


UNIVERSAL_SIGNALS: tuple[SignalSpec, ...] = (
    # --- INV Dimension: How the agent works (procedure, tools, loops, delegation) ---
    SignalSpec(
        key="tool_env_friction",
        title="Tool / Environment Friction",
        dimension="INV",
        target_components=("c4_tool_guidance", "c6_workflow_skill"),
        question_template=(
            "In WINDOW {window_id} ({turn_span}), did the agent waste turns on tool errors, "
            "permission or sandbox blocks, wrong command flags, or misinterpreting how the "
            "runtime environment behaves (such as background task lifecycle, daemon sockets, "
            "or tool schemas)? Do not count isolated `edit_file` target-string-not-found "
            "errors unless `edit_file` fails repeatedly in a multi-turn loop on the same file."
        ),
    ),
    SignalSpec(
        key="automatable_manual_work",
        title="Automatable Manual / Repetitive Work",
        dimension="INV",
        target_components=("c7_script", "c6_workflow_skill"),
        question_template=(
            "In WINDOW {window_id} ({turn_span}), did the agent perform a multi-step, "
            "deterministic extraction, archive/binary inspection, calculation, or transformation "
            "across multiple tool calls (even if it eventually succeeded) that a reusable "
            "helper script (`scripts/<name>.py`) could execute in one step?"
        ),
    ),
    SignalSpec(
        key="context_bloat_investigation",
        title="Large-Input / Small-Answer Context Bloat",
        dimension="INV",
        target_components=("c5_subagent",),
        question_template=(
            "In WINDOW {window_id} ({turn_span}), did the agent read large volumes of raw files, "
            "logs, or search outputs into the main conversation context just to extract a small, "
            "bounded answer that would be better delegated to an isolated subagent? "
            "Do not count platform context-compaction recovery reads of `.system_generated/logs/transcript`."
        ),
    ),
    SignalSpec(
        key="skipped_invariant",
        title="Skipped Invariant / Unverified Deliverable",
        dimension="INV",
        target_components=("c8_hook", "c2_guardrails"),
        question_template=(
            "In WINDOW {window_id} ({turn_span}), did the agent ignore an explicit instruction "
            "already present in the harness/prompt, or claim completion after modifying code/artifacts "
            "without verifying that the deliverable actually works?"
        ),
    ),
    # --- DOM Dimension: What a practitioner in this workspace knows ---
    SignalSpec(
        key="expensive_workspace_discovery",
        title="Expensive Workspace Fact Discovery",
        dimension="DOM",
        target_components=("c3_workspace_memory", "c6_domain_skill"),
        question_template=(
            "In WINDOW {window_id} ({turn_span}), did the agent spend multiple turns hunting "
            "through the repository or running repeated dead-end searches to discover non-obvious "
            "durable workspace or dependency facts (such as where key classes/configs live, "
            "resolved library APIs, build settings, or data schemas) that were not documented upfront?"
        ),
    ),
    SignalSpec(
        key="intent_or_domain_divergence",
        title="User Rework or Domain / Analytic Mistake",
        dimension="DOM",
        target_components=("c6_domain_skill", "c3_workspace_memory", "c1_spec_elicitation"),
        question_template=(
            "In WINDOW {window_id} ({turn_span}), did the user have to correct, reject, or "
            "nudge the agent to redo earlier work, OR did the agent make an invalid domain "
            "assumption, unit/math miscalculation, or unsupported technical attribution?"
        ),
    ),
)

SIGNAL_BY_KEY: dict[str, SignalSpec] = {s.key: s for s in UNIVERSAL_SIGNALS}

# --- Session-Wide Abstract Root-Cause Signals (Macro Level) ---
MACRO_SIGNALS: tuple[SignalSpec, ...] = (
    SignalSpec(
        key="macro_iterative_rework_loop",
        title="Multi-Turn Rework from Missing Upfront Alignment",
        dimension="INV",
        target_components=("c1_spec_elicitation", "c6_workflow_skill"),
        question_template=(
            "Looking across the ENTIRE SESSION (`# FULL SESSION EXECUTIVE DIGEST`), did the agent "
            "go through multiple build-review-rewrite cycles on UI, UX, ranking, or feature behavior "
            "because success criteria or design expectations were discovered by trial-and-error after "
            "coding rather than aligned with the user upfront?"
        ),
    ),
    SignalSpec(
        key="macro_unverified_claims_or_defaults",
        title="Unverified Technical Claims or Hardcoded Defaults",
        dimension="INV",
        target_components=("c2_guardrails", "c6_domain_skill"),
        question_template=(
            "Looking across the ENTIRE SESSION (`# FULL SESSION EXECUTIVE DIGEST`), did the agent "
            "state plausible-sounding technical limits, library behaviors, or design-system values "
            "from assumption/priors (or hardcode magic literals instead of using defined theme/config "
            "tokens) without inspecting the source of truth first, which the user or runtime later disproved?"
        ),
    ),
    SignalSpec(
        key="macro_recurring_manual_toil",
        title="Recurring Multi-Step Manual Inspection / Toil",
        dimension="INV",
        target_components=("c7_script", "c6_workflow_skill"),
        question_template=(
            "Looking across the ENTIRE SESSION (`# FULL SESSION EXECUTIVE DIGEST`), did the agent "
            "repeat the same class of multi-step manual shell, binary/archive, or log inspection "
            "at multiple separate points in the session (proving it is a recurring workflow worth "
            "scripting rather than an isolated one-off check)?"
        ),
    ),
    SignalSpec(
        key="macro_missing_domain_mental_model",
        title="Durable Domain / Subsystem Mental Model Gap",
        dimension="DOM",
        target_components=("c6_domain_skill", "c3_workspace_memory"),
        question_template=(
            "Looking across the ENTIRE SESSION (`# FULL SESSION EXECUTIVE DIGEST`), did the agent "
            "struggle with non-obvious framework, library, design-system, or architectural invariants "
            "that had to be pieced together across multiple turns and will genuinely recur in future "
            "tasks in this repository?"
        ),
    ),
    SignalSpec(
        key="macro_verification_blind_spot",
        title="User-Caught Runtime / Verification Blind Spot",
        dimension="INV",
        target_components=("c8_hook", "c7_script", "c2_guardrails"),
        question_template=(
            "Looking across the ENTIRE SESSION (`# FULL SESSION EXECUTIVE DIGEST`), did the agent "
            "repeatedly rely on the user to manually test, spot regressions, or paste runtime logs/errors "
            "because the agent lacked or skipped an automated verification check before handing off?"
        ),
    ),
)

MACRO_SIGNAL_BY_KEY: dict[str, SignalSpec] = {s.key: s for s in MACRO_SIGNALS}

MACRO_ROOT_CAUSE_CRITERIA: dict[str, str] = {
    "spec_alignment_c1": (
        "Missing upfront specification or UX/acceptance alignment before writing code "
        "(caused multiple build-and-rewrite cycles)."
    ),
    "source_of_truth_verification_c2": (
        "Guessing technical limits or hardcoding magic defaults from priors instead of "
        "checking the binary, theme, or codebase source of truth first."
    ),
    "reusable_automation_script_c7": (
        "Recurring multi-step manual shell, archive/JAR, or log inspections that should be "
        "automated into a reusable helper script or workflow skill."
    ),
    "domain_subsystem_model_c6": (
        "Missing practitioner mental model of a core framework, library, or design system "
        "used in this repository."
    ),
    "runtime_verification_loop_c8": (
        "Handing off unverified deliverables where the user had to catch runtime or visual regressions."
    ),
    "none_routine_session": (
        "Normal productive session with no systemic harness root cause."
    ),
}

TARGET_COMPONENT_TO_LEVER: dict[str, str] = {
    "c7_script": "script_c7",
    "c6_workflow_skill": "workflow_skill_c6",
    "c4_tool_guidance": "workflow_skill_c6",
    "c1_spec_elicitation": "workflow_skill_c6",
    "c6_domain_skill": "domain_skill_c6",
    "c3_workspace_memory": "workspace_memory_c3",
    "c5_subagent": "subagent_c5",
    "c8_hook": "hook_c8",
    "c2_guardrails": "hook_c8",
}

LEVER_CRITERIA: dict[str, str] = {
    "script_c7": (
        "A deterministic Python helper script (`scripts/<name>.py`) to automate repeated "
        "inspection, parsing, calculation, or verification."
    ),
    "workflow_skill_c6": (
        "An on-demand procedural skill (`SKILL.md`) for handling a recurring tool, build, "
        "environment recovery, or spec-elicitation workflow."
    ),
    "domain_skill_c6": (
        "An on-demand domain skill (`SKILL.md`) encoding practitioner rules, artifact "
        "contracts, or calculation/reconciliation checks."
    ),
    "workspace_memory_c3": (
        "Concise verified workspace facts in always-on memory (`GEMINI.md` / `AGENTS.md`) "
        "recording non-obvious repository paths, schemas, or configuration."
    ),
    "subagent_c5": (
        "A delegated subagent (`sub_agents/<name>/AGENT.md`) to isolate a noisy, "
        "large-input investigation that returns a compact answer."
    ),
    "hook_c8": (
        "A deterministic tool-loop hook (`hooks.json` / `plugin`) to enforce a rule "
        "or verification check that prose instructions failed to guarantee."
    ),
}

INV_LEVERS: frozenset[str] = frozenset(
    {"script_c7", "workflow_skill_c6", "subagent_c5", "hook_c8"}
)
DOM_LEVERS: frozenset[str] = frozenset(
    {"domain_skill_c6", "workspace_memory_c3"}
)


def build_window_questions(
    window_id: str,
    turn_span: str,
    signals: tuple[SignalSpec, ...] = UNIVERSAL_SIGNALS,
) -> dict[str, dict[str, Any]]:
    """Build the `gemini-decision-1` question dictionary for a single turn window."""
    questions: dict[str, dict[str, Any]] = {}
    for sig in signals:
        q_key = f"{window_id}_{sig.key}"
        questions[q_key] = sig.format_question(window_id, turn_span)

    questions[f"{window_id}_already_covered"] = {
        "type": "noul",
        "instructions": (
            f"Is the friction or knowledge needed in WINDOW {window_id} ({turn_span}) "
            f"ALREADY clearly and adequately covered by the existing `# CURRENT HARNESS SUMMARY`?"
        ),
    }
    questions[f"{window_id}_best_lever"] = {
        "type": "choice",
        "instructions": (
            f"If Square were to adapt the agent harness based on WINDOW {window_id} ({turn_span}), "
            f"which Harness² component lever is the single most appropriate intervention?"
        ),
        "criteria": dict(LEVER_CRITERIA),
    }
    return questions


def build_macro_questions(
    macro_signals: tuple[SignalSpec, ...] = MACRO_SIGNALS,
) -> dict[str, dict[str, Any]]:
    """Build session-wide abstract root-cause questions for `gemini-decision-1`."""
    questions: dict[str, dict[str, Any]] = {}
    for sig in macro_signals:
        questions[sig.key] = {
            "type": "noul",
            "instructions": sig.question_template,
        }
    questions["macro_dominant_root_cause"] = {
        "type": "choice",
        "instructions": (
            "Stepping back from individual turns and looking across the ENTIRE SESSION "
            "(`# FULL SESSION EXECUTIVE DIGEST`), what is the single highest-leverage "
            "abstract root cause that explains where turns or quality were lost?"
        ),
        "criteria": dict(MACRO_ROOT_CAUSE_CRITERIA),
    }
    return questions


def build_session_scan_questions(
    slot_id: str,
    session_label: str,
    macro_signals: tuple[SignalSpec, ...] = MACRO_SIGNALS,
) -> dict[str, dict[str, Any]]:
    """Build multi-session discovery/scan questions for a single candidate session `slot_id`."""
    questions: dict[str, dict[str, Any]] = {
        f"{slot_id}_worth_extracting": {
            "type": "noul",
            "instructions": (
                f"Looking at CANDIDATE SESSION {slot_id} ({session_label}), is this session "
                f"a high-value candidate for testing Square's harness proposer — i.e., does it "
                f"contain substantive multi-turn user rework/alignment friction, repeated manual "
                f"shell/inspection toil, or non-obvious domain/architectural discoveries from "
                f"which generalizable skills, rules, or helper scripts should be extracted "
                f"(rather than a routine, smooth, or one-off session)?"
            ),
        }
    }
    for sig in macro_signals:
        scoped_q = sig.question_template.replace(
            "`# FULL SESSION EXECUTIVE DIGEST`",
            f"CANDIDATE SESSION {slot_id} ({session_label})",
        )
        questions[f"{slot_id}_{sig.key}"] = {
            "type": "noul",
            "instructions": f"In CANDIDATE SESSION {slot_id} ({session_label}): {scoped_q}",
        }
    questions[f"{slot_id}_dominant_root_cause"] = {
        "type": "choice",
        "instructions": (
            f"In CANDIDATE SESSION {slot_id} ({session_label}), what is the single "
            f"highest-leverage abstract root cause that explains where turns or quality "
            f"were lost (or `none_routine_session` if smooth/routine)?"
        ),
        "criteria": dict(MACRO_ROOT_CAUSE_CRITERIA),
    }
    return questions
