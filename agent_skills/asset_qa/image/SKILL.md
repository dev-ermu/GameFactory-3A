# Image preparation and T-pose generation Skill

Use this Skill when a game plan needs a **single-subject concept image**, a
character reference cleaned for image-to-3D, or a **front-facing transparent
T-pose image** for downstream character reconstruction. T-pose generation is an
image-generation and image-editing task; it is not a separate asset category.

## Scope and handoff

| Need | Route | Next step |
|---|---|---|
| Single-object concept art for reconstruction | `<REPO_PATH>/models/gen_image/sdxl_turbo.py` | Review image, then use `<REPO_PATH>/agent_skills/asset_qa/3d_object/SKILL.md` |
| Convert an existing character image into a T-pose | `<REPO_PATH>/pipeline/assets_gen/gen_tpose_image/run.py` | Use the transparent PNG as input to the selected 3D-object or motion workflow |
| Validate a generated T-pose | This Skill | Confirm pose, identity, silhouette, alpha, framing, and style before handoff |

Do not use multi-view sheets, collages, multiple characters, busy scenery,
watermarks, floor shadows, or cropped limbs as input to an image-to-3D workflow.
They tend to become fused geometry, baked texture, or missing body parts.

## Models and pipeline

| Component | Location | Responsibility |
|---|---|---|
| Concept image model | `<REPO_PATH>/models/gen_image/sdxl_turbo.py` | Fast single-object text-to-image concept art; tuned for reconstruction inputs |
| Image editor (local) | `<REPO_PATH>/models/gen_image/qwen_edit_model.py` | Turns a supplied character reference into a white-background T-pose render |
| Image editor (cloud API) | `<REPO_PATH>/models/gen_image/seedream_model.py` | Uses Seedream image editing as a swappable T-pose generation backend |
| Task operator | `<REPO_PATH>/operators/gen_tpose_image/operator.py` | Reads a task, generates the T-pose, saves artifacts and metadata |
| Runner | `<REPO_PATH>/pipeline/assets_gen/gen_tpose_image/run.py` | Loads models, accepts CLI/JSONL tasks, and writes result summaries |

can be changed to Seedream `doubao-seedream-5-0-260128` while keeping the same
Local model weights are downloaded on first use unless checkpoint flags point to

