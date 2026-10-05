# three.js适配器迁移清单

状态：ThreeClient v1版本、`A3GamePlayable`网页运行时框架已完成开发，游戏包安装、世界场景图发布、Node工具链构建与测试执行以及已实现的API参考文档均已完成。参考用的《竞技场格斗》《第一人称射击》《赛车》游戏包也已被提取出来。平台服务、实时追踪捕获以及受限修复协调器部分则与UE5适配器保持一致。

参考代码库：

- [mrdoob/three.js](https://github.com/mrdoob/three.js) —— 上游引擎基准版本（r185）
- [zhangbo126/ThreeFlow](https://github.com/zhangbo126/ThreeFlow) —— 基于three.js开发的Vue3编辑器

本清单通过镜像UE5适配器的模式，将three.js映射到3AGameFactory架构中。它不会改变现有的A/B/C层、`design_doc.txt`、`pipeline_task.jsonl`文件或输出布局。

## 设计前提

UE5适配器所驱动的引擎本身已经具备渲染、世界管理、帧循环、输入处理、动画、物理计算以及导入管道等功能。而在网页端，three.js仅是一个渲染库。因此，要实现与UE5的功能对等，必须将工作拆分为两部分：

1. **Python适配器**——与`UEClient`拥有相同的11个命名空间，采用相同的结果契约以及代码库任务标识解析方式。这是一种严格的镜像实现，另外还新增了一个网页端需要但Unreal引擎中没有的命名空间（`three.preview`，详见下文）。
2. **JavaScript运行时框架**——涵盖Unreal引擎原生提供但three.js不具备的所有功能：渲染器/循环宿主、资源解析器、世界构建器、输入规范化器、动画调度器、射线检测碰撞基元、HUD图层以及运行时控制通道。

如果没有第二部分，生成的游戏便无基础可依托，每个生成的游戏都不得不重新编写约2000行代码。框架中内置这些基础结构正是为了确保其具备游戏中立性且便于测试。

## 命名空间对应关系

| UE5 | three.js | 结构是否一致？ |
| --- | --- | --- |
| `ue.project.*` | `three.project.*` | 是，额外包含`install_dependencies` |
| `ue.assets.*` | `three.assets.*` | 是，额外包含`import_audio`、`write_manifest` |
| `ue.animation.*` | `three.animation.*` | 是 |
| `ue.bindings.*` | `three.bindings.*` | 是 |
| `ue.world.*` | `three.world.*` | 是，额外包含`get_scene_graph` |
| `ue.plugin.*` | `three.plugin.*` | 是 |
| `ue.build.project` | `three.build.project` | 是 |
| `ue.testing.run_automation_tests` | `three.testing.run_automation_tests` | 是 |
| `ue.runtime.launch_editor` | `three.runtime.launch_dev_server` | 名称已更改；新增`preview_bundle` |
| `ue.runtime.sessions.*` | `three.runtime.sessions.*` | 是 |
| `ue.reflection.*` | `three.reflection.*` | 是，额外包含`list_object_names` |
| `ue.observe.check_status` | `three.observe.check_status` | 是 |
| — | `three.preview.*` | 新增功能：根据指定轴向渲染产物，以便做出朝向判断并记录下来 |

## 刻意设计的差异所有差异的产生都是因为平台不同，而非镜像不完整。

| 关注点 | UE5 | three.js | 原因 |
| --- | --- | --- | --- |
| 传输方式 | 远程控制HTTP + Python远程执行 | Node子进程 + 开发服务器HTTP探测 + 运行时控制通道 | 浏览器无法承载入站RPC端口 |
| 引擎根目录 | `ue_root`（已安装的引擎） | `three_root`（可选的源码检出目录）加上`node_modules/three` | three.js属于npm依赖项，并非独立安装的程序 |
| 资源导入 | Interchange工具构建uasset文件 | 将文件暂存至`public/`目录下 | glTF本身就是运行时格式 |
| 资源寻址方式 | `/Game/...` 包路径 | 清单中的`/assets/...` URL | 浏览器解析的是URL，而非包 |
| 地图格式 | `.umap` 包 | `assets/worlds/<id>.json` 场景图 | 不存在二进制的关卡格式 |
| 框架安装 | 复制插件，在`.uproject`中启用 | 复制包，添加`file:`依赖并配置工作区 | npm解析机制取代了插件发现机制 |
| 构建工具 | UnrealBuildTool | `vite build` | — |
| 测试工具 | 自动化测试报告 | vitest或Playwright JSON报告 | — |
| 扩展契约 | `UINTERFACE` | 抽象类加上鸭子类型验证器 | JavaScript没有接口机制 |
| 组件类型 | `UActorComponent` | `object.userData.a3game` 插槽 | three.js没有组件系统 |
| 帧循环机制 | 引擎tick | `A3GameRuntimeHost.onTick` | 框架必须掌控`requestAnimationFrame`调用权 |
| 物理系统 | Chaos | `A3GameCollisionProbe`射线检测 | three.js不自带物理引擎 |
| 资源释放机制 | 垃圾回收器自动处理 | 需手动调用`dispose()` | WebGL资源不会被垃圾回收器回收 |
| 朝向约定 | 角色正向为`+X`，编辑器会显示该方向 | 每个资源单独记录`orientation.forward_axis`，实例化时应用 | glTF仅修正坐标和单位，不处理朝向问题，且网页环境没有编辑器视口可供观察 |
| 资源预览方式 | 编辑器视口和缩略图 | `three.preview.*`在CPU上渲染正交视图 | 网页环境没有原生编辑器，构建机器也没有GPU或显示器 |

## 实现进度

已完成：- 确定 `from engine_adapters.three_js import ThreeClient` 为唯一的公共 Python 入口点，其具备版本化的结果契约（`ThreeOperationResult`、`ThreeDiagnostic`）；
- 确定 `@a3game/playable` 为生成的游戏玩法对应的唯一公共 JavaScript 导入接口；
- 将 Node 工具链以及开发服务器/运行时传输层置于 `_internal/transport/` 目录下；
- 复用仓库任务标识 `(game_id, run_id, task_kind, task_id, artifact_key)` 来实现公共资源的解析，同时与 UE5 适配器共享 `pipeline.common.paths` 以及每个任务的 `meta.json` 文件；
- 实现纯 Python 编写的 glTF/GLB/纹理/音频检查器，因此验证、反射和元数据提取无需依赖 Node 进程；
- 实现资源暂存、`.gltf` 旁侧文件收集、 artifact 注册表以及运行时资源清单功能；
- 实现基于文件名的槽位推断的 PBR 材质绑定功能，该绑定可在运行时被 `A3GameAssetLibrary.applyMaterialBinding` 调用；
- 实现世界规范、草稿注册表、验证机制、包注册表以及运行时场景图发布功能；
- 实现生成的游戏玩法包安装功能：当声明使用 `@a3game/playable` 时，会自动进行框架同步；
- 实现带有结构化诊断信息解析功能的 `vite build` 执行流程；
- 实现 vitest 和 Playwright 测试执行逻辑：会删除过期的测试报告，拒绝接受早于当前运行周期的测试报告，若测试报告匹配数为零则判定测试失败；
- 实现开发服务器启动功能：包含就绪状态轮询、 bundles 预览功能，且仅允许客户端启动的进程占用该服务器；
- 实现通用的参与者、控制器、实体、绑定以及标准化输入会话状态管理功能，其中不包含 Fighter/FPS/Racing 相关的命令字段；所有操作会被转发至浏览器运行时通道，且传递状态与记录状态分开上报；
- 实现 `A3GamePlayable`，它包含数据类型契约、三个扩展契约、两个组件、两个子系统以及八个引擎基础模块；
- 从 `ThreeFlow` 中提取可复用的 three.js 模式（`renderScene`、`sceneModules`、加载器映射、`disposeScene`、`SkeletonUtils.clone`、HDR 环境、雾效、变换处理），将其整合为与游戏无关的框架模块，同时剔除所有 Vue、Pinia、Element Plus、IndexedDB 以及仅编辑器使用的依赖；
- 提取出 Arena Fighter、FPS、Racing 三类参考游戏玩法包，每类包都包含各自的具体实体、工厂、规则和 HUD；
- 新增一套参考性生成测试套件，无需 GPU 和截图即可验证实体、规则以及快照行为；
- 端到端验证 Python 流程：涵盖项目创建、框架安装、针对 r185 版本的引擎版本检测、资源检查与暂存、清单生成、世界验证、世界发布以及包列表生成；
- 在 Node 20 环境下端到端验证 JavaScript 流程：涵盖会话同步、输入仲裁与传递、快照、扩展功能等。消息分发、实体销毁以及工厂合约防护。

## 布局结构

```text
engine_adapters/three_js/
├── __init__.py                  # 公共入口：仅提供ThreeClient
├── three_client.py              # 用于组装命名空间客户端的门面
├── config.py                    # ThreeClientConfig及其默认配置
├── cli.py                       # 包含create-project、import-asset、run等命令
├── contracts/                   # 定义ThreeOperationResult、ThreeDiagnostic等合约
├── _internal/transport/         # 包含NodeToolchain、DevServerClient等内部传输组件
├── project/  assets/  animation/  bindings/  world/
├── plugin/   build/   testing/   runtime/   reflection/  observe/
├── plugin/A3GamePlayable/       # Web运行时框架
│   └── src/
│       ├── data-types/          # 通用运行时数据合约
│       ├── interfaces/          # 扩展合约
│       ├── components/          # 身份标识、运行时实体组件
│       ├── subsystems/          # 运行时子系统、世界会话管理模块
│       └── engine/              # 主机、资源、世界、输入、
│                                # 动画、碰撞检测、HUD、频道管理等引擎模块
├── examples/                    # 包含arena-fighter、FPS、赛车类示例参考
├── import_generated/            # Node端生成的网格模型查看器
└── MIGRATION_INVENTORY.md
```

## 边界规则

Web平台遵循与UE5适配器相同的规则：

- 生成的游戏代码只能导入`@a3game/playable`，不能访问更深层的内容；
- 生成的游戏代码绝不能直接调用`engine_adapters.three_js._internal`或任何以`_internal`命名的包；
- 生成的游戏代码绝不能硬编码资源URL、`public/`路径或`dist/`路径；
- 生成的游戏代码绝不能调用`requestAnimationFrame`；
- 游戏生成代理绝不会调用`three.testing.*`相关接口；
- 示例包仅为只读引用，不能作为依赖项使用。

## 后续工作

- 平台服务集成（实现与UE5版本的功能对等）；
- 通过`preview_bundle`结合Playwright追踪功能，实现实时追踪与证据采集；
- 为构建和测试诊断功能搭建受限的修复协调机制；
- 提供可选的WebSocket中继功能，以便在不使用本地桥接的情况下支持`runtime_transport="websocket"`配置；
- 开发符合规范的现有制品评估工具。
