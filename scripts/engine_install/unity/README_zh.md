# Unity CLI脚本

这些脚本是对`engine_adapters.unity3d.cli`（即`a3game-unity` CLI）的简易封装。

## 项目路径规范

项目选择由Agent负责。Agent必须传入流水线生成的确切Unity项目根目录，例如：

```text
test_data/outputs/<game_id>/<run_id>/pipeline/<task_id>/unity_project/<ProjectName>
```

其中`<ProjectName>`是指直接包含`Assets/`、`Packages/`和`ProjectSettings/`的目录。切勿传入`pipeline/`、`unity_project/`或项目的`Assets/`目录。这些脚本不会发现、猜测、拼接或重写该路径，也不会自行复制源资源。所有资源和生成的代码输入都必须是经`UnityClient`解析后的标准基准描述符。

要完成一次完整运行，每条命令都应使用相同的项目路径，且保持单一的编辑器生命周期：

```text
Agent选定生成的项目根目录
        -> UnityClient/project.create（仅用于新建空项目）
        -> UnityClient/runtime.launch_editor(项目根目录)
        -> UnityClient/generate_game（执行一次GenerateGame任务）
        -> UnityClient runtime/session/observe
```

生成完整游戏时优先使用`generate-game`命令。仅在进行资源导入操作时才使用`import-batch`。如果可以批量提交资源，就不要逐个调用`import-asset`；否则会创建独立的编辑器任务，甚至触发独立的Unity授权流程。这些脚本仅为命令启动器；项目的创建、资源导入、编译、构建、播放模式以及运行时行为均由公开的`UnityClient`和Unity编辑器负责。

## 命令

### generate-game

要生成完整的游戏，需提供一个包含标准输出描述符和生成场景规格的JSON任务文件：

```bash
scripts/engine_install/unity/generate_game.sh \
    --unity-root /path/to/Unity \
    --project /path/to/generated/pipeline/fps_pipeline_001/unity_project/MyGame \
    --job-file /path/to/generated_game.json
```

`UnityClient.generate_game()`会在项目本地路径下的`Library/GameFactory3A/jobs/`中写入一个清单文件。随后，单个Unity编辑器会话会按顺序执行Unity原生操作：安装已定型的机制/UI程序集，通过`AssetDatabase`导入角色/武器/动作/场景，拼接场景，刷新并编译脚本，运行`BuildPipeline`，必要时还会进入播放模式。这样就能避免为每个阶段都启动一个Unity进程。

该任务必须使用能通过标准路径`test_data/outputs/<game_id>/<run_id>/...`解析的描述符。公开客户端不接受来自`test_samples`或`asset/`的原始路径。

### create-project

```bash
scripts/engine_install/unity/create_project.sh \
    --unity-root /path/to/Unity \
    --project-path /path/to/generated/pipeline/fps_pipeline_001/unity_project/MyGame \
    --dry-run
```

### import-asset```bash
scripts/engine_install/unity/import_asset.sh \
    --unity-root /path/to/Unity \
    --project /path/to/generated/pipeline/fps_pipeline_001/unity_project/MyGame \
    --game-id my_game \
    --run-id run_001 \
    --task-kind 3d_object \
    --task-id task_001 \
    --artifact-key model_path \
    --type prop \
    --dry-run
```

资源导入功能接受的是仓库任务标识（game-id/task-id），而非任意的源路径。如果任务的`meta.json`文件中包含多个非空的`*_path`字段，则必须指定`--artifact-key`参数。移除`--dry-run`参数即可执行Unity导入操作。完整的接口规范可参考`agent_skills/engine_context/unity3d_api.md`。

### 运行
```bash
scripts/engine_install/unity/run.sh \
    --unity-root /path/to/Unity \
    --project /path/to/generated/pipeline/fps_pipeline_001/unity_project/MyGame \
    --scene Assets/Scenes/Main.unity \
    --dry-run
```

移除`--dry-run`参数即可启动Unity编辑器。这个一次性封装脚本不提供停止命令；若需通过编程方式启动或停止，必须复用同一个`UnityClient`实例。

### 批量导入
若要通过一次启动Unity编辑器来导入所有已准备好的资源，需创建一个包含标准描述符的JSON数组（这些描述符的字段与`import-asset`命令所接受的字段一致）：

```json
[
  {"game_id":"gameB_fps_test","run_id":"run_001","task_kind":"3d_object","task_id":"player_char","asset_type":"avatar"},
  {"game_id":"gameB_fps_test","run_id":"run_001","task_kind":"motion","task_id":"jogging","asset_type":"motion","skeleton":"Assets/Generated/Prefabs/player_char.prefab"}
]
```

然后运行以下命令：
```bash
scripts/engine_install/unity/import_asset.sh import-batch \
    --unity-root /path/to/Unity \
    --project /path/to/generated/pipeline/fps_pipeline_001/unity_project/MyGame \
    --batch-file /path/to/assets.json
```

客户端会先解析每个描述符，按照头像/网格、动作、场景的顺序处理，随后调用一次`ImportBatch.RunFromCLI`，并为每个任务返回一份报告。Shell封装脚本本质上只是一个简单的命令启动器。

在Windows系统中，可使用参数相同的对应`.cmd`文件来执行相关操作。

## 环境变量
| 变量名 | 用途 |
|--------|------|
| `A3GAME_PYTHON` | 用于覆盖Python解释器 |

这些封装脚本需要显式指定`--unity-root`参数以及`--project`/`--project-path`参数。运行时主机和端口可通过`--runtime-host`和`--runtime-port`参数指定。如果调用方未传入相应值，`UnityClient`的Python API也能解析其文档中说明的`A3GAME_UNITY_*`系列环境变量。
