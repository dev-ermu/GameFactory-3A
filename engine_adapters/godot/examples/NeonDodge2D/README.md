# Neon Dodge 2D

一款完整的过程化街机生存游戏范例。它展示了可移动的`CharacterBody2D`、被监测的`Area2D`危险物和拾取物、键盘输入、动画效果、HUD更新、分数/护盾状态、胜利/失败判定，以及无需外部资源的重新开始循环。

可通过命令 `godot4 --path . -- --manual` 交互式运行该游戏。默认的确定性演示模式适合无人值守的验证与录制。若要运行原生烟雾探测功能，可执行以下命令：

```bash
godot4 --headless --path . --import
godot4 --headless --path . --script res://scripts/smoke.gd
```

评审演示版本生成于 `test_data/outputs/game101/godot/`；除Godot忽略的`.godot/`导入缓存外，两个版本的文件内容必须完全一致。
