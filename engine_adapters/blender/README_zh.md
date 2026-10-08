# engine_adapters/blender

Blender（`bpy`）参考代码——用于资产导入、无头预览以及可游玩会话。

> Blender并非第四个目标引擎。它是生成器与引擎之间的中立环节：它是此处唯一能读取`.ply`和`.usd`格式的适配器，能够修正生成器生成的错误资产的坐标轴或简化其结构，还能无需项目、许可证或GPU即可渲染结果图像，或让你在场景中自由走动。

## 文件

| 路径 | 运行环境 | 用途 |
|------|---------|---------|
| `import_generated/import_mesh.py` | `bpy`解释器 | 导入→处理→测量→重新导出→生成报告 |
| `import_generated/import_motion.py` | `bpy`解释器 | 导入经过重定位的FBX文件并检查姿势动画 |
| `render_preview.py` | `bpy`解释器 | 无头模式下对资产进行旋转展示或静态渲染 |
| `game/` | `bpy`解释器 | 生成机制所依赖的游戏玩法工具包 |
| `examples/` | `bpy`解释器 | 该适配器支持的各类游戏类型机制（第一人称射击/赛车/格斗/RPG） |
| `runtime/` | `bpy`解释器 | 通过UDP传输JSON指令驱动的实时会话——包括生成物体、移动物体、添加特效、生成快照等操作 |
| `../../scripts/import_generated_asset.py` | 宿主Python | 查找Blender安装路径，启动导入程序并读取报告 |
| `../../scripts/prepare_world_asset.py` | 宿主Python | 世界场景导出→生成单个完整的`.glb`文件（无需使用Blender） |

动作绑定/重定位功能不在此处实现——需通过gen_motion流程调用`operators/gen_motion/funcs/retarget_utils/`来实现。

除`runtime/`外，其余均为批处理模式：输入一个文件，输出一个文件，处理完成后进程即终止。`runtime/`属于另一种模式——它是一个长期运行的进程，会持续维护一个可动态变更的场景，用来解答报告无法确定的问题，比如修复后的世界场景是否真的可以让人行走。详情请参阅其自带的README文档。

`game/`属于第三种模式，区分这几种模式很有必要：`runtime/`用于驱动实时运行的Blender，方便人观察场景；而`game/`则是在无人观看的情况下运行完整比赛，将其烘焙为关键帧后再进行渲染。前者用于检查场景，后者用于留存证据。

`game/`也有自己的实时模式——即`--play`参数，它会在窗口中通过键盘输入来触发相同的规则，而非先进行烘焙。这并非第三种实现方式：它使用的是同一固定时间步长的`tick()`函数，且游玩过程中产生的输入记录会被保存下来，以便离线重新渲染出相同的过程。详情请参阅下方的两个章节。


## 运行方式

这里的所有功能可通过两种解释器运行，代码并不区分具体是哪种：

```bash
# Blender应用程序
blender --background --factory-startup \
    --python engine_adapters/blender/import_generated/import_mesh.py -- \
    --src out/model.glb --dest library/ --name Sword_001 --preview
```# 或者使用包含wheel包的Python版本
pip install bpy==4.2.0
python engine_adapters/blender/import_generated/import_mesh.py \
    --src out/model.glb --dest library/ --name Sword_001 --preview
```

在命令 `blender --python x.py -- ...` 中，整个命令行参数都会被传递给脚本，因此双横线 `--` 之后的所有内容都属于脚本的参数。`pip` 安装的wheel包中没有分隔符；`_script_argv()` 函数可以处理这两种情况。

宿主端的启动器会自动找到对应的工具，并且使用的参数格式与UE5和Unity版本一致，比如 `--usage`、`--pivot`、`--target-tris`：

```bash
python scripts/import_generated_asset.py --engine blender \
    --src test_data/outputs/<game>/<run>/assets/3d_object/<task>/model.glb \
    --blender-preview
