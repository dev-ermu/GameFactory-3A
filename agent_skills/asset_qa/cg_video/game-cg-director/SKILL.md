---
name: game-cg-director
description: 将游戏CG创作意图及可选的媒体引用转换为经过验证、适配特定模型的导演指令包，用于生成开场、过场、必杀技或宣传类视频片段。既可用于独立的CG提示词编写，也可作为游戏生成流程Harness的子功能模块。支持T2VA/纯文本模式、I2VA/首帧图像模式、FL2VA/首尾帧图像模式以及Ref2VA/图像/视频/音频引用模式；本身绝不调用视频生成API。
---

# 游戏CG导演工具

为每个生成的视频片段创建一个经过验证的导演指令包。若用于3AGameFactory项目，直接将其写入Harness任务行；若独立使用，则返回该指令包文件。切勿调用视频生成API或写入生成的媒体内容。

## 明确调用方上下文

要求调用方提供以下信息：
- 已获批的游戏规划、CG需求说明或独立的CG创作意图；
- 视频片段用途：`opening`（开场）、`cutscene`（过场）、`ultimate`（必杀技）或`promo`（宣传）；
- 每个请求任务对应的预期输出视频片段及验收标准；
- 可选的素材路径以及每种素材的指定角色；
- 选定的模型（`h3`或`seedance`），或授权使用默认模型；
- 可选的时长、宽高比、随机种子以及稳定的`task_id`。

当3AGameFactory将该工具作为子功能模块调用时，还需提供选定的`game_id`，并使用其标准的创作工作区：

```text
test_data/test_samples/<game_id>/cg_video/
├── requirement.txt
├── ref_images/                 # 可选的源素材
├── ref_videos/                 # 可选的源素材
├── ref_audio/                  # 可选的源素材
└── cg_tasks.jsonl              # 由该工具直接写入
```

此处请勿选择生成成品的目录。父级工具以及`<REPO_PATH>/pipeline/common/paths.py`负责管理`run_id`和最终输出路径。

对于多片段序列，需为每个独立生成的视频片段分别创建并验证一个导演指令包。确保任务ID唯一，并保留各指令包之间的连贯性锚点。切勿将多个独立生成的视频片段合并为一个任务。

## 整理输入依据

1. 选择模式前，先梳理创作意图、参数设置、素材路径以及每种素材的指定角色，原样保留提供的路径和角色信息。
2. 检查可访问的素材。仅采用实际观察到的事实或用户明确描述的内容，并在工作上下文中区分这些来源。
3. 无法访问的素材视为不透明素材：保留其路径，绝不可根据文件名或剧情背景推测其内容；只有当所需的动作或终点依赖于未知信息时，才请求一段简短的描述。
4. 对于T2VA模式或无参考内容，仅添加为保证场景连贯性、构图、时序或音效所需的具体细节，绝不可将其表述为已确认的参考事实。
5. 切勿声称已查看不透明的媒体内容，也勿在输出的JSON中添加相关依据记录。

## 转发请求1. 请精准选择一个场景：`opening`、`cutscene`、`ultimate` 或 `promo`。需根据请求目的推断场景；仅当意图模糊时才询问用户。
2. 请精准选择一种模式并使用其对应的JSON值：
   - 无媒体输入：T2VA → `text_to_video`；
   - 明确使用一张图片作为首帧：I2VA → `first_frame_to_video`；
   - 明确使用两张图片分别作为首帧和尾帧：FL2VA → `first_last_frame_to_video`；
   - 使用一个或多个素材作为参考而非最终输出内容：Ref2VA → `reference_to_video`；
   - 切勿选择或提及被排除的仅尾帧模式。
3. 请使用指定的模型，名称需转为小写；若未指定模型则使用`h3`。请查阅`<REPO_PATH>/agent_skills/asset_qa/cg_video/game-cg-director/models/<model>.md`获取相关信息。若该模型配置文件不存在，请停止操作，切勿自行编造参数。

## 仅阅读选定的指导规则
将模型配置文件视为输出语体规范，所选场景模板视为游戏CG任务层级。请按以下顺序读取相关文件，所有路径均相对于该技能目录，从`<REPO_PATH>/`解析：
1. `common/principles.md`
2. `common/camera.md`
3. `common/sound.md`
4. 仅当请求中包含风格术语时，才读取`common/style-mapping.md`
5. 精准读取一个`modes/<mode>.md`文件：对应`t2va`、`i2va`、`fl2va`或`ref2va`
6. 精准读取一个`templates/<scene>.md`文件
7. `<REPO_PATH>/agent_skills/asset_qa/cg_video/game-cg-director/models/<model>.md`——此为该技能自身的`models/`目录下的文件，并非仓库级别的`<REPO_PATH>/models/`目录下的文件

