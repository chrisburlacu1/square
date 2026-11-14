"""Tests for `square/slicer.py` (Deterministic Intra-Session & Cross-Commit Pre-Slicer).

Tests three realistic session transcripts:
1. Trace 1 (Mechanical Thrash): 6 turns running `javap` and `jar tf` to find `EmbeddingEngine`
   signatures -> exit 0 at $T_Y$, surviving at $T_{Y+1}$ -> classified as `MECHANICAL_THRASH`.
2. Trace 2 (Semantic / UI Taste Thrash): 5 turns rewriting `FeedSearch.kt` where each $T_Y^{(i)}$
   compiles cleanly but user prompts at $T_{Y+1}^{(i)}$ force >50% line overwrites ->
   classified as `SEMANTIC_REVERT_INTRA`.
3. Trace 3 (Smooth Session): 10 normal turns with no thrash and 100% survival ->
   zero slices emitted, zero LLM calls.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from square import slicer
from square.schemas import FileMutation, NormalizedTurn, SessionTrace, ToolCallRecord


class TestSlicer(unittest.TestCase):
    def test_trace1_mechanical_thrash_javap_litertlm(self) -> None:
        turns = [
            NormalizedTurn(
                turn_index=0,
                role="user",
                text="Wire up EmbeddingEngine in LiteRT-LM for the Android app.",
            ),
            NormalizedTurn(
                turn_index=1,
                role="assistant",
                tool_calls=[
                    ToolCallRecord(
                        tool_name="bash",
                        command_or_target="javap -cp app/libs/litert.jar com.google.ai.EmbeddingEngine",
                        output="Error: class not found: com.google.ai.EmbeddingEngine",
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
                        tool_name="bash",
                        command_or_target="jar tf ~/.gradle/caches/litertlm.aar",
                        output="classes.jar\nAndroidManifest.xml",
                        exit_code=0,
                    )
                ],
            ),
            NormalizedTurn(
                turn_index=3,
                role="assistant",
                tool_calls=[
                    ToolCallRecord(
                        tool_name="bash",
                        command_or_target="unzip -l ~/.gradle/caches/litertlm.aar",
                        output="classes.jar",
                        exit_code=0,
                    )
                ],
            ),
            NormalizedTurn(
                turn_index=4,
                role="assistant",
                tool_calls=[
                    ToolCallRecord(
                        tool_name="bash",
                        command_or_target="javap -cp classes.jar com.google.edge.EmbeddingEngine",
                        output="Error: class not found",
                        exit_code=1,
                        is_error=True,
                    )
                ],
            ),
            NormalizedTurn(
                turn_index=5,
                role="assistant",
                tool_calls=[
                    ToolCallRecord(
                        tool_name="bash",
                        command_or_target="javap -cp classes.jar com.google.ai.edge.litertlm.EmbeddingEngine",
                        output="public final class com.google.ai.edge.litertlm.EmbeddingEngine { public float[] embed(String); }",
                        exit_code=0,
                    )
                ],
                file_mutations=[
                    FileMutation(
                        path="app/src/main/java/com/example/SearchRepo.kt",
                        before_content="class SearchRepo {}\n",
                        after_content="import com.google.ai.edge.litertlm.EmbeddingEngine\nclass SearchRepo { val eng = EmbeddingEngine() }\n",
                    )
                ],
            ),
            NormalizedTurn(
                turn_index=6,
                role="user",
                text="Looks great, thanks!",
            ),
        ]
        trace = SessionTrace(
            session_id="sess_litert_01",
            domain="android",
            task_prompt="Wire up EmbeddingEngine in LiteRT-LM for the Android app.",
            turns=turns,
        )

        slices = slicer.detect_slices(trace)
        self.assertEqual(len(slices), 1)
        s = slices[0]
        self.assertEqual(s.thrash_type, "MECHANICAL_THRASH")
        self.assertEqual(s.t_start, 1)
        self.assertEqual(s.t_y, 5)
        self.assertGreaterEqual(s.error_count, 2)
        self.assertIn("app/src/main/java/com/example/SearchRepo.kt", s.touched_files)

    def test_trace2_semantic_revert_intra_ui_taste_thrash(self) -> None:
        ty_code = "\n".join(
            [
                "package com.example.ui",
                "@Composable",
                "fun FeedSearch() {",
                "    ModalBottomSheet(onDismissRequest = {}) {",
                "        TextField(value = '', onValueChange = {})",
                "        Button(onClick = {}) { Text('Search Modal') }",
                "        LazyColumn { items(10) { Text('Modal Result') } }",
                "    }",
                "}",
            ]
        )
        ty1_code = "\n".join(
            [
                "package com.example.ui",
                "@Composable",
                "fun FeedSearch() {",
                "    TopAppBarSearchBar(query = '', onQueryChange = {})",
                "    FilterChipRow(chips = listOf('All', 'Unread', 'Starred'))",
                "    CompactFeedList(items = emptyList())",
                "}",
            ]
        )

        turns = [
            NormalizedTurn(
                turn_index=0,
                role="user",
                text="Add search to the feed screen in FeedSearch.kt",
            ),
            NormalizedTurn(
                turn_index=1,
                role="assistant",
                text="I implemented a modal bottom sheet search experience.",
                file_mutations=[
                    FileMutation(
                        path="app/src/main/java/com/example/ui/FeedSearch.kt",
                        before_content="package com.example.ui\n",
                        after_content=ty_code,
                        added_lines=ty_code.splitlines(),
                    )
                ],
                tool_calls=[
                    ToolCallRecord(
                        tool_name="bash",
                        command_or_target="./gradlew compileDebugKotlin",
                        output="BUILD SUCCESSFUL",
                        exit_code=0,
                    )
                ],
            ),
            NormalizedTurn(
                turn_index=2,
                role="user",
                text="No, I don't want a modal bottom sheet! Make it an inline top search bar with filter chips.",
            ),
            NormalizedTurn(
                turn_index=3,
                role="assistant",
                text="Rewrote FeedSearch.kt to use an inline top bar with filter chips.",
                file_mutations=[
                    FileMutation(
                        path="app/src/main/java/com/example/ui/FeedSearch.kt",
                        before_content=ty_code,
                        after_content=ty1_code,
                        added_lines=ty1_code.splitlines(),
                    )
                ],
                tool_calls=[
                    ToolCallRecord(
                        tool_name="bash",
                        command_or_target="./gradlew compileDebugKotlin",
                        output="BUILD SUCCESSFUL",
                        exit_code=0,
                    )
                ],
            ),
        ]

        trace = SessionTrace(
            session_id="sess_ui_02",
            domain="android",
            task_prompt="Add search to the feed screen in FeedSearch.kt",
            turns=turns,
        )

        slices = slicer.detect_slices(trace)
        self.assertEqual(len(slices), 1)
        s = slices[0]
        self.assertEqual(s.thrash_type, "SEMANTIC_REVERT_INTRA")
        self.assertEqual(s.t_y, 1)
        self.assertEqual(s.t_y1, 3)
        self.assertLess(s.survival_ratio, 0.50)
        self.assertIn("modal bottom sheet", s.user_nudge_text.lower())

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = slicer.populate_case_workspace(Path(tmp) / "case_ui", trace, s)
            self.assertTrue((case_dir / "slice.json").is_file())
            self.assertTrue((case_dir / "trajectory.md").is_file())
            self.assertFalse((case_dir / "runs").exists())
            self.assertFalse((case_dir / "slice_meta.json").exists())

    def test_trace3_smooth_session_emits_zero_slices(self) -> None:
        turns = [
            NormalizedTurn(turn_index=0, role="user", text="Add a version constant to Config.kt"),
            NormalizedTurn(
                turn_index=1,
                role="assistant",
                text="Added VERSION = '1.2.0' to Config.kt.",
                file_mutations=[
                    FileMutation(
                        path="src/Config.kt",
                        before_content="object Config {}\n",
                        after_content="object Config {\n    const val VERSION = \"1.2.0\"\n}\n",
                    )
                ],
                tool_calls=[
                    ToolCallRecord(
                        tool_name="bash",
                        command_or_target="pytest",
                        output="1 passed",
                        exit_code=0,
                    )
                ],
            ),
            NormalizedTurn(turn_index=2, role="user", text="Perfect!"),
        ]
        trace = SessionTrace(session_id="sess_smooth_03", domain="android", turns=turns)
        slices = slicer.detect_slices(trace)
        self.assertEqual(slices, [])

    def test_distinct_file_reads_with_zero_errors_do_not_trigger_thrash(self) -> None:
        turns = [
            NormalizedTurn(turn_index=0, role="user", text="Check how the four modules work."),
            NormalizedTurn(
                turn_index=1,
                role="assistant",
                tool_calls=[
                    ToolCallRecord(tool_name="read_file", command_or_target="a.py", exit_code=0),
                    ToolCallRecord(tool_name="read_file", command_or_target="b.py", exit_code=0),
                    ToolCallRecord(tool_name="read_file", command_or_target="c.py", exit_code=0),
                    ToolCallRecord(tool_name="read_file", command_or_target="d.py", exit_code=0),
                    ToolCallRecord(tool_name="read_file", command_or_target="e.py", exit_code=0),
                ],
            ),
        ]
        trace = SessionTrace(session_id="sess_reads", turns=turns)
        self.assertEqual(slicer.detect_slices(trace), [])

    def test_render_trace_markdown_prefers_normalized_turns_over_truncated_raw_md(self) -> None:
        huge_read = "line\n" * 2_000
        turns = [
            NormalizedTurn(turn_index=0, role="user", text="Start session"),
            NormalizedTurn(
                turn_index=1,
                role="assistant",
                tool_calls=[
                    ToolCallRecord(
                        tool_name="read_file",
                        command_or_target="HugeFile.kt",
                        output=huge_read,
                        exit_code=0,
                    )
                ],
            ),
            NormalizedTurn(turn_index=450, role="user", text="Late turn after huge read"),
        ]
        trace = SessionTrace(
            session_id="sess_late",
            turns=turns,
            raw_trajectory_md="[USER] Start session\n…(+375483 chars — render truncation)",
        )
        rendered = slicer.render_trace_markdown(
            trace, obs_trunc=4_000, read_obs_trunc=1_200, max_chars=0
        )
        self.assertIn("[USER] (turn 450) Late turn after huge read", rendered)
        self.assertIn("[ACTION] (turn 1) read_file: HugeFile.kt", rendered)
        self.assertNotIn("render truncation", rendered)
        self.assertLess(len(rendered), len(huge_read))


if __name__ == "__main__":
    unittest.main()
