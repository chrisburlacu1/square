import tempfile
import unittest
from pathlib import Path

from square.evidence import EvidenceStore
from square.engine import SquareEngine
from square.proposer import Proposer
from square.engine import StageOutcome
from square.schemas import SessionTrace, NormalizedTurn, ToolCallRecord
from unittest.mock import patch


class TestEvidence(unittest.TestCase):
    def test_manual_review_bypasses_gate_and_reuses_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            engine = SquareEngine(repo, Proposer(), square_root=root / "state")
            trace = SessionTrace(session_id="smooth", task_prompt="Inspect this interface",
                turns=[NormalizedTurn(turn_index=0, role="user", text="Inspect this interface")])
            def stage(**kwargs):
                return StageOutcome(label=kwargs["label"], dim=kwargs["dim"], tree={},
                    kept_base=True, notes="No reusable improvement justified")
            with patch("square.engine.run_stage", side_effect=stage) as proposer:
                report = engine.analyze_session(trace)
                self.assertIn("No reusable improvement justified", report.read_text())
                self.assertEqual(proposer.call_count, 2)
                self.assertEqual(engine.analyze_session(trace), report)
                self.assertEqual(proposer.call_count, 2)
                self.assertNotEqual(engine.analyze_session(trace, retry=True), report)
            self.assertEqual(list(repo.iterdir()), [])

    def test_manual_report_distinguishes_failure_from_no_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.joinpath("repo").mkdir()
            engine = SquareEngine(root / "repo", Proposer(), square_root=root / "state")
            trace = SessionTrace(session_id="failure", raw_trajectory_md="[USER] Inspect a package")
            def stage(**kwargs):
                return StageOutcome(label=kwargs["label"], dim=kwargs["dim"], tree={},
                    fell_back=True, error="CLI unavailable")
            with patch("square.engine.run_stage", side_effect=stage):
                report = engine.analyze_session(trace).read_text()
            self.assertIn("CLI unavailable", report)
            self.assertIn("not evidence", report)

    def test_unknown_exit_is_neither_failure_nor_green_validation(self):
        turn = NormalizedTurn(turn_index=0, role="assistant", tool_calls=[
            ToolCallRecord(tool_name="shell", command_or_target="pytest")])
        self.assertFalse(turn.has_errors)
        self.assertFalse(turn.has_green_validation)

    def test_offline_proposal_trial_and_decision_leave_repo_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "GEMINI.md").write_text("User instructions", encoding="utf-8")
            engine = SquareEngine(repo, Proposer(), square_root=root / "state")
            trace = SessionTrace(session_id="repeat", turns=[NormalizedTurn(
                turn_index=i, role="assistant", tool_calls=[ToolCallRecord(
                    tool_name="read_file", command_or_target="package")]) for i in range(4)])
            def stage(**kwargs):
                return StageOutcome(label=kwargs["label"], dim=kwargs["dim"],
                    tree={"GEMINI.md": "Proposed instructions"}, notes="Reduce repeated work")
            with patch("square.engine.run_stage", side_effect=stage) as proposer:
                # Default process_session() is probe-only (zero LLM calls when no active lease exists)
                probe_only = engine.process_session(trace)
                self.assertEqual(probe_only.created_leases, [])
                self.assertEqual(proposer.call_count, 0)
                # Opt-in propose=True runs background slice detection -> AWAITING_TRIAL candidates
                report = engine.process_session(trace, propose=True)
                self.assertTrue(report.created_leases)
                count = proposer.call_count
                engine.process_session(trace, propose=True)
                self.assertEqual(proposer.call_count, count)
            records = list((engine.evidence.root / "candidates").glob("*.json"))
            version = records[0].stem
            def runner(workspace, input_id):
                self.assertEqual((workspace / "GEMINI.md").read_text(), "Proposed instructions")
                return dict(completed=True, correct=True, helped=True, regression=False, details="Fixture passed")
            observations = [engine.try_candidate(version, name, runner) for name in ("a", "b")]
            decision = engine.assess_candidate(version, observations)
            self.assertEqual(decision["status"], "supported_in_recorded_trials")
            self.assertEqual((repo / "GEMINI.md").read_text(), "User instructions")
            self.assertEqual(len(list(repo.iterdir())), 1)

    def test_default_engine_does_not_create_project_instructions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            engine = SquareEngine(repo, Proposer(), square_root=root / "state")
            self.assertEqual(engine.current_harness(), {})
            self.assertEqual(list(repo.iterdir()), [])

    def test_trials_are_immutable_and_revision_cannot_inherit_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp))
            candidate = store.candidate({"skill.md": "first"}, case_id="case", notes="reason")
            def trial(input_id):
                return store.trial(candidate, input_id=input_id, completed=True,
                    correct=True, helped=True, regression=False, details="checked output", runner="fixture")
            first = trial("one")
            self.assertEqual(first, trial("one"))
            self.assertEqual(store.assess(candidate, [first, first])["status"], "needs_more_evidence")
            second = trial("two")
            self.assertEqual(store.assess(candidate, [first, second])["status"], "supported_in_recorded_trials")
            revision = store.candidate({"skill.md": "changed"}, case_id="case", notes="revision", parent=candidate)
            with self.assertRaises(ValueError):
                store.assess(revision, [first])
            bad = store.trial(candidate, input_id="three", completed=True, correct=False,
                helped=None, regression=True, details="incorrect output", runner="fixture")
            self.assertEqual(store.assess(candidate, [first, second, bad])["status"], "rejected")
            self.assertEqual(len(list((store.root / "trials").glob("*.json"))), 3)

    def test_incomplete_and_tampered_evidence_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp))
            candidate = store.candidate({}, case_id="case", notes="reason")
            self.assertEqual(store.assess(candidate, [])["status"], "needs_more_evidence")
            path = store.root / "candidates" / f"{candidate}.json"
            path.write_text('{}', encoding="utf-8")
            with self.assertRaises(ValueError):
                store.assess(candidate, [])
