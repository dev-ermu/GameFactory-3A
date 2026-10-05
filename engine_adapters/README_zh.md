# engine_adapters/

引擎端的参考代码——在生成机制/UI代码时，**作为上下文提供给大语言模型**，并在运行时用于RPC风格的资产传输。

## 子目录

| 目录       | 内容描述                                                     |
|------------|--------------------------------------------------------------|
| `ue5/`     | UE5蓝图模板、C++模块、Python远程脚本、导入辅助工具         |
| `unity3d/` | Unity3D C#模板、编辑器脚本、PackageManager清单文件         |
| `godot/`   | Godot 4公共客户端、完整的GDScript运行时插件、导入/导出/测试辅助工具、原生游戏玩法参考 |
| `blender/` | Blender Python（`bpy`）导入器、无头渲染工具、`game/`工具包、`examples/`分类玩法示例、`playtest/`录制功能 |
| `three_js/`| Web运行时：`ThreeClient` Python API、`A3GamePlayable` JS框架、glTF加载器、场景脚手架、HUD覆盖层 |

`ue5/`、`unity3d/`、`godot/`和`three_js/`实现了完整版本化的客户端协议。每个目录都仅暴露一个公共Python入口点——分别是`UEClient`、`UnityClient`、`GodotClient`或`ThreeClient`——它们拥有相同的11个命名空间以及一致的`{ok, operation, artifacts, diagnostics, warnings, errors, payload}`结果结构，因此流水线代码无需通过分支判断即可切换引擎。

每个目录还附带一个由适配器专属的运行时框架，生成的游戏玩法代码会基于该框架扩展但不会修改它：

| 适配器       | 框架                          | 生成的游戏玩法代码存放位置               |
|------------|-------------------------------|------------------------------------------|
| `ue5/`     | `A3GamePlayable` UE插件（C++协议） | 项目本地的游戏玩法插件中                 |
| `unity3d/` | `A3GameRuntime` Unity包（C#协议） | 项目本地的游戏玩法脚本和程序集里         |
| `godot/`   | `A3GamePlayable` Godot插件（GDScript协议及UDP会话桥接） | 项目本地的插件或游戏脚本树中             |
| `three_js/`| `A3GamePlayable` npm包`@a3game/playable` | 项目本地`packages/`下的游戏玩法包中     |
| `blender/` | `engine_adapters/blender/game`（Python工具包） | 项目本地的`game.py`；参考副本存放在`blender/examples/`中 |

`three_js/`暴露`ThreeClient`；`blender/`同样以类似方式暴露`BlenderClient`。两种引擎的玩法录制功能均通过`client.playtest.record(...)`实现。

关于为何three.js框架还要负责Unreal引擎原生提供的渲染器、帧循环、输入、动画和碰撞相关基础架构，可查阅`three_js/MIGRATION_INVENTORY.md`了解详情。

Blender的分类玩法示例存放在`blender/examples/`下，与`ue5/examples/`和`unity3d/examples/`并列。这样能避免引擎专属示例混入共享的`test_data/test_samples/`目录，直到后续合并时再处理。

要求大语言模型*引用/扩展*这些文件，而非从头编写引擎代码，此举既能提升编译效率，又能减少虚构API的情况。

## 导入生成的资产每个引擎都有一个 `import_generated/` 子目录：它充当了 `models/` 生成的数据与引擎可实际使用内容之间的桥梁。该目录特意与上文提到的引擎接口函数分开——前者负责“引擎如何执行X操作”，后者则负责“我们的资源如何被导入”。

| 路径 | 运行环境 |
|------|---------|
| `ue5/import_generated/import_mesh.py` | Unreal的Python环境 |
| `unity3d/import_generated/ImportGeneratedMesh.cs` | Unity编辑器（`Assets/Editor/`目录下） |
| `godot/`公共`GodotClient.assets` API | 主机Python在安全暂存完成后启动Godot 4，并添加`--headless --import`参数 |
| `three_js/import_generated/import_mesh.mjs` | 主机Node环境，需安装项目所需的`three`库 |
| `blender/import_generated/import_mesh.py` | `bpy`解释器（Blender应用程序或pip安装的模块） |
| `scripts/import_generated_asset.py` | 主机Python——它会定位编辑器，启动相应的导入器，读取其生成的JSON报告 |

```bash
python scripts/import_generated_asset.py --engine both \
    --summary test_data/outputs/<game>/<run>/3d_object_results_summary.json
```

其中，`--engine both` 表示同时处理UE5和Unity的数据；`--engine all` 则会额外包含Godot和Blender的数据。兼容性启动器同样接受`--usage {asset,vfx_standalone,vfx_particle}`这类参数，并生成特定于引擎的JSON报告。Godot会输出暂存的`res://`资源信息、实际原生类名称、加载/实例化结果、动画与骨骼路径、源文件大小、可用的GLB三角形数据、警告信息以及编辑器进程的相关记录。具体细节可查看各目录下的README文档。

先决条件：Unity项目中需要安装`com.unity.cloud.gltfast`插件；UE则需要启用`PythonScriptPlugin`，且需通过完整编辑器而非命令行工具来驱动导入过程（UE的README中解释了原因）。Blender无需特定项目或许可证，若未安装Blender应用程序，通过`pip install bpy`即可满足需求。可通过`scripts/engine_install/godot/install.sh --json`或`install.cmd --json`来安装/复用指定版本的Godot 4编辑器；该过程会验证官方的SHA-512校验码及精确的引擎版本。Godot主机代码要求Python版本为3.14及以上。
需设置`A3GAME_GODOT_EXECUTABLE`和`A3GAME_GODOT_PROJECT`环境变量，或通过命令行参数指定相应值。若未设置可执行文件变量，则系统会通过`PATH`路径来查找。Godot材质绑定功能还会运行适配器自带的SceneTree脚本，只有当包含修改后的`MeshInstance3D`节点的已绑定`PackedScene`文件被成功记录并持久化后，该过程才会完成。

## 场景数据

Hunyuan-WorldPlay导出的数据包含Gaussian-splat格式的PLY文件以及零散的多边形PLY文件，并非传统的网格文件；这些多边形会被处理成三角形集合：没有共享顶点、各部分之间存在缝隙，且顶点缠绕顺序混乱。`scripts/prepare_world_asset.py`脚本会将其融合修复为一个连续的`world.glb`文件，供上述导入器像处理其他资源一样使用。该过程无需依赖任何引擎或Blender。

```bash
python scripts/prepare_world_asset.py --src <export_dir> --out out/world --up z
```

## 场景浏览`blender/runtime/`是一个持续运行的Blender进程，它通过UDP接收JSON指令——比如生成角色、操控角色移动、触发特效，以及渲染当前场景。它主要用于解决导入报告无法回答的问题：修复后的世界是否可通行，生成点位置是否与地面重合等。

```bash
python -m engine_adapters.blender.runtime.serve --port 30021
python -m engine_adapters.blender.runtime.send_command \
    engine_adapters/blender/runtime/examples/walk_a_generated_world.json
```

该服务器需要依赖`bpy`库；而发送端无需任何额外依赖，因此可以从任意位置操控渲染节点上的进程。

各引擎的API说明文档会直接嵌入智能体的上下文，单独存放在`agent_skills/engine_context/{ue5,unity3d,godot,blender,three_js}_api.md`路径下。
