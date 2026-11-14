"""Session triage evaluator, episode merger, and Markdown report renderer for `gemini-decision-1`."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..schemas import Dimension, SessionTrace
from ..tree import SurfaceSpec, Tree
from .client import (
    DEFAULT_DECISION_MODEL,
    ChoiceAnswer,
    DecisionClient,
    GeminiDecisionClient,
    NoulAnswer,
)
from .signals import (
    DOM_LEVERS,
    INV_LEVERS,
    MACRO_ROOT_CAUSE_CRITERIA,
    MACRO_SIGNALS,
    SIGNAL_BY_KEY,
    TARGET_COMPONENT_TO_LEVER,
    UNIVERSAL_SIGNALS,
    SignalSpec,
    build_macro_questions,
    build_session_scan_questions,
    build_window_questions,
)
from .windowing import (
    TurnWindow,
    batch_windows_for_input,
    format_executive_digest,
    format_shared_input,
    slice_into_windows,
)


@dataclass(frozen=True)
class SignalScore:
    """Evaluated probability and confidence for one universal signal on one window."""

    key: str
    title: str
    dimension: str
    probability: float
    confidence: float
    triggered: bool


@dataclass
class WindowEvaluation:
    """Decision-model evaluation of a single turn window."""

    window_id: str
    t_start: int
    t_end: int
    preview: str
    signals: list[SignalScore]
    already_covered: NoulAnswer
    best_lever: ChoiceAnswer
    triggered: bool
    recommended_dimensions: list[Dimension] = field(default_factory=list)
    turn_digest: list[str] = field(default_factory=list)

    @property
    def top_signal(self) -> SignalScore | None:
        if not self.signals:
            return None
        return max(self.signals, key=lambda s: s.probability)

    @property
    def aligned_lever(self) -> tuple[str, float]:
        """Return the highest-probability lever aligned with the window's triggered signal targets."""
        if not self.recommended_dimensions or not self.best_lever.probabilities:
            p = self.best_lever.probabilities.get(self.best_lever.choice, 0.0)
            return self.best_lever.choice, p

        dim_allowed: set[str] = set()
        if "INV" in self.recommended_dimensions:
            dim_allowed |= set(INV_LEVERS)
        if "DOM" in self.recommended_dimensions:
            dim_allowed |= set(DOM_LEVERS)

        sig_allowed: set[str] = set()
        hot_sigs = [s for s in self.signals if s.triggered]
        for s in hot_sigs:
            spec = SIGNAL_BY_KEY.get(s.key)
            if spec is not None:
                for comp in spec.target_components:
                    mapped = TARGET_COMPONENT_TO_LEVER.get(comp)
                    if mapped:
                        sig_allowed.add(mapped)

        allowed = (sig_allowed & dim_allowed) or dim_allowed or sig_allowed
        if not allowed:
            p = self.best_lever.probabilities.get(self.best_lever.choice, 0.0)
            return self.best_lever.choice, p

        candidates = [
            (k, float(v))
            for k, v in self.best_lever.probabilities.items()
            if k in allowed
        ]
        if not candidates:
            p = self.best_lever.probabilities.get(self.best_lever.choice, 0.0)
            return self.best_lever.choice, p
        return max(candidates, key=lambda item: item[1])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MergedEpisode:
    """Contiguous or overlapping triggered windows merged into one cohesive episode."""

    episode_id: str
    window_ids: list[str]
    t_start: int
    t_end: int
    recommended_dimensions: list[Dimension]
    peak_signals: list[SignalScore]
    primary_lever: str
    primary_lever_prob: float
    turn_digest: list[str] = field(default_factory=list)


