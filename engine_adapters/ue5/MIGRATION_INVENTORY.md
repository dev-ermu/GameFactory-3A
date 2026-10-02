# UE5 Adapter Migration Inventory

Status: UEClient v1, engine-native Automation Test execution, AAAGamePlayable
Runtime Framework, repository UE scripts, Preview tooling, reference gameplay
plugin extraction, the implemented API reference, and the engine-neutral
Mechanic Agent contract are complete. Stub and non-interactive Codex backends,
the engine-neutral Mechanic Operator, and the generation-only Pipeline runner
are implemented. A real Codex FPS artifact has compiled Editor/Game targets,
passed generated Automation Tests, and launched with imported assets through
separately executed UEClient validation. The earlier automatic-import
implementation was removed from `GenMechanicOperator` because engine execution
does not belong in Agent orchestration. A conforming existing-artifact
Evaluator, UE execution migration, bounded repair coordinator, live
trace/evidence capture, and platform serving remain.

Source repository:

```text
D:\Desktop\game\OpenWL_Avatar
```

Target repository:

```text
D:\Desktop\game\3AGameFactory
```

This inventory maps the existing OpenWL Unreal and serving code into the
3AGameFactory architecture. It does not change the existing Layer A/B/C,
`design_doc.txt`, `pipeline_task.jsonl`, or output layout.

## Implementation Progress

Completed on August 2, 2026:

- established `from engine_adapters.ue5 import UEClient` as the unique public
  Python entry point with a versioned result contract;
- migrated configuration and Remote Control/Python execution transports behind
  private modules;
- migrated asset import, validation, registry, PBR, Effect, Gaussian Splat,
  PLY, generated Scene, and World draft/package logic;
- changed public asset resolution to the repository task identity
  `(game_id, run_id, task_kind, task_id, artifact_key)`;
- made `pipeline.common.paths` and each task's `meta.json` the only route from a
  task descriptor to an artifact file or plugin directory;
- added all v1 namespaces: `project`, `assets`, `animation`, `bindings`,
  `world`, `reflection`, `plugin`, `build`, `runtime`, and `observe`;
- migrated generic participant, controller, entity, binding, and normalized
  input session state without Fighter/FPS/Racing command fields;
- migrated the runtime UDP bridge into
  `runtime/_internal/bridge/` and connected it to `UEClient.runtime.sessions`;
- removed `serving.*`, `serving.paths`, and platform-serving imports from the
  migrated UE adapter;
- refactored `OpenWLPlayable` into `AAAGamePlayable`, containing only Public
  interfaces, data types, components, and world/runtime subsystems;
- added an atomic `sync_session` runtime command so participant, controller,
  entity, and binding state are established together;
- added a generated-style Gameplay Plugin fixture that registers its own entity
  factory and implements its own Pawn;
- ported focused asset, Effect, PBR, Gaussian Splat, PLY, World, plugin, build,
  runtime, reflection, and public Contract tests;
- compiled the framework and fixture with UE 5.4 for both Editor and Game
  targets, then verified a headless Game world accepted a UDP `sync_session`
  and spawned/bound the generated entity successfully;
- changed `project.create()` to generate a minimal C++ host module plus Game and
  Editor targets, without concrete gameplay defaults;
- migrated `create_project`, `import_asset`, and `run` CLI behavior; the final
  repository wrappers live under `scripts/ue` and call only public-UEClient
  implementation in `engine_adapters/ue5/cli.py`;
- changed the import launcher from arbitrary source paths to repository task
  descriptors;
- changed the run launcher to own Unreal launch only; gateway/browser serving
  is no longer mixed into the UE script;
- made `plugin.install()` automatically synchronize and enable
  `AAAGamePlayable` when a generated plugin declares that dependency;
- verified a newly scripted project can create, install the framework and
  generated fixture, run UHT, and compile both plugin modules with UE 5.4.

Completed on August 3, 2026:

- moved the public Windows/Linux wrappers to repository-level `scripts/ue`;
- kept Python CLI implementation in `engine_adapters/ue5/cli.py`, with the
  wrappers calling it and the CLI importing only the public `UEClient`;
- extracted Preview character, controller, and GameMode behavior into the
  optional adapter-owned `AAAGamePreview` plugin;
- extracted concrete Arena Fighter, FPS, and Racing Character/Pawn,
  Controller, GameMode, HUD, normalized-input handling, and entity-factory
  registration into independent optional plugins under
  `engine_adapters/ue5/examples`;
- added static dependency tests that prevent `AAAGamePlayable` from depending
  on Preview/examples and prevent examples from including framework Private
  headers;
- compiled Preview and all three reference plugins with UE 5.4 for both Editor
  and Game targets.
- added `engine_adapters/ue5/testing/` and exposed
  `ue.testing.run_automation_tests()`;
- made Automation success depend on both process status and a fresh parsed
  `index.json` report with at least one matched test and all tests passing;
- preserved fresh Automation Reports on test/process failure and returned
  command output, diagnostics, timeout state, and structured test counts;
- added focused missing-configuration, dry-run, success, warning, failed-test,
  empty/inconsistent/invalid/stale-report, process-failure, and timeout tests;
- documented the Agent/Operator/Evaluator execution authority boundary in
  `ue5_api.md` and its contract tests;
- compiled and executed the generated-style
  `AAAGame.GeneratedGameplay.Smoke` test with UE 5.4 through the public API.
- added the engine-neutral `game_generation.md` Skill and
  `system.md`, `task.md`, and `repair.md` prompts;
- changed concrete engine calls to reference exactly one selected API file by
  read-only path instead of embedding the complete API surface in a Prompt;
- added generic Operator-provided project and game-owned module identifiers;
- added a JSON-serializable Mechanic Agent request/result contract with
  workspace/read-only boundaries and explicit test/benchmark authority;
