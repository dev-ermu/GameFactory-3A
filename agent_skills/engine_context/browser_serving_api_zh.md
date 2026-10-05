# 浏览器服务代理API参考

状态：已实现的浏览器服务API版本为`v1`。

本文档是已实现的公共功能的简明索引，仅列出了公共名称及其功能。如需了解具体的参数、路由或结果数据字段，请查阅当前源代码。

## 浏览器/后端API边界

浏览器服务是一种与引擎无关的浏览器映射层：

```text
浏览器UI -> 浏览器服务API -> EngineBackend -> 引擎客户端 -> 引擎
```

浏览器UI以及生成的Browser Play源码不得直接导入具体的后端、直接调用引擎客户端，或根据引擎名称进行分支判断。已注册的后端和网关组合根节点只能通过其公共客户端来访问UE5和Unity：

```python
from engine_adapters.ue5 import UEClient
from engine_adapters.unity3d import UnityClient
```

允许的调用方向如下：

```text
Browser Play HTTP/fetch
    -> 浏览器服务网关
        -> 已注册的EngineBackend
            -> 公共引擎客户端
                -> 引擎运行时
```

Browser Play绝不会实例化`EngineBackend`、`UEClient`或`UnityClient`。特定游戏的后端或录制预设应属于负责注册该后端的执行组合根节点，而非放在生成的Browser Play代码或`<REPO_PATH>/engine_adapters/*/examples`目录下。

浏览器服务提供引擎视图、资源、World、会话、流以及通用输入功能，但它无法替代引擎原生的Mechanic UI。

## 结果约定

公共操作会返回包含以下稳定字段、可序列化为JSON的结果：

- `ok`：表示该操作是否成功完成；
- `operation`：稳定的操作标识符；
- `engine`：所选后端的标识符；
- `artifacts`：生成或检测到的产物；
- `warnings`：非致命性问题；
- `errors`：致命性问题；
- `payload`：特定操作的结果数据。

## 公共入口点及所有权

Python代理从以下路径导入公共API：

```python
from engine_adapters.browser_serving import BrowserServingClient
```

`BrowserServingClient`是用于管理、执行和集成工具的主机端Python客户端。浏览器端的JavaScript使用的是文档中说明的HTTP路由，不会导入该Python客户端。- `API_VERSION`：返回公开的浏览器服务API版本。
- `BrowserServingClient`：调用公开的浏览器服务HTTP API。
- `BrowserServingConfig`：解析网关、管理员、引擎、流、上传以及会话相关的配置。
- `BrowserServingService`：网关/服务组合API，会将操作委托给已注册的引擎后端。它并非生成的Browser Play依赖项。
- `CgVideoGateway`：将标准化的CG视频任务加入队列，并记录其生成的产物。
- `CgVideoGatewayProtocol`：CG视频任务网关的注入契约。
- `CgVideoError`：报告被拒绝或失败的CG视频请求。
- `EngineBackend`：由网关组合根节点实现并注册的协议。生成的Browser Play会将其视为不透明对象。
- `EngineCapabilities`：声明浏览器端支持的能力。
- `EngineDescriptor`：描述已注册的后端。
- `AssetImportRequest`：将暂存的任务产物传递给后端。
- `StagedUpload`：描述以标准化任务产物形式呈现的浏览器上传内容。
- `AssetRecord`：描述与引擎无关的已导入资产。
- `WorldRecord`：描述与引擎无关的运行时世界。
- `BrowserServingError`：公开的浏览器服务错误基类。
- `UnknownEngineError`：报告未注册的引擎标识符。
- `EngineCapabilityError`：报告后端不支持的操作。
- `create_app`：创建浏览器服务FastAPI网关。

## 客户端

- `client.health`：报告网关就绪状态以及已注册的引擎信息。
- `client.engines`：列出引擎描述符及能力。
- `client.engine_status`：报告某个后端的就绪状态。

## 资产

- `client.assets.upload`：将上传的文件暂存为标准化任务产物，并通过选定的后端导入。
- `client.assets.import_descriptor`：通过选定的后端导入已有的生成任务产物。
- `client.assets.list`：列出后端可见的资产。
- `client.assets.groups`：按与引擎无关的资产类型对资产进行分组。
- `client.assets.inspect`：检查某个已导入的产物。

