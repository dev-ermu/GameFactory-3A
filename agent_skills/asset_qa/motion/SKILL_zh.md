# 动作生成

从校准后的网格投影和连续的VLM关节标注中重建骨骼，随后拟合关节并设定蒙皮权重。通过逆向运动学（IK），根据关节位置轨迹、节奏及接触约束生成动作；再针对具体动作调整骨骼朝向，最后导出动作数据，在目标网格上进行重定位与验证。

请将`<...>`形式的路径占位符替换为实际路径；`<repo_path>`代表代码库根目录。

入口文件：`<repo_path>/pipeline/assets_gen/gen_motion/run.py`。
操作符文件：`<repo_path>/operators/gen_motion/operator.py`。
修改任何内容前需先阅读的参考文档：本文件，以及`<repo_path>/operators/gen_motion/funcs/`下的模块文档说明。

## 优先使用Vibe Motion功能

优先调用`<repo_path>/operators/gen_motion/funcs/vibe_motion_utils/`中的函数；仅当模型拓扑结构或动作不受支持，或经过质量检查（QA）未达标时，才考虑改用Mixamo、MoMask或Tripo生成工具。

1. 需提供明确的关节位置轨迹、命名后的节奏事件、静止状态下的骨骼模型以及IK约束。在选择其他数据源前，请先调整该程序的相关参数。
2. 需检查骨骼长度、地面穿透情况、接触速度、IK残差以及蒙皮权重；在目标网格上回放生成结果。若`vibe_motion_utils`中存在可复现的功能漏洞，需先修复，再通过`GenMotionOperator`重新运行。
3. 若模型拓扑结构或动作仍不受支持，或结果仍未通过QA检查，可使用**Mixamo/本地动作捕捉数据**或**直接生成工具**（MoMask/Tripo）。需记录下采用替代方案的原因、参数以及数据源/授权信息。切勿悄悄用其他预设动作替换用户请求的动作。

### 入口点与适用范围

| 功能 | 用途 |
|---|---|
| `skeleton.fit_skeleton(mesh, config=...)` | 使用完整且明确的拟合参数设置来拟合骨骼 |
| `skinning.skin_mesh(mesh, rig, config=...)` | 根据指定的核函数、骨骼约定及平滑设置生成蒙皮权重 |
| `motion.build_plan(skeleton, rhythm=..., program=...)` | 验证完整的轨迹程序，并绑定命名后的关节链 |
| `motion.generate_clip(plan)` | 采样位置数据，通过IK算法求解关节运动 |
| `generate_vibe_motion(config=..., mesh=...)` | 生成BVH文件、关节数据、目标数据、残差信息，以及可选的骨骼/蒙皮/GLB格式产物 |

需将多阶段动作表述为包含命名事件和接触窗口的连续位置程序。`program.action`是一个标签，而非预设动作选择器。

IK实现代码路径：`<repo_path>/operators/gen_motion/funcs/vibe_motion_utils/motion_utils/generate.py`。对于屈曲受限的双骨链，使用`solve_two_bone_ik`函数；对于肩部/肘部受限情况的优化，使用`solve_arm_ik`函数；`task_space.solve_part`用于提供采样后的目标点。

使用时需指定`task_type="vibe"`，并传入包含相关参数的`config`对象：- `骨架`：包含明确的`名称`、`名称列表`、`父节点`以及世界空间中的`静止`位置。
- `节奏`：包含`持续时间`、`帧率`，以及归一化时间下的命名`事件`。持续时间对应的帧率必须为整数；动画片段包含起始和结束端点，总帧数为`持续时间 × 帧率 + 1`。
- `程序`：包含`动作`、`水平前进`方向、根节点位置曲线、命名的`部件`、`求解器`设置以及`质量`阈值。缺失的设置属于错误，而非默认值。

曲线包含`关键帧`、`数值`以及明确的`插值`模式：`PCHIP`、`Hermite`、`线性`或`平滑`。使用Hermite模式时还需提供`斜率`，其单位为归一化时间单位。关键帧可引用节奏事件、`起始点`或`终点`。所有空间尺度均需明确指定。坐标系统采用Y轴向上的约定；局部动画四元数采用wxyz格式，与BVH/GLB适配器兼容。

支持的部件操作符如下：

