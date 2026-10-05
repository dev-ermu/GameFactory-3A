---
name: create-vfx-effects
description: 在Unreal Engine 5或Unity中创建并控制可复用的游戏视觉特效，包括烟雾、火焰、爆炸、尘土、风格化墨水/霜冻/赛博特效，以及绑定于动作上的特效。可用于环境或战斗类视觉特效制作，支持Niagara、Unity ParticleSystem、视觉特效生命周期管理、动画/插槽绑定功能，也适用于需要复用现有特效模板的引擎代码开发。
---

# 创建视觉特效

从经过审核的Niagara系统、粒子预制体或VFX Graph资源入手。适配器提供了通用的特效生成与清理接口；对于没有合适资源的项目，Unity的程序化特效可作为备选方案。

## 选择引擎
- 针对UE5，请阅读`<REPO_PATH>/engine_adapters/ue5/vfx/vfx_functions.py`，并在Unreal Editor中调用其Python API。
- 针对Unity，请阅读`<REPO_PATH>/engine_adapters/unity3d/vfx/Runtime/A3Game_VFX.cs`。在引用该类之前，需将其复制到目标项目的`Assets/`目录下。
- 引擎相关的代码切勿写入宿主Python模块以及模型/运算符模块中。

对于机械类任务，`UEClient`仍是唯一的宿主端Unreal API。可将视觉特效模块作为生成引擎代码的参考，或用于编辑器端的审核步骤；切勿从宿主Agent导入这些模块，也不要绕过`UEClient`的传输边界。

## 优先复用现有模板
1. 在项目内搜索轮廓和时长符合要求的特效。在Unity中，可查看`Assets/`目录以及`%APPDATA%/Unity/Asset Store-5.x/`路径下的内容。
2. 对实例的参数、变换属性、材质实例或颜色进行调整，切勿修改源模板。
3. 如果文档中指定的默认资源未安装，可传入项目专用的资源路径或预制体。
4. 仅当没有经过审核的资源可用时，才可使用Unity的程序化命名函数作为备选。

切勿用发光球体或无纹理的白色粒子来替代烟雾或火焰特效。

## UE5相关函数
- 针对已命名的特效，调用`spawn_smoke`、`spawn_fire`、`spawn_explosion`或`spawn_dust`函数。
- 针对项目专用的模板，调用`spawn_niagara(system_path, ...)`函数。
- 当需要动态选择特效类别时，调用`spawn_effect(kind, ...)`函数。
- 要清理循环播放的特效，调用`stop_effect(actor, destroy=True)`函数。
- 针对墨水、霜冻或赛博类特效，调用`spawn_styled_effect`函数。
- 对于绑定于动作上的特效，使用`build_punch_fire_binding`构建WorldFlexVFXBinder请求；在更改动画资源前，先以`Apply=false`参数运行检测。
- 位置参数单位为厘米，旋转参数以`(俯仰角, 偏航角, 翻滚角)`的形式表示，单位为度。

自然类特效的默认设置：

| 特效类型 | 默认的Niagara系统 |
|---|---|
| 烟雾 | `/Game/NiagaraExamples/FX_Smoke/NS_Smoke_Plume` |
| 火焰 | `/Game/NiagaraExamples/FX_Misc/NS_Fire` |
| 爆炸 | `/Game/NiagaraExamples/FX_Explosions/NS_Explosion_Small` |
| 尘土 | `/Game/NiagaraExamples/FX_Explosions/NS_Dirt_Explosion_Small` |

风格化特效的默认设置及图层规范：| 风格 | Niagara系统 | 所需图层 | 材质与调色板 |
|---|---|---|---|
| 墨迹 | `/Game/VFXGenEngine/SwapFX/NS_sp_ink` | 量化实体、流体扭曲效果层、液滴层 | 四阶数值变化；缓慢的两相流动效果；接近黑色与纸张质感灰色 |
| 冰霜 | `/Game/VFXGenEngine/SwapFX/NS_sp_ice` | 低温核心层、水晶碎片层、镜头反光层 | 世界空间噪声反光效果；低扭曲度；青白色与深蓝色 |
| 赛博 | `/Game/VFXGenEngine/SwapFX/NS_sp_cyber` | 能量实体层、脉冲层、数据流线条层 | 四阶动态数值变化；快速脉冲/故障效果；青色与品红色 |

