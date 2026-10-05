# A3GamePlayable（three.js）

这是为生成的three.js游戏包提供的运行时扩展接口。该框架属于适配器专属框架，是UE5中`A3GamePlayable`插件的网页端对应版本。

请通过公共适配器API安装它，切勿直接复制文件：

```python
from engine_adapters.three_js import ThreeClient

three = ThreeClient(project_path="/path/to/project")
three.plugin.install_framework()
```

## 导入接口

```js
import {
  A3GameRuntimeHost,
  A3GameEnvironmentPreset,
  A3GameAssetLibrary,
  A3GameSceneLoader,
  A3GameInputRouter,
  A3GameLookMode,
  A3GameAnimationDirector,
  A3GameCollisionProbe,
  A3GameHudLayer,
  A3GameMaterialPreset,
  A3GameRuntimeSubsystem,
  A3GameWorldSessionSubsystem,
  A3GameCinematicPlayer,
  A3GameRuntimeEntityComponent,
  A3GameEntityFactory,
  A3GameControllableEntity,
  bootA3GameRuntime,
  createContactShadow,
  createFillLight,
  createInstancedFromModel,
  createMaterial,
  createRoundedBox,
  createSeededRandom,
  createSunLight,
  disposeObject3D,
  fitToHeight,
  forwardAxisYaw,
  groundObject,
  measureObject,
  orientModel,
  prepareModel,
  resolveEntityId,
  A3GameForwardAxis,
  A3GAME_RUNTIME_FORWARD_AXIS,
} from '@a3game/playable';
```

`A3GameCinematicPlayer`会向已配置的浏览器服务端网关提交标准的CG视频任务，等待获取视频资源的URL，并负责管理临时的`<video>`元素。游戏玩法部分决定何时触发视频播放，同时需负责处理播放前后的游戏状态切换。

直接导入`src/`目录下的内容不属于接口范畴。`three`是由宿主项目提供的同级依赖项。

## 选择碰撞体类型

Three.js本身不内置物理引擎，因此`A3GameCollisionProbe`为所有生成的游戏提供了所需的碰撞体类型。选错碰撞体类型是游戏中最常见的BUG：

| 需求场景 | 对应的碰撞体 |
| --- | --- |
| 我脚下是什么？ | `sampleGround` |
| 我能移动到那里吗？ | `resolveMove` / `stepCharacter` |
| 我瞬间击中了什么？ | `hitscan` |
| 我附近有什么？ | `overlapSphere` |
| 我的投射物这一帧飞到了哪里？ | `sweepSphere` |

`overlapSphere`会将没有几何体的目标视为位于其世界坐标处的点，因此空的`Object3D`标记就能用作触发器。`sweepSphere`会检测整个移动路径，因此高速投射物无法穿透薄墙。

## 摄像机设置

`A3GameRuntimeHost`支持两种投影模式。对于横版或等距视角游戏，可传入`cameraType: 'orthographic'`（需指定`frustumHeight`）；也可在运行时通过`useOrthographicCamera()`/`usePerspectiveCamera()`切换投影模式。`setFrustumHeight()`能以极低的成本调整正交视图，甚至可每帧调用。

对于第一人称游戏，若`yaw`/`pitch`值由输入帧决定，应使用`requestPointerLock()`而非`attachPointerLockControls()`：因为`PointerLockControls`会直接操作摄像机，若有两个模块同时争夺对同一摄像机的控制权，就会导致画面抖动。

## 无需美术资源也能呈现出色效果Three.js本身并不提供现成的模型，因此生成游戏的外观依赖于以下代码调用，而非从外部查找资源：

```js
host.setEnvironment({
  preset: 'sky',                // 室内场景可选用 'room'
  sunPosition: sunDirection,
  toneMapping: 'ACESFilmicToneMapping',
  toneMappingExposure: 0.7,
});
host.add(createSunLight({ radius: 120 }), 'lights');   // 适配阴影效果
host.add(createFillLight(), 'lights');
const prop = createRoundedBox({ width: 2, depth: 4, preset: 'painted_metal' });
```