- added a CPU-safe `StubAgent` implementing only `model.run(request)`;
- tracked created, modified, and deleted Agent files separately;
- added 16 focused cross-engine Prompt, request/result, sandbox, repair,
  Duck-Typing, and Stub contract tests.
- implemented `GenMechanicOperator(model, output_dir, run_id,
  default_game_id)`, `run()`, and `run_batch()`;
- implemented task/requirement loading, stable project/module naming, Prompt
  rendering, validated `model.run(request)`, Agent file ownership checks,
  transcript/result persistence, artifact checks, and failure `meta.json`;
- synchronized `AAAGamePlayable` and the canonical generated plugin source into
  Stub-produced UE projects;
- implemented `pipeline/mechanic/run.py` with `load_model`, `make_operator`,
  `generate`, `run_from_jsonl`, and `main`;
- added 7 Operator/runner tests, bringing focused Mechanic tests to 23;
- ran the real `fps_core_001` JSONL through the Stub backend under
  `fps_baseline_v1`, producing the standard project/plugin/demo/meta layout.

Completed on August 4, 2026:

- implemented `CodexAgent` with non-interactive `codex exec`, workspace-write
  sandboxing, timeout handling, JSON event transcripts, usage collection, and
  generated/modified/deleted file snapshots;
- connected `--backend codex` without changing the Duck-Typed
  `model.run(request)` or Operator constructor contracts;
- generated `AAAGameCyberPrisonFPS` and the separate `CyberPrisonFPS` Gameplay
  Plugin under `fps_skill_validation_v1`;
- imported the abandoned-prison native scene, player/enemy avatars, rifle, and
  seven role-specific motions from `fps_baseline_v1` through public UEClient
  operations;
- compiled `AAAGameCyberPrisonFPS` and
  `AAAGameCyberPrisonFPSEditor` successfully with UE 5.4;
- executed `AAAGame.CyberPrisonFPS.*`: 3 tests found, 3 passed, 0 failed;
- launched the prison map and retained logs proving imported player/rifle
  loading, right-hand attachment, three enemy spawns, pursuit/attack state, and
  player damage;
- added automatic Layer A import to `GenMechanicOperator`: Editor preparation,
  controlled Editor lifecycle, native scene import, avatar/weapon import,
  Skeleton-role motion import, per-item results, and import manifest;
- added runner `--ue-root` support through `AAAGAME_UE_ROOT`;
- added a focused automatic-import Operator test; the current focused
  Mechanic Agent/Operator suite contains 25 passing tests.

Architecture correction completed on August 4, 2026:

- superseded the automatic-import Operator placement while preserving the
  existing UEClient implementation and validation evidence;
- removed all Engine Adapter imports, UE project/plugin synchronization,
  descriptor import, Editor lifecycle, and execution metadata from
  `GenMechanicOperator`;
- reduced the Operator to Skill/Prompt/context assembly, generate/repair
  `model.run(request)`, workspace-change validation, and Agent evidence;
- removed project/plugin/launch completeness checks from generation;
- restored `pipeline/mechanic/run.py` to the Pipeline README's
  generation-only five-function API and removed `--ue-root`;
- made Engine API Reference paths explicit task/CLI inputs;
- reserved `pipeline/mechanic/eval.py` for existing-artifact evaluation;
- passed all 31 focused Mechanic Agent/Operator/runner tests and confirmed no
  `engine_adapters` or `UEClient` references remain under
  `operators/gen_mechanic`.

Still pending:

- implement `pipeline/mechanic/eval.py` through `pipeline.common.paths`;
- migrate descriptor import, project preparation, authoritative builds,
  generated tests, and runtime evidence into the UE evaluation/execution path;
- place bounded build/test repair without putting evaluation in generation
  `run.py` or Agent generation in evaluation `eval.py`;
- replay the complete live deterministic FPS trace and capture valid
  game-window screenshots;
- reproduce the full Codex/import/build/test/runtime path through an
  architecture-conforming coordinator and update metadata from
  Pipeline/Evaluator evidence;
- define task-owned state, input, event, observation, and UI binding schemas;
- implement UI generation only after that Mechanic contract is stable;
- migrate platform serving to `engine_adapters/z_other_serving`.

## Current Framework Validation Stage

The current implemented generation milestone is:

```text
test_samples
    |
    v
GenMechanicOperator
    |
    v
CodexAgent
    |
    v
durable Mechanic source artifacts
```

This proves real Agent execution and durable workspace-change reporting without
binding the Operator to one engine. The retained validation artifact separately
proves UE import, builds, generated tests, and runtime startup. It does not yet
prove an architecture-conforming closed loop:

```text
generation + existing-artifact evaluation + repair coordination
    + live trace + screenshots = reproducible playable game
```

Implementation priority is frozen as:

```text
P0  Real Mechanic closed loop
    real Agent -> Evaluator import/build/test -> repair coordinator
    -> live trace/evidence -> playable fps_core_001

P1  Mechanic contract stabilization
    task-defined state/input/event/observation/UI schemas

P2  UI Agent
    GenUIOperator -> HUD/menu/end states -> screenshots and metadata

P3  Full Game Pipeline
    Layer A assets -> Mechanic -> UI -> packaging/evaluation
```

The P0 exit gate is a launched UE game in which the player can enter the map,
move, attack, affect and defeat enemies, reach win/loss states, and pass
Evaluator-executed generated Automation Tests with retained build, test, trace,
and runtime evidence.

UI work must not start merely because `fps_hud_001` exists. P1 must first
validate and freeze the Mechanic-facing fields needed by UI, including the
baseline state set:

```text
game_state
player_health
magazine_ammo
reserve_ammo
enemies_remaining
is_reloading
objective_text
```

The UI must consume the stabilized binding contract rather than bind directly
to whichever concrete Character, Weapon Component, inventory implementation,
or Gameplay Ability classes the generated Mechanic happens to use.

