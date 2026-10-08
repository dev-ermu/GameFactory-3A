# three.js开发技能与公共API参考

## 范围与导航

本指南适用于three.js项目的创建、游戏开发、资源管理、场景构建及验证。
基准版本：`ThreeClient` API `v1`，three.js r185（`three@0.185.0`，兼容r185系列版本），Node 20+，项目使用Vite/Vitest版本。
权威来源：`engine_adapters/three_js/`。除非另有说明，路径均为仓库相对路径。
第2节和第18节列出了公共API；后续章节定义了这些API的契约与限制，而非私有实现细节。

| 任务 | 对应章节 |
|---|---|
| 创建项目或安装游戏功能 | 1–2 |
| 导入资源、检查物体朝向、绑定材质 | 3 |
| 组装或发布场景 | 4 |
| 启动浏览器游戏并配置渲染 | 5–6 |
| 构建地形、道具、路径及背景 | 7 |
| 实现实体、输入处理、会话管理或远程命令 | 8–10 |
| 为角色添加动画 | 11 |
| 添加风效、水效、表面流动效果或视觉特效 | 12–13 |
| 实现碰撞检测与HUD（游戏界面） | 14–15 |
| 验证、记录并发布资源 | 16–17 |
| 查看完整的公共API接口及源码位置 | 18 |

## 1. 公共边界与项目工作流程

- Python端：`from engine_adapters.three_js import ThreeClient`；JS端：框架API使用`@a3game/playable`，原生类型使用`three`。
- 将游戏逻辑代码放入`packages/<游戏名称>/`目录下；可复用的代码应编写在规范插件中，并通过项目工具进行安装。
- 应避免使用Python的`_internal`模块、直接构造命名空间客户端代码，以及JS中的深层导入语句。将`examples/`目录仅作为只读参考资料。
- 通过已注册的任务标识来导入资源/包（详见第3节）。
- 遵循数据包权限规则：机械生成器负责编写测试，不生成权威性结果；UI生成器也需遵守截图限制，同时保留机械生成器的代码。

```text
<解析后的项目目录>/
├── package.json                 包含three.js、Vite、Vitest配置；packages/*为工作区
├── vite.config.js
├── index.html                   用于定义视口和HUD容器
├── src/main.js                  导入并启动游戏逻辑包
├── public/assets/manifest.json   由资源导入工具维护
└── packages/
    ├── a3game-playable/          已安装的框架
    └── <游戏名称>/
        ├── src/index.js         启动逻辑、工厂模式、系统组装
        ├── src/world.js         场景布局与静态碰撞检测
        ├── src/player.js        具体的实体类；名称根据游戏角色设定
        ├── src/rules.js         游戏规则与可观察状态
        └── tests/
```

相关路径：`pipeline.common.paths.task_output_dir(game_id,task_kind,task_id,run_id='default',create=True)`；
`eval_output_dir`使用相同的参数。查询时可设置`create=False`；根目录覆盖值为AAAGF_OUTPUT_ROOT。不存在`three.pipeline`命名空间。

工作流程：project.create → plugin.install_framework → 实现游戏逻辑/入口点 → project.install_dependencies → project.validate → 授权后进行构建/浏览器验证。
该脚手架不会提供具体的角色、控制器、游戏模式、武器或载具等实现。

### 客户端配置与结果```python
from engine_adapters.three_js import ThreeClient

three = ThreeClient(project_path=resolved_project_path)
info = three.get_environment_info()
if not info["ok"]:
    raise RuntimeError(info["errors"])
```

构造函数：`ThreeClient(project_path=None, three_root=None, api_version='v1', *, host=None, port=None,
runtime_host=None, runtime_port=None, package_manager=None, runtime_transport=None, node_root=None)`。
请读取`three.api_version`；要获取有效的路径和URL，应使用`get_environment_info()`，而非直接访问`three._config`。
`project_path`参数可接受项目目录或`package.json`文件。配置无效的话，在实例化过程中可能会触发`ValueError`异常。

| 设置项 | 默认值/配置方式 |
|---|---|
| API版本 | 仅支持`v1` |
| 开发环境主机/端口 | 回环主机以及来自`engine_adapters/three_js/config.py`的适配器默认端口；Python会读取环境变量`A3GAME_THREE_HOST`、`A3GAME_THREE_PORT`，同时也兼容`THREE_HOST`、`THREE_PORT` |
| 运行时端点 | 该模块中定义的独立回环主机/端口默认值；对应环境变量为`A3GAME_THREE_RUNTIME_HOST`、`A3GAME_THREE_RUNTIME_PORT` |
| 包管理器 | 默认为`npm`；支持的选项包括`npm`、`pnpm`、`yarn`；可通过环境变量`A3GAME_THREE_PACKAGE_MANAGER`配置 |
| 运行时传输配置 | 默认为`http`；Python配置中接受的选项有`http`、`websocket`；具体传输限制详见第10节说明 |
| 项目/适配器根目录 | 分别对应环境变量`A3GAME_THREE_PROJECT`、`A3GAME_THREE_ROOT` |
| Node工具链 | 对应参数`node_root` / 环境变量`A3GAME_NODE_ROOT` |
| 注册表及数据路径 | 分别对应环境变量`A3GAME_THREE_DATA_ROOT`、`A3GAME_THREE_ARTIFACT_REGISTRY`、`A3GAME_THREE_WORLD_REGISTRY_ROOT`、`A3GAME_THREE_PREVIEW_ROOT` |

Vite会单独读取环境变量`A3GAME_DEV_HOST`和`A3GAME_DEV_PORT`；Python启动时会通过显式参数`--host`/`--port`传递相应值。端口范围：1–65535；开发环境端点与运行时端点需区分开。
切勿在生成的代码或命令中硬编码主机/端口字面量：应显式传递这些参数，或从`get_environment_info()`、文档中说明的环境变量、CLI参数中获取实际值，这样即便端口被占用，也无需修改源代码即可调整。
务必将服务部署在回环地址或受保护的网络中；若使用`0.0.0.0`且设置`allowedHosts:true`，则会扩大访问权限。

返回结果格式为：`{ok, operation, artifacts, diagnostics, warnings, errors, payload}`。除了检查`ok`字段外，还需查看`payload`内容（其并非游戏运行的直接依据）。
`contracts/`目录下定义了`ThreeDiagnostic`和`ThreeOperationResult`类，它们提供了`to_dict`方法以及`success`/`failure`辅助函数，并不存在`three.contracts`命名空间。
配置相关错误或调用方引发的异常未必会被包裹处理。

## 2. 完整的Python门面操作索引

通过该门面可使用这13个命名空间以及嵌套的`runtime.sessions` API。
该索引涵盖了57种操作，包括`get_environment_info()`，但不包含构造函数和`api_version`属性。
不存在`three.scene`、`three.schema`、`three.controller`或`three.network`命名空间。
函数签名采用Python的关键词限定参数`*`；省略的`options`字典会在相应章节中详细说明。

### 项目、包、构建及服务| 操作 | 签名 / 用途 |
|---|---|
| `get_environment_info()` | 获取有效的项目/工具链/注册表/运行时信息 |
| `project.get_info()` | 获取项目信息 |
| `project.create(*, dry_run=False)` | 在配置的项目路径下创建项目 |
| `project.install_dependencies(*, timeout=None, dry_run=False)` | 使用配置的包管理器安装依赖 |
| `project.validate()` | 验证项目结构与配置是否正确 |
| `plugin.install(source, *, replace_existing=False, dry_run=False)` | 安装已注册的Gameplay Package |
| `plugin.install_framework(*, dry_run=False)` | 安装官方的`@a3game/playable`包 |
| `plugin.list()` | 列出已安装的包 |
| `build.project(*, target='build', configuration='production', clean=False, dry_run=False, timeout=None)` | 调用项目构建流程 |
| `runtime.launch_dev_server(*, script='dev', world='', extra_args=(), wait_timeout=60.0, dry_run=False)` | 启动开发服务器并等待其就绪 |
| `runtime.stop_dev_server(process_id)` | 停止由该客户端实例管理的进程 |
| `runtime.preview_bundle(*, script='preview', extra_args=(), wait_timeout=60.0, dry_run=False)` | 提供现有构建版本的服务 |
| `observe.check_status(*, timeout=5.0, check_runtime=True)` | 检查工具链、项目、依赖、开发服务器以及可选的运行时端点状态 |

- 若`package.json`文件已存在，则创建操作会被拒绝。源码目录中需要包含顶层的`package.json`文件，且需指定名称。
- `@a3game/playable`依赖项或同级依赖项会要求安装框架；安装完依赖后再执行后续操作。
- 替换操作在同步过程中无法保证旧文件会被删除；资源覆盖规则详见第3节说明。
- 预演模式下的操作仅用于检查前置条件；预览功能需要`dist/`目录存在。启动超时并不会自动终止进程。
- 设置`check_runtime=False`可跳过远程检查；就绪状态检测既不会验证WebGL支持情况，也不会因缺少框架文件而直接判定为失败。

### 资源、动画、绑定与检查| 操作 | 参数签名 |
|---|---|
| `assets.import_asset` | `(source, asset_type, *, destination='', options=None)` |
| `assets.import_avatar` | `(source, *, destination='', options=None)` |
| `assets.import_scene` | `(source, *, destination='', options=None)` |
| `assets.import_prop` | `(source, *, destination='', options=None)` |
| `assets.import_weapon` | `(source, *, destination='', options=None)` |
| `assets.import_material` | `(source, *, destination='', options=None)` |
| `assets.import_texture` | `(source, *, destination='', options=None)` |
| `assets.import_effect` | `(source, *, destination='', options=None)` |
| `assets.import_audio` | `(source, *, destination='', options=None)` |
| `assets.import_motion` | `(source, *, skeleton='', destination='', avatar_name='', options=None)` |
| `assets.validate` | `(source, asset_type, *, destination='', options=None)` |
| `assets.resolve_source` | `(source, *, asset_type='')` |
| `assets.list` | `(asset_type='', *, root='assets/imported')` |
| `assets.list_registered` | `(asset_type='')` |
| `assets.get_metadata` | `(artifact_id)` |
| `assets.set_orientation` | `(reference, *, forward_axis='', up_axis='', yaw_offset_degrees=None, pitch_offset_degrees=None, roll_offset_degrees=None, scale_hint_metres=None, pivot='', verified_by='', notes='')` |
| `assets.get_orientation` | `(reference)` |
| `assets.analyze_orientation` | `(reference, *, asset_type='')` |
| `assets.write_manifest` | `()` |
| `animation.import_motion` | `(source, *, skeleton='', destination='', avatar_name='', options=None)` |
| `animation.resolve_skeleton` | `(artifact_id)` |
| `animation.validate_compatibility` | `(motion_artifact_id, skeleton_artifact_id)` |
| `bindings.bind_pbr_material` | `(*, asset_id, source, mesh_assets, destination='', options=None)` |
| `reflection.inspect_artifact` | `(artifact_id, *, refresh=False)` |
| `reflection.list_object_names` | `(artifact_id)` |
| `preview.render_artifact` | `(reference, *, views='all', size=384, target_samples=2200000, output_dir='')` |
| `preview.render_source` | `(source, *, asset_type='', views='all', size=384, target_samples=2200000, output_dir='')` |
| `preview.orientation_report` | `(reference, *, asset_type='', size=384, output_dir='')` |
| `preview.list_views` | `()` |

可使用 `import_asset(source, 'environment')` 或 `import_asset(source, 'static_mesh')`；系统并未提供专门的 `import_environment`/`import_static_mesh` 封装函数。
`animation.resolve_skeleton` 用于读取骨骼元数据。兼容性检查仅涉及元数据、动画片段及节点层面的校验，并非绑定姿势验证或完整的动作重定向操作。
`reflection.list_object_names` 会返回已记录的动画/材质名称以及几何数量信息；切勿将其等同于完整的场景节点名称枚举。
当参数 `refresh=True` 时，系统会重新读取待处理的内容以供查看；切勿认为这会重写资源注册表。

### 世界与会话| 操作 | 签名 |
|---|---|
| `world.build` | `(source, *, options=None)` |
| `world.create_draft` | `(spec, *, draft_id='', project_id='', metadata=None)` |
| `world.validate_draft` | `(draft_id)` |
| `world.publish_draft` | `(draft_id)` |
| `world.list_packages` | `(*, project_id='', world_id='')` |
| `world.get_scene_graph` | `(draft_id)` |
| `runtime.sessions.join` | `(*, world_id='', participant_id='', user_id='', avatar_artifact_id='', idle_motion_artifact_id='', move_motion_artifact_id='', controller_kind='human', control_mode='exclusive', priority=0, transform=None, parameters=None)` |
| `runtime.sessions.leave` | `(*, participant_id='', controller_id='')` |
| `runtime.sessions.heartbeat` | `(controller_id)` |
| `runtime.sessions.apply_input` | `(controller_id, *, move_x=0.0, move_y=0.0, run=False, jump=False, yaw=0.0, pitch=0.0, seq=0)` |
| `runtime.sessions.snapshot` | `(*, world_id='')` |
| `runtime.sessions.reset_world` | `(*, world_id='')` |
| `runtime.sessions.clear_entity` | `(*, participant_id='', controller_id='', entity_id='', destroy_object=True)` |

### 测试与录制

`testing.run_automation_tests(*, runner='vitest', test_filter='', script='', report_path='', timeout=None, dry_run=False)`。

playwright_root=None, browser_executable=None, browsers_path=None, library_path=None, ffmpeg=None,
duration=14.0, fps=20, width=1280, height=720, timeout=900.0, dry_run=False,
mode='gameplay', preview=False, allow_partial_plan=False, source_hash=None)`。