上传操作会使用`pipeline.common.paths`。跨引擎使用者通过`artifact_id`来选择资产；后端原生路径仅作为元数据存在。

## 世界

- `client.worlds.upload`：暂存场景文件，并触发后端世界的构建/发布流程。
- `client.worlds.list`：列出后端可见的运行时世界包。

## 会话- `client.sessions.create`：启动由浏览器端控制的引擎/流会话。
- `client.sessions.list`：列出活跃的会话。
- `client.sessions.get`：读取某个会话的信息。
- `client.sessions.recover`：重新注册仍可访问的会话。
- `client.sessions.catalog`：列出可运行的虚拟形象、动作和场景。
- `client.sessions.configure`：选择虚拟形象、闲置动作、移动动作以及角色选项。
- `client.sessions.play_preview_animation`：播放预览动作。
- `client.sessions.load_world`：选择要运行的场景。
- `client.sessions.join`：进入游玩模式。
- `client.sessions.leave`：退出游玩模式。
- `client.sessions.apply_input`：发送经过标准化的移动、视角、奔跑及跳跃输入指令。
- `client.sessions.apply_preview_camera`：发送预览摄像头的输入指令。
- `client.sessions.stop`：停止引擎会话及流传输。

## CG视频相关接口

- `client.cg_video.generate`：根据代码库任务标识将CG视频生成任务加入队列，并返回请求ID。
- `client.cg_video.status`：读取已排队、正在运行、已完成或失败的任务状态。

该请求会解析`test_data/test_samples/<game_id>/cg_video/cg_tasks.jsonl`文件，且不会接收来自浏览器的提示词或凭证信息。生成的视频片段会存储在标准的CG视频输出目录下，并通过网关控制的媒体URL对外提供访问。

请求体中包含`game_id`、`task_id`、可选的`run_id`、`backend`、`engine`、`session_id`、`trigger_id`、`idempotency_key`、`options`和`playback`字段。响应中会返回任务状态（`queued`、`running`、`ready`或`failed`）；若任务状态为`ready`，响应中还会包含`video.artifact_id`、`video.media_type`和`video.url`，这些值与`artifacts`中列出的公共描述符一致。

`(game_id, task_id)`用于唯一标识视频片段，对应的`cg_tasks.jsonl`行会定义该片段的相关信息。因此`generate`接口在生成新片段前会先查找已存储的对应产物：若已有正在处理的同任务请求，新请求会加入该任务；若已存在定义匹配的成品片段，首次响应就会直接返回`ready`状态，且无需调用GPU进行渲染。即便命中已有产物，接口仍会返回HTTP 202状态码，并在响应中显示*已存储的*`run_id`和`video.artifact_id`。匹配过程会比较实际值，因为`meta.json`中记录的是默认值之后的设定，且本地生成过程不具备确定性，所以只有复用已有产物才能得到相同的视频片段。只有当`meta.json`中记录了真实的生成记录（`model_call.runtime`）时，已存储的产物才会被认定为命中结果，因此替代性产物的输出不会被返回。`options.reuse: false`会强制触发生成流程，而指定的`run_id`会将查找范围限定为单次运行任务。

特定游戏相关的操作仍由生成的Mechanic合约负责管理。

## 浏览器HTTP API