@dataclass
class TriageReport:
    """Complete `gemini-decision-1` triage result for a coding session."""

    session_id: str
    substrate_name: str
    model: str
    wall_ms: float
    input_chars: int
    question_count: int
    signal_threshold: float
    already_covered_max: float
    windows: list[WindowEvaluation] = field(default_factory=list)
    macro_signals: list[SignalScore] = field(default_factory=list)
    macro_dominant_root_cause: ChoiceAnswer | None = None

    @property
    def triggered_windows(self) -> list[WindowEvaluation]:
        return [w for w in self.windows if w.triggered]

    @property
    def triggered_macro_signals(self) -> list[SignalScore]:
        return [m for m in self.macro_signals if m.triggered]

    @property
    def recommended_dimensions(self) -> list[Dimension]:
        dims: list[Dimension] = []
        for w in self.triggered_windows:
            for d in w.recommended_dimensions:
                if d not in dims:
                    dims.append(d)
        for m in self.triggered_macro_signals:
            d_mac: Dimension = "INV" if m.dimension == "INV" else "DOM"
            if d_mac not in dims:
                dims.append(d_mac)
        return dims

    @property
    def should_propose(self) -> bool:
        return bool((self.triggered_windows or self.triggered_macro_signals) and self.recommended_dimensions)

    def merged_episodes(self) -> list[MergedEpisode]:
        """Merge overlapping or adjacent triggered windows that share at least one triggered signal."""
        hot = self.triggered_windows
        if not hot:
            return []
        groups: list[list[WindowEvaluation]] = []
        for w in hot:
            w_keys = {s.key for s in w.signals if s.triggered}
            prev_keys = (
                {s.key for s in groups[-1][-1].signals if s.triggered}
                if groups
                else set()
            )
            if (
                groups
                and w.t_start <= groups[-1][-1].t_end + 2
                and (w_keys & prev_keys)
            ):
                groups[-1].append(w)
            else:
                groups.append([w])

        episodes: list[MergedEpisode] = []
        for idx, grp in enumerate(groups, 1):
            w_ids = [w.window_id for w in grp]
            t_start = grp[0].t_start
            t_end = max(w.t_end for w in grp)
            dims: list[Dimension] = []
            for w in grp:
                for d in w.recommended_dimensions:
                    if d not in dims:
                        dims.append(d)

            best_by_key: dict[str, SignalScore] = {}
            for w in grp:
                for s in w.signals:
                    if s.triggered:
                        prev = best_by_key.get(s.key)
                        if prev is None or s.probability > prev.probability:
                            best_by_key[s.key] = s
            peak_sigs = sorted(best_by_key.values(), key=lambda s: s.probability, reverse=True)

            # Pick the aligned lever from the window with the highest peak signal
            lead_w = max(
                grp,
                key=lambda w: max((s.probability for s in w.signals if s.triggered), default=0.0),
            )
            lever_name, lever_prob = lead_w.aligned_lever

            seen_digest: list[str] = []
            for w in grp:
                for ln in w.turn_digest:
                    if ln not in seen_digest:
                        seen_digest.append(ln)

            episodes.append(
                MergedEpisode(
                    episode_id=f"ep{idx}",
                    window_ids=w_ids,
                    t_start=t_start,
                    t_end=t_end,
                    recommended_dimensions=dims,
                    peak_signals=peak_sigs,
                    primary_lever=lever_name,
                    primary_lever_prob=lever_prob,
                    turn_digest=seen_digest[:24],
                )
            )
        return episodes

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["should_propose"] = self.should_propose
        d["recommended_dimensions"] = self.recommended_dimensions
        d["merged_episodes"] = [asdict(ep) for ep in self.merged_episodes()]
        return d


def _determine_window_routing(
    signals: list[SignalScore],
    already_covered: NoulAnswer,
    best_lever: ChoiceAnswer,
    *,
    signal_threshold: float,
    already_covered_max: float,
) -> tuple[bool, list[Dimension]]:
    """Decide whether a window crosses the threshold and which proposer dimensions to wake.

    Routing (`INV` vs `DOM`) is determined strictly from which `noul` signals crossed
    `signal_threshold` so a split `best_lever` probability distribution cannot wake an
    unrelated dimension.
    """
    hot_signals = [s for s in signals if s.probability >= signal_threshold]
    if not hot_signals:
        return False, []
    if already_covered.probability >= already_covered_max:
        return False, []

    dims: list[Dimension] = []
    for s in hot_signals:
        dim: Dimension = "INV" if s.dimension == "INV" else "DOM"
        if dim not in dims:
            dims.append(dim)

    return bool(dims), dims


