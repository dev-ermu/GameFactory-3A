# RPG探险者3D

这是一个与Three.js的`explorer-example`功能对应的第三人称探索示例：移动操作以摄像机为参照，摄像机会有延迟跟随效果，耐力值机制控制冲刺行为，任务循环会追踪三个世界中的拾取物。玩家角色是一个完整的、独立的glTF 2.0资源，包含蒙皮网格、单骨骼结构以及`Walk`动画。除非Godot能成功导入全部三种资源并正确解析导入后的动画，否则原生 Smoke 测试无法通过。

该glTF格式的测试内容已随示例一同提交，因此验证过程无需联网、无需凭证、无需专有资源，也无需模拟导入器。

```bash
godot4 --headless --path . --import
godot4 --headless --path . --script res://scripts/smoke.gd
godot4 --path . -- --manual
```

评审演示路径为：
`test_data/outputs/game606/godot/`