在将任何结果视为验证依据之前，请先阅读第16节内容。

## 3. 资源标识、加载、方向与PBR绑定

### 已注册的源描述符

对于基于源的导入、World构建、源预览、材质绑定以及包安装操作，需传入映射而非原始文件路径：

```python
source = {
    "game_id": "example_game",
    "run_id": "default",
    "task_kind": "3d_object",
    "task_id": "example_crate",
    "artifact_key": "model_path",
}
```

- 请将示例值替换为已注册的ID。必须提供`game_id`和`task_id`；`run_id`的默认值为`default`。
- 任务类型的推断规则：`scene`对应`3d_scene`，`motion`对应`motion`，`audio`对应`audio`，其余情况对应`3d_object`。包安装需要明确指定任务类型。
- 仅当`meta.json`中恰好有一个非空的`*_path`字段时，才可省略`artifact_key`。元数据标识必须匹配；文件路径必须位于任务目录内。
- 通用场景/特效/环境导入可接受目录形式；绑定和包有单独的规则。
- 优先选择GLB/glTF格式；由导入器负责维护附属文件、注册表及清单文件。需检查许可证、预算限制、边界范围、皮肤及剪辑内容。
- 可选参数包括`asset_id`、`category`、`replace_existing`、`orientation`；任意额外参数可能仅属于元数据范畴，并非用于转换或重定向。
- **若`Asset replace_existing=False`，可能会触发警告并覆盖原有内容**；这并非包安装器的覆盖保护机制。

请区分这些记录：| 记录 | 相关字段/访问方式 |
|---|---|
| 已注册的资源 | `backend_class, backend_path, runtime_capabilities`；通过 `assets.get_metadata(artifact_id)` 可获取 `artifacts[]` 中的记录 |
| 运行时清单条目 | `artifact_id, asset_id, type, class, url, capabilities, orientation, material_bindings, animations, bounds, sun` |
| 世界图资源引用 | 较小的 `assets` 映射；无法替代将清单加载到 AssetLibrary 的操作 |

### JavaScript 资产库

使用 `new A3GameAssetLibrary({manifestUrl, baseUrl, requireManifest, dracoDecoderPath, ktx2TranscoderPath, renderer})` 创建实例。默认的清单/解码器路径为 `/assets/manifest.json`、`/draco/`、`/basis/`，这些路径会通过 `baseUrl` 进行作用域限定。`baseUrl` 在浏览器中默认为文档目录，在 Node 环境中默认为 `/`；需确保其值与构建基准路径及页面服务路径保持一致。

| 方法 | 结果/行为 |
|---|---|
| `resolveUrl(url)` | 重新调整项目资源路径；保留已添加前缀的路径、外部协议、data/blob URL 以及 `//` 开头的 URL |
| `await load()` | 获取/索引清单；返回资产库实例；可查看 `available, manifest, warnings` 属性 |
| `has(reference)`、`findEntry(reference)`、`requireEntry(reference)` | 分别返回布尔值、条目/空值，或条目/抛出异常；候选数组会选取第一个已注册的候选项 |
| `listByType(type)` | 返回匹配类型的清单条目 |
| `await loadArtifact(reference)` | 返回缓存的模型/纹理/音频缓冲区/JSON 结果；并非所有资源都能被实例化 |
| `await instantiate(reference)` | 生成完全独立的模型实例，包含克隆的材料/皮肤及绑定关系；不会自动处理方向/高度相关设置 |
| `await tryInstantiate(reference, options={})` | 返回已准备好的实例或 `null`；加载失败时会将相关信息记入警告列表 |
| `await instantiateOrBuild(reference, fallback, options={})` | 返回已准备好的资产，或同步返回的 Object3D 备用对象；可查看 `source` 属性 |
| `await tryLoadTexture(reference, options={})` | 返回配置好的纹理或 `null`；默认会克隆纹理，`clone:false` 则会修改共享的源状态 |
| `await applyMaterialBinding(object, bindingUrl)` | 应用经过验证的绑定规则；若目标对象或参数无效则会抛出异常 |
| `await applyEnvironment(host, reference, options={})` | 返回环境资源结果或 `null`（当资源不可用时）；若参数或宿主操作无效则可能抛出异常 |
| `await dispose()` | 释放缓存的/资产库占用的资源 |

切勿将缓存的 `loadArtifact` 模型当作独立实体进行修改。准备好的结果会暴露 `object` 属性用于游戏中的变换操作，暴露 `model` 属性用于访问原始模型的根节点。当可选资源缺失时可使用备用几何体；但备用几何体不会自动进行法线重建或方向调整。

```js
const loaded = await assets.tryInstantiate(['scene_crate', 'crate_fallback'], {
  height: 0.8, ground: true, envMapIntensity: 1,
});
if (loaded) host.add(loaded.object, 'environment');
```

在此处及后续代码片段中，除非明确自行创建，否则应从启动上下文中获取 `assets, host, runtime, session, sceneLoader, hud`。

### 方向与模型工具请使用米作为长度单位，采用右手坐标系且Y轴向上，运行时局部前向为-Z轴。需通过视觉方式验证模型的方向设定；仅依靠边界信息无法判断其朝向。
作者设定的坐标轴转换为-Z轴时遵循以下规则：`+z → 180°`，`-z → 0°`，`+x → 90°`，`-x → 270°`。
需通过方向相关API存储以下参数：`forward_axis`（前向轴）、`up_axis`（上向轴）、`yaw_offset_degrees`（偏航角偏移量）、`pitch_offset_degrees`（俯仰角偏移量）、`roll_offset_degrees`（横滚角偏移量）、`scale_hint_metres`（缩放提示值，单位：米）、`pivot`（枢轴点）、`verified_by`（验证人）、`notes`（备注）。
JavaScript端对应的参数名为`forwardAxis`、`yawOffsetDegrees`、`pitchOffsetDegrees`、`rollOffsetDegrees`；设置`orient:false`可禁用方向校正功能。
可使用`height`参数覆盖`scale_hint_metres`的值；设置`ground:true`可使模型的边界框底部与地面对齐。
切勿同时在元数据和处理逻辑中应用相同的校正操作。预先处理好的外部变换会保留内部资产的归一化属性。

| 工具函数 | 功能说明 |
|---|---|
| `measureObject(object)` | 返回物体在世界空间中的`Box3`边界框 |
| `fitToHeight(object, metres)` | 原地调整物体尺寸以匹配指定高度；返回调整后的物体 |
| `groundObject(object, {horizontal=true}={})` | 将物体放置于地面，还可选择将其在原地居中 |
| `forwardAxisYaw(forwardAxis, runtimeForwardAxis='-z')` | 实现轴向的弧度制转换 |
| `orientModel(object, options={})` | 为已有的欧拉旋转添加方向校正；多次调用会累积校正效果 |
| `prepareModel(object, options={})` | 处理模型的方向、缩放、接地及渲染标记；本身不会创建安全的包装层 |
| `principalAxes(points)` | 根据输入的Vector3点集，返回质心以及各轴向的向量和偏差信息 |
| `measureWeapon(object, options={})` | 基于几何特征评估武器轴向的可信度 |
| `alignWeaponModel(object, options={})` | 先进行测量并标记结果；若测量合格则替换四元数数值 |

武器测量时可用的参数包括：`lowerBandFraction`（下限占比）、`minElongation`（最小延伸度）、`maxThicknessRatio`（最大厚度比）、`minMuzzleMargin`（枪口最小余量）、`stride`（步长）。
对齐操作时还可指定`requireConfident`参数；默认情况下，只有符合武器特征且测量可信度高的模型才会被接受。
切勿仅根据注释就推断存在可用的`tipFraction`参数；该参数在此实现中并未被读取。

### 材质绑定
调用`bindings.bind_pbr_material(asset_id=..., source=..., mesh_assets=[artifact_id, ...], options=...)`即可完成绑定。
`mesh_assets`参数需传入已注册的 artifact ID，而非网格名称、资产ID或文件名。
绑定机制会将目标解析为资产URL；运行时匹配依据是已加载的资产标识，而非任意材质名称。

支持的`options.type`类型包括：MeshStandardMaterial、MeshPhysicalMaterial、MeshBasicMaterial、MeshLambertMaterial、MeshPhongMaterial、MeshMatcapMaterial、MeshToonMaterial。

| 参数类别 | 支持的绑定键 |
|---|---|
| 纹理插槽 | `map`、`normalMap`、`roughnessMap`、`metalnessMap`、`aoMap`、`emissiveMap`、`alphaMap`、`displacementMap`、`clearcoatMap`、`sheenColorMap` |
| 标量参数 | `roughness`、`metalness`、`clearcoat`、`clearcoatRoughness`、`sheen`、`sheenRoughness`、`transmission`、`ior`、`iridescence`、`emissiveIntensity`、`normalScale`、`aoMapIntensity`、`envMapIntensity`、`opacity` |
| 颜色参数 | `color`、`emissive`、`sheenColor`、`attenuationColor` |
| 标志参数 | `transparent`、`side`、`flatShading`、`wireframe`、`depthWrite`、`vertexColors` |显式指定的纹理路径会覆盖基于文件名的插槽查找机制；未知选项会触发警告并被忽略。
请查看返回的 `binding_path`、`binding_url`、`material_type`、`targets`、`textures`、`scalars`、`colors` 和 `flags`。
Python绑定创建并不能保证运行时一定能被接受：JS引擎会拒绝匹配目标数为零、材质属性不受支持或数值无效的情况。
颜色/自发光贴图请使用sRGB格式，法线/粗糙度/金属度/AO贴图则使用线性数据格式；同时需保留glTF纹理的方向信息。

### CPU预览与反射
CPU预览功能借助NumPy和Pillow来渲染GLB/glTF的绑定姿势，并非浏览器中的PBR渲染、动画效果，也不涉及Draco/meshopt几何处理。
视图类型：`all`表示全部六个轴向：`+z`、`-z`、`+x`、`-x`、`+y`；`horizontal`表示四个水平轴向；`front_back`表示`+z`/-z轴向；显式列表可支持六个轴向。
轴向名称指的是摄像机的方向，而非模型的正面。目录预览时会选择排序后的首个GLB文件，否则就选择glTF文件。
输出默认路径为`.a3game/previews`；返回的数据包含视图信息、`contact_sheet`、`view_axes`、渲染结果、源路径及输出目录。
`orientation_report`会记录相关依据、决策及反思内容；定向设置需单独提交审核，通过`set_orientation`来实现。

## 4. 世界草稿、发布与浏览器加载
`world.create_draft(spec)`用于创建完整世界规格的草稿；目前没有针对单个实体的补丁/合并API。
`world.build(source)`会将已注册的场景导入为可碰撞的`environment_000`，默认会进行发布操作。
可选参数包括：`world_id`、`project_id`、`publish`、`default_spawn_point`、`native_scene`、`replace_existing`、`environment_artifact_id`、`lights`、`camera`、`environment`。
未知选项会触发警告；`native_scene`仅用于存储元数据，而`environment_artifact_id`是用来指定场景实体，并非HDRI资源。
世界包本质是场景JSON文件，并非npm游戏玩法包。

| 步骤 | 从结果中读取的内容 |
|---|---|
| `create_draft` | `payload.draft`，包含`draft_id`、`spec`、`status`、`metadata` |
| `validate_draft` | 已解析的资源及数量信息；警告/错误信息 |
| `get_scene_graph` | `payload.scene_graph`，用于`sceneLoader.buildWorld(graph)` |
| `publish_draft` | `payload.package.scene_url`/`scene_path`，以及版本号/包标识 |
| `list_packages` | `artifacts[]`中的包列表；`payload.count` |

世界模式的字段采用snake_case命名规则，但嵌入的JS选项字典仍保留文档中规定的camelCase键名，例如`environment.wind.gustStrength`。运行时会话消息采用camelCase命名；切勿机械地重命名这两类标识符。| 世界字段 | 输入合约 |
|---|---|
| 顶层 | `world_id, name, project_id, environment, camera, lights, entities, spawn_points, metadata`；其中world_id默认为world_001 |
| ID | 世界/实体/光源/水体ID遵循格式`[A-Za-z0-9][A-Za-z0-9_.-]*` |
| `entities[]` | `entity_id, role, artifact_id, category, collision, cast_shadow, receive_shadow, transform, behaviors, parameters` |
| 角色类型 | environment、player_start、prop、npc、pickup、trigger、vehicle、weapon、effect |
| `transform` | `{position,rotation,scale}`；向量标准化为`{x,y,z}`格式；默认值为零/零/一 |
| `lights[]` | 必须指定类型：AmbientLight、HemisphereLight、DirectionalLight、PointLight、SpotLight、RectAreaLight；包含light_id、color、intensity、position、target、cast_shadow字段 |
| `behaviors[]` | 必须指定类型：animation/spin/orbit/float/path/audio；动画验证需要artifact_id或clip参数 |
| `camera` | 支持PerspectiveCamera/OrthographicCamera类型；默认参数为fov=50、near=0.1、far=2000，同时包含position、target、controls字段 |
| `environment` | 包含preset、sun、sky、background、environment/background artifact ID、intensity/blur/rotation、show_sky、tone_mapping/exposure、shadows、fog、ground、wind、water等配置项 |
| `spawn_points[]` | 包含name、position、rotation字段 |
| `environment.water[]` | 每个水体有唯一的water_id；包含size、position、normal_artifact_id、terrain_entity_ids、options字段 |

