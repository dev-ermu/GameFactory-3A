# UE5 Agent API参考文档

状态：已实现`UEClient` API版本`v1`。

验证通过的引擎基线：Unreal Engine 5.4。

本文档是已实现的公共功能的精简索引，仅列出了公共名称及其功能。如需了解确切的参数或结果负载字段，请查阅当前源代码。

## 主机端API边界

对于主机端的Python代码，唯一支持的Unreal入口点为：

```text
from engine_adapters.ue5 import UEClient
```

Agent、Pipeline代码、执行/评估组合根、仓库脚本以及平台服务端均不得：
- 导入`engine_adapters.ue5._internal`；
- 直接导入客户端实现类所在的命名空间；
- 调用传输层、服务、调度器、注册表或脚本构建器；
- 通过私有传输层执行任意Unreal Python代码；
- 修改由适配器拥有的`A3GamePlayable`框架；
- 包含`A3GamePlayable`的私有头文件；
- 依赖可选的Arena Fighter、FPS或赛车类示例插件；
- 手动构造生成输出路径。

主机端代码不得将公共`UEClient`操作替换为直接的`UnrealEditor`、`Build.bat`、`unreal.AssetImportTask`或临时Unreal Python启动器。仓库中的`<REPO_PATH>/scripts/engine_install/ue5/import_asset.sh`封装脚本只是围绕同一公共客户端契约的生命周期封装，并非第二种导入API。

### 原生插件边界

生成的Unreal游戏玩法与UI插件在Unreal引擎内部运行，可使用项目中可用的、有文档说明的原生Unreal C++ API。这些插件不会导入或调用Python版的`UEClient`。

```text
主机端项目/导入/构建/运行时生命周期 -> UEClient
原生Unreal游戏玩法/UI插件         -> Unreal原生C++ API
```

原生插件仅限于项目内部使用，仅能使用允许的公共`A3GamePlayable`头文件及常规的Unreal模块依赖项，且不能访问`<REPO_PATH>/engine_adapters/ue5`下的私有实现代码。

### 执行组合根

生成Agent可能会产出原生插件源码和测试内容，但它不会运行引擎，也无法保证构建/可玩性的权威性。后续的执行/组装组合根可以复用已配置的`UEClient`会话来验证并准备项目、导入描述符、安装插件、构建目标、运行权威性测试，以及启动或停止运行时环境。

如果`UEClient`中缺少某项所需操作，应先报告公共API的能力缺口，并扩展公共客户端/适配器契约，切勿创建游戏自有的并行导入器或构建系统。

## 执行权限说明

游戏生成Agent会生成引擎原生的测试源码。该Agent绝不能调用`ue.testing.*`或宣称基准测试成功。引擎执行与评估代码负责构建、自动化测试执行、运行时证据以及基准测试结果。生成代理不得调用`ue.testing.*`；后续的执行/组装模块可通过`UEClient`来调用它。仅进程返回码为零并不等同于操作成功；自动化报告必须包含对应的通过测试项。

## 结果约定

公共操作会返回可序列化为JSON的结果字典，其中包含以下稳定的顶层字段：
- `ok`：操作是否成功完成；
- `operation`：稳定的操作标识符；
- `artifacts`：生成的或保留的工件路径；
- `diagnostics`：结构化的诊断记录；
- `warnings`：非致命性问题；
- `errors`：致命性问题；
- `payload`：特定于操作的结果数据。

## 客户端

- `UEClient`：用于创建公共的Unreal环境客户端及其命名空间客户端。
- `ue.api_version`：返回当前生效的公共UEClient API版本。
- `ue.get_environment_info`：返回已配置的项目、引擎、传输方式及运行时环境信息。

## 项目相关

- `ue.project.get_info`：返回已配置的Unreal项目及引擎路径。
- `ue.project.create`：创建一个不含具体游戏逻辑默认设置的简易C++ Unreal宿主项目。
- `ue.project.validate`：检查项目配置、描述文件、引擎、源代码以及必要的项目结构是否符合要求。

## 资产相关

