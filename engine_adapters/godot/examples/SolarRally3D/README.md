# Solar Rally 3D

一款完整的第三人称街机赛车参考项目。它利用Godot网格、物理静态几何体、`CharacterBody3D`载具、有序排列的`Area3D`检查点、发光型PBR材质、追踪摄像机、遥测数据、圈数状态以及胜利循环，构建了一条炫酷的3D赛道。

可通过命令 `godot4 --path . -- --manual` 交互式运行该项目。默认的确定性驾驶程序可支持无人值守的游戏流程，便于进行烟雾测试与录制：

```bash
godot4 --headless --path . --import
godot4 --headless --path . --script res://scripts/smoke.gd
```

评审演示版本生成于 `test_data/outputs/game202/godot/` 目录下；除Godot忽略的 `.godot/` 导入缓存外，其文件结构与本项目一致。