仅当实体角色为environment/prop/vehicle时，collision默认值为true；阴影投射/接收的默认值为true。
Python中的向量输入可接受对象向量，或至少包含三个元素的列表/元组。旋转角度以弧度为单位；缩放操作在资源标准化流程之外执行。
验证机制会检查资源是否就绪、实体ID是否重复、动画引用是否有效；缺少光源/生成点时会有警告提示。
验证过程不会执行行为逻辑、验证导航路径、编译着色器或校验游戏玩法逻辑。

**当前架构/加载器的边界说明：**
- `frustum_height`参数在Python端已被弃用；仅当切换到正交投影模式时，JS图形系统才会应用该参数。加载完成后需通过host.setFrustumHeight设置。
- 控制组件方面：Python支持none、OrbitControls、PointerLockControls、MapControls、FlyControls；JS仅安装OrbitControls和PointerLockControls。需显式卸载旧的控制组件。
- 光源/行为的额外键会作为options参数处理；嵌套的options可在数据往返过程中继续嵌套。如有需要，可在JS中配置高级光源参数。
- behaviors属于`userData.a3gameWorldEntity`中的元数据，并非可执行的动作。世界对象不会被注册为运行时实体；graph.assets也不会向AssetLibrary填充数据。

### A3GameSceneLoader

通过`new A3GameSceneLoader({host, assets})`可获取相关接口：| 方法/属性 | 说明 |
|---|---|
| `await loadWorld(sceneUrl)` | 先获取数据再构建场景；URL不会通过AssetLibrary自动重新定位 |
| `await buildWorld(sceneGraph)` | 释放加载器所持有的旧World实例，然后构建新的World |
| `getEntityObject(entityId)` | 返回对应的Object3D对象，若不存在则返回null |
| `resolveSpawnTransform(index=0)` | 通过取模索引获取生成点的变换信息；需传入非负整数；若列表为空则返回原点/单位缩放值 |
| `sceneGraph` | 原始加载的场景图 |
| `entityObjects, collisionTargets, spawnPoints, waterSurfaces, warnings` | 实体映射表、碰撞体列表、生成点、水面映射表、诊断信息列表 |
| `dispose()` | 释放加载器所持有的内容及订阅关系 |

构建/加载操作会返回`{worldId, entityCount, collisionTargetCount, spawnPoints, warnings}`，而非场景图本身。
没有artifact_id的普通实体会被忽略；player_start会贡献一个生成点。
重建World时不会重置会话中的实体。若要将collisionTargets复制到其他子系统中，需在重建后手动更新。
若采用子路径托管方式，需传入正确解析后的World URL，例如`assets.resolveUrl('/assets/worlds/example.json')`。

## 5. 浏览器启动、视口与宿主生命周期

在启动前需提供指定尺寸的视口和HUD容器。切勿在游戏模块导入阶段创建渲染器或访问文档对象。

```js
import { bootA3GameRuntime, createRoundedBox, createSunLight } from '@a3game/playable';

export async function startGame() {
  const context = await bootA3GameRuntime({
    container: '#a3game-viewport', 
    hudContainer: '#a3game-hud',
    requireManifest: false, 
    autoBeginPlay: false, 
    autoStart: false,
    hostOptions: { fov: 50, fixedTimeStep: 1 / 60 },
  });
  const { host, runtime } = context;
  host.setEnvironment({ preset: 'gradient' });
  host.add(createSunLight({ radius: 20 }), 'environment');
  const ground = createRoundedBox({ width: 30, height: 0.2, depth: 30, preset: 'stone' });
  ground.position.y = -0.1;
  host.add(ground, 'environment');
  host.camera.position.set(0, 4, 8);
  host.camera.lookAt(0, 0, 0);
  runtime.onWorldBeginPlay();
  host.start();
  return context;
}
```

`bootA3GameRuntime`会返回`{host,assets,sceneLoader,hud,session,runtime,world}`；其中world为加载器的汇总信息或null。
可选参数包括：`container/hudContainer/baseUrl/manifestUrl/worldUrl/worldId/hostOptions/requireManifest/createHud/autoBeginPlay, autoStart, entityFactory`。其中autoBeginPlay/autoStart默认值为true；requireManifest默认值为false。
若指定了hudContainer，除非设置createHud=false，否则会自动创建一个HUD；可重复使用该HUD。只有指定worldUrl才会触发World加载。
系统不会自动创建输入路由器、控制器或绑定关系。不存在全局的context.dispose方法。
对于boot函数未转发的解码器、会话或通道选项，需手动构造对应的公共类。

### A3GameRuntimeHost参考主机默认设置：抗锯齿开启、阴影开启、像素比上限为2、清除颜色为0x101014；
相机类型为透视相机，视锥体高度为12，视野范围为50，近平面距离为0.1，远平面距离为2000；
固定时间步长为1/60，最大子步数为6，最大帧间隔为0.1，环境更新间隔为0。
可根据需要接受container/hudContainer、toneMapping/toneMappingExposure以及风力相关参数。
要求fixedTimeStep和environmentUpdateInterval必须为有限的非负数，maxFrameDelta必须为正数，maxSubSteps必须为正整数。

| 分组 | 公共方法 |
|---|---|
| 生命周期 | `await init()`、`start()`、`stop()`、`tick(forcedDelta?)`、`dispose()` |
| 调度 | `onTick(listener)`、`onRender(listener)`、`onResize(listener)`；每种方法均返回取消订阅函数 |
| 插值 | `interpolateObject(object)` 返回取消订阅函数；`resetInterpolation(object)` |
| 场景根节点 | `add(object, rootName='entities')`、`remove(object)`、`getRoot(rootName='entities')` |
| 投影 | `usePerspectiveCamera({fov, near, far})`、`useOrthographicCamera({frustumHeight, near, far})`、`setFrustumHeight(height)` |
| 控制 | `attachOrbitControls(options)`、`attachPointerLockControls()`、`detachControls()` |
| 指针锁定 | `await requestPointerLock()`、`exitPointerLock()`、`isPointerLocked()` |
| 环境 | `setEnvironment(options)`、`setFog(options)`、`setWind(config, immediate=false)` |
| 太阳/IBL | `registerSunLight(light, distance?)`、`getSunDirection()`、`getSunPosition(distance=100)`、`refreshEnvironment()` |
| 查询/数据获取 | `raycastFromPointer(event, targets?)`、`raycast(origin, direction, {targets, near, far})`、`captureFrame()`、`getStats()` |

`add`方法会返回该对象；切换相机的方法会返回当前使用的相机。`remove`方法仅会解除关联，不会释放相关资源。
`registerSunLight`方法会返回取消注册函数。射线检测会返回Three.js原生的交点信息：指针查询返回一个结果或null，射线检测则返回结果数组。
请勿将其与CollisionProbe返回的`{hit,...}`格式结果混淆。

### 固定模拟与显示帧

- `onTick(dt, elapsed)`：用于模拟；在会话或实体处理前需先注册输入/人工智能逻辑。
- `onRender(dt, alpha)`：仅用于显示，不涉及规则判定或权威性移动计算。
- `tick`方法负责推进模拟并渲染画面；若dt为负数或非有限值则会抛出异常；多余的追赶时间会累加到droppedSeconds中。当fixedTimeStep设为0时，则允许使用可变时间步长。
- `interpolateObject`方法会在显示后恢复模拟中的物体变换状态；传送操作后需调用`resetInterpolation`。
- `captureFrame`方法会在`onRender(0, alpha)`阶段运行，仅进行渲染而不推进模拟。
- `getStats`返回的数据包括：frameCount（帧数）、elapsedSeconds（经过的秒数）、simulationSteps（模拟子步数）、interpolationAlpha（插值系数）、droppedSeconds（丢帧时间）、drawCalls（绘制调用次数）、triangles（三角形数量）、geometries（几何体数量）、textures（纹理数量）、programs（着色器程序数量）、pixelRatio（像素比）以及size（画布尺寸）。其中simulationSteps表示最新一帧的子步数。
- 需利用dt来控制冷却时间与平滑效果；无需额外的游戏循环请求动画帧或时钟计时器。

### 视口与相机容器尺寸用于控制渲染器/投影，支持窗口回退和自动调整大小功能；onResize会接收`{width,height}`参数。
捕获视口即指页面尺寸。captureFrame会返回不含DOM界面元素的画布PNG数据URL；录制器页面捕获功能会包含该内容。

| 设置项 | 说明 |
|---|---|
| 透视相机视野角 | 以垂直方向度数计；可见高度=`2*d*tan(fov*PI/360)`，宽度=高度×宽高比 |
| 正交相机视锥高度 | 可见世界高度；宽度=高度×宽高比 |
| 相机切换 | 复制位置、四元数及父级信息，并控制.object属性，但不涉及缩放或图层设置 |
| 轨道控制选项 | 仅支持target、enableDamping、maxPolarAngle、minDistance、maxDistance这几个参数 |
| 所有权规则 | 仅能有一个相机驱动器；切勿将此类控制与独立的偏航/俯仰写入操作混用 |
| 指针锁定 | 需由用户触发 |

需根据相机**及控制模型**选择参考项；应在生成的游戏玩法包内进行调整，而非将其作为依赖项。详情可查看[示例](../../engine_adapters/three_js/examples/README.md)。

| 示例 | 相机所有权 | 输入/移动方式 |
|---|---|---|
| `fps-example` | 第一人称玩家相机 | 通过指针锁定实现视角控制，直接移动角色 |
| `arena-fighter-example` | 共享对决相机（示例中称为“第二人称”相机） | 面向固定方向的对决移动逻辑 |
| `racing-example` | 第三人称跟随相机 | 车辆转向控制；相机随车辆朝向同步移动 |
| `explorer-example` | 第三人称跟随/轨道相机 | 基于相机坐标系的角色移动逻辑 |
| `rts-example` | 独立的俯视地图相机 | 支持平移/缩放；可选取单位并下达队列式指令（见第9节） |

`motion-vfx-example`在上述基础上增加了角色动画和批量特效功能。
即时战略类场景可使用**正交或透视**投影；本示例选用正交投影。可通过`setFrustumHeight`调整视锥高度；沿视图轴平移并不会导致缩放。
可自定义相机空间的场景深度范围：正交投影下允许设置负值的近平面值，但并非必需。需确保仅有一个相机驱动器，在拾取物体前更新矩阵，同时绑定地图平移功能。

## 6. 光照、天空、材质及纹理缩放

```js
host.setEnvironment({
  preset: 'gradient', sunPosition: { x: -0.5, y: 0.8, z: -0.3 },
  sky: { zenith: 0x2f6fbd, horizon: 0xd3e2ee, cloudCoverage: 0.44 },
  toneMapping: 'NeutralToneMapping', toneMappingExposure: 1,
});
host.setFog({ type: 'Fog', color: 0xd3e2ee, near: 70, far: 240 });
```

预设类型包括：room（室内IBL环境）、gradient（可调节的天空/云层效果）、sky（物理天空）、none。可将IBL与环境光结合使用；自发光材质并非光源。默认的色调映射方式为NeutralToneMapping。| 控制项 | 说明 |
|---|---|
| sunPosition | 指向太阳的非零 `{x,y,z}`/Vector3数值，并非数组 |
| `createSunLight({radius,mapSize,near,far,position,target,intensity,syncEnvironment})` | 主光源/阴影区域；调用`host.add`可注册同步机制；传入`false`可禁用该光源 |
| `createFillLight({skyColor,groundColor,intensity})` | 半球光 |
| getSunPosition | 相对于原点的坐标值；已注册的方向光会围绕各自的目标点同步位置 |
| setEnvironment({sunPosition}) | 更新天空以及已注册的光源 |
| refreshEnvironment / environmentUpdateInterval | 手动重建程序化IBL，或按设定的模拟间隔重建，无需导入HDRI贴图 |
| assets.applyEnvironment(host,ref,options) | 设置`background:false`可保留天空效果；可选参数包括environmentIntensity、backgroundReference、backgroundBlurriness、shared rotationDegrees |
| host.setEnvironment | 此处可用于单独设置backgroundRotationDegrees/environmentRotationDegrees，或设置showSky:false + background |

请使用sRGB色彩贴图和线性数据贴图；PMREM中无需进行双重伽马校正或显示色调映射。

| API | 重要参数/所有权说明 |
|---|---|
| `createMaterial(preset, overrides={})` | 标准/物理PBR材质；若预设名称未知则会报错 |
| `createRoundedBox(options)` | 可设置宽度/高度/深度/圆角半径/分段数/材质/预设/渲染标志；可见的倒角不会替换简单的碰撞体 |
| `createSurfaceTextures(options)` | 可设置图案、尺寸、重复次数、颜色、接缝颜色、粗糙度、单元格数量、对比度、法线强度、种子、渲染器、各向异性参数 |
| `createSurfaceMaterial(options)` | 基于表面纹理生成材质，可额外设置normalScale、金属度、envMapIntensity；选项里的`options.material`可覆盖材质的其他属性 |
| `createTilingTexture(texture, options)` | 可设置贴图的重复次数、旋转角度、srgb模式、色彩空间、各向异性参数 |
| `createRadialGradientTexture({resolution=128,color})` | 在浏览器中通过Canvas生成，若无DOM元素则回退为DataTexture；浏览器环境下颜色需使用CSS颜色字符串 |
| `createContactShadow({radius,opacity,...})` | 用于生成视觉上的接触阴影网格；需将其置于碰撞目标之外 |

