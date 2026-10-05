# `runtime/` —— 可游玩的Blender会话

`engine_adapters/blender/` 目录下的其他内容都属于批量处理任务：输入一个文件，输出一个经过处理的文件，流程随即结束。而这里属于另一种模式：一个长期运行的Blender进程会持有一个场景，该场景中的物体会在运行过程中被修改。

之所以存在这种模式，是因为有些问题仅靠报告无法解答。`import_mesh.py` 会告诉你某个世界包含24万个三角形且没有裂缝；但它无法告知你门口太窄无法通行，或者修复后的地板比角色生成点高出一米。要回答这类问题需要有一个可供角色移动的环境，而在这里解决这些问题，成本远低于在导入UE5之后才处理。

## 与它交互

先启动一个会话，然后通过UDP发送JSON指令：

```bash
# 需要用到bpy——即Blender自带的Python环境，或是安装了对应pip wheel包的3.11环境
python -m engine_adapters.blender.runtime.serve --port 30021

# 发送端无需额外依赖；它只需要套接字和JSON文件即可
python -m engine_adapters.blender.runtime.send_command \
    engine_adapters/blender/runtime/examples/walk_a_generated_world.json

python -m engine_adapters.blender.runtime.send_command \
    --type render_snapshot --payload '{"samples": 16}'
```

每个数据报对应一条指令，格式为 `{"type": ..., "payload": {...}}`。选择UDP协议是因为通常的发送端是控制器，会以帧率持续发送输入指令，此时丢包比指令阻塞更可接受；同时这也意味着发送端无需安装Blender、无需共享文件系统，也只需用到`socket`库即可。

设置`BLENDER_ASSET_ROOT`变量后，路径为`/Library/...`的资源会基于该变量解析。其他路径则会被视为真实路径，因此在一台机器上编写的命令文件可以在另一台机器上运行。

## 指令说明

| 类型 | 参数 |
|---|---|
| `ensure_player` | `entity_id`、`obj_path`、`spawn_location?`、`rotation?` —— 通过`entity_id`确保操作的幂等性 |
| `destroy_player` | `entity_id` |
| `load_action` | `entity_id`、`action_path`、`loop?`、`play_rate?` |
| `apply_input` | `entity_id`、`move_x`、`move_y`、`run`、`jump`、`yaw`、`pitch` |
| `load_scene` | `scene_path`（仅限`.blend`格式）、`link?` |
| `import_scene` | `scene_path`（生成的网格/USD文件）、`collection_name?`、`scale?`、`location?`、`replace_existing?` |
| `clear_scene` | —— 删除`player_*`和`vfx_*`类的物体，保留其他物体 |
| `set_preview_character` | `obj_path`、`scale?`、`yaw?`、`reframe?` |
| `play_preview_action` | `action_path`、`loop?`、`play_rate?` |
| `apply_camera_input` | `yaw_delta`、`pitch_delta`、`zoom_delta`、`pan_y?`、`pan_z?` |
| `trigger_vfx` | `vfx_kind`、`entity_id?`、`location?`、`params` |
| `clear_vfx` | `name?` —— 若省略该参数则清除所有已生成的特效 |
| `join_world` / `leave_world` / `destroy_session` | 会话生命周期管理 |
| `render_snapshot` | `filepath?`、`resolution?`、`engine?`、`samples?` |
| `save_blend` | `filepath?` |
| `dump_scene_report` | `filepath?` |

旋转角度和相机偏移量以**度**为单位；位置和距离以**米**为单位。这些指令既有人工编写也有自动生成的情况，而用弧度表示在JSON中可读性较差。