- `位置`：世界坐标系、根节点坐标系或父节点坐标系下的末端执行器轨迹，包含明确的极点/静止极点方向及弯曲范围；支持三关节或四关节链。`朝向`可设置为`身体朝向`、`静止朝向`，或基于静止状态的Y轴偏航角度的显式标量曲线。在支撑阶段保持该曲线恒定可锁定脚部朝向。位置/接触IK的极点使用根节点到身体的轴线；瞄准极点则使用选定的目标空间。`静止极点`始终采用原始的世界空间静止基准。
- `接触路径`：独立计时的支撑窗口、明确的锚点采样时间，以及每个间隙对应的一个身体坐标系下的摆动偏移量。接触朝向可被锁定。
- `手臂弧线`：带有肩部/肘部IK约束的任务空间手腕弧线。极角描述的是手腕位置，而非预设的关节旋转角度。所有优化器设置和关节范围均需明确指定。
- `瞄准`：用于轴向链的子关节位置追踪，可保持骨骼长度不变。
- `静止`：明确保留局部的静止姿势。

关节链是根据提供的骨架解析而成，而非基于硬编码的人体名称。双足和四足动物的示例，包括所有运动参数和合成骨架数据，分别存放在`<repo_path>/test/vibe_motion_examples/horse_gallop_stop_kick.json`和`<repo_path>/test/vibe_motion_examples/turn_jump_chop.json`中。后者将飞行过程编码为显式的Hermite位置关键帧，而非内置的跳跃算法。可将示例JSON加载到`config`中，再将其与`task_type="vibe"`、`game_id`和`task_id`一同传给`GenMotionOperator.run`。

对于真实网格，需提供`target_mesh_path`、`rig_quality`和`export.text`（包含`精度`、`求和容差`、`最大影响数`参数）。既可提供对应的骨架，也可设置`skeleton=null`并搭配完整的`rigging`配置。若要生成带蒙皮的GLB文件，还需额外提供`skinning`、`skin_quality`以及`export.glb`（包含`绑定容差`、`求和容差`、`材质`、`插值`参数）。
不会自动加载任何生物几何体、骨骼预设或蒙皮预设。对于FBX文件，可使用`vibe_retarget`，配合相同的网格/蒙皮设置、整数节奏帧率以及bpy运行时环境。网格测试代码位于`<repo_path>/tests/test_vibe_rigging.py`。

### 必需的视觉骨骼绑定工作流程对于未绑定骨骼的模型，请按照以下顺序处理：

**3D模型 → 投影图像 → 基于VLM的顺序识别与标注 → 3D骨骼 → 蒙皮 → 根据运动效果优化骨骼方向。**1. **加载原始网格。** 利用任务输入对其进行归一化处理，记录其摘要、归一化参数以及实际处理后的几何形态标识。切勿用参考骨骼替换原始网格、把已绑定资源的模型谎称为未绑定模型，也不得修改源数据。
2. **渲染校准后的投影图像。** 调用 `rigging_utils.estimation.prepare_projection`。根据网格边界、指定的视图轴、图像尺寸和填充参数，计算出实际的相机中心、像素原点以及通用的像素/单位比值。使用带深度缓冲的原始三角形来生成图像。将生成的图像以及 `projection/calibration.json` 文件保存到运行输出目录下。切勿要求视觉语言模型（VLM）自行猜测相机矩阵。
3. **按顺序识别并标注。** 调用 `estimate_rigging`，传入具备真实视觉能力的估算器。需传入的是经过标注的实际视图图像以及计算出的校准参数，而非仅文件名或文本。首先根据指定的控制链约束推断父子关节的关联关系；随后按输入顺序为每个关节链发起一次请求。将此前验证通过的结果传递给下一次请求。估算内部关节中心位置，保留几何不对称性，针对每个观测到的视图记录对应的像素坐标、置信度以及推断结果。不支持的视图予以忽略；每个关节至少需要两个独立的观测视图数据支撑。绝不要凭空编造可见性信息，也不得镜像呈现被遮挡的肢体。将每次请求的内容及原始回复分别保存为 `estimation_00.json`、`estimation_01.json` 等文件。若回复内容被拒绝、截断、无效、退化或不一致，直接驳回，不得回退到旧坐标值。在推进流程前，需验证拓扑结构、像素边界、加权重建的秩/条件数以及每个视图的重投影误差是否符合要求。只有所有阶段均通过后，才能生成并发布 `annotations.json` 和 `resolved_rigging.json`。
4. **重构并拟合骨骼。** 将解析完成的结果传入 `skeleton.fit_skeleton`。拟合过程需在输入的窗口范围内进行；若存在几何/标注冲突需明确报告。需区分闭合凸多面体认证、开放网格封装以及启发式奇偶性验证三类情况。切勿为了凑合而强行将关节吸附到皮肤表面。
5. **生成皮肤权重。** 应用调用方选定的影响集与软先验，再针对实际网格边缘进行筛选扩散处理，并以精确锚点作为约束。将这些参数以 `allowed_bones`、`weight_bias`、`anchors` 的形式传入 `skinning.skin_mesh`，或通过 `config.skin_constraints` 配置。需明确指定 `screening` 和 `edge_epsilon_ratio` 参数；绝不要在不相连的曲面之间添加邻近关联。示例中针对特定资产的物体选择器和接缝选择器属于任务约束，并非模型预测结果。
6. **利用动作调整骨骼朝向。** 若启用 `--with-motion` 参数，调用 `<repo_path>/tests/test_vibe_motion.py` 来生成明确的位置/节奏/IK动作数据。在比较静止极点候选位置和预弯曲候选位置时，需保持皮肤权重与动作设置不变。只有能同时满足几何约束与重投影误差要求的优化结果才会被采纳。一旦静止关节发生变化，需重新计算绑定矩阵。导出相关结果。读取GLB格式的几何数据、权重及动画信息；保留未通过的QA指标。

