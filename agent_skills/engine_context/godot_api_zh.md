# Godot Agent API参考

状态：已为Godot 4.x实现`GodotClient` API版本`v1`。

这是AI智能体的可执行能力索引。它首先涵盖引擎安装内容，随后列出所有受支持的公共主机调用。唯一支持的Python入口点为：

```python
from engine_adapters.godot import GodotClient
```

请勿导入`engine_adapters.godot._internal`，不要直接调用适配器所属的GDScript，不要编辑`.a3game`状态，不要构造生成输出路径，也不要让生成的游戏在运行时依赖`engine_adapters/godot/examples/`。

> 由游戏玩法触发的音频、视频CG、动画CG和VFX相关内容会在下方的**媒体导演**章节中说明。如果任务涉及运行时媒体，请结合该章节与公共Python API使用。

## 1. 开展项目工作前，先发现、安装并验证Godot

智能体在创建项目、导入资源或启动游戏之前，必须先确定已验证可用的Godot可执行文件。

Linux/macOS系统：

```bash
scripts/engine_install/godot/install.sh --dry-run --json
scripts/engine_install/godot/install.sh --version 4.5.1 --json
```

Windows系统：

```bat
scripts\engine_install\godot\install.cmd --dry-run --json
scripts\engine_install\godot\install.cmd --version 4.5.1 --json
```

执行结果需满足退出码为零、`ok=true`且`verified_version`完全匹配的要求。默认版本锁定为`4.5.1-stable`；刻意拒绝使用`latest`版本。安装程序的功能如下：
- 依次探测`--executable`、`A3GAME_GODOT_EXECUTABLE`，以及PATH中的`godot4`/`godot`/`godot-mono`，仅复用指定版本的二进制文件；
- 选择Linux x86-64/x86-32/arm64/arm32、通用macOS或Windows x64/x86/arm64官方资产；
- 仅通过HTTPS下载GitHub上的官方Godot发行版，要求官方`SHA512-SUMS.txt`中存在对应的精确资产条目，若不匹配则安装失败；
- 拒绝不安全的归档遍历、链接、重复路径及特殊节点；
- 先将文件解压到同级暂存目录，探测暂存目录中的二进制文件，确认无误后才通过重命名发布，若替换失败还会恢复原先的目标文件；
- 写入版本/平台清单、`godot4`的PATH占位符、机器可读的JSON，以及无需编辑配置文件即可加载的`.env`或`.cmd`配置；
- 具备幂等性（`action=reused-managed`）：新的精确`--version`会安装在旧版本旁边，而`--force`参数仅替换已解析的目标文件。

安装程序和适配器使用Python 3.14+标准库，无需pip包或引擎SDK包。兼容性由Python 3.14上的完整Godot适配器套件保障。平台详情、参数及故障处理逻辑详见`scripts/engine_install/godot/README.md`。

请配置返回的路径，并通过公共客户端进行验证：```bash
export A3GAME_GODOT_EXECUTABLE=/绝对路径/to/godot4
export A3GAME_GODOT_PROJECT=/projects/MyGame
python3 -m engine_adapters.godot \
  --project "$A3GAME_GODOT_PROJECT" create-project --name MyGame
python3 -m engine_adapters.godot \
  --project "$A3GAME_GODOT_PROJECT" validate-project
```

请勿在 `scripts/engine_install/godot/` 目录下查找项目、导入或启动相关的封装脚本：该目录仅用于存放安装文件。请使用这一套统一的适配器命令行工具：

```bash
python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" \
  import-asset --source-json generated-asset.json --asset-type avatar
python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" launch-game
```

## 2. 客户端配置与结果契约

```python
godot = GodotClient(
    project_path="/projects/MyGame",       # 目录或project.godot文件
    godot_executable="/opt/godot/godot4", # 在PATH环境变量配置完成后此项可选
    api_version="v1",
    runtime_host="127.0.0.1",
    runtime_port=30050,
    editor_timeout=300,
    import_timeout=300,
)
```

构造函数的参数优先级与状态说明：

| 设置项 | 解析规则 |
| --- | --- |
| 项目路径 | 优先采用传入参数 → 再参考 `settings.godot_project`（`A3GAME_GODOT_PROJECT`） |
| 可执行文件 | 优先采用传入参数 → 再参考 `settings.godot_executable`（`A3GAME_GODOT_EXECUTABLE`）→ 最后通过PATH环境变量查找 |
| 运行时环境 | 优先采用 `A3GAME_GODOT_RUNTIME_HOST` / `A3GAME_GODOT_RUNTIME_PORT` 参数 → 默认值为 `127.0.0.1:30050` |
| 超时时间 | 优先采用 `A3GAME_GODOT_EDITOR_TIMEOUT` / `A3GAME_GODOT_IMPORT_TIMEOUT` 参数 → 默认值为300秒 |
| 私有状态存储路径 | `A3GAME_GODOT_DATA_ROOT` → `<项目目录>/.a3game` |
| 工件注册表路径 | `A3GAME_GODOT_ARTIFACT_REGISTRY` → `<数据根目录>/artifacts.json` |
| 世界注册表根路径 | `A3GAME_GODOT_WORLD_REGISTRY_ROOT` → `<数据根目录>/worlds` |

