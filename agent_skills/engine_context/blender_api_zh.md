# Blender（`bpy`）——引擎上下文

本文是为使用Blender Python编写代码的开发者准备的API说明。Blender并非游戏发行时所针对的目标引擎；它是**生成器与引擎之间的中立中转站**——在本代码库中，只有它负责读取`.ply`和`.usd`文件，修正生成器产生的轴心点或缩放错误，且无需项目文件、许可证或GPU即可渲染出结果图片。

`blender.playtest.*`并非基准测试工具：它仅记录游戏运行时的实际情况，并不对测试结果做出合格/不合格判定。详情请参阅**Playtest**部分。

推荐参考现有实现进行扩展而非重新编写：
`<REPO_PATH>/engine_adapters/blender/`。

---

## 1. 代码运行环境

此处的所有脚本均在`bpy`解释器中执行，该解释器存在两种形式，代码无需区分具体是哪一种：

| 运行方式 | 启动命令 | 说明 |
|---|---|---|
| Blender应用程序 | `blender --background --factory-startup --python x.py -- ...` | 完整的无头模式应用程序 |
| pip安装包 | `pip install bpy` 后执行 `python x.py ...` | API完全一致；不含GUI相关代码路径，不依赖ffmpeg，Cycles作为插件运行 |

该安装包对解释器版本有严格限制：`bpy` 5.0及4.x版本需要**Python 3.11**，3.6版本对应Python 3.10，其他版本均无对应构建包。在Python 3.9环境下执行`pip install bpy`时，会提示“没有匹配的分发版”，而非版本相关的错误信息。

编写代码时必须考虑以下三点：

**参数解析。** 当使用`blender --python x.py -- --src a`命令时，整个命令行参数都会传递给脚本；其中位于单独的`--`之前的参数属于Blender自身使用。若通过pip安装包运行，则不存在这种分隔符。需同时兼容两种情况：

```python
def _script_argv() -> list:
    import sys
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return [a for a in sys.argv[1:] if a != Path(__file__).name]
```

**退出码不可信。** 无论脚本返回或抛出了什么异常，执行`blender --background --python x.py`后进程退出码始终为`0`。调用方若仅检查退出码，会在脚本完全失败时误以为运行成功。因此需在脚本末尾显式抛出`SystemExit(code)`——在本代码库中，该逻辑受`AAAGF_BLENDER_EXIT_ON_DONE`变量控制，以避免交互式运行时意外终止应用。

**Windows系统下，`--`边界处的长参数或带引号的参数可能无法被正确识别。** 此时应传入一个**作业文件**，文件名由环境变量（`此处为AAAGF_IMPORT_JOB`）指定，程序启动时读取该文件内容。UE5导入器也采用同样的机制，因此主机端的启动器会为每种引擎生成统一的作业格式。

**延迟导入`bpy`模块。** 将导入操作封装在函数中，这样即使未安装Blender，主机端启动器和`<REPO_PATH>/test/`目录下的代码也能读取该模块的常量：

```python
def _bpy():
    try:
        import bpy
    except ImportError as e:
        raise RuntimeError("该模块必须在bpy解释器中运行...") from e
    return bpy
```**务必将所有输出路径设为绝对路径。** 这一点会耗费你一个小时的时间。
Blender会根据Blend文件来解析相对输出路径，而无头模式运行时没有Blend文件。glTF导出器恰好会回退到工作目录，但`bpy.ops.render.render()`不会：它什么也不会写入，仅返回`{'FINISHED'}`，不会记录任何错误，最终生成的文件根本不存在。在将目标路径写入报告前，请先调用`.resolve()`，并确认`path.is_file()`为真。

**pip安装的wheel包并非完整的应用程序。** 它根本不包含FFMPEG写入器——`file_format`枚举中也没有对应条目——因此任何视频路径都会退化为PNG序列，切勿想当然地认为Blender“内置了ffmpeg”。此外，Cycles是以插件形式而非内置组件提供的；详见第5节。

---

## 2. 数据模型

`bpy.data`代表文件内容；`bpy.context`代表当前选中的活动对象；`bpy.ops`是操作层，作用于上下文环境。

```python
bpy.data.objects["Cube"]          # 一个对象：包含变换信息以及指向数据的链接
bpy.data.objects["Cube"].data     # 网格本身——顶点数据存储于此
bpy.data.meshes, .materials, .images, .actions, .armatures
```

