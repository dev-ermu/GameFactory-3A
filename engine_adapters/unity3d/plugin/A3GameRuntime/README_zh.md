# A3Game运行时框架

这是3AGameFactory为Unity引擎打造的运行时框架，相当于UE5中的`A3GamePlayable` C++框架。它提供了可控实体契约、内存中的会话状态管理功能，以及用于AI驱动游戏生成的UDP输入接收能力。

## 架构

```
A3GameRuntime/
├── package.json
├── Runtime/
│   ├── A3GameRuntime.asmdef          # 程序集定义（仅依赖UnityEngine）
│   ├── A3GameControlMode.cs          # 控制模式枚举
│   ├── A3GameLocomotionState.cs      # 移动状态枚举
│   ├── A3GameRuntimeInputState.cs    # 输入状态结构体
│   ├── A3GameEntitySpawnRequest.cs   # 实体生成请求结构体
│   ├── A3GameParticipantInfo.cs      # 参与者信息结构体
│   ├── A3GameControllerState.cs      # 控制器状态结构体
│   ├── A3GameControlBinding.cs       # 控制绑定结构体
│   ├── A3GameEntitySnapshot.cs       # 实体快照结构体
│   ├── IA3GameControllableEntity.cs  # 可控实体接口
│   ├── IA3GameEntityFactory.cs       # 实体工厂接口
│   ├── IA3GameRuntimeMessageHandler.cs # 消息处理器接口
│   ├── A3GameIdentityComponent.cs    # 身份标识MonoBehaviour组件
│   ├── A3GameRuntimeEntityComponent.cs # 实体MonoBehaviour组件
│   ├── A3GameRuntimeSubsystem.cs     # 运行时协调器单例
│   ├── A3GameWorldSessionSubsystem.cs # 会话状态管理单例
│   ├── A3GameRuntimeInputReceiver.cs # UDP输入接收器（端口30030）
│   └── A3GameMediaDirector.cs       # 原生音视频CG/VFX桥接组件
└── Tests/
    └── A3GameRuntime.Tests.asmdef    # 测试程序集定义
```

## 媒体导演命名规则

跨引擎的逻辑组件名称为`media_director`。在Unity中遵循原生C#命名规范，该组件的文件名为`A3GameMediaDirector.cs`，公开类型为`A3GameMediaDirector`；请勿将其重命名为`media_director.cs`，因为MonoBehaviour文件名与类名必须保持一致。关于该组件的命名、所有权、暂停机制及数据契约详情，可参考`<REPO_PATH>/agent_skills/engine_context/unity3d_api.md`中的“Unity媒体导演”章节。

## 关键设计决策

- **仅引用UnityEngine程序集**——不依赖任何游戏专属程序集。生成的游戏逻辑代码依赖于该程序集，但该程序集本身从不依赖生成的代码。
- **基于MonoBehaviour实现**——采用Unity的组件模型，而非UE5的UObject/Actor系统。
- **移动逻辑由游戏逻辑层掌控**——运行时组件负责记录移动数据并广播标准化输入信息；碰撞检测、重力计算、跳跃、战斗及交互逻辑则由生成的控制器或示例代码实现。
- **UDP端口30030**——用于接收来自Python端`RuntimeUDPBridge`的JSON数据包。
- **内存中的会话状态管理**——通过基于`Dictionary`的结构，同步Python端`RuntimeSessionService`中的参与者、控制器、实体、绑定关系及输入追踪数据。

## 消息类型

`A3GameRuntimeInputReceiver`可处理以下UDP JSON消息类型：| 类型 | 描述 |
|---|---|
| `sync_session` | 创建/重新连接参与者，并将控制器与其对应的实体绑定 |
| `input_state` | 将输入信息应用到已绑定的实体上 |
| `participant_offline` | 标记某个参与者及其控制器为离线状态 |
| `destroy_entity` | 移除某个实体并清理其相关状态 |

未知的消息类型会通过 `A3GameRuntimeSubsystem.DispatchExtensionMessage` 转发给已注册的 `IA3GameRuntimeMessageHandler` 实例。

## 使用方法

1. 将 `A3GameRuntime` 和 `A3GameWorldSessionSubsystem` 添加到场景中的 GameObject 上（也可让它们自动创建）。
2. 向运行时子系统注册一个 `IA3GameEntityFactory` 实现，以便自定义实体的创建方式。
3. 启用后，`A3GameRuntimeInputReceiver` 会自动开始监听 UDP 端口 30030 上的输入数据。
4. 使用 `A3GameWorldSessionSubsystem.Instance` 来查询会话状态和快照信息。
