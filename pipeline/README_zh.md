# pipeline/

按功能分类的全链路运行器。每个任务目录包含两个入口点：

- **`run.py`** —— 仅负责生成（演示/生产环境）
- **`eval.py`** —— 仅负责评估（基准测试评分）

相关合约以及无需GPU的合规性检查工具位于 `agent_skills/develop_harness/pipeline_require.md` 中。

## 结构

```
pipeline/
├── common/                                  # 共享的、与任务无关的工具函数
│   └── paths.py                             #   所有输入输出路径的统一管理源
│
├── assets_gen/                              # 资产生成任务
│   ├── gen_3d_object/{run.py, eval.py}      #   图像/文本 → 3D物体
│   ├── gen_tpose_image/{run.py, eval.py}    #   角色图像 → T型姿势RGBA图像
│   ├── gen_3d_scene/{run.py, eval.py, render.py}  # 图像/视频素材 → 场景网格
│   ├── gen_motion/{run.py, eval.py}         #   文本或下载的视频片段 + 骨骼数据 → 动画
│   ├── gen_cg_video/{run.py, eval.py}       #   文本/帧 → 计算机生成视频
│   └── gen_audio/{run.py, eval.py}          #   文本/参考素材 → 对话或游戏音效
│
└── code_gen/                                # 代码生成任务
    ├── gen_mechanic/{run.py, eval.py}       #   规格说明 + 引擎模板 → 代码 + 执行轨迹
    └── gen_ui/{run.py, eval.py}             #   界面规格说明 → 界面代码 + 截图
```

端到端的游戏切片没有专属的运行器：智能体通过遵循 `agent_skills/setting_overview.md` 中的指引来协调上述任务运行器。`pipeline` 任务类型会在 `common/paths.py` 中注册，以确保切片产物和 `pipeline_task.jsonl` 输入文件的存储位置保持稳定。

## 公开资产生成API

每个已实现的 `pipeline/assets_gen/<task>/run.py` 都遵循相同的生命周期：

1. `load_*()` 用于加载或复用所需的各个模型组件。
2. `make_operator()` 将已加载的模型注入到任务的Operator中。
3. `generate(inp, operator)` 用于生成单个资产并返回结果字典。
4. `run_from_jsonl(...)` 批量调用同一个 `generate()` 函数。

`generate()` 不会加载模型或构建Operator。已经管理好加载模型的调用方可使用更底层的 `operator.run(inp)` API。

### T型姿势图像示例

```python
from pipeline.assets_gen.gen_tpose_image.run import (
    generate,
    load_gen_model,
    load_mask_model,
    make_operator,
)

gen_model = load_gen_model("Qwen/Qwen-Image-Edit-2511")
mask_model = load_mask_model("briaai/RMBG-1.4", model_type="rmbg")
operator = make_operator(gen_model, mask_model, run_id="default")

result = generate(
    {
        "game_id": "gameA_cyberpunk_shooter",
        "task_id": "hero_tpose",
        "image_path": "path/to/character.png",
        "description": "全身角色呈现中性的T型姿势。",
        "seed": 42,
    },
    operator,
)
print(result["tpose_rgba_path"])
```该运行器所使用的具体封装代码位于
`models/gen_image/qwen_edit_model.py` 和
`models/tools/image_matting/{rmbg_model.py,depth_anything_model.py}`。当不再需要已加载的模型时，请调用其 `unload()` 方法。

## 职责划分

### `run.py`
1. 加载所需的模型（来自 `models/` 目录）
2. 实例化操作符（来自 `operators/` 目录）
3. 接收单个输入 → 生成单个输出结果
4. 不执行评分操作，也不计算指标

### `eval.py`
1. 遍历 `test_data/test_samples/<game>/<task>/*_tasks.jsonl` 中的测试集
   （或跨游戏的 `*_collect.jsonl` 文件）
2. 从已有的 `game_id` / `run_id` 中获取结果文件；绝不要导入 `run.py`、
   加载生成模型或触发生成过程
3. 对每个已有的输出结果调用 `operators/<task>/metrics/` 中的评估逻辑
4. 将各任务的得分写入 `paths.eval_output_dir(...)`，并将汇总结果写入
   `paths.eval_summary_path(...)`

## 路径管理 —— 始终通过 `common/paths.py` 处理

输出结果按生成的游戏项目分组，与测试集结构保持一致。
切勿手动拼接输出路径：

```python
from pipeline.common import paths

paths.resolve_tasks_path(kind, args.tasks, args.game)   # 输入路径
paths.iter_tasks(tasks_path, game_filter=args.game)     # 返回 (task, game_id) 对
paths.task_output_dir(game, kind, task_id, run_id)      # 结果文件存储路径
paths.eval_output_dir(game, kind, task_id, run_id)      # 得分文件存储路径
paths.write_results_summary(results, kind, run_id)      # 单游戏汇总结果写入路径
```

若要新增一种任务类型，只需在 `paths.py` 的四个表中各添加一项即可
（`TASK_LAYER`、`TASK_INPUT_DIR`、`TASK_JSONL`、`TASK_COLLECT_JSONL`）——
没有其他注册入口。

## 标准命令行参数

每个 `run.py` 都提供相同的参数选项：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--game <game_id>` | `None` | 限定仅处理某一个游戏项目（优先使用该游戏自带的 `*_tasks.jsonl` 文件） |
| `--tasks <jsonl>`  | `None` | 显式指定任务列表，会覆盖 `--game` 参数的查找逻辑 |
| `--run-id <name>`  | `default` | 运行结果的存储目录名称；设为 `auto` 则会使用时间戳命名 |
| `--out-dir <dir>`  | `None` | 传统的扁平化输出方式；会绕过按游戏分组的存储结构 |
| `--device`         | `cuda` | 指定使用的计算设备 |

## 命名规范

```python
# pipeline/assets_gen/gen_3d_object/run.py
TASK_KIND = "3d_object"

def load_model(ckpt, device="cuda", **kw): ...
def make_operator(model, output_dir=None, run_id=..., default_game_id=None): ...
def generate(inp: dict, operator) -> dict: ...
def run_from_jsonl(tasks_path, operator, game_filter=None) -> list[dict]: ...

# pipeline/assets_gen/gen_3d_object/eval.py
# 为已有的 game_id/run_id 解析结果文件并进行评分。
# 切勿导入 run.py 或调用 generate()。
```

这五个函数构成了生成运行器的 API —— 调用方和 `test/` 模块都会导入它们。
`eval.py` 保持独立，仅读取已有的结果文件。