- `ue.assets.import_asset`：根据声明的资产类型导入已注册的任务工件。
- `ue.assets.import_avatar`：导入已注册的角色或虚拟形象工件。
- `ue.assets.import_motion`：针对指定的骨骼模型导入已注册的动画数据。
- `ue.assets.import_scene`：导入已注册的场景工件。
- `ue.assets.import_prop`：导入已注册的道具或通用网格模型工件。
- `ue.assets.import_weapon`：导入已注册的武器网格模型工件。
- `ue.assets.import_material`：导入已注册的材料工件。
- `ue.assets.import_texture`：导入已注册的纹理工件。
- `ue.assets.import_effect`：导入经过验证的效果包或原生效果内容。
- `ue.assets.validate`：在可能的情况下，无需连接实时运行的Unreal引擎即可验证已注册的源工件。
- `ue.assets.resolve_source`：将仓库任务标识解析为对应的已注册源工件。
- `ue.assets.list`：列出当前运行的Unreal项目中可见的资产。
- `ue.assets.list_registered`：列出适配器注册表中记录的工件。
- `ue.assets.get_metadata`：读取某个已注册工件的元数据。

公共资产方法接收的是仓库任务标识或文档中规定的公共描述符格式，不会接受调用方随意拼凑的生成输出文件路径。请通过客户端解析源信息，并保留其返回的结构化结果与工件标识。

### 导入生命周期`<REPO_PATH>/scripts/engine_install/ue5/import_asset.sh` 是一个围绕同一公共`UEClient`的生命周期封装脚本，它并非第二个或更快的资产API。主机端的批量执行应复用已配置好的客户端和正在运行的编辑器会话，而非为每个资产单独启动一个Unreal进程。

直接的资产和世界操作要求Unreal Python执行环境已准备就绪。执行代码应针对一批任务复用同一个`UEClient`和正在运行的编辑器会话，而非为每个资产重新创建或重启它们。

仓库导入启动器会检查准备状态，仅在必要时启动编辑器；即便可选的远程控制功能不可用，只要Python执行环境就绪，它就能继续运行。

## 动画相关
- `ue.animation.import_motion`：通过Animation命名空间导入动作数据。
- `ue.animation.resolve_skeleton`：解析与已注册虚拟形象或导入资产关联的骨骼信息。
- `ue.animation.validate_compatibility`：检查动作数据与骨骼资源是否兼容。

## 绑定相关
- `ue.bindings.bind_pbr_material`：为导入的资产创建或更新PBR材质绑定。

## 世界相关
- `ue.world.build`：根据已注册的场景资源构建或导入世界。
- `ue.world.create_draft`：创建一个可持久编辑的世界草稿。
- `ue.world.validate_draft`：验证世界草稿及其引用的资源是否有效。
- `ue.world.publish_draft`：将验证通过的草稿发布为已注册的世界包。
- `ue.world.list_packages`：列出已注册的世界包。

当任务提供原生项目或地图包时，世界操作会保留Unreal原生内容。

## 插件相关
- `ue.plugin.install`：将已注册的生成型游戏插件安装到项目中，并同步声明的框架依赖项。
- `ue.plugin.install_framework`：安装由适配器提供的`A3GamePlayable`运行时框架。
- `ue.plugin.list`：列出已安装的项目插件。

生成的游戏插件仅能依赖`A3GamePlayable`的公共头文件。

## 构建相关
- `ue.build.project`：构建Unreal项目目标，并返回结构化的命令及诊断信息。

## 测试相关
- `ue.testing.run_automation_tests`：运行Unreal自动化测试，解析最新的测试报告，并返回匹配、通过和失败测试的准确数量。

游戏生成代理不得调用此命名空间，只有后续的执行/组装模块才能通过`UEClient`调用它。

## 运行时相关
- `ue.runtime.launch_editor`：启动配置好的Unreal编辑器或游戏运行时进程。
- `ue.runtime.stop_editor`：停止由同一运行时客户端启动的编辑器进程。

## 运行时会话- `ue.runtime.sessions.join`：创建或更新通用的参与者、控制器、实体及控制绑定会话。
- `ue.runtime.sessions.leave`：从运行时会话中移除某个参与者。
- `ue.runtime.sessions.heartbeat`：刷新参与者的活跃状态。
- `ue.runtime.sessions.apply_input`：将标准化后的控制输入应用到绑定的运行时实体上。
- `ue.runtime.sessions.snapshot`：返回当前通用运行时会话的状态。
- `ue.runtime.sessions.reset_world`：请求重置通用的运行时世界。
- `ue.runtime.sessions.clear_entity`：从会话状态中移除某个实体及其关联的绑定关系。

运行时会话与游戏类型无关，不会定义格斗类、第一人称射击类或赛车类的相关指令。

## 反射功能
- `ue.reflection.inspect_artifact`：通过Unreal反射机制检查已注册的导入构件，并返回结构化的元数据。