`A3GameMaterialPreset`的可选名称包括：METAL、GUNMETAL、PAINTED_METAL、PLASTIC、RUBBER、CLOTH、LEATHER、WOOD、STONE、CONCRETE、TARMAC、GRASS、SAND、GLASS、EMISSIVE（对应的值均为小写形式）。
`A3GameSurfacePattern`的可选名称包括：CONCRETE、STEEL_PLATE、BLOCKWORK、PAINTED_PANEL。
表面尺寸以像素为单位；重复次数可为标量或`[u,v]`形式，并非以米为单位。应根据实际网格尺寸和期望的贴图平铺大小来确定重复次数。
纹理集会返回`{map, normalMap, roughnessMap, height, size, dispose}`。请使用统一的height字段来保证凹凸效果的一致性。
该纹理集也可通过`material.userData.surface`访问；仅调用`material.dispose`并不会释放其关联的纹理。
法线信息会影响光照效果，不会影响几何形状或碰撞检测。材质的粗糙度会与roughnessMap的数值相乘。`createSkyGradient(options)`函数支持设置天顶/地平线/地面颜色、太阳方向、太阳颜色、太阳大小、太阳光晕效果、云层覆盖率、云层透明度、云层缩放比例、云层移动速度、云层颜色、云层阴影、云层高度、雾霾效果以及风场参数。
仅当并非由宿主驱动时，才可使用其`userData.update(dt,wind?)`方法和`setSunDirection(direction)`方法。
若要禁用太阳圆盘，可将`sunSize`参数设为0；太阳圆盘大小、光晕衰减范围以及雾霾效果均为独立控制项。

## 7. 场景构图与可复用布局辅助工具

- 规划场景内的动线、地标、层级关系及围合结构；确保生成点、任务目标及摄像机路径清晰明确。
- 地形、地面模型、道具、路径及水面共用同一高度数据源；需保证视觉表现、碰撞体变换及尺寸的一致性。
- 使用`createSeededRandom(seed)`生成随机数；需验证旋转后的轮廓、间隙、坡度、边界以及分隔段的完整性。
- 通过实际求解器测试跳跃可达范围；需检查玩家视角下及俯视视角下的遮挡情况。
- 区分前景、中景和背景元素，避免远处轮廓因雾化效果而模糊不清。

| 辅助函数 | 功能说明 |
|---|---|
| `directionToYaw(direction)` | 接收`{x,z}`或Vector3类型参数；返回`atan2(-x,-z)`值；若XZ分量为零或非有限数值则报错 |
| `yawToDirection(yaw,pitch=0,target?)` | 返回单位长度的运行时前进方向Vector3；正值俯仰角表示向上看 |
| `footprintCorners({x,z,width,depth,rotation},margin=0)` | 基于THREE的Y轴旋转计算四个`{x,z}`坐标角点；`margin`参数用于扩展各侧边距 |
| `distanceToPolyline(point,points,closed=false)` | 计算点到有限线段/端点的XZ距离；若路径为空则返回Infinity |
| `createGroundRibbon(points,options={})` | 生成贴合地形的网格；不会自动成为碰撞体 |
| `createFacadeTexture(options={})` | 生成带随机种子的sRGB格式的DataTexture，无需依赖Canvas |
| `createDistantRange({radius,height,baseY,color,topColor,segments,roughness,seed})` | 生成无缝衔接的远处山脉环带 |
| `createCloudLayer(options={})` | 生成精灵云层组；可配置云朵数量、半径、高度、大小、纹理、颜色、透明度、随机种子、移动速度及风场参数 |
| `createInstancedFromModel(source,count,options={})` | 仅支持单个非蒙皮网格；若源模型包含不支持的层级结构则返回null |

```js
import { createGroundRibbon } from '@a3game/playable';

const trail = createGroundRibbon([[0, 0], [0, -8], [5, -16]], {
  width: 2, heightAt: terrainHeight, lift: 0.03, tileLength: 2, segments: 8,
});
host.add(trail, 'environment');
```

Ribbon函数的参数可接受Vector3、`{x,y?,z}`、`[x,z]`或`[x,y,z]`类型值。
`width`、`lift`、`tileLength`的单位为米；`segments`表示每个源线段的细分数量，最大值为1024。
开放路径至少需要两个不重复的XZ坐标点，闭合路径则需要三个坐标点。
UV坐标基于米/`tileLength`计算；`userData.pathLength`表示XZ方向的中心线长度。
`heightAt`参数会对路径两侧进行高度投影；若不指定该参数，则会插值计算路径的Y坐标。该函数还支持`closed`、`material`、`name`等可选参数。
为生成平滑曲线需提供足够多的源坐标点；尖锐拐点或自相交情况需在应用层面另行处理。立面默认参数：宽度=256像素，高度=512像素；列数=6，行数=12，种子值=1，发光比例=0.45。
需设置墙面颜色、窗户颜色和发光颜色；各参数取值范围需在16到2048之间，且每个单元格尺寸至少为4像素。
发光的窗户仅呈现烘焙后的颜色，并非光源；如需实现发光效果，需使用限制发射强度的材质设置。

云对象的userData属性提供update、attachToHost、dispose方法；该对象只需附加一次，无需手动再次更新。
受风力驱动的云会依据风场移动，而非采用固定速度漂移。
实例化机制会克隆/烘焙几何体，但共享材质；在烘焙变换数据前，需先将模板置于原点位置。
调用setMatrixAt方法后需设置instanceMatrix.needsUpdate，当物体摆放位置发生变化时还需刷新实例边界。
相关选项包括castShadow（投射阴影）、receiveShadow（接收阴影）、frustumCulled（视锥体剔除）；即便启用这些选项，分组渲染和阴影通道仍可能增加绘制调用次数。
实例化能减少绘制调用次数，但不会减少三角形数量；对于高多边形数量的重复道具，需根据距离和细节需求来合理控制其渲染量。

## 8. 运行时线缆数据、接口与身份标识

运行时消息采用驼峰命名的普通对象形式。数据工厂会对已知字段进行规范化处理；它们并非完整的验证器，会丢弃未知的顶层字段。
测试中需使用明确的身份标识和递增序列；timestampSeconds字段默认取值为性能计时时间，而非主机模拟时间。
除`createVector3(source, fallback={x:0,y:0,z:0})`外，其他数据工厂均接受`(source={})`作为参数。

| 工厂函数 | 输出字段 |
|---|---|
| `createVector3` | 从对象中提取或至少包含三个数组元素的普通`{x,y,z}`结构；并非THREE.Vector3类型 |
| `createTransform` | 包含`position`（位置）、`rotation`（旋转）、`scale`（缩放）字段；默认值分别为零、零、一 |
| `createRuntimeInputState` | 包含`worldId`（世界ID）、`participantId`（参与者ID）、`controllerId`（控制器ID）、`entityId`（实体ID）、`moveX`、`moveY`、`run`（奔跑）、`jump`（跳跃）、`yaw`（偏航角）、`pitch`（俯仰角）、`sequence`（序列号）、`timestampSeconds`（时间戳）字段 |
| `createEntitySpawnRequest` | 包含`worldId`、`participantId`、`entityId`、`transform`（变换信息）、`parameters`（参数）字段 |
| `createParticipantInfo` | 包含`participantId`、`worldId`、`userId`（用户ID）、`entityId`、`online`（在线状态）、`lastSeenSeconds`（最后活跃时间）字段 |
| `createControllerState` | 包含`controllerId`、`participantId`、`worldId`、`kind`（类型）、`online`、`lastSeenSeconds`字段 |
| `createControlBinding` | 包含`controllerId`、`entityId`、`worldId`、`mode`（模式）、`priority`（优先级）、`active`（激活状态）字段 |
| `createEntitySnapshot` | 包含`entityId`、`objectName`（物体名称）、`position`、`rotation`、`locomotionState`（运动状态）、`motionState`（动作状态）、`persistent`（持久化标记）、`lastInputTimeSeconds`（最后一次输入时间）字段 |
| `locomotionStateFromInput` | 优先处理跳跃动作，随后根据1e-3的移动阈值判断奔跑/行走/静止状态 |

需分别将moveX和moveY的取值范围限制在[-1,1]之间，再对游戏中的综合移动向量加以限制，以避免出现对角线移动速度过快的情况。
工厂函数会将sequence/priority字段截断为整数，但不会强制要求它们呈单调递增关系；parameters字段会被浅拷贝。
控制器类型默认值为human（人类）；online/active/persistent字段的默认值均为true。游戏特有的生命值/得分状态需定义在固定的通用快照工厂之外。`A3GameControlMode`：EXCLUSIVE='独占模式'，PRIORITY='优先模式'，ASSISTED='辅助模式'，OBSERVING='观察模式'。
`A3GameLocomotionState`：IDLE='静止状态'，WALK='行走状态'，RUN='奔跑状态'，JUMP='跳跃状态'。
`A3GameRuntimeCommand`：SYNC_SESSION='同步会话'，LEAVE_SESSION='离开会话'，APPLY_INPUT='应用输入指令'，
WORLD_SNAPSHOT='世界快照'，RESET_WORLD='重置世界'，CLEAR_ENTITY='清除实体'。

### 实体、工厂与消息处理器契约

通过继承或鸭子类型来实现：
| 接口 | 必需的契约 |
|---|---|
| `A3GameControllableEntity` | getRuntimeEntityId()、setRuntimeEntityId(entityId)、applyRuntimeInput(inputState) → 布尔值、getRuntimeSnapshot() → 可序列化对象 |
| 可选的实体钩子 | tick(deltaSeconds)、dispose() |
| `A3GameEntityFactory` | spawnRuntimeEntity(request,{host,assets,session}) → 实体或实体的Promise |
| `A3GameRuntimeMessageHandler` | handleRuntimeMessage(messageType,payload) → 同步布尔值 |

`CONTROLLABLE_ENTITY_METHODS`、`ENTITY_FACTORY_METHODS`、`RUNTIME_MESSAGE_HANDLER_METHODS`列出了必需的方法。
`isControllableEntity`、`isEntityFactory`、`isRuntimeMessageHandler`用于检查方法是否存在；
`assertControllableEntity/assertEntityFactory/assertRuntimeMessageHandler(candidate,label?)`会返回传入的候选对象，否则抛出TypeError异常。
请勿使用异步消息处理器：运行时扩展调度不会等待处理器执行完毕。
工厂负责模型的创建、场景挂载以及游戏逻辑组装；框架不会自动移动Object3D实例。

### 身份与运行时组件

`A3GAME_USER_DATA_KEY='a3game'`；`A3GameIdentityComponent(object,{participantId,entityId})`会将身份信息存储在object.userData.a3game中。
静态附加操作会复用或更新组件；get方法用于查询对象中的组件；findInParents方法会在父级中查找组件。
setRuntimeIdentity(participantId,entityId)用于更新身份信息；toJSON会返回participantId、entityId、objectName和objectUuid。

`A3GameRuntimeEntityComponent(object,{entityId,participantId,persistent})`提供了静态的get方法、setRuntimeEntityId方法，
onRuntimeInput(listener) → 取消订阅、applyRuntimeInput(rawInputState)、setMotionState、getRuntimeSnapshot、dispose方法。
它存储的是输入信息而非运动数据；需要将其封装在实现了getRuntimeEntityId方法的实体中。快照使用的是本地位置/旋转信息。
序列号拒绝机制是针对整个组件的，仅适用于递增的非正值，不适用于零/负值或身份验证相关场景。
dispose方法只会清除输入状态，不会清除身份信息或Object3D/GPU资源。

## 9. 输入路由与会话所有权

采用+Y为向上方向、单位为米、弧度、秒以及米/秒。运行时偏航角=0时对应朝向-Z方向；偏航角=π/2时对应朝向-X方向。
前进方向为`(-sin(yaw),0,-cos(yaw))`；右方方向为`(cos(yaw),0,-sin(yaw))`。
moveY=1表示向前移动，moveX=1表示向右移动。需将归一化后的移动量乘以速度和dt来计算实际位移。
可根据示例（§5）选择偏航角和移动语义，无需为所有游戏统一采用同一套规范。**即时战略游戏/指令驱动输入**（`examples/rts-example`）：连续的位置数据、实时更新；
`moveX/moveY`用于平移相机，被选中的单位会执行按先进先出顺序排列的离散指令。

- 游戏逻辑中会保留选中状态、到达/停止规则以及编队偏移量。该示例不提供路径查找、人群避让、建筑经济系统或远程指令传输功能。
- 将可见的单位中心投影到画布像素上以实现框选操作；这种方式在两种投影模式下均适用。仅可使用`raycastFromPointer(event, groundTargets)`来确定移动目标。
- 拾取、瞄准以及小地图标记功能基于当前视野范围判定，而非仅依据已探索的地形。
- 手势识别从画布按下到释放/取消全程由自身处理；忽略HUD区域的点击操作，且在鼠标离开/失去焦点时重置边缘平移功能。需单独预留平移/停止按键。该示例不使用指针锁定机制，而是始终采用`ALWAYS`模式，同时将`pointerSensitivity`设为0，且仅对相机进行一次采样，不会通过`pipeToSession`重复采样。
- 没有实体形态的指挥官需使用`registerParticipant` + `createController`；即便处于观察模式下，`syncSession`也会始终生成一个实体。`spawnEntity`本身并不会注册实体：需调用`session.registerEntity`。运行时会对该实体进行更新并处理销毁，因此切勿为你的单位赋予第二个生命周期。自定义的生成参数需通过`parameters`传递。