**Prefer the Seedream cloud route** when the user permits paid generation; local
first call **pause and follow *Paid cloud backend* in
`<REPO_PATH>/agent_skills/asset_qa/README.md`**: send the purchase/API-key page
(<https://console.volcengine.com/ark>), state the estimated cost for the planned
image count including retries, ask the user to buy access and supply
`ARK_API_KEY`, and wait for an explicit answer.

## Install the image environment


```bash
bash scripts/asset_env_setup/image/qwen_image_install.sh
conda activate qwen_image
```

Install only the shared HTTP and smoke-test dependencies for cloud wrappers:

```bash
bash scripts/asset_env_setup/image/cloud_api_install.sh
```

## Plan the image before generating

For each requested image, record the asset role, visual style, camera/view,
intended downstream use, desired silhouette, material cues, and acceptance
criteria. For a T-pose input, provide one clearly visible character reference
and a description of appearance, costume, colors, and important accessories.

The T-pose editor preserves the input appearance while requesting this fixed
result: upright character, arms horizontal at shoulder height, directly facing
forward, flat white background, no scenery, no cast shadow, and clean game-art
presentation. The pipeline then removes the background, crops the foreground,
pads it to a square, and resizes it for reconstruction.

## Generate concept art for 3D reconstruction

`SDXLTurboModel` is for fast **single-object concept art**, not final game art.
It defaults to a square 512 px image and a negative prompt that excludes
turnarounds, duplicate subjects, crops, ground planes, shadows, text, and busy
backgrounds—details that harm 3D reconstruction.

```python
from models.gen_image.sdxl_turbo import SDXLTurboModel

model = SDXLTurboModel(model_path="stabilityai/sdxl-turbo", device="cuda")
image = model.generate(
    prompt="a single stylized brass-and-wood treasure chest, centered, full object visible",
    seed=42,
)
image.save("/absolute/path/chest.png")
model.unload()
```

Keep only one subject in frame. If the result will be converted to 3D, review
it before calling the 3D-object Skill rather than trying to repair bad geometry
later.

## Generate a T-pose image

### Single image

Run from the repository root:

```bash
python pipeline/assets_gen/gen_tpose_image/run.py \
  --game gameA_cyberpunk_shooter \
  --run-id auto \
  --image /absolute/path/character_reference.png \
  --task-id character_tpose_001 \
  --description "Full-body cyberpunk scout, teal jacket, red utility belt, boots, and visor." \
  --seed 42 \
  --steps 40 \
  --target-size 1024
```

### JSONL batch

Use `--tasks` for an explicit task file or `--game` to resolve that game's task
list. A task supports `image_path` (or an in-memory PIL `image` for Python
callers), `game_id`, `task_id`, `description`, `seed`, `steps`, `target_size`,
and `save_intermediate`.

```json
{"game_id":"gameA_cyberpunk_shooter","task_id":"luffy_tpose_001","image_path":"test_data/test_samples/gameA_cyberpunk_shooter/tpose/ref_images/luffy.jpg","description":"Monkey D. Luffy wearing his iconic red vest and straw hat.","seed":42,"steps":40,"target_size":1024}
```

```bash
python pipeline/assets_gen/gen_tpose_image/run.py \
  --tasks /absolute/path/tpose_tasks.jsonl \
  --run-id auto
```

Optional backend/model overrides and segmentation choice:

```bash
python pipeline/assets_gen/gen_tpose_image/run.py \
  --gen-backend qwen_edit \
  --gen-ckpt Qwen/Qwen-Image-Edit-2511 \
  --device cuda \
  --tasks test_data/test_samples/tpose_gen_collect.jsonl \
  --run-id auto

export ARK_API_KEY="your-key"
python pipeline/assets_gen/gen_tpose_image/run.py \
  --gen-backend seedream \
  --gen-ckpt doubao-seedream-5-0-260128 \
  --device cuda \
  --tasks test_data/test_samples/tpose_gen_collect.jsonl \
  --run-id auto
```

Use `--mask-type depth --mask-ckpt LiheYoung/depth-anything-small-hf` only
legacy flat-output mode for debugging; do not use it for game deliverables.

## Outputs and metadata

The current registered task kind remains `tpose`, so standard artifacts are:

```text
test_data/outputs/<game_id>/<run_id>/assets/tpose/<task_id>/
├── tpose_fg.png   # transparent-background deliverable
├── tpose.png      # white-background intermediate, unless save_intermediate=false
└── meta.json       # source, models, seed, steps, size, and task metadata
```

Use `<REPO_PATH>/pipeline/common/paths.py` and preserve this task-kind layout. The Skill is
named `image` for agent routing; it does not rename existing pipeline APIs or
artifact paths.

## Validation and QA

Run free contract checks before loading production checkpoints or spending API
credits:

```bash
python tests/harness/smoke.py --kind tpose
python tests/harness/smoke.py --kind tpose --backend seedream
```

The smoke harness uses stub models, requires only `pillow`, `numpy`, and `scipy`,
and leaves no production output after success. Run the local checkpoint integration

```bash
python -m unittest test.test_gen_tpose_image -v
```

Run the paid Seedream integration against the same canonical task JSONL and the

```bash
export ARK_API_KEY="your-key"
export AAAGF_RUN_SEEDREAM_LIVE=1
export SEEDREAM_MODEL="doubao-seedream-5-0-260128"
python -m unittest test.test_api_gen_tpose_image -v
```

Review every production image at full size before handoff:

1. **Pose and framing:** upright full body; both arms horizontal; feet, hands,
   head, and accessories visible; no crop or duplicate body parts.
2. **Facing and identity:** direct front view; readable facial/body orientation;
   costume, colors, and key accessories retained from the reference.
3. **Background and alpha:** no scenery, floor shadow, halo, or opaque white
   rectangle; inspect the transparent PNG on both light and dark backgrounds.
4. **Reconstruction readiness:** one centered subject with a clear silhouette;
   avoid excessive pose asymmetry, motion blur, text, watermarks, and tiny props.
5. **Style:** image must follow the planned game style before it is consumed by
   3D or motion generation.

If any check fails, improve the source image or description, change the seed,
regenerate, and re-review. Do not compensate for a reversed or malformed image
only through downstream mesh rotations or gameplay code.