所有被管理的路径组件必须是普通目录，其下的文件也必须是常规文件。符号链接、特殊节点、路径逃逸、格式错误的严格JSON、`NaN`以及无穷大值都会导致操作失败。

除了 `api_version` 和 `runtime.sessions.probe` 之外，所有公开操作都会返回一个严格遵循JSON格式的字典，其中包含以下顶层字段：

| 字段名 | 含义 |
| --- | --- |
| `ok` | 布尔值，表示操作是否成功；切勿仅根据进程退出码判断操作是否成功 |
| `operation` | 稳定的操作名称 |
| `artifacts` | 生成/选定的工件记录 |
| `diagnostics` | 结构化的引擎诊断信息 |
| `warnings` | 非致命性限制提示，包括已文档说明的本地运行时回退情况 |
| `errors` | 致命错误信息；操作失败时该字段非空 |
| `payload` | 特定操作对应的返回值，具体说明见下文 |

`runtime.sessions.probe(timeout)` 用于检测UDP可达性，属于底层操作，它会返回 `ok`、`reachable`、响应/错误详情以及请求匹配证据。

## 3. 完整的公开调用索引

下述签名对 `v1` 版本具有权威性。`E0`–`E8` 对应第4节中的可运行示例。

### 根目录与项目相关操作| 调用 | 用途及成功返回结果 | 失败表现 | 示例 |
| --- | --- | --- | --- |
| `godot.api_version -> str` | 返回字面量 `v1` | 构造函数会拒绝不支持的API版本 | E0 |
| `godot.get_environment_info(*, probe_version=True)` | 返回项目/可执行文件路径、路径是否存在、引擎版本支持情况、运行时端点及注册表路径 | 若可执行文件缺失/版本错误，或路径不安全，会在结果中体现 | E0 |
| `godot.project.get_info(*, probe_version=True)` | 返回项目标记、主场景、可执行文件信息，以及可选的`--version`参数相关信息 | 探测错误会以结构化形式呈现；不会修改项目状态 | E0 |
| `godot.project.create(project_path=None, *, project_name="", renderer="gl_compatibility", overwrite=False, dry_run=False)` | 创建一个最小的Godot 4版`project.godot`文件、主场景及导入根目录；生成的文件路径会写入产物列表 | 若渲染器不受支持、存在关联/特殊目标、未设置`overwrite`却已有相关管理文件、布局不完整/不安全，则创建会失败 | E1 |
| `godot.project.validate(*, check_engine=True)` | 验证项目标记及主场景；若开启引擎检查，Godot会加载并实例化解析后的`PackedScene` | 若场景缺失/无法加载/UID无效、可执行文件非Godot 4版本、导入/加载诊断出错或路径不安全，则验证失败 | E1 |

### 资产

