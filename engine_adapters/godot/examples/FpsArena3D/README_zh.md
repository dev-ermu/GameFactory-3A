# FPS竞技场3D

这是一个完整的第一人称射击游戏示例，与代码库中的Three.js `fps-example`项目相匹配：摄像机归属于玩家，移动方向由偏航角决定，射击则是从摄像机发出的物理射线，而非从第三人称角色身上生成的投射物。该示例包含动态目标、弹匣/装填状态显示、生命值系统、命中统计、准星HUD界面、可确定性运行的演示模式，以及手动控制的WASD/方向键/空格键操作方式。

```bash
godot4 --headless --path . --import
godot4 --headless --path . --script res://scripts/smoke.gd
godot4 --path . -- --manual
```

评审演示路径为 `test_data/outputs/game404/godot/`。