## 观测功能
- `ue.observe.check_status`：报告远程控制、Python执行、项目、运行时以及观测功能的就绪状态。

## A3GamePlayable公共C++接口规范
生成的游戏玩法插件只能包含以下路径下的头文件：
```text
A3GamePlayable/Source/A3GamePlayable/Public/
```

### 枚举类型
- `EA3GameControlMode`：标识分配给实体的通用控制模式。
- `EA3GameLocomotionState`：表示运行时快照中的通用移动状态。

### 数据类型
- `FA3GameRuntimeInputState`：携带标准化的移动、视角、动作及输入时序状态。
- `FA3GameEntitySpawnRequest`：描述通用的实体生成请求。
- `FA3GameParticipantInfo`：描述单个运行时参与者信息。
- `FA3GameControllerState`：描述单个通用控制器的状态。
- `FA3GameControlBinding`：用于关联参与者、控制器和实体。
- `FA3GameEntitySnapshot`：汇报可观测的通用实体状态。

### 接口
- `IA3GameControllableEntity`：由游戏自有的可操控实体实现的接口。
- `IA3GameEntityFactory`：由游戏自有的实体工厂实现的接口。
- `IA3GameRuntimeMessageHandler`：用于游戏自有的运行时消息处理的接口。

### 组件
- `UA3GameIdentityComponent`：在游戏自有的Actor上存储稳定的运行时身份标识。
- `UA3GameRuntimeEntityComponent`：将游戏自有的Actor与运行时实体状态及控制逻辑关联起来。

### 子系统
- `UA3GameRuntimeSubsystem`：注册游戏自有的工厂，并协调通用运行时实体的创建。
- `UA3GameWorldSessionSubsystem`：负责管理通用的参与者、控制器、实体、绑定、输入及快照会话状态。

## 框架边界说明
A3GamePlayable仅提供运行时接口，不提供具体的角色、Pawn、控制器、游戏模式、HUD、武器、载具、战斗规则或游戏专属的输入映射功能。

生成的项目负责实现具体的游戏玩法逻辑。可选的Preview、Arena Fighter、FPS及Racing插件仅为只读引用，既不属于依赖项，也不作为项目成功的标准。这个原生C++合约特意与上述的宿主端`UEClient`合约分开。`UEClient`负责准备并执行项目；它并非生成后的Unreal模块内的依赖项。

## 试玩录制

- `ue.playtest.record(...)`会启动一个专用的游戏进程并在引擎内录制内容：编译后的`A3GamePlayable`插件中的`UA3GamePlaytestRecorderSubsystem`会读取`-A3Playtest*`命令行参数，在游戏开始（`HasBegunPlay`）后通过引擎截图管道捕获PNG帧，写入`play_started.json`输入标记，录制结束后便退出游戏。相关参数包括：`output_dir`、`map_path`、`scenario`或`action_plan`、`duration`、`fps`、`warmup`、`timeout`、`ffmpeg`以及`dry_run`。
- 对于已打包的项目（包含`Binaries/Win64/<Project>.exe`和`Content/Paks`），可直接运行打包后的游戏；未打包的项目则会启动`UnrealEditor.exe <project> <map> -game`。若插件源代码有改动，需在录制前重新构建对应的目标。
- 支持的动作名称包括`move`、`look`、`jump`、`attack`、`interact`、`dash`、`pause`、`restart`和`wait`。每个动作都对应一个正整数`duration_ms`；场景计划必须非空且能在指定的`duration`内完成。在Windows平台上，客户端会在`play_started.json`标记之后，通过`SendInput`将时间线作为真实的键盘事件注入；其他平台仅会记录轨迹。
- 输出目录结构与其他适配器一致：`frames/`文件夹、`actions.jsonl`文件、`report.json`文件、可选的`video.mp4`文件（需PATH环境变量中包含FFmpeg或指定`ffmpeg=`参数），此外还有`play_started.json`和`_editor_report.json`（即游戏内录制器生成的报告，以`native_report`形式呈现）。该报告的架构为`gamefactory3a.ue5.playtest_report.v1`，包含`status`、`frames`、`recorded_seconds`、`executed_actions`、`video`和`warnings`字段。
- 即使缺少FFmpeg也不会导致致命错误：即便没有视频，帧数据、动作轨迹和报告仍会被保留。

## UE5 Media Director：音频、视频CG、动画CG及VFX

在生成的原生游戏代码中使用公开的`UA3GameMediaSubsystem`类；它相当于Unity/Godot中的`A3GameMediaDirector`。跨引擎的逻辑组件名称为`media_director`，而UE端的源码则遵循引擎的类文件命名规范：

