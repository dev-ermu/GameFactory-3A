# `agent_skills/asset_qa` — asset generation and visual QA

This directory contains the asset-generation and quality-assurance Skills used
by a vision-capable coding agent. Use it after the game plan identifies an asset
need and before declaring that generated or imported content is ready to ship.

`<REPO_PATH>/agent_skills/asset_qa/` covers the parts of asset work that require visual or
runtime judgement: whether a mesh faces the right direction, has plausible
scale, fits the requested style, or produces a usable animation in-game. File
parsing and structural checks alone cannot answer these questions.

Paths are written from the repository root as `<REPO_PATH>/...`; see the Path
convention section of `<REPO_PATH>/agent_skills/setting_overview.md`.
`<REPO_PATH>/engine_adapters/`, `<REPO_PATH>/pipeline/`, `<REPO_PATH>/scripts/`,
and `<REPO_PATH>/test_data/` are siblings of `<REPO_PATH>/agent_skills/`, not
subdirectories of it.

## Skill map

| Asset task | Skill | Use it for |
|---|---|---|
| Image preparation and T-pose generation | `<REPO_PATH>/agent_skills/asset_qa/image/SKILL.md` | Single-object reconstruction inputs, character T-pose images, alpha preparation, and image QA |
| 3D object generation and review | `<REPO_PATH>/agent_skills/asset_qa/3d_object/SKILL.md` | Props, avatars, weapons, mesh quality, provenance, facing, scale, and ship-readiness |
| Motion | `<REPO_PATH>/agent_skills/asset_qa/motion/SKILL.md` | Rigging, generation/fetch, retargeting, import, and in-game motion review |
| CG video | `<REPO_PATH>/agent_skills/asset_qa/cg_video/SKILL.md` | CG prompt direction, backend selection, generation, artifact layout, and video QA |

Read the selected engine contract from `<REPO_PATH>/agent_skills/engine_context/` before
importing an approved asset or scene. The engine documents define formats,
coordinate conventions, public APIs, project structure, and runtime validation.

## Environment setup