```

## 单位与坐标轴

Blender采用米作为单位，且坐标轴为**Z轴向上**；glTF同样以米为单位，但坐标轴为**Y轴向上**；UE则使用厘米作为单位，坐标轴也为Z轴向上。glTF导入器和导出器会在两种坐标体系间进行转换，因此经过 `glb → Blender → glb` 的往返转换后数据保持不变——这正是Blender能安全用作生成工具与UE5之间中间层的原因。出于同样的原因，FBX导出器被设置为 `-Z` 方向向前、`Y` 轴向上。

`.ply` 导入器不会进行任何坐标转换，因为PLY文件本身不包含可用于转换的坐标元数据。`scripts/prepare_world_asset.py --up z` 命令会在其他程序处理前，对Z轴向上的世界导出数据进行一次旋转处理。

## 骨骼绑定与动作重定向

角色骨骼绑定和动作重定向功能位于 `operators/gen_motion/funcs/retarget_utils/` 目录下（宿主驱动文件为 `operators/gen_motion/funcs/retarget_motion.py`）。相关详情可查看 `agent_skills/asset_qa/motion_gen_skills.md`。

重定向后的FBX文件生成后，可通过以下命令导入并验证：

```bash
python scripts/import_generated_asset.py \
  --src retargeted.fbx --engine blender --kind motion \
  --blender $A3GF_RETARGET_BPY_PYTHON
```

## 游戏开发工具包（`game/`）

这是生成机制所导入的内容。游戏类需继承自 `kernel.Game` 并实现三个方法：`build()`、`tick()`、`summary()`，其余逻辑由内核自动处理：

| 模块 | 为游戏提供的功能 |
|---|---|
| `kernel` | 固定时间步长循环、`Actor`类、事件日志、世界与光源设置、`main()`函数 |
| `prims` | 共享的单元网格——立方体、圆柱体、球体、平面、扫掠带状物——以及实体生成功能 |
| `materials` | 缓存的原理化材质与发光材质，以及共享调色板 |
| `camera_rigs` | 第一人称、跟随视角和侧面视角摄像机，采用统一的角度定义方式 |
| `hud` | 进度条、图标行、标签、准星和暗角效果，均为绑定到摄像机的几何物体 |
| `recorder` | 关键帧烘焙、Cycles渲染设置、MP4视频及缩略图导出功能 |
| `controls` | 玩家操作的输入界面，以及按键和鼠标操作与该界面的映射关系 |
| `interactive` | 将该界面实时连接到Blender窗口——即 `--play` 模式 |

该设计有三个核心特性至关重要：

**时钟并非系统时钟。** `tick()` 函数按固定的 `dt` 值推进，一次tick对应一帧渲染画面，因此运行过程可复现；在tick N时刻记录的事件在视频中对应的时间为N/帧率，且缓慢的渲染过程不会影响游戏结果。**HUD属于几何体，而非叠加层。**在无头模式下，不存在可供绘制的视口。
控件是挂载在摄像机上的自发光平面，这不仅能让它们自动处于屏幕空间，更重要的是——它们支持关键帧动画：生命值条对应`scale.x`，因此即便在审阅者打开的`.blend`文件中，它仍能正常显示。这些条形图的自发光强度设为1.0，因为渲染时采用的是标准视图变换，该变换会直接裁剪掉超出范围的像素；任何亮度更高的物体都会丢失最暗的通道，屏幕上所有彩色条形图最终都会呈现为白色。

**`hide_render`无法阻挡射线。**将HUD元素或闲置的视觉特效对象从渲染中隐藏后，它们仍会存在于光线投射的依赖图中，从而默默阻挡玩家发射的每一发子弹。`prims.spawn(..., collide=False)`也会同时设置`hide_viewport`，这才是真正将其移除的方法。所有的HUD控件、轨迹线、火花以及视图模型部件都是以此方式生成的。

```bash
# 直接运行随附的示例之一
GAMEFACTORY3A_ROOT=$PWD blender --background --factory-startup \
    --python engine_adapters/blender/examples/FPSExample/game.py -- \
    --out-dir /tmp/fps --duration 8 --no-render      # 仅生成规则，运行时长为8秒