浏览器端的游玩功能调用的是网关HTTP API，而非导入Python客户端或引擎客户端。公共路由直接对应上述的客户端操作：- `GET /api/health`：用于报告网关的就绪状态。
- `GET /api/engines`：列出已注册的引擎及其功能。
- `GET /api/engines/{engine}/capabilities`：读取某个引擎的能力集。
- `GET /api/engines/{engine}/status`：读取某个后端服务的就绪状态。
- `POST /api/assets/upload`：上传并导入资产。
- `POST /api/assets/import`：导入生成的制品描述符。
- `GET /api/assets`：列出所有资产。
- `GET /api/assets/groups`：按类型对资产进行分组。
- `POST /api/assets/inspect`：检查某项资产。
- `GET /api/worlds`：列出正在运行的World实例。
- `POST /api/sessions`：创建一个会话。
- `GET /api/sessions`：列出所有会话。
- `GET /api/sessions/catalog`：列出可运行的资产和World实例。
- `POST /api/sessions/recover`：恢复会话快照。
- `POST /api/sessions/runtime-event`：将引擎就绪状态或运行时事件应用到会话中。
- `GET /api/sessions/{session_id}`：读取指定会话的信息。
- `POST /api/sessions/{session_id}/character`：配置会话中的角色。
- `POST /api/sessions/{session_id}/preview-animation`：播放动画预览。
- `POST /api/sessions/{session_id}/load-world`：为会话选择指定的World实例。
- `POST /api/sessions/{session_id}/join`：进入游玩模式。
- `POST /api/sessions/{session_id}/leave`：退出游玩模式。
- `POST /api/sessions/{session_id}/input`：应用标准化后的输入指令。
- `POST /api/sessions/{session_id}/preview-camera`：应用预览摄像机的输入指令。
- `DELETE /api/sessions/{session_id}`：终止指定会话。
- `WS /api/sessions/{session_id}/input-ws`：流式传输标准化后的输入数据。
- `POST /api/cg-video`：排队处理一个CG视频生成任务。
- `GET /api/cg-video/{request_id}`：查看CG视频任务的执行状态。
- `GET /api/media/cg-video/{artifact_id}`：流式传输已生成的MP4格式制品。

HTTP响应结果遵循上述的Result Contract规范。浏览器代码会从`payload`字段中读取操作数据，从会话的`payload.stream_url`字段中获取可播放的引擎URL。

## 能力与流

- `asset_upload`：后端支持通过浏览器上传资产。
- `asset_import`：后端支持导入生成的任务描述符。
- `asset_inspection`：后端提供已导入资产的检查功能。
- `world_build`：后端支持World实例的构建或发布。
- `world_catalog`：后端可列出正在运行的World实例。
- `runtime_sessions`：后端支持浏览器创建的会话。
- `skeletal_animation`：后端支持角色/动画的选择功能。
- `streaming`：后端会返回可供浏览器嵌入的`stream_url`。
- `pixel_streaming`：后端提供与UE兼容的Pixel Streaming功能。
- `preview_camera`：后端可接受预览摄像机的控制指令。

浏览器UI根据能力而非引擎名称来启用对应功能。浏览器游玩功能会调用`stream_url`；特定传输方式的URL别名并不属于跨引擎的通用规范。虽然可以将`engine`作为参数来指定后端，但基于特定引擎的UI逻辑并不被允许。实际选择已注册的后端服务的是网关，而非浏览器页面。

## EngineBackend合约这是网关组合根的后端实现契约，并非由浏览器播放代码生成、实现或导入的API。

- `descriptor`：返回后端身份与功能。
- `status`：报告后端就绪状态。
- `import_asset`：导入已暂存的资源。
- `inspect_asset`：查看单个资源的详情。
- `list_assets`：列出所有资源。
- `list_worlds`：列出运行时的世界实例。
- `build_world`：构建或发布一个世界实例。
- `create_session`：创建一个引擎/浏览器会话。
- `list_sessions`：列出所有会话。
- `get_session`：读取某个会话的信息。
- `recover_session`：恢复某个会话。
- `session_catalog`：列出运行时可用的资源和世界实例。
- `configure_session`：配置会话中的角色参数。
- `play_preview_animation`：播放预览动画。
- `load_world`：选择要加载的世界实例。
- `join_world`：进入播放模式。
- `leave_world`：退出播放模式。
- `apply_input`：应用标准化后的输入指令。
- `apply_preview_camera`：应用预览摄像头的输入数据。
- `handle_runtime_event`：处理引擎就绪状态及相关运行时事件。
- `stop_session`：停止某个会话及其关联进程。
- `debug`：运行支持的开发者调试功能，但不会将引擎内部信息暴露给前端代码。

## 内置后端

- `create_ue5_example_backend`：创建UE5后端，将操作映射到`UEClient`，并通过`stream_url`提供UE像素流服务。
- `create_unity3d_example_backend`：创建Unity3D后端，将操作映射到`UnityClient`，并通过`stream_url`提供Unity WebGL页面。