将`<repo_path>/test/vibe_motion_examples/rigging_example.json`作为简短的任务请求：其中包含视图生成设置、所需的骨骼链名称及其含义、拟合与蒙皮参数、动作约束及容差要求。所要求的骨骼链名称属于输出模式的约束条件，并非推断出的骨架结构。请勿在此输入目录中存储实际的校准数据、估算的像素坐标、置信度数值、推断出的拓扑结构或生成的3D关节信息。所有这类中间结果、原始模型响应、解析后的设置、权重数据、诊断信息及视频文件应存储在`<repo_path>/test_data/outputs/`目录下。仅将旧有的估算结果作为有明确标识的历史输出保留；切勿将回放数据或测试存根标记为全新的VLM运行结果。VLM的估算结果并不等同于解剖学上的真实情况。

### 运行或检查估算阶段

使用现有的命令行工具，每条命令需写在单行中：
- 无需网络调用即可准备图像：`python -m test.test_vibe_rigging rig-mesh --input "<mesh_path>" --output-dir "<output_dir>" --prepare-only`。此操作应记为投影准备阶段，而非已完成的估算或绑定流程。
- 运行真正的估算流程及后续动作：`python -m test.test_vibe_rigging rig-mesh --input "<mesh_path>" --output-dir "<output_dir>" --with-motion --ffmpeg "<ffmpeg_path>"`。也可选择性地通过`--config "<repo_path>/test/vibe_motion_examples/rigging_example.json"`指定简短的任务请求。该命令行工具仅会添加`<repo_path>/tests/test_vibe_rigging.py`中已声明的测试端QA/导出设置；生产环境中的功能并不会提供默认的资产参数。
- 显式回放已完成的估算结果：添加参数`--annotations "<annotations_path>"`，填入实际已完成的注释文件路径即可，无需指定固定的父目录。同时保留其同级的`projection/`相关文件，并选择新的`<output_dir>`。需验证源网格与处理后的网格摘要、归一化参数、任务信息、投影设置、校准数据及图像哈希值。若更改了模型或任务内容，则需重新进行估算。此操作属于回放，并非新的模型调用。请配置 `VIBE_VLM_BASE_URL`（如需的话需包含 `/v1` 的兼容OpenAI协议的HTTPS API地址）、`VIBE_VLM_MODEL`（支持JSON对象聊天输出的视觉模型）以及 `VIBE_VLM_API_KEY`。前两个参数可通过 `--vlm-base-url`/`--vlm-model` 覆盖；若想使用已有的凭证变量，则使用 `--vlm-key-env`。切勿随意选择提供商或模型、将密钥存入JSON文件，也勿打印凭证值。API传输依赖 `models.common.cloud_api`，且需要安装 `requests`；投影功能则需要 Pillow。上传本地投影数据或产生API费用前，请先获取必要授权。正常的API运行流程为一次拓扑请求加上每条链条对应的一次请求。若缺少相关配置，应输出可操作性的错误信息并终止程序，或选择仅准备模式；切勿凭离线测试结果宣称实现了真正的视觉验证。运行失败时请保留部分回复内容，修正后再将结果写入新的输出目录，切勿覆盖已有的输出文件。若下游质量检测未达标，程序将返回非零退出码，同时保留相关产物。

数值计算运行时需要 NumPy 和 SciPy；输入网格文件还需用到 trimesh。
运行运动回归测试套件，可执行：
`python -m unittest discover -s "<repo_path>/test" -t "<repo_path>" -p 'test_vibe_motion.py' -v`。

若要导出骨骼测试视频，可使用：
`python -m test.test_vibe_motion export-videos --ffmpeg "<ffmpeg_path>"`。
这种明确的预览模式需要 Pillow，不会干扰普通测试的产物生成，生成的MP4文件和数值报告会保存在
`<repo_path>/test_data/outputs/_GPT6_astra_test/vibe_motion_refine260927` 目录下。
可通过 `--output-dir` 指定其他的测试输出位置。这些骨骼预览并非带皮肤的角色模型，也无法代表物理模拟的真实性。