```

运行后会生成`gameplay.mp4`、`thumbnail.png`、`session.blend`、`demo_outputs/events.json`和`demo_outputs/report.json`文件。报告包含了游戏自行计算出的指标以及通过/失败的判定结果，**报告才是最终成果**——无论脚本执行结果如何，`blender --background --python x.py`都会返回0状态码，因此缺少报告就意味着测试失败，而非悄无声息的成功。

## 试玩测试

通过`Controls`功能发现按键映射，而非依赖默认策略：

```python
from engine_adapters.blender import BlenderClient

BlenderClient(
    project_path="engine_adapters/blender/examples/FPSExample",
    duration=8,
    no_render=True,
)
```

设置`no_render=True`可跳过Cycles渲染流程。详情参见`blender_api.md`中的“试玩测试”章节。

## 启动游戏（`--play`）

与预渲染版本不同，该版本可直接通过键盘实时操控。由于需要真实的Blender窗口，因此不能使用`--background`参数：

```bash
GAMEFACTORY3A_ROOT=$PWD blender --factory-startup \
    --python engine_adapters/blender/examples/RacingExample/game.py -- --play
```

生成的游戏机制对应的`launch.sh`旁会有一个`play.sh`脚本，该脚本已预先配置好正确的规格和环境，可直接用于启动游戏。

| | FPS游戏 | 赛车游戏 | 格斗游戏 |
|---|---|---|---|
| 移动 | `WASD`键 | `W`/`S`控制油门，`A`/`D`控制转向 | `A`/`D`键控制步伐 |
| 操作 | 鼠标瞄准，`左键`射击，`R`键换弹 | `空格键`触发手刹 | `J`键轻击，`K`键重击，`L`键防御 |

所有游戏中按`P`键暂停，按`ESC`键退出。方向键的功能与`WASD`键一致；在FPS游戏中，方向键还可用于控制视角——远程显示环境下首先失效的就是鼠标捕获功能，而无法瞄准的射击游戏是无法进行测试的。

要让批量编写的游戏机制能够安全运行，需满足以下四个条件：**时间步长依然没有变化。** 系统时钟决定了游戏逻辑更新的“时刻”，却无法决定每次更新所持续的时间；延迟到达的帧会运行同样的33毫秒游戏逻辑，而延迟极严重的帧甚至会在“债务”被清除前连续执行多达四次更新。根据实际经过的时间来调整固定时间步长，正是导致模拟程序在窗口被拖动时首次崩溃的典型原因。

**没有任何内容被渲染生成。** 由于未调用`Recorder.capture()`，即便游戏会话持续十分钟，每个物体也不会累积多达一万八千个关键帧。

**由EEVEE负责渲染，而非Cycles。** 交互式Cycles渲染模式本质上就像幻灯片播放一样。生成的材质仅为普通的漫反射+自发光类型，EEVEE渲染出的效果与Cycles渲染的视频极为接近，因此玩家看到的游戏关卡和最终渲染结果看起来并无二致。

**游戏规则并不关心是谁在操作。** 游戏程序读取的是`self.controls`；至于这些数据来自键盘输入、录制的操作时间线还是游戏自身的决策逻辑，游戏程序并不关心。正是这一特性为下一节的内容奠定了基础。

### 回放游戏会话

每次游戏会话都会生成`demo_outputs/input_timeline.json`文件——其中记录的是按键与鼠标移动数据，而非游戏结果。将这些数据重新输入程序，就能驱动离线渲染器走完完全相同的流程：

```bash
./launch.sh --replay-input demo_outputs/input_timeline.json --duration 12
```

回放功能能完全复现原始游戏会话——角色位置、射击动作、事件触发顺序均完全一致。这正是该回放功能对基准测试而言有价值的原因：游戏会话不再是凭感觉描述的“体验描述”，而是可重新以全画质渲染并用于对比验证的证据。

“完全复现”是个要求很高的标准，要实现它需经过两次修复。时间线中存储的是以“秒”为单位的时间，而游戏tick时间则是百分之一秒的三分之一；由于`0.0333…`小于`0.033`，会导致系统误判为按键在一帧前就被释放——因此时间边界的比较需基于tick索引而非浮点数。此外，瞄准机制本身是个反馈循环：如果将录制的鼠标移动数据四舍五入到百分之一像素的精度，三百个tick之后就会导致射击失误，进而引发后续的战斗结果差异。这两个问题都是通过回放一个包含354个tick的会话并将其与原始数据对比才发现，这也是唯一能检测出它们的测试方法；即便存在这些漏洞，短时间的测试流程也能顺利通过。

## 无头渲染

pip安装的`bpy`模块可通过GL/EGL上下文来驱动EEVEE和Workbench渲染器。没有显示器的机器无法提供此类上下文，此类错误会表现为`libEGL`崩溃而非异常，因此`render_preview.py`默认采用**CPU版的Cycles渲染器**，一旦请求使用GL渲染引擎却失败，便会自动切换为CPU版Cycles。即便在Cycles渲染模式下，蜡笔类物体仍需通过GL接口处理，这会导致进程无法捕获地崩溃；这类物体会被从渲染结果中隐藏，渲染完成后才会重新显示。

```bash
blender --background --factory-startup \
    --python engine_adapters/blender/render_preview.py -- \
    --src world.glb --out previews/ --mode orbit --format mp4