`setEnvironment({ preset })`会利用`RoomEnvironment`或`Sky`着色器在GPU上生成基于图像的照明效果——无需`.hdr`文件，也无需额外授权。这一操作的重要性远超其他任何调用：如果没有环境贴图，基于物理的渲染（PBR）材质就没有反射对象，无论光照如何设置，看起来都像普通的塑料。

之所以存在`createSunLight`函数，是因为默认的`DirectionalLight`阴影相机是以原点为中心的10米立方体，因此大型地图根本无法产生正确的阴影；此外它优先使用随几何体缩放的`normalBias`，而非仅在特定距离下才生效的固定`bias`值。

`A3GameMaterialPreset`能让材质属性更符合物理规律：表面要么是导体，要么不是，因此绝缘体的`metalness`值始终为0，其光泽感由`clearcoat`参数决定。

## 导入的模型

`GLTFLoader`输出的模型无法直接用于场景，因此两个加载辅助工具都会自动为你执行`prepareModel`操作：

```js
// 从零开始构建的内容：直接使用模型，或使用基础几何版本。
const built = await assets.instantiateOrBuild('robot_expressive',
  () => buildPrimitiveBody(), { height: 1.8, ground: true });

// 正在升级的现有内容。
const loaded = await assets.tryInstantiate('fox', { height: 0.85 });
if (loaded) entity.setVisual(loaded.object, loaded.animations);
```

有两个问题在glTF层面没有解决方案，因此会在该处处理：
- **缩放问题**：每个模型采用的单位都是作者自定义的，因此应通过`height`参数来标准化缩放，而非使用固定的魔法数值。如果适配器记录了`scale_hint_metres`参数，就会将其作为默认缩放值；
- **阴影问题**：glTF格式无法表达`castShadow`属性，因此所有网格的该属性默认都为`false`。

还有第三个在glTF层面同样没有解决方案的问题，且与前两个问题不同，它甚至无法被检测出来：
- **朝向问题**：面向+Z轴建模的模型和面向-Z轴建模的模型会生成完全相同的文件。框架的约定是**局部前向 = -Z**，这与`Math.atan2(-x, -z)`的计算结果一致，而清单文件中的`orientation.forward_axis`参数会标明模型的真实朝向。修正操作会在包裹模型的`Group`内应用，你最终拿到的就是经过包裹后的模型——因此无法通过修改`visual.rotation.y`来调整游戏中的朝向。若要覆盖默认设定，可使用`{ forwardAxis: '+x' }`参数；若想跳过朝向修正，可使用`{ orient: false }`。

  ```js
  // 当游戏逻辑比清单文件的设定更可靠时，可采用等效写法：
  orientModel(model, { forwardAxis: '+z' });        // 原地旋转模型
  forwardAxisYaw('+z');                            // 结果为 Math.PI
  ```如果没有任何记录，就不会有旋转：未标注的资源表现与存在该机制之前完全一致。

对于骨骼动画角色，需将 `frustumCulled` 设为 `false`，否则该角色会基于其绑定姿势边界被剔除，从而在屏幕边缘消失不见。

## 同一模型的多个副本

一个角色对应一个模型；场景中的74棵树各自对应一个模型，若为每个放置位置都实例化一个生成的物体，就会让游戏运行变慢——而非保持流畅——因为这会产生74次绘制调用，以及数万个三角形的74个副本。

```js
const loaded = await assets.tryInstantiate('explorer_pine', { height: 9 });
const trees = createInstancedFromModel(loaded.object, placements.length);
if (trees) {
  placements.forEach((holder, index) => {
    trees.setMatrixAt(index, matrixFor(holder));
    holder.visible = false;       // 将其保留为碰撞体积
  });
  trees.instanceMatrix.needsUpdate = true;
  host.add(trees, 'environment');
}
```