请查看 `vibe_report_path`，若是网格相关任务，还需查看 `skin_report_path` 和 `rig_report_path`。报告中会记录完整的程序运行信息、事件时间、原始目标残差、接触速度、骨长误差、地面穿透情况以及优化器故障信息。质量阈值由输入参数决定。无法到达的目标会被投影到关节限制范围内并予以记录，绝不会通过拉伸骨骼来掩盖问题。这些属于运动学检查，并非平衡性、自碰撞或视觉质量的验证依据；接受结果前需在真实网格上重新播放动画确认。

### 备选方案

- **Mixamo / 本地动作捕捉：** 若有匹配的剪辑可使用该方案。下载 Mixamo FBX Binary格式文件，选择“无皮肤”选项，然后设置 `task_type=retarget`、`motion_source=mixamo`，对于厘米单位的剪辑初始可设 `global_scale=0.01`。
- **MoMask / Tripo：** 若缺少库动作数据或需要临时替代方案，可选择该方案；交付前请检查生成的姿势、时序、接触情况和循环逻辑是否符合要求。
- 请遵守访问限制和许可协议；对于需要登录才能访问的资源，请手动下载。每种备选方案都要记录其来源信息。

## 云端备选方案（Tripo）

设置 `task_type=cloud_rig` / `cloud_humanoid` 可在 TokenHub / Tripo 后端执行骨骼绑定和动画生成操作。
相关代码位于：`<repo_path>/operators/gen_motion/funcs/cloud_rig_animate.py`、
`<repo_path>/models/gen_motion/tripo_rigging_model.py`。仅在Vibe Motion不适用或未能通过QA时，才使用此路由。每次生成的骨骼绑定可能有所不同，动画则采用固定的预设库。请直接在目标网格上检查骨骼绑定和动画片段，而不要想当然地认为API调用成功就代表动画质量合格。

需遵循的限制条件如下：

- `input`参数仅接受**公开的http(s) URL**；不支持上传端点，`data:`格式的URI会被拒绝。
- 动画生成依赖于骨骼绑定的**任务ID**（有效期为24小时），而非文件本身。
- 指定`spec="mixamo"`的文件无法用于动画制作——需使用`spec="tripo"`格式的文件来制作动画。
- `rig_type`（双足/四足/六足/八足/鸟类/蛇形/水生）应通过`rig-check`接口获取；预设类型必须与之一致。
- 每次调用都会产生费用，包括处理失败的网格以及额外的尝试次数所产生的费用。

在发布前需先对结果进行校验：`inspect_rig`（确保肢体链已正确解析）和`inspect_animation`（确保关节旋转角度不超过150°）。这两个校验工具位于`<repo_path>/models/gen_motion/tripo_rigging_model.py`中；操作人员需将其与生成的结果文件一同存放。

**切勿**对运动相关的FBX文件使用静态网格导入器（`<repo_path>/engine_adapters/blender/import_generated/import_mesh.py`或`<repo_path>/engine_adapters/ue5/import_generated/import_mesh.py`），因为这些工具会合并网格并丢弃骨骼信息，从而导致动画无法播放。

## 格式说明（为何运动数据特殊）

| 阶段 | 常用格式 | 备注 |
|---|---|---|
| 角色网格 | `.glb`、`.gltf`、`.obj`、`.ply`、`.stl`（重定位时使用`.fbx`） | 顶点顺序必须与Puppeteer骨骼绑定的OBJ文件一致 |
| 运动片段 | `.bvh`、`.fbx` | Mixamo生成的FBX文件常以厘米为单位；MoMask格式的BVH文件则以米为单位，帧率为20帧/秒 |
| 映射关系 | JSON格式的骨骼映射表 | 该表根据Puppeteer骨骼绑定生成，无法在不同角色间复用 |
| 引擎输出 | `.fbx`（包含完整模型及动画数据） | 用于Blender或UE的骨骼导入，非静态网格 |

不同库中的骨骼命名规则也有所差异（如Mixamo使用`mixamorig:*`，UE的人体模型使用`pelvis`/`*_l`，CMU有专用命名规则，SMPL的命名存在偏移）。源配置文件存储在`mapping_presets.SOURCE_SKELETONS`中；BVH格式的识别由宿主端完成，FBX格式则需借助bpy库或`mapping_auto`工具处理。