````--format mp4`参数需要FFMPEG写入器，Blender应用程序会内置该写入器，但**pip安装包中并不包含**——在该安装包里，`file_format`枚举项中根本没有`FFMPEG`选项。`auto`和`mp4`两种模式最终都会回退为PNG序列输出，因此无论哪种设置，生成的旋转动画结果都一样。

输出路径在传递给`bpy`之前会被转换为绝对路径。Blender会根据blend文件解析相对渲染路径，但在无头模式下不存在对应的blend文件，因此渲染过程不会生成任何文件，却仍会报告“渲染完成”。出于同样的原因，所有标注文件名的相关报告字段只有在文件确实写入磁盘后才会被填充内容。

## 依赖项

| 模块 | 所需依赖 |
|------|----------|
| `import_generated/import_mesh.py`、`import_motion.py`、`render_preview.py` | 仅需`bpy` |
| `game/` | 仅需`bpy`——此外还需内置用于生成MP4文件的FFMPEG写入器 |
| `runtime/` | 仅需`bpy`——其中`runtime/send_command.py`根本不需要任何依赖 |

这两个导入模块中的`bpy`导入操作都被延迟执行，因此主机端的启动器和`test/`目录下的脚本无需安装Blender就能读取其中的常量。

## 验证情况

测试环境为**Blender 5.0.1**（pip安装的`bpy` wheel包，Python 3.11，无显示界面、无GPU支持）：
- 导入模块与预览渲染器——具体测试数据及复现方法可查看`import_generated/README.md`；
- 可运行运行时环境——通过`runtime/selftest.py`验证，17个步骤全部通过，5种特效后端均正常工作；此外还通过一个未安装Blender的Python程序通过UDP协议驱动实时服务器进行测试。`runtime/README.md`记录了两个在Blender 5.0.1环境下耗费实际时间排查出的问题。

主机端的相关功能——作业文件、参数结构、层级默认设置——已由`tests/test_world_asset.py`覆盖测试，该测试无需安装Blender。

交互模式在**Blender 4.5.12**上针对三种随附模板进行了验证：键盘与鼠标操作均符合各类型的规则要求，会话循环的固定步长、追赶上限、暂停与退出功能均正常；数百帧的录制会话可完全还原为字节级一致的运行结果。未进行测试的是实时窗口功能，因为该功能需要图形驱动支持——这台主机安装了CUDA计算栈但未安装OpenGL，因此Cycles渲染功能正常，却无法打开窗口。正因如此，`--play`参数会给出相应说明，而不会启动一个无人能看到的会话。
