# Arena Duel 3D

A second-person combat reference in which
the match owns a camera that frames both fighters, neither fighter may steer it,
and locomotion/facing stay locked to the opponent axis. The project adds live
character collision, attack windows, cooldowns, health, knockback, round reset,
score state, deterministic AI-versus-AI validation, and manual A/D/space control.

The example is intentionally asset-free. Its module boundary mirrors a Unity
assembly or Unreal feature module:

- `mechanic/` owns the fighters, arena, combat loop, camera, and runtime bridge.
- `ui/` owns the screen-space HUD and depends only on the runtime bridge.
- `main.tscn` is the composition root; `scripts/main.gd` is a compatibility
  entry point that delegates to `mechanic/main.gd`.

```bash
godot4 --headless --path . --import
godot4 --headless --path . --script res://scripts/smoke.gd
godot4 --path . -- --manual
```

The reviewer demonstration path is
`test_data/outputs/game505/godot/`.
