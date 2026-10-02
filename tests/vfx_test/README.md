# VFX tests

Run the offline adapter suite from the repository root:

```bash
python -m unittest test.vfx_test.test_vfx_adapters -v
```

The Unreal integration scripts resolve project-specific review assets from
`AAAGF_VFX_TEST_CONTENT_ROOT`. Set it to the Unreal content directory that
contains `Maps`, `Preview`, `Review`, and `Sequences`, for example
`/Game/MyProject/VFXTests`. Filesystem output paths are supplied separately by
the existing `AAAGF_VFX_REVIEW_ROOT`, `AAAGF_PUNCH_FIRE_OUTPUT_DIR`, and
`AAAGF_VFX_PLAYER_PATH` variables.
