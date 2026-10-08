# CG视频生成与QA技能

该技能适用于**文本转视频、首帧转视频、首尾帧过渡，以及基于参考图像的CG视频生成**。只有在游戏规划明确了视频的叙事目的、视觉风格、镜头类型、时长及验收标准后，才能开始生成视频。

## 流程链、边界与产物

```text
游戏规划 → game-cg-director → cg_tasks.jsonl
→ GenCGVideoOperator → VideoGenerationInput → 视频后端
→ MP4字节流 → video.mp4 + meta.json
```

| 层级 | 位置 | 职责 |
|---|---|---|
| 模型层 | `<REPO_PATH>/models/gen_cg_video/` | 模型原生推理、云端传输及生命周期管理 |
| 流水线层 | `<REPO_PATH>/pipeline/assets_gen/gen_cg_video/` | 后端选择、命令行接口、JSONL批量处理及汇总 |
| 测试框架层 | `<REPO_PATH>/tests/harness/` | 纯CPU、无网络环境下的流程链验证 |
| 导演子技能 | `<REPO_PATH>/agent_skills/asset_qa/cg_video/game-cg-director/` | 针对特定模型的分镜提示词生成及已验证的任务条目 |

本技能中的路径均从代码库根目录出发。所有`<REPO_PATH>/...`路径需据此解析，且下方的每条`bash`和`python`命令均需以`<REPO_PATH>/`为工作目录执行。

标准产物目录结构如下：

```text
test_data/outputs/<game_id>/<run_id>/assets/cg_video/<task_id>/
├── video.mp4
└── meta.json
```

通过浏览器服务网关播放的游戏，会在运行时根据任务标识加载对应视频片段；此类请求会直接调用已存储的产物，而非实时生成。生产阶段需根据游戏规划生成所有指定的视频片段，同时运行播放时网关时需设置`A3GAME_BROWSER_CG_VIDEO_PREBUILT_ONLY=1`参数，这样未生成的片段会被标记为失败，而不会在页面加载时临时生成。若要求返回的字节流保持固定，需锁定对应的`run_id`：未锁定的查询会返回最新的匹配产物。


## 导演子技能与测试框架的交接

当已获批的游戏规划明确了CG片段的用途，但尚未给出适配模型的提示词时，可参考`<REPO_PATH>/agent_skills/asset_qa/cg_video/game-cg-director/SKILL.md`文档。该子技能是本技能的子功能，并非独立的生成后端；它会为每个输出片段创建并验证一个导演信封，且不会调用模型进行生成。

阅读该文档及其引用的文件后，在使用相关条目前需先验证其返回的每个信封——若验证退出码非零，则流程将被阻塞：

```bash
python3 <REPO_PATH>/agent_skills/asset_qa/cg_video/game-cg-director/scripts/validate_output.py <envelope.json>
```验证是提示词与付费生成之间的唯一检查环节。流水线及浏览器服务网关会接受所有执行字段格式正确的请求行，因此未经验证器校验的请求包也能直接毫无阻碍地抵达后端。

调用子流程前需先选择输入工作区：

```text
test_data/test_samples/<game_id>/cg_video/
├── requirement.txt
├── ref_images/                  # 可选
├── ref_videos/                  # 可选
├── ref_audio/                   # 可选
└── cg_tasks.jsonl
```

将选定的`game_id`、以下类型之一：`opening`、`cutscene`、`ultimate`或`promo`、计划动作及验收标准、可选的参考素材路径和角色信息、模型选择、时长、宽高比、随机种子以及任务ID传递给子流程。对于需要多次独立生成的序列，需为每个片段分别调用一次子流程，并在各请求包之间保留连续性锚点。

子流程会验证其指令包内容，添加选定的工作区标识，然后将完整的对象作为一行紧凑的文本直接写入`cg_tasks.jsonl`：

```text
game_id                                      ← 选定的工作区
task_id, mode, model, scene
duration_sec, aspect_ratio, prompt, meta
seed                                         ← 存在时才会写入
first_frame_path                             ← 仅首帧模式会写入
last_frame_path                              ← 仅首/尾帧模式会写入
reference_image_paths                        ← 存在参考模式时写入
reference_video_paths, reference_audio_paths ← 存在参考模式时写入
```

