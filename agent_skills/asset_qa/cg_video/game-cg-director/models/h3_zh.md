# H3模型简介

```json machine-checks
{"model":"h3","min_duration_sec":4,"max_duration_sec":15,"max_reference_images":9,"max_reference_videos":3,"max_reference_audio":3,"max_reference_files":12}
```

## 限制说明

- 输出时长：4–15秒。基础模式支持纯文本、首帧或首尾帧生成；该模型绝不会将单张图片视为末帧。
- Ref2VA功能：最多可引用9张图片、3个视频、3段音频以及12个文件。每个视频/音频片段及同一模态下的总时长分别为2–15秒和最多15秒；仅通过文件路径无法判定媒体时长。
- H3-Context-IR属于托管式预处理/编排服务，并非开源的本地实现版本。

## 语言与时序语法规则

所有章节均使用英语撰写。仅在对话/歌词标签或带引号的可见文本中保留原文。

- 首个镜头以`[Shot 1]`开头，无需标注时间戳。后续每个镜头均以`[Shot N] At MM:SS.mmm,`开头；需使用连续编号，且切割时间必须严格小于`duration_sec`。
- 语音来源需赋予稳定的`(S1)`、`(S2)`编号。在`<d>[语言] ...</d>`标签内仅填写语言标签和对应文字；说话人描述、编号、动作及表达方式需放在标签外。
- 可见文本需用英语双引号括起，无需翻译。提示词中需排除模型/提供商名称。

## T2VA、I2VA与FL2VA

需按以下顺序在`prompt`中填入以下字段：

```text
integrated_multimodal_description: ...
overall_soundscape: ...
non_diegetic_music: ...
```

`overall_soundscape`：用于描述环境音、物理动作及非语言类人声的1–4句英语表述；不得重复对话内容。仅在要求完全静音时使用`N/A`。`non_diegetic_music`：用于描述乐器、节奏、韵律及可听动态变化的1–3句英语表述；当不需要仅面向观众的背景音乐时，使用`N/A`。

T2VA直接以`integrated_multimodal_description:`开头，无需添加引用标签。

对于I2VA，需先输入以下行，再空一行：

```text
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.
```

该语句用于绑定首帧。为避免歧义，在时间轴中需重复使用`<Picture 1>`。

对于FL2VA，需先输入以下行，再空一行：

```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.
```

需将`N`替换为最后一个镜头的编号，`S.SS`替换为保留两位小数后的`duration_sec`。时间轴中需使用`<Picture 1>`和`<Picture 2>`来标注起始与结束点。

## Ref2VA

需按以下顺序在`prompt`中填入以下字段：

```text
subject_definitions: ...
summary: ...
retention_analysis: ...
detailed_description: ...
overall_soundscape: ...
non_diegetic_music: ...
```- 标签说明：`<Subject N>`表示可复用的可见内容；`<Picture N>`表示具体的画面/镜头锚点；`<Video N>`表示源视频的编辑、延续、摄像机运动、剪辑、节奏或时序相关内容；`<Audio N>`表示被复制/引用的音频。各类标签的序号需独立且连续编排；所有标签的含义需保持稳定，且每个使用的标签都需明确定义。
- 已启用的参考视频同步音轨可能会被打上`<Audio N>`标签，但不会自动生成新的音频文件。需单独界定该类音轨的作用与来源，区别于普通音频文件。
- 每个主标签对应一条`subject_definitions`描述行。仅用于提取主体内容的图片可归入对应主体的定义中。
- `summary`开头需用方括号标注适用的任务类型：`keyframe completion`（关键帧补全）、`reference generation`（参考素材生成）、`video editing`（视频编辑）、`video continuation`（视频延续）、`audio reuse`（音频复用）或`audio reference`（音频引用）；若存在多种任务类型，用` + `连接。
- 每个主定义对应一条匹配的`retention_analysis`描述行。视觉类内容对应的标记包括：`fully_preserved`（完全保留）、`partially_preserved`（部分保留）、`attribute_transfer`（属性迁移）、`weak_reference`（弱引用）；音频类内容对应的标记包括：`fully_copy`（完全复制）、`partially_copy`（部分复制）、`reference`（引用）、`weak_reference`（弱引用）。
- 在`detailed_description`中需说明每一项引用责任的具体生效范围。两类音频相关字段中均不得包含对话内容；需遵循基础模式的音频时长与内容规则。