@dataclass
class SessionTriageService:
    """Runs `gemini-decision-1` across a session's turn windows to detect and route opportunities."""

    client: DecisionClient = field(default_factory=GeminiDecisionClient)
    model: str = DEFAULT_DECISION_MODEL
    window_size: int = 8
    stride: int = 6
    signal_threshold: float = 0.65
    already_covered_max: float = 0.75
    signals: tuple[SignalSpec, ...] = UNIVERSAL_SIGNALS
    macro_signals: tuple[SignalSpec, ...] = MACRO_SIGNALS

    def evaluate(
        self,
        trace: SessionTrace,
        *,
        surface: SurfaceSpec,
        harness: Tree,
        unmanaged_skills: list[dict[str, str]] | None = None,
    ) -> TriageReport:
        windows: list[TurnWindow] = slice_into_windows(
            trace,
            window_size=self.window_size,
            stride=self.stride,
        )
        if not windows:
            return TriageReport(
                session_id=trace.session_id,
                substrate_name=surface.name,
                model=self.model,
                wall_ms=0.0,
                input_chars=0,
                question_count=0,
                signal_threshold=self.signal_threshold,
                already_covered_max=self.already_covered_max,
                windows=[],
            )

        batches = batch_windows_for_input(windows)
        combined_noul: dict[str, NoulAnswer] = {}
        combined_choice: dict[str, ChoiceAnswer] = {}
        total_wall_ms = 0.0
        total_input_chars = 0
        total_questions = 0
        used_model = self.model

        for batch_idx, batch in enumerate(batches):
            shared_input = format_shared_input(
                trace,
                batch,
                surface=surface,
                harness=harness,
                all_windows=windows if batch_idx == 0 else None,
                unmanaged_skills=unmanaged_skills or (),
            )
            batch_questions: dict[str, dict[str, Any]] = {}
            if batch_idx == 0 and self.macro_signals:
                batch_questions.update(build_macro_questions(self.macro_signals))
            for w in batch:
                batch_questions.update(
                    build_window_questions(w.window_id, w.turn_span, signals=self.signals)
                )

            resp = self.client.decide(
                shared_input,
                batch_questions,
                model=self.model,
            )
            used_model = resp.model
            total_wall_ms += resp.wall_ms
            total_input_chars += resp.input_chars
            total_questions += resp.question_count
            combined_noul.update(resp.noul_answers)
            combined_choice.update(resp.choice_answers)

        evaluated_macro: list[SignalScore] = []
        for msig in self.macro_signals:
            mans = combined_noul.get(msig.key, NoulAnswer(probability=0.0, confidence=0.0))
            evaluated_macro.append(
                SignalScore(
                    key=msig.key,
                    title=msig.title,
                    dimension=msig.dimension,
                    probability=mans.probability,
                    confidence=mans.confidence,
                    triggered=mans.probability >= self.signal_threshold,
                )
            )
        macro_root_choice = combined_choice.get("macro_dominant_root_cause")

        evaluated_windows: list[WindowEvaluation] = []
        for w in windows:
            sig_scores: list[SignalScore] = []
            for sig in self.signals:
                q_key = f"{w.window_id}_{sig.key}"
                ans = combined_noul.get(q_key, NoulAnswer(probability=0.0, confidence=0.0))
                sig_scores.append(
                    SignalScore(
                        key=sig.key,
                        title=sig.title,
                        dimension=sig.dimension,
                        probability=ans.probability,
                        confidence=ans.confidence,
                        triggered=ans.probability >= self.signal_threshold,
                    )
                )

            cov_ans = combined_noul.get(
                f"{w.window_id}_already_covered",
                NoulAnswer(probability=0.0, confidence=0.0),
            )
            lever_ans = combined_choice.get(
                f"{w.window_id}_best_lever",
                ChoiceAnswer(choice="keep_base", probabilities={}, confidence=0.0),
            )

            triggered, rec_dims = _determine_window_routing(
                sig_scores,
                cov_ans,
                lever_ans,
                signal_threshold=self.signal_threshold,
                already_covered_max=self.already_covered_max,
            )
            evaluated_windows.append(
                WindowEvaluation(
                    window_id=w.window_id,
                    t_start=w.t_start,
                    t_end=w.t_end,
                    preview=w.preview,
                    signals=sig_scores,
                    already_covered=cov_ans,
                    best_lever=lever_ans,
                    triggered=triggered,
                    recommended_dimensions=rec_dims,
                    turn_digest=list(w.turn_digest),
                )
            )

        return TriageReport(
            session_id=trace.session_id,
            substrate_name=surface.name,
            model=used_model,
            wall_ms=round(total_wall_ms, 1),
            input_chars=total_input_chars,
            question_count=total_questions,
            signal_threshold=self.signal_threshold,
            already_covered_max=self.already_covered_max,
            windows=evaluated_windows,
            macro_signals=evaluated_macro,
            macro_dominant_root_cause=macro_root_choice,
        )


