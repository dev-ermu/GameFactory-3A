# operators/

Task **operators** — one per asset-generation task type.

Each operator directory has a uniform layout:

```
operators/<task>/
├── __init__.py
├── operator.py       # Top-level class, e.g. Gen3DObjectOperator
├── funcs/            # Decoupled steps (one file per logical function)
└── metrics/          # Task-specific evaluation code
```

`metrics/` is co-located with each operator on purpose — the evaluation logic
is tightly coupled to that operator's outputs (e.g., CG needs temporal-consistency
metrics; 3D-object needs Chamfer + PBR checks; motion needs foot-skate + jerk).

## Operators

| Operator | Class | Description | Steps in `funcs/` |
|---|---|---|---|
| `gen_tpose_image` | `GenTPoseImageOperator` | Character image → T-pose RGBA, ready for rigging | `gen_tpose_image` |
| `gen_3d_object` | `Gen3DObjectOperator` | Generate a single 3D asset from image / text | `art_plan`, `asset_import`, `asset_pack`, `mesh_cleanup` |
| `gen_3d_scene` | `Gen3DSceneOperator` | Reconstruct a 3D scene from a reference image, or compose ground + placed objects | `scene_mask`, `points_to_mesh`, `build_scene_mesh`, `scene_assets`, `appearance_assets` |
| `gen_motion` | `GenMotionOperator` | Rig a character, generate or fetch a clip, and retarget it | `rig_character`, `generate_motion`, `fetch_motion`, `retarget_motion` |
| `gen_audio` | `GenAudioOperator` | Generate character dialogue and game sound effects | `generate_dialogue`, `generate_sound_effect`, `prepare_reference_audio`, `resample_audio` |
| `gen_cg_video` | `GenCGVideoOperator` | Generate CG / cutscene video | — |

`gen_motion` covers rigging, text-to-motion, library downloads, and retargeting
in one operator; `task_type` on the task selects the route, so there is no
separate `retarget` operator.

Two directories are reserved but not implemented yet — `operator.py` is empty in
both, so do not import them:

| Reserved | Intended scope | Current state |
|---|---|---|
| `process_input` | Parse text, preprocess image, extract character | Placeholder |


`metrics/` exposes a single `evaluate(result, task)` entry point per task and runs
without a model, weights, or a GPU. Only `gen_3d_scene` (boundary-edge ratio,
largest-component share, stretch p99) and `gen_motion` (rig, BVH, and retarget
artifact checks) are implemented; the remaining `metrics/` packages are empty
placeholders.

## Note on `gen_3d_scene`

Its `funcs/` split exists to fix the perforated meshes the upstream
HunyuanWorldMirror code produces. Upstream answers "is this pixel valid?" and
"is this pixel on a discontinuity?" with the same deletion, which punches holes
through solid surfaces because a discontinuity belongs to the boundary *between*
two pixels, not to either one. So `scene_mask.py` only judges pixels and
`points_to_mesh.py` only judges faces, using a tangent-plane test that keeps a
ground plane receding at a grazing angle intact while still cutting where a
foreground silhouette meets the background. On real reference images that lifts
retained coverage from roughly 82% of pixels to over 99%.

Two artefacts survive that and are handled separately, because neither is a
continuity problem. Sky is predicted at a finite depth and has to be segmented
out by the operator's `sky_model`. And where the depth head blurs an occlusion
boundary into a ramp, the sheet spanning it passes every per-edge test; it is
caught instead by comparing each face's own normal against the ones it inherits.

Nothing under `operators/gen_3d_scene/` or `pipeline/assets_gen/gen_3d_scene/`
names a model: the operator takes `model`, `video_model` and `sky_model` as
injected dependencies, so swapping the Hunyuan backends for another scene
generator touches only `models/`. Three pipeline tools inspect the output
without needing weights or a GPU:

| Command | What it tells you |
|---|---|
| `eval.py --self-check` | Meshes synthetic scenes with known answers, against upstream's filtering |
| `eval.py --contract-check` | Whether `WorldPlayModel`'s calls still match the HY-WorldPlay checkout |
| `render.py scene.glb` | Rasterises the mesh offscreen, so holes and rubber sheets are visible |