构造函数为：`new A3GameInputRouter({target,controllerId,keyBindings,actionBindings,pointerSensitivity=.0025, invertPitch=false, maxPitch=PI/2-.05, lookMode='pointer-lock', gamepadIndex=null})`。
建议将`host.container`作为target：默认的窗口目标无法安装指针监听器。
`keyBindings`会合并`DEFAULT_KEY_BINDINGS`（WASD/方向键、Shift、空格键）；默认的鼠标操作为左键/右键。
`A3GameLookMode`的取值包括：POINTER_LOCK、DRAG、ALWAYS。可通过`setLook(yaw,pitch)`设置游戏启动或重生时的视角。

| 方法 | 功能说明 |
|---|---|
| `enable()/disable()/reset()` | 管理监听器及持续输入状态；不会重置偏航角、俯仰角或序列号 |
| `setLook(yaw,pitch=this.pitch)` | 设置绝对视角，同时限制俯仰角范围 |
| `onAction(listener)` | 本地回调`(action,phase)`，可获取按键按下/释放事件；返回取消订阅函数 |
| `isActionHeld(action)` | 查询当前按键的持续按压状态 |
| `sample(identity={})` | 获取运行时输入帧数据；序列号会随之递增；跳跃操作属于按下瞬间触发事件 |
| `pipeToSession(session,host,identity)` | 在运行时消费输入数据前插入采样步骤；返回取消订阅函数 |

`pipeToSession`不会启用输入路由器、创建控制器或绑定实体。
命名后的动作事件不会包含在移动逻辑框架中；如需实现远程游戏操作，需自行实现指令传输机制。
`reset`会清除已按压的按键状态，但不会触发所有释放回调；`disable`配合保存的取消订阅函数可替代不存在的`router.dispose()`方法。
游戏手柄相关设置：axes0/1用于控制移动，axes2/3用于控制视角，button10用于奔跑，button0用于跳跃，button7对应主按键，button6对应次按键；死区阈值为0.15。
游戏手柄的输入轮询在`sample`阶段进行，会覆盖键盘的移动/奔跑指令，且每次采样时应用的视角缩放系数固定为0.04，而非根据时间增量动态调整。

### 参与者、控制器、实体与绑定参与者用于标识用户，控制器负责生成输入指令，实体则负责实现游戏逻辑，而绑定机制则将控制器与实体关联起来。
通过 `new A3GameWorldSessionSubsystem({worldId='world_001',inputConsumeHz=60})` 可调用以下功能：

| 公共方法 | 返回结果/执行操作 |
|---|---|
| `registerParticipant(participantId,userId='')` | 创建参与者记录 |
| `markParticipantOffline(participantId)` | 标记该参与者及对应的控制器为离线状态，解除相关绑定；但实体仍会保留 |
| `createController(participantId,controllerId='',kind='human')` | 创建控制器记录 |
| `registerEntity(entityId,entity,participantId='')` | 返回解析后的实体ID |
| `getEntity(entityId)` | 返回对应的实体，若不存在则返回null |
| `removeEntity(entityId,disposeEntity=true)` | 移除实体，可根据参数决定是否释放该实体占用的资源 |
| `bindControllerToEntity(controllerId,entityId,mode=EXCLUSIVE,priority=0)` | 建立控制器与实体之间的绑定关系 |
| `unbindController(controllerId)` | 解除控制器与实体的绑定 |
| `await syncSession(payload,spawnEntity)` | 注册/同步实体并调用工厂函数；最终返回实体标识 |
| `enqueueInputState(rawInputState)` | 将原始输入状态加入最新输入队列，不会立即触发角色移动 |
| `consumeLatestInputs(deltaSeconds)` | 按预设时间间隔处理队列中的输入帧；返回已处理的输入数量 |
| `getWorldStateSnapshot()` | 返回当前世界中所有实体的快照数组 |
| `getSessionSnapshot()` | 返回包含worldId、参与者、控制器、绑定关系及实体的会话快照 |
| `resetWorld(disposeEntities=true)` | 清空当前会话并返回被清除的实体ID；不会重新加载静态世界数据 |

`syncSession` 的参数格式为：`{participant:{participantId,userId},controller:{controllerId,kind},binding:{mode,priority},spawnRequest:{entityId,transform,parameters}}`。
返回的实体标识为 `{worldId,participantId,controllerId,entityId}`。若工厂函数执行失败，系统不保证会进行事务回滚。
为便于确定性测试，请使用显式指定的ID；系统生成的ID则基于时间戳或随机数。

```js
import { A3GameInputRouter } from '@a3game/playable';

// 从启用了autoBeginPlay:false和autoStart:false的上下文开始运行。
runtime.setEntityFactory(factory);
session.registerParticipant('local-player');
const entity = await runtime.spawnEntity({
  entityId: 'player-1', participantId: 'local-player',
  transform: sceneLoader.resolveSpawnTransform(0),
});
const entityId = session.registerEntity('player-1', entity, 'local-player');
const controller = session.createController('local-player', 'keyboard-1');
session.bindControllerToEntity(controller.controllerId, entityId);
const input = new A3GameInputRouter({ target: host.container, controllerId: controller.controllerId }).enable();
const stopInput = input.pipeToSession(session, host, { controllerId: controller.controllerId });
runtime.onWorldBeginPlay();
host.start();
```根据第8节内容为工厂提供资源。会话传递规则如下：
- 保留最后到达的帧/控制器；被覆盖的边缘数据将会丢失。活跃的绑定会设置worldId/entityId；无需进行身份验证或序列排序。
- EXCLUSIVE模式会移除其他实体绑定；OBSERVING模式不会发送输入数据。其余模式均按优先级降序传递数据，不会进行优胜者筛选或数据混合处理。
- 每个时间间隔仅消费一个批次的数据并重置累加器；不会重放已错过的批次数据。

## 10. 运行时编排、命令与传输

通过`new A3GameRuntimeSubsystem({host,session,assets,channel,autoConnect})`创建实例，其中autoConnect参数默认值为true。
公共API包括：setEntityFactory(factory)、registerMessageHandler(handler)、unregisterMessageHandler(handler)、getSessionSubsystem()、onWorldBeginPlay()、deinitialize()、spawnEntity(rawRequest)、handleRuntimeCommand(command,payload={})、dispatchExtensionMessage(messageType,payload)。registerMessageHandler方法会返回取消订阅函数。spawnEntity和handleRuntimeCommand均为异步操作。
spawnEntity仅负责调用工厂；实体的注册/绑定操作需单独执行，或通过syncSession完成。onWorldBeginPlay方法是幂等的，会在更新已注册实体之前先处理输入数据。切勿手动更新这些实体。deinitialize方法会解除对tick操作和通道的绑定，重置会话中的实体并清除相关处理器，但不会影响宿主、资源或HUD。
未知消息会同步传递给所有已注册的处理器，不会在首个处理器返回true时停止传递。

| 命令值 | 负载/结果 |
|---|---|
| sync_session | 来自第9节的会话同步负载数据；返回身份标识 |
| leave_session | controllerIds数组和/或participantId；解除绑定/标记为离线状态，但保留实体 |
| apply_input | 运行时输入帧；若被接受则意味着已加入队列 |
| world_snapshot | 返回完整的会话快照 |
| reset_world | 清空运行时会话并返回clearedEntities列表 |
| clear_entity | 指定entityId，销毁对应对象；若参数为false则跳过entity.dispose操作，但仍会移除注册信息 |
| 其他字符串 | 传递给扩展处理器；可查看handled_by和ok字段 |

### 浏览器通道与本地桥接

通过`new A3GameRuntimeChannel({onCommand,host,port,transport='local',pollIntervalMs=250,globalName='__A3GAME_RUNTIME__'})`创建实例。
若未指定host/port参数，则会使用`engine_adapters/three_js/plugin/A3GamePlayable/src/engine/runtime-channel.js`中定义的回环运行时默认值。
公共API包括：baseUrl获取器、connect()、disconnect()、await dispatch(command,payload={})、getHistory()。
优先级顺序为：选项参数 → VITE_A3GAME_RUNTIME_* → A3GAME_RUNTIME_* → 默认配置。
connect方法会安装本地桥接；若需使用WebSocket或轮询机制，则需明确选择并配备中继服务（Vite并未提供此类服务）。
该系统没有回退机制、重连功能或访问控制功能。connected状态并不等同于中继服务正常运行状态；history会保留包含200条记录的数据，每条记录包含wall-clock durationMs/at字段。`globalThis.__A3GAME_RUNTIME__`：用于频道/命令/分发/同步会话/应用输入/生成快照/重置世界/清除实体/历史记录相关操作。
这些命令是异步执行的；历史记录相关操作则是同步的。调用方式为例：`dispatch('leave_session', payload)`；目前没有现成的`leaveSession`辅助函数。
`dispatch`会捕获错误；直接调用`handleRuntimeCommand`可能会返回拒绝状态。轮询机制为：通过GET请求获取待处理任务，通过POST请求提交结果。
WebSocket通信格式为：客户端发送`{id, command, payload}`，服务器返回`{id, result}`。

### Python运行时会话
- 需将snake_case格式的参数转换为JS通信字段。默认的世界名称为`world_001`；使用前提是需要先准备好基于Web的虚拟形象、道具以及动作资源。
- 调用`leave`会解除绑定但保留实体；`clear_entity`会移除实体注册信息；`reset_world`则会清空整个会话。
- 心跳信号和快照可能反映的是Python端的本地状态。即便外层返回的`ok`值为`true`，也需检查`payload.runtime_delivery.delivered`和`response`字段。
- 命令传输采用HTTP POST请求发送至`/command`端点，即便配置中启用了WebSocket也是如此；需单独配置兼容的浏览器中继服务。
- 序列值仅会被转发；集成过程中需自行保证顺序以及游戏动作的语义一致性。

### 电影级播放与剪辑切换
在正在运行的游戏中播放标准的CG视频剪辑——这类剪辑可以是关卡过场动画，也可以是游戏运行中的过渡场景，而非游戏启动时的内容。
`A3GameCinematicPlayer`负责处理播放请求以及临时的`<video>`元素；游戏逻辑则负责触发播放、设定角色姿势以及执行剪辑切换操作。
网关提供的是已存储的剪辑而非实时生成的（`browser_serving_api.md`），因此剪辑的首尾帧在生成时就已经固定：需利用运行时自带的摄像头捕获这些帧，分别记为任务的`first_frame_path`和`last_frame_path`，这样拼接处就能通过重新渲染实现无缝衔接，而非靠近似处理。重新捕获帧后需更新这些文件的版本；`meta.json`中存储的是文件路径而非内容哈希值。

所有操作需在同一个tick内完成：若摄像头正在补间移动到被传送的实体位置，会导致该实体滑入目标点，进而使捕获的帧依赖于摄像头的过往状态。`host`对应`A3GameRuntimeHost`，`input`对应`A3GameInputRouter`，`seize`则是游戏自身的逻辑。

```js
input.disable();                          // 停止接收新输入
seize(entity, poseA);                     // 设置位置和朝向，无需设置position.y
host.stop();                              // 在单个tick内执行是安全的：后续的更新请求会被取消
for (let i = 0; i < steps; i += 1) host.tick(1 / 60);
host.tick(0);                             // 纯重绘操作：此时帧缓冲区已保存目标帧
```

切勿直接设置`position.y`；实体会根据采样到的地面高度进行补间移动，因此只需设置`x`、`z`值和朝向即可。
`steps`的值需根据游戏自身的摄像头补间速率确定：若摄像头的缓动函数为`1 - exp(-k * delta)`，那么循环结束后摄像头的衰减程度为`exp(-k * steps / 60)`。

需清除游戏同步到实体上的输入状态，而非仅清除路由器中的状态：`disable()`只会重置路由器的轴向参数，但残留的节流字段仍会让实体在剪辑播放期间继续加速。收敛完成后需重新设定恢复速度，避免被阻尼效应抵消该速度。不要在元素触发`play()`解析完成后再执行后续操作——因为`play()`是在播放开始时才解析完成的。而应在元素的`ended`事件触发时执行相应操作。此外还需添加错误处理路径，以及设置`duration * 1000 + 2000`的看门狗机制：因为卡住的元素永远不会触发`ended`事件，而没有控制选项导致游戏冻结，比错过一段视频片段的后果更糟糕。恢复游戏运行的操作是调用`host.start()`和`input.enable()`。

触发逻辑应基于游戏自身的时间进度指针，而非几何信息，且需逐帧对比差异：时间指针会在上报前就递增，因此如果实体在触发区域内生成，会在第一帧就被检测到。

有两个需要遵循的限制：调用`disable()`会移除路由器的`window`监听器，因此当玩家按住某个按键时，在调用`enable()`恢复监听器前不会收到任何输入信号；另外收敛操作会阻塞主线程，因此请求操作的时间应参考资源计时数据（`entry.duration`），而非放在`await fetch(...)`语句附近。

## 11. 动画与运动库

将游戏玩法/碰撞根节点与其可替换的动画视觉效果分离。运动资源并不等同于可见角色；当没有可用的动画角色时，需保留程序化回退机制。

```js
import { createAnimatedActor } from '@a3game/playable';

const actor = await createAnimatedActor(assets, ['hero', 'hero_fallback'], {
  height: 1.8, states: ['idle', 'walk', 'run'], defaultState: 'idle',
});
const stopAnimation = actor?.animator?.attachToHost(host);
```