```text
A3GameMediaSubsystem.h
class A3GAMEPLAYABLE_API UA3GameMediaSubsystem : public UWorldSubsystem
```

目前UE5仅实现了音频和视频CG的绑定；动画CG和VFX的绑定仍由游戏自身负责，直到该子系统后续扩展相关功能。游戏机制负责决定游戏事件发生的时机，并提供稳定的snake_case格式的事件键，例如`hit_confirmed`或`ultimate_cg`。该子系统负责管理UE播放对象和媒体相关数据。它不应涉及伤害规则、攻击时机、UI布局、管线编排、Browser Play传输或基准测试评分等逻辑。

### 公开操作| UE5方法 | 用途 | 原生绑定 |
|---|---|---|
| `RegisterAudio(eventKey, sourcePath)` | 注册本地音频文件，并创建对应的播放器与声音组件 | `UMediaPlayer` + `UMediaSoundComponent` |
| `TriggerAudio(eventKey, triggerSource="gameplay")` | 播放已注册的音频事件并记录相关证据 | `UMediaPlayer::Play()` |
| `RegisterCG(eventKey, videoUrl)` | 注册本地或可访问的视频URL | `UMediaPlayer` |
| `TriggerCG(eventKey, triggerSource="gameplay")` | 播放非循环播放的CG动画，并获取游戏玩法暂停锁 | `UMediaPlayer::Play()` |
| `StopCG(eventKey, triggerSource="gameplay")` | 停止CG动画并释放暂停锁 | `UMediaPlayer::Pause()`/`Close()` |
| `GetMediaPlayer(eventKey)` | 返回用于游戏内显示画面的原生播放器 | `UMediaPlayer` |
| `GetEventLogJson()` | 返回以换行符分隔的媒体运行时记录 | 内存中的证据数据 |

`RegisterMedia`和`TriggerMedia`仍作为兼容别名使用。当缺少对应绑定时，触发操作会记录`playback_call_issued=false`；切勿将方法调用成功视为媒体已在运行中的游戏中可见或可听的凭证。通过旧版`RegisterMedia(..., false)`形式注册的视频文件会被归类为音频，且不会获取CG暂停锁——对于MP4/MOV格式的媒体，请使用`RegisterCG`。

### 暂停与完成机制

当有中断性CG动画获取或释放仅用于战斗的暂停锁时，会广播`OnGameplayPauseChanged`事件；`IsGameplayPaused`则用于获取当前的锁状态。

- 一旦`TriggerCG`请求被接受，子系统会广播`OnGameplayPauseChanged(true)`，并记录当前活跃的视频键。
- 游戏内的机制代码在持有该锁期间必须禁用战斗动作与伤害判定。切勿仅为了暂停战斗就使用引擎全局暂停功能（`APlayerController::SetPause`），因为视频和音频必须继续播放。
- 子系统会在视频正常播放完毕（`OnEndReached`，记录为`cg_finished`）、执行`StopCG`操作或世界场景销毁时释放该锁，随后广播`OnGameplayPauseChanged(false)`。
- 子系统会提供音频路径与`UMediaPlayer`；视频画面仍需由游戏自身提供`UMediaTexture`/UMG表面，并与`GetMediaPlayer(eventKey)`绑定。
- 子系统无法推断正确的命中窗口、投射物释放时机或动画过渡节点；这些均由游戏自身控制，需通过原生测试验证。

### 运行时证据

每个事件均遵循`schema gamefactory3a.media_runtime_event.v1`，其字段相当于：

```json
{
  "schema_version": "gamefactory3a.media_runtime_event.v1",
  "seq": 1,
  "t_monotonic_ms": 1234,
  "event_type": "media_registered|audio_triggered|cg_triggered|media_stopped|cg_stopped|cg_finished",
  "event_key": "ultimate_cg",
  "trigger_source": "gameplay",
  "playback_call_issued": true,
  "asset_path": "Movies/ultimate.mp4"
}
```每条记录会通过 `OnMediaEvent` 进行广播，并被追加到由 `GetEventLogJson()` 返回的日志中。请务必将事件日志与原生测试追踪信息一同保存；若要确认视觉/音频效果是否正常，仍需观察正在运行的 UE5 项目。UE 游戏代码应仅依赖这一公共子系统接口，绝不要依赖适配器私有的注册表、传输机制、编辑器脚本或生成的输出路径。
