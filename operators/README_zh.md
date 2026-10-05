# 运算符/

任务**运算符**——每种资产生成任务类型对应一个运算符。

每个运算符目录都有统一的布局：

```
operators/<任务类型>/
├── __init__.py
├── operator.py       # 顶层类，例如 Gen3DObjectOperator
├── funcs/            # 解耦后的步骤（每个逻辑功能对应一个文件）
└── metrics/           # 特定任务的评估代码
```

特意将`metrics/`目录与每个运算符放在同一位置——因为评估逻辑与该运算符的输出紧密关联（例如，计算机图形学任务需要时间一致性指标；3D物体生成任务需要倒角距离和基于物理的渲染检查；动作生成任务需要脚部滑动量和抖动指标）。

## 运算符

| 运算符 | 类 | 描述 | `funcs/`中的步骤 |
|---|---|---|---|
| `gen_tpose_image` | `GenTPoseImageOperator` | 角色图像 → 适合绑定骨骼的T型姿势RGBA图像 | `gen_tpose_image` |
| `gen_3d_object` | `Gen3DObjectOperator` | 根据图像/文本生成单个3D资产 | `art_plan`、`asset_import`、`asset_pack`、`mesh_cleanup` |
| `gen_3d_scene` | `Gen3DSceneOperator` | 根据参考图像重建3D场景，或组合地面与放置的物体 | `scene_mask`、`points_to_mesh`、`build_scene_mesh`、`scene_assets`、`appearance_assets` |
| `gen_motion` | `GenMotionOperator` | 为角色绑定骨骼，生成或获取动画片段，并进行重定向 | `rig_character`、`generate_motion`、`fetch_motion`、`retarget_motion` |
| `gen_audio` | `GenAudioOperator` | 生成角色对话和游戏音效 | `generate_dialogue`、`generate_sound_effect`、`prepare_reference_audio`、`resample_audio` |
| `gen_cg_video` | `GenCGVideoOperator` | 生成计算机图形学/过场动画视频 | — |

`gen_motion`运算符集成了骨骼绑定、文本转动作、素材库下载以及动作重定向功能；通过任务中的`task_type`参数来选择执行路径，因此没有单独的`retarget`运算符。

有两个已预留但尚未实现的目录——这两个目录中的`operator.py`文件均为空，请勿导入它们：

| 预留名称 | 预期用途 | 当前状态 |
|---|---|---|
| `process_input` | 解析文本、预处理图像、提取角色信息 | 占位符 |
| `gen_ui` | 生成HUD/前端界面，包含`agent/`、`prompts/`、`skills/`模块 | 占位符；可运行的UI路径为`pipeline/code_gen/gen_ui/` |

游戏玩法和UI的代码生成没有单独的运算符层：`pipeline/code_gen/gen_mechanic/`和`pipeline/code_gen/gen_ui/`会直接驱动智能体调用引擎适配器。

`metrics/`为每个任务提供了统一的`evaluate(result, task)`入口点，且运行时不依赖模型、权重或GPU。目前仅实现了`gen_3d_scene`（边界-边缘比例、最大组件占比、伸展程度p99）和`gen_motion`（骨骼绑定、BVH格式及重定向产物检查）的评估逻辑；其余`metrics/`包均为空的占位符。

## 关于`gen_3d_scene`的说明其`funcs/`目录下的代码是为了修复上游HunyuanWorldMirror代码生成的穿孔网格问题。上游代码在回答“该像素是否有效？”以及“该像素是否位于不连续处？”时会采用相同的删除逻辑，这会导致实体表面出现孔洞——因为不连续处属于两个像素之间的边界，而非某个像素本身。因此，`scene_mask.py`仅用于判断像素，`points_to_mesh.py`仅用于判断面片；它们采用切平面测试机制：既能保持以掠射角后退的地面平面完整，又能在前景轮廓与背景交汇处进行切割。在真实参考图像上，这种处理方式能将保留的像素覆盖率从约82%提升至99%以上。

仍有两种瑕疵存在，且需单独处理，因为它们均不属于连续性问题。天空部分被预测为有限深度，需通过操作符中的`sky_model`将其分割出来。而当深度头模型将遮挡边界模糊成斜坡时，跨越该区域的面片能通过每条边的测试；此时则需通过比较每个面片自身的法线与它所继承的法线来识别此类情况。

`operators/gen_3d_scene/`或`pipeline/assets_gen/gen_3d_scene/`目录下没有任何模型命名：操作符将`model`、`video_model`和`sky_model`作为注入的依赖项，因此要将Hunyuan后端替换为其他场景生成器时，只需修改`models/`目录即可。有三款流水线工具无需依赖权重文件或GPU即可对输出结果进行检测：

| 命令 | 功能说明 |
|---|---|
| `eval.py --self-check` | 用已知答案的合成场景与上游过滤机制进行对比测试 |
| `eval.py --contract-check` | 检查`WorldPlayModel`的调用是否与HY-WorldPlay版本相匹配 |
| `render.py scene.glb` | 将网格离屏渲染，以便查看其中的孔洞及变形情况 |
