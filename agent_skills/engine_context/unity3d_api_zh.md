# Unity3D Agent API参考文档

状态：已实现`UnityClient` API版本`v1`。

经过验证的引擎基准版本：Unity 2022.3.62f3c1。

本文档是已实现的公共功能的精简索引，仅列出公共名称及其功能。如需了解确切的参数或结果数据字段，请查阅当前源代码。

> 由游戏玩法触发的音频、视频CG、动画CG和VFX相关内容，详见下方的**媒体导演**章节。若任务涉及运行时媒体处理，需结合该章节与公共Python API使用。

## 硬性API边界

唯一支持的Python入口点为：

```text
from engine_adapters.unity3d import UnityClient
```

Agent、生成代码、Pipeline代码以及平台Serving代码不得执行以下操作：
- 导入`engine_adapters.unity3d._internal`；
- 直接导入命名空间客户端实现类；
- 调用传输层、服务、调度器、注册表或编辑器脚本构建器；
- 通过私有传输层执行任意Unity编辑器C#代码；
- 修改或引用适配器所属的`A3GameRuntime`框架的内部结构；
- 依赖可选的Arena Fighter、FPS或赛车示例程序集；
- 手动构造生成输出路径。

生成的游戏逻辑应置于独立的项目本地机制与UI程序集（`.asmdef`）中。

## 执行权限

游戏生成Agent会生成引擎原生测试源码。该Agent不得调用`unity.testing.*`或声明基准测试结果成功。

引擎执行与评估代码负责构建流程、Unity Test Framework执行、运行时证据以及基准测试结果。仅进程返回码为0并不等同于成功；NUnit XML报告中必须包含匹配的通过测试用例。

## 结果约定

公共操作会返回可序列化为JSON的结果字典，这些字典包含以下稳定的顶层字段：
- `ok`：操作是否成功完成；
- `operation`：稳定的操作标识符；
- `artifacts`：生成或保留的工件描述符；
- `diagnostics`：结构化的诊断记录；
- `warnings`：非致命性问题；
- `errors`：致命性问题；
- `payload`：特定操作的结果数据。

## 客户端

- `UnityClient`：创建公共的Unity环境客户端及其命名空间客户端。
- `unity.api_version`：返回当前生效的公共UnityClient API版本。
- `unity.get_environment_info`：返回配置的项目、Unity编辑器、传输层及运行时环境信息。
- `unity.generate_game`：运行生成游戏的流程，涵盖项目设置、机制/UI安装、批量资源导入、场景编排、构建，以及可选的编辑器播放模式。

## 项目- `unity.project.get_info`：返回已配置的Unity项目路径及编辑器路径。
- `unity.project.create`：创建一个不含具体游戏逻辑默认设置的简易Unity宿主项目。
- `unity.project.validate`：检查项目设置、包清单以及必要的项目结构。
- `unity.project.synchronize_packages`：将适配器所需的Unity包及内置模块添加到项目清单中。

## 资源
- `unity.assets.import_asset`：根据声明的资源类型导入已注册的任务产物。
- `unity.assets.import_batch`：在单次Unity编辑器中操作内按依赖顺序导入多个已注册的产物。
- `unity.assets.import_avatar`：导入已注册的角色或化身产物，并生成其在Unity中的资源表示。
- `unity.assets.import_motion`：针对指定或已解析的目标骨骼导入已注册的动画数据。
- `unity.assets.import_scene`：导入已注册的Unity场景或环境包产物。
- `unity.assets.import_prop`：导入已注册的道具或通用网格产物。
- `unity.assets.import_weapon`：导入已注册的武器网格产物。
- `unity.assets.import_material`：导入已注册的材料产物。
- `unity.assets.import_texture`：导入已注册的纹理产物。
- `unity.assets.import_effect`：导入已注册的受支持的效果产物。
- `unity.assets.validate`：在可能的情况下，无需导入即可验证已注册的源产物。
- `unity.assets.resolve_source`：将仓库任务标识解析为对应的已注册源产物。
- `unity.assets.list`：列出已配置的Unity项目中可见的资源。
- `unity.assets.list_registered`：列出适配器注册表中记录的产物。
- `unity.assets.get_metadata`：读取某个已注册产物的元数据。