def render_triage_markdown(report: TriageReport) -> str:
    """Format a `TriageReport` into a scannable Markdown report for CLI output or `TRIAGE.md`."""
    verdict = (
        f"PROPOSE ({', '.join(report.recommended_dimensions)})"
        if report.should_propose
        else "KEEP_BASE (No proposer call needed)"
    )
    est_cost = (report.input_chars / 4.0) / 1_000_000.0 * 0.10
    episodes = report.merged_episodes()

    lines: list[str] = [
        f"# Square Decision Triage (`{report.session_id}`)",
        "",
        f"- **Verdict**: **{verdict}**",
        f"- **Decision Model**: `{report.model}` | **Latency**: `{report.wall_ms:.0f} ms` | "
        f"**Questions Evaluated**: `{report.question_count}` across `{len(report.windows)}` window(s)",
        f"- **Input Size**: `{report.input_chars:,} chars` (~`${est_cost:.5f}` at $0.10/1M tokens, 0 output tokens)",
        f"- **Thresholds**: `signal >= {report.signal_threshold:.2f}`, `already_covered < {report.already_covered_max:.2f}`",
        "",
    ]

    if report.macro_signals:
        lines.extend(
            [
                "## 1. Macro Session Root-Cause Analysis",
                "",
            ]
        )
        if report.macro_dominant_root_cause and report.macro_dominant_root_cause.choice:
            rc_key = report.macro_dominant_root_cause.choice
            rc_prob = report.macro_dominant_root_cause.probabilities.get(
                rc_key, report.macro_dominant_root_cause.confidence
            )
            rc_desc = MACRO_ROOT_CAUSE_CRITERIA.get(rc_key, "")
            lines.append(
                f"- **Dominant Root Cause**: `{rc_key}` (**P={rc_prob:.2f}**) — {rc_desc}"
            )
            lines.append("")
        lines.extend(
            [
                "| Macro Root-Cause Signal | Dim | Probability | Triggered |",
                "| :--- | :---: | :---: | :---: |",
            ]
        )
        for ms in report.macro_signals:
            p_str = f"**{ms.probability:.2f}**" if ms.triggered else f"{ms.probability:.2f}"
            t_str = f"**YES ({ms.dimension})**" if ms.triggered else "no"
            lines.append(f"| `{ms.key}` — {ms.title} | `{ms.dimension}` | {p_str} | {t_str} |")
        lines.append("")

    lines.extend(
        [
            f"## 2. Highlighted Episodes ({len(episodes)} consolidated from {len(report.triggered_windows)} window(s))",
            "",
        ]
    )

    if not episodes:
        lines.append("_No windows crossed the intervention threshold._")
        lines.append("")
    else:
        for ep in episodes:
            win_str = ", ".join(f"`{wid}`" for wid in ep.window_ids)
            sig_str = ", ".join(
                f"`{s.key}` (**{s.probability:.2f}**, {s.dimension})" for s in ep.peak_signals
            )
            lines.extend(
                [
                    f"### Episode `{ep.episode_id}` — Turns {ep.t_start}..{ep.t_end} ({win_str}) -> Route: `{', '.join(ep.recommended_dimensions)}`",
                    f"- **Peak Signals**: {sig_str}",
                    f"- **Aligned Lever**: `{ep.primary_lever}` (P={ep.primary_lever_prob:.2f})",
                ]
            )
            if ep.turn_digest:
                lines.append("- **Turn Activity Log**:")
                lines.append("```text")
                lines.extend(f"  {ln}" for ln in ep.turn_digest)
                lines.append("```")
            lines.append("")

    lines.extend(
        [
            "## 3. Full Window Scorecard",
            "",
            "| Window | Turns | Tool/Env (INV) | AutoScript (INV) | CtxBloat (INV) | SkipInv (INV) | WsDiscovery (DOM) | Intent/Domain (DOM) | Covered? | Aligned Lever | Triggered |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :---: |",
        ]
    )

    sig_order = [s.key for s in UNIVERSAL_SIGNALS]
    for w in report.windows:
        by_key = {s.key: s for s in w.signals}
        cells: list[str] = []
        for k in sig_order:
            sc = by_key.get(k)
            if sc is None:
                cells.append("-")
            elif sc.triggered:
                cells.append(f"**{sc.probability:.2f}**")
            else:
                cells.append(f"{sc.probability:.2f}")
        lever_name, lever_p = w.aligned_lever
        lever_str = f"`{lever_name}` ({lever_p:.2f})"
        trig_str = f"**YES ({'+'.join(w.recommended_dimensions)})**" if w.triggered else "no"
        lines.append(
            f"| `{w.window_id}` | {w.t_start}..{w.t_end} | "
            + " | ".join(cells)
            + f" | {w.already_covered.probability:.2f} | {lever_str} | {trig_str} |"
        )

    lines.append("")
    return "\n".join(lines)