当前的Operator仅读取其支持的执行字段，其余指令元数据会被安全忽略。切勿因为某个后端支持的输入较少就简化任务行内容。应保留现有的JSONL行，仅在明确修订时才替换匹配的`task_id`。

Runner会根据流程分别选择模型和宽高比。当JSONL文件中包含多种执行配置时，需一次调用一个任务：

| 请求包中的模型 | Runner的选择 |
|---|---|
| `seedance` | `--backend seedance` |


```bash
python pipeline/assets_gen/gen_cg_video/run.py \
  --tasks test_data/test_samples/<game_id>/cg_video/cg_tasks.jsonl \
  --task-id <task_id> \
  --run-id <run_id> \
  <backend-and-format-options>
```

视频和音频参考素材现在即可编写，但当前的Operator会在未来支持相关功能前阻止其执行。当前流水线会为每个任务生成一个`video.mp4`文件；将多个片段合成一个编辑后的主视频属于独立的后期制作步骤。

## 共享模式| 模式 | 必需的图片输入 | 用途 |
|---|---|---|
| `text_to_video` | 无 | 根据文本提示生成视频片段 |
| `first_frame_to_video` | `first_frame` | 为预设的开场构图制作动画 |
| `first_last_frame_to_video` | `first_frame`、`last_frame` | 创建受控的关键帧到关键帧过渡效果 |
| `reference_to_video` | 一张或多张有序的`reference_images` | 保留角色/环境的视觉参考特征 |

参考图片的顺序具有重要意义。当视频构图依赖于这些图片时，需在提示词中说明每张图片的作用。后端会直接拒绝不支持的模式与后端组合请求，而不会悄悄将请求转发给其他模型。

## 后端选择

| 后端/运行环境 | 文本输入 | 首帧输入 | 首尾帧输入 | 参考图片输入 | 最佳适用场景 |
|---|---:|---:|---:|---:|---|
| Seedance 2.0云API | 支持 | 支持 | 支持 | 支持 | 所有共享模式下均能提供高质量的云端生成服务 |
| MiniMax Hailuo 2.3 API | 支持 | 支持 | 不支持 | 不支持 | 仅适用于云端文本转视频和图像转视频任务 |



## 常用命令行用法

文本转视频：

```bash
python pipeline/assets_gen/gen_cg_video/run.py \
  --backend seedance \
  --prompt "一只纸做的龙在云雾缭绕的山脉上空飞翔。" \
  --mode text_to_video \
  --duration-sec 5 \
  --task-id paper_dragon \
  --game gameA_cyberpunk_shooter \
  --run-id auto \
  --cache-dir test_data/outputs/_api_cache
```

帧输入与参考模式：

```bash
# 首帧输入
python pipeline/assets_gen/gen_cg_video/run.py \
  --backend seedance \
  --mode first_frame_to_video \
  --first-frame /absolute/path/first.png \
  --prompt "角色向前行走。" \
  --duration-sec 5

# 首尾帧输入
python pipeline/assets_gen/gen_cg_video/run.py \
  --backend seedance \
  --mode first_last_frame_to_video \
  --first-frame /absolute/path/first.png \
  --last-frame /absolute/path/last.png \
  --prompt "在这两帧之间自然过渡。" \
  --duration-sec 5
```# 有序参考图像；重复该参数
python pipeline/assets_gen/gen_cg_video/run.py \
  --backend seedance \
  --mode reference_to_video \
  --reference-image /absolute/path/character.png \
  --reference-image /absolute/path/environment.png \
  --prompt "保持角色与环境的一致性。" \
  --duration-sec 5
```

批量模式：

```bash
python pipeline/assets_gen/gen_cg_video/run.py \
  --tasks /absolute/path/cg_tasks.jsonl \
  --run-id auto