公共资源方法会使用仓库任务标识，不会接受任意生成的输出文件系统路径。

## 动画
- `unity.animation.import_motion`：通过Animation命名空间导入动画数据。
- `unity.animation.resolve_skeleton`：解析与已注册化身或导入资源相关联的骨骼。
- `unity.animation.validate_compatibility`：检查动画数据与骨骼产物是否兼容。

## 绑定
- `unity.bindings.bind_pbr_material`：为导入的资源创建或更新PBR材质绑定。

## 世界- `unity.world.compose_scene`：根据导入的预制体、GameObject、组件及字段引用，创建并保存Unity场景。
- `unity.world.build`：导入已注册的场景，注册其环境资源，生成经过验证的World草稿以及可选的包。
- `unity.world.create_draft`：创建可持久编辑的World草稿。
- `unity.world.validate_draft`：验证World草稿及其引用的资源是否合法。
- `unity.world.publish_draft`：将验证通过的草稿发布为已注册的World包。
- `unity.world.list_packages`：列出已注册的World包。

当任务提供原生Unity场景和包内容时，World相关操作会保留这些内容。

## 插件
- `unity.plugin.install`：将已注册的生成的机制或UI组件安装到Unity项目中。
- `unity.plugin.install_framework`：安装由适配器提供的`A3GameRuntime`运行时框架。
- `unity.plugin.list`：列出已安装的项目组件。

生成的游戏玩法组件仅能依赖公开的`A3GameRuntime` API。

## 构建
- `unity.build.project`：构建Unity Player目标，并返回结构化的命令、资源及诊断信息。

## 测试
- `unity.testing.run_automation_tests`：运行Unity Test Framework测试，解析最新的NUnit XML报告，并返回匹配、通过及失败的测试数量。
游戏生成Agent不得调用此命名空间。

## 运行时
- `unity.runtime.launch_editor`：为项目启动配置好的Unity编辑器，可指定可选的场景。
- `unity.runtime.stop_editor`：停止由同一运行时客户端启动的编辑器进程。
- `unity.runtime.launch_player`：启动由`unity.build.project`生成的原生Unity Player资源。
- `unity.runtime.stop_player`：停止由同一运行时客户端启动的Player进程。

## 运行时会话
- `unity.runtime.sessions.join`：创建或更新通用参与者、控制器、实体及控制绑定会话。
- `unity.runtime.sessions.leave`：标记参与者和控制器为离线状态。
- `unity.runtime.sessions.heartbeat`：刷新参与者的在线状态。
- `unity.runtime.sessions.apply_input`：将标准化后的控制输入应用到绑定的运行时实体上。
- `unity.runtime.sessions.snapshot`：返回当前通用运行时会话的状态。
- `unity.runtime.sessions.reset_world`：请求重置通用的运行时World。
- `unity.runtime.sessions.clear_entity`：从会话状态中移除某个实体及其关联的绑定关系。

运行时会话与具体游戏类型无关，不定义格斗类、FPS类或赛车类指令。原生编辑器和Player会话使用运行时桥接；Unity WebGL会话则通过浏览器画布接收键盘和指针输入。

## 试玩录制- `unity.playtest.record(...)`会启动一个专用的GUI编辑器，并调用`-executeMethod GameFactory3APlayTestRecorder.Enter`：编辑器端的录制器会进入Play模式，按照指定帧率捕获游戏视图的画面，将运行时适配器通过`GetStateSnapshot()`生成的每帧状态快照写入`diagnostics.jsonl`，录制结束后便退出编辑器。相关参数包括：`output_dir`、`scene`、`scenario`或`action_plan`、`duration`、`fps`、`warmup`、`timeout`、`ffmpeg`以及`dry_run`。
- 该录制功能不允许在同一项目中运行实时GUI编辑器（必须使用专用实例），它会根据`scene`参数确定要播放的场景，若未指定则选用`EditorBuildSettings`中的第一个条目。复用录制目录前会先清理其中的旧数据，从而避免旧帧混入新视频中。
- 支持的动作名称包括`move`、`look`、`jump`、`attack`、`interact`、`dash`、`pause`、`restart`和`wait`。每个动作都对应一个正整数`duration_ms`；场景计划必须非空且时长不超过指定的`duration`。macOS平台实现了输入注入功能（借助`System Events`），会在`play_started.json`标记后发送真实的键盘事件；在其他平台上，若无法注入输入，录制任务会直接失败，而非在不包含玩家输入的情况下继续录制。
- 输出文件的存放结构与其他适配器一致：`frames/`文件夹、`actions.jsonl`文件、`report.json`文件、可选的`diagnostics.jsonl`文件（引擎端的状态快照，权限较高），以及启用FFmpeg时生成的`video.mp4`文件。报告采用的架构为`gamefactory3a.unity3d.playtest_report.v1`；由于Play模式在空闲时会受到限制，`recorded_seconds`字段的取值来自编辑器的捕获日志。
- 缺少FFmpeg并不会导致录制失败：即便没有视频文件，帧数据、动作轨迹和报告仍会被保留。

