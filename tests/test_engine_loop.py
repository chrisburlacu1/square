"""End-to-end deterministic tests for `square/engine.py` (`SquareEngine`) and Antigravity transcript parsing.

Modeled on `reference/harness2/harness2/demo.py:DemoProposer`.
Exercises the complete zero-user-input autonomous lifecycle across 3 sessions on native `SurfaceSpec`s:
1. Session 1 (Friction): Agent thrashes on LiteRT `EmbeddingEngine` bytecode lookup ->
   `Slicer` extracts $e^0$ slice -> `Propose` runs `INV` + `DOM` in parallel ->
   Auto-leases Tier 1 `lease_inv` and `lease_dom` into `.square/leases.json` and
   materializes tagged blocks (`<!-- SQUARE_LEASE:id=... -->`) directly into the substrate's
   native files (`GEMINI.md`, `.agents/skills/`, `.agents/rules/`).
2. Session 2 (Unrelated): Agent edits `README.md` -> `match_activation` sees
   `situation_matched=False` -> lease clock stays at $A_1 = 0$, zero LLM calls.
3. Session 3 (Activated Probe): Agent works on `EmbeddingEngine` in `FeedViewModel.kt` ->
   `match_activation` sees `situation_matched=True` ($A_1 = 1$) -> records $e^{\\text{probe}}$ ->
   triggers multi-candidate `Composer` (merges `INV` + `DOM` together, reverts lease tags, and
   safely applies $H_1$ via `apply_tree` while preserving pre-existing user skills) ->
   triggers `Experience Reflector` (updates unified `.square/library/antigravity/INDEX.md` and
   `harnesses/<case_id>/EXPERIENCE.md` with YAML frontmatter).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from square import cli, tree
from square.engine import SquareEngine
from square.proposer import ChannelSpec, Proposer, Reply
from square.schemas import FileMutation, NormalizedTurn, SessionTrace, ToolCallRecord
from square.substrates import AGY_SURFACE, parse_session_trace


class ScriptedSquareProposer(Proposer):
    """Deterministic scripted proposer that edits `context/harness/` in-place on `AGY_SURFACE`."""

    def __init__(self, audit_dir: Path | None = None):
        super().__init__(
            spec=ChannelSpec(kind="scripted", model="local/scripted"),
            audit_dir=audit_dir,
        )

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
        ctx = Path(context_dir) if context_dir else Path(".")
        workspace: Path | None = None

        if ".inv1." in label:
            tmp_h = Path(tempfile.mkdtemp(prefix="scripted-inv-"))
            shutil.copytree(ctx / "harness", tmp_h, dirs_exist_ok=True)
            skill_file = tmp_h / ".agents" / "skills" / "aar_inspect" / "SKILL.md"
            skill_file.parent.mkdir(parents=True, exist_ok=True)
            skill_file.write_text(
                "---\n"
                "name: aar_inspect\n"
                "description: Inspect AAR/JAR class signatures with javap in one step\n"
                "---\n"
                "# AAR Bytecode Inspection\n"
                "Extract classes.jar once and run `javap -cp classes.jar <Class>`.\n",
                encoding="utf-8",
            )
            gm = (tmp_h / "GEMINI.md").read_text(encoding="utf-8")
            (tmp_h / "GEMINI.md").write_text(
                gm.rstrip()
                + "\n- When inspecting AAR or JAR class signatures, read .agents/skills/aar_inspect/SKILL.md and follow it.\n",
                encoding="utf-8",
            )
            workspace = tmp_h
            text = (
                "<notes>Added aar_inspect skill after 5 turns of javap/jar thrash in base1.</notes>\n"
                "<trigger>\n"
                '{"path_globs": ["**/*.gradle.kts", "**/*.kt"], '
                '"command_regex": "\\\\b(javap|jar\\\\s+tf)\\\\b", '
                '"cue_keywords": ["EmbeddingEngine", "litertlm"]}\n'
                "</trigger>"
            )

        elif ".dom1." in label:
            tmp_h = Path(tempfile.mkdtemp(prefix="scripted-dom-"))
            shutil.copytree(ctx / "harness", tmp_h, dirs_exist_ok=True)
            skill_file = tmp_h / ".agents" / "skills" / "litert_api" / "SKILL.md"
            skill_file.parent.mkdir(parents=True, exist_ok=True)
            skill_file.write_text(
                "---\n"
                "name: litert_api\n"
                "description: LiteRT-LM Android SDK package and initialization contract\n"
                "---\n"
                "# LiteRT-LM Contract\n"
                "Import `com.google.ai.edge.litertlm.EmbeddingEngine`.\n",
                encoding="utf-8",
            )
            rule_file = tmp_h / ".agents" / "rules" / "litert_package.md"
            rule_file.parent.mkdir(parents=True, exist_ok=True)
            rule_file.write_text(
                "# LiteRT Package Rule\n"
                "Always import `com.google.ai.edge.litertlm.EmbeddingEngine`.\n",
                encoding="utf-8",
            )
            gm = (tmp_h / "GEMINI.md").read_text(encoding="utf-8")
            (tmp_h / "GEMINI.md").write_text(
                gm.rstrip()
                + "\n- In this workspace, `EmbeddingEngine` is in package `com.google.ai.edge.litertlm`.\n"
                + "- When integrating LiteRT-LM APIs, read .agents/skills/litert_api/SKILL.md and follow it.\n",
                encoding="utf-8",
            )
            workspace = tmp_h
            text = (
                "<notes>Encoded verified LiteRT package fact in GEMINI.md, .agents/rules/litert_package.md, and litert_api skill.</notes>\n"
                "<trigger>\n"
                '{"path_globs": ["**/*.kt"], '
                '"command_regex": "", '
                '"cue_keywords": ["EmbeddingEngine", "litertlm"]}\n'
                "</trigger>"
            )

        elif ".compose_" in label:
            tmp_h = Path(tempfile.mkdtemp(prefix="scripted-comp-"))
            base_t = tree.read_tree(AGY_SURFACE, ctx / "harness")
            pool_dirs = sorted((ctx / "pool").iterdir()) if (ctx / "pool").is_dir() else []
            inv_t: tree.Tree | None = None
            dom_t: tree.Tree | None = None
            for pd in pool_dirs:
                cand_t = tree.read_tree(AGY_SURFACE, pd / "harness")
                if pd.name.endswith("_inv"):
                    inv_t = cand_t
                else:
                    dom_t = cand_t
            merged = tree.merge_parallel_trees(AGY_SURFACE, base_t, inv_t, dom_t)
            tree.write_tree(AGY_SURFACE, merged, tmp_h, stubs=False)
            workspace = tmp_h
            text = (
                "<notes>\n"
                "kept -> GEMINI.md, .agents/rules/litert_package.md & .agents/skills/ -> probe session resolved EmbeddingEngine in 1 turn without javap errors\n"
                "</notes>"
            )

        elif label.startswith("experience."):
            text = (
                "<edits>\n"
                "component: .agents/skills/aar_inspect/SKILL.md\n"
                "candidates: case_inv\n"
                "change: added reusable aar_inspect skill for one-step javap inspection\n"
                "observed: probe session resolved class signature in turn 1 without 5 javap retries\n"
                "verdict: helped\n"
                "</edits>\n\n"
                "<experience>\n"
                "task_domain: android-kotlin-litert\n"
                "deficiency_type: INV: Mechanical Thrash\n"
                "trajectory_differential_summary: Base session took 5 javap/jar turns with 2 errors; probe session completed in 1 turn.\n"
                "cue: When an Android AAR dependency ships classes whose package path is non-obvious\n"
                "lesson: Provide a reusable aar_inspect skill in .agents/skills/ that extracts classes.jar once before javap\n"
                "evidence: Base session took 5 javap/jar turns with 2 errors; probe session completed in 1 turn.\n"
                "confidence: high\n"
                "</experience>"
            )
        else:
            raise ValueError(f"Unexpected scripted proposer label: {label}")

        reply = Reply(label=label, text=text, ok=True, attempts=1, workspace=workspace)
        self._calls.append(reply)
        return reply


class TestEngineLoop(unittest.TestCase):
    def test_full_autonomous_loop_across_three_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            # Pre-create an untracked user skill to verify apply_tree never deletes user skills
            user_skill = repo_root / ".agents" / "skills" / "existing_team_skill" / "SKILL.md"
            user_skill.parent.mkdir(parents=True, exist_ok=True)
            user_skill.write_text(
                "---\nname: existing_team_skill\ndescription: User skill\n---\nKeep me.\n",
                encoding="utf-8",
            )

            prop = ScriptedSquareProposer()
            engine = SquareEngine(
                live_workspace=True,  # Legacy live-edit compatibility path.
                repo_root=repo_root,
                proposer=prop,
                substrate="antigravity",
                activations_target=1,
            )

            # ------------------------------------------------------------------
            # SESSION 1: Friction session (Mechanical Thrash on EmbeddingEngine)
            # ------------------------------------------------------------------
            sess1 = SessionTrace(
                session_id="sess1_friction",
                agent_kind="antigravity",
                task_prompt="Wire up LiteRT EmbeddingEngine in SearchRepo.kt",
                turns=[
                    NormalizedTurn(
                        turn_index=0,
                        role="user",
                        text="Wire up LiteRT EmbeddingEngine in SearchRepo.kt",
                    ),
                    NormalizedTurn(
                        turn_index=1,
                        role="assistant",
                        tool_calls=[
                            ToolCallRecord(
                                tool_name="run_command",
                                command_or_target="javap com.google.ai.EmbeddingEngine",
                                output="Error: class not found",
                                exit_code=1,
                                is_error=True,
                            )
                        ],
                    ),
                    NormalizedTurn(
                        turn_index=2,
                        role="assistant",
                        tool_calls=[
                            ToolCallRecord(
                                tool_name="run_command",
                                command_or_target="jar tf litertlm.aar",
                                output="classes.jar",
                                exit_code=0,
                            )
                        ],
                    ),
                    NormalizedTurn(
                        turn_index=3,
                        role="assistant",
                        tool_calls=[
                            ToolCallRecord(
                                tool_name="run_command",
                                command_or_target="javap -cp classes.jar com.google.edge.EmbeddingEngine",
                                output="Error: class not found",
                                exit_code=1,
                                is_error=True,
                            )
                        ],
                    ),
                    NormalizedTurn(
                        turn_index=4,
                        role="assistant",
                        tool_calls=[
                            ToolCallRecord(
                                tool_name="run_command",
                                command_or_target="javap -cp classes.jar com.google.ai.edge.litertlm.EmbeddingEngine",
                                output="public class EmbeddingEngine",
                                exit_code=0,
                            )
                        ],
                        file_mutations=[
                            FileMutation(
                                path="app/src/main/SearchRepo.kt",
                                before_content="class SearchRepo {}\n",
                                after_content="import com.google.ai.edge.litertlm.EmbeddingEngine\nclass SearchRepo {}\n",
                            )
                        ],
                    ),
                ],
            )

            rep1 = engine.process_session(sess1)
            self.assertEqual(len(rep1.slices_detected), 1)
            self.assertEqual(len(rep1.created_leases), 2)
            active = engine.lease_store.active_leases(substrate_name="antigravity")
            self.assertEqual(len(active), 2)
            self.assertEqual({l.dimension for l in active}, {"INV", "DOM"})

            # Check that GEMINI.md has the tagged SQUARE_LEASE blocks and .agents/ has leased skills + rules
            gemini_md = (repo_root / "GEMINI.md").read_text(encoding="utf-8")
            self.assertIn("<!-- SQUARE_LEASE:id=", gemini_md)
            self.assertTrue((repo_root / ".agents/skills/aar_inspect/SKILL.md").is_file())
            self.assertTrue((repo_root / ".agents/skills/litert_api/SKILL.md").is_file())
            self.assertTrue((repo_root / ".agents/rules/litert_package.md").is_file())
            self.assertTrue(user_skill.is_file())

            calls_after_sess1 = len(prop._calls)
            self.assertEqual(calls_after_sess1, 2)  # inv1 + dom1

            # ------------------------------------------------------------------
            # SESSION 2: Unrelated session (touches README.md only)
            # ------------------------------------------------------------------
            sess2 = SessionTrace(
                session_id="sess2_unrelated",
                agent_kind="antigravity",
                task_prompt="Update README.md installation notes",
                turns=[
                    NormalizedTurn(turn_index=0, role="user", text="Update README.md"),
                    NormalizedTurn(
                        turn_index=1,
                        role="assistant",
                        text="Updated README.md.",
                        file_mutations=[
                            FileMutation(
                                path="README.md",
                                before_content="# App\n",
                                after_content="# App\nInstall instructions.\n",
                            )
                        ],
                    ),
                ],
            )

            rep2 = engine.process_session(sess2)
            self.assertEqual(rep2.composed_leases, [])
            self.assertEqual(rep2.slices_detected, [])
            self.assertEqual(len(prop._calls), calls_after_sess1)

            # ------------------------------------------------------------------
            # SESSION 3: Activated Probe Session (touches .kt and EmbeddingEngine)
            # ------------------------------------------------------------------
            sess3 = SessionTrace(
                session_id="sess3_probe",
                agent_kind="antigravity",
                task_prompt="Add EmbeddingEngine initialization to FeedViewModel.kt",
                turns=[
                    NormalizedTurn(
                        turn_index=0,
                        role="user",
                        text="Add EmbeddingEngine initialization to FeedViewModel.kt",
                    ),
                    NormalizedTurn(
                        turn_index=1,
                        role="assistant",
                        reasoning="Reading aar_inspect and applying litert_api from GEMINI.md: com.google.ai.edge.litertlm.EmbeddingEngine.",
                        text="Initialized com.google.ai.edge.litertlm.EmbeddingEngine in FeedViewModel.kt.",
                        tool_calls=[
                            ToolCallRecord(
                                tool_name="read_file",
                                command_or_target=".agents/skills/aar_inspect/SKILL.md",
                                arguments={"Path": ".agents/skills/aar_inspect/SKILL.md"},
                                output="# AAR Bytecode Inspection",
                            )
                        ],
                        file_mutations=[
                            FileMutation(
                                path="app/src/main/FeedViewModel.kt",
                                before_content="class FeedViewModel {}\n",
                                after_content="import com.google.ai.edge.litertlm.EmbeddingEngine\nclass FeedViewModel { val e = EmbeddingEngine() }\n",
                            )
                        ],
                    ),
                ],
            )

            rep3 = engine.process_session(sess3)
            # Both sibling leases (INV and DOM) are composed together!
            self.assertEqual(len(rep3.composed_leases), 2)
            self.assertEqual(len(rep3.reflected_cases), 1)

            # Verify adopted harness in repo_root now permanently contains both INV and DOM wins
            final_harness = engine.current_harness("antigravity")
            self.assertIn(".agents/skills/aar_inspect/SKILL.md", final_harness)
            self.assertIn(".agents/skills/litert_api/SKILL.md", final_harness)
            self.assertIn(".agents/rules/litert_package.md", final_harness)
            self.assertIn("com.google.ai.edge.litertlm", final_harness["GEMINI.md"])
            # Pre-existing untracked user skill is still intact on disk
            self.assertTrue(user_skill.is_file())

            # Verify Leak-Proof INV-Only Continual Improvement Library R_t (.square/library/antigravity/)
            lib = engine.library_for("default", "antigravity")
            self.assertTrue(lib.index.is_file())
            entries = lib.entries()
            self.assertEqual(len(entries), 1)
            entry_dir = lib.entry_dir(entries[0])
            exp_md = (entry_dir / "EXPERIENCE.md").read_text(encoding="utf-8")
            self.assertIn("task_domain: android-kotlin-litert", exp_md)
            self.assertIn("contrast_validation_flag: true", exp_md)
            self.assertIn('".agents/skills/aar_inspect/SKILL.md"', exp_md)
            # Joint INV+DOM skill leak check: DOM skill & DOM rule MUST NOT leak into cross-project library!
            self.assertNotIn("litert_api", exp_md)
            self.assertNotIn("litert_package.md", exp_md)
            self.assertTrue(
                (entry_dir / "harness/.agents/skills/aar_inspect/SKILL.md").is_file()
            )
            self.assertFalse(
                (entry_dir / "harness/.agents/skills/litert_api").exists()
            )
            self.assertFalse(
                (entry_dir / "harness/.agents/rules/litert_package.md").exists()
            )
            # ensure_always_on=False: no empty/partial GEMINI.md stub in library harness snapshot
            self.assertFalse((entry_dir / "harness/GEMINI.md").exists())
            ao_delta = (entry_dir / "ALWAYS_ON_DELTA.md").read_text(encoding="utf-8")
            self.assertIn("aar_inspect", ao_delta)
            self.assertNotIn("com.google.ai.edge.litertlm", ao_delta)

            # Active leases should now be empty (all composed) and stripped from GEMINI.md
            self.assertEqual(engine.lease_store.active_leases(), [])
            gemini_md_after = (repo_root / "GEMINI.md").read_text(encoding="utf-8")
            self.assertNotIn("<!-- SQUARE_LEASE:id=", gemini_md_after)
            self.assertIn("com.google.ai.edge.litertlm", gemini_md_after)

            # Verify repo_root is completely clean of any local `.square/` folder
            self.assertFalse((repo_root / ".square").exists())
            # Verify ~/.square/projects/<slug>/cases/<case_id>/ contains only lean files (no context/ or harnesses/)
            for cdir in engine.cases_dir.iterdir():
                self.assertTrue((cdir / "slice.json").is_file())
                self.assertTrue((cdir / "trajectory.md").is_file())
                self.assertFalse((cdir / "context").exists())
                self.assertFalse((cdir / "harnesses").exists())
                self.assertFalse((cdir / "runs").exists())

    def test_default_cli_loop_analyze_apply_ingest_without_live_workspace(self) -> None:
        """Exercise the standard user-facing CLI lifecycle (`analyze` -> `apply` -> `ingest`)
        with default `live_workspace=False`.
        """
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "GEMINI.md").write_text("# Base Workspace\n", encoding="utf-8")
            sq_home = root / "sq_home"
            prop = ScriptedSquareProposer(audit_dir=sq_home / "audit")

            sess1_jsonl = root / "sess1.jsonl"
            sess1_events = [
                {
                    "step_index": 0,
                    "source": "USER_EXPLICIT",
                    "type": "USER_INPUT",
                    "content": "<USER_REQUEST>\nWire up LiteRT EmbeddingEngine in SearchRepo.kt\n</USER_REQUEST>",
                },
                {
                    "step_index": 1,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "content": "Inspected EmbeddingEngine.",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "name": "run_command",
                            "args": {"CommandLine": "javap -cp classes.jar EmbeddingEngine"},
                        },
                        {
                            "id": "c2",
                            "name": "write_file",
                            "args": {
                                "Path": "app/SearchRepo.kt",
                                "Content": "import com.google.ai.edge.litertlm.EmbeddingEngine\n",
                            },
                        },
                    ],
                },
            ]
            sess1_jsonl.write_text(
                "\n".join(json.dumps(e) for e in sess1_events) + "\n", encoding="utf-8"
            )

            sess2_probe_jsonl = root / "sess2_probe.jsonl"
            sess2_events = [
                {
                    "step_index": 0,
                    "source": "USER_EXPLICIT",
                    "type": "USER_INPUT",
                    "content": "<USER_REQUEST>\nUse litertlm EmbeddingEngine in DetailRepo.kt\n</USER_REQUEST>",
                },
                {
                    "step_index": 1,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "content": "Used aar_inspect and litert_api.",
                    "tool_calls": [
                        {
                            "id": "p1",
                            "name": "read_file",
                            "args": {"Path": ".agents/skills/aar_inspect/SKILL.md"},
                        },
                        {
                            "id": "p2",
                            "name": "read_file",
                            "args": {"Path": ".agents/skills/litert_api/SKILL.md"},
                        },
                        {
                            "id": "p3",
                            "name": "write_file",
                            "args": {
                                "Path": "app/DetailRepo.kt",
                                "Content": "class DetailRepo {}\n",
                            },
                        },
                    ],
                },
            ]
            sess2_probe_jsonl.write_text(
                "\n".join(json.dumps(e) for e in sess2_events) + "\n", encoding="utf-8"
            )

            def _fake_make_engine(args):
                return SquareEngine(
                    repo_root=Path(args.repo).resolve(),
                    proposer=prop,
                    substrate="antigravity",
                    library_root=sq_home / "library",
                    square_root=sq_home / "project",
                    use_library=not bool(getattr(args, "no_library", False)),
                )

            with patch("square.cli._make_engine", side_effect=_fake_make_engine):
                # 1. `square analyze` creates AWAITING_TRIAL candidates without modifying repo
                rc_an = cli.main(
                    ["--repo", str(repo), "analyze", str(sess1_jsonl), "--no-glow"]
                )
                self.assertEqual(rc_an, 0)
                self.assertEqual(
                    (repo / "GEMINI.md").read_text(encoding="utf-8"), "# Base Workspace\n"
                )
                self.assertFalse((repo / ".agents/skills/aar_inspect").exists())

                # 2. `square apply` promotes AWAITING_TRIAL -> ACTIVE and materializes native files
                rc_ap = cli.main(["--repo", str(repo), "apply"])
                self.assertEqual(rc_ap, 0)
                self.assertIn(
                    "<!-- SQUARE_LEASE:id=",
                    (repo / "GEMINI.md").read_text(encoding="utf-8"),
                )
                self.assertTrue((repo / ".agents/skills/aar_inspect/SKILL.md").is_file())
                self.assertTrue((repo / ".agents/skills/litert_api/SKILL.md").is_file())

                # 3. `square ingest` (default probe-only, live_workspace=False) probes, composes, and reflects!
                rc_in = cli.main(["--repo", str(repo), "ingest", str(sess2_probe_jsonl)])
                self.assertEqual(rc_in, 0)

            # Lease tags stripped; permanent harness adopted in repo; library contains ONLY INV skill!
            gm_final = (repo / "GEMINI.md").read_text(encoding="utf-8")
            self.assertNotIn("<!-- SQUARE_LEASE:id=", gm_final)
            self.assertIn("com.google.ai.edge.litertlm", gm_final)
            self.assertTrue((repo / ".agents/skills/aar_inspect/SKILL.md").is_file())
            self.assertTrue((repo / ".agents/skills/litert_api/SKILL.md").is_file())

            lib_idx = sq_home / "library" / "antigravity" / "INDEX.md"
            self.assertTrue(lib_idx.is_file())
            harnesses_dir = sq_home / "library" / "antigravity" / "harnesses"
            case_entries = list(harnesses_dir.iterdir())
            self.assertEqual(len(case_entries), 1)
            self.assertTrue(
                (case_entries[0] / "harness/.agents/skills/aar_inspect/SKILL.md").is_file()
            )
            self.assertFalse(
                (case_entries[0] / "harness/.agents/skills/litert_api").exists()
            )

    def test_staggered_inv_first_then_dom_second_probe_composition_preserves_inv(self) -> None:
        """Verify ready_leases compose asynchronously when INV activates in Session 2 and DOM
        activates in Session 3, rebasing DOM onto live_base_tree without wiping INV.
        """
        class StaggeredProposer(ScriptedSquareProposer):
            def call(self, mission, context_dir, label, **kwargs):
                reply = super().call(mission, context_dir, label, **kwargs)
                if ".inv1." in label:
                    reply.text = (
                        "<notes>INV aar_inspect</notes>\n"
                        '<trigger>{"path_globs": [], "command_regex": "\\\\bjavap\\\\b", "cue_keywords": []}</trigger>'
                    )
                elif ".dom1." in label:
                    reply.text = (
                        "<notes>DOM litert_api</notes>\n"
                        '<trigger>{"path_globs": ["**/FeedViewModel.kt"], "command_regex": "", "cue_keywords": []}</trigger>'
                    )
                return reply

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "GEMINI.md").write_text("# Instructions\n", encoding="utf-8")
            prop = StaggeredProposer()
            engine = SquareEngine(
                repo_root=repo,
                proposer=prop,
                square_root=root / "sq",
                library_root=root / "lib",
            )

            sess1 = SessionTrace(
                session_id="s1",
                agent_kind="antigravity",
                task_prompt="Initial friction",
                turns=[NormalizedTurn(turn_index=0, role="user", text="Initial friction")],
            )
            engine.analyze_session(sess1)
            applied = engine.apply_case_leases()
            self.assertEqual(len(applied), 2)

            # Session 2 triggers ONLY INV (`javap` command, no `FeedViewModel.kt`)
            sess2_inv_only = SessionTrace(
                session_id="s2_inv",
                agent_kind="antigravity",
                task_prompt="Inspect classes.jar with javap",
                turns=[
                    NormalizedTurn(turn_index=0, role="user", text="Inspect classes.jar"),
                    NormalizedTurn(
                        turn_index=1,
                        role="assistant",
                        tool_calls=[
                            ToolCallRecord(
                                tool_name="read_file",
                                command_or_target=".agents/skills/aar_inspect/SKILL.md",
                            ),
                            ToolCallRecord(
                                tool_name="run_command",
                                command_or_target="javap -cp classes.jar Foo",
                            ),
                        ],
                    ),
                ],
            )
            rep2 = engine.process_session(sess2_inv_only)
            self.assertEqual(len(rep2.composed_leases), 1)
            self.assertTrue(rep2.composed_leases[0].endswith("_inv"))
            self.assertEqual(len(rep2.reflected_cases), 1)
            # DOM lease is still ACTIVE with unrelated_sessions_seen == 1
            rem_active = engine.lease_store.active_leases()
            self.assertEqual(len(rem_active), 1)
            self.assertEqual(rem_active[0].dimension, "DOM")
            self.assertEqual(rem_active[0].unrelated_sessions_seen, 1)

            # Session 3 triggers DOM (`FeedViewModel.kt`) -> composes DOM onto live_base_tree without wiping INV!
            sess3_dom_only = SessionTrace(
                session_id="s3_dom",
                agent_kind="antigravity",
                task_prompt="Edit FeedViewModel.kt",
                turns=[
                    NormalizedTurn(turn_index=0, role="user", text="Edit FeedViewModel.kt"),
                    NormalizedTurn(
                        turn_index=1,
                        role="assistant",
                        tool_calls=[
                            ToolCallRecord(
                                tool_name="read_file",
                                command_or_target=".agents/skills/litert_api/SKILL.md",
                            )
                        ],
                        file_mutations=[
                            FileMutation(
                                path="app/FeedViewModel.kt",
                                before_content="",
                                after_content="class FeedViewModel {}\n",
                            )
                        ],
                    ),
                ],
            )
            rep3 = engine.process_session(sess3_dom_only)
            self.assertEqual(len(rep3.composed_leases), 1)
            self.assertTrue(rep3.composed_leases[0].endswith("_dom"))
            # DOM-only batch skips run_reflect() completely!
            self.assertEqual(rep3.reflected_cases, [])

            # Both INV (`aar_inspect`) and DOM (`litert_api` + `litert_package.md`) survive in repo!
            final_h = engine.current_harness("antigravity")
            self.assertIn(".agents/skills/aar_inspect/SKILL.md", final_h)
            self.assertIn(".agents/skills/litert_api/SKILL.md", final_h)
            self.assertIn(".agents/rules/litert_package.md", final_h)
            self.assertIn("aar_inspect", final_h["GEMINI.md"])
            self.assertIn("com.google.ai.edge.litertlm", final_h["GEMINI.md"])

    def test_no_library_flag_and_inv_only_library_mounting(self) -> None:
        """Verify library context mounts strictly for INV when use_library=True, and is suppressed
        for both INV and DOM when use_library=False (`--no-library`).
        """
        mounted_by_label: dict[str, bool] = {}

        class InspectContextProposer(ScriptedSquareProposer):
            def call(self, mission, context_dir, label, **kwargs):
                ctx = Path(context_dir) if context_dir else Path(".")
                mounted_by_label[label] = (ctx / "library" / "INDEX.md").is_file()
                return super().call(mission, context_dir, label, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "GEMINI.md").write_text("# Instructions\n", encoding="utf-8")
            lib_root = root / "lib"

            # Seed an existing entry into library_root / "antigravity"
            seed_engine = SquareEngine(
                repo_root=repo,
                proposer=InspectContextProposer(),
                square_root=root / "sq1",
                library_root=lib_root,
                use_library=True,
            )
            lib = seed_engine.library_for("default", "antigravity")
            lib.add(
                case_id="case_seed_inv",
                harness={
                    ".agents/skills/seed_tool/SKILL.md": "---\nname: seed_tool\ndescription: Seed\n---\n"
                },
                why="kept -> seed_tool",
                label="compose_inv",
                experience={
                    "task_domain": "python-cli",
                    "deficiency_type": "INV",
                    "trajectory_differential_summary": "Saved 3 turns.",
                    "cue": "When running CLI checks",
                    "lesson": "Use seed_tool.",
                    "evidence": "4 turns -> 1 turn",
                    "confidence": "high",
                },
                applied_components=[".agents/skills/seed_tool/SKILL.md"],
            )

            trace = SessionTrace(
                session_id="s_lib_check",
                agent_kind="antigravity",
                task_prompt="Check library mounting",
                turns=[NormalizedTurn(turn_index=0, role="user", text="Check")],
            )

            # 1. Default use_library=True: INV sees context/library/INDEX.md, DOM does NOT!
            seed_engine.analyze_session(trace)
            inv_warm = next(v for k, v in mounted_by_label.items() if ".inv1." in k)
            dom_warm = next(v for k, v in mounted_by_label.items() if ".dom1." in k)
            self.assertTrue(inv_warm)
            self.assertFalse(dom_warm)

            # 2. Cold benchmark mode (`use_library=False` / `--no-library`): neither INV nor DOM sees library!
            mounted_by_label.clear()
            cold_engine = SquareEngine(
                repo_root=repo,
                proposer=InspectContextProposer(),
                square_root=root / "sq2",
                library_root=lib_root,
                use_library=False,
            )
            cold_engine.analyze_session(trace)
            inv_cold = next(v for k, v in mounted_by_label.items() if ".inv1." in k)
            dom_cold = next(v for k, v in mounted_by_label.items() if ".dom1." in k)
            self.assertFalse(inv_cold)
            self.assertFalse(dom_cold)


class TestSubstrateTranscriptParsersAndCLI(unittest.TestCase):
    def test_real_antigravity_transcript_parsing_and_cli_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Simulate real Antigravity brain directory layout:
            # <brain>/<conv-id>/.system_generated/logs/transcript.jsonl
            conv_id = "4c8b3e7e-1a99-48d3-9a8c-dd5cc78fe8bd"
            logs_dir = root / "brain" / conv_id / ".system_generated" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            transcript_path = logs_dir / "transcript.jsonl"

            events = [
                {
                    "step_index": 0,
                    "source": "USER_EXPLICIT",
                    "type": "USER_INPUT",
                    "content": (
                        "<USER_REQUEST>\nUpdate Config.kt\n</USER_REQUEST>\n"
                        "<ADDITIONAL_METADATA>\nActive Workspaces:\n- "
                        + str(root).replace("\\", "/")
                        + "\n</ADDITIONAL_METADATA>"
                    ),
                },
                {
                    "step_index": 1,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "thinking": "Running command and writing Config.kt.",
                    "content": "Updated Config.kt.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "name": "run_command",
                            # Doubly-JSON-encoded string inside args, as in real AGY transcripts
                            "args": {
                                "CommandLine": json.dumps("javap com.example.Missing"),
                                "WaitMsBeforeAsync": json.dumps(5000),
                            },
                        },
                        {
                            "id": "call_2",
                            "name": "write_file",
                            "args": {
                                "Path": json.dumps("src/Config.kt"),
                                "Content": json.dumps("object Config {}\n"),
                            },
                        },
                    ],
                },
                # Consecutive GENERIC steps holding the tool outputs for step_index 1
                {
                    "step_index": 2,
                    "source": "TOOL",
                    "type": "GENERIC",
                    "content": "Exit code 1\nError: class not found: com.example.Missing",
                },
                {
                    "step_index": 3,
                    "source": "TOOL",
                    "type": "GENERIC",
                    "content": "Created file src/Config.kt",
                },
            ]
            transcript_path.write_text(
                "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
            )

            sub, trace = parse_session_trace(transcript_path)
            self.assertEqual(sub.name, "antigravity")
            self.assertEqual(trace.agent_kind, "antigravity")
            self.assertEqual(trace.session_id, conv_id)
            self.assertEqual(trace.task_prompt, "Update Config.kt")
            self.assertEqual(trace.workspace_root, str(root).replace("\\", "/"))
            self.assertEqual(len(trace.turns), 2)
            t1 = trace.turns[1]
            self.assertEqual(len(t1.tool_calls), 2)
            self.assertEqual(t1.tool_calls[0].command_or_target, "javap com.example.Missing")
            self.assertTrue(t1.tool_calls[0].is_error)
            self.assertEqual(t1.tool_calls[0].exit_code, 1)
            self.assertEqual(len(t1.file_mutations), 1)
            self.assertEqual(t1.file_mutations[0].path, "src/Config.kt")

            # Verify CLI defaults to antigravity without requiring --substrate or --domain
            repo_dir = root / "workspace"
            repo_dir.mkdir(parents=True, exist_ok=True)
            rc_status = cli.main(["--repo", str(repo_dir), "status"])
            self.assertEqual(rc_status, 0)
            self.assertFalse((repo_dir / "GEMINI.md").exists())

            # Verify _iter_watch_transcripts ignores logs/chunks/transcript/0000000*.jsonl
            chunks_dir = logs_dir / "chunks" / "transcript"
            chunks_dir.mkdir(parents=True, exist_ok=True)
            (chunks_dir / "00000000.jsonl").write_text("{}\n", encoding="utf-8")
            (logs_dir / "transcript_full.jsonl").write_text("{}\n", encoding="utf-8")
            found = cli._iter_watch_transcripts(root / "brain")
            self.assertEqual(found, [transcript_path])

            # Verify --latest discovers the newest transcript belonging to `root`
            latest = cli._find_latest_repo_transcript(root / "brain", root)
            self.assertEqual(latest, transcript_path)
            rc_latest = cli.main(["--repo", str(root), "--latest", "--watch-dir", str(root / "brain")])
            self.assertEqual(rc_latest, 0)


if __name__ == "__main__":
    unittest.main()
