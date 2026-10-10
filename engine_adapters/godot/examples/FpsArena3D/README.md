# FPS Arena 3D

A complete first-person shooter reference in which the camera belongs to the
player, movement is resolved from its
yaw, and shots are physics rays from the camera rather than projectiles spawned
from a third-person character. It includes live targets, magazine/reload state,
health, hit accounting, a crosshair HUD, deterministic demo play, and manual
WASD/arrow/space controls.

```bash
godot4 --headless --path . --import
godot4 --headless --path . --script res://scripts/smoke.gd
godot4 --path . -- --manual
```

The reviewer demonstration path is
`test_data/outputs/game404/godot/`.