**对象**和它的**数据**是两个不同的概念，将二者混淆是导致导出的资源与屏幕上显示不一致的最常见原因。`obj.location = ...`用于移动对象；`obj.data.vertices[i].co += ...`才是移动网格。导出器会对对象的变换进行烘焙，因此在对象层级进行的重新设定枢轴操作在导出时会失效。若要移动顶点，需执行以下代码：

```python
for vertex in obj.data.vertices:
    vertex.co += delta          # 这样修改后才能在导出时保留
```

同理，`bpy.ops.object.transform_apply(scale=True)`操作也遵循这一逻辑。

### 操作需要上下文环境

`bpy.ops.object.join()`会将*选中的*对象合并到*活动的*对象中。该操作没有用于指定“哪些对象”的参数——必须先设置好相关状态：

```python
for other in bpy.data.objects:
    other.select_set(False)
for obj in group:
    obj.select_set(True)
bpy.context.view_layer.objects.active = group[0]
bpy.ops.object.join()
```

当操作的检测条件不满足时（比如模式错误、没有活动对象、插件被禁用），操作会抛出`RuntimeError`异常。请捕获该异常并记录下来；不要因为一次简化操作失败就中止原本正常的导入流程。

### 计算三角形数量

`len(mesh.polygons)`对四边形网格的计数会少一半，且无法考虑修改器的影响。应查询经过计算的网格的循环三角形数量——这才是引擎实际会识别的数量：

```python
depsgraph = bpy.context.evaluated_depsgraph_get()
evaluated = obj.evaluated_get(depsgraph)
mesh = evaluated.to_mesh()
try:
    mesh.calc_loop_triangles()
    count = len(mesh.loop_triangles)
finally:
    evaluated.to_mesh_clear()   # 否则批量处理时会泄露内存
```

---

## 3. 4.0版本中操作名称发生了变化

Blender 4.x将Python编写的OBJ/PLY/STL导入器替换为了C++版本的导入器，且新名称有所不同，旧版本的导入器还会保留一段时间。具体存在哪种导入器取决于构建版本，因此不要硬编码名称，而应同时检测两者：| 格式 | 4.x版本 | 4.0之前的版本 |
|--------|-----|---------|
| `.obj` | `wm.obj_import` | `import_scene.obj` |
| `.ply` | `wm.ply_import` | `import_mesh.ply` |
| `.stl` | `wm.stl_import` | `import_mesh.stl` |
| `.glb` / `.gltf` | `import_scene.gltf` | 同上 |
| `.fbx` | `import_scene.fbx` | 同上 |
| `.usd*` | `wm.usd_import` | 同上 |
| `.abc` | `wm.alembic_import` | 同上 |

```python
def _resolve_operator(bpy, dotted: str):
    group, _, operator = dotted.partition(".")
    namespace = getattr(bpy.ops, group, None)
    if namespace is None or not hasattr(namespace, operator):
        return None
    return getattr(namespace, operator)
```

在缺少对应功能的版本中调用`getattr(bpy.ops.wm, "ply_import")`时，会在调用阶段而非查找阶段触发`AttributeError`。因此需先用`hasattr`进行检查，若不存在则给出包含两种备选名称的提示信息。在5.0版本中，整个旧的`bpy.ops.import_mesh`命名空间为空，所以这种检测并非多余。

渲染引擎标识符也发生了两次变更：EEVEE在4.2之前为`BLENDER_EEVEE`，4.2至4.4期间为`BLENDER_EEVEE_NEXT`，从4.5开始又变回`BLENDER_EEVEE`。使用时需同时列出这两种名称并尝试赋值，同时捕获`TypeError`异常——切勿通过读取枚举值来决定使用哪种，具体原因见第5节说明。

## 3a. 4.4版本中的动画相关变更

`action.fcurves`已被移除；动画数据现在采用插槽式存储，曲线位于图层→条带→通道包之下。插入关键帧的操作保持不变，因此只有后续需要遍历曲线的代码会出错：

```python
def _action_fcurves(action) -> list:
    if hasattr(action, "fcurves"):          # 4.4之前的版本
        return list(action.fcurves)
    return [fc
            for layer in getattr(action, "layers", ())
            for strip in getattr(layer, "strips", ())
            for bag in getattr(strip, "channelbags", ())
            for fc in bag.fcurves]
```

`World.use_nodes`在5.0版本中已被弃用，预计将在6.0版本中被移除；新的世界对象默认就包含着色器树。赋值时应先通过`if world.node_tree is None:`进行判断，而非无条件设置。

