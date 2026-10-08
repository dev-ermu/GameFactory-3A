# 图像准备与T型姿势生成技能

当游戏策划需要**单主体概念图**、适用于图像转3D的角色参考图，或是用于后续角色重建的**正面透明T型姿势图像**时，即可使用本技能。T型姿势生成属于图像生成与编辑任务，并非独立的资产类别。

## 适用范围与交接流程

| 需求 | 处理路径 | 下一步操作 |
|---|---|---|
| 用于重建的单物体概念艺术图 | `<REPO_PATH>/models/gen_image/sdxl_turbo.py` | 先审核图像，随后使用`<REPO_PATH>/agent_skills/asset_qa/3d_object/SKILL.md`继续后续流程 |
| 将现有角色图像转换为T型姿势 | `<REPO_PATH>/pipeline/assets_gen/gen_tpose_image/run.py` | 将该透明PNG图像作为输入，接入选定的3D物体或动作工作流 |
| 验证已生成的T型姿势 | 本技能 | 交接前需确认姿势、身份特征、轮廓、透明度、构图及风格均符合要求 |

在图像转3D工作流中，切勿使用多视图合成图、拼贴画、多角色图像、复杂场景图、水印、地面阴影或肢体被裁剪的图像作为输入。这类内容往往会导致几何结构融合、纹理错误，甚至出现身体部位缺失的问题。

## 模型与处理流程

| 组件 | 位置 | 职责 |
|---|---|---|
| 概念图像模型 | `<REPO_PATH>/models/gen_image/sdxl_turbo.py` | 快速生成单物体文生图概念艺术图，专为重建输入场景优化 |
| 图像编辑器（云端API） | `<REPO_PATH>/models/gen_image/seedream_model.py` | 采用Seedream图像编辑功能作为可替换的T型姿势生成后端 |
| 任务执行器 | `<REPO_PATH>/operators/gen_tpose_image/operator.py` | 读取任务指令，生成T型姿势图像，保存相关产物与元数据 |
| 运行器 | `<REPO_PATH>/pipeline/assets_gen/gen_tpose_image/run.py` | 加载模型，接收命令行/JSONL格式的任务指令，输出结果摘要 |


## 安装图像生成环境


```bash
```

仅安装云端封装所需的通用HTTP及冒烟测试依赖项：

```bash
bash scripts/asset_env_setup/image/cloud_api_install.sh
```

## 生成图像前先制定规划

针对每张请求生成的图像，需记录其资产角色、视觉风格、摄像机视角、预期下游用途、期望的轮廓特征、材质线索以及验收标准。若输入为T型姿势模型，需提供一个清晰可见的角色参考图，并附上关于外观、服装、颜色及重要配饰的描述。

T型姿势编辑器会在保留输入外观的基础上，要求生成固定结果：角色直立，双臂与肩同高呈水平状态，正面朝向镜头，背景为纯白色，无场景元素、无投影，且呈现干净的游戏艺术风格。随后流程会移除背景、裁剪前景、将其填充为正方形，再调整尺寸以供重建使用。

## 为3D重建生成概念图

`SDXLTurboModel`适用于快速生成**单物体概念图**，而非最终游戏画面。它默认生成512像素的正方形图像，且负向提示词会排除多视角图、重复主体、裁剪画面、地面、阴影、文字以及杂乱背景——这些元素都会对3D重建造成干扰。

```python
from models.gen_image.sdxl_turbo import SDXLTurboModel

model = SDXLTurboModel(model_path="stabilityai/sdxl-turbo", device="cuda")
image = model.generate(
    prompt="一个风格化的黄铜与木质制成的宝箱，居中摆放，完整可见",
    seed=42,
)
image.save("/absolute/path/chest.png")
model.unload()
```

画面中仅保留一个主体。如果生成结果将用于3D转换，在调用3D物体生成功能前应先审核图像质量，切勿试图后续修复有问题的几何结构。

## 生成T型姿势图像

### 单张图像

从代码库根目录运行以下命令：

