# outputs/

```
outputs/
├── samples/   ← read-only task inputs, one directory per game project
└── outputs/        ← generated artifacts, same `<game_id>` first axis
```

## Status

`samples/` provides several game-project test cases, including fighting,
exploration RPG, tactical FPS, and racing examples, for users to try the
pipelines and reproduce the demo results.

Each game directory contains its requirements and task lists; the corresponding
`*_collect.jsonl` files support running a task type across multiple games. Some
tasks reference external media or earlier generated artifacts, so place the
required files in the documented paths before running them.

`outputs/` is created at runtime under `outputs/<game_id>/<run_id>/...` to store
the generated artifacts and evaluation results.

## You do not need a prepared test case

The Skills are complete. Hand a coding agent
`<REPO_PATH>/agent_skills/setting_overview.md` together with your game
requirement — in **any format** (a sentence, a bullet list, a design doc, a
reference image folder) — and the agent produces good results on its own: it
reads the entry-point skill, routes itself to the right asset skill and engine
API context, and calls the pipelines.

```text
1. Open a coding agent, such as Codex, Claude Code, or another compatible agent.
2. cd <REPO_PATH>
3. Give the agent your game requirement and ask it to read
   agent_skills/setting_overview.md first.
```

Use `samples/` when you want a fixed, reproducible input for pipeline-level
runs and regression comparison; use the agent path for actually generating a
game.
