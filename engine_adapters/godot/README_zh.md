# Godot适配器

`engine_adapters.godot`是适配Godot 4版本的适配器。它唯一的公开Python入口点是：

```python
from engine_adapters.godot import GodotClient

godot = GodotClient(
    project_path="/projects/MyGame",
    godot_executable="/opt/godot/godot",
)
```

它与其他完整适配器一样，提供了相同的11个命名空间：`project`、`assets`、`animation`、`bindings`、`world`、`plugin`、`build`、`testing`、`runtime`、`reflection`和`observe`。所有操作都会返回统一的`{ok, operation, artifacts, diagnostics, warnings, errors, payload}`结构。

在创建客户端实例之前，请先安装或复用指定版本的官方编辑器：

```bash
scripts/engine_install/godot/install.sh --version 4.5.1 --json
```

这款跨平台安装程序是非交互式的，能自动识别架构，会验证官方的SHA-512校验值，以原子方式完成安装，还会检测实际安装的版本，并输出相关的PATH和配置信息。该安装程序以及本适配器均要求使用Python 3.14及以上版本。详情请参阅`scripts/engine_install/godot/README.md`。

## 配置说明

- `A3GAME_GODOT_PROJECT`：项目目录或`project.godot`文件。
- `A3GAME_GODOT_EXECUTABLE`：Godot 4编辑器可执行文件。如果该变量未设置，系统会从`PATH`中查找`godot4`、`godot`和`godot-mono`这几个可执行文件。

每个Godot变量都只有唯一名称——不存在传统的`AAAGF_*`/`A3GAME_GODOT`回退机制，因为配置源只有一个：由`.env`文件生成的`settings`实例。
- `A3GAME_GODOT_RUNTIME_HOST`/`A3GAME_GODOT_RUNTIME_PORT`：原生运行时UDP桥接地址；默认值为`127.0.0.1:30050`。
- `A3GAME_GODOT_EDITOR_TIMEOUT`/`A3GAME_GODOT_IMPORT_TIMEOUT`：编辑器子进程的超时时间（单位：秒）。
- `A3GAME_GODOT_DATA_ROOT`：适配器私有的持久化状态存储路径（用于存放注册表、绑定信息、报告以及导出所有权密钥）；默认路径为`<project>/.a3game`。
- `A3GAME_GODOT_ARTIFACT_REGISTRY`：可选的制品注册表文件覆盖项。该文件必须是普通的严格JSON格式文件，不能是符号链接或特殊节点；读写过程中会拒绝非标准的`NaN`和无穷大常量。
- `A3GAME_GODOT_WORLD_REGISTRY_ROOT`：可选的世界草稿/包目录覆盖项；默认路径为`<data-root>/worlds`。

适配器管理的所有状态路径都会逐组件进行检查。数据根目录、`worlds`/`drafts`/`packages`、`bindings`、`reports`和`build`这些层级结构必须只包含普通目录，而其中的文件则必须是常规文件。一旦在任何层级发现符号链接或特殊节点，系统在读取、替换外部文件或用于回滚操作前就会直接报错。

## 实际的引擎路径

项目验证过程会解析`res://`和`uid://`路径下的主场景；如果启用了引擎检查功能，还要求Godot引擎本身能够加载并实例化解析后的资源，生成`PackedScene`对象。即使禁用引擎检查功能，文本场景仍需包含`[gd_scene]`头部；而二进制UID解析则必须依赖Godot引擎。资源导入过程会将已注册的任务产物复制到 `res://assets/imported/` 目录下，随后执行文档中说明的 `godot --headless --path <project> --import` 生命周期流程。该适配器需要 Godot 4.x 可执行文件，且会拒绝所有导入/资源错误，包括文件损坏、解析错误以及依赖图像解码相关诊断信息，即便 `--import` 命令的退出码为 0 也会如此。之后，适配器会要求 Godot 加载生成的 `res://` 资源。

可实例化的资源必须能作为可实例化的 `PackedScene` 加载；道具、武器、静态网格和角色模型必须包含 `MeshInstance3D`，角色模型还需具备蒙皮网格和 Skeleton3D 骨骼。运动场景会保留其原始的 `PackedScene` 类，且必须包含动画、Skeleton3D 以及以骨骼为目标的轨迹。只有上述所有原生校验都通过后，对应的产物才会被录入注册表。

