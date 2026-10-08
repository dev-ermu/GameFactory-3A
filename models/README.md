# models/

Thin wrappers around individual generation models. **One file per model.**

Each wrapper should expose a uniform interface (e.g., `load()`, `infer()`,
`unload()`) so operators can swap backends without knowing implementation details.

Two contracts apply, both in `agent_skills/develop_harness/`:
`model_require.md` for local-weight models, plus `api_model_require.md` (R9) when
the model is a closed-source cloud API. Shared cloud plumbing (HTTP retry, error
classification, response cache, submit → poll → download) lives in
`models/common/cloud_api.py` — do not re-implement it per provider.

## Implemented wrappers

| Slot | Class | File | Kind | Needs |
|------|-------|------|------|-------|
| `gen_3d_object` | `TripoModel` | `gen_3d_object/tripo_model.py` | cloud API | `$TRIPO_API_KEY` + `scripts/asset_env_setup/3d_object/cloud_api_install.sh` |
| `gen_3d_object` | `MeshyModel` | `gen_3d_object/meshy_model.py` | cloud API | `$MESHY_API_KEY` + `scripts/asset_env_setup/3d_object/cloud_api_install.sh` |
| `gen_cg_video` | `SeedanceModel` | `gen_cg_video/seedance_model.py` | cloud API | `$ARK_API_KEY` + `scripts/asset_env_setup/cg_video/cloud_api_install.sh` |
| `gen_cg_video` | `MiniMaxH3Model` | `gen_cg_video/minimax_h3_model.py` | cloud API + local pruned INT8 | `$MINIMAX_API_KEY` or `scripts/asset_env_setup/cg_video/minimax_h3_install.sh` |
| `gen_image` | `SeedreamModel` | `gen_image/seedream_model.py` | cloud API | `$ARK_API_KEY` + `scripts/asset_env_setup/image/cloud_api_install.sh` |
| `gen_audio` | `SeedAudioModel` | `gen_audio/seed_audio_model.py` | cloud API | `$SEED_AUDIO_API_KEY` + `scripts/asset_env_setup/audio/cloud_api_install.sh`; one class serves both dialogue and SFX slots |

isolated subprocesses. This avoids namespace collisions and releases GPU memory
between the rigging and motion-generation stages. Their repositories, weights,
caches and test assets are external runtime data; only these wrappers and the
reproducible setup scripts belong in Git.

All three `gen_3d_object` backends expose the same
`infer_and_save(image, output_path, seed, decimation_target, texture_size)`, so
`Gen3DObjectOperator` swaps between them without changing (R6). Pick one with

| | Tripo | Meshy |
|---|---|---|
| free tier | 2000 credits on sign-up | 100 credits / month |
| formats | GLB (conversion endpoint not wired) | GLB, FBX, OBJ, USDZ, STL |
| text-to-3D | one task | preview + refine (two billed tasks) |
| low poly | `smart_low_poly`, P-series models | `model_type="lowpoly"` |
| face budget | `face_limit` | `target_polycount`, 100-300 000 |

The two `gen_3d_scene` wrappers chain rather than substitute for each other.
takes them in separate slots. Only the geometry slot is required — a task that
already has footage, or that is content with what a single view can see, needs
source that backs the geometry wrapper; see its README for what was changed.

`SkySegmentationModel` is a third, smaller piece of the same chain. Depth heads
cannot express "infinitely far", so they place sky at a finite depth that no
threshold separates from real surface, and it gets meshed into a curtain over
the scene. Only segmentation finds it.

## Sub-modules

| Directory        | Purpose                              | Candidate models |
|------------------|--------------------------------------|------------------|
| `gen_cg_video/`  | Cinematic / CG video generation      | LTX-2.3, HunyuanVideo, Wan, Mochi, CogVideoX, Open-Sora, Seedance 2, Kling 3, Veo 3, Sora 2, Runway Gen-4, Hailuo, Vidu |
| `unified_model/` | Composite / multimodal pipelines     | e.g., end-to-end asset+motion models  |