def format_proposer_brief(
    report: TriageReport,
    dim: Dimension,
    *,
    spotlight_threshold: float | None = None,
) -> str:
    """Format a focused highlight block for `MISSION.md` targeting `dim` ('INV' or 'DOM')."""
    thr = report.signal_threshold if spotlight_threshold is None else spotlight_threshold
    all_eps = report.merged_episodes()
    primary_eps = [ep for ep in all_eps if dim in ep.recommended_dimensions]
    cross_eps = [
        ep
        for ep in all_eps
        if dim not in ep.recommended_dimensions
        and any(s.key == "intent_or_domain_divergence" for s in ep.peak_signals)
    ]
    hot_macros = [m for m in report.macro_signals if m.probability >= thr]
    soft_wins = []
    if spotlight_threshold is not None and not primary_eps:
        for w in report.windows:
            if w.already_covered.probability >= report.already_covered_max:
                continue
            wsigs = [s for s in w.signals if s.dimension == dim and s.probability >= thr]
            if wsigs:
                soft_wins.append((w, sorted(wsigs, key=lambda s: s.probability, reverse=True)))
    if not primary_eps and not hot_macros and not soft_wins:
        return ""

    distinct_levers = sorted({ep.primary_lever for ep in primary_eps if ep.primary_lever})
    lever_summary = ", ".join(f"`{lv}`" for lv in distinct_levers) if distinct_levers else "appropriate lever"

    lines: list[str] = [
        f"# DECISION MODEL TRIAGE HIGHLIGHTS FOR `{dim}` (`{report.model}`)",
        "",
        "These macro signals and turn episodes are **symptom spotlights** surfaced by Square's "
        "decision model — NOT a literal checklist of narrow rules to implement one-by-one. "
        f"Group related episodes into **distinct, orthogonal root-cause clusters** in `{dim}` "
        f"(candidate levers across episodes: {lever_summary}) and propose a generalizable "
        "component for **each** distinct root-cause cluster (for example, addressing both a "
        "macro workflow/alignment gap with a skill AND a repeated mechanical toil pattern with "
        "an executable `scripts/<name>.py` helper, or `KEEP_BASE` if they reflect normal conversation):",
        "",
    ]
    if hot_macros or (
        report.macro_dominant_root_cause and report.macro_dominant_root_cause.choice
    ):
        lines.append("## Session-Wide Abstract Root-Cause Signals")
        if report.macro_dominant_root_cause and report.macro_dominant_root_cause.choice:
            rc_key = report.macro_dominant_root_cause.choice
            rc_prob = report.macro_dominant_root_cause.probabilities.get(
                rc_key, report.macro_dominant_root_cause.confidence
            )
            lines.append(f"- **Dominant Session Root Cause**: `{rc_key}` (P={rc_prob:.2f})")
        for ms in hot_macros:
            lines.append(
                f"- **`{ms.title}` (`{ms.key}`, {ms.dimension})**: P={ms.probability:.2f}"
            )
        lines.append("")

    if primary_eps:
        lines.append(f"## Primary `{dim}` Episode Spotlights")
        for ep in primary_eps:
            dim_sigs = [
                f"`{s.title}` (`{s.key}`: P={s.probability:.2f})"
                for s in ep.peak_signals
                if s.dimension == dim
            ] or [
                f"`{s.title}` (`{s.key}`: P={s.probability:.2f})"
                for s in ep.peak_signals
            ]
            sig_desc = ", ".join(dim_sigs)
            target_comps = sorted(
                {
                    comp
                    for s in ep.peak_signals
                    if s.dimension == dim and s.key in SIGNAL_BY_KEY
                    for comp in SIGNAL_BY_KEY[s.key].target_components
                }
            )
            lines.append(
                f"- **Episode `{ep.episode_id}` (Turns {ep.t_start}..{ep.t_end}, windows {', '.join(ep.window_ids)})**:\n"
                f"  - Signals: {sig_desc}\n"
                f"  - Candidate lever hint: `{ep.primary_lever}` (P={ep.primary_lever_prob:.2f}; targets: {', '.join(f'`{c}`' for c in target_comps)})"
            )
        lines.append("")

    if soft_wins:
        lines.append(f"## Soft `{dim}` Window Spotlights (P >= {thr:.2f})")
        for w, wsigs in soft_wins:
            sig_desc = ", ".join(f"`{s.title}` (`{s.key}`: P={s.probability:.2f})" for s in wsigs)
            lever_name, lever_prob = w.aligned_lever
            lines.append(
                f"- **Window `{w.window_id}` (Turns {w.t_start}..{w.t_end})**: {sig_desc} "
                f"(candidate lever: `{lever_name}`, P={lever_prob:.2f})"
            )
        lines.append("")

    if cross_eps:
        lines.append(
            f"## Cross-Dimension User Pushback / Rework Episodes (Context for `{dim}` Root-Cause Analysis)"
        )
        for ep in cross_eps:
            sig_desc = ", ".join(
                f"`{s.title}` (`{s.key}`: P={s.probability:.2f})" for s in ep.peak_signals
            )
            lines.append(
                f"- **Episode `{ep.episode_id}` (Turns {ep.t_start}..{ep.t_end}, windows {', '.join(ep.window_ids)})**: {sig_desc}"
            )
        lines.append("")
    return "\n".join(lines)