这些系统会用特定风格的材质实例和后期处理效果，替换默认的`NS_Fire`渲染材质。仅使用默认系统加参数写入的方式无法实现同等效果，因为不受支持的Niagara参数会被直接忽略，不会产生任何作用。

`build_punch_fire_binding`函数会检测高速手部动作间隔，并将定时的Niagara通知状态绑定到`RightHand`。运行时可设置`Apply=false`，先查看事件时间、持续时长和缩放参数，再将其应用到副本或经过审核的动画资源中。

如果项目将资产安装在其他路径，需传入参数`system_path="/Game/..."`。若缺少对应资产，会触发`VFXAssetNotFound`错误。

```python
from engine_adapters.ue5.vfx import spawn_fire, stop_effect

fire = spawn_fire(
    (120.0, -40.0, 0.0),
    scale=0.8,
    color=(1.0, 0.35, 0.05, 1.0),
)
stop_effect(fire, destroy=True)
```

仅能设置所选Niagara系统暴露的参数。Unreal引擎允许向未使用的参数写入数据，因此在批量修改前，建议先预览单个实例的效果。

## Unity相关功能
- 对于已有的粒子预制体或编译后的VFX Graph预制体，调用`SpawnPrefab`即可生成。
- 若没有对应的资产，可调用`SpawnSmoke`、`SpawnFire`、`SpawnExplosion`或`SpawnDust`来生成默认的ParticleSystem效果。
- 针对烟雾翻页特效，需设置`SmokeOptions.particleMaterial`和`textureSheetTiles`。仅在修正转换后的URP材质时才需使用`forceAlphaBlend`；切勿更改插件自带的材质。
- 对于循环播放的烟雾或火焰效果，调用`Stop(root, immediate)`即可停止。
- `SpawnInkSmoke`、`SpawnFrostFire`和`SpawnCyberFire`属于实验性替代方案；经过验证的风格化基准效果仍是上文提到的UE系统。
- 位置与尺寸参数均以米为单位。
- 需引入内置的`com.unity.modules.particlesystem`模块。若精简版项目中该模块被禁用，需将其添加到`Packages/manifest.json`中。

```csharp
using A3Game.EngineAdapters;

GameObject fire = firePrefab != null
    ? A3GameVFX.SpawnPrefab(
        firePrefab, transform.position, transform.rotation, Vector3.one, transform)
    : A3GameVFX.SpawnFire(transform.position, new FireOptions {
        loop = true,
        intensity = 1.2f
    }, transform);

A3GameVFX.Stop(fire);
```

## 结果验证- 至少预览1秒，确保世界时钟正常运转。
- 验证在游戏摄像机的拍摄距离下，特效呈现的效果符合所要求的类别。
- 验证循环类特效会停止播放，一次性特效会自行清理。
- 验证透明烟雾特效使用了Alpha混合渲染，火焰核心则根据情况采用叠加或自发光渲染方式。
- 对于密集的特效群，应使用专门定制的系统，而非大量实例化完整模板。
- 将动态特效绑定到指定的插槽或变换节点上，调整偏移量前需先确认坐标单位。
- 在UE 5.7中，若集成测试需要生成编辑器Actor，请勿使用`-nullrhi`参数，应选用常规RHI。Null-RHI编辑器脚本路径可能会在Python报告异常前就崩溃。
- 在检查颜色、密度、时序、游戏内比例及附着效果前，先以灰度模式查看风格化特效。静态图片无法验证特效的运动节奏。

## 需通过视觉审核

在将烟雾或火焰预设设为基准之前：
1. 渲染一段包含启动阶段和稳定运行状态的固定摄像机视频。
2. 在视频旁记录Niagara/预制体路径、序列、渲染配置、帧率、分辨率和时长信息。
3. 请特效负责人审核其轮廓、颜色、密度、时序和比例是否符合要求。
4. 在负责人批准前，暂不采纳该结果。
5. 将对应的视频和配置本地保存为回归测试的基准。

审核相关的媒体文件请勿存入代码库。获批的公共资源需通过跟踪工单发布。
