# Godot核心游戏玩法参考

这些是完整且独立的Godot 4项目，其组织方式类似于Three.js示例库：根据摄像机类型和游戏机制选择对应的参考项，将相关代码模式复制到自己的项目中，运行时无需依赖示例目录。

| 项目 | 摄像机类型/游戏类型 | 核心系统 |
| --- | --- | --- |
| `NeonDodge2D/` | 固定视角2D街机生存类游戏 | `CharacterBody2D`、键盘输入、可监测的危险物/拾取物、HUD界面、分数/护盾系统、胜利/失败/重启状态管理 |
| `SolarRally3D/` | 第三人称追逐竞速类游戏 | `CharacterBody3D`、静态碰撞检测、有序 checkpoint 设置、PBR/发光材质、定向光/泛光照明、追踪摄像机、圈数/胜利状态管理 |
| `OrbitPinball2D/` | 固定视角2D物理弹珠类游戏 | `RigidBody2D`、静态碰撞体、可动画控制的弹板、接触冲量计算、连击/生命值状态管理及动态轨迹生成 |
| `FpsArena3D/` | 第一人称射击游戏 | 玩家控制的摄像机、摄像机相对移动逻辑、物理射线命中检测、生命值目标、弹匣/装填状态管理及准星HUD |
| `ArenaDuel3D/` | 第二人称竞技场格斗游戏 | 比赛专属的框架摄像机、面向锁定机制、攻击窗口判定、生命值、回合及分数系统 |
| `RpgExplorer3D/` | 第三人称RPG探索类游戏 | 摄像机相对移动逻辑、跟随摄像机、不平坦地形遍历、任务拾取物、耐力系统，以及带有导入骨骼动画的蒙皮glTF角色模型 |

这种拆分是有意为之：摄像机和物理系统的所有权归属对核心代码的影响远大于表面的游戏类型标签。前五个示例均采用程序化生成的内容。`RpgExplorer3D`还内置了一个小型、自包含的生成型glTF模型（无需下载或授权内容），因此原生验证过程会直接调用Godot的3D资源和运动导入器，而非仅通过源代码检查来宣称支持导入。

## 原生验证

每个项目都包含真实的`project.godot`文件、主`PackedScene`、确定性演示驱动程序、交互式键盘模式，以及`res://scripts/smoke.gd`脚本。安装Godot 4编辑器后，可运行全部六个示例：

```bash
for project in NeonDodge2D SolarRally3D OrbitPinball2D \
  FpsArena3D ArenaDuel3D RpgExplorer3D; do
  godot4 --headless --path "engine_adapters/godot/examples/$project" --import
  godot4 --headless --path "engine_adapters/godot/examples/$project" \
    --script res://scripts/smoke.gd
done
```

这些smoke脚本会实例化实际的主场景，推进实时物理运算，并验证物体运动以及游戏特定的实体/状态逻辑是否符合约定。`RpgExplorer3D`示例还需依赖一个导入的`MeshInstance3D`、一个非空的`Skeleton3D`、导入的`Walk`动画剪辑，以及正确的动画播放效果。仅靠静态文件检查无法得出`A3GAME_SMOKE_OK`的验证结果。

## 生成输出可追溯性

每个项目中的`mechanic_contract.json`文件会记录其对应的精确审查输出路径：| 参考项目 | 生成的演示版本 |
| --- | --- |
| `NeonDodge2D` | `test_data/outputs/game101/godot/` |
| `SolarRally3D` | `test_data/outputs/game202/godot/` |
| `OrbitPinball2D` | `test_data/outputs/game303/godot/` |
| `FpsArena3D` | `test_data/outputs/game404/godot/` |
| `ArenaDuel3D` | `test_data/outputs/game505/godot/` |
| `RpgExplorer3D` | `test_data/outputs/game606/godot/` |

生成的输出副本属于交付产物，并非这些参考项目的运行时依赖项。请使用上述原生命令重新验证源代码；生成审核用副本时，需采用每个项目对应的`generated_output`值。

## 玩法逻辑/UI模块边界

Godot没有与Unity的`.asmdef`或Unreal的`.uplugin`直接等效的模块规则。适配器通过两个产物以及一个明确的产品组装步骤来模拟同样的边界：

- **玩法逻辑产物**：包含游戏玩法、场景、物理系统、输入处理相关代码以及公共运行时适配器。该产物可独立运行，不包含HUD或UI场景。
- **UI产物**：包含`CombatUI.tscn`及其展示脚本。它依赖于玩法逻辑模块，仅通过自动加载的运行时适配器与游戏玩法交互；它无法访问战斗单位、场景节点或私有字段。
- **产品组合根节点**：在组装过程中会生成为`res://scenes/Main.tscn`，其中包含并列的`Mechanic`和`UI`实例。

无需修改Unity、UE或共享的浏览器服务端代码，即可组装出Godot产品：

```python
from engine_adapters.godot import GodotClient

client = GodotClient(godot_executable="godot4")
client.project.assemble_modules(
    "path/to/mechanic-artifact",
    "path/to/ui-artifact",
    "path/to/product-project",
    overwrite=True,
)
```

生成的`assembly_manifest.json`会记录依赖方向为`ui -> mechanic -> runtime_framework`，而`browser_play/launch.sh`应指向组装后的产品项目，而非单独的玩法逻辑产物。
