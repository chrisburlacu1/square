HARNESS2 ENGINE ARCHITECTURE BLUEPRINT: DUAL-RECURSION SCALABLE AGENT SCAFFOLDING

1. Executive Technical Overview & Strategic Architectural Foundations

The rapid evolution of Large Language Model (LLM) deployment has exposed a fundamental architectural bottleneck: model-centric fine-tuning and weight optimization are computationally expensive, bounded by static training data cutoffs, and incapable of dynamic online adaptation. Autonomous LLM agent performance depends not merely on the intrinsic parameters of the underlying foundation model, but critically on its execution harness—the runtime scaffolding encompassing system prompts, tool interfaces, memory structures, orchestration rules, and programmatic guardrails. In open-world operational environments characterized by unseen tasks and evolving constraints, agent scaffolding acts as the definitive capability multiplier. Harness2 establishes a strategic paradigm shift from static, weight-based fine-tuning to continuous, harness-centric self-improvement, enabling frozen foundation models to dynamically adapt to complex deployment streams without parametric modification.

+-----------------------------------------------------------------------------------+
| HARNESS2 ENGINE |
| |
| +-----------------------------------------------------------------------------+ |
| | Harnessing-Level Recursion | |
| | (Updates Continual Improvement Harness R_t across task stream N) | |
| +-------------------------------------+---------------------------------------+ |
| | |
| v |
| +-----------------------------------------------------------------------------+ |
| | Task-Level Recursion | |
| | (Propose - Probe - Compose Cycle on Execution Harness H_t per task q_t) | |
| +-------------------------------------+---------------------------------------+ |
| | |
| v |
| +-----------------------------------------------------------------------------+ |
| | FROZEN BASE MODEL | |
| | Agent = Model (M_frozen) + Harness (H_runtime) | |
| +-----------------------------------------------------------------------------+ |
+-----------------------------------------------------------------------------------+

1.1 Open-World Deployment Challenges

Deploying autonomous agents into open-world environments presents two severe execution bottlenecks that invalidate conventional offline search and static validation paradigms:

1. Absence of Ground-Truth Verifiers at Test Time: Open-world deployment tasks arrive dynamically without labeled validation feedback, unit tests, or ground-truth reward models. Traditional Recursive Self-Improvement (RSI) techniques rely on external verifier signals or fixed target outputs; in contrast, real-world deployment requires safely evaluating and updating runtime harnesses using imperfect, stochastic execution traces alone.
2. Task-Specific Overfitting and Noisy Improvement Drift: Modifications tailored to solve a single isolated task frequently fail to generalize to subsequent operational scenarios. Inheriting a highly tailored execution harness directly across shifting task distributions introduces noisy recursive drift, leading to brittle operational rules and degraded performance on novel problems.

Operational Dimension Offline Search & Static Validation Open-World Online Deployment
Verification Signal External unit tests, known labels, offline reward functions Zero ground-truth labels; unverified environment responses
Harness Lifecycle Pre-computed, static, frozen prior to deployment Dynamic, continuous, real-time adaptation per task stream
Generalization Focus Overfits to fixed benchmark splits and static test suites Requires cross-task experience extraction without task drift
Failure Mode Inability to adapt to novel, unseen task requirements Cascading failure from unverified, task-overfitted edits

1.2 The Harness2 Dual-Recursion Paradigm

To solve these open-world bottlenecks, Harness2 formalizes agent execution through the foundational composition equation:

\text{Agent} = \text{Model} + \text{Harness} \quad \implies \quad \mathcal{A}(\cdot \,; \mathcal{M}, \mathcal{H})

where the parameter weights of the underlying base model \mathcal{M} remain strictly frozen, while the runtime scaffolding \mathcal{H} undergoes continuous optimization. Harness2 implements this optimization through a dual-recursion macro-architecture operating across two coupled operational time-scales:

- Task-Level Recursion: Refines the active execution harness \mathcal{H}\_t in real time for a specific task q_t. It operates without ground-truth feedback via a contrastive Propose–Probe–Compose cycle, generating and testing candidate harness modifications to fix identified deficiencies.
- Harnessing-Level Recursion: Operates across the task stream q_1, q_2, \dots, q_N. Rather than passing a highly specific execution harness from task to task, harnessing-level recursion extracts generalizable procedural experience and validated component artifacts from task-level explorations to update a persistent continual improvement harness \mathcal{R}\_t.

  1.3 Strategic Architectural Impact ("So What?" Layer)

By strictly decoupling the frozen executor model \mathcal{M} from an evolving, dual-layer scaffolding (\mathcal{H}, \mathcal{R}), Harness2 eliminates the risk of catastrophic forgetting inherent in model parameter fine-tuning. System engineers can deploy lightweight, high-performing agent scaffolding over proprietary, immutable foundation LLM APIs. The architecture transforms localized execution failures into non-destructive, persistent operational knowledge, ensuring that test-time inference compute scales directly into permanent systemic capability gains without costly task-specific retraining.

