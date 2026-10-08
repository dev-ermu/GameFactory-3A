# 3AGameFactory Unity Example Plugins

These are **educational reference implementations** that demonstrate how to
build fully functional gameplay on top of the `A3GameRuntime` Unity
framework. They are not skeletons or stubs — every script contains real,
testable game logic.

## Examples

| Example | Genre | Demonstrates |
| --- | --- | --- |
| `ArenaFighterExample` | Melee arena combat | Health, attacks, range-based hit detection, AI opponent |
| `ArenaFighterUIExample` | Arena presentation | Fight status, combat log, and world-space health bars |
| `FPSExample` | First-person shooter mechanic | CharacterController movement/collision, jump, door interaction, environment collision, enemy pursuit, hitscan combat, restart |
| `FPSUIExample` | FPS presentation | HUD, crosshair, health/ammo/kill/timer state, damage/hit feedback, restart interaction |
| `RacingExample` | Arcade racing | Checkpoint-based lap counting, vehicle movement |
| `RacingUIExample` | Racing presentation | Speed/lap/checkpoint HUD, result overlay, restart interaction |

## Key Properties

- **Gameplay and presentation are separate.** Gameplay examples reference
  `A3GameRuntime`; optional UI examples reference the public gameplay assembly.
- **All gameplay scripts are MonoBehaviours** with complete, working logic.
- **Gameplay examples ship with NUnit EditMode tests** that create real
  `GameObject`s and verify behavioral invariants (damage, death, lap counting).
  invariants the implementation must satisfy.

Arena Fighter and Racing now follow the same mechanic/UI assembly boundary as
FPS. Their mechanics accept generic runtime input and their optional UI
assemblies consume only the public mechanic state, events, and commands.

`FPSExample` and `FPSUIExample` are namespace-generic copies of the separate
Mechanic and UI assemblies exercised by the `gameB_fps_test` Unity end-to-end
run. That run imported the prepared avatars, rifle, motions, and outpost scene,
compiled both assemblies, built WebGL, entered Play Mode, and was played through
Browser Serving. Arena Fighter and Racing remain code/test references; they
were not part of that end-to-end validation.

## Directory Layout

```
examples/
├── README.md                           ← you are here
├── ArenaFighterExample/
│   ├── package.json
│   ├── ArenaFighterExample.asmdef
│   ├── Scripts/
│   │   ├── ArenaFighterController.cs
│   │   ├── ArenaFighterCombat.cs
│   │   ├── ArenaFighterAI.cs
│   │   └── ArenaFighterGameMode.cs
│   └── Tests/
│       ├── ArenaFighterExample.Tests.asmdef
│       └── ArenaFighterTests.cs
├── ArenaFighterUIExample/
│   ├── package.json
│   ├── ArenaFighterUIExample.asmdef
│   ├── Scripts/
│   │   ├── FightHUD.cs
│   │   └── FighterHealthBar.cs
├── FPSExample/
│   ├── package.json
│   ├── FPSExample.asmdef
│   ├── Scripts/
│   │   ├── FPSGameRuntimeAdapter.cs
│   │   ├── FPSGameState.cs
│   │   ├── FPSPlayerController.cs
│   │   ├── FPSEnemy.cs
│   │   ├── FPSEnemySpawner.cs
│   │   ├── FPSWeapon.cs
│   │   └── FPSDoor.cs
│   └── Tests/
│       ├── FPSExample.Tests.asmdef
│       └── FPSTests.cs
├── FPSUIExample/
│   ├── package.json
│   ├── FPSUIExample.asmdef
│   ├── Scripts/
│   │   └── FPSArenaHUD.cs
│   └── Tests/
│       ├── FPSUIExample.Tests.asmdef
│       ├── FPSArenaHUDTests.cs
├── RacingExample/
│   ├── package.json
│   ├── RacingExample.asmdef
│   ├── Scripts/
│   │   ├── RacingVehicleController.cs
│   │   ├── RacingCheckpoint.cs
│   │   ├── RacingLapCounter.cs
│   │   └── RacingGameMode.cs
│   └── Tests/
│       ├── RacingExample.Tests.asmdef
│       └── RacingTests.cs
└── RacingUIExample/
    ├── package.json
    ├── RacingUIExample.asmdef
    ├── Scripts/RacingHUD.cs
    └── Tests/
        ├── RacingUIExample.Tests.asmdef
        └── RacingHUDTests.cs
```

## Running the Tests

1. Open the Unity project that includes the `A3GameRuntime` package.
2. Import the desired example folder(s) into the project.
3. Open **Window → General → Test Runner**.
4. Select the **EditMode** tab and click **Run All**.

All tests are EditMode tests that instantiate `GameObject`s programmatically,
so no scene setup is required.

## Relationship to A3GameRuntime

Each gameplay example depends on the `A3GameRuntime` assembly for:

- Entity identity and observation (`A3GameRuntimeEntityComponent`,
  `IA3GameControllableEntity`, `A3GameEntitySnapshot`)
- Runtime coordination (`A3GameRuntimeSubsystem`)
- Locomotion and control-mode enums (`A3GameLocomotionState`,
  `A3GameControlMode`)

The examples never modify `A3GameRuntime`; they consume its public API.
UI examples reference only their corresponding gameplay assembly and Unity
uGUI; they do not reference `A3GameRuntime` directly.

> **Note:** These examples are not installed automatically. Generated games
> should adapt the relevant patterns inside their own gameplay code rather than
> depending on or inheriting from an example. Once copied into a generated
> project, the FPS Mechanic and UI assemblies use the same auto-reference
> behavior as the assemblies exercised by the validated run.