---

## 4. 单位与坐标轴

| | 单位 | 上方轴 | 前方轴 |
|---|---|---|---|
| Blender | 米 | **Z轴** | −Y轴 |
| glTF / GLB | 米 | **Y轴** | +Z轴 |
| UE5 | **厘米** | Z轴 | +X轴 |
| Unity | 米 | Y轴 | +Z轴 |

glTF导入器和导出器会在两个方向上进行坐标转换，因此`glb → Blender → glb`的转换结果是**恒等变换**。这正是Blender可以安全地作为生成器和UE5之间的中间层的原因。对于FBX文件，需显式设置坐标轴：

```python
bpy.ops.export_scene.fbx(filepath=..., use_selection=True,
                         apply_scale_options="FBX_SCALE_ALL",
                         axis_forward="-Z", axis_up="Y")
```

`.ply`导入器不会进行任何坐标转换，因为PLY文件本身不携带可用于转换的坐标元数据。若需导出Z轴朝上的世界数据，必须预先通过`scripts/prepare_world_asset.py --up z`进行一次旋转处理，而非每次打开文件时都重复旋转操作。

由于Blender采用Z轴朝上的坐标系，因此`"bottom"`枢轴点对应的是**Z轴最小值**；而`--normalize-scale`参数所设定的目标缩放值为**1.0**（UE5导入器对同样情况的定义是100，因为其以厘米为单位）。## 5. 无头渲染

pip安装的`bpy` wheel包通过GL/EGL上下文驱动EEVEE和Workbench渲染引擎。没有显示器的机器不存在GL/EGL上下文，此时会触发`libEGL`**中止**错误——进程直接终止，无法捕获异常。因此：

- 默认使用**基于CPU的Cycles渲染引擎**（`scene.render.engine = "CYCLES"`、`scene.cycles.device = "CPU"`）。这种方式速度较慢，但总能正常工作。
- 采用防御性方式启用该引擎：`if "cycles" not in bpy.context.preferences.addons: bpy.ops.preferences.addon_enable(module="cycles")`。
- **`CYCLES`并未出现在`engine`枚举中**，因为插件型渲染引擎是以`RenderEngine`子类的形式注册，而非静态枚举成员。在5.0版本的wheel包中，该枚举值为`['BLENDER_EEVEE']`，但设置`scene.render.engine = "CYCLES"`仍能生效，且`scene.cycles.device`属性也存在。判断Cycles是否可用的方法是尝试赋值并捕获`TypeError`异常；若直接读取枚举值，即使Cycles实际可用也会提示它不存在。
- **即使在Cycles渲染引擎下，铅笔画对象也会通过GL路径渲染，且会导致进程不可捕获地崩溃**。渲染前需将其从渲染场景中隐藏，渲染结束后再恢复——可通过`render_preview.hide_gl_only_objects`实现，该逻辑在运行时也会复用，因为重复编写相同规则很容易出现偏差。
- `mp4`格式需要FFMPEG写入器，该程序会捆绑FFMPEG组件，但pip安装的wheel包中并不包含。在该wheel包环境下设置`file_format = "FFMPEG"`会触发错误，因为枚举中不存在该成员。需捕获该异常并改为输出PNG序列图片。
- 渲染到相对路径时不会生成任何文件，却会返回成功结果——详见§1节。

摄像机沿其**−Z轴**方向观察：

```python
direction = target - camera.location
camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
```

`mathutils`模块仅存在于`bpy`命名空间内，因此也需在函数内部导入它。

---

## 6. 骨骼绑定与动作重定向

动作重定向应基于**世界空间旋转差值**，而非直接复制局部旋转：

```
delta_ws  = src_pose_ws @ src_rest_ws⁻¹
target_ws = delta_ws @ dst_rest_ws
```

基于局部坐标系的重定向会继承目标骨骼的旋转参数，从而导致手臂偏移、膝盖反向等问题。而传递世界空间旋转能让结果不受骨骼旋转参数的影响，同时支持替换源动画——无论是Mixamo导出的FBX格式还是MoMask导出的BVH格式都能正常使用，导入器会根据文件扩展名选择对应解析逻辑，根骨骼信息则从映射JSON文件中读取。

基于关节数据和蒙皮权重创建骨骼时的实用要点：

