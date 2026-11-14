"""Tests for `square/lease.py` (Situation-Based `ActivationTrigger` Matching & Lease Store).

Verifies Invariant #7 across native `SurfaceSpec`s:
1. Unrelated sessions do not match `situation_matched` (`UNRELATED_SESSION`) and do not increment $A_1$.
2. Sessions matching `ActivationTrigger` where the agent invokes the leased skill/script/rule
   return `ACTIVATED_AND_INVOKED`.
3. Sessions matching `ActivationTrigger` where the agent ignores the leased component return
   `IGNORED_BY_AGENT`.
4. Tier 1 vs. Tier 2 classification and approval gate.
"""

from __future__ import annotations

import tempfile
import unittest

from square.lease import LeaseStore, classify_tier, match_activation
from square.schemas import ActivationTrigger, NormalizedTurn, SessionTrace, ToolCallRecord
from square.substrates import CLAUDE_SURFACE, CODEX_SURFACE


class TestLeaseActivation(unittest.TestCase):
    def setUp(self) -> None:
        self.base_tree = {"AGENTS.md": "# Repository Instructions\n"}
        self.cand_tree = dict(self.base_tree)
        self.cand_tree[".agents/skills/wf_inspect_aar/SKILL.md"] = (
            "---\nname: wf_inspect_aar\ndescription: Inspect AAR classes\n---\n"
            "Run javap on classes.jar once.\n"
        )
        self.cand_tree["AGENTS.md"] += (
            "- When inspecting AAR/JAR packages, read .agents/skills/wf_inspect_aar/SKILL.md and follow it.\n"
        )
        self.trigger = ActivationTrigger(
            path_globs=["**/*.gradle.kts", "**/*.aar"],
            command_regex=r"\b(javap|jar\s+tf|unzip\s+-l)\b",
            cue_keywords=["EmbeddingEngine", "litertlm"],
        )

    def test_tier_classification(self) -> None:
        self.assertEqual(
            classify_tier(["AGENTS.md", ".agents/skills/wf_inspect_aar/SKILL.md"], CODEX_SURFACE),
            "TIER_1",
        )
        self.assertEqual(
            classify_tier(["AGENTS.md", "scripts/inspect_jar.py"], CODEX_SURFACE),
            "TIER_2",
        )
        self.assertEqual(
            classify_tier([".codex/hooks.json"], CODEX_SURFACE),
            "TIER_2",
        )
        self.assertEqual(
            classify_tier([".claude/hooks.json"], CLAUDE_SURFACE),
            "TIER_2",
        )

    def test_unrelated_session_does_not_activate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LeaseStore(tmp)
            lease = store.create_lease(
                case_id="case_001",
                domain="android",
                dimension="INV",
                base_tree=self.base_tree,
                candidate_tree=self.cand_tree,
                trigger=self.trigger,
                surface=CODEX_SURFACE,
            )
            assert lease is not None

            unrelated_trace = SessionTrace(
                session_id="sess_readme",
                domain="android",
                task_prompt="Fix a typo in README.md",
                turns=[
                    NormalizedTurn(turn_index=0, role="user", text="Fix typo in README.md"),
                    NormalizedTurn(
                        turn_index=1,
                        role="assistant",
                        text="Fixed typo in README.md.",
                        tool_calls=[
                            ToolCallRecord(
                                tool_name="edit_file",
                                command_or_target="README.md",
                                arguments={"path": "README.md"},
                            )
                        ],
                    ),
                ],
            )

            res = match_activation(unrelated_trace, lease, surface=CODEX_SURFACE)
            self.assertFalse(res.situation_matched)
            self.assertFalse(res.component_invoked)
            self.assertEqual(res.outcome, "UNRELATED_SESSION")

    def test_situation_matched_and_component_invoked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LeaseStore(tmp)
            lease = store.create_lease(
                case_id="case_001",
                domain="android",
                dimension="INV",
                base_tree=self.base_tree,
                candidate_tree=self.cand_tree,
                trigger=self.trigger,
                surface=CODEX_SURFACE,
            )
            assert lease is not None

            activated_trace = SessionTrace(
                session_id="sess_litert_probe",
                domain="android",
                task_prompt="Update build.gradle.kts to configure litertlm EmbeddingEngine",
                turns=[
                    NormalizedTurn(
                        turn_index=0,
                        role="user",
                        text="Update build.gradle.kts to configure litertlm EmbeddingEngine",
                    ),
                    NormalizedTurn(
                        turn_index=1,
                        role="assistant",
                        reasoning="Situation matches AAR inspection; reading wf_inspect_aar skill first.",
                        text="Loaded wf_inspect_aar and configured EmbeddingEngine.",
                        tool_calls=[
                            ToolCallRecord(
                                tool_name="read_file",
                                command_or_target=".agents/skills/wf_inspect_aar/SKILL.md",
                                arguments={"path": "app/build.gradle.kts"},
                            )
                        ],
                    ),
                ],
            )

            res = match_activation(activated_trace, lease, surface=CODEX_SURFACE)
            self.assertTrue(res.situation_matched)
            self.assertTrue(res.component_invoked)
            self.assertEqual(res.outcome, "ACTIVATED_AND_INVOKED")

    def test_situation_matched_but_ignored_by_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LeaseStore(tmp)
            lease = store.create_lease(
                case_id="case_001",
                domain="android",
                dimension="INV",
                base_tree=self.base_tree,
                candidate_tree=self.cand_tree,
                trigger=self.trigger,
                surface=CODEX_SURFACE,
            )
            assert lease is not None

            ignored_trace = SessionTrace(
                session_id="sess_ignored_probe",
                domain="android",
                task_prompt="Check EmbeddingEngine in litertlm",
                turns=[
                    NormalizedTurn(
                        turn_index=0,
                        role="user",
                        text="Check EmbeddingEngine in litertlm",
                    ),
                    NormalizedTurn(
                        turn_index=1,
                        role="assistant",
                        text="I will run unzip -l manually without loading any skill.",
                        tool_calls=[
                            ToolCallRecord(
                                tool_name="bash",
                                command_or_target="unzip -l litertlm.aar",
                                output="classes.jar",
                            )
                        ],
                    ),
                ],
            )

            res = match_activation(ignored_trace, lease, surface=CODEX_SURFACE)
            self.assertTrue(res.situation_matched)
            self.assertFalse(res.component_invoked)
            self.assertEqual(res.outcome, "IGNORED_BY_AGENT")

    def test_read_output_noise_immunity(self) -> None:
        """A cue_keyword appearing strictly inside a read_file tc.output payload on an unrelated
        task must NOT trigger situation_matched=True -> IGNORED_BY_AGENT.
        """
        with tempfile.TemporaryDirectory() as tmp:
            store = LeaseStore(tmp)
            lease = store.create_lease(
                case_id="case_noise",
                domain="android",
                dimension="INV",
                base_tree=self.base_tree,
                candidate_tree=self.cand_tree,
                trigger=ActivationTrigger(
                    path_globs=[],
                    command_regex="",
                    cue_keywords=["EmbeddingEngine"],
                ),
                surface=CODEX_SURFACE,
            )
            assert lease is not None

            unrelated_dump_trace = SessionTrace(
                session_id="sess_read_dump",
                domain="android",
                task_prompt="Check license header in NOTICE.txt",
                turns=[
                    NormalizedTurn(
                        turn_index=0,
                        role="user",
                        text="Check license header in NOTICE.txt",
                    ),
                    NormalizedTurn(
                        turn_index=1,
                        role="assistant",
                        text="NOTICE.txt uses Apache 2.0.",
                        tool_calls=[
                            ToolCallRecord(
                                tool_name="read_file",
                                command_or_target="NOTICE.txt",
                                arguments={"path": "NOTICE.txt"},
                                output="Apache 2.0 License - mentions EmbeddingEngine in third-party credits",
                            )
                        ],
                    ),
                ],
            )
            res = match_activation(unrelated_dump_trace, lease, surface=CODEX_SURFACE)
            self.assertFalse(res.situation_matched)
            self.assertEqual(res.outcome, "UNRELATED_SESSION")

    def test_skill_casual_prose_is_ignored_while_bundled_script_is_invoked(self) -> None:
        cand_with_bundled = dict(self.cand_tree)
        cand_with_bundled[".agents/skills/wf_inspect_aar/scripts/check_aar.py"] = (
            "print('ok')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = LeaseStore(tmp)
            lease = store.create_lease(
                case_id="case_skill_inv",
                domain="android",
                dimension="INV",
                base_tree=self.base_tree,
                candidate_tree=cand_with_bundled,
                trigger=self.trigger,
                surface=CODEX_SURFACE,
            )
            assert lease is not None

            # 1. Mentioning `wf_inspect_aar` casually in prose WITHOUT reading SKILL.md or running its script -> IGNORED_BY_AGENT
            prose_only_trace = SessionTrace(
                session_id="sess_prose_only",
                domain="android",
                task_prompt="Configure litertlm EmbeddingEngine",
                turns=[
                    NormalizedTurn(
                        turn_index=0,
                        role="user",
                        text="Configure litertlm EmbeddingEngine",
                    ),
                    NormalizedTurn(
                        turn_index=1,
                        role="assistant",
                        reasoning="I see wf_inspect_aar mentioned in AGENTS.md, skipping it.",
                        text="Skipped wf_inspect_aar and edited manually.",
                    ),
                ],
            )
            res_prose = match_activation(prose_only_trace, lease, surface=CODEX_SURFACE)
            self.assertTrue(res_prose.situation_matched)
            self.assertFalse(res_prose.component_invoked)
            self.assertEqual(res_prose.outcome, "IGNORED_BY_AGENT")

            # 2. Executing bundled script `.agents/skills/wf_inspect_aar/scripts/check_aar.py` -> ACTIVATED_AND_INVOKED
            bundled_script_trace = SessionTrace(
                session_id="sess_bundled_script",
                domain="android",
                task_prompt="Configure litertlm EmbeddingEngine",
                turns=[
                    NormalizedTurn(
                        turn_index=0,
                        role="user",
                        text="Configure litertlm EmbeddingEngine",
                    ),
                    NormalizedTurn(
                        turn_index=1,
                        role="assistant",
                        text="Ran bundled AAR inspector.",
                        tool_calls=[
                            ToolCallRecord(
                                tool_name="run_command",
                                command_or_target="python .agents/skills/wf_inspect_aar/scripts/check_aar.py",
                                output="ok",
                            )
                        ],
                    ),
                ],
            )
            res_script = match_activation(bundled_script_trace, lease, surface=CODEX_SURFACE)
            self.assertTrue(res_script.situation_matched)
            self.assertTrue(res_script.component_invoked)
            self.assertEqual(res_script.outcome, "ACTIVATED_AND_INVOKED")

    def test_always_on_only_lease_returns_mounted_always_on(self) -> None:
        from square.substrates import AGY_SURFACE

        base = {"GEMINI.md": "# Instructions\n"}
        cand = {
            "GEMINI.md": "# Instructions\n- Verified package is com.example.sdk.\n",
            ".agents/rules/sdk_pkg.md": "# SDK Rule\nUse com.example.sdk.\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = LeaseStore(tmp)
            lease = store.create_lease(
                case_id="case_ao",
                domain="android",
                dimension="DOM",
                base_tree=base,
                candidate_tree=cand,
                trigger=ActivationTrigger(path_globs=["**/*.kt"]),
                surface=AGY_SURFACE,
            )
            assert lease is not None
            trace = SessionTrace(
                session_id="sess_ao",
                task_prompt="Edit Main.kt",
                turns=[
                    NormalizedTurn(
                        turn_index=0,
                        role="assistant",
                        text="Edited Main.kt",
                        tool_calls=[
                            ToolCallRecord(
                                tool_name="write_file",
                                command_or_target="app/Main.kt",
                                arguments={"path": "app/Main.kt"},
                            )
                        ],
                    )
                ],
            )
            res = match_activation(trace, lease, surface=AGY_SURFACE)
            self.assertTrue(res.situation_matched)
            self.assertTrue(res.component_invoked)
            self.assertEqual(res.outcome, "MOUNTED_ALWAYS_ON")

    def test_apply_revert_prunes_empty_dirs_strips_active_and_preflights_scripts(self) -> None:
        from pathlib import Path
        from square.engine import SquareEngine
        from square.proposer import Proposer
        from square.substrates import AGY_SURFACE

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "GEMINI.md").write_text("# Instructions\n", encoding="utf-8")
            engine = SquareEngine(repo_root=repo, proposer=Proposer(), square_root=root / "sq")

            # 1. Stage a broken Tier 2 script lease -> pre-flight rejects unless force=True
            base = {"GEMINI.md": "# Instructions\n"}
            bad_cand = {
                "GEMINI.md": "# Instructions\n- Run scripts/bad_tool.py\n",
                "scripts/bad_tool.py": "import nonexistent_pkg_xyz_999\nprint('hi')\n",
            }
            bad_lease = engine.lease_store.create_lease(
                case_id="case_bad_py",
                domain="default",
                dimension="INV",
                base_tree=base,
                candidate_tree=bad_cand,
                trigger=ActivationTrigger(cue_keywords=["tool"]),
                surface=AGY_SURFACE,
            )
            assert bad_lease is not None
            bad_lease.status = "AWAITING_TRIAL"
            engine.lease_store.update_lease(bad_lease)

            with self.assertRaises(ValueError) as ctx_pf:
                engine.apply_case_leases("case_bad_py")
            self.assertIn("Tier 2 script pre-flight failed", str(ctx_pf.exception))
            self.assertFalse((repo / "scripts/bad_tool.py").exists())

            # 2. Stage a clean skill + GEMINI.md lease -> apply -> verify stamped & stripped from current_harness -> revert -> verify zero residue & pruned dirs
            good_cand = {
                "GEMINI.md": "# Instructions\n- Read .agents/skills/clean_probe/SKILL.md\n",
                ".agents/skills/clean_probe/SKILL.md": (
                    "---\nname: clean_probe\ndescription: Clean probe skill\n---\n# Clean\n"
                ),
            }
            good_lease = engine.lease_store.create_lease(
                case_id="case_clean",
                domain="default",
                dimension="DOM",
                base_tree=base,
                candidate_tree=good_cand,
                trigger=ActivationTrigger(cue_keywords=["probe"]),
                surface=AGY_SURFACE,
            )
            assert good_lease is not None
            good_lease.status = "AWAITING_TRIAL"
            engine.lease_store.update_lease(good_lease)

            applied = engine.apply_case_leases("case_clean")
            self.assertEqual(len(applied), 1)
            skill_disk = repo / ".agents/skills/clean_probe/SKILL.md"
            self.assertTrue(skill_disk.is_file())
            self.assertIn("<!-- square-managed -->", skill_disk.read_text(encoding="utf-8"))
            self.assertIn(
                "<!-- SQUARE_LEASE:id=",
                (repo / "GEMINI.md").read_text(encoding="utf-8"),
            )

            # While active, current_harness() strips both the SQUARE_LEASE block and the active leased skill!
            clean_h = engine.current_harness("antigravity")
            self.assertNotIn(".agents/skills/clean_probe/SKILL.md", clean_h)
            self.assertNotIn("SQUARE_LEASE", clean_h["GEMINI.md"])

            # Revert removes SQUARE_LEASE tags and prunes empty `.agents/skills/clean_probe` directory
            reverted = engine.revert_active_leases("case_clean")
            self.assertEqual(len(reverted), 1)
            self.assertEqual((repo / "GEMINI.md").read_text(encoding="utf-8"), "# Instructions\n")
            self.assertFalse((repo / ".agents/skills/clean_probe").exists())


if __name__ == "__main__":
    unittest.main()
