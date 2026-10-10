# Godot core gameplay references

These are complete, independent Godot 4 projects: choose a reference by
camera and mechanic, copy the relevant
pattern into generated code, and never depend on the example directory at
runtime.

| Project | Camera / genre | Core systems |
| --- | --- | --- |
| `NeonDodge2D/` | Fixed 2D arcade survival | `CharacterBody2D`, keyboard input, monitored hazards/pickups, HUD, score/shield, win/failure/restart state |
| `SolarRally3D/` | Third-person chase racing | `CharacterBody3D`, static collision, ordered checkpoints, PBR/emissive materials, directional/omni lighting, chase camera, laps/win state |
| `OrbitPinball2D/` | Fixed 2D physics pinball | `RigidBody2D`, static colliders, animated flippers, contact impulses, combo/lives state and procedural trails |
| `FpsArena3D/` | First-person shooter | Player-owned camera, camera-relative movement, physics hitscan, health targets, magazine/reload state and crosshair HUD |
| `ArenaDuel3D/` | Second-person arena combat | Match-owned framing camera, facing-locked fighters, attack windows, health, rounds and score |
| `RpgExplorer3D/` | Third-person RPG exploration | Camera-relative movement, follow camera, uneven traversal, quest pickups, stamina, and a skinned glTF actor with imported bone animation |

This split is intentional: camera and physics ownership change the core code far
more than cosmetic genre labels. The first five examples use procedural
content. `RpgExplorer3D` additionally vendors a tiny self-contained, generated
glTF fixture (no downloaded or licensed content) so native validation crosses
the actual Godot 3D asset and motion importer rather than claiming import
support from source inspection.

## Native validation

Each project contains a real `project.godot`, main `PackedScene`, deterministic
demo driver, interactive keyboard mode, and `res://scripts/smoke.gd`. Run all
six with an installed Godot 4 editor:

```bash
for project in NeonDodge2D SolarRally3D OrbitPinball2D \
  FpsArena3D ArenaDuel3D RpgExplorer3D; do
  godot4 --headless --path "engine_adapters/godot/examples/$project" --import
  godot4 --headless --path "engine_adapters/godot/examples/$project" \
    --script res://scripts/smoke.gd
done
```

The smoke scripts instantiate the actual main scene, advance live physics, and
assert motion plus game-specific entity/state contracts. The RPG probe also
requires one imported `MeshInstance3D`, one nonempty `Skeleton3D`, the imported
`Walk` clip, and observed animation advancement. A static file check cannot
produce `A3GAME_SMOKE_OK`.

## Generated-output traceability


| Reference | Generated demonstration |
| --- | --- |
| `NeonDodge2D` | `test_data/outputs/game101/godot/` |
| `SolarRally3D` | `test_data/outputs/game202/godot/` |
| `OrbitPinball2D` | `test_data/outputs/game303/godot/` |
| `FpsArena3D` | `test_data/outputs/game404/godot/` |
| `ArenaDuel3D` | `test_data/outputs/game505/godot/` |
| `RpgExplorer3D` | `test_data/outputs/game606/godot/` |

Generated-output copies are delivery artifacts, not runtime dependencies of
these references. Reproduce source validation with the native commands above;
use each contract's `generated_output` value when materializing a reviewer copy.

## Mechanic/UI module boundary

Godot does not provide a direct equivalent of Unity's `.asmdef` or Unreal's
`.uplugin` module rules. The adapter models the same boundary with two
artifacts and an explicit product assembly step:

- **Mechanic artifact**: owns gameplay, scenes, physics, input, and the public
  runtime adapter. It is runnable on its own and contains no HUD or UI scene.
- **UI artifact**: owns `CombatUI.tscn` and its presentation script. It depends
  on the mechanic contract and talks to gameplay only through the autoloaded
  runtime adapter; it does not access fighters, stage nodes, or private fields.
- **Product composition root**: is generated during assembly as
  `res://scenes/Main.tscn`, with sibling `Mechanic` and `UI` instances.

Assemble a Godot product without changing Unity, UE, or shared Browser Serving
code:

```python
from engine_adapters.godot import GodotClient

client = GodotClient(godot_executable="godot4")
    "path/to/mechanic-artifact",
    "path/to/ui-artifact",
    "path/to/product-project",
    overwrite=True,
)
```

The resulting `assembly_manifest.json` records the dependency direction
`ui -> mechanic -> runtime_framework`, and `browser_play/launch.sh` should point
at the assembled product project rather than the mechanic artifact alone.