`source`是一个映射，包含`{game_id, run_id, task_kind, task_id, artifact_key}`字段。每个标识都是仓库`OUTPUT_ROOT`下的一个安全路径组成部分；调用方无法指定任意生成的输出路径。`options`是转发给导入处理模块的严格JSON格式元数据；常见的选项包括`replace_existing`以及导入提示。| 调用函数 | 功能及成功返回值 | 失败时的表现 | 示例 |
| --- | --- | --- | --- |
| `godot.assets.import_asset(source, asset_type, *, destination="", options=None)` | 解析、暂存、导入指定类型的资产，对其进行原生层面的检测并注册；最终生成的产物包含真实的 `res://` 路径、类信息及功能属性。 | 若资产类型/标识无法识别、源路径存在逃逸风险、格式不匹配、存在冲突、导入/加载出错，或不符合原生合约要求，则会回滚已生成的文件、缓存及注册信息。 | E2 |
| `godot.assets.import_batch(sources, *, options=None, timeout=None, dry_run=False)` | 预先校验资产描述信息，按任务ID命名资产，先导入虚拟形象/网格数据，再处理动作与场景数据；返回每个资产的导入结果以及所有已注册的资产信息。 | 描述信息无效的资产会在导入前直接判定为失败；一旦某个资产导入失败，后续处理会立即停止，同时会报告此前已成功导入的资产情况。 | E2 |
| `godot.assets.import_avatar(source, **kwargs)` | 针对虚拟形象的专用导入函数；支持指定 `destination` 和 `options` 参数；返回已注册的带骨骼蒙皮的 `PackedScene` 对象。 | 导入时需提供对应的网格数据、Skeleton3D 骨骼信息，以及与骨骼绑定的带蒙皮的网格模型。 | E2 |
| `godot.assets.import_motion(source, *, skeleton="", destination="", avatar_name="", options=None)` | 针对动作数据的专用导入函数；`skeleton` 参数可接受实时的 Skeleton3D NodePath，也可接受已注册的虚拟形象资产/资源引用。 | 导入的动作数据需包含 `PackedScene`、动画数据，且动画轨迹需能与指定的骨骼结构匹配。 | E3 |
| `godot.assets.import_scene(source, **kwargs)` | 针对可实例化场景的专用导入函数；支持指定 `destination`/`options` 参数。 | 对应的原生资源必须能够成功加载并实例化为 `PackedScene` 对象。 | E2 |
| `godot.assets.import_prop(source, **kwargs)` | 针对道具模型的专用导入函数；支持指定 `destination`/`options` 参数。 | 导入的模型需能实例化为包含 `MeshInstance3D` 组件的 `PackedScene`；纯 OBJ 格式模型无法被导入。 | E2 |
| `godot.assets.import_weapon(source, **kwargs)` | 针对武器的专用导入函数；支持指定 `destination`/`options` 参数。 | 武器的网格模型需满足与道具相同的可实例化要求。 | E2 |
| `godot.assets.import_material(source, **kwargs)` | 针对Godot材质/图像的专用导入函数；支持指定 `destination`/`options` 参数。 | 若材质类别不匹配、解码/导入出错，或目标环境不兼容，则导入会失败。 | E2 |
| `godot.assets.import_texture(source, **kwargs)` | 针对 `Texture2D` 类型的专用导入函数；支持指定 `destination`/`options` 参数。 | 若图像文件损坏/不被支持、对应的导入资源缺失，或类类型不匹配，则导入会失败。 | E2 |
| `godot.assets.import_effect(source, **kwargs)` | 针对特效资源的专用导入函数；支持指定 `destination`/`options` 参数。 | 若源数据、目标类型或原生加载合约不匹配，则导入会失败。 | E2 |
| `godot.assets.import_audio(source, **kwargs)` | 针对 `AudioStream` 类型的专用导入函数；支持指定 `destination`/`options` 参数。 | 若音频解码/加载出错，或类类型不匹配，则导入会失败。 | E2 |
| `godot.assets.validate(source, asset_type, *, destination="", options=None)` | 无需复制数据即可预先校验资产的标识、格式、目标路径及是否存在冲突。 | 该函数会返回结构化的路径/类型/源数据错误信息，且不会对本地文件或注册信息进行任何修改。 | E2 || `godot.assets.resolve_source(source, *, asset_type="")` | 解析可信的任务元数据/工件路径并返回源详情 | 若元数据/密钥/文件缺失、身份不匹配、链接错误或试图跳出OUTPUT_ROOT，则操作失败 | E2 |
| `godot.assets.list(asset_type="", *, root="assets/imported")` | 列出指定根目录下项目内已导入的资源 | 若遍历过程出错、根路径为外部路径、存在链接/特殊条目或项目无法读取，则操作失败 | E2 |
| `godot.assets.list_registered(asset_type="")` | 返回注册表中的工件及过滤后的数量 | 若注册表格式错误、存在链接/特殊条目或非严格模式下的注册表有问题，且无法找到替代项，则操作失败 | E2 |
| `godot.assets.get_metadata(artifact_id)` | 返回一个已注册的工件及其元数据 | 若ID未知或注册表无效，则操作失败 | E2 |
| `godot.assets.register_resource(*, resource_path, asset_type, asset_id, source_path="", backend_class="", spawnable=None, metadata=None)` | 原生加载项目中已有的规范资源`res://`，推导其类别/可生成性并进行注册；可选的声明可作为断言条件 | 若遍历/链接过程出错、资源缺失，或类型/类别/可生成性不符，又或是加载/实例化失败，或注册表更新存在歧义，则操作失败且不会写入数据 | E2 |

支持的资产类型包括`avatar`（角色）、`motion`（动作）、`scene`（场景）、`environment`（环境）、`effect`（特效）、`material`（材质）、`texture`（纹理）、`prop`（道具）、`static_mesh`（静态网格）、`weapon`（武器）和`audio`（音频）。glTF主文件以及本地缓冲区/图像属于同一事务。若原生验证失败，系统会恢复被替换的源文件、相邻的`.import`文件、匹配的`.godot/imported`缓存文件以及之前的注册表。

### 动画与材质绑定

