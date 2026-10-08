# 3AGameFactory Unity示例插件

这些是**教学参考实现**，用于演示如何在`A3GameRuntime` Unity框架之上构建功能完整的游戏玩法。它们并非简单的框架骨架或占位代码——每个脚本都包含真实且可测试的游戏逻辑。

## 示例说明

| 示例 | 游戏类型 | 演示内容 |
| --- | --- | --- |
| `ArenaFighterExample` | 近战竞技场格斗 | 生命值、攻击机制、基于范围的命中检测、AI对手 |
| `ArenaFighterUIExample` | 竞技场展示 | 战斗状态、战斗日志以及世界空间中的生命值条 |
| `FPSExample` | 第一人称射击机制 | CharacterController的移动与碰撞处理、跳跃、门交互、环境碰撞、敌人追踪、射线命中式战斗、重新开始功能 |
| `FPSUIExample` | FPS界面展示 | 平视显示器（HUD）、准星、生命值/弹药/击杀数/计时器状态显示、伤害/命中反馈、重新开始交互 |
| `RacingExample` | 街机赛车 | 基于检查点的圈数计数、车辆移动控制 |
| `RacingUIExample` | 赛车界面展示 | 速度/圈数/检查点信息的HUD显示、结果弹窗、重新开始交互 |

## 主要特性

- **游戏玩法与界面展示相互分离**。游戏玩法示例引用`A3GameRuntime`；可选的UI示例则引用公开的游戏玩法程序集。
- **所有游戏玩法脚本均为MonoBehaviour**，具备完整且可运行的逻辑。
- **游戏玩法示例附带NUnit编辑模式测试**，这些测试会创建真实的`GameObject`并验证行为规则（如伤害计算、角色死亡判定、圈数计数等）。

如今，竞技场格斗和赛车类示例遵循与第一人称射击示例相同的“玩法逻辑/UI”组件边界：它们的玩法逻辑模块接受通用的运行时输入，而可选的UI组件仅调用公开的玩法状态、事件和指令。

`FPSExample`和`FPSUIExample`是命名空间通用的副本，对应独立的玩法逻辑和UI组件，这些组件会在`gameB_fps_test` Unity端到端测试中得到验证。该测试导入了预先准备好的虚拟角色、步枪、动作资源以及据点场景，编译两个组件后生成WebGL版本，进入Play模式并通过浏览器运行。竞技场格斗和赛车类示例目前仅作为代码/测试参考，并未纳入此次端到端验证范围。

## 目录结构```
示例/
├── README.md                           ← 您当前所在位置
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

## 运行测试

1. 打开包含 `A3GameRuntime` 包的 Unity 项目。
2. 将所需的示例文件夹导入到项目中。
3. 打开 **Window → General → Test Runner**。
4. 选择 **EditMode** 选项卡并点击 **Run All**。

所有测试均为 EditMode 测试，它们会通过编程方式实例化 `GameObject`，因此无需进行场景设置。

## 与 A3GameRuntime 的关系

每个游戏玩法示例都依赖 `A3GameRuntime` 程序集来实现以下功能：

- 实体身份与观测（`A3GameRuntimeEntityComponent`、`IA3GameControllableEntity`、`A3GameEntitySnapshot`）
- 运行时协调（`A3GameRuntimeSubsystem`）
- 移动与控制模式枚举（`A3GameLocomotionState`、`A3GameControlMode`）

这些示例从不修改 `A3GameRuntime`，仅调用其公共 API。UI 示例仅引用对应的游戏玩法程序集和 Unity uGUI，不会直接引用 `A3GameRuntime`。> **注意：** 这些示例并不会自动安装。生成的游戏应在自身的游戏代码中选择适配相关模式，而非依赖或继承这些示例。一旦复制到生成的项目中，FPS机械组件和UI组件会采用与验证运行时所使用的组件相同的自动引用机制。
