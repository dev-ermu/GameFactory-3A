# Asset environment setup

Every generation backend in this repository is a **cloud API**, so the only
thing an asset task needs installed is an HTTP client. There is one script, and
it serves every asset task:

```bash
bash scripts/asset_env_setup/cloud_api_install.sh
```

| Asset task | Backends it serves |
|---|---|
| 3D object | `TripoModel` (`$TRIPO_API_KEY`), `MeshyModel` (`$MESHY_API_KEY`) |
| Image / T-pose | `SeedreamModel` (`$ARK_API_KEY`) |
| CG video | `SeedanceModel` (`$ARK_API_KEY`), Hailuo (`$MINIMAX_API_KEY`) |
| Audio | `SeedAudioModel` (`$SEED_AUDIO_API_KEY`) |
| Motion | cloud rigging / animation (`$TOKENHUB_API_KEY`) |

It installs `requests` plus the offline test dependencies (`pillow`, `numpy`,
`scipy`). No GPU, no weights, no compiled extensions. Pass `--conda` to build a
dedicated environment instead of installing into the active one.

This directory used to hold one thin forwarder per asset task, all four
byte-identical. They were removed: the path you typed named the task but the
script it reached for did nothing different, so the extra files only made the
real entry point harder to find.

Configuration happens in exactly one place, and it is not here:

```bash
cp .env.example .env   # then fill in the key for whichever backend you use
```

Weights are never downloaded. The two wrappers that do read weights from disk
— `DepthAnythingModel` and `SkySegmentationModel` — take a local `model_path`
from the caller and fail with an actionable message when it is missing.
