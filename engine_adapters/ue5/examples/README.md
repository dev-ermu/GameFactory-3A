# UE5参考游戏插件

这些插件是基于公共的`AAAGamePlayable`契约构建的可选具体示例：

| 插件 | 演示内容 |
| --- | --- |
| `ArenaFighterExample` | 角色移动、轻重攻击、竞技场GameMode、HUD |
| `FPSExample` | 第一人称移动、射线射击、装弹、FPS GameMode、HUD |
| `RacingExample` | 街机风格载具移动、加速、手刹、赛车GameMode、HUD |

这些插件默认处于禁用状态，且不会自动安装。生成的游戏应在自身的游戏插件中采用相关的模式，而非依赖或继承这些示例插件。

每个示例都包含其具体的Pawn/角色、PlayerController、GameMode、HUD、实体工厂以及运行时子系统。`AAAGamePlayable`仅定义了标准化的输入、会话、绑定、实体和观测契约。