## Validation Snapshot

Completed through August 4, 2026:

- `python -m unittest discover -s tests -p 'test_ue5_*.py' -v`
  passes all 86 tests;
- scans report no `serving.*` or `z_other_serving` imports from
  `engine_adapters/ue5`;
- scans report no Fighter, FPS, Racing, Punch, Kick, steering, throttle, boost,
  handbrake, Preview Character, or Preview GameMode coupling in
  `AAAGamePlayable`, runtime sessions, generated fixture, or migrated scripts;
- the generated fixture includes no framework Private headers;
- `OpenWLScriptContractTestEditor` and `OpenWLScriptContractTest` both compile
  successfully with `D:\UE\UE_5.4`;
- the headless runtime log contains:

  ```text
  [AAAGame] Generated gameplay entity factory registered
  [AAAGame] Runtime session sync entity=entity_contract controller=controller_contract result=ok
  ```

- `scripts\ue\create_project.cmd` created and compiled
  `AAAGameScriptMigrationTestFullEditor`;
- after installing the mechanic fixture through `UEClient.plugin.install`,
  `AAAGameScriptMigrationTestFullEditor` ran UHT and compiled
  `AAAGamePlayable` plus `GeneratedGameplayPlugin` successfully;
- `AAAGameScriptMigrationTestFullEditor` compiled `AAAGamePreview`,
  `ArenaFighterExample`, `FPSExample`, and `RacingExample`;
- `AAAGameScriptMigrationTestFull` compiled the same optional plugins for the
  Win64 Development Game target, confirming no Editor-only dependency.
- `AAAGameScriptMigrationTestFullEditor` compiled
  `GeneratedGameplayAutomationTests.cpp`;
- `ue.testing.run_automation_tests()` executed
  `AAAGame.GeneratedGameplay.Smoke` with UE 5.4 and returned:

  ```text
  returncode = 0
  tests_found = 1
  tests_passed = 1
  tests_failed = 0
  ```
- `python -m unittest test.test_gen_mechanic_agent_contract -v`
  passes all 17 Mechanic Agent context/contract tests;
- a custom non-UE API Reference file passes the same request contract,
  confirming the Agent protocol does not depend on UE-specific calls.
- `python -m unittest test.test_gen_mechanic_agent_contract
  test.test_gen_mechanic_operator -v` passes all 31 focused Mechanic tests,
  including generate/repair persistence, Operator purity, thin generation
  runner behavior, and explicit Engine API Reference handling;
- `pipeline/mechanic/run.py --backend stub --game
  gameA_cyberpunk_shooter --run-id fps_baseline_v1` completed
  `fps_core_001` and wrote:

  ```text
  project/AAAGameFpsCore001.uproject
  generated_plugin/
  demo_outputs/agent_request.json
  demo_outputs/agent_result.json
  demo_outputs/agent_transcript.jsonl
  meta.json
  ```

  This is a source/artifact contract result only.
  `authoritative_validation=false`, and build/tests are `not_run`.
- `pipeline/mechanic/run.py --backend codex --game
  gameA_cyberpunk_shooter --run-id fps_skill_validation_v1
  --agent-timeout 1800 --agent-max-turns 16` generated
  `AAAGameCyberPrisonFPS` and `CyberPrisonFPS`;
- public UEClient operations imported all 11 declared Layer A roles into the
  generated project: 272 native scene files plus 28 imported avatar, weapon,
  Skeleton, material/texture, and motion assets;
- `AAAGameCyberPrisonFPS` and `AAAGameCyberPrisonFPSEditor` both compiled with
  UE 5.4, return code 0;
- `ue.testing.run_automation_tests("AAAGame.CyberPrisonFPS")` returned 3 found,
  3 passed, 0 failed;
- runtime logs confirm the prison map loaded, player and rifle assets resolved,
  the rifle attached to `RightHand`, three enemies spawned, and enemy attacks
  damaged the player;
- the retained screenshot captured the IDE rather than the game and is not
  accepted as visual evidence; complete live trace replay remains pending;
- the ignored artifact's `meta.json` was corrected to record actual import,
  build, generated-test, and runtime-smoke evidence without assigning a
  benchmark result.
- a fresh disk recount matches that metadata: 272 native scene files, 28
  imported asset files, 300 UE asset files total, and 2,472,307,641 bytes;
  every recorded build, test, runtime, and visual-evidence path exists.
- the retained visual-evidence file was rechecked and shows VS Code rather
  than the game, so it remains explicitly invalid.

The recurring PowerShell `Set-PSReadLineOption` message is emitted by the local
PowerShell profile when output is redirected. It is not an Unreal failure.
UnrealBuildTool may require sandbox escalation because it rotates logs under
`C:\Users\Y4624\AppData\Local\UnrealBuildTool`. Unreal Editor Automation runs
also require writable user AppData paths for DerivedDataCache, Trace, and
logs.

## Temporary Validation Projects

All paths below are ignored by Git through `.tmp/`:

| Path | Purpose |
| --- | --- |
| `.tmp/OpenWLScriptContractTest` | Created by the legacy OpenWL script, then converted to the new framework boundary; Editor/Game compile and headless UDP runtime validation passed |
| `.tmp/AAAGameScriptMigrationTestFull` | Created by the migrated `create_project.cmd`; framework, generated fixture, Preview, and all reference plugins compile for Editor and Game |
| `.tmp/AAAGameScriptMigrationTest` | Project creation succeeded; its first in-sandbox build stopped only because UBT could not rotate the AppData log |
| `.tmp/AAAGamePlayableContractTest` | Earlier minimal manual C++ contract fixture |
| `.tmp/script_outputs` | Temporary task metadata and generated-plugin artifacts used to validate descriptor-based script operations |