1.4 Section Transition

Having established the macro-architectural paradigm of dual-recursion scaffolding, the next section details the concrete, file-level runtime components that constitute the execution harness.

2. Modular Runtime Component Architecture (The Eight-Component Scaffolding)

To enable fine-grained observability, automated debugging, and targeted programmatic intervention, the Harness2 execution harness decomposes the agent's runtime environment into discrete, file-mounted scaffolding primitives. Exposing these primitives as physical files allows automated improvers to perform precise, localized code and prompt diffs rather than opaque full-prompt rewrites.

2.1 Mathematical Decomposition of Execution Scaffolding

Extending the Agentic Harness Engineering (AHE) structure, the active execution harness \mathcal{H} is defined mathematically as an ordered set of K=8 discrete runtime components:

\mathcal{H} = (c_1, c_2, c_3, c_4, c_5, c_6, c_7, c_8)

Each component c_i \in \{1, \dots, 8\} represents a file-mounted asset in the execution workspace, intercepting or constructing specific stages of the agent's runtime loop.

2.2 Comprehensive Component Taxonomy & Runtime Interception Roles

The eight file-mounted components operate across distinct execution scopes, triggers, and file paths:

Component Identifier File Mount Path Activation Trigger & Scope Functional Runtime Definition
C1 System Prompt systemprompt.md Context Construction; mounted every model call Establishes core system persona, operational objectives, and top-level procedural execution boundaries.
C2 Guardrails guardrails.md Context Construction; mounted every model call Enforces hard operational constraints, mandatory validation policies, and safety boundary checks.
C3 Memory LongTermMEMORY.md Context Construction; mounted every model call Maintains persistent task state, episodic notes, and structured long-term state across execution steps.
C4 Tool Guidance tool_guidance.md Tool Interface; mounted every model call Provides explicit rules, usage directives, type-handling constraints, and formatting rules for available tools.
C5 Subagents sub_agents/<n>/AGENT.md Orchestration; triggered via task tool call Governs sub-task delegation, specialist agent persona definitions, and multi-agent coordination protocols.
C6 Skills skills/<n>/SKILL.md Context Construction; mounted dynamically on invoke Provides domain-specific procedural mechanics, specialized workflows, and step-by-step resolution rules.
C7 Scripts scripts/<name>.py Tool Interface; invoked explicitly via bash tool Executes deterministic, code-based operational helpers, parsing tools, and automated output verification scripts.
C8 Plugin plugin/<name>.ts Middleware Hooks; intercepts every tool call automatically Non-discretionary TypeScript hooks enforcing programmatic boundary checks outside model choice.

2.3 Context Construction vs. Tool Interface vs. Orchestration vs. Middleware

The eight components map directly into four macro-runtime functional groups:

                  +-------------------------------------------------------+
                  |               HARNESS2 RUNTIME ENGINE                 |
                  +-------------------------------------------------------+
                                              |
      +-------------------+-------------------+-------------------+
      |                   |                   |                   |
      v                   v                   v                   v

+--------------+ +--------------+ +--------------+ +--------------+
| CONTEXT | | TOOL | |ORCHESTRATION | | MIDDLEWARE |
| CONSTRUCTION | | INTERFACE | | & SKILLS | | HOOKS |
| (C1, C2, C3) | | (C4, C7) | | (C5, C6) | | (C8) |
+--------------+ +--------------+ +--------------+ +--------------+
| | | |
+-------------------+-------------------+-------------------+
|
v
+---------------------+
| FROZEN BASE MODEL |
+---------------------+

- Context Construction (C1, C2, C3): Determines what contextual state enters the LLM context window on every iteration.
- Tool Interface (C4, C7): Defines available tool calling mechanics, combining prompt-level guidance (C4) with executable helper scripts (C7).
- Orchestration & Domain Knowledge (C5, C6): Governs modular delegation to sub-agents (C5) and procedural domain skill injection (C6).
- Middleware Hooks (C8): Operates at the runtime container level outside model discretion.

Architectural Significance of Non-Discretionary Hooks (C8): While components C1–C7 rely on the probabilistic model choosing to follow instructions, C8 plugin hooks execute deterministically at the runtime middleware layer. Intercepting every tool call outside the model's control ensures that strict system constraints (e.g., payload sanitization, resource limits, file format validation) are mandatorily enforced regardless of LLM generation variances.

2.4 Section Transition

The physical decomposition of \mathcal{H} into discrete, file-mounted components provides the exact targets modified during task-level recursion.

3. Task-Level Recursion Mechanics: The Contrastive Propose–Probe–Compose Cycle

Task-level recursion optimizes the active execution harness \mathcal{H} for a specific task q_t without relying on external ground-truth verifiers or reward models. It achieves this by executing candidate harness edits under identical environmental conditions and deriving actionable optimization signals from the resulting behavioral contrasts.