```

JSONL格式的任务示例：

```json
{"game_id":"gameA_cyberpunk_shooter","task_id":"shot_001","mode":"first_frame_to_video","prompt":"摄像机缓慢靠近。","duration_sec":5,"seed":42,"first_frame_path":"test_data/test_samples/gameA_cyberpunk_shooter/cg_video/ref_images/shot_001.png"}
```

仓库相对路径的图像会通过`pipeline.common.paths`解析，而非通过Shell工作目录。

## Seedance 2.0云API

安装共享依赖并设置凭证：

```bash
bash scripts/asset_env_setup/cg_video/cloud_api_install.sh
export ARK_API_KEY="你的API密钥"
export GAMEFACTORY3A_API_CACHE=test_data/outputs/_api_cache
```

可选配置：

```bash
export ARK_API_BASE=https://ark.cn-beijing.volces.com/api/v3
export SEEDANCE_MODEL=doubao-seedance-2-0-260128
export SEEDANCE_RESOLUTION=720p
export SEEDANCE_RATIO=16:9
export SEEDANCE_GENERATE_AUDIO=1
export SEEDANCE_WATERMARK=0
export SEEDANCE_TASK_TIMEOUT=1800
export SEEDANCE_POLL_INTERVAL=3
export SEEDANCE_MAX_RETRIES=3
```

首次非缓存请求时需要提供`ARK_API_KEY`。Ark端点ID并非API密钥。切勿将密钥放入JSONL、元数据、缓存键或提交的命令示例中。共享缓存键包含模型、模式、提示词、图像哈希值以及生成参数，但不包括API密钥和原始图像字节数据。

实用的显式运行参数选项：

```bash
python pipeline/assets_gen/gen_cg_video/run.py \
  --backend seedance \
  --ckpt doubao-seedance-2-0-260128 \
  --resolution 720p \
  --ratio 16:9 \
  --no-generate-audio \
  --no-watermark \
  --timeout 1800 \
  --poll-interval 3 \
  --max-retries 3 \
  --cache-dir test_data/outputs/_api_cache \
  --prompt "一座悬浮城市的电影级全景镜头。"
```

## MiniMax H3 / Hailuo 2.3

### API运行时

Hailuo 2.3仅支持`text_to_video`和`first_frame_to_video`模式。

```bash
bash scripts/asset_env_setup/cg_video/cloud_api_install.sh
export MINIMAX_API_KEY="你的密钥"

python pipeline/assets_gen/gen_cg_video/run.py \
  --backend minimax-h3 \
  --minimax-runtime api \
  --mode text_to_video \
  --prompt "一名骑士穿过被雨水浸湿的霓虹广场。" \
  --duration-sec 6 \
  --resolution 1080P
```

Hailuo API支持768P分辨率下生成6秒或10秒的视频，以及1080P分辨率下生成6秒的视频。该API不提供种子参数；共享的种子参数会被接受但会被忽略。



```bash
bash scripts/asset_env_setup/cg_video/minimax_h3_install.sh

```bash
python pipeline/assets_gen/gen_cg_video/run.py \
  --backend minimax-h3 \
  --mode first_last_frame_to_video \
  --first-frame /data/first.png \
  --last-frame /data/last.png \
  --prompt "摄像机完成一次缓慢的环绕运动。" \
  --duration-sec 5
```


## 测试、质量保证与成本控制

首先运行免费合约检查：

```bash
python tests/harness/smoke.py --kind cg_video --backend seedance
python tests/harness/smoke.py --kind cg_video --backend minimax-h3
```


```bash
export ARK_API_KEY="你的API密钥"
export CG_VIDEO_BACKEND=seedance
export CG_VIDEO_TEST_TASKS=/绝对路径/to/cg_tasks.jsonl
export CG_VIDEO_TEST_OUT_DIR=/绝对路径/to/output
export GAMEFACTORY3A_API_CACHE=/绝对路径/to/api_cache
```

该测试会在联系服务提供商前先验证任务有效性。设置`CG_VIDEO_TEST_TASK_ID=<任务ID>`即可复现特定任务结果。切勿在持续集成环境中启用付费测试，也不要为了验证代码变更而运行所有模式。

生成视频后，需以正常速度并在目标游戏场景中查看MP4文件：
1. 验证提示词匹配度、时间连贯性、角色一致性以及摄像机运动是否符合要求；
2. 检查是否存在闪烁现象、人物/道具变形、不可能的过渡效果、难以辨认的动作、多余文字/水印，或宽高比错误；
3. 确保视频的灯光、特效、构图、时长及音频选择符合游戏要求的风格；
4. 在元数据中标明服务提供商/模型名称、提示词、生成模式、图像版权信息、参数设置、缓存状态，以及人工或视觉审核结果；
5. 若视频存在视觉瑕疵，应调整帧、提示词、时长或后端重新生成，而非因为MP4文件格式有效就直接接受质量不佳的视频。