| 调用 | 用途及成功返回值 | 失败时的行为 | 示例 |
| --- | --- | --- | --- |
| `godot.animation.import_motion(source, *, skeleton, destination="", avatar_name="", options=None)` | 针对实时的Skeleton3D NodePath或已注册的角色引用导入动作 | 若骨架为空/缺失、角色未知、动画/骨骼轨迹不存在或目标不匹配，则操作失败并回滚 | E3 |
| `godot.animation.resolve_skeleton(avatar)` | 重新加载已注册的角色并返回实时的Skeleton3D路径/骨骼信息 | 若角色未知、非角色类型、无法加载或未绑定蒙皮的资源，则操作失败 | E3 |
| `godot.animation.validate_compatibility(motion, skeleton)` | 重新加载动作并验证其动画及骨骼轨迹是否能匹配实时骨架或已注册的角色引用 | 若结构不匹配则操作失败；该操作不保证视觉上的重定向效果 | E3 |
| `godot.bindings.bind_pbr_material(*, asset_id, source, mesh_assets, destination="assets/imported/materials", options=None)` | 导入/创建材质，通过Godot将`material_override`应用到每个目标网格上，保存绑定的场景，原子性地更新记录并返回清单/工件 | 若目标/材质缺失、无网格被更改、引擎出错、状态不安全、目标重复，或任何提交步骤失败，系统会恢复材质/场景/纹理/清单/注册表 | E3 |

### 世界| 调用方法 | 用途及成功返回结果 | 失败表现 | 示例 |
| --- | --- | --- | --- |
| `godot.world.build(source, *, options=None)` | 导入场景后，根据选项创建、验证并可选发布一个World | 任何资产/草稿/原生验证失败的情况都会被返回；不会生成虚构的包 | E4 |
| `godot.world.create_draft(spec, *, draft_id="", project_id="", metadata=None)` | 写入一个指向已注册就绪场景的带版本号的草稿；显式指定的ID会覆盖规范中的设定，显式指定的元数据会与规范中的元数据合并 | 若架构/JSON错误、注册表不安全、场景缺失/无法实例化/非`PackedScene`类型，或原生加载失败，则无法生成有效的草稿 | E4 |
| `godot.world.validate_draft(draft_id)` | 重新验证记录/文件的身份、生命周期以及当前注册的/原生场景的有效性 | 未知的/损坏的/版本不匹配的/过期的草稿会导致验证失败 | E4 |
| `godot.world.publish_draft(draft_id)` | 原子化地发布经过验证的包并返回包产物 | 只有经过验证的草稿才能被发布；链接路径/特殊路径、冲突或过期的场景会导致发布失败 | E4 |
| `godot.world.list_packages(*, project_id="", world_id="")` | 返回按上述任一/两个ID筛选出的合规包列表 | 若某条记录损坏则读取操作会失败；记录绝不会被静默跳过或合成 | E4 |

### 插件

| 调用方法 | 用途及成功返回结果 | 失败表现 | 示例 |
| --- | --- | --- | --- |
| `godot.plugin.install(source, *, install_dir="", replace_existing=False, enable=True, dry_run=False)` | 安装已注册的生成型插件，原生验证`plugin.cfg`及入口文件的有效性，可选启用插件并返回复制的文件 | 若源路径包含跳转/链接/特殊节点、名称/脚本不安全、元数据缺失、非`@tool EditorPlugin`类型、目标路径已存在或设置存在歧义，则安装操作会原子化失败 | E5 |
| `godot.plugin.install_framework(*, replace_existing=False, enable=True, dry_run=False)` | 安装适配器自有的`A3GamePlayable` v1.1.0版本，启用该插件及`A3GameRuntime`自动加载功能；负载列表中包含复制的实现/测试文件 | 遵循相同的原子验证、目标路径及设置规则；若存在冲突的自动加载项，则需要显式替换才能安装 | E5 |
| `godot.plugin.list()` | 列出已安全安装的插件描述符；框架类插件会有独立的产物类型 | 无法读取/为链接状态的条目会被跳过并给出警告；不安全的项目根目录会导致操作失败 | E5 |

该框架的机器可读能力矩阵及原生冒烟测试文件位于
`engine_adapters/godot/plugin/A3GamePlayable/`目录下。它实现了身份识别、
规范化输入、会话/实体绑定、场景加载、动画调度、射线/球体碰撞探测、
HUD遥测以及材质/光照辅助功能。原生的Godot角色/刚体物理、特效/音频及游戏规则仍由游戏逻辑层自行管理。

### 构建与测试| 调用 | 用途及成功返回结果 | 失败行为 | 示例 |
| --- | --- | --- | --- |
| `godot.build.project(*, preset, output_path, debug=False, pack_only=False, extra_args=(), allow_external_output=False, timeout=None, dry_run=False)` | 执行名为 `--export-release`、`--export-debug` 或 `--export-pack` 的导出命令；返回完整的已提交兄弟文件集及所有权凭证 | 预设/输出路径缺失、超时、引擎诊断出错、受保护/外部/未受管理/被篡改的输出文件、清单/证明文件有误，或嵌套链接出错，同时会保留之前的构建结果 | E6 |
| `godot.testing.run_automation_tests(test_filter="", *, script="", test_root="res://tests", report_path="", timeout=None, dry_run=False)` | 运行适配器/默认测试套件或指定的SceneTree运行器；返回匹配/通过/失败/跳过测试用例的数量及验证通过的用例信息 | 运行器/报告路径/根目录不合法、超时、报告过期/缺失/不符合严格格式要求、模式/状态无效，或任何测试用例失败都会导致操作终止 | E6 |