## Unity Media Director：音频、视频CG、动画CG及VFX

对于由游戏玩法触发的媒体内容，可使用引擎原生的`A3GameMediaDirector`组件。跨引擎的逻辑组件名称为`media_director`，而在Unity/C#环境中，对应的文件名和公共类型如下：

```text
A3GameMediaDirector.cs
public sealed class A3GameMediaDirector : MonoBehaviour
```

切勿将Unity文件重命名为`media_director.cs`；保持MonoBehaviour文件和公共类的命名一致是Unity的稳定规范。游戏机制负责决定游戏玩法事件何时触发，并提供稳定的snake_case格式的事件键，例如`hit_confirmed`或`ultimate_cg`。Media Director则负责管理Unity播放对象和媒体资源，它不应负责伤害规则、攻击时机、UI布局、管线编排、浏览器播放传输或基准测试评分等逻辑。

### 公开操作| 操作 | 用途 | 原生绑定 |
|---|---|---|
| `RegisterAudio(eventKey, clip)` | 注册Unity的`AudioClip` | `AudioSource.PlayOneShot()` |
| `TriggerAudio(eventKey, triggerSource="gameplay")` | 播放已注册的音频事件并返回证据记录 | `AudioSource` |
| `RegisterCG(eventKey, videoUrl)` | 注册本地或可访问的视频URL | `VideoPlayer` + `RenderTexture` |
| `TriggerCG(eventKey, triggerSource="gameplay")` | 设置视频URL、播放视频CG，并获取游戏玩法暂停锁 | `VideoPlayer.Play()` |
| `StopCG(eventKey, triggerSource="gameplay")` | 停止CG并释放游戏玩法暂停锁 | `VideoPlayer.Stop()` |
| `NotifyCGFinished(success)` | 通过`loopPointReached`或错误回调释放暂停锁 | `VideoPlayer`回调 |
| `RegisterAnimation(eventKey, animator, stateName, layer=0)` | 绑定Animator状态 | `Animator.Play()` |
| `TriggerAnimation(eventKey, triggerSource="gameplay")` | 播放已注册的动画CG | `Animator` |
| `RegisterVFX(eventKey, effect)` | 绑定`ParticleSystem` | `ParticleSystem` |
| `TriggerVFX(eventKey, triggerSource="gameplay")` | 重启并播放已注册的特效 | `ParticleSystem.Play()` |
| `StopVFX(eventKey, triggerSource="gameplay")` | 停止并清除已注册的特效 | `ParticleSystem.Stop()` |
| `GetEventLog()` | 返回媒体运行时记录 | 内存中的证据 |

如果键为空、资源为null或绑定无效，注册操作会返回`false`。
当绑定或原生播放器不可用时，触发操作会返回一个`MediaEvent`，其中`playback_call_issued=false`；
切勿将方法成功返回视为媒体已在运行中的游戏中可见或可听的凭证。

### 暂停与完成约定

当具有中断性的CG获取或释放仅用于战斗的暂停锁时，会触发`GameplayPauseChanged`事件；`IsGameplayPaused`用于获取当前的锁状态。

- 一旦`TriggerCG`请求被接受，导演就会触发`GameplayPauseChanged(true)`。
- 游戏自有的机制代码在持有该锁期间必须禁用战斗动作与伤害判定。它不应仅仅为了暂停战斗就使用`Time.timeScale = 0`，因为视频和音频必须继续播放。
- 导演会通过`NotifyCGFinished`、`StopCG`或游戏的显式错误/回退清理路径来释放锁，随后触发`GameplayPauseChanged(false)`。
- 导演无法推断正确的命中窗口、投射物释放时机或动画过渡节点；这些仍由游戏自身管控，需通过原生游戏测试来验证。