将`actor.object`附加到视觉根节点上；动画器销毁时需单独取消订阅。最终得到的`motionSource`取值包括`clips`、`imported_motion`、`rigged_asset`、`auto_rig`、`none`，同时还会返回骨骼信息、测量数据及相关警告。可选参数包括`ground`、`motionReferences`、`motionLibrary`、`clipSpeed`、`shoulderWidth`、`minAspect`、`maxAspect`、`requireMotion`、`autoRig`。其中`requireMotion`会拒绝无运动数据的结果；设置`autoRig:false`只会禁用生成的骨骼回退机制，不会影响剪辑或导入的运动数据。`clipSpeed`仅影响生成的剪辑；`states`并非严格的过滤条件。默认参数为：`ground=true`、`envMapIntensity=1`、`frustumCulled=false`。

### A3GameAnimationDirector

构造函数：`new A3GameAnimationDirector(root,clips=[],{defaultFade=.2})`

| API | 功能描述 |
|---|---|
| `addClip`、`addClips`、`listClipNames` | 添加并枚举剪辑 |
| `mapState(state,clipName)`、`mapStates(mapping)` | 绑定状态；批量操作时返回缺失的名称 |
| `mapStateChain(state,candidates)`、`mapStateChains(mapping)` | 选择可用的候选剪辑；批量操作时返回已绑定/缺失的名称 |
| `play(state,options={})` | 可设置淡入效果、循环模式、时间缩放、播放结束时的限制等参数；返回操作对象或null |
| `playOnce(state,{fade,timeScale})` | 播放一次剪辑，通过混合器更新时解析返回的Promise |
| `stopAll(fade=0)`、`update(dt)`、`attachToHost(host)` | 控制播放；附加到宿主后返回取消订阅的函数 |
| `getState()`、`dispose()` | 查看并释放混合器状态 |名称匹配规则为：完全匹配且大小写不敏感，其次才是子字符串匹配。无需重启即可重放相同状态时，不会重新应用所有参数。
playOnce动作完成后，混合器仍会持续更新。Director被销毁时，不会自动调用此前返回的宿主取消订阅函数。
切勿从状态名称的交叉渐变中推断出完整的叠加图层或骨骼重定向系统。

### 动作库与底层工具

`new A3GameMotionLibrary({assets})`：提供getter方法、listMotions()函数，支持await loadClips(reference)以及await loadForCharacter(character,{references,states,rename}) → `{clips,sources}`；可查看警告信息与缓存。该对象没有公开的dispose方法。

| 函数 | 功能说明 |
|---|---|
| `createHumanoidSkeleton({height,centre,baseY,shoulderWidth})` | 返回根节点、骨骼列表、按名称查找的映射表、骨架信息及半径值；不会生成可见角色模型 |
| `measureHumanoid(object,{minAspect,maxAspect})` | 用于评估人体比例、尺寸、中心点、基准Y轴位置及原因；并非语义层面的面部检测 |
| `autoRigHumanoid(object,options)` | 尝试进行近似绑定，可能返回null；可设置身高、中心点、基准Y轴位置、肩宽、最大骨骼数及是否投射阴影等参数 |
| `findRiggedHumanoid(object,minimumBones=12)` | 检查首个骨架中是否存在规范的骨骼名称及髋部骨骼 |
| `createHumanoidClip(state,{height,speed,hipsRest})` | 生成对应的动作剪辑；未知状态会返回null |
| `createHumanoidClipSet(states?,options)` | 若未指定状态则默认选择完整动作集；未知状态会被忽略 |
| `retargetClipToSkeleton(clip,target,{boneMap,strict})` | 返回映射后的剪辑；仅处理轨迹名称映射，不涉及绑定姿势或肢体长度校正 |

`A3GameMotionState`包含以下状态：IDLE、WALK、RUN、JUMP、BLOCK、PUNCH、KICK、SLASH、HIT、DEATH、AIM、SHOOT、RELOAD、DRAW。这些状态名称均为小写。A3GameHumanoidBone定义了规范骨骼名称；A3GameSourceBoneAliases列出了导入的别名；A3GAME_HUMANOID_CLIP_NAMES则列出了生成的动作剪辑名称。
autoRigHumanoid会替换静态网格模型，并可释放其原始几何数据：切勿在共享资产的分析中使用它，以免破坏原有数据。
通过maxBones参数最多可设置四个影响源；四权重存储机制不支持任意更多数量的影响源。
对于不同的静止姿势、坐标轴或骨骼比例差异，需使用离线重定向功能；严格的名称映射并不能证明兼容性。

## 12. 共享的风、水、浮力及表面流效果

### 风效

`host.setWind({velocity:[3,0,1],gustStrength:.5,gustPeriod:6,spatialScale:30,response:1.5,seed:7}, immediate=false)`。其中velocity表示顺风方向的世界坐标速度（单位：米/秒，可为数组或对象）；host会在每个模拟步骤中更新一次风场。
`A3GameWindField(config)`：可通过set(config,immediate=false)设置参数，sample(position,time?,target?)用于采样，update(dt)用于更新，getState()用于获取状态。
sample函数需要传入x/y/z坐标；getState返回的是速度、目标点、阵风信息、时间及位移数据，而非完整配置。
参数限制：heightShear默认值设为0.05；gustStrength/heightShear≥0，gustPeriod/spatialScale≥0.1，response≥0.01。该风场模型不支持障碍物影响的流体计算。`bindVegetationWind(object, host, {flexibility, maxBend, response, phase})` 会以预设的根节点为轴进行旋转；调用detach方法可恢复植被的初始姿态。
风响应计算采用公式 `1-exp(-dt/response)`；植被弯曲计算则使用公式 `1-exp(-response*dt)`。植物摆动幅度可能会略微超过maxBend设定的上限。
需将固定碰撞体单独处理；只需一次性附加效果，无需后续手动更新。

### 水面

```js
import { createWaterSurface } from '@a3game/playable';

const water = createWaterSurface({
  size: [30, 20], position: [0, 0, 0], quality: 'standard',
  terrainHeight: (x, z) => -2, waveHeight: 0.07,
});
host.add(water, 'environment');
water.userData.attachToHost(host);
```

“standard”模式采用GPU加速的解析波浪算法；“low”模式则使用受限的CPU几何计算，且会禁用平面反射/折射效果。
水面并非实体游戏地面。`terrainHeight`函数用于返回世界坐标下的底部高度；若未提供该函数，则默认深度为5米。
水面不会修改地形。`waveHeight`/振幅数值并不等同于平均水位。

| 选项 | 含义/取值范围 |
|---|---|
| size/position/quality | 平面的尺寸、位置，以及模式：standard/low |
| waves | 最多可设置四个波浪参数 `{direction:[u,v], wavelength, amplitude, speed, phase}`；方向基于水面局部坐标轴定义，speed表示波浪相位的移动速度 |
| segments | “standard”模式默认值为64，最大值为192；“low”模式默认值为24，最大值为32 |
| waveHeight/windInfluence | 振幅范围为0–20；windInfluence默认值为0.15，限定范围为0–1 |
| depth, depthResolution, terrainHeight | 深度相关参数；resolution默认值为32，取值范围为2–128 |
| normalMap, repeat, normalScale | 细节纹理设置；加载的贴图会被配置好，其偏移量也会实时动画化 |
| color, shallowColor, deepColor, absorption | 水面/深度外观参数；absorption包含三个分量 |
| roughness, opacity, envMapIntensity | 光学材质控制参数 |
| foamWidth, foamStrength, distortion | 岸边效果及折射外观参数 |
| reflection/refraction | 两者默认均为false；启用折射效果需要透视投影 |
| reflectionResolution/reflectionUpdateRate | 默认值分别为256和30（模拟Hz）；取值范围分别为64–1024和1–60 |
| current | 可为世界向量，也可为 `(position, time, target) => Vector3` 形式的函数；该参数与风效或纹理流动速度无关 |
| rippleCapacity, rippleLifetime, maxRippleStrength | 涟漪相关参数；standard模式下capacity为8，“low”模式下为4，最大值均为8 |

公开的水面`water.userData`方法：| 方法 | 功能说明 |
|---|---|
| `update(dt)` | 推进波浪/细节/涟漪效果 |
| `sampleHeight(x,z)`、`sampleNormal(x,z,target?)` | 获取世界表面的高度/法线信息 |
| `sampleDepth(x,z)`、`sampleBottom(x,z)` | 获取世界深度/底部位置；干燥区域的深度值为零 |
| `sampleVelocity(position,time?,target?)` | 获取当前流速以及垂直波浪流速；也支持传入位置和目标参数 |
| `addRipple(x,z,strength=.12,radius=1,{speed,frequency,decay}={})` | 添加涟漪效果；半径至少为0.05；若区域已被水覆盖则会直接覆盖原有内容，返回布尔值表示是否成功添加 |
| `computeBuoyancy(settings={})` | 计算浮力相关参数：受力、扭矩、浸没比例以及各采样点的结果 |
| `applyBuoyancy(body,settings={})` | 调用`body.applyForce(force, worldPoint)`来施加浮力，同时返回计算结果 |
| `refreshDepth()` | 在底部发生变化后刷新深度数据 |
| `attachToHost(host)` | 将水体绑定到宿主对象上，返回用于取消绑定的函数 |
| `getState()`、`dispose()` | 用于查看状态以及释放该类所占用的资源 |

超出覆盖范围的表面查询会返回null；在干燥地面上，`sampleVelocity`也会返回null。
浮力相关参数包括：采样点、质心、速度、角速度、体积、吃水深度、密度、重力、阻尼系数。
最多可使用64个体积相等的柱底采样点；被埋入水中的部分不会排开水体。
`applyBuoyancy`不会自动处理物体的运动，需要调用方自行实现`applyForce`逻辑。
该类并不拥有外部传入的法线贴图，水体的清理操作也不会释放该法线贴图。

世界水底的优先级为：显式指定的`terrain_entity_ids` > 参数中设置`waterTerrain=true`的实体 > 世界地面。
桥梁和屋顶不会被自动识别为水底。`SceneLoader`通过`waterSurfaces.get(water_id)`来管理这些表面。

### A3GameWaterBody

构造函数：`new A3GameWaterBody({water, object, mass=500, volume, size=[1,1,1], velocity, onEnterWater, density=1000, gravity=9.81, damping, angularDamping=1.5, groundFriction=4, fixedStep=1/120})`。
默认以物体原点作为质心，采用米/千克/秒作为单位；阻尼系数的默认值为质量乘以4。
公开方法包括：`update(dt)`、`attachToHost(host)`、`dispose()`。可获取的参数有：速度、角速度、受力、扭矩、浸没比例、是否接触地面、经过时间、是否已释放。
该类没有`getState`、`reset`、`applyForce`方法，本身也不属于`applyBuoyancy`的实体接口。
需先绑定水体再绑定物体。`fixedStep`的取值范围限制在1/240到1/30之间；每次更新时输入的`dt`会被限制在0.25秒以内。
当物体首次进入水中时，`onEnterWater`会接收到`{body, object, position, velocity, impactSpeed}`参数，而非仅在物体构造于水中时触发。
`dispose`方法只会解除绑定关系，不会释放物体或水体资源。这是一个轻量级的盒状物体模型，并非通用的刚体或船舶水动力引擎。

### 表面水流`createSurfaceFlow({preset, size, position, resolution, heightMap, initialDepth, viscosity, mobility, sources,...})`函数会返回一个Mesh。
预设类型包括岩浆/血液；position参数为`[x,y,z]`，heightMap用于返回绝对世界高度。
resolution的取值范围为4到256的整数，默认值为56；initialDepth可以是数值，也可以是`(worldX, worldZ) => number`形式的函数。
其他可选参数包括：coolingRate、yieldSlope、solidificationTemperature、thermalViscosity、referenceDepth、fixedStep、minVisibleDepth、boundary、color、roughness、emissiveIntensity。
viscosity的值至少为0.0001；mobility、coolingRate、yieldSlope、thermalViscosity均为非负数；solidificationTemperature的取值范围在[0,1)之间。

userData对象包含以下方法：update(dt)、addSource(source)、getBedGeometry()、attachToHost(host)、getState()、dispose()。
- 源数据格式为`{x, z, radius, volume, rate, duration, temperature}`，表示世界坐标下的源；其中volume为即时体积，rate的单位为体积/秒，temperature的取值范围是0到1。超出边界时会抛出异常。
- 若不指定duration则表示为持续注入；Infinity是无效值。addSource返回的stop函数仅用于停止后续的注入操作。
- 封闭边界模式下会保持体积不变；开放边界模式则会记录流出的体积。可查看massError了解相关数据。fixedStep的值为1/120；update方法没有追赶机制限制。
- getState会复制类型化数组；应避免在运行时生成完整的网格快照。getBedGeometry返回的是独立克隆的数据。
- `createSurfaceFlowTerrain(flow, materialOptions)`会创建一个独立拥有的mesh。切勿对已创建的流体对象进行变换，也不要将其重复附加到多个宿主上。
- 温度和粘度属于游戏内的系数，并非经过校准的国际单位制数值；该模块不具备完整的3D翻转/飞溅模拟功能。

## 13. 粒子、光束、轨迹和闪电特效

视觉特效仅用于反馈展示，不可作为权威的游戏命中检测依据。

```js
import { createVfxDirector, A3GameVfxPreset } from '@a3game/playable';

const vfx = createVfxDirector({
  host, seed: 7,
  presets: { dust: { ...A3GameVfxPreset.IMPACT_DUST, windResponse: 0.6 } },
});
vfx.play('dust', { position: [0, 0.1, 0], direction: [0, 1, 0], count: 12 });
```