@dataclass
class SessionScanEntry:
    """Multi-session discovery score for one local session transcript."""

    slot_id: str
    session_id: str
    transcript_path: str
    workspace_root: str
    repo_name: str
    turn_count: int
    error_count: int
    first_user_prompt: str
    worth_extracting_prob: float
    peak_macro_prob: float
    benchmark_score: float
    recommended_dimensions: list[str]
    dominant_root_cause: str
    dominant_root_cause_prob: float
    macro_signals: list[SignalScore]


@dataclass
class SessionScanReport:
    """Result of scanning multiple historical sessions with `gemini-decision-1`."""

    model: str
    total_sessions_evaluated: int
    total_questions: int
    total_input_chars: int
    latency_ms: int
    entries: list[SessionScanEntry]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_REPO_MARKERS = (
    ".git",
    "settings.gradle.kts",
    "settings.gradle",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "GEMINI.md",
    "AGENTS.md",
    "CLAUDE.md",
)


def _infer_repo_root(raw_ws: str) -> tuple[str, str]:
    """Normalize a raw workspace path (or file path inside a workspace) to `(repo_root, repo_name)`."""
    norm = (raw_ws or "").replace("\\", "/").rstrip("/")
    if not norm:
        return "", "unknown"
    try:
        p = Path(norm)
        cur = p.parent if p.is_file() else p
        for anc in (cur, *cur.parents):
            if any((anc / m).exists() for m in _REPO_MARKERS):
                clean = str(anc).replace("\\", "/").rstrip("/")
                return clean, anc.name
    except OSError:
        pass
    m = re.match(
        r"^(.+?)/(?:app|src|lib|tests|packages|components|pages|square)(?:/.*)?$",
        norm,
    )
    if m:
        root_str = m.group(1).rstrip("/")
        return root_str, root_str.split("/")[-1]
    if "." in norm.split("/")[-1]:
        parent_str = "/".join(norm.split("/")[:-1])
        if parent_str:
            return parent_str, parent_str.split("/")[-1]
    return norm, norm.split("/")[-1]


