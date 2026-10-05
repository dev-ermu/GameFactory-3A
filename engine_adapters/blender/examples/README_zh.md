# Blender参考机制

这些脚本是基于`engine_adapters/blender/game`构建的可选具体示例。它们与`ue5/examples/`和`unity3d/examples/`并列存放，以便每个引擎都能拥有自己的示例。共享的`test_data/test_samples/`在后续合并前保持与引擎无关的状态。

| 示例 | 类型 | 演示内容 |
| --- | --- | --- |
| `FPSExample` | 第一人称射击 | 射线命中射击、掩体机制、弹匣/装填逻辑、脚本化玩家行为规则 |
| `RacingExample` | 赛车 | 街机风格转向控制、圈数统计、加速/手刹功能、跟随摄像机 |
| `ArenaFighterExample` | 格斗 | 轻击/重击/防御操作、最佳N局制比赛规则、角色朝向判定 |
| `ForestExplorerExample` | 角色扮演 | 第三人称视角林地场景、近战/弓箭攻击、宝箱交互、Mixamo动画片段 |

这些示例永远不会被自动安装。生成的游戏应在自身的`game.py`中适配相关模式，而非将这些文件作为库导入。

每个示例都独立包含自身的关卡布局、游戏规则、HUD界面和摄像机设置。`blender/game`仅负责提供共享工具集：固定时间步长的`Game`类、角色对象、资源、动画片段、录制模块以及控制逻辑。

## 阅读顺序

1. `game.py` — `build()` / `tick()` / `summary()` / `verdict()`。
2. `engine_adapters/blender/game/kernel.py` — `Game`基类。
3. `agent_skills/engine_context/blender_api.md` — API使用注意事项。

## 运行单个示例

```bash
# 仅执行规则验证（不渲染视频）
GAMEFACTORY3A_ROOT=$PWD blender --background --factory-startup \
    --python engine_adapters/blender/examples/FPSExample/game.py -- \
    --out-dir /tmp/fps --duration 8 --no-render

# 在窗口中运行游戏
GAMEFACTORY3A_ROOT=$PWD blender --factory-startup \
    --python engine_adapters/blender/examples/RacingExample/game.py -- --play
```

如果未设置环境变量，通过脚本向上查找也能定位到仓库根目录。

## 试玩测试

通过`Controls`模块绑定按键操作；示例自带的`--no-render`模式运行时的规则如下：

```python
from engine_adapters.blender import BlenderClient

BlenderClient(
    project_path="engine_adapters/blender/examples/FPSExample",
).playtest.record(
    output_dir="/tmp/blender_playtest",
    duration=8,
    no_render=True,
)
```

可选操作：在`Game`子类中设置`playtest_actions`参数；否则会采用默认的类型专属按键绑定。