带有host参数的createVfxDirector调用会默认进行附加操作；设置attach:false可禁用此功能。新建的A3GameVfxDirector需要手动指定附加操作。
自定义预设会覆盖工厂默认设置；可通过register或registerAll方法进行追加。
默认注册的预设名称为muzzle_flash、bullet_impact、impact_dust、blood_hit、melee_impact、shock_ring、block_spark、foot_dust，并非A3GameVfxPreset中的所有常量。未注册的预设调用play方法时返回值为0。

| 常量 | 成员 |
|---|---|
| `A3GameEmitterShape` | POINT、BOX、SPHERE、CONE、DISK、EDGE |
| `A3GameParticleAppearance` | DEFAULT、GRADIENT、CIRCULAR、RING |
| `A3GameParticleBlending` | NORMAL、ADDITIVE、MULTIPLY |
| `A3GameParticleRenderMode` | BILLBOARD、STRETCHED、MESH |
| `A3GameVfxPreset` | MUZZLE_FLASH、BULLET_IMPACT、IMPACT_DUST、BLOOD_HIT、MELEE_IMPACT、SHOCK_RING、BLOCK_SPARK、FOOT_DUST、LIGHT_ARROW_CORE、LIGHT_ARROW_MOTES、LIGHT_ARROW_IMPACT、BLADE_SLASH、PICKUP_SPARKLE、SMOKE_PLUME、EXPLOSION、FIRE_PLUME、TYRE_SMOKE、SCRAPE_SPARK、BOOST_FLAME |

### 粒子系统`new A3GameParticleSystem(config={})`；其公共方法包括start、stop、clear、emit、burst、update、attachToHost、getState、dispose。
emit(count=1, options={})会返回实际发射的粒子数量；burst的默认值等于粒子池容量。update(dt, camera=null)用于推进粒子模拟。

| 配置分组 | 字段 |
|---|---|
| 粒子池与生命周期 | maxParticles、lifetime、size、sizeOverLife、opacityOverLife、seed |
| 外观属性 | colorStart、colorEnd、intensity、appearance、blending、map、renderMode、geometry、material、depthTest、renderOrder、name |
| 运动参数 | speed、direction、gravity、drag、turbulence、windResponse、windField、rotation、rotationSpeed、stretchBySpeed、orientToDirection |
| 发射器设置 | position、emitterShape、emitterRadius、emitterAngle、emitterHeight、emitterDirection、emitterSize、surfaceOnly、startPositionAsDirection |
| 连续发射配置 | emissionOverTime、looping、autoStart |

单次发射时可覆盖的参数：position、direction、spread、speed、size、lifetime、colorStart、colorEnd、scale。
- 这些参数的取值范围为标量或端点值，而非曲线；scale会影响偏移量、尺寸和速度，不会影响生命周期。
- windResponse的默认值为0（单位：1/s）；SMOKE_PLUME和FIRE_PLUME类型的效果会启用该参数。当粒子池被填满时新粒子会被覆盖；totalEmitted的数值与activeCount不同。
- stop方法会保留仍在存活的粒子；clear不会停止发射过程；当looping设为false时，系统在首次有效更新后就会停止发射。
- 若指定了direction，当spread=0时会回退为0.45。
- attachToHost不会自动插入object3D对象；需手动添加或使用director组件。系统销毁时会同时释放自定义的geometry/material资源。

### Director、光束与拖尾效果

| 类 | 公共接口 |
|---|---|
| `A3GameVfxDirector({host, root='effects', seed, scale=1})` | register(name, config)、registerAll(presets)、get(name)、play(name, options)、follow(name, target, options)、registerBeam(name, options)、fireBeam(name, from, to, options)、update(dt, camera)、attachToHost(host)、getState()、dispose() |
| `A3GameBeamEffect({count=8, color, lifetime=.08, blending, name})` | fire(from, to, {lifetime, color})、update(dt)、getState()、dispose() |
| `A3GameTrailRibbon({segments=24, width=.09, color, endColor, opacity=.9, taper=true, blending, name})` | reset(position?)、push(position, camera=null)、dispose() |

- register和registerBeam方法会复用已存在的名称，无需重新配置。
- follow(name, target, {offset, rate})会返回`{stop}`；其中offset为世界坐标系下的偏移量。一个系统仅共享一个emitterPosition；未挂载父级且非摄像机的目标物体将停止跟随。
- 光束使用x/y/z坐标端点，会覆盖整个粒子池；目前不支持可配置的粗线条宽度设置。
- 拖尾效果需要手动调用push方法；历史记录统计的是世界坐标系下的采样点数量，而非时间。该类没有update、attachToHost、getState方法。
- 对齐效果需与世界法线匹配；系统销毁时需取消相关订阅。

`createLightningArc({from, to, segments, period, seed, width, color})`会返回一个Group对象。
端点为数组形式，线段数量限制在4到64之间；userData字段可用于定义update、attachToHost、getState、dispose方法。
在形状或闪烁效果变化时，端点位置保持不变；风效不会影响闪电弧线的移动。

## 14. 碰撞与角色运动`A3GameCollisionProbe`是一款简化的静态几何碰撞求解器，并非通用物理引擎。
默认参数：targets=[]、radius=0.4、stepHeight=0.6、groundOffset=0、gravity=-18、maxFallSpeed=-40。
`setTargets(targets=[])`、`addTarget(target)`、`removeTarget(target)`方法会返回该探测器的实例。构造函数与`setTargets`方法会直接复制传入的数组。
后续修改`SceneLoader`中的碰撞体数组时，并不会自动更新探测器。
`resolveEntityId(object)`方法会沿着父级对象向上查找`a3game.entityId`或`a3gameWorldEntity.entityId`；若未找到则返回空字符串。

| 查询类型 | 函数签名 |
|---|---|
| 地面检测 | sampleGround(position,{maxDrop,probeHeight,ignore,targets}) |
| 滑动移动计算 | resolveMove(position,displacement,{height,radius,ignore,targets}) |
| 重力/跳跃处理 | stepCharacter(state,displacement,dt,{height,radius,jump,jumpImpulse,ignore,targets}) |
| 射线检测 | hitscan(origin,direction,{range,ignore,targets}) |
| 区域重叠检测 | overlapSphere(center,radius,{targets,ignore,requireEntityId}) |
| 连续扫描检测 | sweepSphere(from,to,{radius,ignore,targets}) |

`state`是持久化状态，包含`{position:Vector3, velocityY, grounded}`，其中`position`表示脚部位置；`stepCharacter`会修改该状态。
`displacement`指的是移动步长，而非速度。`resolveMove`会返回移动结果（可移动/被阻挡/正常移动/接触信息）；需手动应用移动结果。

```js
collision.stepCharacter(motion, displacement, dt, {
  height: 1.8, radius: 0.35, jump: inputFrame.jump, ignore: [player],
});
player.updateMatrixWorld(true);
```

- 需忽略移动实体自身的根节点，同时排除装饰性部件。在同一帧内进行查询前需先更新`matrixWorld`，修改几何形状后需设置`needsUpdate`。
- `hitscan`会返回命中信息、交点、法线、物体、距离以及`entityId`。`overlapSphere`仅检测边界/标记点，并非精确网格碰撞；`ignore`参数会匹配实际的目标对象。
- `sweepSphere`会检测静态面、边缘、顶点及实例；返回结果包含中心点、交点、法线、距离、碰撞发生时间以及穿透深度。若未命中，则距离为无穷大、TOI为Infinity。
  网格属于表面，并非实心体积；即使不可见的几何结构也会产生碰撞，且重写射线检测逻辑也无法绕过扫描检测。
- 角色移动采用带滑动和天花板检测功能的球体碰撞模型。系统不支持自动攀爬、堆叠、关节模拟或完整的移动平台动力学功能。
  `stepHeight`用于控制地面探测高度。请使用简单的碰撞体，而非动画皮肤。

## 15. HUD与可观测状态

可复用`context.hud`，也可仅实例化一次`new A3GameHudLayer({container})`。
锚点类型包括：左上、上中、右上、居中、左下、下中、右下；同一锚点下的控件会垂直堆叠。| API | 功能说明 |
|---|---|
| addText/addPanel(name,{anchor,value,className}) | 将参数值序列化为字符串；返回HTMLElement元素 |
| addBanner(name,{anchor,value,visible}) | 生成结果/公告横幅；返回HTMLElement元素 |
| addBar(name,{anchor,value,label}) | 将归一化后的值限制在0–1区间；返回HTMLElement元素 |
| addCrosshair(name='crosshair') | 生成居中十字准星 |
| setValue(name,value), setValues(values) | 更新单个或多个控件 |
| setVisible(name,visible), remove(name) | 显示/隐藏/移除指定名称的控件 |
| autoHide(name,{host,after=6,fade=.8}) | 可取消的延迟淡出效果 |
| getState(), dispose() | 获取可观察的控件状态并执行清理操作 |

```js
hud.addPanel('controls', { anchor: 'bottom-left', value: 'WASD键控制移动' });
const cancelHide = hud.autoHide('controls', { host, after: 4, fade: 0.6 });
```

若要实现确定的淡出效果，需传入host参数：该参数会用于明确的渲染帧间隔计算；若未提供host，则使用系统时钟时间。
after和fade参数必须为有限的非负秒数。setVisible会取消淡出效果；设置为true可恢复控件不透明度；remove/dispose会取消待执行的任务。
建议通过检查getState以及data-a3game-value/data-a3game-visible属性来确认状态，而非依赖光学字符识别技术。
在目标视口尺寸下，应保持HUD内容简洁且易于阅读。切勿为了让录制画面看起来更完美而隐藏游戏UI。

## 16. 测试执行、录制与证据留存

### 测试与权限管理

测试时需使用Node宿主模拟对象、真实的碰撞器、随机种子、时间步长以及明确的ID/序列号。测试范围需覆盖实体生成/重置、自身碰撞检测、速度/帧率变化、输入所有权、备用方案及清理逻辑；同时需验证状态与事件是否符合预期。此外还需单独验证开发环境/生产环境下的浏览器启动、帧渲染、遮挡处理及路由逻辑。

`testing.run_automation_tests`：基于vitest/playwright框架；对应脚本为test/test:e2e；可通过-t/--grep参数过滤测试项。
测试报告默认保存为`.a3game/reports/vitest-report.json`或playwright-report.json。
可查看matched_count、passed_count、failed_count、skipped_count、cases、failed_cases以及命令执行状态等信息。
缺失、过期、格式错误、内容为空或执行失败的报告会被判定为无效，但**全部跳过项的报告或非零/超时命令仍可能返回ok=True**。
测试需满足执行成功、实际通过用例数与预期一致且覆盖率达标等要求；截图、就绪状态检查及预演结果均不计入基准测试结果。

### 声明的游戏玩法计划

通过`globalThis.__A3GAME_GAME__ = game`暴露宿主、输入设备及getState接口；返回可序列化的游戏玩法状态，而非THREE图形对象。

```js
  warmup: 1, look: 'off',
  actions: [
    { id: 'approach', keys: ['KeyW'], duration: 2 },
    { id: 'interact', taps: ['KeyE'], duration: 0.5 },
    { id: 'observe', duration: 1 },
  ],
};
```

需使用实际的绑定逻辑。执行流程为：先读取声明的计划 → 匹配actionBindings/keyBindings → 映射到DOM元素 → 若无匹配则使用备用方案；声明的操作也可能是函数形式。
外部传入的action_plan为包含数组或`{actions,sustained,warmup,look}`结构的JSON路径；应使用sustained参数，而非仅用于声明的hold别名。| 字段/规则 | 行为说明 |
|---|---|
| keys / taps / hold | keys会占用对应插槽；taps会在同一帧内同时触发；当hold:true时，会将taps/鼠标操作延续到插槽结束 |
| 冲突规则 | 不存在keys/taps或持续操作与taps重叠的情况；重复的独立操作需要占用不同的插槽 |
| mouse / click | 主指针/DOM选择器 |
| duration / seconds | 必须为正数；会对累积的时间边界进行取整处理；拒绝亚帧级别的操作 |
| 预算分配 | 未指定持续时间的操作会共享剩余时间；短计划会补充空闲时间；若超出预算则需设置allow-partial-plan参数 |
| sustained | 从预热阶段开始生效；对于仅用于捕获的操作，每次动作中需重复输入对应的keys |
| look | 可选值为off/pan/auto；false/‘false’表示关闭；拖拽或无模式场景下auto会被设为关闭状态，否则会通过input.setLook实现受限的平移操作 |

需保证探测帧率/最终帧率保持一致。需覆盖移动车辆的整个尾部区域；空闲并不等同于车辆停止。
需演示真实的输入操作，而非瞬移、碰撞绕过或虚构的状态。

### 命令行工具、Python封装、模式与媒体相关说明

默认分辨率为1280×720，帧率为20fps，录制时长为14秒。可通过--duration/--fps/--width/--height参数设置参数；建议使用正的偶数维度值。
为保证Python环境与命令行工具的使用一致性，建议选择正整数作为帧率；命令行工具会验证帧率是否为正有限值，Python环境也会强制要求帧率为整数。
其他可选参数包括：--action-plan/--hold/--warmup/--look/--playwright-root/--browser-executable/--source-hash/--self-test。
source-hash是一个不透明的标签，会被记录为source_hash；录制器不会计算或验证其对应的源内容。