### 运行时证据

每次触发操作都会返回一个符合`gamefactory3a.media_runtime_event.v1`模式的`MediaEvent`，其字段相当于：

```json
{
  "schema_version": "gamefactory3a.media_runtime_event.v1",
  "seq": 1,
  "t_monotonic_ms": 1234,
  "event_type": "audio_triggered|cg_triggered|cg_animation_triggered|vfx_triggered",
  "event_key": "ultimate_cg",
  "trigger_source": "gameplay",
  "playback_call_issued": true,
  "asset_path": "Assets/Media/ultimate.mp4"
}
```该记录会区分所请求的事件、触发源、原生播放调用、单调运行时排序，以及已注册的剪辑/视频/特效标识。请保留带有原生试玩追踪信息的事件日志；若要确认视觉/音频效果是否正常，仍需观察正在运行的Unity项目。Unity游戏代码应仅依赖这一公共组件接口，绝不能依赖适配器私有的注册表、传输机制、编辑器脚本或生成输出路径。

## 反射功能
- `unity.reflection.inspect_artifact`：通过Unity反射机制检查已注册的导入资源，并返回结构化的元数据。

## 观测功能
- `unity.observe.check_status`：报告编辑器传输状态、项目状态、运行时状态以及观测准备情况。

## A3GameRuntime公共C#接口
生成的游戏逻辑程序集可引用以下路径下的公共API：
```text
A3GameRuntime/Runtime/
```

### 枚举类型
- `A3GameControlMode`：用于标识分配给实体的通用控制模式。
- `A3GameLocomotionState`：用于表示运行时快照中的通用移动状态。

### 数据类型
- `A3GameRuntimeInputState`：携带归一化后的移动、视角、操作及时序状态信息。
- `A3GameEntitySpawnRequest`：描述通用的实体生成请求。
- `A3GameParticipantInfo`：描述某一个运行时参与者信息。
- `A3GameControllerState`：描述某一个通用控制器信息。
- `A3GameControlBinding`：关联参与者、控制器与实体之间的关系。
- `A3GameEntitySnapshot`：报告可观测的通用实体状态。

### 接口
- `IA3GameControllableEntity`：由游戏自有的可操控实体实现的接口。
- `IA3GameEntityFactory`：由游戏自有的实体工厂实现的接口。
- `IA3GameRuntimeMessageHandler`：用于游戏自有的运行时消息处理的接口。

### 组件
- `A3GameIdentityComponent`：在游戏自有的GameObject上存储稳定的运行时标识。
- `A3GameRuntimeEntityComponent`：将游戏自有的GameObject与运行时实体状态及控制输入相关联。

### 子系统
- `A3GameRuntimeSubsystem`：注册游戏自有的工厂，并协调通用运行时实体的创建。
- `A3GameWorldSessionSubsystem`：负责管理通用的参与者、控制器、实体、绑定关系、输入及快照会话状态。
- `A3GameRuntimeInputReceiver`：接收运行时输入消息并将其转发给运行时子系统。

## 框架边界说明
`A3GameRuntime`仅提供运行时接口和协调组件，并不包含具体的角色、控制器、移动实现、武器、载具、战斗规则、HUD或游戏专属的输入映射功能。

生成的项目负责实现具体的游戏逻辑。可选的ArenaFighterExample、FPSExample和RacingExample程序集仅为只读引用，既非依赖项，也不作为功能达成的评判标准。

## 传输机制Unity没有Unreal那样的Python远程执行或HTTP远程控制功能。
`UnityClient`采用子进程传输方式。每次启动编辑器时，都会将子进程的工作目录设置为生成的Unity项目根目录。这么做是必要的，因为Unity编辑器脚本会使用诸如`Assets/Imported/Weapons`这类相对于项目的路径；如果没有这一工作目录约定，相对文件操作可能会写入项目外部，导致AssetDatabase无法识别新导入的资源：