请勿预加载其他模式或场景文件。提示词内容请用英语撰写。需原样保留用户提供的对话、歌词及场景文本，并严格按照模型配置文件的要求格式化这些内容。

## 撰写前准备工作
制定简洁的私密场景规划，切勿将其加入JSON或提示词中。仅记录请求所需的信息：
1. 连贯性锚点：反复出现的主体、所需数量、外观特征或参考角色，以及携带的状态；
2. 舞台地图：相对位置、入口或边界、朝向、目标或作用对象，以及主要行动路线；
3. 表演节拍：起始→准备→行动→反应或结果→结束；
4. 镜头目的：要呈现的新信息、摄像机的侧别与方向、主导运动方式，以及结尾构图；
5. 声音演进：既定声源、对话时机、可听峰值，以及适用的音乐变化。

在添加装饰性节拍前，需先确保必要节拍能在给定时长内完成。需保留反复出现的身份与数量、因果顺序、空间方向、清晰的表演逻辑，以及请求指定的最终输出要求。

## 确定各项设置- 保留指定的`aspect_ratio`；否则使用`16:9`，并将`aspect_ratio:16:9`记录到`meta.defaults_applied`中。
- 确保时长在模型限制范围内。必要时将时长调整至模型限制值，并将此次调整记录到`meta.defaults_applied`中。
- 如果未指定时长，则分别使用`opening=10`、`cutscene=12`、`ultimate=6`或`promo=10`，随后应用模型限制，并记录最终的默认值。
- 如果未指定模型，则将`model:h3`记录到`meta.defaults_applied`中。
- 保留指定的`task_id`；否则根据主题、场景、模式以及一个数字后缀生成一个简短且稳定的ID。
- 保留指定的整数型`seed`；否则不填写该字段。

## 构建并移交每个任务

遵循输出架构：
`<REPO_PATH>/agent_skills/asset_qa/cg_video/game-cg-director/schemas/output.schema.json`。
保持封装结构简洁：
- 将完整的提示词内容直接填入`prompt`字段。
- 将`model`、`mode`、`scene`、材质路径以及`meta`字段置于顶层。
- 针对I2VA任务添加`first_frame_path`字段，针对FL2VA任务添加两个端点路径字段。
- 针对Ref2VA任务，仅添加适用的参考路径数组。
- 绝不要将元数据、技能名称、提供商名称或厂商名称放入`prompt`字段。
- 在封装结构验证完成前，不要添加`game_id`或`run_id`。该架构特意设计为可独立验证指令相关字段，无需依赖Harness的身份信息。

对于3AGameFactory子调用：
1. 构建不含`game_id`和`run_id`的封装结构。
2. 将其写入仓库外的唯一临时JSON文件，并运行捆绑的验证器对该文件进行校验。
3. 验证通过后，仅添加选定的`game_id`，然后将完整对象作为一行紧凑的内容直接写入
   `<REPO_PATH>/test_data/test_samples/<game_id>/cg_video/cg_tasks.jsonl`。
4. 保留原有行序及无关任务。除非调用方明确请求修订，否则拒绝重复的`task_id`；若收到修订请求，则直接替换对应行内容。
5. 删除临时验证文件。切勿创建持久的`director/`工作目录。

若为独立使用场景，则写入调用方指定的路径；若未指定路径，则在当前工作目录下生成名为`game-cg-<scene>-<mode>-<task_id>.json`的文件。

## 验证直至通过

在添加`game_id`或写入3AGameFactory任务行之前，先验证每个封装结构。独立使用场景下需验证已写入的封装结构。运行以下命令：
```bash
python3 <REPO_PATH>/agent_skills/asset_qa/cg_video/game-cg-director/scripts/validate_output.py <envelope-json-path>
```
验证是强制性的。若验证失败，仅修改报告中指出的违规项，重新运行同一命令直至退出码为0。验证器中绝不要调用LLM，也绝不要用肉眼检查替代正式验证。

## 移交至父级技能对于3AGameFactory，需返回`cg_tasks.jsonl`的路径、有序的任务ID以及验证状态。父级路径`<REPO_PATH>/agent_skills/asset_qa/cg_video/SKILL.md`用于选择后端及宽高比运行参数，并调用生成流程。若用于独立使用场景，则需返回有序的信封文件路径以及验证状态。

切勿自行选定输出`run_id`，也无需调用模型、消耗云额度，更不得声称已生成视频。