One virtual environment, one dependency file. Every asset task uses the same
Python dependencies, so there is no per-task installer.

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # Linux / macOS
pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
```

`requirements.txt` pins exact versions. That is the whole dependency surface:
every backend is a cloud API reached over HTTP, so there is no local model, no
checkpoint path, and nothing to download.

| Asset task | Extra setup |
|---|---|
| Image / T-pose | See `<REPO_PATH>/agent_skills/asset_qa/image/SKILL.md` |
| 3D object | — |
| Motion | Blender for retargeting: `<REPO_PATH>/scripts/engine_install/blender/install.sh` |
| Audio | — |
| CG video | — |

Verify without spending credits or touching the network:

```bash
python tests/harness/smoke.py --kind 3d_object --backend tripo
python tests/test_api_3d_object.py
python tests/harness/smoke.py --kind tpose --backend seedream
python tests/harness/smoke.py --kind audio --backend seed_audio
python tests/test_api_audio.py
python tests/harness/smoke.py --kind cg_video --backend seedance
python tests/harness/smoke.py --kind motion
```

## Paid cloud backend: ask the user before spending

For the mature asset types — **3D object, image/T-pose, audio, CG video** — the
closed-source cloud APIs are the recommended first choice, because they are
materially more reliable than the local/open routes. They also spend the user's
money, so the agent must **stop and ask** rather than assume a key exists.

| Asset task | Preferred paid backend | Purchase / API-key page | Env var |
|---|---|---|---|
| 3D object | Tripo, then Meshy | <https://platform.tripo3d.ai/api-keys>, <https://www.meshy.ai/api> | `TRIPO_API_KEY`, `MESHY_API_KEY` |
| Image / T-pose | Seedream via Volcengine Ark | <https://console.volcengine.com/ark> | `ARK_API_KEY` |
| Audio | Seed Audio via Volcengine | <https://console.volcengine.com/speech/> | `SEED_AUDIO_API_KEY` |
| CG video | Seedance via Ark, then MiniMax Hailuo | <https://console.volcengine.com/ark>, <https://platform.minimax.io/user-center/basic-information/interface-key> | `ARK_API_KEY`, `MINIMAX_API_KEY` |

Every one of these goes into **`<REPO_PATH>/.env`**, the single configuration
file (`cp .env.example .env`), read by `<REPO_PATH>/config.py`. Each
provider needs **both** its `*_API_BASE` and its `*_API_KEY`; the base URL is
required and has no silent default, because the public endpoint is not reachable
from every network.

There is no local fallback for these asset types. The repository does not
download model weights, and every listed backend runs server-side: no GPU, no
local checkpoints, no disk budget. Fill the provider's `*_API_BASE` and
`*_API_KEY` in `.env`; the Pipeline runners refuse to start while either is
unset, so a missing key surfaces immediately rather than mid-task.

Before the first paid call:

1. **Pause.** Do not run a paid backend, and never invent, guess, or reuse a key
   from an unrelated source.
2. **Ask in one message**, containing: the recommended provider and why; the
   purchase/API-key URL above; the provider's current pricing page (linked from
   that console) with your **estimated cost for this batch** — unit price × task
   count, seconds, or resolution, plus an allowance for retries; and an explicit
   request that the user buy access and hand you the key.
3. **Wait for an explicit answer.** Spending is the user's decision, not a
   default.
4. **If approved**, prefer that the user exports the key themselves; otherwise
   set it only in the session environment. Never put a key in a JSONL, task
   metadata, cache key, log, or commit.
5. **If declined, or the budget does not allow it**, say so and report the gap.
   There is no local route to fall back to, so state plainly which asset type
   cannot be produced and why, rather than silently downgrading quality.
6. Run the Skill's free smoke/contract check before spending credits, and
   re-confirm with the user before an unusually large or repeated batch.

## Review workflow

1. Start from the approved game plan and its stated style, role, and acceptance
   criteria for the asset.
2. Generate or obtain the asset through the selected route. Prefer reliable
   closed-source/cloud APIs for mature asset types such as 3D objects — getting
   the user's approval and key first, per *Paid cloud backend* above. For
   immature routes such as motion or 3D scenes, prefer suitable licensed assets
   from the selected engine's asset library when they provide a better shippable
   result.
3. Run the task-specific structural checks and the selected Skill’s visual QA.
4. Import the asset using the selected `<REPO_PATH>/agent_skills/engine_context/` contract.
5. Run the asset in the target game, exercise relevant player actions, and
   review a low-resolution capture for orientation, attachment, animation,
   clipping, scale, material, VFX, lighting, and style issues.
6. Iterate until the asset meets its planned acceptance criteria. Keep source
   and licence/provenance information with externally sourced assets.

## Where generated results and tests live

- All generated game results belong under `<REPO_PATH>/test_data/outputs/`, organized by
  game, run, task kind, and task id. Use `<REPO_PATH>/pipeline/common/paths.py`; never
  hand-construct output paths.
- Mechanics and UI belong under each game's run directory, for example
  `<REPO_PATH>/test_data/outputs/gameA_cyberpunk_shooter/default/mechanic/<task_id>/` and
  `<REPO_PATH>/test_data/outputs/gameA_cyberpunk_shooter/default/ui/<task_id>/`. Do not
  create root-level `<REPO_PATH>/test_data/outputs/mechanic/` or `<REPO_PATH>/test_data/outputs/ui/`
  directories.
- `<REPO_PATH>/test/` contains runnable, current-use test and smoke scripts. Agents should
  use the relevant test to verify that generated assets, game code, or adapter
  flows can actually run; a written file alone is not evidence of success.
- `<REPO_PATH>/third_party/` holds externally cloned repositories such as `trimesh` and
  engine material/asset packs. Treat its contents as external dependencies: do
  not modify or redistribute them, and check each upstream licence and setup
  instructions before use.

## Why visual QA is required

The adapter can validate format, hierarchy, triangle count, bounding box, and
animation structure. It cannot determine whether a symmetric mesh faces the
correct way, whether an unseen reconstruction is usable, whether wheel or weapon
attachments are positioned correctly, or whether an animation looks natural.
A vision model or human review of rendered previews and gameplay capture is
therefore required before a visual asset is accepted.

For motion clips, retain the source/licence metadata next to the motion asset
and do not ship non-commercial sources in a product build.
