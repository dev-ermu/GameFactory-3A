# Blender Reference Mechanics

These scripts are optional concrete examples built on
`engine_adapters/blender/game`. They sit next to `ue5/examples/` and
`unity3d/examples/` so each engine owns its samples. Shared
`test_data/test_samples/` stays engine-neutral until a later merge.

| Example | Genre | Demonstrates |
| --- | --- | --- |
| `FPSExample` | FPS | Hitscan fire, cover, magazine/reload, scripted player policy |
| `RacingExample` | Racing | Arcade steering, lap, boost/handbrake, chase camera |
| `ArenaFighterExample` | Fighting | Light/heavy/guard, best-of-N rounds, facing |
| `ForestExplorerExample` | RPG | Third-person glade, melee/bow, chests, Mixamo clips |

They are never installed automatically. Generated games should adapt the
relevant patterns inside their own `game.py` rather than importing these
files as a library.

Each example owns its level scatter, rules, HUD, and camera.
`blender/game` owns only the shared kit: fixed-timestep `Game`, actors,
assets, clips, recorder, and controls.

## Reading order

1. `game.py` — `build()` / `tick()` / `summary()` / `verdict()`.
2. `engine_adapters/blender/game/kernel.py` — the `Game` base class.
3. `agent_skills/engine_context/blender_api.md` — API caveats.

## Running one

```bash
# rules only (no video)
GAMEFACTORY3A_ROOT=$PWD blender --background --factory-startup \
    --python engine_adapters/blender/examples/FPSExample/game.py -- \
    --out-dir /tmp/fps --duration 8 --no-render

# play in a window
GAMEFACTORY3A_ROOT=$PWD blender --factory-startup \
    --python engine_adapters/blender/examples/RacingExample/game.py -- --play
```

Walking up from the script also finds the repo root if the env var is unset.

