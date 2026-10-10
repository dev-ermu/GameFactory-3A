# 面向Godot的A3GamePlayable

这款由适配器开发的Godot 4插件，提供了游戏开发所需的可复用引擎层功能：身份识别、标准化输入处理、运行时会话管理、实体绑定、安全的场景实例化、动画调度、碰撞查询、遥测数据HUD显示，以及PBR/光照辅助工具。具体的移动逻辑、战斗机制、载具控制、摄像机行为、计分规则以及游戏专属UI则仍由生成的游戏逻辑部分负责。

通过公共API即可安装该插件：

```python
from engine_adapters.godot import GodotClient

result = GodotClient(project_path="/projects/MyGame").plugin.install_framework()
assert result["ok"], result["errors"]
```

安装程序会在独立的Godot项目中验证`plugin.cfg`文件以及`@tool EditorPlugin`条目，仅复制常规的非链接目录树，随后启用该插件，并将`A3GameRuntime`注册为自动加载项。除非设置`replace_existing=True`，否则现有文件及设置不会被覆盖；一旦安装过程中出现验证或提交错误，插件和`project.godot`文件都会被回滚至初始状态。

## 功能对照表

该对照表源自该代码库对应的UE和Unity运行时插件。“原生支持”意味着Godot本身已直接提供该功能，额外的适配器抽象只会削弱其原有机制的有效性。

| 跨引擎功能 | Godot实现 | 契约与故障行为 |
| --- | --- | --- |
| 身份组件 | `A3GameIdentity`、`A3GameRuntimeEntity` | 需要非空的World/实体ID；快照会返回稳定的身份信息和最后一次输入状态 |
| 标准化输入 | `A3GameInputState.normalize()` | 会对布尔值和序列进行类型检查，拒绝非有限数值，限制移动和俯仰角度；无效数据包会在状态变更前被发送NACK响应 |
| 运行时/会话子系统 | `A3GameRuntime`自动加载模块 | 支持UDP方式的加入/重新连接/离开/输入/重置/清除操作，提供按World划分的快照、最后一次输入查询功能，针对不支持的操作会抛出明确错误 |
| 可控制实体 | `A3GameRuntimeEntity` | 支持分组注册、身份配置、标准化输入信号、输入拒绝信号，以及快照和显式清除钩子 |
| 场景加载器 | `A3GameSceneLoader.instantiate_scene()` | 仅支持非遍历的`res://`路径下的`PackedScene`资源；若资源缺失或路径错误，会返回`{ok=false}`且不会附加节点 |
| 动画导演 | `A3GameAnimationDirector` | 会查找`AnimationPlayer`组件；若剪辑缺失、混合设置无效，或速度值为零/非有限数值，会直接报错 |
| 媒体导演 | `media_director.gd` / `A3GameMediaDirector` | 负责原生音频、视频CG、动画CG及VFX触发；遇到中断性CG时会发出`gameplay_pause_changed`信号 |
| 碰撞探测 | `A3GameCollisionProbe` | 可在调用方的`World3D`上执行射线和球体重叠查询；若World、半径或结果限制参数无效，会直接报错 |
| HUD遥测 | `A3GameHudLayer` | 提供轻量级的标题/排序状态展示界面；生成的UI仍归游戏所有 |
| 材质与光照工具包 | `A3GameVisualKit` | 提供受限范围的PBR数值以及阴影太阳/补光辅助功能；会返回原生的Godot资源/节点 |
| 角色/载具物理 | 原生的`CharacterBody*`、`RigidBody*`、`move_and_slide` | 游戏特定的物体形状、重力、加速度及碰撞响应逻辑仍由生成代码处理 |
| 资产/场景图 | 原生的`ResourceLoader`、`PackedScene`、`Node` | 宿主端的来源/导入信息仍标记为`GodotClient.assets`；运行时代码仅能访问`res://`路径下的资源 |
| VFX与音频 | 原生的粒子系统、着色器、`AudioStreamPlayer*` | 生成代码会决定特效/音频的语义；没有包装器会试图配置游戏内容 |

`capabilities.json`是这张表的机器可读形式。所有引用的文件都是原生框架冒烟测试中实际使用的实现。

## 媒体导演命名规则

跨引擎的逻辑组件名为`media_director`。这个Godot适配器保留了原生文件的拼写`media_director.gd`，并公开了公共类型`A3GameMediaDirector`；关于命名、所有权、暂停机制及契约细节，可查看`<REPO_PATH>/agent_skills/engine_context/godot_api.md`中的**Godot媒体导演**章节。