所选根目录下名为 `test_*.gd` 的本地测试文件必须继承自可实例化的Godot类型，且需从 `run_test()` 方法返回布尔值或包含布尔型字段 `ok` 的字典。对于超出契约规定的返回值，绝不会依据其“真值”来判断。只有经过模式验证后，报告才会从私有的临时暂存路径发布。

### 运行时与会话| 调用函数 | 功能及成功返回值 | 失败表现 | 示例 |
| --- | --- | --- | --- |
| `godot.runtime.launch_editor(*, scene_path="", extra_args=(), dry_run=False)` | 在独立的进程组中启动已配置的编辑器；返回被管理的进程ID | 若项目/可执行文件缺失、场景不合法或启动出错，则操作失败 | E7 |
| `godot.runtime.stop_editor(process_id)` | 仅停止由当前客户端启动的编辑器 | 若进程ID未知/错误，或正常终止操作失败，则返回错误信息 | E7 |
| `godot.runtime.launch_game(*, scene_path="", headless=False, extra_args=(), dry_run=False)` | 启动项目/主程序或指定场景；返回被管理的进程ID | 遵循与编辑器相同的所有权、路径及启动校验规则 | E7 |
| `godot.runtime.stop_game(process_id)` | 仅停止被管理的游戏进程组 | 若PID未知/错误，或停止操作失败，则返回错误信息 | E7 |
| `godot.runtime.launch_player(build_path, *, extra_args=(), dry_run=False)` | 启动常规导出的可执行文件/程序，并返回被管理的进程ID | 若构建文件为链接类型/特殊类型/缺失/非可执行，或启动出错，则操作失败 | E7 |
| `godot.runtime.stop_player(process_id)` | 仅停止被管理的导出版播放器 | 若PID未知/错误，或停止操作失败，则返回错误信息 | E7 |
| `godot.runtime.sessions.join(*, world_id="", participant_id="", user_id="", avatar_artifact_id="", idle_motion_artifact_id="", move_motion_artifact_id="", controller_kind="human", transform=None, parameters=None, require_runtime=False)` | 解析可选资源，创建/重新连接控制器与实体，返回会话信息及桥接凭证 | 若映射/JSON/资源/类型不合法、参与者已绑定其他实体、出现可识别的NACK/协议错误，或所需的运行时环境无法访问，则操作失败且不会进行本地注册 | E7 |
| `godot.runtime.sessions.leave(*, participant_id="", controller_id="")` | 解除当前绑定关系，返回会话及桥接记录 | 若会话不存在，或出现可识别的NACK，则操作失败且不会误解除绑定 | E7 |
| `godot.runtime.sessions.heartbeat(controller_id)` | 更新并返回活跃的本地会话信息 | 若控制器未知、处于非活跃状态或离线，则操作失败 | E7 |
| `godot.runtime.sessions.apply_input(controller_id, *, move_x=0.0, move_y=0.0, run=False, jump=False, yaw=0.0, pitch=0.0, seq=0, require_runtime=False)` | 发送经过归一化处理的有限输入数据，仅在桥接响应正常时才会记录该输入 | 若输入值非有限数、控制器未知/非活跃、出现可识别的NACK/响应格式错误/不匹配，或所需的桥接环境无法访问，则操作失败且不会修改状态 | E7 |
| `godot.runtime.sessions.snapshot(*, world_id="")` | 返回防御性的会话列表、会话总数及活跃会话数，可选返回某个World的相关信息 | 若World转换/注册表状态异常，则操作失败 | E7 |
| `godot.runtime.sessions.reset_world(*, world_id="")` | 仅在本地/原生层面移除已解析的World（默认值为`world_001`）；该操作具备幂等性，会返回相关计数结果 | 若原生层面拒绝操作，则不会执行本地移除操作 | E7 || `godot.runtime.sessions.clear_entity(*, participant_id="", controller_id="", entity_id="", destroy_actor=True)` | 清除已解析实体的所有绑定；原生结果会区分匹配到的节点和已加入销毁队列的节点 | 非布尔类型的标识；若实体不存在或无法访问，则不会执行移除操作，且操作会失败 | E7 |
| `godot.runtime.sessions.probe(timeout=0.25)` | 返回原始的UDP状态、可达性以及协议相关信息，并非七字段的结果封装 | 返回的记录中会明确标注超时、不可达、格式错误或不匹配的响应情况 | E7 |