| 模式/参数 | 行为说明 |
|---|---|
| --mode gameplay | 默认模式：执行输入计划 |
| --mode overview | 模拟游戏运行流程但不执行输入计划；可选择性应用相机预览钩子 |
| --allow-partial-plan | 显式前缀/探测捕获模式；会录制未执行的动作/帧；不能作为完整计划的凭证 |
| --preview / --poster | 仅捕获PNG格式的画面；不会进行计划解析、预滚动或视频编码 |
| --self-test | 仅用于验证录制器的自身契约，并非游戏性能基准测试 |

可选的`__A3GAME_REVIEW__({mode,time,frame,dt,duration})`会在每帧更新后同步运行；仅能调整相机参数，且不会返回等待中的/序列化的结果。
概览模式下需将look设为off；若未设置对应钩子则会发出警告并保留游戏相机设置。预览模式仅会执行明确的预热流程，随后返回preview_completed标识。

Python接口的参数说明：第2节中，warmup/look=None时会继承原有计划；设置为0/False则会覆盖原有设定。source_hash应为非空字符串或None。
playwright_root目录下必须包含node_modules/playwright；其他可覆盖的环境参数包括browser_executable/browsers_path/library_path/ffmpeg。
超时时间默认为900秒。需保留URL中的结尾斜杠。payload.output_dir对应BASE目录，take_dir为新生成的录像文件目录，report_path为最后一次输出的stdout JSON路径（试运行模式下该值为None）。
需验证录像文件中新生成的录像路径、源标签、模式/URL信息、浏览器错误信息以及视频元数据是否合规；严禁复用BASE目录下的/report.json文件。预览模式会单独验证PNG文件的有效性。

### 录制时间与输出规范__A3GAME_RECORDING__会停止已发布的循环；每个输出帧通过内部固定步长或有界外部步长来推进1/fps。
请检查初始/高级模拟时间以及dropped_seconds；墙钟时间并非模拟时间，也不代表实时性能。
快照会保留共享引用，并标记循环/THREE对象；非有限数值会被转换为null。
限制条件：深度为8，预算为2048，每个对象或数组最多128个条目，字符串最多512个字符；它并非无损状态转储。

| 证据 | 约定 |
|---|---|
| 目录 | 在BASE下生成新的唯一条目；保留先前的证据 |
| 视频文件 | report.json、manifest.json、init.png、poster.png、frames/fNNNNNN.jpg、video.mp4 |
| 预览 | png_frames=1，无视频；状态为preview_completed |
| 路径 | 报告/stdout为绝对路径；所有manifest中的媒体/报告路径均相对于BASE |
| 完成 | MP4文件需经ffprobe验证其帧数、大小、fps和时长，且无页面错误；只有此类文件才会更新BASE/manifest.json |
| 游戏玩法 | 检查executed_actions、unexecuted_actions、partial_plan以及实际的游戏状态进展 |
| 播放 | 测试目标浏览器支持的编解码器；若H.264不可用，则提供WebM格式 |

### 流水线集成边界

并非所有mode、preview、source_hash选项都会被传递。如需使用声明的计划默认值，请选用适配器。
recorder_root对应Playwright根目录、root/browsers、root/deps/lib。

UI视口是尺寸为正的对象/键值对，并非自动捕获。`gamefactory3a.ui_screenshot_plan.v1`会验证声明的屏幕，而非渲染后的视口覆盖范围。
该机制要求具备schema_version、正的contract_version、匹配的游戏模块、非空的state/events/commands，以及包含public_api_paths的工作区。

## 17. 清理与交付检查

1. 禁用输入；取消订阅动作、管道、时钟事件、渲染及动画回调。
2. runtime.deinitialize会断开通道并释放会话实体；避免重复释放。
3. 先释放World/HUD/VFX/水体/动画资源，然后等待assets.dispose完成，再释放宿主资源。

`disposeObject3D(root)`会调用userData.dispose，分离/清空根节点，并根据资产所有权标记来释放资源。
它并非通用的引用计数器。分离操作并不等同于GPU资源清理；仅在相关使用者不再使用后，才释放共享资源。

交付检查项包括：公共导入项、生产环境启动、资源路径/回退机制、视觉与碰撞体一致性、输入/dt/序列、
摄像头/UI、最新的报告、完整的计划以及可播放的媒体。

## 18. 完整的JavaScript导出与源映射

以下索引涵盖了来自`engine_adapters/three_js/plugin/A3GamePlayable/src/index.js`的所有108个命名导出项。
生成的导入路径应设为`@a3game/playable`；正常游戏运行无需额外的打包子路径。| 分组 | 根导出项 |
|---|---|
| 版本/启动 | `A3GAME_PLAYABLE_API_VERSION`、`A3GAME_PLAYABLE_ENGINE`、`bootA3GameRuntime` |
| 数据线相关 | `A3GameControlMode`、`A3GameLocomotionState`、`A3GameRuntimeCommand`、`createControlBinding`、`createControllerState`、`createEntitySnapshot`、`createEntitySpawnRequest`、`createParticipantInfo`、`createRuntimeInputState`、`createTransform`、`createVector3`、`locomotionStateFromInput` |
| 接口 | `A3GameControllableEntity`、`A3GameEntityFactory`、`A3GameRuntimeMessageHandler`、`CONTROLLABLE_ENTITY_METHODS`、`ENTITY_FACTORY_METHODS`、`RUNTIME_MESSAGE_HANDLER_METHODS`、`assertControllableEntity`、`assertEntityFactory`、`assertRuntimeMessageHandler`、`isControllableEntity`、`isEntityFactory`、`isRuntimeMessageHandler` |
| 组件/会话 | `A3GAME_USER_DATA_KEY`、`A3GameIdentityComponent`、`A3GameRuntimeEntityComponent`、`A3GameRuntimeSubsystem`、`A3GameWorldSessionSubsystem` |
| 运行时系统 | `A3GameRuntimeHost`、`A3GameEnvironmentPreset`、`A3GameAssetLibrary`、`A3GameSceneLoader`、`A3GameInputRouter`、`A3GameLookMode`、`DEFAULT_KEY_BINDINGS`、`A3GameCinematicPlayer`、`A3GameRuntimeChannel`、`A3GameHudLayer`、`A3GameCollisionProbe`、`resolveEntityId`、`disposeObject3D` |
| 布局相关 | `directionToYaw`、`yawToDirection`、`footprintCorners`、`distanceToPolyline`、`createGroundRibbon`、`createFacadeTexture` |
| 模型/材质工具 | `A3GAME_RUNTIME_FORWARD_AXIS`、`A3GameForwardAxis`、`A3GameMaterialPreset`、`A3GameSurfacePattern`、`alignWeaponModel`、`measureWeapon`、`principalAxes`、`measureObject`、`fitToHeight`、`groundObject`、`forwardAxisYaw`、`orientModel`、`prepareModel` |
| 视觉构建 | `createCloudLayer`、`createContactShadow`、`createDistantRange`、`createFillLight`、`createInstancedFromModel`、`createMaterial`、`createRadialGradientTexture`、`createRoundedBox`、`createSeededRandom`、`createSkyGradient`、`createSunLight`、`createSurfaceMaterial`、`createSurfaceTextures`、`createTilingTexture`、`createWaterSurface` |
| 运动相关 | `A3GAME_HUMANOID_CLIP_NAMES`、`A3GameHumanoidBone`、`A3GameMotionState`、`A3GameSourceBoneAliases`、`A3GameAnimationDirector`、`A3GameMotionLibrary`、`autoRigHumanoid`、`createAnimatedActor`、`createHumanoidClip`、`createHumanoidClipSet`、`createHumanoidSkeleton`、`findRiggedHumanoid`、`measureHumanoid`、`retargetClipToSkeleton` |
| 风/流体相关 | `A3GameWindField`、`bindVegetationWind`、`A3GameWaterBody`、`createSurfaceFlow`、`createSurfaceFlowTerrain`、`createLightningArc` |
| 视觉效果(VFX) | `A3GameEmitterShape`、`A3GameParticleAppearance`、`A3GameParticleBlending`、`A3GameParticleRenderMode`、`A3GameVfxPreset`、`A3GameParticleSystem`、`A3GameBeamEffect`、`A3GameTrailRibbon`、`A3GameVfxDirector`、`createVfxDirector` |

### 实现查找| 路径 | 功能/用途 |
|---|---|
| `engine_adapters/three_js/__init__.py`、`engine_adapters/three_js/three_client.py`、`engine_adapters/three_js/config.py`、`engine_adapters/three_js/contracts/` | Python入口文件、命名空间构建、配置设置、操作封装 |
| `engine_adapters/three_js/project/client.py`、`engine_adapters/three_js/plugin/client.py`、`engine_adapters/three_js/build/client.py`、`engine_adapters/three_js/runtime/client.py` | 项目/包/构建/服务器相关工作流程 |
| `engine_adapters/three_js/runtime/sessions.py`、`engine_adapters/three_js/observe/client.py` | Python会话传递与就绪状态检查 |
| `engine_adapters/three_js/assets/client.py`、`engine_adapters/three_js/bindings/client.py`、`engine_adapters/three_js/animation/client.py`、`engine_adapters/three_js/reflection/client.py`、`engine_adapters/three_js/preview/client.py` | 源文件导入、绑定处理、兼容性适配、元数据管理、CPU预览功能 |
| `engine_adapters/three_js/world/client.py` | 草稿/构建/验证/发布流程的接口层；需参考其内部的模式实现来了解序列化字段的限制，不可作为公共导入项使用 |
| `engine_adapters/three_js/plugin/A3GamePlayable/src/index.js`、`engine_adapters/three_js/plugin/A3GamePlayable/package.json` | 运行时导出、初始化引导、支持的包/版本协议定义 |
| `engine_adapters/three_js/plugin/A3GamePlayable/src/data-types/runtime-types.js`、`engine_adapters/three_js/plugin/A3GamePlayable/src/interfaces/contracts.js` | 数据记录结构与动态类型协议定义 |
| `engine_adapters/three_js/plugin/A3GamePlayable/src/components/`、`engine_adapters/three_js/plugin/A3GamePlayable/src/subsystems/` | 身份标识、输入状态组件、实体/会话生命周期管理 |
| `engine_adapters/three_js/plugin/A3GamePlayable/src/engine/runtime-host.js`、`engine_adapters/three_js/plugin/A3GamePlayable/src/engine/runtime-channel.js` | 渲染器调度与指令传输逻辑 |
| `engine_adapters/three_js/plugin/A3GamePlayable/src/engine/asset-library.js`、`engine_adapters/three_js/plugin/A3GamePlayable/src/engine/scene-loader.js`、`engine_adapters/three_js/plugin/A3GamePlayable/src/engine/scene-kit.js` | 运行时资源管理、场景加载、通用布局辅助工具 |
| `engine_adapters/three_js/plugin/A3GamePlayable/src/engine/visual-kit.js`、`engine_adapters/three_js/plugin/A3GamePlayable/src/engine/wind-field.js`、`engine_adapters/three_js/plugin/A3GamePlayable/src/engine/water-body.js`、`engine_adapters/three_js/plugin/A3GamePlayable/src/engine/surface-flow.js` | 材质、天空、水体、风场、流体效果的实现限制说明 |
| `engine_adapters/three_js/plugin/A3GamePlayable/src/engine/motion-kit.js`、`engine_adapters/three_js/plugin/A3GamePlayable/src/engine/animation-director.js` | 骨骼绑定/动作处理及混合控制逻辑 || `engine_adapters/three_js/plugin/A3GamePlayable/src/engine/vfx-kit.js`、`engine_adapters/three_js/plugin/A3GamePlayable/src/engine/lightning-effect.js`、`engine_adapters/three_js/plugin/A3GamePlayable/src/engine/collision-probe.js`、`engine_adapters/three_js/plugin/A3GamePlayable/src/engine/input-router.js`、`engine_adapters/three_js/plugin/A3GamePlayable/src/engine/hud-layer.js` | 特效、查询、输入、用户界面 |
| `engine_adapters/three_js/plugin/A3GamePlayable/tests/*.spec.js`、`engine_adapters/three_js/plugin/A3GamePlayable/vitest.config.js` | 框架回归测试依据；配置文件还包含选定的示例测试 |
| `engine_adapters/three_js/plugin/A3GamePlayable/tests/realism.html`、`engine_adapters/three_js/plugin/A3GamePlayable/tests/wind-fluid.html`、`engine_adapters/three_js/plugin/A3GamePlayable/tests/wind-fluid-demo.js` | 用于验证光照、水体、风效及表面流动等真实WebGL效果的参考浏览器测试环境；不属于Vitest测试范畴 |
| `engine_adapters/three_js/cli.py` | 公共Python命令行工具，支持create-project、import-asset、run等子命令 |
| `engine_adapters/three_js/import_generated/import_mesh.mjs` | Node环境下的GLTFLoader检查工具，不用于暂存区或注册表导入操作 |
| `engine_adapters/three_js/examples/` | 只读示例：fps-example、arena-fighter-example、racing-example、explorer-example、motion-vfx-example |

网格检查工具参数说明：--source、--usage用于指定资源类型，可选值包括asset、vfx_standalone、vfx_particle；也可选用--report或--draco-decoder参数。该工具无需更新暂存区或注册表即可报告资源的可加载性、几何结构、材质、纹理、动画、边界及资源占用情况。
安装脚本位于`scripts/engine_install/three_js/`目录下，而非`scripts/three_js/`目录。需验证包装器的当前工作目录及运行环境；确保仓库根目录可被正常导入。

### 覆盖率维护
API变更后，需将Python公共方法与JS根导出项与第2节、第18节内容进行对比。需同步更新函数签名、接口约定、限制条件及索引信息；实现算法及调研历史内容无需纳入更新范围。