Do not treat files inside `.tmp` as source. Canonical code remains under
`engine_adapters/ue5` and `test/fixtures`.

## Next Implementation Plan: FPS Mechanic Generation

Platform serving is deferred until the FPS Mechanic generation loop is
working. The next work proceeds in this order.

### Phase A - Add Engine-Native Testing [complete]

1. [complete] Add `engine_adapters/ue5/testing/` and expose it as
   `ue.testing`.
2. [complete] Implement:

   ```python
   ue.testing.run_automation_tests(
       test_filter,
       *,
       report_dir="",
       extra_args=(),
       timeout=None,
       dry_run=False,
   )
   ```

3. [complete] Treat `ue.testing` as public adapter API owned by Operators and
   Evaluators. The code Agent generates test source but does not execute this
   API or declare benchmark success.
4. [complete] Return the command, process output, structured diagnostics,
   report artifacts, and parsed test counts.
5. [complete] Add missing-configuration, dry-run, success, failed-test,
   process-failure, timeout, and report-parsing tests.
6. [complete] Compile and execute a minimal generated-style UE Automation Test
   with UE 5.4.
7. [complete] Update `ue5_api.md` after the method and tests pass.

### Phase B - Define Mechanic Agent Context [complete]

1. [complete] Add one engine-neutral Skill:

   ```text
   operators/gen_mechanic/skills/game_generation.md
   ```

2. [complete] The Skill reads the task requirement, acceptance criteria,
   generated asset descriptors, one selected Engine API Reference, and
   optional read-only examples.
3. [complete] The Skill contains no engine-specific method names, FPS
   implementation code, HUD design, or Example dependencies.
4. [complete] Add engine-neutral `system.md`, `task.md`, and `repair.md`
   prompts.
5. [complete] Require the Agent to generate engine-native gameplay source and
   engine-native gameplay test source. The Operator executes tests.

### Phase C - Add A Model-Like Agent Backend [Codex complete]

1. [complete] Keep the injected constructor parameter named `model`, matching
   existing asset Operators.
2. [complete] Add `StubAgent` and `CodexAgent` implementations of the Mechanic
   Operator's expected `model.run(request)` behavior. Claude remains optional
   future work.
3. [complete] Do not introduce a public `CodeAgentModel` class or change
   existing asset model parameter names.
4. [complete] Implement the CPU-safe Stub before a real Agent backend.

### Phase D - Implement The Mechanic Operator [Agent orchestration complete]

`GenMechanicOperator` must match the existing Operator management surface:

```python
GenMechanicOperator(
    model,
    output_dir=None,
    run_id="default",
    default_game_id=None,
)

run(inp: dict) -> dict
run_batch(inputs: list[dict]) -> list[dict]
```

The Operator owns:

- reading the task and requirement;
- resolving the standard task output directory;
- selecting the Skill, Engine API Reference, prompts, and optional Example;
- invoking the injected Agent model;
- validating generated/modified/deleted workspace reports;
- rendering generate and repair requests through the same Agent contract;
- writing `meta.json` and preserving failed workspaces.

The Agent owns concrete gameplay architecture, game-owned classes, input
mapping, movement, animation binding, actions, AI, rules, and generated test
source.

Implemented:

- task/output resolution and durable directory creation;
- engine-neutral Prompt/request assembly by API Reference path;
- direct Duck-Typed `model.run(request)` invocation;
- generated/modified/deleted file validation;
- generate/repair request and evidence persistence;
- rejection of Agent writes to `meta.json`, `demo_outputs/`, and
  `evaluation/`;
- failure artifact preservation.

Pending:

- no engine execution belongs in this Operator;
- build/test failures will enter repair mode only through a future external
  coordinator.

### Phase E - Implement The Mechanic Pipeline [generation path complete]

`pipeline/mechanic/run.py` must match the existing asset runner surface:

```python
load_model(...)
make_operator(model, output_dir=None, run_id="default",
              default_game_id=None)
generate(inp, operator)
run_from_jsonl(tasks_path, operator, game_filter=None)
main()
```

The runner keeps the standard `--game`, `--tasks`, `--run-id`, `--out-dir`,
and `--device` flags, with additive Agent backend, model, timeout, max-turn,
and explicit Engine API Reference options.

The current runner supports Stub and Codex backends, is generation-only, and
rejects the unimplemented Claude backend. Engine execution flags do not belong
in this runner.

### Phase F - Run And Preserve `fps_core_001`

1. Read `fps_core_001` and its requirement from `test_data/test_samples`.
2. Consume the provided Layer A descriptors from `fps_baseline_v1`.
3. Generate a complete UE project, copy `AAAGamePlayable` source into it, and
   generate/install a separate FPS Gameplay Plugin.
4. Use `FPSExample` only as optional read-only implementation reference.
5. Build Editor and Game targets.
6. Execute Agent-generated Automation Tests through `ue.testing`.
7. Replay the required FPS trace and capture runtime evidence.
8. Preserve successful and failed source projects.

The Stub run remains a source contract fixture. The Codex validation run
completed steps 1-6 with retained source, imported assets, successful
Editor/Game builds, and 3 passing generated tests. Those build/test steps were
executed after generation and now need to be integrated through a conforming
Evaluator plus an external bounded repair coordinator. Step 7 remains partial:
runtime startup and combat AI were observed, but the complete live trace and
valid game-window screenshots were not captured.

### Phase G - Stabilize The Mechanic Contract [P1]

After the FPS Mechanic artifact is reproducible:

1. define and verify the Mechanic state exposure contract;
2. define and verify normalized game input ownership;
3. define and verify gameplay events used by downstream artifacts;
4. define the UI binding contract without exposing concrete generated class
   internals;
5. record the stable contract in the Mechanic artifact metadata and Agent
   context.

### Phase H - Implement The UI Agent [P2]

After Phase G is complete:

1. implement `GenUIOperator`, the UI Agent backend integration, prompts,
   Skills, runner, screenshots, and metadata;
2. generate `fps_hud_001` against the stabilized Mechanic binding contract;
3. implement the required HUD, pause, victory, and failure states;
4. keep UE runtime HUD and browser/platform frontend selection explicit
   without adding a new top-level task kind.

### Phase I - Integrate The Full Game Pipeline [P3]

After the Mechanic and UI artifacts are independently reproducible:

1. integrate existing Layer A, Mechanic, and UI artifacts through
   `pipeline/full_pipeline`;
2. package and validate the final playable vertical slice;
3. implement artifact-based evaluation without triggering regeneration;
4. resume platform serving migration when required by the selected UI/runtime
   delivery path;
5. fill `z_other_serve_func.md` only after the public serving API exists.

The source `OpenWL_Avatar` worktree may contain uncommitted files. Continue to
copy/read from it without deleting, moving, resetting, or rewriting source
files.

## Conversation Reference Goal: Mechanic And UI Generation

This section records the agreed reference target for later Codex conversations.
It follows the existing README-defined structure and does not introduce new
layers, task kinds, Operators, or output directories.

### UE And Frontend Separation

- `engine_adapters/ue5` owns Unreal project, asset, world, plugin, build,
  runtime, reflection, and observation operations.
- `engine_adapters/z_other_serving` owns platform gateway, browser serving,
  Pixel Streaming integration, and frontend-facing platform operations.
- UE scripts create, import, build, and launch Unreal only. They do not launch
  the platform gateway or browser frontend.
- Platform serving accesses Unreal only through the public
  `UEClient(api_version="v1")` API. Frontend, routes, and application use cases
  must not import UE adapter internals.

### Agent API References

- Keep `agent_skills/engine_context/ue5_api.md` synchronized with the real
  public `UEClient` API and `AAAGamePlayable` Public headers.
- Complete `agent_skills/engine_context/z_other_serve_func.md` after the public
  `z_other_serving` API exists. Do not document proposed APIs as implemented
  APIs.
- Mechanic Agent skills under `operators/gen_mechanic/skills` must treat
  `ue5_api.md` as required reference context.
- UI Agent skills under `operators/gen_ui/skills` must treat
  `z_other_serve_func.md` as required reference context for browser/platform
  frontend work. UE runtime HUD work may also use `ue5_api.md`.
- The reference files describe callable APIs and boundaries. Per-game behavior
  and values continue to come from the user's requirement and task JSONL.

### Generated Gameplay Plugin Flow

The Mechanic Operator and injected Agent model follow this flow:

1. Pipeline reads one task from `test_data/test_samples` and passes it to the
   Operator without modifying the input files.
2. Operator reads the requirement, asset descriptors, `game_generation.md`,
   prompts, the selected Engine API Reference path, and optional read-only
   Example paths. Full API documents are not embedded in Prompt templates.
3. Agent generates the selected engine's game-owned extension and
   engine-native test source according to the referenced public API.
4. Agent designs game-owned input mapping, movement, animation binding,
   actions, AI, rules, and state according to the requirement.
5. Operator validates the Agent's workspace-change report and saves request,
   result, transcript, and `meta.json` under the standard
   `paths.task_output_dir()` location, including on failure.
6. A future Evaluator locates that existing artifact through
   `pipeline.common.paths`, prepares the selected engine project, imports
   dependencies, builds, tests, and captures runtime evidence through the
   Engine Adapter.
7. Structured evaluation failures may be passed back to the same Operator in
   repair mode by an external bounded coordinator.

The Agent must not manually copy adapter internals, modify
`AAAGamePlayable`, include framework Private headers, or use a framework-owned
concrete Character, Pawn, Controller, or GameMode as the generated game's base.
Concrete gameplay classes, rules, actions, AI, weapons, and state are generated
inside the separate Gameplay Plugin according to the user's requirement.

### UI Implementation Entry Gate

- `fps_hud_001` remains a read-only future task definition while P0 and P1 are
  incomplete.
- UI generation starts only after `fps_core_001` is playable, its generated
  tests pass through Evaluator-owned `ue.testing`, and runtime evidence is
  preserved.
- Mechanic must expose a stable state/event binding contract before UI code is
  generated.
- UI code must bind to that contract, not to incidental concrete fields such
  as a particular Character health member, Weapon Component ammo member, or
  inventory/GAS implementation.
- A later Mechanic refactor may change concrete classes without forcing UI
  regeneration as long as the binding contract remains compatible.

### Pipeline Placement

- `pipeline/mechanic/run.py` selects tasks, loads the Agent-backed `model`,
  injects it into `GenMechanicOperator`, batch-drives generation, and writes
  summaries.
- `GenMechanicOperator` assembles the requirement, engine reference, Skill,
  prompts, Example context, output workspace, generate/repair Agent request,
  and Agent metadata.
- The Agent request stays Mechanic-specific but engine-neutral. The selected
  API Reference determines concrete engine calls.
- `pipeline/mechanic/eval.py` must read existing Mechanic artifacts and use
  public Engine Adapter APIs without importing the generation runner.
- `pipeline/ui/run.py` performs the corresponding UI/frontend generation
  through `GenUIOperator`.
- Mechanic and UI outputs remain separate standard artifacts.
- `pipeline/full_pipeline/run.py` integrates existing asset, Mechanic, and UI
  artifacts into the final playable vertical slice. It does not construct
  `UEClient`.
- Evaluation remains separate from generation and reads the artifacts already
  written for the selected `run_id`.

### Uniform Operator And Runner Contracts

Mechanic and UI preserve the same management surface as asset generation:

```text
Operator constructor: model, output_dir, run_id, default_game_id
Operator methods: run(inp), run_batch(inputs)
Runner functions: load_model, make_operator, generate, run_from_jsonl, main
```

