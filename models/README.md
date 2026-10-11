# models/

Thin wrappers around individual generation models. **One file per model.**

Each wrapper exposes a uniform interface so operators can swap backends without
knowing implementation details.

Two contracts apply, both in `agent_skills/develop_harness/`:
`model_require.md` for the wrapper shape, plus `api_model_require.md` (R9) for
closed-source cloud APIs — R9 overrides R2.1–R2.3, R3.3/R3.4, R3.6 and R4 for
remote models. Shared cloud plumbing (HTTP retry, error classification, response
cache, submit → poll → download) lives in `models/common/cloud_api.py` — do not
re-implement it per provider.

Every generation backend here is a **cloud API**. The repository does not
download model weights; credentials live in `.env`, and the setup scripts only
install the Python dependencies each provider needs.

## Implemented wrappers

| Slot | Class | File | Kind | Needs |
|------|-------|------|------|-------|
| `gen_3d_object` | `TripoModel` | `gen_3d_object/tripo_model.py` | cloud API | `$TRIPO_API_KEY` + `scripts/asset_env_setup/cloud_api_install.sh` |
| `gen_3d_object` | `MeshyModel` | `gen_3d_object/meshy_model.py` | cloud API | `$MESHY_API_KEY` + `scripts/asset_env_setup/cloud_api_install.sh` |
| `gen_image` | `SeedreamModel` | `gen_image/seedream_model.py` | cloud API | `$ARK_API_KEY` + `scripts/asset_env_setup/cloud_api_install.sh` |
| `gen_cg_video` | `SeedanceModel` | `gen_cg_video/seedance_model.py` | cloud API | `$ARK_API_KEY` + `scripts/asset_env_setup/cloud_api_install.sh` |
| `gen_audio` | `SeedAudioModel` | `gen_audio/seed_audio_model.py` | cloud API | `$SEED_AUDIO_API_KEY` + `scripts/asset_env_setup/cloud_api_install.sh`; one class serves both dialogue and SFX slots |
| `gen_motion` | `TripoRiggingModel` | `gen_motion/tripo_rigging_model.py` | cloud API | `$TRIPO_API_KEY`; rigging, retargeting, animation and format conversion over one provider |
| `tools/image_matting` | `DepthAnythingModel` | `tools/image_matting/depth_anything_model.py` | local weights, **path supplied by the caller** | a local `model_path`; loaded with `local_files_only=True`, never downloaded |
| `tools/segmentation` | `SkySegmentationModel` | `tools/segmentation/sky.py` | local ONNX, **path supplied by the caller** | a local `model_path` + `onnxruntime` (the CPU build is enough) |

## Choosing a `gen_3d_object` backend

Both backends expose the same
`infer_and_save(image, output_path, seed, decimation_target, texture_size)`, so
`Gen3DObjectOperator` swaps between them without code changes (R6):

| | Tripo | Meshy |
|---|---|---|
| free tier | 2000 credits on sign-up | 100 credits / month |
| formats | GLB (conversion endpoint not wired) | GLB, FBX, OBJ, USDZ, STL |
| text-to-3D | one task | preview + refine (two billed tasks) |
| low poly | `smart_low_poly`, P-series models | `model_type="lowpoly"` |
| face budget | `face_limit` | `target_polycount`, 100-300 000 |

Pick one with:

```
python pipeline/assets_gen/gen_3d_object/run.py --backend {tripo,meshy}
```

## The two tool models

`DepthAnythingModel` and `SkySegmentationModel` are the only wrappers that read
weights from disk, and neither will fetch them: both take a local path and fail
with an actionable message when it is missing. They stay local because a
segmentation or depth head has no cloud equivalent that fits the pipeline's
latency budget.

`SkySegmentationModel` exists because depth heads cannot express "infinitely
far". They place sky at a finite depth that no threshold separates from real
surface, so it gets meshed into a curtain over the whole scene; only
segmentation finds it.

## Sub-modules

| Directory        | Purpose                              | Candidate models |
|------------------|--------------------------------------|------------------|
| `gen_3d_object/` | Single 3D asset generation           | Tripo, Meshy, Rodin, CSM, Step1X-3D, Direct3D-S2 |
| `gen_motion/`    | Motion generation and rigging         | Tripo rigging; MDM, MLD, T2M-GPT as candidates |
| `gen_cg_video/`  | Cinematic / CG video generation      | Seedance, Kling, Veo, Sora, Runway Gen-4, Hailuo, Vidu |
| `gen_audio/`     | Character voice, dialogue, game SFX  | Seed Audio; other voice and SFX backends as candidates |
| `reasoning/`     | LLMs / VLMs used inside the pipeline  | Claude, GPT, GLM, Kimi, DeepSeek, Gemini, Qwen, Llama, Mistral |
| `tools/`         | Utility models (depth, matting, segmentation) | Depth-Anything, SAM |
| `unified_model/` | Composite / multimodal pipelines     | e.g. end-to-end asset+motion models |