## 布局```
runtime/
├── serve.py            # 启动+Tick循环；整个程序仅三行代码
├── send_command.py     # 客户端；不依赖bpy
├── selftest.py         # 完整测试流程，无界面模式运行
├── snapshot.py         # 渲染/保存/描述实时场景
├── subsystem.py        # 负责管理各组件及线程边界
├── input/              # 接收器（UDP线程）+ 调度器（命令表）
├── players/            # 玩家、管理器、运动逻辑相关代码
├── assets/             # 路径解析器、导入器、动画剪辑
├── scene/              # .blend场景集、生成的世界、预览舞台、摄像机
├── vfx/                # 特效管理器 + 粒子/几何节点/ grease pencil/流体效果
└── examples/           # 正在运行的会话中可发送的指令文件
```

### 唯一的结构性规则

`bpy`不是线程安全的。UDP接收器绝不会直接操作Blender——它仅解析数据报并将其加入队列。`Subsystem.drain_pending()`在主线程中运行，是命令能够调用`bpy.ops`的唯一入口。该包可能出现的所有死锁和隐蔽数据损坏问题，都源于跨越了这一界限，因此接收器甚至不会导入`bpy`。

### 共享而非复制的内容

- 后缀→导入操作符的对应关系由`import_generated/import_mesh.py`中的`import_file`定义。离线读取`.usdz`格式的构建过程也在此处处理。
- Grease pencil隐藏功能和Cycles启用功能分别对应`../render_preview.py`中的`hide_gl_only_objects`和`enable_cycles`。若这些设置出错，不会导致异常，而是会直接终止进程，因此这两段代码各只有一份副本。

## 无界面模式渲染

出于相同原因，遵循与`../render_preview.py`相同的规则：

- **CPU上的Cycles**是默认且作为备选的渲染方式。EEVEE和Workbench渲染需要依赖GL/EGL上下文，而没有显示器的机器不具备该环境，此类错误会导致进程终止而非抛出异常。
- **渲染时会隐藏Grease pencil**。即便在Cycles模式下，它仍依赖GL渲染，会直接导致进程崩溃且无法捕获错误。
- **`save_blend`是解决问题的途径**。无界面渲染器跳过的所有内容都会保存在文件中，用Blender图形界面打开该文件时就能正常显示。

## 已验证

`selftest.py`会执行完整测试流程：包括测试夹具、`.blend`场景集、生成的`.glb`世界、能实际移动的生成角色、五种特效后端、Cycles-CPU渲染、`.blend`文件、场景报告，最后进行清理：

```bash
python -m engine_adapters.blender.runtime.selftest
OUT_DIR=D:/scratch/runtime python -m engine_adapters.blender.runtime.selftest
```

在**Blender 5.0.1**（通过pip安装的`bpy`插件，Python 3.11环境，无显示器、无GPU）下测试：
17个步骤全部通过，5种特效后端全部验证无误，退出码为0。

这是针对Blender安装环境的诊断工具，并非单元测试——它检测的是机器的属性。不涉及`bpy`的主机端逻辑则由`tests/test_world_asset.py`覆盖测试。

### 值得留意的Blender 5.0.1的两个发现

这两项都是在本地测试得出的，乍看之下像是代码中的漏洞，但仔细排查后会发现并非如此：- **流体模拟会导致Blender无法正常退出。**一旦Mantaflow域和流体对象同时存在，在所有工作完成后就会出现崩溃故障——对于检查退出代码的程序而言，这会被视为运行失败。附带的Mantaflow脚本与编译后的模块不兼容（`LevelsetGrid`没有`setConst`属性）。删除这些对象无法解决问题，移除修改器也无济于事；只有清空文件才能解决，而这正是`Subsystem.shutdown()`的作用。调用该函数即可，或者`serve.py`和`selftest.py`也会执行相应操作。
- **`os._exit`并非安全的快捷方式。**在加载了`bpy`模块的情况下，它在Windows系统上会引发故障，因此用它来跳过复杂的清理流程反而会触发原本想避免的崩溃。应正常退出程序，再清除那些清理流程无法处理的内容。

### 4.3版本中铅笔工具的生成逻辑发生了变化

以往笔触是依附于帧对象的（`frame.strokes.new()`，笔触点通过`.co`访问）；现在笔触则依附于帧所拥有的绘图对象（`frame.drawing.add_strokes([...])`，笔触点通过`.position`访问）。Blender 5.0已完全弃用旧版API。`vfx/grease_pencil.py`同时支持两种写法，因为该适配器的重定向功能仍兼容4.2版本。