For Mechanic/UI, `model` is a Code Agent execution backend. Pipeline does not
special-case whether the injected model is a neural inference wrapper or a
tool-using Agent.

The Mechanic Agent result reports `generated_files`, `modified_files`, and
`deleted_files` as workspace-relative paths.

### Mechanic Output Layout

All files stay inside:

```text
test_data/outputs/<game_id>/<run_id>/mechanic/<task_id>/
```

Expected layout:

```text
<task_id>/
├── project/
│   ├── <Project>.uproject
│   ├── Config/
│   ├── Content/
│   ├── Source/
│   └── Plugins/
│       ├── AAAGamePlayable/
│       └── <GeneratedGameplayPlugin>/
├── generated_plugin/
├── launch.cmd
├── launch.sh
├── demo_outputs/
│   ├── trace.json
│   ├── trace_result.json
│   ├── build.log
│   ├── agent_transcript.jsonl
│   ├── automation/
│   └── screenshots/
└── meta.json
```

`project/` is the complete runnable game. `generated_plugin/` is the canonical
Agent-authored plugin artifact used for installation/synchronization.
`demo_outputs/` contains generated validation evidence. Failed projects and
logs are retained.

## Frozen Boundaries

- `engine_adapters/ue5` is an Unreal environment adapter, not a game generator.
- `UEClient(api_version="v1")` is the only public Python API for Agents and
  platform serving code.
- Agent code must not import UE adapter internal modules.
- The source `OpenWLPlayable` plugin is migrated as `AAAGamePlayable`, a
  Runtime Extension Framework.
- `AAAGamePlayable` must not provide a concrete Character, Pawn, Controller,
  or GameMode for generated games to inherit as their gameplay base.
- Mechanic Agents create a separate Gameplay Plugin inside the generated
  project and depend only on `AAAGamePlayable` Public headers.
- Fighter, FPS, and Racing implementations are reference examples only.
- `ue.testing` is an Operator/Evaluator capability. Agents generate test source
  but do not execute the API or declare benchmark success.
- Generated and failed project source is a durable Mechanic artifact.
- Platform serving lives under `engine_adapters/z_other_serving` and accesses
  Unreal only through `UEClient`.
- Full Pipeline orchestrates Operators and never imports `UEClient`.

## Inventory Summary

The OpenWL source currently contains:

| Scope | Tracked files | Classification |
| --- | ---: | --- |
| `serving/` | 273 | UE implementation, platform serving, Blender runtime, and shared contracts |
| `serving/engines/unreal/` | 153 | UE adapter implementation and UE-specific debug UI |
| `OpenWLPlayable` plugin | 29 | Runtime infrastructure mixed with Fighter/FPS/Racing/Preview implementations |
| `scripts/ue/` | 7 | Public create/import/run launchers |
| Game templates/examples | 47 | Arena Fighter, FPS, and Racing references |

The OpenWL source worktree has uncommitted files. Migration must copy from the
source and must not delete, move, reset, or rewrite source files.

## Classification Labels

| Label | Meaning |
| --- | --- |
| `COPY` | Move with import/path updates and focused cleanup |
| `REFACTOR` | Preserve capability but change dependencies or public boundary |
| `SPLIT` | Source file currently owns responsibilities for more than one target layer |
| `REFERENCE` | Preserve as optional Agent reference; never install automatically |
| `PLATFORM` | Move to `z_other_serving`; it must call `UEClient` |
| `SUPERSEDE` | Replace with the new stable public API |
| `DEFER` | Outside the UE5 migration scope |

## Unreal Python Migration Matrix