当设置`require_runtime=False`时，若没有UDP响应，则会进入文档中说明的仅限本地使用的状态，并触发警告。一旦收到任何响应，无论是NACK还是格式错误/不匹配的协议数据，都会导致操作失败，且无法修改本地状态。重新连接时会保留实体ID，替换旧的控制器，并触发`session_reconnected`事件；`session_left`表示控制权被释放，而非实体被销毁。

### 反射与观测

| 调用 | 用途及成功返回值 | 失败时的行为 | 示例 |
| --- | --- | --- | --- |
| `godot.reflection.inspect_artifact(artifact_id, *, live=True, timeout=60.0)` | 返回注册表元数据；实时模式下会向Godot请求资源类、PackedScene节点、骨骼、皮肤、动画/轨迹以及加载相关信息 | 若工件未知、注册表有误、发生超时，或资源无法加载/已损坏/类型不匹配，又或是原生报告格式错误，则操作会失败 | E8 |
| `godot.observe.check_status(*, timeout=5.0, check_runtime=False)` | 报告项目/可执行文件/版本信息，以及可选的UDP运行时就绪状态 | 环境无效或请求的运行时无法使用的情况会被明确告知；操作不会修改任何状态 | E8 |

## Godot媒体导演：音频、视频CG、动画CG及视觉特效

对于由游戏玩法触发的媒体内容，可使用引擎原生的`A3GameMediaDirector`组件。跨引擎的逻辑组件名称为`media_director`，但Godot端的代码遵循GDScript规范：

```text
media_director.gd
class_name A3GameMediaDirector
```

机制模块负责决定游戏玩法事件发生的时机，并提供稳定的snake_case格式的事件键，例如`hit_confirmed`或`ultimate_cg`。媒体导演则负责管理Godot播放对象和媒体相关数据。它不应负责伤害规则、攻击时序、UI布局、管线编排、浏览器播放传输或基准测试计分等逻辑。

### 公开操作| 操作 | 用途 | 原生绑定 |
|---|---|---|
| `register_audio(event_key, stream, volume_db=0.0, pitch_scale=1.0)` | 注册Godot的`AudioStream`并创建`AudioStreamPlayer` | `AudioStreamPlayer.play()` |
| `trigger_audio(event_key, trigger_source="gameplay", metadata={})` | 播放已注册的音频事件并返回证据记录 | `AudioStreamPlayer` |
| `register_cg(event_key, stream, loop=false)` | 注册`VideoStream`并创建一个隐藏的`VideoStreamPlayer` | `VideoStreamPlayer` |
| `trigger_cg(event_key, trigger_source="gameplay", metadata={})` | 显示并播放视频CG；触发后获取游戏暂停锁 | `VideoStreamPlayer.play()` |
| `stop_cg(event_key)` | 停止并隐藏CG，同时释放游戏暂停锁 | `VideoStreamPlayer.stop()` |
| `register_animation(event_key, player, animation_name)` | 绑定现有的`AnimationPlayer`动画 | `AnimationPlayer.play()` |
| `trigger_animation(event_key, trigger_source="gameplay", metadata={})` | 播放已注册的动画CG | `AnimationPlayer` |
| `register_vfx(event_key, effect_node)` | 绑定支持原生`restart()`或`play()`方法的节点 | VFX节点方法 |
| `trigger_vfx(event_key, trigger_source="gameplay", metadata={})` | 重启或播放已注册的VFX节点 | 优先调用`restart()`，其次调用`play()` |
| `stop_vfx(event_key)` | 若该VFX节点支持`stop()`方法，则停止该节点 | VFX节点方法 |
| `get_event_log()` | 返回媒体运行时记录的防御性副本 | 内存中的证据 |

注册过程会验证事件键以及原生资源/节点类型。若绑定缺失或无效，触发操作会返回`playback_call_issued=false`；切勿将成功的注册或方法返回值视为运行中游戏中媒体可见或可听的凭证。

### 暂停与完成约定

当具有中断性的CG获取或释放仅用于战斗的暂停锁时，会发出`gameplay_pause_changed(paused: bool)`信号。`gameplay_paused`则用于反映当前的锁状态。

- 一旦`trigger_cg`被接受，导演模块就会发出`gameplay_pause_changed(true)`信号。
- 游戏自有的机制代码在持有该锁期间必须禁用战斗动作与伤害计算。它不应仅仅为了暂停战斗就设置`Time.time_scale = 0`，因为视频和音频必须继续播放。
- 导演模块会在视频正常播放完毕、`stop_cg`被调用，或游戏执行显式的错误/回退清理流程时释放该锁，随后发出`gameplay_pause_changed(false)`信号。
- 导演模块无法推断正确的命中窗口、投射物发射时机或动画过渡节点；这些均由游戏自身控制，需通过原生游戏测试来验证。

### 运行时证据

