# 动作与特效参考

生成的三维游戏需要两项three.js本身并不提供的功能：**导入角色的动作**，以及**粒子特效**。本套资料仅作为这两项功能的只读参考。其中内容不会自动安装，生成的游戏必须根据自身游戏逻辑包的特点来调整相关实现方式。

| 文件 | 阅读目的 |
| --- | --- |
| `src/motion.js` | 让生成的角色能够移动，同时排除无法移动的角色 |
| `src/effects.js` | 批量处理粒子、追踪光束、投射物尾迹以及受强度驱动的流体效果 |

## 为何存在这份资料

这两部分内容旨在纠正两种极易发生却难以察觉的错误。

**动作方面**：对于*下载*的角色而言，`assets.tryInstantiate`的用法是正确的，但对于*生成*的角色来说却完全行不通。图像转3D技术会生成一个融合体，因此清单条目中会显示为`animations: []`且`skinned: false`。如果游戏用这类模型替换掉原有的程序化生成的角色，得到的角色虽然外观精美却无法移动——其表现甚至还不如被替换掉的胶囊体模型，因为原本用于设定姿势的简易肢体在替换后便不复存在了。

**特效方面**：每个火花对应一个`Sprite`，这意味着每个火花会产生一次绘制调用，还需额外的动画循环，且不会产生任何资源释放操作；因此战斗越激烈，帧率下降就越明显。

## 通过适配器导入动作

动作与其他资源一样，是通过仓库任务标识来加载的——绝不要通过文件系统路径加载：

```python
from engine_adapters.three_js import ThreeClient

three = ThreeClient(project_path="/path/to/project")

# 由pipeline/assets_gen/gen_motion生成的剪辑
three.assets.import_motion(
    {"game_id": "game_fps_pistol_arena", "run_id": "default",
     "task_kind": "assets", "task_id": "trooper_walk"},
    options={"asset_id": "trooper_walk"},
)

# 或者通过Animation命名空间针对目标骨架进行导入，该过程还会返回该剪辑是否无需重新定位就能驱动对应角色的信息：
three.animation.import_motion(task_identity, options={"asset_id": "trooper_walk"})
three.animation.resolve_skeleton("arena_trooper")
three.animation.validate_compatibility("arena_trooper", "trooper_walk")
```

导入的动作会被存放在`public/assets/imported/motions/`目录下，并在清单中标记为`type: "motion"`。`A3GameMotionLibrary`负责在运行时查找这些动作文件——动作文件包含剪辑数据，通常还包含骨架信息，但不包含可渲染的实体，因此无法通过`instantiate()`方法直接调用。

完整的生成流程在`agent_skills/asset_qa/motion_gen_skills.md`中有详细说明：首先用Puppeteer进行骨骼绑定，接着用MoMask生成动作数据，或获取授权许可的剪辑；之后通过Blender的`world_delta`步骤进行动作重定向，再用`inspect_fbx`验证，若`pose_animated`字段值为false则予以拒绝。在导入前需将重定向后的FBX文件转换为glTF格式：FBX格式虽能在浏览器中加载，但会触发警告提示，而glb才是运行时使用的格式。

## 通过适配器导入特效内容在其他地方制作的效果——纹理图集、翻页动画、JSON格式的效果描述——可通过`import_effect`指令导入：

```python
three.assets.import_effect(
    {"game_id": "game_archer_explorer", "run_id": "default",
     "task_kind": "assets", "task_id": "spark_atlas"},
    options={"asset_id": "spark_atlas"},
)
```

导入后的文件会存放在`public/assets/imported/effects/`目录下。如果是纹理图集类型的效果，需将加载的纹理作为`map`参数传给粒子系统，同时指定翻页动画对应的行数和列数。

大多数效果根本无需导入，这也是设计初衷：形状遮罩是在片段着色器中实时计算的，因此火花、枪口闪光、烟雾效果无需额外下载，也不存在版权限制。只有当需要特定预设的外观时，才需要导入效果。