| OpenWL source | Target | Action | Notes |
| --- | --- | --- | --- |
| `serving/engines/unreal/config.py` | `engine_adapters/ue5/config.py` | `REFACTOR` | Separate UE engine version from UEClient API version |
| `serving/engines/unreal/environment.py` | `engine_adapters/ue5/_internal/environment.py` | `REFACTOR` | Remove concrete gameplay class defaults |
| `serving/engines/unreal/cli.py` | `engine_adapters/ue5/project/`, `build/`, `runtime/`, `scripts/` | `SPLIT` | Project/build logic stays in UE adapter; UI/Gateway launch moves to platform |
| `serving/engines/unreal/editor/transport/**` | `engine_adapters/ue5/_internal/transport/**` | `COPY` | Never exposed to Agents |
| `serving/engines/unreal/editor/asset_pipeline/**` | `engine_adapters/ue5/assets/_internal/**` | `COPY`/`REFACTOR` | Exposed only through `ue.assets` and `ue.animation` |
| `serving/engines/unreal/editor/control/**` | `engine_adapters/ue5/world/_internal/`, `runtime/_internal/`, `observe/_internal/` | `SPLIT` | Existing `UEClient` is only a partial Editor facade |
| `serving/engines/unreal/editor/commands/**` | `engine_adapters/ue5/_internal/commands/**` | `REFACTOR` | Replace dependencies on platform request/result DTOs |
| `serving/engines/unreal/inspection/**` | `engine_adapters/ue5/assets/_internal/inspection/**` | `COPY` | Public access through asset query/validation methods |
| `serving/engines/unreal/project_content.py` | `engine_adapters/ue5/assets/_internal/project_content.py` | `COPY`/`REFACTOR` | Project Content scan and registry reconciliation |
| `serving/engines/unreal/services/asset_service.py` | `engine_adapters/ue5/assets/_internal/service.py` | `COPY`/`REFACTOR` | Primary asset import implementation |
| `serving/engines/unreal/services/effect_*` | `engine_adapters/ue5/assets/_internal/effects/` | `COPY`/`REFACTOR` | Keep package validation and safe staging |
| `serving/engines/unreal/services/material_binding_service.py` | `engine_adapters/ue5/bindings/_internal/materials.py` | `COPY` | Public through `ue.bindings` |
| `serving/engines/unreal/services/scene_*` | `engine_adapters/ue5/world/_internal/` and `assets/_internal/scenes/` | `SPLIT` | Separate import/package parsing from world operations |
| `serving/engines/unreal/services/native_*` | `engine_adapters/ue5/assets/_internal/native_content/` | `COPY` | Preserve archive/path traversal checks |
| `serving/engines/unreal/services/runtime_*_bridge_service.py` | `engine_adapters/ue5/runtime/_internal/bridge/` | `COPY`/`REFACTOR` | Remove concrete playable character assumptions |
| `serving/engines/unreal/services/runtime_session_service.py` | `engine_adapters/ue5/runtime/_internal/session.py` | `REFACTOR` | Keep controller/entity state; expose through `ue.runtime` |
| `serving/engines/unreal/services/player_session_service.py` | `engine_adapters/ue5/runtime/_internal/` and `z_other_serving` | `SPLIT` | UE process/ports stay in adapter; browser/platform lifecycle moves to serving |
| `serving/engines/unreal/services/pixel_streaming_server.py` | `engine_adapters/ue5/runtime/_internal/streaming.py` and `z_other_serving` | `SPLIT` | UE signalling process support vs. frontend/viewer ownership |
| `serving/engines/unreal/services/import_*viewer_service.py` | `engine_adapters/z_other_serving` | `PLATFORM` | Viewer process orchestration is platform UI |
| `serving/engines/unreal/world/**` | `engine_adapters/ue5/world/_internal/**` | `COPY`/`REFACTOR` | Keep current WorldSpec/package behavior behind UEClient |
| `serving/engines/unreal/runtime/commands/**` | `engine_adapters/ue5/runtime/_internal/commands/**` | `REFACTOR` | Remove fixed punch/kick/racing request handling |
| `serving/engines/unreal/adapter.py` | `engine_adapters/ue5/ue_client.py` and private composition | `SUPERSEDE` | Old platform EngineAdapter is not the Agent API |
| `serving/engines/unreal/capabilities.py` | UEClient contract metadata if needed | `SUPERSEDE` | No multi-engine capability abstraction required |
| `serving/engines/unreal/gateway_debug/**` | `engine_adapters/z_other_serving` | `PLATFORM` | Rewrite to use UEClient, not internal services |
| `serving/ue_client.py` | none | `SUPERSEDE` | Old file contains only `NotImplemented` stubs |
| `serving/engines/unreal/editor/control/client.py` | private implementation input | `SUPERSEDE` | Must not remain a second public UEClient |

## Cross-Package Dependencies To Remove

The Unreal implementation currently imports platform-owned packages:

| Dependency | Import occurrences | Resolution |
| --- | ---: | --- |
| `serving.contracts` | 12 | Define UEClient v1 request/result contract inside the UE adapter |
| `serving.paths` | 8 | Replace with UE adapter configuration/path services |
| `serving.core` | 4 | Internalize only the artifact/world data required by UEClient |

After migration, `engine_adapters/ue5` must not import
`engine_adapters/z_other_serving`.

## OpenWLPlayable To AAAGamePlayable C++ Classification

### Keep And Refactor As Runtime Framework

| Current file | Action | Required change |
| --- | --- | --- |
| `OpenWLPlayableModule.*` | `COPY` | Keep module bootstrap |
| `OpenWLRuntimeSubsystem.*` | `REFACTOR` | Remove Preview Character/GameMode coupling |
| `OpenWLRuntimeInputReceiver.*` | `REFACTOR` | Keep transport/envelope/readiness; remove Fighter commands and concrete actor classes |
| `OpenWLWorldSessionManager.*` | `REFACTOR` | Replace `AOpenWLPlayableCharacter` creation/control with interfaces, factories, and generic entity bindings |
| `OpenWLPlayerState.*` | `REFACTOR` | Replace concrete PlayerState requirement with identity data/component contract |

Target Public header layout:

```text
Source/AAAGamePlayable/Public/
├── Interfaces/
├── Subsystems/
├── Components/
└── DataTypes/
```

Generated plugins may include only these Public headers. Private headers are
not part of the Contract.

### Move Out Of Runtime Framework

| Current file | Classification | Destination |
| --- | --- | --- |
| `OpenWLPlayableCharacter.*` | Fighter/FPS gameplay plus concrete movement/camera | Reference gameplay plugins |
| `OpenWLPlayerController.*` | Fighter/FPS/Racing key and action mapping | Reference gameplay plugins |
| `OpenWLGameMode.*` | Arena/FPS/Racing rules and spawning | Reference gameplay plugins |
| `OpenWLFighterHUD.*` | Fighter/FPS/Racing HUD | Reference gameplay plugins |
| `OpenWLArcadeVehiclePawn.*` | Racing implementation | Racing reference plugin |
| `OpenWLPreviewCharacter.*` | Asset preview tooling | Separate adapter-owned Preview tooling plugin |
| `OpenWLPreviewGameMode.*` | Asset preview tooling | Separate adapter-owned Preview tooling plugin |
| `OpenWLPreviewPlayerController.*` | Asset preview tooling | Separate adapter-owned Preview tooling plugin |

The reference implementations must not participate in UEClient, must not be
installed automatically, and must not be dependencies of `AAAGamePlayable`.

## Current Hard-Coded Gameplay Coupling

The following must be removed before the Runtime Framework boundary is valid:

- `DEFAULT_PLAYABLE_CLASS_PATH` points to
  `/Script/OpenWLPlayable.OpenWLPlayableCharacter`.
- Project creation writes
  `GlobalDefaultGameMode=/Script/OpenWLPlayable.OpenWLGameMode`.
- Runtime launch forces `/Script/OpenWLPlayable.OpenWLGameMode`.
- Preview launch forces `/Script/OpenWLPlayable.OpenWLPreviewGameMode`.
- Presentation and runtime bridge scripts spawn
  `OpenWLPlayableCharacter` directly.