3.1 Mathematical Formulation of the Contrastive Improvement Step

Let e = (\tau, y) define an execution record consisting of trajectory trace \tau and submitted deliverable y. The contrastive improvement step is governed by the transformation operator \Phi:

(\mathcal{H}', e', \xi) = \Phi(q_t, \mathcal{H}, \mathcal{E}; \mathcal{R}\_t)

where \mathcal{H} is the current execution harness, \mathcal{E} is accumulated task-local history, \mathcal{R}\_t is the fixed continual improvement harness, \mathcal{H}' is the successor harness, e' = (\tau', y') is the successor execution record, and \xi is the step record capturing candidate proposals, probes, diffs, and composition rationale.

To initiate the step, the system samples an initial reference execution trace:

e_0 \sim \mathcal{A}(q_t; \mathcal{M}, \mathcal{H})

The baseline trace e_0 = (\tau_0, y_0) reveals behavioral deficiencies (e.g., tool errors, unverified outputs, formatting failures) without assuming whether y_0 is correct.

3.2 Proposal Scoping: Invariant vs. Domain-Specific Scopes

Conditioned on task q_t, reference trace e_0, and history \mathcal{E}, the improver drafts candidate harness edits across two distinct operational scopes:

                                 +------------------------+
                                 |  REFERENCE EXECUTION   |
                                 |  e_0 ~ A(q_t; M, H_0)  |
                                 +-----------+------------+
                                             |
                                             v
                                 +------------------------+
                                 |    PROPOSE PHASE       |
                                 +----+--------------+----+
                                      |              |
                   +------------------+              +------------------+
                   |                                                    |
                   v                                                    v
    +------------------------------+                     +------------------------------+
    |      INVARIANT CANDIDATE     |                     |   DOMAIN-SPECIFIC CANDIDATE  |
    |  Targets General Agentic     |                     |   Targets Specialized Task   |
    |  Deficiencies (Planning,     |                     |   Mechanics, Skills, Rules,  |
    |  Tool Handling, Delegation)  |                     |   and Output Constraints     |
    +--------------+---------------+                     +--------------+---------------+
                   |                                                    |
                   +------------------+              +------------------+
                                      |              |
                                      v              v
                                 +------------------------+
                                 |      PROBE PHASE       |
                                 |  Execute Matched Runs  |
                                 +-----------+------------+
                                             |
                                             v
                                 +------------------------+
                                 |     COMPOSE PHASE      |
                                 | Selectively Merge Diffs|
                                 +------------------------+

- Invariant Candidates: Target recurring agentic deficiencies independent of the domain, such as planning loops, context window overflow, tool call formatting errors, and sub-agent delegation failures.
- Domain-Specific Candidates: Target task-specific knowledge, domain constraints, file parsing rules, and environment-specific delivery formats.

Proposals modify specific files in \mathcal{H} = (c_1, \dots, c_8), drafting exact code and text diffs.

3.3 Probing via Matched Execution & Behavioral Contrast

In the Probe phase, proposed candidate harnesses are mounted and executed on task q_t under matched environment states and identical base model parameter configurations. Formally, a trajectory trace \tau is defined as an ordered sequence of action proposals a_i and environment/tool observations o_i:

\tau = (a_1, o_1, a_2, o_2, \dots, a_T, o_T)

Rather than attempting to score outputs using unverified LLM judges or relying on cosmetic text output diffs, the probe phase evaluates concrete execution action differentials across trajectory traces:

\Delta \tau = \tau*{\text{candidate}} - \tau*{0}

By evaluating structural execution diffs (e.g., verifying whether a newly injected script successfully parsed a complex Excel sheet vs. throwing a silent exception, or whether string-to-number type handling prevented a tool retry loop), the system observes concrete behavioral evidence: whether the edit mitigated the targeted deficiency, left execution unchanged, or introduced unexpected regressions.

3.4 Harness Composition Dynamics

During the Compose phase, the system analyzes candidate diffs, candidate probes, and observed behavioral contrasts. Instead of blindly selecting one full candidate, the composer selectively merges supported modifications into a unified successor harness \mathcal{H}':

- Non-conflicting, behaviorally supported edits across invariant and domain proposals are merged.
- Conflicting edits are resolved based on concrete trajectory evidence.
- Edits that cause execution regressions are discarded, retaining original base components.

The newly composed harness \mathcal{H}' is then executed to generate successor record e' = (\tau', y').

3.5 Test-Time Budget Scaling (k): Parallel vs. Sequential Recursion

Harness2 scales test-time optimization budget via integer k, controlling exploration width or depth:

- Parallel Recursion (k Width): Collects k reference executions, simultaneously proposes and probes k invariant and k domain candidates, and executes k independent composition sessions in parallel: \mathcal{H}'\_j = \text{Compose}\_j(q_t, \mathcal{H}, \mathcal{B}, \mathcal{P}; \mathcal{R}\_t), \quad j = 1, \dots, k where \mathcal{B} is the set of reference runs and \mathcal{P} is the candidate probe pool.
- Sequential Recursion (k Depth): Chains k contrastive steps iteratively, carrying forward accumulated history: (\mathcal{H}^{(r)}, e^{(r)}, \xi^{(r)}) = \Phi(q_t, \mathcal{H}^{(r-1)}, \mathcal{E}^{(r-1)}; \mathcal{R}\_t), \quad r = 1, \dots, k allowing later steps to correct or refine earlier harness edits.

Final Selection Stage (k > 1): When budget k > 1 produces multiple candidate deliverables \{y_1, \dots, y_k\}, an agentic selector evaluates anonymized deliverables against task requirements. Crucially, the selector evaluates only deliverable outputs without access to the originating harness or internal prompt state, selecting the best existing deliverable y^_ and adopting its associated harness \mathcal{H}^_\_t.

3.6 Strategic Execution Impact ("So What?" Layer)

Contrastive behavioral probing isolates cause-and-effect relationships between harness diffs and trajectory changes. Because it evaluates concrete execution actions (e.g., verifying whether a script successfully parsed a file) rather than relying on probabilistic self-judgments, Harness2 bypasses shared model bias and execution stochasticity, generating reliable harness updates without ground-truth labels.

3.7 Section Transition

While task-level recursion optimizes scaffolding locally for task q_t, harnessing-level recursion converts these local step records into persistent, cross-task capabilities.

4. Harnessing-Level Recursion Mechanics: The Continual Improvement Engine

Harnessing-level recursion ensures that local task explorations accumulate into systemic improvements. After task completion, the system extracts generalizable lessons to update the continual improvement harness \mathcal{R}\_t, accelerating adaptation on future tasks.

+-----------------------------------------------------------------------------------+
| HARNESSING-LEVEL RECURSION |
| |
| Task Execution Complete (q_t) |
| Full Step Record D_t = { References, Candidates, Probes, Diffs, Selection } |
| | |
| v |
| +-----------------------------------------------------------------------------+ |
| | RETROSPECTIVE REFLECTION | |
| | Filter: Retain lessons ONLY grounded in contrastive evidence | |
| +-------------------------------------+---------------------------------------+ |
| | |
| v |
| +-----------------------------------------------------------------------------+ |
| | HARNESS IMPROVEMENT LIBRARY (R_t+1) | |
| | - Adopted Component Files (c_1 ... c_8) | |
| | - EXPERIENCE.md (YAML Frontmatter + Lessons + Contrastive Evidence) | |
| | - Persistent Index File (Searchable Metadata Schema) | |
| +-------------------------------------+---------------------------------------+ |
| | |
| +-------------------------------------+---------------------------------------+ |
| | Next Task Arrival (q_t+1) | |
| | - Reset Execution Harness to H_0 | |
| | - Propose/Probe/Compose query updated R_t+1 for component reuse & guidance | |
| +-----------------------------------------------------------------------------+ |
+-----------------------------------------------------------------------------------+

4.1 Retrospective Improvement Reflection

Upon submitting deliverable y^\*, the framework conducts retrospective reflection over the complete task record:

\mathcal{D}\_t = \{ \text{references}, \text{candidates}, \text{probes}, \text{diffs}, \text{composition decisions}, \text{selected deliverable} \}

Strict Evidence Filter Rule: Reflection extracts lessons only when changes in behavior are directly verified by observed trajectory contrasts (\Delta \tau). Output adoption alone does not validate a lesson; if a harness edit produces no observable behavioral contrast or lacks trajectory evidence, it is rejected by the filter, preventing noisy meta-knowledge corruption.

4.2 Architecture of the Harness Improvement Library

The improvement harness \mathcal{R}\_{t+1} is formally updated via:

\mathcal{R}\_{t+1} = \text{Update}(\mathcal{R}\_t, \mathcal{H}^\*\_t, \mathcal{D}\_t)

The library maintains a persistent directory structure containing:

1. Validated Component Assets: Executable helper scripts (C7), skill definitions (C6), tool guidance snippets (C4), and guardrails (C2) preserved from adopted harnesses \mathcal{H}^\*\_t.
2. EXPERIENCE.md Documentation: Structured markdown records documenting the situation, lessons, and supporting contrastive evidence. Each file incorporates a strict, machine-readable YAML frontmatter metadata schema:

---

task_id: "jobbench_task1_producers"
task_domain: "financial_reconciliation"
deficiency_type: "unreconciled_cross_file_figures"
applied_components:

- "c2_guardrails"
- "c4_tool_guidance"
- "c6_skills"
- "c7_scripts"
  contrast_validation_flag: true
  trajectory_differential_summary: "Forced pre-analysis file inventory and script-based XLSX verification; eliminated silent formula failures and unhandled numeric string formats."

---