- 在**编辑模式**下创建骨骼（`armature.edit_bones`），在**姿势模式**下调整骨骼姿态。编辑模式之外`edit_bones`属性无效，读取它会引发错误。
- 长度为零的骨骼在退出编辑模式后会被自动忽略。为末端关节设置较小的尾部偏移量即可避免此问题。
- 蒙皮权重需存入与骨骼名称完全一致的顶点组中；Armature修改器会通过名称匹配顶点组，名称拼写错误不会导致报错，只会造成对应肢体无法移动。
- 导出前需先将动画烘焙为关键帧；依赖约束驱动的姿势无法在FBX格式中完整保留。`<REPO_PATH>/operators/gen_motion/funcs/retarget_utils/`（通过`retarget_motion.py`调用）实现了Puppeteer骨骼导入、自动骨骼映射以及世界坐标空间下的动作重定向功能。可使用`<REPO_PATH>/engine_adapters/blender/import_generated/import_motion.py`（参数`--kind motion`）来验证生成的FBX文件。

---

## 7. 报告即契约

切勿要求调用方去解析日志。每个入口点都会返回并写入一个字典：

```json
{
  "ok": true,
  "object": "Sword_001",
  "tris": 24418, "vertices": 12907, "source_tris": 24418,
  "bounds": {"min": [...], "max": [...]},
  "dimensions": [0.31, 0.08, 1.04],
  "materials": ["Material_0"],
  "exports": {"glb": "/out/library/Sword_001.glb"},
  "preview": "/out/library/Sword_001_preview.png",
  "warnings": []
}
```

为确保该字典的实用性，需遵守以下规则：
- 任何异常路径都会将相关信息追加到`warnings`字段中，同时继续处理流程——缺少预览图并不等同于导入失败。
- 即使是成功的有损操作也会触发警告。减面操作始终会发出警告，因为生成低多边形模型（`TripoModel(low_poly=True)`）时会保留UV和法线信息，后续再进行的减面操作并不会改变这些属性。
- 记录调用方测量的数据（`source_tris`）以及Blender测量的数据（`tris`），这样就能直接看到导致网格变化的因素，无需自行推断。
- 在批量处理中，单个有问题的资产只会在其对应的条目中报错，其余资产仍会继续处理。

---

## 8. 使用层级

该定义与UE5和Unity导入器中的定义完全一致，因此无论资产被哪个引擎接收，参数`--usage`的含义都相同：

| `--usage` | 适用场景 | 三角形数量 | 枢轴点 | 缩放 |
|-----------|---------|-----------|-------|-------|
| `asset`（默认值） | 道具、武器、角色 | 保持原样 | 保持原样 | 保持原样 |
| `vfx_standalone` | 单个网格，无粒子效果 | 保持原样 | 重新居中 | 可选 |
| `vfx_particle` | 由粒子系统实例化的网格 | 限制为单个网格的三角形数量乘以实例数 | 重新居中 | 标准化为1米 |

默认设置不会对资产做任何改动。切勿悄悄“优化”已生成的资产。

---

## 9. 世界场景

Hunyuan-WorldPlay导出的内容并非网格文件。它包含Gaussian-splat格式的PLY文件（用于呈现视觉效果）以及一个或多个多边形PLY文件（用作碰撞体），而这些多边形是以**三角形碎片**的形式存在的：没有共享顶点、各部分之间存在缝隙、缠绕顺序混乱。直接将原始PLY文件导入Blender可以查看生成器输出的结果，但这并不能算作合格的资产。

需先运行`<REPO_PATH>/scripts/prepare_world_asset.py`——它会合并各个部分并将表面修复为一个连续的`world.glb`文件，无需借助Blender或任何游戏引擎即可使用。修复功能的具体实现位于`<REPO_PATH>/models/common/mesh_repair.py`；`<REPO_PATH>/models/README.md`详细说明了每个步骤的作用，以及为何填补孔洞时需要区分真正的孔洞和开放的边界。

---

## 10. 实时会话`<REPO_PATH>/engine_adapters/blender/runtime/` 是该适配器中不属于批处理流程的部分：它是一个持续运行的Blender进程，通过UDP接收JSON指令，因此在对引擎介入之前就能在场景中自由探索。当涉及“空间内的行为”相关问题时，就可以用它来查询——比如某个门能否通行、角色生成点是否在地面上——这些信息是任何导入报告都无法给出的。

**关键规则：`bpy`模块不是线程安全的。** 套接字线程绝对不能直接操作Blender。需要先解析数据报并将其放入队列，再由主循环来处理——只有在这里，命令才能调用`bpy.ops`。在该代码库中，接收器甚至不会导入`bpy`，因此这种边界划分是结构性的，而非需要人为记忆的约定。