每条触发记录均采用`schema gamefactory3a.media_runtime_event.v1`，且至少包含以下内容：```json
{
  "schema_version": "gamefactory3a.media_runtime_event.v1",
  "seq": 1,
  "t_monotonic_ms": 1234,
  "event_type": "音频触发|CG触发|CG动画触发|特效触发",
  "event_key": "终极技能CG",
  "trigger_source": "游戏玩法",
  "playback_call_issued": true,
  "metadata": {}
}
```

该记录明确了所请求的事件、触发源、原生播放调用、单调运行时排序以及调用方元数据。请保留事件日志与原生试玩追踪信息；若要确认视觉/音频效果是否正常，仍需观察正在运行的Godot项目。

## 试玩录制

- `godot.playtest.record(...)` 会在游戏进程内录制内容：客户端会将场景文件（`_scenario.json`）和录制脚本写入录制目录，确保存在录制场景（`scenes/main_record.tscn`，若缺失则会根据`main.tscn`生成），随后以`--a3-record`、`--a3-record-fps`和`--a3-record-duration`参数启动游戏。游戏内的录制器会驱动游戏进程，按照指定频率通过`get_viewport().get_texture().get_image()`捕获视口帧，录制结束后自动退出游戏。相关参数包括：`output_dir`、`scenario`或`action_plan`、`duration`、`fps`、`width`、`height`、`timeout`、`headless`、`ffmpeg`和`dry_run`。
- 若要捕获画面，`headless`参数必须设为`false`：无头模式的Godot没有渲染服务器。视口尺寸通过`--resolution`参数由`width`/`height`指定。
- 支持的动作名称包括`move`、`look`、`jump`、`attack`、`interact`、`dash`、`pause`、`restart`和`wait`。每个动作都对应一个正整数`duration_ms`；场景规划不能为空且需包含在`duration`时间范围内。输入指令会在引擎内部处理（`Input.parse_input_event()`或自主AI驱动程序），因此无需在主机端注入输入指令。
- 输出布局与其他适配器一致：当FFmpeg可用时，会生成`frames/`、`actions.jsonl`、`report.json`和`video.mp4`文件。报告的结构为`gamefactory3a.godot.playtest_report.v1`。
- 即使缺少FFmpeg也不会导致致命错误：即便没有视频文件，帧数据、动作轨迹和报告仍会被保留。

## 4. 可执行的调用模式

### E0 — 环境检查

```python
godot = GodotClient(project_path="/projects/MyGame")
assert godot.api_version == "v1"
environment = godot.get_environment_info(probe_version=True)
assert environment["ok"], environment["errors"]
```

### E1 — 创建并验证项目

```python
created = godot.project.create(project_name="MyGame", renderer="gl_compatibility")
assert created["ok"], created["errors"]
validated = godot.project.validate(check_engine=True)
assert validated["ok"], validated["errors"]
```

### E2 — 解析、验证、导入、查询或注册资源```python
source = {
    "game_id": "game101",
    "run_id": "run_001",
    "task_kind": "3D物体",
    "task_id": "crate",
    "artifact_key": "glb_path",
}
assert godot.assets.resolve_source(source, asset_type="prop")["ok"]
assert godot.assets.validate(source, "prop")["ok"]
imported = godot.assets.import_prop(source, destination="assets/imported/props")
assert imported["ok"], imported["errors"]
artifact_id = imported["artifacts"][0]["artifact_id"]
assert godot.assets.get_metadata(artifact_id)["ok"]
assert godot.assets.list_registered("prop")["ok"]

existing = godot.assets.register_resource(
    resource_path="res://scenes/arena.tscn",
    asset_type="场景",
    asset_id="arena",
    backend_class="PackedScene",  # 断言：切勿轻信此类推断
    spawnable=True,
)
assert existing["ok"], existing["errors"]
```

### E3 — 动作与材质绑定

```python
motion = godot.animation.import_motion(
    source,
    skeleton="Character/Skeleton3D",
    avatar_name="hero",
)
assert motion["ok"], motion["errors"]
assert godot.animation.resolve_skeleton("hero_avatar")["ok"]
assert godot.animation.validate_compatibility(
    motion["artifacts"][0]["artifact_id"], "Character/Skeleton3D"
)["ok"]

bound = godot.bindings.bind_pbr_material(
    asset_id="hero_material",
    source=source,
    mesh_assets=["hero_avatar"],
)
assert bound["ok"], bound["errors"]
```

### E4 — 世界生命周期

```python
draft = godot.world.create_draft({
    "draft_id": "arena_draft",
    "world_id": "arena",
    "scene_artifact_id": "arena",
})
assert draft["ok"], draft["errors"]
assert godot.world.validate_draft("arena_draft")["ok"]
assert godot.world.publish_draft("arena_draft")["ok"]
packages = godot.world.list_packages(world_id="arena")
assert packages["ok"], packages["errors"]
```

### E5 — 框架与生成的插件

```python
framework = godot.plugin.install_framework()
assert framework["ok"], framework["errors"]