1. Library Metadata Index: A searchable index compiling the YAML frontmatter headers across all entries, allowing improver sessions to query past experience efficiently by task domain, deficiency type, and applied component filters.

4.3 Cross-Task Library Transfer & Reuse Protocols

When task q*{t+1} arrives, the execution harness resets to baseline \mathcal{H}\_0, preventing task-specific drift. However, the improver gains full access to \mathcal{R}*{t+1}. During the Propose, Probe, and Compose phases of task q*{t+1}, the improver queries the metadata index of \mathcal{R}*{t+1} to:

- Retrieve and mount pre-validated scripts (C7) or skills (C6) designed for similar tasks.
- Apply established guardrail policies (C2) without re-inventing workflow rules.
- Transfer cross-domain strategies (e.g., transferring data reconciliation workflows accumulated on JobBench to office automation tasks in WorkBuddy-Bench).

  4.4 Strategic Meta-Learning Impact ("So What?" Layer)

By continually updating \mathcal{R}_t while resetting \mathcal{H}\_0 per task, Harness2 decoupling avoids task-specific overfitting while achieving compounding meta-learning. Higher test-time budgets (k) during task-level recursion generate richer contrastive evidence \mathcal{D}\_t, directly upgrading the quality of \mathcal{R}_{t+1}. Consequently, initial zero-shot adaptation steps on future, unseen tasks become systematically more effective over time.

4.5 Section Transition

The practical efficacy of dual-recursion scaffolding is demonstrated through empirical validation across standardized professional agent benchmarks.

5. Empirical Benchmark Validation & Architectural Ablations

Harness2 underwent extensive evaluation across three multi-domain professional agent benchmarks: WorkBuddy-Bench (office, web, and coding workflows), JobBench (long-horizon professional jobs), and Harvey's Legal Agent Benchmark (LAB Partial) (complex legal analysis, research, and drafting). Evaluations utilized frozen foundation models under open-source initial harnesses (OpenCode and Codex CLI).

5.1 Primary Benchmark Performance Synthesis