```python
def _enqueue(self, command, payload):   # 接收线程：仅负责入队
    self._pending.put((command, payload))

def drain_pending(self, max_ops=32):    # 主线程：在此处使用bpy
    ...
```

要限制命令处理的数量。一次批量导入操作可能耗时数秒，若不加限制会导致程序卡顿。不要想当然地认为每个时间步长都是固定的，应测量每个时间步长的实际耗时并加以限制：如果一个时间步长花费了1秒来导入场景数据，将其直接集成到游戏中会导致所有正在跳跃的角色瞬间瞬移。

针对5.0.1版本做了三项测试，结果看似像是你代码中的漏洞，实则另有原因：

- **Mantaflow域加上流体对象会导致Blender无法正常退出。** 清理工作会在所有任务完成后才执行，因此运行成功时也会返回崩溃退出码。删除这些对象或修改器无法解决问题；唯有执行`bpy.ops.wm.read_factory_settings(use_empty=True)`才能修复。如果场景中曾存在流体，需在解释器关闭前清空相关文件。
- **`os._exit`并非跳过复杂清理流程的安全方式。** 加载了`bpy`后，该函数在Windows上会出错，反而造成了它本想避免的崩溃。应正常退出程序，再移除那些无法处理的清理逻辑。
- **Grease Pencil在4.3版本中改变了生成机制。** 笔触不再直接附属于帧（`frame.strokes.new()`，点坐标为`.co`），而是被归入帧所拥有的绘图对象中（`frame.drawing.add_strokes([n, ...])`，点坐标为`.position`）；5.0版本废弃了旧版API。判断时应通过`hasattr(frame, "drawing")`来检测，而非依赖版本号。

命令载荷既可以是手动编写的，也可以是自动生成的：旋转角度采用**度**为单位，距离采用**米**为单位，所有合理的参数都设置默认值；生成角色的指令应通过ID保证幂等性——因为UDP不保证消息一定能送达，重试的发送方绝不能因此创建出两个相同的角色。

---

## 11. 试玩测试

- `blender.playtest.record`：驱动`game.py`执行探测到的操作，并生成`frames/`、`video.mp4`以及`report.json`文件。这回答了游戏自身使用`--no-render`参数运行时无法解答的问题：*游戏能否正常运行*。该运行模式由无人值守策略驱动；测试人员按下游戏宣称会响应的按键，并记录下发生的情况。利用它可确认生成的机制是否有效，也能生成可供人观看的视频片段。它只是佐证材料，并非权威基准——后续评估报告中的`checks`字段会说明录制内容完整，`game_state`则用于判断游戏是否做出了响应。

```bash
python -m pipeline.code_gen.playtest.run \
    --engine blender \
    --project test_data/outputs/<game>/<run>/mechanic/<task> \
    --duration 10 --fps 20 \
    --no-render

python -m pipeline.code_gen.playtest.eval --report <out_dir>/report.json
```

`run.py`不会记录任何数据也不会打分；`eval.py`会读取已写好的报告且同样不记录任何内容。`--no-render`参数会跳过Cycles渲染器；若要生成`video.mp4`，可去掉该参数。适配器`blender.playtest.record`仍可直接调用。

### 这不是屏幕录制

这些机器上没有显示器，因此无法使用EEVEE渲染器：它需要GL/EGL上下文，否则会触发`libEGL`错误而非抛出异常。模拟过程以**固定时间步长**驱动（这正是`Game.run`原本的功能），一个时间步对应一帧预渲染内容，随后由Cycles渲染该预渲染范围。无论每帧实际耗时多久，视频都能以目标帧率流畅播放。

`--play`参数对应的是另一种场景：它需要真实的窗口。而测试运行不会打开窗口。它会填充`controls.ScriptedSource`，并运行与`--replay-input`参数相同的循环。

### 不可协商的限制条件

每一条限制都是经过反复尝试后总结得出的。`playtest/record.py`文件中包含了这些要求。