如果操作人员无法处理合法的剪辑格式、缩放规则或重定位相关需求，应在代码库中扩展`fetch_motion`、`formats`、`mapping_auto`或`world_delta`模块，并将相关任务保留在流水线中——切勿使用未经审核的自定义Blender脚本，这类脚本不会纳入`<repo_path>/operators/`目录。

## 任务类型| `task_type` | 所需输入 | 生成结果 |
|---|---|---|
| `vibe` | 配置：骨骼 + 节奏 + 位置程序；可选网格/蒙皮数据 | BVH文件、关节数据、QA报告；包含几何信息的绑定好的模型/OBJ文件/蒙皮报告 |
| `vibe_retarget` | 相同的配置 + 网格数据 + 蒙皮/导出设置 + 整数帧率 + bpy库 | Vibe生成的动画产物 + 重定位后的FBX文件/动画/映射数据 |
| `rig` | 角色网格数据 | `rig.txt`、`skeleton.txt`、`mesh.obj` |
| `text_to_motion` | 文本提示词 | `motion.bvh`文件（+原始数据/IK数据/预览数据） |
| `retarget` | 源动画片段 + 网格数据 + 绑定好的骨骼 | `retargeted.fbx`、`animation.fbx`、`mapping.json` |
| `humanoid` | 网格数据 + 提示词 | 上述所有步骤的结果，按顺序串联处理 |
| `cloud_rig` | `mesh_url` | 绑定好骨骼的网格数据 + `rig_report.json`报告 |
| `cloud_humanoid` | `mesh_url` + 预设参数 | 绑定好骨骼且带有动画的网格数据 + 相关报告 |

