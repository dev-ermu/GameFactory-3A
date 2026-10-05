# Arena Duel 3D

这是一个与Three.js的`arena-fighter-example`示例对应的第二人称战斗参考项目：
该对战场景会使用一个摄像机来同时框定两名战士，且任何一名战士都无法操控摄像机；
角色的移动和朝向会始终锁定在对手所在轴线上。该项目还加入了实时角色碰撞检测、攻击判定窗口、技能冷却时间、生命值系统、击退效果、回合重置、得分状态管理、确定性AI对战验证，以及手动的A/D/空格键操控功能。

该示例特意未包含任何素材资源。其模块划分方式类似于Unity的程序集或Unreal的功能模块：

- `mechanic/`模块负责处理战士、竞技场、战斗循环、摄像机以及运行时桥接逻辑。
- `ui/`模块负责屏幕空间的HUD显示，且仅依赖运行时桥接接口。
- `main.tscn`是场景组合的根节点；`scripts/main.gd`是一个兼容性入口点，会将相关调用委托给`mechanic/main.gd`。

```bash
godot4 --headless --path . --import
godot4 --headless --path . --script res://scripts/smoke.gd
godot4 --path . -- --manual
```

审核演示路径为
`test_data/outputs/game505/godot/`。
