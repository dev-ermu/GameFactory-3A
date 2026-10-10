# RPG Explorer 3D

A third-person exploration reference in which
movement is camera-relative, the camera follows with lag, stamina gates sprint,
and a quest loop tracks three world pickups. The player visual is a real,
self-contained glTF 2.0 asset with a skinned mesh, one-bone skeleton, and `Walk`
animation. The native smoke test refuses to pass unless Godot imports all three
resource contracts and advances the imported animation.

The glTF is generated test content committed with the example, so validation
requires no network, credentials, proprietary asset, or mocked importer.

```bash
godot4 --headless --path . --import
godot4 --headless --path . --script res://scripts/smoke.gd
godot4 --path . -- --manual
```

The reviewer demonstration path is
`test_data/outputs/game606/godot/`.