1. 必要时，将所需的捆绑C#编辑器脚本复制到项目的`Assets/Editor/`文件夹中；
2. 将操作参数写入临时JSON作业文件；
3. 调用命令：`Unity -batchmode -quit -projectPath <proj> -executeMethod <Class.Method> --job <job.json> --report <report.json>`；
4. C#脚本将JSON报告写入临时文件；
5. Python传输层读取该JSON报告并返回结果。

### Unity授权前提条件
Unity授权属于外部主机的前提条件，并非3AGameFactory的操作范畴。在调用会修改数据的客户端方法之前，必须通过对应的Unity Hub/Tuanjie Hub账号安装并激活所选编辑器；或者需有已打开且已授权的编辑器可用。`UnityClient`不会自动获取凭证、激活许可席位，也不会替换Hub授权守护进程。

直接批量传输机制特意不强制使用`-licensingIpc`参数：Unity及其Hub会自动选择正确的本地LicensingClient通道。如果主机上存在冲突的Hub守护进程或未完成授权，Unity可能会在加载项目前就退出（常见退出代码为199）。这种情况下，传输层会返回`blocked=true`、`blocked_stage="licensing"`、`license_status`以及日志尾部信息，以便调用方能快速因外部前提条件不满足而报错，而非误以为导入、编译或构建操作已成功。

项目创建、游戏生成、资源导入以及运行时启动命令需使用`<REPO_PATH>/scripts/engine_install/unity/`路径。顶层的`import-batch`公共客户端命令用于批量导入资源；若要执行完整流程，可使用`generate-game`命令，该命令会在单个编辑器会话中完成插件安装、资源导入、材质重新映射、场景搭建、编译、构建以及可选的Play模式运行等操作。

### 运行时输入传输
对于运行时会话，`RuntimeUDPBridge`会将JSON数据包发送至`A3GameRuntimeInputReceiver` C#组件（UDP端口30030），这一机制与UE5中通过UDP桥接发送至`A3GameRuntimeInputPort`（端口30020）的方式类似。

## 坐标系
glTF和Unity均采用Y轴向上的坐标系，且单位均为米，但两者的左右手规则有所不同。Unity的模型导入器会负责格式转换；适配器或游戏逻辑代码不应再额外进行统一的轴向转换。FBX文件的创作轴和单位可能存在差异，因此导入后的模型方向、缩放比例、骨骼结构以及武器朝向仍需进一步检查或通过导入器配置调整。

# Unity VFX API对于烟雾、火焰、爆炸、尘埃以及粒子生命周期相关的效果制作，请使用[`create-vfx-effects`](create-vfx-effects/SKILL.md)技能，以及`<REPO_PATH>/engine_adapters/unity3d/vfx/Runtime/A3Game_VFX.cs`。

建议通过`SpawnPrefab`调用已有的、经过审核的粒子或VFX Graph预制体。那些名为ParticleSystem的函数属于无资源备用方案，它们采用Unity世界空间单位来定位。

程序化风格的备用函数包括`SpawnInkSmoke`、`SpawnFrostFire`和`SpawnCyberFire`。只要存在已制作的预制体，就优先选用；这些风格函数只是分层备用方案，使用时仍需经过视觉层面的审批。

## 导入生成的网格模型

对于生成的GLB、FBX或OBJ文件，可使用宿主启动器进行处理：

```bash
python scripts/import_generated_asset.py --engine unity \
    --src <model> --unity-project <project>
```

该启动器会将`<REPO_PATH>/engine_adapters/unity3d/import_generated/ImportGeneratedMesh.cs`安装到项目的`Assets/Editor/`目录下，并调用`ImportGeneratedMesh.RunFromCLI`。若处理普通网格模型，请使用参数`--usage asset`；若为单个特效网格，使用`vfx_standalone`；若为粒子系统实例化的网格，则使用`vfx_particle`。

请将JSON导入报告视为结果约定。在引用预制体之前，需检查其中的`ok`、`assetPath`、`prefabPath`字段，以及三角形数量、材质数量、绑定的纹理、边界信息及警告提示。导入GLB文件需要安装`com.unity.cloud.gltfast`插件；完整的项目设置说明详见`<REPO_PATH>/scripts/engine_install/README.md`。生成的项目包含具体的游戏逻辑实现。可选的Arena Fighter、FPS和赛车类示例仅作为参考，并非运行时依赖项，也不作为项目成功的标准。