`assets.import_batch()` 会对相同的任务描述符进行预检，并按依赖顺序导入：先导入角色模型和网格/材质输入，再导入运动数据，最后导入场景、特效和音频。批量任务的默认名称为 `task_id`，可避免与通常命名为 `artifact.glb` 的生成文件产生冲突。运动目标可以是明确的 Skeleton3D NodePath，也可以是已注册的角色模型产物 ID、资产 ID 或 `res://` 路径；角色模型引用会解析为经过验证的原生骨骼路径。

通过 `assets.register_resource()` 可以添加现有项目资源。该操作仅接受项目中合法的 `res://` 格式文件，需要 Godot 4 能够加载该文件并匹配所选资产类型，系统会根据检测结果确定其原生类和可实例化属性，最终返回与其他公共 API 一致的结构化操作结果。原始的注册表和适配器内部的事务写入路径属于私有实现细节，对用户不可见。

由于 Godot 4 会将纯 `.obj` 文件加载为 `ArrayMesh`，因此这类文件无法用于可实例化类型，需先将其转换为 GLB/glTF 格式，或将其封装进 Godot 场景中。glTF 主文件和本地附属文件会一起进行预检并作为单个事务提交，因此默认的“不替换”模式无法覆盖现有的缓冲区或纹理。若校验失败，系统会恢复被替换的源文件、其对应的 Godot `.import` 元数据以及匹配的 `.godot/imported` 缓存文件；同时会删除新生成的相关文件，且不会更新资产注册表。

`bindings.bind_pbr_material()` 用于创建/导入材质，它会调用 Godot 将该材质应用到所有 `MeshInstance3D` 上，并将绑定后的 `PackedScene` 资源保存到 `res://assets/imported/material_bindings/` 目录下，同时原子性地重新定位已注册的网格产物。系统会保留一份清单以供审计，而绑定的场景才是后续运行时操作实际使用的资源。构建过程需要在 `export_presets.cfg` 文件中指定一个命名好的预设，并运行 `--export-release`、`--export-debug` 或 `--export-pack` 命令；如果退出代码为0但没有生成所请求的输出文件，则视为构建失败。即便Godot的退出代码为0，只要存在错误诊断信息，构建也会失败，因此解析/编译错误会导致无法发布已暂存的导出内容。每次导出内容都会先写入独立的暂存目录，这样即便Web导出失败，也不会覆盖现有构建中的部分 `.html`、`.wasm`、`.pck`、`.js` 文件或配套图片资源，也不会留下残缺文件。

适配器会将已提交的同组文件的内容校验值记录在经过签名的所有权清单中；其签名密钥存储在配置的适配器数据根目录下（默认为 `A3GAME_GODOT_DATA_ROOT` 或 `<project>/.a3game`）。只有当文件未发生变化且受管文件集通过身份验证时，后续构建才会替换其中仍存在的成员。如果清单中缺少某成员记录，且已签名的清单及所有现存成员均有效，则可从新暂存的构建中重新生成该成员。一旦修改清单、替换已存在的记录输出，或遇到没有有效所有权的现有输出文件或配套资源，操作便会直接失败；指向 `project.godot`、`export_presets.cfg` 或所有权密钥的路径也会被拒绝。提交前会对目录导出内容进行递归检查，其中不得包含符号链接，包括指向项目输入文件、适配器状态或外部可变内容的链接。

请务必将适配器数据根目录设为私有且持久化存储，若需指定输出路径，请勿指向项目源代码或外部管理的工件。

原生测试报告同样会写入私有的同级暂存路径，经过模式验证后会原子性地发布。如果报告路径包含符号链接、使用了特殊的文件系统节点，或指向 `project.godot`、选定的运行器或检测到的原生测试脚本，那么在Godot启动前就会被拒绝。原生 `run_test()` 函数的返回值必须是布尔值，或是包含布尔型 `ok` 字段的字典；其他类型的值会直接导致构建失败，不会被强制转换为布尔值。