`createInstancedFromModel` 会将源模型的变换信息烘焙到几何体中，因此已设置好 `height` 属性的模型会保持其实际尺寸，每个实例矩阵仅用于指定副本的位置。对于骨骼动画模型或多部件模型，该函数会返回 `null`，而非将其展平处理——毕竟运行时才发现骨架丢失可不是什么好事——这样调用方仍能继续渲染原有内容。

隐藏原始几何体而非直接删除才是关键：`Raycaster` 不会检测 `visible` 属性，而 `Mesh.raycast` 仅需材质即可工作，因此一个不可见的盒子仍能阻挡移动、拦截射线检测，其成本远低于美术资源。看起来坚固的遮盖物依然能发挥遮挡作用。

## 帧更新顺序

`A3GameRuntimeSubsystem.onWorldBeginPlay()` 会安装负责将队列中的输入传递给实体的帧更新函数。务必在该函数之前注册 `input.pipeToSession()`——以及所有需要排队处理帧的AI逻辑——否则每帧输入都会延迟一帧到达。`bootA3GameRuntime({ autoBeginPlay: false })` 会将这一顺序控制权交给游戏本身。

## 资源是可选的

`A3GameAssetLibrary.load()` 能容忍清单文件缺失的情况，并将原因记录在 `warnings` 中，因为程序化生成的游戏无需导入任何资源。在调用资源前请先检查 `assets.available`，或者当游戏确实无法在没有导入内容的情况下运行时，传入参数 `requireManifest: true`。

## 框架所管辖的内容

| 层级 | 职责 |
| --- | --- |
| `data-types/` | 通用的运行时数据协议，Python端和浏览器端的传输格式一致 |
| `interfaces/` | 游戏逻辑实现所需的三个接口 |
| `components/` | 附加到 `THREE.Object3D` 上的运行时标识与实体状态 |
| `subsystems/` | 会话管理、输入仲裁、运行时协调 |
| `engine/` | 渲染器、帧循环、资源清单、世界场景图、输入系统、动画模块、射线检测探针、HUD、控制通道 |

## 框架不管辖的内容不包含角色、pawn、控制器、游戏模式、HUD内容、武器、载具、战斗规则、计分规则或游戏专属的输入映射。这些内容均由生成的Gameplay Package负责处理。

## 最简化的生成游戏逻辑

```js
import * as THREE from 'three';
import {
  A3GameControllableEntity,
  A3GameEntityFactory,
  A3GameRuntimeEntityComponent,
} from '@a3game/playable';

class MyPawn extends A3GameControllableEntity {
  constructor(object) {
    super();
    this.object = object;
    this.runtime = new A3GameRuntimeEntityComponent(object);
  }

  getRuntimeEntityId() {
    return this.runtime.entityId;
  }

  setRuntimeEntityId(entityId) {
    this.runtime.setRuntimeEntityId(entityId);
  }

  applyRuntimeInput(inputState) {
    // 具体的移动规则应在此处实现，而非写在框架中。
    return this.runtime.applyRuntimeInput(inputState);
  }

  getRuntimeSnapshot() {
    return this.runtime.getRuntimeSnapshot();
  }
}

export class MyEntityFactory extends A3GameEntityFactory {
  async spawnRuntimeEntity(request, { host, assets }) {
    const { object } = await assets.instantiate(
      request.parameters.avatarArtifactId,
    );
    host.add(object, 'entities');
    return new MyPawn(object);
  }
}
```

## 资源管理规范

Three.js不会自动释放GPU内存。每个实体都必须自行释放其几何数据、材质和纹理；`disposeObject3D(root)`函数可用于遍历并清理这些资源。忘记执行此操作是生成的网页游戏中最常见的故障原因。

另一个不易察觉的陷阱是：射线检测会读取`matrixWorld`属性，而渲染器仅在渲染阶段才会更新该属性。如果某个物体在同一帧内既产生移动又被用于射线检测，必须先调用`object.updateMatrixWorld(true)`，否则检测位置会停留在物体的初始位置。
