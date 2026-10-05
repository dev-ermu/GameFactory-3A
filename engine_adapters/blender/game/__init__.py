"""
engine_adapters/blender/game

The gameplay half of the Blender adapter: what a generated mechanic is built
out of. `../runtime/` drives a *live* Blender for interactive inspection; this
package instead simulates a whole match headlessly, bakes it onto keyframes and
renders it, which is what a benchmark needs — a fixed-timestep run that produces
the same video and the same numbers every time.

    kernel       fixed-timestep loop, actors, event log, the `Game` base class
    prims        shared unit meshes; spawning, aiming, stretching, ribbons
    materials    cached Principled and emissive materials, plus a palette
    assets       resolving an asset reference to a file, and importing it once
    figures      posing a humanoid model from the numbers the rules compute
    clips        playing authored glTF actions (walk, punch, death) on a rig
    camera_rigs  first-person, chase and side-on cameras
    hud          screen-space bars, pips, labels and vignettes as camera-parented geometry
    recorder     keyframe baking, Cycles setup, MP4 and thumbnail export
    controls     the input surface a player drives, and how keys map onto it
    interactive  the same rules stepped live in a window, from a keyboard

A generated mechanic can therefore be watched or played, and the two are not
separate implementations: `interactive` steps the same `tick()` at the same fixed
timestep, and a played session records its input so `Game.run(source=...)` can
re-render it offline and get the same run back.

Everything here imports `bpy`, so it only loads inside Blender or a Python with
the `bpy` wheel. A generated game subclasses `kernel.Game`, and the modules
above are the vocabulary it writes in — see `../examples/`
for four worked examples and `../../../agent_skills/engine_context/blender_api.md`
for the API caveats they were written against.

Blender适配器的游戏逻辑部分：即生成的游戏机制所由构建的内容。`../runtime/`模块用于驱动实时运行的Blender以便进行交互式查看；而该包则会在无头模式下模拟整场比赛，将其关键帧化并渲染输出——这正是基准测试所需要的：一种固定时间步长的运行方式，每次都能生成相同的视频和数值结果。

    内核（kernel）：负责固定时间步长循环、角色管理、事件日志以及`Game`基类；
    基础模型（prims）：共享的单元网格；涵盖模型的生成、瞄准、拉伸及丝带效果实现；
    材质（materials）：缓存好的Principled材质与发光材质，外加调色板功能；
    资源（assets）：将资源引用解析为具体文件，并仅导入一次以节省开销；
    角色建模（figures）：根据规则计算出的数据来设定人形模型的姿态；
    动画片段（clips）：在骨骼模型上播放预先制作好的glTF动画（行走、出拳、死亡等）；
    摄像机系统（camera_rigs）：包括第一人称、跟随视角以及侧面视角摄像机；
    用户界面（HUD）：作为摄像机子对象的屏幕空间元素，如进度条、图标、标签及暗角效果；
    录制器（recorder）：负责关键帧烘焙、Cycles渲染设置，以及MP4视频和缩略图的导出；
    控制逻辑（controls）：玩家操作的输入界面，以及按键到操作指令的映射关系；
    交互模式（interactive）：在窗口中实时运行相同规则，通过键盘进行控制。

因此，生成的游戏机制既可以被观看也可以被游玩，且二者并非独立的实现：`interactive`模式会以相同的固定时间步长执行同样的`tick()`函数；而游玩过程中产生的输入记录会被保存下来，使得`Game.run(source=...)`能够离线重新渲染，得到完全一致的运行结果。

由于此处所有代码都引入了`bpy`模块，因此仅在Blender环境或安装了`bpy`插件的Python环境中才能运行。生成的游戏会继承自`kernel.Game`，上述模块便是编写游戏时使用的工具集——可查看`../examples/`中的四个示例，相关API的使用限制可参考`../../../agent_skills/engine_context/blender_api.md`。
"""

__all__ = ["kernel", "prims", "materials", "assets", "figures", "clips", "hud",
           "camera_rigs", "recorder", "controls", "interactive"]