世界草稿仅接受处于就绪、可实例化状态的 `scene` 记录：这类记录中注册的 `res://` 路径必须对应真实的Godot场景或可导入的资源，且其后端类必须为 `PackedScene`。Godot还会加载并实例化该原生资源；草稿创建、验证及发布流程都会重新核对这一约束条件。持久化的草稿和软件包会使用严格的版本化模式。未知版本、缺失或类型错误的字段、非法的生命周期状态、不匹配的记录/文件ID以及格式错误的JSON都会导致公开操作失败；软件包列表绝不会默默跳过损坏的记录，也不会凭空生成对应的工件。

`world.create_draft(spec, *, draft_id="", project_id="", metadata=None)` 与其他完整适配器的逻辑一致：非空显式指定的ID会覆盖 `spec` 中的对应值，显式指定的元数据会与 `spec` 中的元数据合并。`world.list_packages(*, project_id="", world_id="")` 会应用这两个可选过滤条件。`plugin.install_framework()`会将`A3GamePlayable`作为项目插件安装。其自动加载功能可接收与游戏无关的会话消息以及标准化输入消息。该插件还实现了身份/实体绑定、场景加载、动画调度、碰撞探针、遥测HUD以及PBR/光照辅助功能，同时配备能力矩阵和原生冒烟测试。生成后的游戏逻辑包含具体的移动、战斗、摄像机、游戏专属UI、载具、计分及规则模块。自定义插件必须在`plugin.cfg`中声明Godot要求的`name`、`author`、`version`、`description`和`script`字段，且需指定一个安全的、位于源码目录内的脚本路径。在复制或启用插件前，配置好的Godot可执行程序会解析该描述文件，并在独立项目中加载入口脚本，以验证其是否为可实例化的、带有`@tool`标记的`EditorPlugin`。若入口脚本缺失、路径错误或无法被识别，则`addons/`目录和`project.godot`文件均不会发生变化。

运行时若无指定World，则会使用`world_001`。`reset_world()`仅清除指定的World（默认为`world_001`）在Python端及原生会话状态中的记录，其他World的数据将被保留。重新加入已有参与者的会话时，会复用其持久化实体，替换其原生控制器绑定，并触发`session_reconnected(previous_session, session)`事件，而不会生成人为的`session_left`/`session_joined`配对事件；同时旧的Python控制器会因审计需求而处于离线状态。`session_joined`事件仅在场景树中不存在对应实体ID时才用于请求创建实体；游戏逻辑可通过`A3GameRuntime.find_entity(entity_id)`获取已保存的节点。`session_left`事件仅用于解除控制权限，绝不能被视为实体销毁。`snapshot().payload.active_count`因此会分别统计活跃绑定数量与总审计记录数量。`clear_entity()`会删除匹配实体的所有控制器记录；若指定`destroy_actor=False`，则保留对应的Godot节点，默认设置为`True`时会调用该节点的`clear_a3game_entity()`钩子。原生确认信息会反馈已移除的会话数量以及已匹配/待销毁的节点数量。参与者调用`leave()`时会终止当前活动的控制器并使其失效；此后该参与者的输入指令及心跳信号都将无效，直至其重新加入会话。若未收到UDP响应，除非设置了`require_runtime=True`，否则操作可能会使用文档中说明的本地备用方案，并弹出警告提示。一旦收到响应，若为NACK或协议格式错误/不匹配，则该响应不会被注册、激活、移除或用于更新本地会话状态。`examples/`目录下提供了六个完整的、经过引擎验证的游戏示例：
2D街机生存游戏、3D跟随镜头赛车游戏、2D刚体弹珠台游戏、第一人称射击游戏、第二人称竞技场格斗游戏，以及第三人称RPG探索游戏。每个示例都是独立项目，具备交互式输入功能、无需人工操作的演示驱动程序、用户界面与状态管理模块、有意义的碰撞与物理效果，还有原生的动态烟雾脚本。其中RPG示例还导入了真实的骨骼动画glTF模型，验证了骨骼动画的正常运作，从而覆盖了程序化网格无法实现的3D资产与动作边界问题。

如需查看命令行接口的使用方法，可运行`python -m engine_adapters.godot --help`；仅经过验证的引擎安装包才存放在`scripts/engine_install/godot/`目录下。项目的创建、任务标识资产导入、测试、构建及启动等操作均通过适配器命令行接口完成，因此开发者只需使用这一套生命周期管理接口，无需为不同命令编写单独的Shell或批处理脚本。
