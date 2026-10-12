# samples/

3AGameFactory test set — **one directory per game project**, plus cross-game
aggregate jsonls. Read-only input; generated artifacts go to
`../outputs/<game_id>/...` (same first axis — see `../outputs/README.md`).

## Game projects

`game_id` is `game<Letter>_<theme>_<engine>`. The **letter identifies the theme**,
so the same game targeting two engines shares a letter and differs only in the
engine suffix:

| game_id | Genre | Visual reference | Engine |
|---------|-------|------------------|--------|
| `gameA_fighting_arena_unity` | 2.5D versus fighting, multi-level arena | Mortal Kombat | Unity3D 2022.3 URP |
| `gameA_fighting_arena_ue` | 1v1 fighting, open-air arena | Mortal Kombat | Unreal Engine 5 |
| `gameB_forest_adventure_unity` | Open-world action RPG, exploration + combat | Zelda BotW | Unity3D 2022.3 URP |
| `gameB_forest_adventure_ue` | Third-person exploration RPG, no combat | Zelda BotW | Unreal Engine 5 |
| `gameC_fps_tactical_unity` | FPS tactical shooter, urban counter-terrorism | Call of Duty | Unity3D 2022.3 URP |
| `gameC_fps_tactical_ue` | FPS tactical shooter, single player vs AI | Call of Duty | Unreal Engine 5 |
| `gameD_racing_unity` | Circuit racing, 1 player + 3 AI | — | Unity3D 2022.3 URP |

Engine variants sharing a letter are **separate projects with their own art
direction and scope**, not two builds of one game. They are kept apart because
their `general_requirement.txt` genuinely differ (e.g. `gameA_*_unity` is a
Japanese-courtyard arena with ninja weapons, `gameA_*_ue` a medieval arena with
bare-fist boxing).

The engine is *also* carried by the `engine` field on every `mechanic` / `ui`
task line (`unity3d` / `ue5`); the suffix in `game_id` exists so the two variants
can hold different requirement documents and land in different output directories.

## Layout

```
samples/
├── gameA_fighting_arena_unity/       ← one directory per game project
│   ├── general_requirement.txt       ← overall spec of the game
│   ├── 3D_object/
│   │   ├── requirement.txt
│   │   ├── ref_images/               ← concept-art references
│   │   └── object_tasks.jsonl        ← one line per 3D-object task
│   ├── tpose/
│   │   ├── requirement.txt
│   │   ├── ref_images/               ← character references
│   │   └── tpose_tasks.jsonl
│   ├── motion/
│   │   ├── requirement.txt
│   │   ├── ref_videos/
│   │   └── motion_tasks.jsonl        ← rigging, generation, download, retarget
│   ├── cg_video/
│   │   ├── requirement.txt
│   │   ├── ref_images/               ← optional image references / keyframes
│   │   ├── ref_videos/               ← optional video references
│   │   ├── ref_audio/                ← optional audio references
│   │   └── cg_tasks.jsonl
│   └── audio/
│       ├── requirement.txt
│       ├── ref_audio/                ← optional voice / sound references
│       └── audio_tasks.jsonl
│
├── gameA_fighting_arena_ue/          ← same five task dirs, UE5 variant
├── gameB_forest_adventure_unity/  ·  gameB_forest_adventure_ue/
├── gameC_fps_tactical_unity/      ·  gameC_fps_tactical_ue/
├── gameD_racing_unity/
│
└── *_collect.jsonl                   ← cross-game aggregate jsonls
    ├── 3D_object_gen_collect.jsonl
    ├── tpose_gen_collect.jsonl
    ├── motion_gen_collect.jsonl
    ├── cg_video_collect.jsonl
    └── audio_gen_collect.jsonl
```

`3D_scene`, `mechanic`, `ui` and `pipeline` are no longer registered task
kinds: they described generating scenes, gameplay code and UI code, and no
runner for any of them exists. Every kind below is an asset kind.

Directory names and task-list filenames are registered in
`pipeline/common/paths.py` (`TASK_INPUT_DIR`, `TASK_JSONL`, `TASK_COLLECT_JSONL`).
Renaming one here means updating that table. The nine task kinds in that table are
the whole set — rigging, text-to-motion, library downloads, and retargeting all
live under `motion/`, selected by `task_type` on the task line.

## Task line schema

Every line in a `*_tasks.jsonl` / `*_collect.jsonl` should carry:

| Field | Purpose |
|-------|---------|
| `game_id` | Which game project this task belongs to → selects the output directory. Must match the directory the file sits in. |
| `task_id` | Unique within its `(game_id, task_kind)` → names the output directory. |
| `engine` | Which engine a task targets: `unity3d` or `ue5`. Present on tasks that feed an engine importer. |

Everything else is task-specific (`image_path`, `prompt`, `description`, `seed`, …).
Paths are written **relative to the repo root**.

```jsonc
{"game_id": "gameA_fighting_arena_unity", "task_id": "demoFighting_001",
 "image_path": "outputs/samples/gameA_fighting_arena_unity/3D_object/ref_images/warrior_tpose.png",
 "prompt": "High-detail realistic male arena fighter, clean symmetrical T-pose ...", "seed": 42}
```

A per-game `*_tasks.jsonl` and the cross-game `*_collect.jsonl` hold the same
lines. `run.py --game <id>` prefers the former and falls back to filtering the
latter by `game_id`.

Some task lines consume the *output* of an earlier stage — e.g. a `motion` task's
`target_glb_path` points at
`outputs/runs/<game_id>/default/assets/3d_object/<task_id>/model.glb`. Those
paths only exist after the corresponding generation step has run.

## Current status

| game_id | 3D_object | tpose | motion | cg_video | audio |
|---------|----------:|------:|-------:|---------:|------:|
| `gameA_fighting_arena_unity` | 7 | 2 | 14 | 6 | 22 |
| `gameA_fighting_arena_ue` | 3 | – | 10 | – | – |
| `gameB_forest_adventure_unity` | 8 | 3 | 14 | 1 | 12 |
| `gameB_forest_adventure_ue` | 4 | – | 11 | – | – |
| `gameC_fps_tactical_unity` | 6 | 1 | 16 | 1 | 7 |
| `gameC_fps_tactical_ue` | 3 | – | 8 | – | – |
| `gameD_racing_unity` | 2 | – | – | – | – |

(task-line counts, read from the jsonl files; `–` = no tasks yet)

The Unity variants carry detailed asset `requirement.txt` files; the UE variants
currently hold one-line placeholders and reuse prepared assets
(`source_mode: provided_or_reused_local_fixture`), so their asset requirements are
**not** authored yet. If you add asset generation to a UE variant, write its
`requirement.txt` properly rather than copying the Unity one — the two have
different art direction.

## Reference images and assets

Some task JSONL files reference `ref_images/` paths under `outputs/samples/`.
These images are **not** stored in the repository to keep it lightweight.

Reference images for all test sample games are collected in the GitHub issue:
**[#47 — Reference images for test samples](https://github.com/OpenDCAI/GameFactory-3A/issues/47)**

Download and place them into the corresponding `ref_images/` directories to match
the paths referenced in the task JSONL files.

Additional free character and motion assets can be downloaded from
[Mixamo](https://www.mixamo.com/) (Adobe, free Adobe ID required). Mixamo
provides public rigged characters and a large library of motion clips that can
be used as alternative or supplementary inputs for the 3D object, T-pose, and
motion tasks.
