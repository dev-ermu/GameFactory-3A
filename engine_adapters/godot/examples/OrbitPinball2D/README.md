# Orbit Pinball 2D

一份完整的物理弹珠台参考示例。它展示了持续模拟的`RigidBody2D`、静态碰撞几何体、可动画化的`AnimatableBody2D`挡板、由碰撞触发的冲量与计分机制、程序生成的轨迹效果、HUD遥测数据、连击系统、生命值设定、胜利状态判定以及重置功能。

通过命令 `godot4 --path . -- --manual` 可交互式运行该程序。默认的确定性挡板驱动逻辑使得同一项目也适用于无人值守的验证场景：

```bash
godot4 --headless --path . --import
godot4 --headless --path . --script res://scripts/smoke.gd
```

供评审人员使用的演示版本生成于 `test_data/outputs/game303/godot/` 目录下；除Godot忽略的`.godot/`导入缓存外，该目录结构与本项目一致。