1. **输入必须是真实的`Controls`对象。**按键信号会通过`ScriptedSource`/`from_held`传递，这是键盘操作对应的处理表。**没有任何程序会直接操控角色**，因为若录制内容直接定位角色位置，那只能说明存在补间动画，而非游戏具备可玩性。`report.json`中的`game_state`字段可用于验证这一点——真实的游戏运行会显示`shots_fired`/`kills`数值变化，或汽车离开起始线。
2. **时钟以时间步长为基准。**捕获的一帧对应一次模拟步骤。按相同速率编码能保证视频的准确性，无论Cycles渲染耗时多久。若依靠系统时钟推进模拟，渲染缓慢时就会出现画面“瞬移”现象。
3. **退出码不可信。**无论脚本执行结果如何，运行`blender --background --python x.py`都会返回0。最终结果需以磁盘上的报告为准。`AAAGF_BLENDER_EXIT_ON_DONE`参数能让Shell也识别到这一结果。
4. **输出路径必须为绝对路径。**Blender会根据blend文件解析相对渲染路径，而无头模式下不存在blend文件：此时渲染操作不会写入任何内容，却会返回`FINISHED`状态，看似执行成功。
5. **pip安装的包中不含FFMPEG写入器。**视频路径必须降级为PNG序列，不能想当然地认为Blender自带ffmpeg。当`PATH`环境变量中包含`ffmpeg`时，才会从MP4文件中提取JPEG格式的`frames/`帧。**要调整视频效果，只需修改录制内容，切勿改动游戏本身。** 第一人称视角下角色盯着墙壁的画面，需要在录制器中设置镜头扫描，而非在`tick()`函数里用`player.yaw =`来操控。

### 操作行为靠自动发现，而非手动配置

如果录制器需要人为指定按下哪些键，那每款游戏都得对应一套新脚本。相比之下，我们按顺序询问正在运行的游戏，再由`report.action_source`指明是哪个来源给出了答案：

| 来源 | 提供的内容 |
|---|---|
| `Game.playtest_actions` | 游戏自行声明的操作方案 |
| 对应`genre`类别的`AXIS_BINDINGS`/`BUTTON_BINDINGS` | `from_held`函数调用的映射表 |
| 内置默认方案 | WASD + 空格 + 鼠标点击，确保没有额外标注的游戏也能正常录制 |

录制器会遵循两条规则，因为一旦违反这些规则，录制的游戏画面就会显得没有响应：
- **移动操作需持续按住；动作指令需轻点触发。** 持续一帧的`forward`指令只能让角色移动几厘米；反之，离散的动作指令必须释放后才能生效——比如半自动武器若未释放扳机就不会连续发射。
- **重复的操作会被忽略。** 绑定设置中可能会同时把`W`和`UP_ARROW`都设为前进指令；若依次按下这两个键，只会录制一次相同的操作。

有特定叙事需求的游戏应在`Game`子类中声明`playtest_actions`——格式为`{id, keys?, taps?, mouse?, duration?}`——这种方式显然优于自动发现机制，因为只有游戏自身才知道敌人的位置。自动发现只是最低要求，并非最佳方案。

### 无声的早期返回会导致整段录制作废

任何悄无声息出错的环节都必须有对应的提示机制。录制器会记录每个操作的`executed_actions[].ok`状态和对应帧数，若没有捕获到任何操作则会判定本次录制失败。自定义方案也应遵循同样的逻辑。

**正式录制前先做一次`--no-render`测试。** 这仅需几秒钟，就能发现空的`game_state`问题，否则整个Cycles录制过程都会付诸东流。

### 成本说明

在Cycles CPU模式下，640x360分辨率、20帧/秒、采样率8 spp时的录制成本如下：

| 游戏类型 | 单帧处理时间（大致） | 10秒视频所需时长 |
|---|---|---|
| 第一人称竞技场类游戏 | 约1秒 | 几分钟 |
| 赛车/森林场景类游戏（视野更广、几何细节更多） | 耗时更长 | 耗时更久 |

因此默认的`timeout`设置为900秒。`--no-render`选项适合在循环流程中使用。

---

## 12. 快速参考

```python
# 清空文件。——即便使用--factory-startup参数，仍会加载默认立方体。
bpy.ops.wm.read_factory_settings(use_empty=True)

# 获取物体的世界空间边界框。
corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]

# 获取经过变换后的物体尺寸。
obj.dimensions            # 单位为米的一个Vector对象

# 获取实际被赋给物体的材质名称。
[slot.material.name for slot in obj.material_slots if slot.material]

# 按名称应用修改器（若应用失败会抛出RuntimeError异常）。
bpy.context.view_layer.objects.active = obj
bpy.ops.object.modifier_apply(modifier="AAAGF_Decimate")

# 仅导出选中的物体。
bpy.ops.export_scene.gltf(filepath=p, export_format="GLB", use_selection=True)
```