## 运行时API

以下所有内容均来自`@a3game/playable`：

```js
import {
  createAnimatedActor,      // 一次调用即可创建完整的动作链
  A3GameMotionLibrary,      // 标记为`type: 'motion'`的资源
  autoRigHumanoid,          // 将骨骼适配到静态的人形网格上
  createHumanoidClipSet,    // 预先制作好的行走/奔跑/出拳/踢击/瞄准/射击等动作剪辑集
  retargetClipToSkeleton,   // 将动作轨迹重命名后应用到另一套骨骼上
  measureHumanoid,          // 判断该网格是否为站立的人形模型？
  createVfxDirector,        // 负责统一管理所有效果的批次处理器
  A3GameVfxPreset,          // 经过调优的效果定义
  A3GameParticleSystem,     // 可复用的粒子效果，单次绘制调用即可渲染
  A3GameBeamEffect,         // 可复用的光束追踪效果
  A3GameTrailRibbon,        // 投射物身后留下的连续拖尾效果
} from '@a3game/playable';
```

### 一键完成动作配置

```js
const actor = await createAnimatedActor(assets, 'arena_trooper', {
  height: 1.8,
  ground: true,                       // 以脚部为基准定位，而非模型的原点
  states: ['idle', 'walk', 'run', 'aim', 'shoot', 'hit', 'death'],
  defaultState: 'idle',
});

if (!actor || actor.motionSource === 'none') {
  // 保留程序生成的身体模型。它能移动，而导入的模型则不能。
} else {
  entity.setVisual(actor.object, actor.animations, {
    animator: actor.animator,
    motionSource: actor.motionSource,
  });
}
```

`motionSource`的取值包括`clips`、`imported_motion`、`auto_rig`或`none`，上述每个分支都至关重要。`none`取值对应那些比例不符合人形站立特征的网格——这类网格通常是重建过程中临时生成的地面平面——正确处理这种情况，决定了游戏画面是呈现为动态效果还是永远静止不动。

### 用列表而非单个名称来映射动作剪辑

```js
animator.mapStateChains({
  idle: ['idle', 'Idle', 'Standing'],
  attack: ['aim', 'ThumbsUp', 'Idle'],
});
```

预设的动作集中将射击姿势命名为`aim`；而CC0授权的`robot_expressive`角色模型包含14个动作剪辑，其中并没有名为`aim`的剪辑。如果仅使用单个名称映射，那么上述两种来源的动作都无法正常播放。

### 效果处理

```js
const vfx = createVfxDirector({ host, presets: { … } });   // 绑定到游戏帧更新逻辑中
``````javascript
vfx.play('bullet_impact', { position: hit.point, direction: hit.normal });
vfx.fireBeam('player_tracer', muzzleWorldPosition, hit.point);
const handle = vfx.follow('tyre_smoke', rearAxleMarker, { rate: 90 });
```

三种特效的放置规则决定了它们能否正常显示：

1. **爆炸特效会沿着表面法线方向扩散**，而非沿子弹飞行方向。如果火花继续向墙壁内部扩散，就无法被看到，因此 `A3GameCollisionProbe.hitscan` 会返回一个世界空间中的法线向量。
2. **曳光弹特效从枪口发射**，而非从摄像机位置发射。从眼睛位置绘制的线条会位于近平面之内，因此不可见。
3. **拖尾特效不会绑定到它所跟随的物体上**。若拖尾特效绑定了父物体，就会被该物体拖动，从而无法在物体后方形成拖尾效果；`follow()` 函数只会移动发射器，而让粒子留在世界空间中。

## 边界限制

该框架由适配器所有：生成的游戏无法修改它，不能深度导入 `@a3game/playable/src/...`，也不能依赖此示例包。特效仅用于装饰，绝不能承担承重功能——如果调用 `play()` 时传入未注册的特效名称，会返回 `0` 而不会抛出异常，因此缺失的特效绝不会成为命中检测失效的原因。