generated_addon = godot.plugin.install({
    "game_id": "game101",
    "run_id": "run_001",
    "task_kind": "机制",
    "task_id": "gameplay_addon",
})
assert generated_addon["ok"], generated_addon["errors"]
assert godot.plugin.list()["ok"]
```

### E6 — 原生测试与导出

```python
tests = godot.testing.run_automation_tests(
    test_root="res://tests",
    report_path="reports/godot-tests.json",
)
assert tests["ok"], tests["errors"]

build = godot.build.project(
    preset="Linux/X11",
    output_path="builds/game.x86_64",
)
assert build["ok"], build["errors"]
```

### E7 — 运行时生命周期与控制

```python
launched = godot.runtime.launch_game(headless=False)
assert launched["ok"], launched["errors"]
``````python
joined = godot.runtime.sessions.join(
    world_id="arena",
    participant_id="player_1",
    avatar_artifact_id="hero_avatar",
)
assert joined["ok"], joined["errors"]
controller = joined["payload"]["controller_id"]
assert godot.runtime.sessions.apply_input(
    controller, move_y=1.0, run=True, yaw=0.2, seq=1
)["ok"]
assert godot.runtime.sessions.heartbeat(controller)["ok"]
assert godot.runtime.sessions.snapshot(world_id="arena")["ok"]
assert godot.runtime.sessions.leave(controller_id=controller)["ok"]
assert godot.runtime.stop_game(launched["payload"]["process_id"])["ok"]
```

### E8 — 检查与观测

```python
inspection = godot.reflection.inspect_artifact("hero_avatar", live=True)
assert inspection["ok"], inspection["errors"]
status = godot.observe.check_status(check_runtime=True)
assert status["ok"], status["errors"]
```

## 5. 原生生命周期细节

### 导入

导入操作只会复制 `res://assets/imported/` 目录下经过验证的任务资源，执行命令 `godot --headless --path <project> --import`。非Godot 4格式的二进制文件会被拒绝，任何非零退出码、已知的损坏/解析/依赖镜像错误（即使退出码为零）也会被判定为导入失败，随后才能用Godot加载结果。可实例化的网格类型必须作为包含 `MeshInstance3D` 的 `PackedScene` 来实例化；角色模型还需要真实的骨骼和绑定的蒙皮。纯OBJ格式的文件会被加载为 `ArrayMesh`，因此需使用GLB/glTF格式，或将其封装在场景中。

### 构建与报告

导出文件和测试报告会先被私下暂存、验证，再原子化发布。构建过程会记录签名的所有者清单以及完整同组文件的哈希值；相关密钥会保存在私有的适配器状态中。后续构建仅能替换未更改的已认证成员。项目输入、状态键、被修改或不受管理的输出、编辑后的清单、链接以及特殊节点一旦出现异常，系统会直接终止流程。

### 示例与演示项目

`engine_adapters/godot/examples/` 目录下包含六个完整的原生项目：

- `NeonDodge2D`：街机生存类游戏，涉及输入处理、UI设计、碰撞检测与状态循环；
- `SolarRally3D`：带追踪摄像头的赛车游戏，包含物理赛道、检查点、PBR材质、定向光/泛光灯，以及圈数/获胜循环；
- `OrbitPinball2D`：刚体弹珠游戏，包含静态碰撞体、动画弹射器、冲击力计算，以及连击/生命值循环；
- `FpsArena3D`：第一人称视角游戏，涵盖角色移动、摄像机控制的瞄准、射线射击、目标设定、弹药/装填状态以及准星HUD；
- `ArenaDuel3D`：第二人称视角对战游戏，采用属于比赛场景的摄像头，角色面向固定、有攻击窗口、生命值设定、回合与得分系统；
- `RpgExplorer3D`：第三人称视角探索游戏，基于摄像机相对位置移动，包含不平坦地形、任务物品拾取、耐力系统，以及原生导入的带蒙皮的glTF格式 `Walk` 动画片段。每个场景都包含一个真正的主`PackedScene`、确定性无人值守驱动程序、手动键盘模式，以及一个用于实时更新物理效果的Godot烟雾脚本。该RPG烟雾效果还证明了Godot已从glTF文件中实例化网格和骨骼，并正在播放导入的骨骼动画。其`mechanic_contract.json`文件会映射到`test_data/outputs/<game_id>/<run_id>/mechanic/<task_id>/`路径下的审阅者副本中。

## 6. 坐标系

Godot 3D采用右手坐标系，Y轴向上，`-Z`方向为前方。glTF同样采用Y轴向上的坐标系，且单位以米计。请明确记录源模型的朝向和缩放参数；切勿在Godot完成源格式导入后再进行统一的转换处理。
