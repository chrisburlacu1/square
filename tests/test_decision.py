"""Tests for `square.decision` (`gemini-decision-1` triage, windowing, routing, and engine integration)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

from square.decision import (
    ScriptedDecisionClient,
    SessionTriageService,
    UNIVERSAL_SIGNALS,
    build_window_questions,
    format_proposer_brief,
    parse_decision_payload,
    render_triage_markdown,
    slice_into_windows,
)
from square.engine import SquareEngine
from square.proposer import ChannelSpec, Proposer, Reply
from square.schemas import NormalizedTurn, SessionTrace, ToolCallRecord
from square.substrates import AGY_SURFACE


def _make_sample_trace(n_turns: int = 12) -> SessionTrace:
    turns: list[NormalizedTurn] = []
    for i in range(n_turns):
        if i % 4 == 0:
            turns.append(NormalizedTurn(turn_index=i, role="user", text=f"User prompt at turn {i}"))
        else:
            turns.append(
                NormalizedTurn(
                    turn_index=i,
                    role="assistant",
                    text=f"Assistant step {i}",
                    tool_calls=[
                        ToolCallRecord(
                            tool_name="run_command",
                            command_or_target=f"echo step {i}",
                            output=f"out {i}",
                            exit_code=(1 if i == 3 else 0),
                            is_error=(i == 3),
                        )
                    ],
                )
            )
    return SessionTrace(
        session_id="sess_decision_01",
        agent_kind="antigravity",
        domain="android",
        task_prompt="Build and verify the release package",
        turns=turns,
    )


class _RecordingProposer(Proposer):
    def __init__(self) -> None:
        super().__init__(spec=ChannelSpec(kind="scripted"))
        self.missions_by_label: dict[str, str] = {}

    def call(
        self,
        mission: str,
        context_dir: Path | str | None,
        label: str,
        *,
        system: str = "",
        timeout: int | None = None,
        max_attempts: int | None = None,
        harvest: str | None = None,
    ) -> Reply:
        del system, timeout, max_attempts, harvest
        self.missions_by_label[label] = mission
        ws = Path(tempfile.mkdtemp(prefix="square-harvest-"))
        if context_dir and (Path(context_dir) / "harness").is_dir():
            import shutil

            shutil.copytree(Path(context_dir) / "harness", ws, dirs_exist_ok=True)
        if ".dom1." in label:
            (ws / ".agents" / "rules").mkdir(parents=True, exist_ok=True)
            (ws / ".agents" / "rules" / "domain_note.md").write_text("# Domain Note\n", encoding="utf-8")
        else:
            (ws / "scripts").mkdir(parents=True, exist_ok=True)
            (ws / "scripts" / "helper.py").write_text("print('ok')\n", encoding="utf-8")
        return Reply(
            label=label,
            text="<notes>Added helper.py</notes>\n<trigger>{\"path_globs\": [\"**/*.kt\"]}</trigger>",
            ok=True,
            workspace=ws,
        )


class TestDecisionTriage(unittest.TestCase):
    def test_window_slicing_and_question_generation(self) -> None:
        trace = _make_sample_trace(12)
        windows = slice_into_windows(trace, window_size=6, stride=4)
        self.assertEqual([w.window_id for w in windows], ["w0", "w1", "w2"])
        self.assertEqual((windows[0].t_start, windows[0].t_end), (0, 5))
        self.assertEqual((windows[1].t_start, windows[1].t_end), (4, 9))
        self.assertEqual((windows[2].t_start, windows[2].t_end), (8, 11))

        qs = build_window_questions("w0", "Turns 0..5")
        self.assertEqual(len(qs), len(UNIVERSAL_SIGNALS) + 2)
        self.assertEqual(qs["w0_automatable_manual_work"]["type"], "noul")
        self.assertEqual(qs["w0_best_lever"]["type"], "choice")

    def test_parse_decision_payload(self) -> None:
        raw = {
            "answers": {
                "w0_automatable_manual_work": {
                    "type": "noul",
                    "noul": 0.91,
                    "confidence": 0.94,
                },
                "w0_best_lever": {
                    "type": "choice",
                    "choice": "script_c7",
                    "probabilities": {"script_c7": 0.88, "keep_base": 0.12},
                    "confidence": 0.90,
                },
            }
        }
        parsed = parse_decision_payload(raw, wall_ms=185.4, input_chars=4200, question_count=2)
        self.assertAlmostEqual(parsed.noul_answers["w0_automatable_manual_work"].probability, 0.91)
        self.assertEqual(parsed.choice_answers["w0_best_lever"].choice, "script_c7")

    def test_triage_routes_inv_only_and_formats_brief(self) -> None:
        trace = _make_sample_trace(10)

        def _respond(_inp: str, questions: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
            answers: dict[str, Any] = {}
            for q_id, q_spec in questions.items():
                if q_spec["type"] == "noul":
                    prob = 0.89 if q_id == "w0_automatable_manual_work" else 0.08
                    answers[q_id] = {"type": "noul", "noul": prob, "confidence": 0.92}
                else:
                    choice = "script_c7" if q_id.startswith("w0_") else "keep_base"
                    answers[q_id] = {
                        "type": "choice",
                        "choice": choice,
                        "probabilities": {choice: 0.85},
                        "confidence": 0.91,
                    }
            return {"answers": answers}

        client = ScriptedDecisionClient(responder=_respond)
        svc = SessionTriageService(client=client, window_size=6, stride=5)
        report = svc.evaluate(
            trace,
            surface=AGY_SURFACE,
            harness={"GEMINI.md": "# Instructions\n"},
        )
        self.assertTrue(report.should_propose)
        self.assertEqual(report.recommended_dimensions, ["INV"])
        self.assertEqual(len(report.triggered_windows), 1)
        self.assertEqual(report.triggered_windows[0].window_id, "w0")

        md = render_triage_markdown(report)
        self.assertIn("PROPOSE (INV)", md)
        self.assertIn("script_c7", md)

        brief = format_proposer_brief(report, "INV")
        self.assertIn("DECISION MODEL TRIAGE HIGHLIGHTS FOR `INV`", brief)
        self.assertIn("automatable_manual_work", brief)
        self.assertEqual(format_proposer_brief(report, "DOM"), "")

    def test_engine_analyze_defaults_to_no_triage_and_runs_both_dimensions(self) -> None:
        trace = _make_sample_trace(6)

        def _all_quiet(_inp: str, questions: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
            answers: dict[str, Any] = {}
            for q_id, q_spec in questions.items():
                if q_spec["type"] == "noul":
                    answers[q_id] = {"type": "noul", "noul": 0.10, "confidence": 0.95}
                else:
                    answers[q_id] = {
                        "type": "choice",
                        "choice": "keep_base",
                        "probabilities": {"keep_base": 0.96},
                        "confidence": 0.95,
                    }
            return {"answers": answers}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "GEMINI.md").write_text("# Instructions\n", encoding="utf-8")
            prop = _RecordingProposer()
            dec_client = ScriptedDecisionClient(responder=_all_quiet)
            engine = SquareEngine(
                repo_root=repo,
                proposer=prop,
                square_root=root / "sq",
                decision_client=dec_client,
            )
            # Default use_triage=False: does not call decision_client and runs both inv1 and dom1
            engine.analyze_session(trace)
            self.assertEqual(len(dec_client.calls), 0)
            called_labels = sorted(prop.missions_by_label.keys())
            self.assertEqual(len(called_labels), 2)
            self.assertTrue(any(lbl.endswith(".inv1.a1") for lbl in called_labels))
            self.assertTrue(any(lbl.endswith(".dom1.a1") for lbl in called_labels))

    def test_engine_analyze_with_triage_runs_spotlight_only_across_both_dimensions(self) -> None:
        trace = _make_sample_trace(6)

        def _flag_inv_moderate(_inp: str, questions: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
            answers: dict[str, Any] = {}
            for q_id, q_spec in questions.items():
                if q_spec["type"] == "noul":
                    # Moderate 0.52 score (< 0.65 hard gate, >= 0.45 spotlight threshold)
                    prob = 0.52 if q_id == "w0_tool_env_friction" else 0.05
                    answers[q_id] = {"type": "noul", "noul": prob, "confidence": 0.90}
                else:
                    answers[q_id] = {
                        "type": "choice",
                        "choice": "workflow_skill_c6",
                        "probabilities": {"workflow_skill_c6": 0.84},
                        "confidence": 0.90,
                    }
            return {"answers": answers}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "GEMINI.md").write_text("# Instructions\n", encoding="utf-8")
            prop = _RecordingProposer()
            dec_client = ScriptedDecisionClient(responder=_flag_inv_moderate)
            engine = SquareEngine(
                repo_root=repo,
                proposer=prop,
                square_root=root / "sq",
                decision_client=dec_client,
            )
            engine.analyze_session(trace, use_triage=True)
            # Spotlight-only mode: BOTH inv1 and dom1 run (dom1 is never skipped!), and inv1 gets >=0.45 spotlight brief
            self.assertGreater(len(dec_client.calls), 0)
            called_labels = sorted(prop.missions_by_label.keys())
            self.assertEqual(len(called_labels), 2)
            inv_lbl = next(lbl for lbl in called_labels if lbl.endswith(".inv1.a1"))
            dom_lbl = next(lbl for lbl in called_labels if lbl.endswith(".dom1.a1"))
            self.assertIn(
                "DECISION MODEL TRIAGE HIGHLIGHTS FOR `INV`",
                prop.missions_by_label[inv_lbl],
            )
            self.assertIn("`tool_env_friction`: P=0.52", prop.missions_by_label[inv_lbl])
            self.assertNotIn(
                "DECISION MODEL TRIAGE HIGHLIGHTS FOR `DOM`",
                prop.missions_by_label[dom_lbl],
            )

    def test_strict_dimension_routing_episode_merging_and_batching(self) -> None:
        # 50 turns -> with window_size=4, stride=2, produces 24 windows across 2 batches (max 20/batch)
        trace = _make_sample_trace(50)

        def _respond(_inp: str, questions: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
            answers: dict[str, Any] = {}
            for q_id, q_spec in questions.items():
                if q_spec["type"] == "noul":
                    if q_id in ("w0_intent_or_domain_divergence", "w1_intent_or_domain_divergence"):
                        prob = 0.74
                    else:
                        prob = 0.10
                    answers[q_id] = {"type": "noul", "noul": prob, "confidence": 0.88}
                else:
                    # Simulate w21 from Stash: workflow_skill_c6 (0.33) slightly beats domain_skill_c6 (0.30)
                    answers[q_id] = {
                        "type": "choice",
                        "choice": "workflow_skill_c6",
                        "probabilities": {
                            "workflow_skill_c6": 0.33,
                            "domain_skill_c6": 0.30,
                            "workspace_memory_c3": 0.20,
                            "keep_base": 0.17,
                        },
                        "confidence": 0.33,
                    }
            return {"answers": answers}

        client = ScriptedDecisionClient(responder=_respond)
        svc = SessionTriageService(client=client, window_size=4, stride=2)
        report = svc.evaluate(
            trace,
            surface=AGY_SURFACE,
            harness={"GEMINI.md": "# Instructions\n"},
        )
        # 24 windows split into 2 batches (20 + 4)
        self.assertEqual(len(report.windows), 24)
        self.assertEqual(len(client.calls), 2)

        # Only DOM signal fired, so INV must NOT be woken up despite workflow_skill_c6=0.33
        self.assertEqual(report.recommended_dimensions, ["DOM"])
        self.assertEqual(report.windows[0].aligned_lever, ("domain_skill_c6", 0.30))

        # Overlapping w0 (0..3) and w1 (2..5) merge into a single episode ep1 (0..5)
        eps = report.merged_episodes()
        self.assertEqual(len(eps), 1)
        self.assertEqual(eps[0].window_ids, ["w0", "w1"])
        self.assertEqual((eps[0].t_start, eps[0].t_end), (0, 5))
        self.assertEqual(eps[0].primary_lever, "domain_skill_c6")
        self.assertTrue(len(eps[0].turn_digest) > 0)

        md = render_triage_markdown(report)
        self.assertIn("Episode `ep1` — Turns 0..5 (`w0`, `w1`) -> Route: `DOM`", md)
        self.assertIn("Turn Activity Log", md)

    def test_macro_root_cause_and_signal_target_lever_alignment(self) -> None:
        trace = _make_sample_trace(16)

        def _respond(_inp: str, questions: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
            answers: dict[str, Any] = {}
            for q_id, q_spec in questions.items():
                if q_spec["type"] == "noul":
                    if q_id == "macro_iterative_rework_loop":
                        prob = 0.88
                    elif q_id == "w0_context_bloat_investigation":
                        prob = 0.76
                    elif q_id == "w1_automatable_manual_work":
                        prob = 0.81
                    else:
                        prob = 0.08
                    answers[q_id] = {"type": "noul", "noul": prob, "confidence": 0.90}
                elif q_id == "macro_dominant_root_cause":
                    answers[q_id] = {
                        "type": "choice",
                        "choice": "spec_alignment_c1",
                        "probabilities": {"spec_alignment_c1": 0.62},
                        "confidence": 0.62,
                    }
                else:
                    # Simulate hook_c8 (0.39) beating script_c7 (0.28) on w1
                    answers[q_id] = {
                        "type": "choice",
                        "choice": "hook_c8",
                        "probabilities": {
                            "hook_c8": 0.39,
                            "script_c7": 0.28,
                            "workflow_skill_c6": 0.18,
                            "subagent_c5": 0.15,
                        },
                        "confidence": 0.39,
                    }
            return {"answers": answers}

        client = ScriptedDecisionClient(responder=_respond)
        svc = SessionTriageService(client=client, window_size=6, stride=4)
        report = svc.evaluate(
            trace,
            surface=AGY_SURFACE,
            harness={"GEMINI.md": "# Instructions\n"},
        )
        # Macro signal fired
        self.assertEqual(len(report.triggered_macro_signals), 1)
        self.assertEqual(report.triggered_macro_signals[0].key, "macro_iterative_rework_loop")
        self.assertIsNotNone(report.macro_dominant_root_cause)
        assert report.macro_dominant_root_cause is not None
        self.assertEqual(report.macro_dominant_root_cause.choice, "spec_alignment_c1")

        # w1 triggered automatable_manual_work -> aligned_lever must pick script_c7 (0.28), NOT hook_c8 (0.39)
        self.assertEqual(report.windows[1].aligned_lever, ("script_c7", 0.28))

        # w0 (context_bloat) and w1 (automatable_manual_work) must stay separate episodes (ep1, ep2)
        eps = report.merged_episodes()
        self.assertEqual(len(eps), 2)
        self.assertEqual(eps[0].window_ids, ["w0"])
        self.assertEqual(eps[1].window_ids, ["w1"])
        self.assertEqual(eps[1].primary_lever, "script_c7")

    def test_scan_candidate_sessions_ranks_and_renders(self) -> None:
        from square.decision import render_scan_markdown, scan_candidate_sessions

        t_boring = _make_sample_trace(16)
        t_boring.session_id = "sess_boring_01"
        t_boring.workspace_root = "C:/workspace/projects/web/landing-page/src/index.tsx"

        t_rich = _make_sample_trace(40)
        t_rich.session_id = "sess_rich_02"
        t_rich.workspace_root = "C:/workspace/projects/backend/payments/src/service.py"

        def _respond(_inp: str, questions: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
            answers: dict[str, Any] = {}
            for q_id, q_spec in questions.items():
                is_rich = q_id.startswith("s1_")
                if q_spec["type"] == "noul":
                    prob = 0.89 if (is_rich and ("worth_extracting" in q_id or "rework" in q_id)) else 0.12
                    answers[q_id] = {"type": "noul", "noul": prob, "confidence": 0.91}
                else:
                    choice = "spec_alignment_c1" if is_rich else "none_routine_session"
                    answers[q_id] = {
                        "type": "choice",
                        "choice": choice,
                        "probabilities": {choice: 0.72},
                        "confidence": 0.72,
                    }
            return {"answers": answers}

        client = ScriptedDecisionClient(responder=_respond)
        scan_rep = scan_candidate_sessions(
            [("path/to/boring.jsonl", t_boring), ("path/to/rich.jsonl", t_rich)],
            client=client,
        )
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(scan_rep.entries[0].session_id, "sess_rich_02")
        self.assertEqual(scan_rep.entries[0].repo_name, "payments")
        self.assertEqual(scan_rep.entries[0].workspace_root, "C:/workspace/projects/backend/payments")
        self.assertGreater(scan_rep.entries[0].benchmark_score, scan_rep.entries[1].benchmark_score)

        md = render_scan_markdown(scan_rep)
        self.assertIn("`payments`", md)
        self.assertIn("python -m square.cli --repo \"C:/workspace/projects/backend/payments\" analyze", md)


if __name__ == "__main__":
    unittest.main()
