"""Tests for `square/tree.py`, `square/library.py`, and `square/substrates/`.

Verifies:
- Native substrate `SurfaceSpec` validation across all 4 substrates (`antigravity`, `codex`, `opencode`, `claude`)
- `autotrigger()` skill trigger line injection per substrate with natural skill names
- `always_on_max` cap and `reject_empty_always_on` enforcement
- `validate_dimension_scope()` enforcing disjoint `INV` vs. `DOM` component ownership (`c1..c8`)
- `apply_tree()` preserving pre-existing untracked user skills on disk when adopting a composed harness
- `Library` unified Continual Improvement Library R_t (`INDEX.md` + `harnesses/<case_id>/EXPERIENCE.md`), YAML frontmatter, and Strict Evidence Filter Rule (`NO_ENTRY`)
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from square import tree
from square.library import Library
from square.substrates import (
    AGY_SURFACE,
    CLAUDE_SURFACE,
    CODEX_SURFACE,
    OPENCODE_SURFACE,
    get_substrate,
)
from square.substrates.base import record_square_managed_components


class TestSubstratesAndTree(unittest.TestCase):
    def test_all_four_substrates_default_trees_validate(self) -> None:
        for name in ("antigravity", "codex", "opencode", "claude"):
            sub = get_substrate(name)
            surf = sub.surface()
            base = sub.default_tree()
            census = tree.validate(surf, base)
            self.assertEqual(census["skills"], 0)
            self.assertEqual(census["scripts"], 0)
            self.assertLess(census["always_on_chars"], surf.always_on_max)

    def test_autotrigger_and_natural_skill_names_across_surfaces(self) -> None:
        # 1. Antigravity auto-discovers skills via frontmatter description; no GEMINI.md trigger line required
        sub_agy = get_substrate("antigravity")
        t_agy = sub_agy.default_tree()
        t_agy[f"{AGY_SURFACE.skill_dir}/elicit_ux_spec/SKILL.md"] = (
            "---\n"
            "name: elicit_ux_spec\n"
            "description: Elicit UX layout constraints from user before coding\n"
            "---\n"
            "# Elicit Spec\nAsk 3 questions first.\n"
        )
        self.assertEqual(tree.autotrigger(AGY_SURFACE, t_agy), [])
        self.assertNotIn("elicit_ux_spec", t_agy["GEMINI.md"])
        census_agy = tree.validate(AGY_SURFACE, t_agy)
        self.assertEqual(census_agy["skills"], 1)

        # 2. Substrates with require_skill_triggers_in_always_on=True enforce and autotrigger
        for surf in (CODEX_SURFACE, CLAUDE_SURFACE, OPENCODE_SURFACE):
            sub = get_substrate(surf.name)
            t = sub.default_tree()
            skill_rel = f"{surf.skill_dir}/elicit_ux_spec/SKILL.md"
            t[skill_rel] = (
                "---\n"
                "name: elicit_ux_spec\n"
                "description: Elicit UX layout constraints from user before coding\n"
                "---\n"
                "# Elicit Spec\nAsk 3 questions first.\n"
            )
            with self.assertRaises(ValueError) as ctx:
                tree.validate(surf, t)
            self.assertIn("is never named in the always-on text", str(ctx.exception))

            repaired = tree.autotrigger(surf, t)
            self.assertEqual(repaired, ["elicit_ux_spec"])
            self.assertIn("elicit_ux_spec", t[surf.autotrigger_file])
            census = tree.validate(surf, t)
            self.assertEqual(census["skills"], 1)

    def test_read_clean_workspace_tree_ignores_third_party_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "GEMINI.md").write_text("# Instructions\n", encoding="utf-8")

            # Unmanaged 3rd-party skill (e.g. Anthropic frontend-design)
            third_party = repo / ".agents" / "skills" / "frontend-design" / "SKILL.md"
            third_party.parent.mkdir(parents=True, exist_ok=True)
            third_party.write_text(
                "---\nname: frontend-design\ndescription: Anthropic skill\n---\n# UI\n",
                encoding="utf-8",
            )

            # Square-managed skill recorded via record_square_managed_components
            managed = repo / ".agents" / "skills" / "spec-elicitation" / "SKILL.md"
            managed.parent.mkdir(parents=True, exist_ok=True)
            managed.write_text(
                "---\nname: spec-elicitation\ndescription: Square skill\n---\n# Spec\n",
                encoding="utf-8",
            )
            record_square_managed_components(repo, [".agents/skills/spec-elicitation/SKILL.md"])

            sub = get_substrate("antigravity")
            clean_tree = sub.read_workspace_tree(repo)
            self.assertNotIn(".agents/skills/frontend-design/SKILL.md", clean_tree)
            self.assertIn(".agents/skills/spec-elicitation/SKILL.md", clean_tree)

    def test_always_on_cap_and_reject_empty_enforced(self) -> None:
        t = {"GEMINI.md": "x" * 100_500}
        with self.assertRaises(ValueError) as ctx:
            tree.validate(AGY_SURFACE, t)
        self.assertIn("over the 100000 cap", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx2:
            tree.validate(AGY_SURFACE, {"GEMINI.md": "   \n"})
        self.assertIn("is empty", str(ctx2.exception))

    def test_script_compile_and_ref_validation(self) -> None:
        t = {"GEMINI.md": "# Instructions\nRun `python scripts/missing_helper.py` first.\n"}
        with self.assertRaises(ValueError) as ctx:
            tree.validate(AGY_SURFACE, t)
        self.assertIn("invokes `scripts/missing_helper.py`", str(ctx.exception))

        t["scripts/missing_helper.py"] = "def broken(:\n    pass\n"
        with self.assertRaises(ValueError) as ctx2:
            tree.validate(AGY_SURFACE, t)
        self.assertIn("does not compile", str(ctx2.exception))

        t["scripts/missing_helper.py"] = "import sys\nprint('ok')\n"
        census = tree.validate(AGY_SURFACE, t)
        self.assertEqual(census["scripts"], 1)

    def test_dimension_scope_orthogonality_on_antigravity_and_opencode(self) -> None:
        # 1. Test on AGY_SURFACE (default substrate with .agents/rules, .agents/hooks.json, scripts; sub_agents disabled)
        base_agy = {"GEMINI.md": "# Project Instructions\n"}
        inv_agy = dict(base_agy)
        inv_agy["scripts/inspect_jar.py"] = "print('inspect')\n"
        inv_agy[".agents/hooks.json"] = (
            '{"hooks": {"PostToolUse": [{"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "python scripts/inspect_jar.py"}]}]}}\n'
        )
        inv_agy[".agents/skills/aar_inspect/SKILL.md"] = (
            "---\nname: aar_inspect\ndescription: Inspect AAR\n---\n"
        )
        inv_agy["GEMINI.md"] += "- When inspecting AARs, read .agents/skills/aar_inspect/SKILL.md and follow it.\n"
        tree.validate_dimension_scope(AGY_SURFACE, "INV", base_agy, inv_agy)
        tree.validate(AGY_SURFACE, inv_agy)

        # AGY_SURFACE forbids sub_agents/*/AGENT.md even for INV (allow_subagents=False), whereas CODEX_SURFACE allows it
        bad_sub_agy = dict(base_agy)
        bad_sub_agy["sub_agents/verifier/AGENT.md"] = (
            "---\nname: verifier\ndescription: Verify builds\n---\nCheck output.\n"
        )
        with self.assertRaises(ValueError):
            tree.validate_dimension_scope(AGY_SURFACE, "INV", base_agy, bad_sub_agy)
        with self.assertRaises(ValueError):
            tree.validate(AGY_SURFACE, bad_sub_agy)

        base_codex = {"AGENTS.md": "# Instructions\n"}
        inv_codex = dict(base_codex)
        inv_codex["sub_agents/verifier/AGENT.md"] = (
            "---\nname: verifier\ndescription: Verify builds\n---\nCheck output.\n"
        )
        tree.validate_dimension_scope(CODEX_SURFACE, "INV", base_codex, inv_codex)
        tree.validate(CODEX_SURFACE, inv_codex)

        # INV cannot create a domain rule in .agents/rules/
        bad_inv = dict(inv_agy)
        bad_inv[".agents/rules/litert_contract.md"] = "# LiteRT Rule\n"
        with self.assertRaises(ValueError) as ctx:
            tree.validate_dimension_scope(AGY_SURFACE, "INV", base_agy, bad_inv)
        self.assertIn("INV editor cannot modify `.agents/rules/litert_contract.md`", str(ctx.exception))

        # DOM can create natural-named skills, .agents/rules/*.md, and update GEMINI.md,
        # but cannot touch scripts/, sub_agents/, or .agents/hooks.json
        dom_agy = dict(base_agy)
        dom_agy[".agents/skills/litert_api/SKILL.md"] = (
            "---\nname: litert_api\ndescription: LiteRT API\n---\n"
        )
        dom_agy[".agents/rules/litert_contract.md"] = (
            "# LiteRT Contract\nUse `com.google.ai.edge.litertlm.EmbeddingEngine`.\n"
        )
        dom_agy["GEMINI.md"] += "- When using LiteRT, read .agents/skills/litert_api/SKILL.md and follow it.\n"
        tree.validate_dimension_scope(AGY_SURFACE, "DOM", base_agy, dom_agy)
        tree.validate(AGY_SURFACE, dom_agy)

        for forbidden_dom_path in (
            "scripts/hack.py",
            "sub_agents/reviewer/AGENT.md",
            ".agents/hooks.json",
        ):
            bad_dom = dict(dom_agy)
            bad_dom[forbidden_dom_path] = "x\n"
            with self.assertRaises(ValueError) as ctx2:
                tree.validate_dimension_scope(AGY_SURFACE, "DOM", base_agy, bad_dom)
            self.assertIn(f"DOM editor cannot modify `{forbidden_dom_path}`", str(ctx2.exception))

        # Merge parallel INV and DOM edits cleanly on AGY_SURFACE
        merged_agy = tree.merge_parallel_trees(AGY_SURFACE, base_agy, inv_agy, dom_agy)
        self.assertIn("scripts/inspect_jar.py", merged_agy)
        self.assertIn(".agents/skills/aar_inspect/SKILL.md", merged_agy)
        self.assertIn(".agents/skills/litert_api/SKILL.md", merged_agy)
        self.assertIn(".agents/rules/litert_contract.md", merged_agy)
        tree.validate(AGY_SURFACE, merged_agy)

        # 2. Test on multi-file OPENCODE_SURFACE (LongTermMEMORY.md vs tool_guidance.md)
        sub_oc = get_substrate("opencode")
        base_oc = sub_oc.default_tree()
        bad_inv_oc = dict(base_oc)
        bad_inv_oc["LongTermMEMORY.md"] += "- Domain fact\n"
        with self.assertRaises(ValueError):
            tree.validate_dimension_scope(OPENCODE_SURFACE, "INV", base_oc, bad_inv_oc)

        bad_dom_oc = dict(base_oc)
        bad_dom_oc["tool_descriptions/tool_guidance.md"] += "- Tool rule\n"
        with self.assertRaises(ValueError):
            tree.validate_dimension_scope(OPENCODE_SURFACE, "DOM", base_oc, bad_dom_oc)

    def test_apply_tree_preserves_untracked_user_skills_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            # User has a pre-existing custom skill on disk not in `base`
            user_skill = repo / ".agents" / "skills" / "my_custom_team_skill" / "SKILL.md"
            user_skill.parent.mkdir(parents=True, exist_ok=True)
            user_skill.write_text("---\nname: my_custom_team_skill\ndescription: Custom\n---\n", encoding="utf-8")

            base = {
                "GEMINI.md": "# Instructions\n- Read .agents/skills/old_leased/SKILL.md\n",
                ".agents/skills/old_leased/SKILL.md": "---\nname: old_leased\ndescription: Old\n---\n",
            }
            tree.write_tree(AGY_SURFACE, base, repo, stubs=False)
            # Re-create user skill in case write_tree wiped it during initial fixture setup
            user_skill.parent.mkdir(parents=True, exist_ok=True)
            user_skill.write_text("---\nname: my_custom_team_skill\ndescription: Custom\n---\n", encoding="utf-8")

            new_tree = {
                "GEMINI.md": "# Instructions\n- Read .agents/skills/adopted_skill/SKILL.md\n",
                ".agents/skills/adopted_skill/SKILL.md": "---\nname: adopted_skill\ndescription: New\n---\n",
            }
            tree.apply_tree(AGY_SURFACE, base, new_tree, repo)

            # Adopted skill is written, old base skill removed, pre-existing untracked user skill preserved!
            self.assertTrue((repo / ".agents/skills/adopted_skill/SKILL.md").is_file())
            self.assertFalse((repo / ".agents/skills/old_leased/SKILL.md").exists())
            self.assertTrue(user_skill.is_file())

    def test_library_unified_rt_frontmatter_and_strict_evidence_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lib = Library(root=Path(tmp), surface=AGY_SURFACE)
            base = {"GEMINI.md": "# Project Instructions\n"}

            # 1. Strict Evidence Filter Rule: NO_ENTRY writes nothing
            no_entry_res = lib.add(
                case_id="case_no_delta",
                harness=base,
                why="kept_base -> no difference",
                label="compose_1",
                experience={"raw": "NO_ENTRY", "no_entry": True},
            )
            self.assertIsNone(no_entry_res)
            self.assertEqual(lib.entries(), [])

            # 2. Valid contrast-validated experience writes YAML frontmatter and updates INDEX.md
            adopted = dict(base)
            adopted[".agents/skills/aar_inspect/SKILL.md"] = (
                "---\nname: aar_inspect\ndescription: Inspect AAR\n---\n"
            )
            adopted["GEMINI.md"] += "- When inspecting AARs, read .agents/skills/aar_inspect/SKILL.md and follow it.\n"
            entry_dir = lib.add(
                case_id="case_litert_01",
                harness=adopted,
                why="kept -> GEMINI.md & .agents/skills/aar_inspect/SKILL.md",
                label="compose_1",
                experience={
                    "edits": "component: GEMINI.md\nverdict: helped",
                    "task_domain": "android-kotlin-sdk",
                    "deficiency_type": "INV+DOM: Mechanical Thrash + Domain Knowledge Gap",
                    "trajectory_differential_summary": "Base took 5 javap/jar turns with 2 errors; probe resolved in 1 turn.",
                    "cue": "When integrating an Android AAR with non-obvious class packages",
                    "lesson": "Provide an aar_inspect skill and record verified package paths in GEMINI.md.",
                    "evidence": "5 turns -> 1 turn on EmbeddingEngine",
                    "confidence": "high",
                },
                applied_components=["GEMINI.md", ".agents/skills/aar_inspect/SKILL.md"],
            )
            self.assertIsNotNone(entry_dir)
            self.assertEqual(lib.entries(), ["case_litert_01"])

            exp_text = (entry_dir / "EXPERIENCE.md").read_text(encoding="utf-8")
            self.assertIn("task_id: case_litert_01", exp_text)
            self.assertIn("task_domain: android-kotlin-sdk", exp_text)
            self.assertIn("contrast_validation_flag: true", exp_text)
            self.assertIn('".agents/skills/aar_inspect/SKILL.md"', exp_text)
            self.assertIn("## Transferable lesson", exp_text)

            index_text = lib.index.read_text(encoding="utf-8")
            self.assertIn("case_litert_01", index_text)
            self.assertIn("android-kotlin-sdk", index_text)
            self.assertIn("Base took 5 javap/jar turns", index_text)

    def test_context_mission_summarizes_large_skills(self) -> None:
        from square import context as ctx_mod

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            harness_dir = root / "src_harness"
            skill_file = harness_dir / ".agents/skills/frontend_design/SKILL.md"
            skill_file.parent.mkdir(parents=True, exist_ok=True)
            large_body = (
                "---\n"
                "name: frontend_design\n"
                "description: Create distinctive frontend interfaces\n"
                "license: MIT\n"
                "---\n"
                "# Frontend Design\n\n"
                "## Typography\n\n"
                + ("Detailed design guidance line.\n" * 60)
            )
            skill_file.write_text(large_body, encoding="utf-8")
            (harness_dir / "GEMINI.md").write_text("# Instructions\n", encoding="utf-8")

            ctree = ctx_mod.build(
                root / "ctx",
                "case_01",
                "# Task\nBuild UI",
                harness_dir=harness_dir,
            )
            m_text = ctx_mod.mission(ctree, job="# Job\nImprove harness")
            self.assertIn("on-demand skill summary", m_text)
            self.assertIn("Create distinctive frontend interfaces", m_text)
            self.assertIn("`# Frontend Design`", m_text)

    def test_current_harness_excludes_third_party_skills_in_analyze_mode(self) -> None:
        from square.engine import SquareEngine
        from square.proposer import Proposer

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            sq_dir = Path(tmp) / "sq_dir"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / "GEMINI.md").write_text("# Instructions\n", encoding="utf-8")
            third_party = repo / ".agents/skills/litert-lm/SKILL.md"
            third_party.parent.mkdir(parents=True, exist_ok=True)
            third_party.write_text(
                "---\nname: litert-lm\ndescription: LiteRT-LM\nauthor: Google LLC\n---\n# Guide\n",
                encoding="utf-8",
            )
            managed = repo / ".agents/skills/sq-skill/SKILL.md"
            managed.parent.mkdir(parents=True, exist_ok=True)
            managed.write_text(
                "---\nname: sq-skill\ndescription: Managed\n---\n<!-- square-managed -->\n# Managed\n",
                encoding="utf-8",
            )

            engine = SquareEngine(
                repo_root=repo,
                proposer=Proposer(),
                square_root=sq_dir,
                substrate="antigravity",
                live_workspace=False,
            )
            h = engine.current_harness("antigravity")
            self.assertNotIn(".agents/skills/litert-lm/SKILL.md", h)
            self.assertIn(".agents/skills/sq-skill/SKILL.md", h)

    def test_agy_surface_enforces_skill_name_match_and_forbids_subagents(self) -> None:
        base = {"GEMINI.md": "# Instructions\n"}

        # 1. Missing `name:` frontmatter is rejected on AGY_SURFACE
        missing_name = dict(base)
        missing_name[".agents/skills/check_apk/SKILL.md"] = (
            "---\ndescription: Check APK signatures\n---\n# Check APK\n"
        )
        with self.assertRaises(ValueError) as ctx1:
            tree.validate(AGY_SURFACE, missing_name)
        self.assertIn("needs frontmatter `name: check_apk`", str(ctx1.exception))

        # 2. Mismatching `name:` vs directory is rejected on AGY_SURFACE
        wrong_name = dict(base)
        wrong_name[".agents/skills/check_apk/SKILL.md"] = (
            "---\nname: apk_checker\ndescription: Check APK signatures\n---\n# Check APK\n"
        )
        with self.assertRaises(ValueError) as ctx2:
            tree.validate(AGY_SURFACE, wrong_name)
        self.assertIn("matching its directory", str(ctx2.exception))

        # 3. `sub_agents/*/AGENT.md` is rejected by `is_allowed()` and `validate()` on AGY_SURFACE
        self.assertFalse(tree.is_allowed(AGY_SURFACE, "sub_agents/helper/AGENT.md"))
        with self.assertRaises(ValueError) as ctx3:
            tree.validate(
                AGY_SURFACE,
                {
                    "GEMINI.md": "# Instructions\n",
                    "sub_agents/helper/AGENT.md": "---\ndescription: Helper\n---\n",
                },
            )
        self.assertIn("sub_agents are not available on this deployment", str(ctx3.exception))

    def test_skill_relative_script_reference_accepted_when_bundled_script_exists(self) -> None:
        t = {
            "GEMINI.md": "# Instructions\n",
            ".agents/skills/foo/SKILL.md": (
                "---\nname: foo\ndescription: Foo workflow\n---\n"
                "Run `python3 scripts/helper.py --check` from the skill directory.\n"
            ),
        }
        # Fails when neither repo scripts/helper.py nor .agents/skills/foo/scripts/helper.py exists
        with self.assertRaises(ValueError) as ctx:
            tree.validate(AGY_SURFACE, t)
        self.assertIn("invokes `scripts/helper.py`", str(ctx.exception))

        # Succeeds when bundled under .agents/skills/foo/scripts/helper.py
        t[".agents/skills/foo/scripts/helper.py"] = "print('bundled ok')\n"
        census = tree.validate(AGY_SURFACE, t)
        self.assertEqual(census["skills"], 1)
        self.assertEqual(census["scripts"], 1)

    def test_rebase_candidate_tree_preserves_intermediate_sibling_edits(self) -> None:
        old_base = {"GEMINI.md": "# Base\n- Core rule\n"}
        # Sibling INV already composed onto live_base in Session 2:
        live_base = {
            "GEMINI.md": "# Base\n- Core rule\n- Use scripts/verify.py before commit\n",
            "scripts/verify.py": "print('verify')\n",
            ".agents/skills/inv_verify/SKILL.md": "---\nname: inv_verify\ndescription: Verify\n---\n",
        }
        # Sibling DOM was originally proposed against old_base in Session 1:
        dom_cand = {
            "GEMINI.md": "# Base\n- Core rule\n- Domain package is com.example.core\n",
            ".agents/skills/dom_arch/SKILL.md": "---\nname: dom_arch\ndescription: Arch\n---\n",
        }
        rebased = tree.rebase_candidate_tree(AGY_SURFACE, live_base, old_base, dom_cand)
        self.assertIn("scripts/verify.py", rebased)
        self.assertIn(".agents/skills/inv_verify/SKILL.md", rebased)
        self.assertIn(".agents/skills/dom_arch/SKILL.md", rebased)
        self.assertIn("- Use scripts/verify.py before commit", rebased["GEMINI.md"])
        self.assertIn("- Domain package is com.example.core", rebased["GEMINI.md"])

    def test_unmanaged_skills_appear_in_mission_and_remain_absent_from_editable_harness(self) -> None:
        from square import context as ctx_mod
        from square.substrates.base import list_unmanaged_workspace_skills

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "GEMINI.md").write_text("# Instructions\n", encoding="utf-8")
            tp = repo / ".agents/skills/litert-lm/SKILL.md"
            tp.parent.mkdir(parents=True, exist_ok=True)
            tp.write_text(
                "---\nname: litert-lm\ndescription: Official LiteRT-LM Android guide\n---\n# LiteRT\n",
                encoding="utf-8",
            )
            unmanaged = list_unmanaged_workspace_skills(AGY_SURFACE, repo)
            self.assertEqual(len(unmanaged), 1)
            self.assertEqual(unmanaged[0]["name"], "litert-lm")

            sub = get_substrate("antigravity")
            clean_h = sub.read_workspace_tree(repo)
            self.assertNotIn(".agents/skills/litert-lm/SKILL.md", clean_h)

            ctree = ctx_mod.build(
                root / "ctx",
                "case_unmanaged",
                "# Task\nCheck LiteRT",
                surface=AGY_SURFACE,
                harness=clean_h,
                unmanaged_skills=unmanaged,
            )
            self.assertFalse((root / "ctx/harness/.agents/skills/litert-lm/SKILL.md").exists())
            m_text = ctx_mod.mission(ctree, job="# Job\nPropose")
            self.assertIn("Pre-existing Read-Only Workspace Skills", m_text)
            self.assertIn("litert-lm", m_text)
            self.assertIn("Official LiteRT-LM Android guide", m_text)


if __name__ == "__main__":
    unittest.main()