```bash
python pipeline/assets_gen/gen_tpose_image/run.py \
  --game gameA_cyberpunk_shooter \
  --run-id auto \
  --image /absolute/path/character_reference.png \
  --task-id character_tpose_001 \
  --description "全身赛博朋克侦察兵，身穿青绿色夹克，配有红色多功能腰带、靴子及护目镜。" \
  --seed 42 \
  --steps 40 \
  --target-size 1024
```

### JSONL批量处理若要指定任务文件，可使用 `--tasks` 参数；若想获取某款游戏的任务列表，则使用 `--game` 参数。一个任务支持以下字段：`image_path`（对于 Python 调用者而言，也可以是内存中的 PIL `image` 对象）、`game_id`、`task_id`、`description`、`seed`、`steps`、`target_size` 以及 `save_intermediate`。

```json
{
  "game_id": "gameA_cyberpunk_shooter",
  "task_id": "luffy_tpose_001",
  "image_path": "test_data/test_samples/gameA_cyberpunk_shooter/tpose/ref_images/luffy.jpg",
  "description": "蒙奇·D·路飞身着标志性的红色背心和草帽。",
  "seed": 42,
  "steps": 40,
  "target_size": 1024
}
```

```bash
python pipeline/assets_gen/gen_tpose_image/run.py \
  --tasks /absolute/path/tpose_tasks.jsonl \
  --run-id auto
```

可选的后端/模型替换方案及分割方式选择如下：

```bash
python pipeline/assets_gen/gen_tpose_image/run.py \
  --device cuda \
  --tasks test_data/test_samples/tpose_gen_collect.jsonl \
  --run-id auto

export ARK_API_KEY="your-key"
python pipeline/assets_gen/gen_tpose_image/run.py \
  --gen-backend seedream \
  --gen-ckpt doubao-seedream-5-0-260128 \
  --device cuda \
  --tasks test_data/test_samples/tpose_gen_collect.jsonl \
  --run-id auto
```

仅当特意选择 Depth Anything 后端时，才需使用 `--mask-type depth --mask-ckpt LiheYoung/depth-anything-small-hf` 参数。`--out-dir` 是用于调试的传统扁平输出模式，切勿将其用于游戏交付物。

## 输出与元数据

当前注册的任务类型仍为 `tpose`，因此标准产出物如下：

```text
test_data/outputs/<game_id>/<run_id>/assets/tpose/<task_id>/
├── tpose_fg.png   # 透明背景的交付文件
├── tpose.png      # 白色背景的中间文件，除非 `save_intermediate` 设为 false
└── meta.json       # 包含源数据、所用模型、随机种子、处理步骤、图像尺寸及任务元数据
```

请使用 `<REPO_PATH>/pipeline/common/paths.py` 并保留这种任务类型目录结构。该“技能”在智能体路由中命名为 `image`；它不会更改现有的流水线 API 或产出文件路径。

## 验证与质量保证

在加载生产环境检查点或消耗 API 额度之前，请先运行免费的合同校验：

```bash
python tests/harness/smoke.py --kind tpose
python tests/harness/smoke.py --kind tpose --backend seedream
```


```bash
python -m unittest test.test_gen_tpose_image -v
```

export ARK_API_KEY="你的密钥"
export AAAGF_RUN_SEEDREAM_LIVE=1
export SEEDREAM_MODEL="doubao-seedream-5-0-260128"
python -m unittest test.test_api_gen_tpose_image -v
```

移交前需逐张检查成品图像的全尺寸效果：

1. **姿势与构图：** 全身直立；双臂水平伸展；脚部、手部、头部及配饰均可见；无裁剪或重复的身体部位。
2. **朝向与身份：** 正对镜头；面部与身体朝向清晰可辨；服装、颜色及关键配饰需与参考图保持一致。
3. **背景与透明度：** 无多余场景、地面阴影、光晕或不透明白色矩形；需在浅色和深色背景下分别检查透明PNG图像的效果。
4. **三维重建适用性：** 主体居中且轮廓清晰；避免出现过度不对称的姿势、动态模糊、文字、水印或细小的道具。
5. **风格：** 图像必须符合规划好的游戏风格，才能用于后续的3D建模或动画生成流程。

若任何一项检查未通过，需优化源图像或描述内容，更换随机种子后重新生成并再次审核。切勿仅通过后续的网格旋转或游戏代码来修正方向颠倒或形态畸形的图像。
