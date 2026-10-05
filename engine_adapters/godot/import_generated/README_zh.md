# 将生成的资源导入Godot

当支持的源资源被放置在`res://`目录下时，Godot会自动导入它们。因此，适配器会在配置好的项目中部署已注册的3AGameFactory任务产物，并调用Godot的仅导入模式编辑器：

```text
godot --headless --path <project> --import
```

可通过自动化工具中的公共任务标识API来实现操作：

```python
from engine_adapters.godot import GodotClient

client = GodotClient("/projects/MyGame")
result = client.assets.import_prop(
    {
        "game_id": "demo",
        "run_id": "default",
        "task_kind": "3d_object",
        "task_id": "crate",
        "artifact_key": "glb_path",
    }
)
```

对于单次使用的文件系统产物，兼容性启动器会执行相同的事务性暂存、原生资源校验以及产物注册流程，随后生成对应的JSON报告：

```bash
python scripts/import_generated_asset.py --engine godot --src model.glb \
  --godot-project /projects/MyGame
```

`--godot-project`参数和`A3GAME_GODOT_PROJECT`环境变量既可接受项目目录路径，也可接受其中的`/projects/MyGame/project.godot`标记文件；显式指定的参数优先级更高。Godot可执行文件的查找顺序为：首先查找`--godot`参数指定的路径，其次查找`A3GAME_GODOT_EXECUTABLE`环境变量的值，最后在`PATH`中搜索。每个变量仅有一个名称，不存在旧版的`AAAGF_*`备用变量。

`.gltf`文件引用的本地缓冲区/图像文件会先经过预检、复制，再与主文档一同处理。网格资源的默认存储路径为`res://assets/imported/props`；若指定`--kind motion`参数，则默认路径为`res://assets/imported/motions`。可通过`--godot-dest`参数覆盖这些默认路径。

仅返回值为0的`--import`退出代码并不代表导入成功：如果导入过程中出现错误输出，或者Godot后续无法加载对应资源，都会触发回滚机制。道具资源必须是可实例化的`PackedScene`类型；运动资源除了需包含动画外，还必须包含`Skeleton3D`节点以及针对骨骼的轨道；导入的glTF/GLB格式运动资源会标注其实际的`PackedScene`类名称。回滚操作还会删除或恢复Godot相关的`.import`元数据以及匹配的`.godot/imported`缓存文件。成功导入的资源会被登记到`A3GAME_GODOT_ARTIFACT_REGISTRY`中，该注册表同样被`GodotClient`、浏览器服务端、World模块以及运行时环境使用。若注册或报告写入失败，系统会恢复之前的注册表数据，并将导入的资源、附属文件及缓存作为一笔事务一并回滚。

建议优先选择GLB/glTF格式来存储网格和动画数据。FBX格式的支持程度取决于所安装的Godot 4版本及导入器配置。