## 运行时通信契约`GodotClient.runtime.sessions`会向`A3GameRuntime`发送JSON消息。该端点默认地址为`127.0.0.1:30050`，可通过`A3GAME_GODOT_RUNTIME_HOST`/`A3GAME_GODOT_RUNTIME_PORT`，或对应的项目设置项`a3game/runtime_host`/`a3game/runtime_port`来修改。

标准化后的输入内容如下：

| 字段 | 类型/规范化规则 |
| --- | --- |
| `move_x`、`move_y` | 有限浮点数，取值范围被限制在`[-1, 1]`之间 |
| `run`、`jump` | 严格的布尔值 |
| `yaw` | 有限浮点数 |
| `pitch` | 有限浮点数，取值范围被限制在`[-π/2, π/2]`之间 |
| `seq` | 整数 |
| `timestamp` | 有限浮点数 |

生成后的游戏玩法子类会继承`A3GameRuntimeEntity`，并处理其`runtime_input`信号：

```gdscript
extends A3GameRuntimeEntity

func _ready() -> void:
	super()
	runtime_input.connect(_apply_input)

func _apply_input(input: Dictionary) -> void:
	# 加速度、碰撞和动画规则因游戏而异。
	velocity.x = float(input["move_x"]) * 6.0
```

`A3GameRuntime.bind_entity(node, entity_id)`会对那些不满足所需属性/方法约定的节点返回明确的错误提示。

## 会话与世界

会话默认对应`world_001`。重置世界时只会移除匹配的原生会话记录，并触发`world_reset`信号；游戏玩法可利用该信号进行自身的世界清理工作。清除实体时总会移除匹配的原生会话记录。只有当`destroy_actor`为`true`时，才会调用`clear_a3game_entity()`，这样调用方就能在保留Godot节点的同时解除对运行时的控制。

离开操作会擦除原生控制器并停用其在Python端的绑定。已离开的控制器无法发送输入数据，也无法通过心跳机制复活；若要恢复控制，需调用`join()`来创建并注册新的控制器。使用相同的参与者ID重新加入时，会保留原有的实体ID，并且会原子性地替换掉之前的原生控制器绑定，因此旧控制器无法继续发送输入数据。基于参与者的离开操作会针对当前绑定的控制器生效。

`session_joined`是一个实体创建请求：仅当`a3game_runtime_entity`组中尚未存在该实体ID时才会触发该信号。控制器被替换时会触发`session_reconnected(previous_session, session)`信号，无需额外的模拟离开/加入操作。如果实体仍存在于场景树中，显式离开后的再次加入也会触发`session_reconnected`信号。可使用`A3GameRuntime.find_entity(entity_id)`来获取该实体。`session_left`表示控制权已被解除；实体的销毁由`clear_entity()`或游戏自身的世界清理逻辑处理。

`sessions_snapshot(world_id)`会返回防御性副本，而`last_input_for(entity_id)`则返回最新被接受的标准化输入数据。`world.reset`仅删除对应世界的状态。`entity.clear`会移除该实体的所有控制器，且仅当`destroy_actor=true`时才会调用`clear_a3game_entity()`。

## 原生辅助函数

```gdscript
var loaded := A3GameSceneLoader.instantiate_scene(
	"res://worlds/arena.tscn", get_tree().current_scene
)
if not loaded.ok:
	push_error(loaded.error)
``````gdscript
var hit := A3GameCollisionProbe.raycast(
	get_world_3d(), global_position, global_position + -basis.z * 20.0
)
if hit.ok and hit.hit:
	print(hit.collider)

var played := A3GameAnimationDirector.play(self, &"Run", 0.12, 1.0)
if not played.ok:
	push_warning(played.error)
```

## 验证

调用 `install_framework()` 后，在目标项目中运行附带的原生冒烟测试脚本：

```bash
godot4 --headless --path /projects/MyGame --import
godot4 --headless --path /projects/MyGame \
  --script res://addons/a3game_playable/tests/framework_smoke.gd
```

若测试成功，会输出 `A3GAME_FRAMEWORK_SMOKE_OK capabilities=10`。该脚本会加载并执行所有辅助功能，检查异常情况/失败路径，实例化真实的 `PackedScene`，创建原生的UI/材质/灯光对象；一旦有任何断言失败，脚本就会返回非零退出码。