Table 5.1 summarizes benchmark performance and execution step counts (#Steps) across initial base harnesses, retrieval baselines, offline optimization, test-time scaling, single-step Harness2 (k=1), and parallel recursive Harness2 (k=5).

Model & Harness Setup Method / Configuration WorkBuddy Code
Score (#Steps) WorkBuddy Web
Score (#Steps) WorkBuddy Office
Score (#Steps) WorkBuddy Avg
Score (#Steps) JobBench
Score (#Steps) LAB Partial
Pass Rate (%) (#Steps)
Gemini 3.5 Flash
(OpenCode) Base Harness 73.4 (29.6) 69.9 (19.2) 74.0 (27.3) 72.4 (25.4) 31.5 (63.6) 79.9 (29.0)
ReasoningBank 72.6 (28.7) 70.7 (18.8) 76.8 (27.1) 73.4 (24.9) 30.8 (65.7) 77.3 (31.3)
Meta-Harness† 75.5 (31.5) 75.1 (26.4) 78.6 (28.6) 76.4 (28.8) 35.8 (71.8) 81.6 (31.1)
Harness Scaling 74.0 (26.1) 74.0 (16.6) 77.9 (24.3) 75.3 (22.3) 32.9 (64.5) 78.9 (31.4)
Harness2 (k=1) 76.5 (22.8) 76.4 (17.7) 79.5 (25.1) 77.5 (21.9) 36.0 (69.3) 81.9 (33.0) + Parallel Rec. (k=5) 80.8 (22.4) 78.3 (18.1) 83.4 (22.9) 80.8 (21.1) 39.0 (59.7) 84.5 (27.3)
Gemini 3.5 Flash
(Codex CLI) Base Harness 74.0 (31.8) 72.5 (22.6) 77.0 (30.6) 74.5 (28.3) 33.9 (53.6) 71.6 (49.8)
ReasoningBank 73.5 (32.8) 65.7 (22.7) 78.4 (32.1) 72.5 (29.2) 30.2 (54.1) 74.8 (52.7)
Meta-Harness† 74.6 (33.5) 67.8 (22.1) 77.6 (30.1) 73.3 (28.6) 34.8 (57.4) 76.5 (56.7)
Harness Scaling 75.5 (32.4) 69.3 (23.5) 76.7 (34.0) 73.8 (30.0) 33.6 (50.8) 67.9 (53.1)
Harness2 (k=1) 79.4 (26.6) 74.7 (19.5) 78.5 (25.6) 77.5 (23.9) 35.3 (54.5) 75.6 (44.2) + Parallel Rec. (k=5) 81.0 (24.6) 77.3 (19.5) 82.8 (26.9) 80.4 (23.7) 39.5 (54.7) 78.5 (49.0)
GLM-5
(OpenCode) Base Harness 58.4 (19.2) 59.2 (9.2) 75.1 (12.0) 64.2 (13.5) 20.6 (20.0) 59.6 (13.6)
ReasoningBank 63.3 (18.6) 61.4 (10.3) 72.0 (14.3) 65.6 (14.4) 20.7 (21.4) 71.3 (15.3)
Meta-Harness† 69.0 (22.4) 61.9 (10.0) 78.1 (13.6) 69.7 (15.3) 20.9 (20.1) 60.0 (14.0)
Harness Scaling 60.3 (16.0) 63.4 (9.0) 79.8 (12.8) 67.8 (12.6) 19.3 (22.2) 67.8 (17.6)
Harness2 (k=1) 77.1 (14.8) 69.1 (11.0) 80.8 (15.2) 75.7 (13.7) 24.2 (23.6) 71.4 (15.8) + Parallel Rec. (k=5) 81.9 (9.3) 74.4 (10.8) 82.5 (12.9) 79.6 (11.0) 28.4 (23.1) 78.1 (18.8)
GLM-5
(Codex CLI) Base Harness 56.8 (28.5) 59.6 (18.0) 76.9 (23.4) 64.4 (23.3) 23.6 (22.3) 58.1 (16.5)
ReasoningBank 50.2 (24.9) 66.3 (17.5) 75.8 (20.9) 64.1 (21.1) 22.8 (25.3) 63.8 (16.9)
Meta-Harness† 76.8 (33.0) 67.8 (24.7) 77.9 (31.4) 74.2 (29.7) 23.9 (22.3) 59.0 (22.0)
Harness Scaling 49.5 (24.2) 60.9 (18.9) 78.2 (22.0) 62.9 (21.7) 17.5 (22.8) 63.7 (24.3)
Harness2 (k=1) 74.9 (19.7) 70.0 (22.4) 81.1 (21.8) 75.3 (21.3) 24.8 (25.3) 65.9 (22.3) + Parallel Rec. (k=5) 77.2 (18.3) 73.3 (19.9) 84.3 (21.9) 78.3 (20.0) 27.9 (27.0) 70.7 (26.7)

Note: Results reported as Score Mean with execution Step Mean (#Steps) over 3 randomized task-order runs. Best single-step results bolded. †Meta-Harness is an offline search method trained on separate dev splits.

Quantitative Landmark & Efficiency Synthesis:

- Dual Benefit of Scaffolding Evolution (Accuracy Gains + Step Reduction): Scaffolding evolution simultaneously improves task completion rates while reducing wasteful operational steps and tool retries. For example, GLM-5 under OpenCode on WorkBuddy Code drops from 19.2 average execution steps to 14.8 steps under Harness2 (k=1) while raising accuracy from 58.4% to 77.1%. Under parallel recursion (k=5), step count drops further to 9.3 steps while accuracy reaches 81.9%.
- WorkBuddy-Bench Landmark Gains: A single step (k=1) of Harness2 raises GLM-5 OpenCode average performance by +11.5 points (64.2 to 75.7). Parallel scaling (k=5) pushes Gemini 3.5 Flash under OpenCode to 80.8 Avg (+8.4 overall gain).
- JobBench & LAB Landmark Gains: Single-step Harness2 achieves up to +4.5 points gain on Gemini 3.5 Flash OpenCode for JobBench, while raising GLM-5 OpenCode LAB Partial pass rate by +11.8 percentage points (59.6% to 71.4%).

  5.2 Component Ablation Analysis

To isolate the structural contribution of each system module, key architectural primitives were systematically ablated (evaluated on Gemini 3.5 Flash under OpenCode at k=1):

Configuration Variant WorkBuddy-Bench Avg Score Absolute Drop JobBench Score Absolute Drop
Full Harness2 Framework 77.5 — 36.0 —
w/o Harness Improvement Library 74.4 -3.1 34.2 -1.8
w/o Scoped Proposal Editors 74.6 -2.9 32.3 -3.7
w/o Multi-Candidate Composition 75.9 -1.6 34.1 -1.9

Compute–Performance Pareto Frontier: Counting all tokens consumed prior to deliverable submission, Harness2 configurations establish an optimal empirical Pareto frontier. While methods like Meta-Harness require large token expenditures during offline search and Harness Scaling incurs high test-time costs for small gains, Harness2 maximizes score gain per token expended by combining targeted local probing with cross-task library retrieval.

5.3 Symmetric Operations: Same Model as Executor and Editor

To verify that self-improvement gains do not depend on a superior editor model (the default setup used Claude Opus 4.8 as editor), experiments evaluated symmetric setups where the same model served as both executor and editor (OpenCode harness at k=2). All five evaluated foundation models demonstrated consistent performance gains across all three benchmarks:

WorkBuddy-Bench Score (%) JobBench Score LAB Partial Pass Rate (%)
85 +-------------------------+ 70 +-------------------------+ 90 +-------------------------+
| 80.4 80.7 82.2| | 51.2 50.8 67.9| | 81.6 89.1 85.6 89.7|
80 | 78.3 | 55 | | 80 | 73.3 |
| 68.3 | | 32.4 | | |
65 +-------------------------+ 20 +-------------------------+ 60 +-------------------------+
GLM5 3.5F 3.7F O4.8 O5 GLM5 3.5F 3.7F O4.8 O5 GLM5 3.5F 3.7F O4.8 O5
(+4.1)(+5.9)(+2.1)(+4.1)(+3.3) (+2.9)(+0.9)(+1.8)(+2.5)(+5.5) (+13.7)(+1.7)(+3.6)(+4.4)(+3.0)

The detailed performance matrix across all five symmetric model configurations is summarized below:

1. GLM-5:

- WorkBuddy-Bench: 64.2 \rightarrow 68.3 (+4.1 gain)
- JobBench: 20.6 \rightarrow 23.5 (+2.9 gain)
- LAB Partial: 59.6% \rightarrow 73.3% (+13.7 percentage points gain)

2. Gemini 3.5 Flash:

- WorkBuddy-Bench: 72.4 \rightarrow 78.3 (+5.9 gain)
- JobBench: 31.5 \rightarrow 32.4 (+0.9 gain)
- LAB Partial: 79.9% \rightarrow 81.6% (+1.7 percentage points gain)

3. Gemini 3.7 Flash:

- WorkBuddy-Bench: 78.3 \rightarrow 80.4 (+2.1 gain)
- JobBench: 49.4 \rightarrow 51.2 (+1.8 gain)
- LAB Partial: 85.5% \rightarrow 89.1% (+3.6 percentage points gain)

4. Claude Opus 4.8:

- WorkBuddy-Bench: 76.6 \rightarrow 80.7 (+4.1 gain)
- JobBench: 48.3 \rightarrow 50.8 (+2.5 gain)
- LAB Partial: 81.2% \rightarrow 85.6% (+4.4 percentage points gain)

5. Claude Opus 5:

- WorkBuddy-Bench: 78.9 \rightarrow 82.2 (+3.3 gain)
- JobBench: 62.4 \rightarrow 67.9 (+5.5 gain)
- LAB Partial: 86.7% \rightarrow 89.7% (+3.0 percentage points gain)

These results confirm that recursive harness editing is a fundamental scaffolding capability that does not require an asymmetrical strong-to-weak model hierarchy.

5.4 Deep-Dive Qualitative Case Study: JobBench "Producers" Task

Task Overview (JobBench task1 - Producers): Reconcile complex schedule, roster, venue, and budget files into interconnected production deliverables.

- Baseline Run Failure (Score: 43.1):
  1. Failure Mode 1: Figures were never cross-reconciled across source files, leading to conflicting budget and staffing numbers.
  2. Failure Mode 2: Created deliverable files were never reopened or verified post-generation, leaving missing sections and unformatted values.
- Harness2 Scaffolding Interventions:
  - C2 Guardrail (guardrails.md - 1,464 B): Added process rule forcing the model to inventory all input files with scripts/inspect_inputs.py before analyzing, trace figures to authoritative sources, and mandate reopening produced files with scripts/verify_outputs.py.
  - C6 Skill (skills/reconcile/SKILL.md - 4,942 B): Instantiated exact reconciliation rules for schedule, venue, labor, and budget files, establishing source hierarchies, hour caps, and rest rules.
  - C4 Tool Guidance (tool_guidance.md - 645 B): Injected instructions handling cell numbers stored as strings (e.g., stripping "$50" and "1,200" before arithmetic) and enforcing single-retry web searches.
  - C7 Script (scripts/verify_outputs.py - 3,881 B): Created a Python script inspecting .xlsx formula values (fv) against visual values (vv) to flag blank reads and broken formulas.
- Outcome (Score: 77.8 / +34.7 Net Gain): The composed harness executed successfully, reconciling all cross-file figures, resolving numerical discrepancies, and restoring all missing memo sections.

  5.5 Strategic Data Insights ("So What?" Layer)

The empirical data proves that harness evolution can compensate for weaker base model parameters. A computationally weaker executor like GLM-5, when enhanced with Harness2 (k=1 score of 75.7 on WorkBuddy Avg), directly outperforms a stronger base model like Gemini 3.5 Flash operating under a static baseline harness (72.4 Avg). Scaffolding self-improvement unlocks latent capabilities in existing models without requiring model weight expansion.

5.6 Section Transition

Translating these empirical architecture findings into production systems requires establishing robust runtime controls, execution sandboxes, and cost calibration guidelines.

6. Architectural Implementation Blueprint & Operational Constraints

Deploying Harness2 into enterprise operational environments requires establishing sandbox boundaries, operational safety controls, and cost-latency calibration rules.

6.1 Enterprise Runtime Safety & Sandbox Isolation

To protect host environments from dynamic code edits generated during recursive optimization, enterprise implementations must strictly enforce three isolation layers:

+-----------------------------------------------------------------------------------+
| ENTERPRISE SANDBOX ENVIRONMENT |
| |
| +-----------------------------------------------------------------------------+ |
| | C8 PLUGIN MIDDLEWARE HOOKS (plugin/<name>.ts) | |
| | - Intercepts ALL tool calls outside LLM discretion | |
| | - Enforces programmatic boundary checks & token limits | |
| +-------------------------------------+---------------------------------------+ |
| | |
| v |
| +-----------------------------------------------------------------------------+ |
| | EPHEMERAL CONTAINER BOUNDARY (Docker / gVisor) | |
| | - File modifications (C1-C6) mounted in ephemeral container workspace | |
| | - State reset between execution runs; isolated file system mounts | |
| | | |
| | +---------------------------------------------------------------------+ | |
| | | ISOLATED BASH SUB-PROCESS | | |
| | | - C7 Helper Scripts (scripts/<name>.py) executed in constrained bash| | |
| | | - Restricted network access, CPU time caps, memory bounds | | |
| | +---------------------------------------------------------------------+ | |
| +-----------------------------------------------------------------------------+ |
+-----------------------------------------------------------------------------------+

1. Ephemeral Container Boundary: All harness file edits (C1–C6) and task executions must run inside ephemeral, isolated containers (e.g., Docker/gVisor). Every rollout must mount a fresh container state to prevent persistent workspace corruption.
2. Constrained Script Execution Sub-process: Helper scripts (C7) generated by task proposals execute in an isolated sub-process via bash with restricted resource caps (CPU, memory, process execution timeouts) and blocked external network access unless explicitly required.
3. Non-Bypassable Middleware Plugins (C8): Security rules, data privacy scrubbers, and destructive command blocks must be compiled into native TypeScript middleware hooks (C8). Because C8 executes outside LLM prompt context, generated harness edits cannot disable or alter these programmatic security barriers.

6.2 Exploration Budget (k) Strategy & Cost-Latency Calibration

Selection of the test-time scaling budget k and operational mode must align with enterprise workflow SLAs:

- Real-Time Interactive Workflows (k=1):
  - Deployment Scope: Low-latency, user-facing agent interactions.
  - Execution Strategy: Run single-step contrastive recursion. Proposes 1 invariant and 1 domain candidate, executes 1 probe step, and composes an updated harness.
  - Operational Profile: Provides immediate score gains (e.g., +11.5 on GLM-5) while minimizing token expenditure and latency overhead.
- High-Stakes Asynchronous Batch Workflows (Parallel k=5):
  - Deployment Scope: Complex, long-horizon job automation, legal drafting, and financial reconciliation.
  - Execution Strategy: Collect 5 reference runs, concurrently probe 5 invariant and 5 domain candidates, run 5 parallel composition sessions, and apply anonymized agentic final selection.
  - Operational Profile: Maximizes accuracy landmarks (e.g., +8.4 on WorkBuddy Avg), leveraging concurrent infrastructure to trade parallel compute for peak task performance.

  6.3 Architectural Limitations & Failure Boundaries

System architects must account for specific failure boundaries inherent in dynamic scaffolding optimization, incorporating concrete production mitigations:

- Context Window Saturation: Accumulating detailed trajectory history \mathcal{E} and long execution records \mathcal{D}\_t across k sequential iterations can approach model context window limits.
  - Architectural Mitigation: Implement an automated sliding-window context compaction pipeline managed by a specialized sub-agent. The pipeline periodically compresses trajectory logs into structured state summaries while preserving active error traces and file diffs.
- Environment Reset Sensitivity: Tasks that modify external stateful environments (e.g., modifying external databases or issuing non-reversible REST API calls) cannot be cleanly re-probed without deterministic rollback mechanisms.
  - Architectural Mitigation: Enforce lightweight container checkpointing (e.g., Docker/gVisor state snapshots) or transactional database snapshotting prior to initiating probe rollouts, allowing the sandbox environment to rollback instantly to state S_0 between candidate probes.
- Parallel Probing Cost Constraints: Scaling parallel recursion to large budgets (k \ge 5) linearly multiplies token consumption during the probe phase.
  - Architectural Mitigation: Apply dynamic budget caps on exploratory streams based on real-time task complexity estimation, capping budget k=1 for simple queries and reserving k=5 for long-horizon multi-file tasks.

  6.4 Definitive Engineering Directives ("So What?" Layer)

For enterprise AI system architects, Harness2 provides a production-ready blueprint for building self-improving agent platforms. By implementing file-mounted modular scaffolding (C1–C8), isolating dynamic code execution within ephemeral sandboxes, and coupling task-local contrastive probing with cross-task experience indexing, organizations can deploy autonomous agent frameworks that continuously optimize over frozen, enterprise-grade LLM APIs. This decoupling ensures continuous capability growth, zero catastrophic forgetting, and predictable operational safety across complex open-world task streams.