def scan_candidate_sessions(
    candidates: list[tuple[str, SessionTrace]],
    *,
    client: DecisionClient | None = None,
    signal_threshold: float = 0.60,
    max_chars_per_batch: int = 420_000,
) -> SessionScanReport:
    """Evaluate a list of `(transcript_path, SessionTrace)` candidates in batched `gdm` calls
    to rank which historical sessions are the best test/benchmark cases for Square.
    """
    decision_client = client or GeminiDecisionClient()
    if not candidates:
        return SessionScanReport(
            model=getattr(decision_client, "model", DEFAULT_DECISION_MODEL),
            total_sessions_evaluated=0,
            total_questions=0,
            total_input_chars=0,
            latency_ms=0,
            entries=[],
        )

    header = (
        "# SQUARE MULTI-SESSION BENCHMARK DISCOVERY SCAN\n"
        "Each block below (`=== CANDIDATE SESSION sN ===`) summarizes a separate coding agent session.\n"
        "Evaluate each question strictly against its named `CANDIDATE SESSION sN` block.\n"
    )

    batches: list[list[tuple[str, str, SessionTrace, str]]] = []
    cur_batch: list[tuple[str, str, SessionTrace, str]] = []
    cur_chars = len(header)

    for idx, (t_path, trace) in enumerate(candidates):
        slot_id = f"s{idx}"
        ws, repo_name = _infer_repo_root(trace.workspace_root or "")
        windows = slice_into_windows(trace, window_size=15, stride=12)
        digest = format_executive_digest(windows, max_chars=8_000)
        block = (
            f"=== CANDIDATE SESSION {slot_id} "
            f"(session_id={trace.session_id}, repo={repo_name}, turns={len(trace.turns)}) ===\n"
            f"{digest}\n"
            f"=== END CANDIDATE SESSION {slot_id} ==="
        )
        if cur_batch and (
            cur_chars + len(block) > max_chars_per_batch or len(cur_batch) >= 35
        ):
            batches.append(cur_batch)
            cur_batch = []
            cur_chars = len(header)
        cur_batch.append((slot_id, t_path, trace, block))
        cur_chars += len(block) + 2

    if cur_batch:
        batches.append(cur_batch)

    raw_noul: dict[str, NoulAnswer] = {}
    raw_choice: dict[str, ChoiceAnswer] = {}
    total_input_chars = 0
    total_questions = 0
    total_latency_ms = 0
    model_name = getattr(decision_client, "model", DEFAULT_DECISION_MODEL)

    for batch in batches:
        doc = header + "\n\n" + "\n\n".join(b[3] for b in batch)
        questions: dict[str, dict[str, Any]] = {}
        for slot_id, _, trace, _ in batch:
            _, repo_name = _infer_repo_root(trace.workspace_root or "")
            label = f"session={trace.session_id[:12]}, repo={repo_name}, turns={len(trace.turns)}"
            questions.update(build_session_scan_questions(slot_id, label))
        resp = decision_client.decide(doc, questions)
        model_name = resp.model
        total_input_chars += resp.input_chars
        total_questions += resp.question_count
        total_latency_ms += int(round(resp.wall_ms))
        raw_noul.update(resp.noul_answers)
        raw_choice.update(resp.choice_answers)

    entries: list[SessionScanEntry] = []
    for idx, (t_path, trace) in enumerate(candidates):
        slot_id = f"s{idx}"
        ws, repo_name = _infer_repo_root(trace.workspace_root or "")
        err_count = sum(
            1
            for t in trace.turns
            for tc in t.tool_calls
            if tc.is_error or tc.exit_code not in (None, 0)
        )
        first_user = ""
        for t in trace.turns:
            if t.role == "user" and t.text.strip():
                first_user = " ".join(t.text.strip().split())
                if len(first_user) > 110:
                    first_user = first_user[:110] + "..."
                break

        worth_ans = raw_noul.get(
            f"{slot_id}_worth_extracting",
            NoulAnswer(probability=0.0, confidence=0.0),
        )
        macro_scores: list[SignalScore] = []
        dims_set: set[str] = set()
        for sig in MACRO_SIGNALS:
            ans = raw_noul.get(
                f"{slot_id}_{sig.key}",
                NoulAnswer(probability=0.0, confidence=0.0),
            )
            trig = ans.probability >= signal_threshold
            if trig:
                dims_set.add(sig.dimension)
            macro_scores.append(
                SignalScore(
                    key=sig.key,
                    title=sig.title,
                    dimension=sig.dimension,
                    probability=round(ans.probability, 4),
                    confidence=round(ans.confidence, 4),
                    triggered=trig,
                )
            )
        rc_ans = raw_choice.get(
            f"{slot_id}_dominant_root_cause",
            ChoiceAnswer(choice="none_routine_session", probabilities={}, confidence=0.0),
        )
        rc_key = rc_ans.choice or "none_routine_session"
        rc_prob = rc_ans.probabilities.get(rc_key, rc_ans.confidence)
        peak_macro = max((m.probability for m in macro_scores), default=0.0)
        benchmark_score = round(0.55 * worth_ans.probability + 0.45 * peak_macro, 4)
        rec_dims = [d for d in ("INV", "DOM") if d in dims_set]

        entries.append(
            SessionScanEntry(
                slot_id=slot_id,
                session_id=trace.session_id,
                transcript_path=t_path,
                workspace_root=ws,
                repo_name=repo_name,
                turn_count=len(trace.turns),
                error_count=err_count,
                first_user_prompt=first_user,
                worth_extracting_prob=round(worth_ans.probability, 4),
                peak_macro_prob=round(peak_macro, 4),
                benchmark_score=benchmark_score,
                recommended_dimensions=rec_dims,
                dominant_root_cause=rc_key,
                dominant_root_cause_prob=round(rc_prob, 4),
                macro_signals=macro_scores,
            )
        )

    entries.sort(key=lambda e: (e.benchmark_score, e.worth_extracting_prob, e.turn_count), reverse=True)
    return SessionScanReport(
        model=model_name,
        total_sessions_evaluated=len(entries),
        total_questions=total_questions,
        total_input_chars=total_input_chars,
        latency_ms=total_latency_ms,
        entries=entries,
    )