UE5会话采用像素流技术，通过UE运行时会话传递标准化输入指令。Unity浏览器会话则使用`runtime_kind=unity_webgl`、`streaming_transport=unity_webgl_http`以及`input_transport=browser_canvas`；键盘和指针事件会直接传递给Unity画布，而非通过兼容UE的像素流协议传输。

内置后端属于实现参考示例及已注册的后端实现。生成的浏览器UI不得导入它们。项目专用的后端仅能在项目或执行组合根中继承或组合这些实现，且仍需使用选定的公共引擎客户端。

## 前端模块

- `build_admin_app`：创建资源和会话管理界面。
- `launch_admin`：运行管理界面。
- `run_gateway`：运行网关、API、播放器以及集成的浏览器播放功能。
- `run_all`：同时运行网关和管理界面。
- `frontend/player`：用于发现引擎、管理会话、展示`stream_url`并处理通用输入指令。
- `BrowserPlayExample`：关于会话创建/恢复、流媒体展示、焦点控制、全屏模式及错误处理的只读参考示例。

生成的浏览器播放功能会读取与引擎无关的`stream_url`，将输入指令同步到引擎帧中，并上报会话或流媒体相关的错误信息。它不会配置后端、调用引擎客户端、注入游戏专属命令，也不会复制引擎原生的交互界面。

## UI生成边界引擎原生UI会使用选定的引擎API并生成Mechanic合约。  
浏览器播放功能仅通过浏览器服务API来实现流媒体、会话、焦点、全屏、错误处理以及通用输入控制。

浏览器服务不会向Web端暴露带有版本号的Mechanic状态/事件/命令桥接接口。生成的浏览器播放模块不得自行创建诸如生命值、弹药量、分数、游戏目标、暂停、胜利判定或游戏专属命令等API。游戏专属操作仍由引擎原生UI和Mechanic合约来处理。CG视频生成是浏览器服务API所提供的唯一通用媒体操作；何时生成视频片段以及如何展示，仍由游戏逻辑来决定。

## 启动方式

- `python -m engine_adapters.browser_serving all`：同时运行管理界面与网关服务。  
- `python -m engine_adapters.browser_serving gateway`：仅运行网关服务。  
- `python -m engine_adapters.browser_serving admin`：仅运行管理界面。  
- `A3GAME_BROWSER_PLAY_DIR`：指定已生成的浏览器播放模块所在目录。  
- `A3GAME_BROWSER_ENGINE`：选择默认的后端引擎。  
- `A3GAME_UE_PROJECT` / `A3GAME_UE_ROOT`：配置UE5后端相关参数。  
- `A3GAME_UNITY_PROJECT` / `A3GAME_UNITY_ROOT`：配置Unity后端相关参数。  
- `A3GAME_UNITY_WEBGL_BUILD`：指定现有的Unity WebGL构建文件。  
- `A3GAME_BROWSER_DRY_RUN`：在不实际调用引擎渲染的情况下验证服务生命周期。  
- `A3GAME_BROWSER_CG_VIDEO_ENABLED`：启用CG视频网关功能（默认为`true`）。  
- `A3GAME_BROWSER_CG_VIDEO_ALLOW_CLOUD`：明确允许云端视频请求（默认为`false`）。  
- `A3GAME_BROWSER_CG_VIDEO_PREBUILT_ONLY`：仅提供已存储的视频素材；若请求的视频片段没有对应素材，则直接返回错误而不会实时生成（默认为`false`）。  
- `A3GAME_BROWSER_CG_VIDEO_MAX_WORKERS`：同时处理的CG视频任务最大数量（默认为`1`）。

默认端口分别为：管理界面使用`7860`，网关服务使用`7870`，会话页面使用`18080+`，UE流媒体传输的WebSocket端口使用`18888+`。Unity WebGL不会使用UE流媒体传输的WebSocket端口。

启动脚本可以设置上述环境变量，并将请求转发给浏览器服务网关。但脚本不得自行实现替代性后端、在注册的后端生命周期之外启动引擎，或在引擎会话准备就绪前就返回浏览器访问地址。