CLI演示（单个任务）。首先加载运行时环境，然后传入[运行时环境](#6-运行时环境)中列出的明确模型参数：

```bash
# 备用方案：将Mixamo下载的动画适配到已有的绑定骨骼上
python "<repo_path>/pipeline/assets_gen/gen_motion/run.py" \
  --task-type retarget \
  --source-motion "<source_motion_path>" \
  --target-mesh "<mesh_path>" \
  --target-rig "<rig_path>" \
  --motion-source mixamo \
  --global-scale 0.01

# 完整流程：从网格生成动画，再输出为FBX格式：网格 → 绑定骨骼 → MoMask处理 → FBX
python "<repo_path>/pipeline/assets_gen/gen_motion/run.py" \
  --task-type humanoid \
  --target-mesh "<mesh_path>" \
  --prompt "一个人向前行走并挥手。" \
  --in-place
```

查看映射关系和动画源注册表：

```bash
python "<repo_path>/pipeline/assets_gen/gen_motion/run.py" --list-mappings
python "<repo_path>/pipeline/assets_gen/gen_motion/run.py" --list-motion-sources
```

## 1. 骨骼绑定

对于兼容的几何数据，优先使用Vibe的`fit_skeleton`和`skin_mesh`功能。如果程序化拟合无法满足任务需求，则采用下方的Puppeteer方案。

**模型路径：** `<repo_path>/models/gen_motion/puppeteer_model.py`（实际运行需依赖CUDA）。
**操作步骤：** `<repo_path>/operators/gen_motion/funcs/rig_character.py`。

支持的网格格式：`.glb`、`.gltf`、`.obj`、`.ply`、`.stl`（重定位时支持`.fbx`格式）。该操作器同时接受`target_mesh_path`和旧版的`target_glb_path`参数。

**不可破坏的约定：** Puppeteer生成的`skin`数据是通过网格中顶点的索引来定位顶点的。因此绑定的产物会包含对应的OBJ文件。重定位过程是基于相同的顶点顺序来分配权重——任何在绑定骨骼和重定位阶段导致顶点顺序变化的转换，都会直接破坏蒙皮效果。

无需CUDA即可进行的简易测试：从`<repo_path>/tests/harness/stubs.py`中引入`StubPuppeteerModel`即可。

## 2. 动画生成

**模型路径：** `<repo_path>/models/gen_motion/momask_model.py`。
**操作步骤：** `<repo_path>/operators/gen_motion/funcs/generate_motion.py`。

在经过参数调整和QA检测后，如果[Vibe Motion](#prefer-vibe-motion-functions)仍无法满足任务需求，可将MoMask作为备选方案。若现有的动作捕捉片段能满足性能要求，则优先选用该片段。- 原生帧率为**20帧/秒**。将该帧率直接传递给重定位模块；将20帧/秒的剪辑以30帧/秒导出时，动画播放速度会过快，但不会出现“画面错乱”的情况。
- 优先使用HumanML3D风格的语句描述（如“一个人向前走并挥手”），而非标签列表。
- 当游戏本身负责控制角色移动，而该动画剪辑仅需呈现行走外观时，需设置`in_place=True`。
- 不要指望能针对动画的时序、风格、脚部接触效果或循环逻辑进行提示词级别的控制。如果某个方案需要特定的动画表现，应直接下载对应结果，而非重新生成随机种子。

<a id="when-generation-quality-is-not-enough"></a>

### 动作来源（Vibe Motion之后的备用选项）

与其纠结于提示词设置，不如直接使用`<repo_path>/operators/gen_motion/funcs/fetch_motion.py`来获取动作。

| 来源 | 获取方式 | 骨骼模型 | 说明 |
|---|---|---|---|
| `mixamo` | 手动下载（需登录） | Mixamo | 首选的备用动作库；需下载FBX Binary格式文件，选择“无皮肤”选项 |
| `mocap_online` | 手动下载 | UE5人体模型 | 免费示例动作包 |
| `cmu_bvh` | 通过直接URL下载 | CMU BVH | 免费资源；动作质量参差不齐 |
| `bandai_namco` | 通过直接URL下载 | — | 遵循CC BY-NC-ND协议——仅可用于研究 |
| `local` | 从本地磁盘路径读取 | 若为BVH格式可自动识别 | 应急备用方案 |

需要登录才能访问的动作源**禁止被爬虫抓取**（会触发`PermissionError`错误，并附带下载说明）。这是有意为之：爬虫抓取Mixamo的动作违反其许可协议。

务必记录动作的来源信息（`*_motion_source.json`）。无论是来自MoMask还是Mixamo的重定位后FBX文件，外观上并无差异；是否可正式发布需在后续阶段判断。

**单位换算说明：** Mixamo使用的单位是厘米，因此针对米级尺度的Puppeteer骨骼模型，初始设置需采用`global_scale=0.01`。对于BVH格式文件，建议用`fetch_motion.suggest_global_scale(clip, rig)`来自动计算缩放比例，该函数会同时测量源动作和目标骨骼的尺寸。缩放比例错误并不会导致姿势变形——只会让角色出现月球漫步般的移动或原地抖动现象，因此这类问题往往能通过视觉检查。

外部动作剪辑的任务参数示例如下：

```json
{
  "task_type": "retarget",
  "motion_source": "mixamo",
  "source_motion_path": "<source_motion_path>",
  "target_mesh_path": "<mesh_path>",
  "target_rig_path": "<rig_path>",
  "global_scale": 0.01,
  "fps": 30
}
```

## 3. 动作重定位与骨骼映射

**主机驱动脚本：** `<repo_path>/operators/gen_motion/funcs/retarget_motion.py`。
**Blender插件包：** `<repo_path>/operators/gen_motion/funcs/retarget_utils/`。

| 模块 | 运行环境 | 作用 |
|---|---|---|
| `validate_mapping` | 任意Python环境 | 提前排除错误的映射关系 |
| `mapping_presets` | 任意Python环境 | 源骨骼注册表（存储剪辑侧的骨骼名称） |
| `mapping_auto` | bpy环境 | 根据骨骼拓扑结构自动生成映射关系 |
| `world_delta` | bpy环境 | 执行动作重定位并导出FBX文件 |
| `rig_io` | bpy环境 | 将Puppeteer格式的`.txt`文件转换为骨骼数据 |
| `inspect_fbx` | bpy环境 | 验证重新导入后的FBX文件是否能正常播放动画 |

### 为何映射关系通常是自动生成的，而非复用现有配置

Puppeteer中关节的名称按**预测顺序**命名为`joint0…jointN`。这些名称并不具备解剖学意义：同一个`joint23`在某一角色中可能代表髋部，在另一角色中却可能是手指。因此，一份骨骼映射仅对其生成时所针对的特定骨骼模型有效——本代码库并未提供Mixamo/MoMask到Puppeteer的预设JSON配置文件。真正可复用的是**源骨骼**部分（Mixamo始终使用`mixamorig:Hips`）。它存放在`<repo_path>/operators/gen_motion/funcs/retarget_utils/mapping_presets.py`文件中的`SOURCE_SKELETONS`变量里。你可以省略映射设置，让`mapping_auto`自动生成映射关系；也可以传入显式的`mapping_path`参数或`--mapping`选项来按需定制映射。

当任务名称中未指定映射时，默认的处理流程是：自动生成映射 → 在FBX文件旁写入`mapping.json` → 运行两次world-delta工具（分别处理完整数据和新动画数据）。

### 当操作符无法处理某种重定向情况时

动作重定向存在很多合理的特殊情况，比如奇特的BVH骨骼层级、引擎自定义的轴向规则、IK脚部节点、非人形道具、新型动作捕捉库等。如果某个真实资产在通过`mapping_auto`、`world_delta`或导入流程时出错，且问题出在我们的代码层面而非输入数据有误，那么相关开发人员应在`<repo_path>/operators/gen_motion/funcs/`目录下**修补重定向功能模块**（对应的测试用例需写在`<repo_path>/tests/test_gen_motion.py`和`<repo_path>/tests/test_rigging_retarget.py`中），以确保下次运行时能正常通过操作符处理。此外，还需保持`<repo_path>/operators/gen_motion/funcs/retarget_utils/formats.py`中的格式常量与数据获取、骨骼绑定及命令行验证逻辑保持一致。

### 映射JSON的结构

```json
{
  "root_bones": {"source": "mixamorig:Hips", "puppeteer": "joint0"},
  "bone_map": {"mixamorig:Hips": "joint0", "...": "..."},
  "retarget_chains": {
    "spine": {"source": [...], "puppeteer": [...]},
    "left_arm": {"source": [...], "puppeteer": [...]},
    "right_arm": {"source": [...], "puppeteer": [...]},
    "left_leg": {"source": [...], "puppeteer": [...]},
    "right_leg": {"source": [...], "puppeteer": [...]}
  }
}
```

加载时会将旧的`mixamo`、`target`键值对标准化为上述结构。

## 4. 导入到各引擎中

### Blender（已在本仓库的bpy 4.2版本中验证）

```bash
# 通过主机启动器调用
python "<repo_path>/scripts/import_generated_asset.py" \
  --src "<retargeted_fbx_path>" \
  --engine blender --kind motion \
  --blender "$A3GF_RETARGET_BPY_PYTHON"

# 或直接调用导入脚本
python "<repo_path>/engine_adapters/blender/import_generated/import_motion.py" \
  --src "<retargeted_fbx_path>" --dest "<output_dir>" --name Walk --report "<output_dir>/report.json"
```

若要满足`ok=True`的条件，必须同时具备以下要素：骨骼蒙皮、动作数据、关键帧信息以及**姿态变化**（仅根节点移动并不符合要求——否则滑动的T型姿势也能通过校验）。

若想快速检查骨骼结构而无需走完整导入流程，可使用以下命令：

```bash
"$A3GF_RETARGET_BPY_PYTHON" \
  -m operators.gen_motion.funcs.retarget_utils.inspect_fbx \
  --input "<retargeted_fbx_path>" --output "<output_dir>/fbx_inspection.json"
```

对于人形模型，可查看输出结果中`pose_animated=true`、`skinned=true`，且身高数值`height_m`大约在1.5–2.0之间。

### Unreal Engine 5

并非所有CI服务器都安装了UE；该导入工具可在安装了编辑器的机器上运行：

```bash
python "<repo_path>/scripts/import_generated_asset.py" \
  --src "<retargeted_fbx_path>" \
  --engine ue5 --kind motion \
  --uproject "<uproject_path>" \
  --ue-motion-dest /Game/Generated/Motion
```# 将仅含动画的FBX文件绑定到现有骨骼上
python "<repo_path>/scripts/import_generated_asset.py" \
  --src "<animation_fbx_path>" \
  --engine ue5 --kind motion --ue-anim-only \
  --ue-skeleton "<ue_skeleton_asset_path>" \
  --uproject "<uproject_path>"
```

引擎脚本：`<repo_path>/engine_adapters/ue5/import_generated/import_motion.py`。
该脚本会强制设置`import_as_skeletal=True`和`import_animations=True`——此处不可使用静态路径`<repo_path>/engine_adapters/ue5/import_generated/import_mesh.py`。

导入后，请在内容浏览器中确认以下内容：
1. 一个`SkeletalMesh`（完整的FBX文件）或者仅一个`AnimSequence`（仅含动画的文件）。
2. 一个`Skeleton`资源，或者针对你指定的`--ue-skeleton`参数的动画。
3. 在资产编辑器中播放该AnimSequence——其姿势必须发生变化，而不仅仅是根节点移动。

更高层的UE客户端调用方式为：`<repo_path>/engine_adapters/ue5/animation/client.py`中的`ue.animation.import_motion(...)`。

### Godot 4
使用生成的任务描述符调用公共客户端；它会将FBX或glTF/GLB文件暂存至`res://`目录下，且需要成功运行一次Godot的`--import`命令：

```python
from engine_adapters.godot import GodotClient

godot = GodotClient(
    project_path="<godot_project_path>",
    godot_executable="<godot_executable_path>",
)
result = godot.animation.import_motion(
    {
        "game_id": "my_game",
        "run_id": "run_001",
        "task_kind": "motion",
        "task_id": "walk",
        "artifact_key": "retargeted_fbx_path",
    },
    skeleton="Character/Armature/Skeleton3D",
)
```

`result.ok`表明Godot 4已加载导入的资源，找到了动画、Skeleton3D以及以骨骼为目标的轨迹，并在注册前匹配了所请求的Skeleton3D路径。glTF/GLB格式的动画仍会被识别为`PackedScene`；适配器不会将其误标为`AnimationLibrary`。请先运行Blender结构检查，随后在Godot中查看/播放导入的动画：这些原生检查无法证明姿势是否美观或重定位质量是否达标。

## 5. 质量检查清单（代码无法单独判定的内容）
在`inspect_fbx`运行完毕且Blender导入报告显示`ok=True`后，请执行以下检查：1. **姿势而非仅根节点。** 双腿和双臂需有摆动动作。如果角色仅能平移却始终保持T型姿势，说明骨骼映射时丢失了肢体链信息。
2. **左右侧区分。** 左臂不应控制右臂。自动映射功能会依据世界坐标系的X轴正负号来判断；若源动画是镜像的，需传入`--left-sign`参数或重新生成映射关系。
3. **脚部处理。** 针对Vibe工具，需检查接触目标与IK残差，随后调整对应参数或切换处理方式。可使用MoMask IK（`use_ik=True`）或动作捕捉数据作为备选方案。
4. **缩放比例。** 导入后人类角色的身高约为1.6–2.0米。设置`global_scale`参数前需先确认源文件的单位；Vibe BVH使用的是米为单位，而非Mixamo所用的厘米单位。
5. **朝向问题。** Vibe BVH会保留其模板的坐标轴设定（默认Y轴向上、+Z轴向前）。需分别验证导出的FBX文件与引擎中的角色朝向；如有偏差需记录修正方案（详见`<repo_path>/agent_skills/asset_qa/3d_object/orientation_review.md`）。
6. **授权许可。** 发布模型前需确认模型、数据集及源动作的授权条款。Mixamo、MoCap Online、万代各自有不同的授权规则；务必将`*_motion_source.json`文件与成品一同留存。

## 6. 运行时环境

需配置bpy以实现FBX重定向功能。为支持基于模型的备选方案及重定向流程，需安装以下Linux环境：

```bash
bash "<repo_path>/scripts/asset_env_setup/gen_motion/install.sh"

# 仅安装源码与环境，权重文件可后续按需下载。
bash "<repo_path>/scripts/asset_env_setup/gen_motion/install.sh" --skip-weights

source "<repo_path>/scripts/asset_env_setup/gen_motion/runtime_env.sh"
```

安装程序会创建`gamefactory3a-puppeteer`、`gamefactory3a-momask`和`gamefactory3a-retarget-bpy`三个组件。`<repo_path>/scripts/asset_env_setup/gen_motion/runtime_env.sh`脚本会导出以下环境变量：
- `A3GF_PUPPETEER_MODEL_PATH`
- `A3GF_PUPPETEER_PYTHON`
- `A3GF_MOMASK_MODEL_PATH`
- `A3GF_MOMASK_PYTHON`
- `A3GF_RETARGET_BPY_PYTHON`

需将这些变量明确传递给流水线，避免命令依赖旧版环境变量别名：

```bash
python "<repo_path>/pipeline/assets_gen/gen_motion/run.py" \
  --task-type humanoid \
  --target-mesh "<mesh_path>" \
  --prompt "一个人向前走并挥手。" \
  --puppeteer-model-path "$A3GF_PUPPETEER_MODEL_PATH" \
  --puppeteer-python "$A3GF_PUPPETEER_PYTHON" \
  --momask-model-path "$A3GF_MOMASK_MODEL_PATH" \
  --momask-python "$A3GF_MOMASK_PYTHON" \
  --bpy-python "$A3GF_RETARGET_BPY_PYTHON" \
  --in-place
```

测试步骤：

```bash
# 单元测试+桩集成测试
python -m unittest test.test_gen_motion

# 创建一个无授权、单网格的T型姿势测试模型，用于本地运行。
"$A3GF_MOMASK_PYTHON" \
  "<repo_path>/scripts/asset_env_setup/gen_motion/create_humanoid_glb.py" \
  "<output_dir>/humanoid.glb"
```

合成人类角色测试模型（包含网格、命名符合Mixamo规范的BVH文件以及匹配的Puppeteer绑定 rig），无需授权资产即可在本地复现流程。可从仓库根目录找到`<repo_path>/tests/test_rigging_retarget.py`脚本并使用：

```python
from test.test_rigging_retarget import build_all
build_all("<output_dir>", mesh_format=".glb")
```