def render_scan_markdown(report: SessionScanReport) -> str:
    """Render a ranked Markdown table and top-candidate spotlight list for `square scan`."""
    est_tokens = report.total_input_chars // 4
    est_cost = (est_tokens / 1_000_000) * 0.10
    lines: list[str] = [
        "# Square Session Benchmark Discovery (`gemini-decision-1`)",
        "",
        f"- **Sessions Scanned**: `{report.total_sessions_evaluated}` | **Questions Evaluated**: `{report.total_questions}` | **Latency**: `{report.latency_ms} ms`",
        f"- **Input Size**: `{report.total_input_chars:,} chars` (~`${est_cost:.5f}` at $0.10/1M tokens, 0 output tokens)",
        "",
        "## 1. Ranked Sessions Overview",
        "",
        "| Rank | Repo | Session ID | Turns (Errs) | Benchmark Score | Worth Extracting | Rework (INV) | Manual Toil (INV) | Domain Gap (DOM) | Dominant Root Cause |",
        "| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    for idx, e in enumerate(report.entries, start=1):
        by_key = {m.key: m.probability for m in e.macro_signals}
        rework_p = by_key.get("macro_iterative_rework_loop", 0.0)
        toil_p = by_key.get("macro_recurring_manual_toil", 0.0)
        dom_p = by_key.get("macro_missing_domain_mental_model", 0.0)

        def _fmt(val: float) -> str:
            return f"**{val:.2f}**" if val >= 0.60 else f"{val:.2f}"

        short_sid = e.session_id[:12]
        lines.append(
            f"| {idx} | `{e.repo_name}` | `{short_sid}` | {e.turn_count} ({e.error_count}) | "
            f"**{e.benchmark_score:.2f}** | {_fmt(e.worth_extracting_prob)} | "
            f"{_fmt(rework_p)} | {_fmt(toil_p)} | {_fmt(dom_p)} | "
            f"`{e.dominant_root_cause}` ({e.dominant_root_cause_prob:.2f}) |"
        )

    top_candidates = [e for e in report.entries if e.benchmark_score >= 0.50][:8] or report.entries[:5]
    if top_candidates:
        lines.extend(["", "## 2. Top Recommended Test Sessions for Square", ""])
        for idx, e in enumerate(top_candidates, start=1):
            trig_macros = [
                f"`{m.key}` ({m.dimension}: **{m.probability:.2f}**)"
                for m in e.macro_signals
                if m.triggered
            ]
            trig_str = ", ".join(trig_macros) if trig_macros else "none >= 0.60"
            repo_arg = f' --repo "{e.workspace_root}"' if e.workspace_root else ""
            lines.append(
                f"### #{idx}. `{e.repo_name}` — Session `{e.session_id}` (Score: **{e.benchmark_score:.2f}**, {e.turn_count} turns)"
            )
            lines.append(f"- **Opening Request**: {e.first_user_prompt or '(no user text)'}")
            lines.append(f"- **Triggered Macro Signals**: {trig_str}")
            lines.append(
                f"- **Dominant Root Cause**: `{e.dominant_root_cause}` (**P={e.dominant_root_cause_prob:.2f}**)"
            )
            lines.append("- **Run Triage / Analyze**:")
            lines.append("```powershell")
            lines.append(f'python -m square.cli{repo_arg} triage "{e.transcript_path}"')
            lines.append(f'python -m square.cli{repo_arg} analyze "{e.transcript_path}"')
            lines.append("```")
            lines.append("")

    return "\n".join(lines)