- `RuntimeInputReceiver` implements Fighter actions and restart behavior.
- `RuntimeInputReceiver` creates `OpenWLPlayableCharacter` and
  `OpenWLPreviewCharacter` directly.
- `WorldSessionManager` creates and controls `OpenWLPlayableCharacter`.
- Runtime session commands carry punch, kick, racing steering, throttle,
  boost, and handbrake fields.
- Player frontend maps J/K/F/R to Fighter/FPS-specific actions.

## Platform Serving Migration Matrix

| OpenWL source | Target | Action |
| --- | --- | --- |
| `serving/gateway/**` | `engine_adapters/z_other_serving/gateway/**` | `PLATFORM` |
| `serving/gateway/frontend/**` | `engine_adapters/z_other_serving/frontend/player/**` | `PLATFORM` |
| `serving/engines/unreal/gateway_debug/import_ui.py` | `engine_adapters/z_other_serving/frontend/asset_admin/` | `PLATFORM` |
| `serving/application/**` | `engine_adapters/z_other_serving/application/**` | `REFACTOR` |
| `serving/client/**` | `engine_adapters/z_other_serving/client/**` | `REFACTOR` |
| `serving/contracts/**` | `engine_adapters/z_other_serving/contracts/**` | `REFACTOR` |
| `serving/core/assets`, `artifacts`, `sessions`, `worlds` | `engine_adapters/z_other_serving/domain/**` | `REFACTOR` |
| `serving/core/games/**` | UE reference examples | `REFERENCE` |
| `serving/infrastructure/**` | `engine_adapters/z_other_serving/infrastructure/**` | `PLATFORM` |
| `serving/bootstrap.py` | `engine_adapters/z_other_serving/bootstrap.py` | `REFACTOR` |
| `serving/paths.py` | split UE/platform configuration | `SPLIT` |
| `serving/docs/**` | design reference during Runtime Contract extraction | `REFERENCE` |
| `serving/blender_runtime/**` | future Blender adapter work | `DEFER` |

The migrated platform composition root may construct `UEClient`, but no
platform route, application use case, or frontend service may import UE
internal modules.

## Scripts And Examples

| Source | Target | Action |
| --- | --- | --- |
| `scripts/ue/create_project.*` | `scripts/ue/` + `engine_adapters/ue5/cli.py` | `COMPLETE`: wrapper calls public-UEClient CLI |
| `scripts/ue/import_asset.*` | `scripts/ue/` + `engine_adapters/ue5/cli.py` | `COMPLETE`: descriptor-based import only |
| `scripts/ue/run.*` | `scripts/ue/` + future platform launcher | `SPLIT`: Unreal launch complete; platform launch pending |
| Fighter concrete C++ behavior | `engine_adapters/ue5/examples/ArenaFighterExample/` | `COMPLETE` reference plugin |
| FPS concrete C++ behavior | `engine_adapters/ue5/examples/FPSExample/` | `COMPLETE` reference plugin |
| Racing concrete C++ behavior | `engine_adapters/ue5/examples/RacingExample/` | `COMPLETE` reference plugin |
| `examples/games/**` | matching reference example directories | `REFERENCE` |
| `scripts/games/generate.py` | reference example tooling | `REFERENCE` |

## Test Migration Matrix

| Test group | Destination/role |
| --- | --- |
| Asset/effect/scene/material/PLY/Gaussian tests | `test/engine_adapters/ue5/` |
| Unreal CLI tests | UEClient project/build/runtime tests |
| Serving client tests | `z_other_serving` tests |
| GameSpec Arena/FPS/Racing tests | Reference example tests |
| Existing `test_ue_serving.py` | Split into UE environment and platform serving tests |
| New Runtime Framework test | Compile a minimal generated-style Gameplay Plugin using Public headers only |
| Preview/reference plugin boundary | Static dependency tests plus UE 5.4 Editor/Game compilation |

Untracked OpenWL tests for effect import, GameSpec, Gaussian splats, PBR
materials, PLY meshes, serving client, and Unreal CLI are part of the migration
inventory and must not be lost.

## UEClient v1 Public Surface Categories

The inventory supports the following stable facade groups:

```text
ue.project
ue.assets
ue.animation
ue.bindings
ue.world
ue.reflection
ue.plugin
ue.build
ue.testing
ue.runtime
ue.observe
```

`ue.testing` executes engine-native Automation Tests for Operators and
Evaluators. Game-generation Agents generate compatible test source but do not
invoke the testing namespace or declare benchmark success.

Implementation modules may change with Unreal versions. Agents, Skills,
platform serving, and generated project automation may depend only on:

```text
from engine_adapters.ue5 import UEClient
```

## Migration Order For Implementation

1. [complete] Establish the UEClient v1 package shell and stable result
   contract.
2. [complete] Move transport/configuration internals without exposing them.
3. [complete] Move asset import, validation, registry, scene, material, and
   effect logic.
4. [complete] Split project/build/runtime process logic and public scripts out
   of the existing CLI/services.
5. [complete] Refactor the source `OpenWLPlayable` plugin into the
   `AAAGamePlayable` Public Contract.
6. [complete] Move Preview tooling and game-specific code out of the base
   plugin into optional Preview/reference plugins.
7. [pending after FPS demo] Rewrite platform serving composition to use only
   UEClient.
8. [complete] Port tests and compile the minimal GeneratedGameplayPlugin
   fixture.

## Step-One Exit Criteria

This inventory is complete when:

- every OpenWL Unreal top-level package has a target and action;
- every current OpenWLPlayable class is classified;
- platform and UE dependency violations are recorded;
- source tests, including untracked tests, are accounted for;
- the next implementation step can start without moving source files blindly.
