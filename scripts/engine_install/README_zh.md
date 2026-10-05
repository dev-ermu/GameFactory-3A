# 导入生成的资产所需的引擎前置条件

在`scripts/import_generated_asset.py`将生成的网格模型导入到UE5、Unity或Godot项目之前，这些项目需要满足的要求。此处并不会安装引擎；这些都是编辑器/项目设置，每个项目只需配置一次。

> 面向智能体的引擎接口说明应放在`agent_skills/engine_context/{ue5,unity3d,godot}_api.md`中；本文档则是与`engine_adapters/{ue5,unity3d,godot}/import_generated/`下的导入工具配套的设置清单。

## UE5

| 要求 | 操作方法 |
|---|---|
| 启用**Python Editor Script Plugin**插件 | 路径：`编辑 ▸ 插件 ▸ 脚本 ▸ Python Editor Script Plugin`，或在`.uproject`文件中添加：`"Plugins": [{"Name": "PythonScriptPlugin", "Enabled": true}]` |
| glTF导入功能 | UE 5.x版本中，Interchange组件可直接处理`.glb`/`.gltf`文件，无需额外安装插件。若导入后没有生成任何内容，请检查Interchange插件是否已启用 |
| 编辑器可执行文件 | `UnrealEditor.exe`（注意不是`-Cmd`参数形式）。启动器会在`C:\Program Files\Epic Games\UE_*`或`<驱动器>:\UE_*`路径下查找该文件；也可通过`--ue-editor`参数或设置`$AAAGF_UE_EDITOR`变量来指定路径 |

无需修改`.uproject`文件，也可为单次运行启用该插件：

```bash
python scripts/import_generated_asset.py --src <glb> --engine ue5 \
    --uproject <project>.uproject \
    --ue-extra=-EnablePlugins=PythonScriptPlugin
```

已在UE 5.7版本上验证。关于为何导入工具会调用完整版编辑器而非命令式工具，可查看`engine_adapters/ue5/import_generated/README.md`。

## Unity

| 要求 | 操作方法 |
|---|---|
| **glTFast**插件 | 路径：`窗口 ▸ 包管理器 ▸ + ▸ 按名称添加包 ▸ com.unity.cloud.gltfast`，或在`Packages/manifest.json`文件中添加`"com.unity.cloud.gltfast": "6.16.0"`。Unity本身没有内置的glTF导入功能 |
| 编辑器脚本 | `ImportGeneratedMesh.cs`必须存放在名为`Editor`的文件夹中。启动器会自动将其复制到`<project>/Assets/Editor/`目录下；若想禁用此操作，可使用`--no-install-editor-script`参数 |
| 编辑器可执行文件 | 通常位于`C:\Program Files\Unity\Hub\Editor\<版本号>\Editor\Unity.exe`路径下；可通过`--unity`参数或设置`$AAAGF_UNITY`变量来指定路径 |

导入FBX和OBJ格式文件无需安装额外插件。如果无法将glTFast插件添加到项目中，可生成FBX格式文件：`MeshyModel(output_format="fbx")`。

已在Unity 6000.5.2f1版本、glTFast 6.16.0插件以及内置渲染管线环境下验证。URP和HDRP材质转换功能尚未经过测试。

## Godot 4| 需求 | 操作方法 |
|---|---|
| 引擎安装 | 运行 `scripts/engine_install/godot/install.sh --json` 或 `install.cmd --json`；经过SHA-512校验的官方归档文件会被原子化安装/复用，系统会检测引擎版本，并将相关路径及配置信息输出。 |
| 项目创建 | 使用包含 `project.godot` 文件的目录；引擎验证通过后，通过命令 `python3 -m engine_adapters.godot --project <dir> create-project` 创建简易项目。 |
| 编辑器二进制文件 | 设置环境变量 `A3GAME_GODOT_EXECUTABLE`；若该变量未设置，系统会在 `PATH` 中查找 `godot4`、`godot` 或 `godot-mono` 可执行文件。 |
| 资源导入 | Godot内置的glTF/GLB导入器无需额外插件；适配器会将文件暂存至 `res://` 目录下，随后执行命令 `godot --headless --path <project> --import` 完成导入。 |
| Python环境 | 需使用Python 3.14及以上版本的标准库；适配器无需依赖引擎SDK包。 |

实际开发中优先选用GLB格式。`.gltf` 文件可能会引用配套的缓冲数据和图像资源；公共路径 `GodotClient.assets` 以及兼容性启动器会对这些配套资源进行校验并统一处理。成功导入的资源还会被写入项目的Godot制品注册表，因此能立即在 `GodotClient`、World和Runtime中看到；若注册表写入失败，则导入操作会回滚至文件系统原始状态。
详情请参阅 `scripts/engine_install/godot/README.md` 和 `engine_adapters/godot/import_generated/README.md`。

## 通用注意事项
**运行导入操作前，请先在编辑器中关闭对应项目。** 导入工具会启动独立的编辑器进程；若编辑器已打开，它会继续显示原有的资产浏览器视图，导致导入操作看似没有生效。

## 无引擎环境下验证安装配置
```bash
# 校验制品并输出准确的引擎命令，但不会实际启动引擎
python scripts/import_generated_asset.py --src <glb> --engine both --dry-run
```
