# develop_harness

用于**资产生成链**的开发工具包 — `<REPO_PATH>/models/` → `<REPO_PATH>/operators/` → `<REPO_PATH>/pipeline/`。在添加或修改任何资产任务前请先阅读本文档。

之所以需要它，是因为只有当这三层对接口约定达成一致时才能发挥作用。该目录明确了这些约定；其可运行的对应部分位于 `<REPO_PATH>/tests/harness/`，借助它可以无需GPU且无需下载权重即可验证整个流程。

路径均以仓库根目录为起点表示为 `<REPO_PATH>/...`；具体规则可参考 `<REPO_PATH>/agent_skills/setting_overview.md` 中的“路径约定”章节。代码块中的Shell命令均以仓库根目录为相对路径 — 执行时需将 `<REPO_PATH>` 设为工作目录。

## 目录说明

| 文件 | 用途 |
|------|------|
| `README.md` | 本文档 — 介绍工作流程（标准操作程序）和分层规则 |
| `model_require.md` | `<REPO_PATH>/models/` 下的包装器必须满足的接口约定 |
| `api_model_require.md` | **R9** — 当模型为闭源云API时的变更要求 |
| `operatar_require.md` | `<REPO_PATH>/operators/` 下的运算符必须满足的接口约定 |
| `pipeline_require.md` | `<REPO_PATH>/pipeline/*/run.py` 与 `eval.py` 必须满足的接口约定 |

可执行部分（位于 `<REPO_PATH>/test/`，即代码存放位置）：

| 文件 | 用途 |
|------|------|
| `<REPO_PATH>/tests/harness/stubs.py` | 模拟模型+测试数据 — 可在毫秒级时间内在CPU上运行任意流程 |
| `<REPO_PATH>/tests/harness/smoke.py` | 使用模拟模型进行端到端流程测试，验证输出结果的结构是否正确 |

## 三层架构

```
models/<family>/<model_name>_model.py        第一层 — “如何与单个模型交互”
        │                          知晓：权重、数据类型、设备、自身API
        │                          不知晓：任务类型、jsonl格式、输出路径、游戏相关信息
        ▼
operators/<task>/operator.py    第二层 — “如何将单个任务字典转换为产物”
        │   └── funcs/             知晓：任务语义、产物名称、元数据
        │   └── metrics/           不知晓：具体是哪个模型、argparse参数、jsonl格式
        ▼
pipeline/assets_gen/<task>/     第三层 — “如何批量运行并评估结果”
    run.py / eval.py               知晓：argparse参数、检查点解析、jsonl格式、汇总信息
                                  不知晓：模型内部实现、产物的字节布局
```

**确保这一架构严谨性的唯一规则：** 依赖关系只能向下延伸。
模型绝不会导入运算符；运算符也绝不会导入 `run.py`。
跨层的连接仅在 `run.py` 的 `make_operator()` 中完成一次。

## 工作流程 — 添加新的资产任务

需按照“自上而下遵循接口约定，自下而上编写代码”的原则操作。

### 1. 注册任务类型

在 `<REPO_PATH>/pipeline/common/paths.py` 的四个表中添加新任务类型：
`TASK_LAYER`、`TASK_INPUT_DIR`、`TASK_JSONL`、`TASK_COLLECT_JSONL`。
仓库中其他部分均不会硬编码路径，因此这是唯一的注册点。

### 2. 模型包装器 — `models/<family>/<model_name>_model.py`请遵循`model_require.md`的要求。参考实现如下：
`<REPO_PATH>/models/gen_3d_object/trellis_2_model.py`（生成模块），
`<REPO_PATH>/models/tools/image_matting/rmbg_model.py`（工具模型，继承自`BaseToolModel`）。

### 3. 算子 — `operators/<task>/operator.py`（含`funcs/`目录）

请遵循`operatar_require.md`的要求。参考示例：`<REPO_PATH>/operators/gen_tpose_image/`
（该目录下包含算子以及多步骤处理的`funcs/gen_tpose_image.py`文件）。

实际算法步骤应放在`funcs/`目录下——每个逻辑步骤对应一个文件，这些文件应为纯函数，输入和输出分别为PIL图像、numpy数组或文件路径。算子本身则应写成简短的脚本：解析输入→调用相关函数→保存生成物→返回字典。

### 4. 运行器 — `pipeline/assets_gen/<task>/run.py`

请遵循`pipeline_require.md`的要求。参考示例：
`<REPO_PATH>/pipeline/assets_gen/gen_3d_object/run.py`。直接照搬其结构；其中五个模块级函数（`load_*`、`make_operator`、`generate`、`run_from_jsonl`、`main`）构成了生成运行器的API；调用方以及`<REPO_PATH>/test/`中的测试代码均通过名称调用它们。`eval.py`保持独立，用于读取已有的生成物。

### 5. 测试数据

需将该任务的相关条目同时添加到针对单个游戏的
`<REPO_PATH>/test_data/test_samples/<game>/<TaskDir>/<kind>_tasks.jsonl`文件，以及跨游戏通用的
`<kind>_collect.jsonl`文件中。每条条目都必须包含`game_id`和`task_id`字段。

### 6. 注册存根并验证——无需GPU环境

在`<REPO_PATH>/tests/harness/stubs.py`文件中向`STUB_OPERATOR_KWARGS`（以及`OPERATOR_LOCATION`）添加相应条目，然后执行以下命令：

```bash
pip install pillow numpy scipy          # 该测试框架无需其他依赖
python tests/harness/smoke.py --kind <new_kind>
```

`smoke.py`会验证生成物是否准确存放在`paths.py`所指定的路径下，`meta.json`是否被正确写入，传统扁平模式是否保持不变，以及汇总信息是否按游戏项目分组。

随后，在配备GPU的设备上执行真正的集成测试：

```bash
python tests/test_<task>.py
```

## 输出目录结构 — 切勿手动构建路径

所有生成物均通过`(game_id, run_id, task_kind, task_id)`这一标识来定位，它们存储在与测试集结构对应的根目录下：

```
test_data/outputs/<game_id>/<run_id>/assets/<task_kind>/<task_id>/
```

务必通过`<REPO_PATH>/pipeline/common/paths.py`来操作路径：

```python
from pipeline.common import paths

paths.resolve_tasks_path(kind, args.tasks, args.game)   # 输入路径
paths.task_output_dir(game_id, kind, task_id, run_id)   # 生成物路径
paths.eval_output_dir(game_id, kind, task_id, run_id)   # 评分结果路径
paths.write_results_summary(results, kind, run_id)      # 各游戏项目的汇总信息
```

`grep -rn "outputs/" operators/ models/`命令的输出必须为空——任何位于`paths.py`之外的字面量输出路径均属于错误。

## 向后兼容性

算子会被`run.py`、`eval.py`以及`<REPO_PATH>/test/`中的代码调用。在进行相关修改时：- **切勿删除或重命名已返回的字典中的键**。可以添加新键，但不要复用已有键。
- **切勿更改现有构造函数参数的含义**。新功能应通过新增带有默认值的参数来实现，该默认值需能复现原有行为。例如：`Gen3DObjectOperator(output_dir=...)` 仍会将文件写入 `<output_dir>/<task_id>.glb`；只有省略 `output_dir` 参数时，才会启用针对单个游戏的布局模式。
- `<REPO_PATH>/tests/harness/smoke.py` 会同时测试这两种模式，因此如果旧有逻辑路径出现回归问题，烟雾测试就会失败。

## 反模式

| 不要这样做 | 建议这样做 |
|-------|-----|
| 在算子中直接使用 `argparse` | 将命令行接口相关逻辑放在 `run.py` 中处理 |
| 算子中直接构建模型 | 注入已加载的模型 |
| 模型直接往 `<REPO_PATH>/test_data/outputs/` 目录写数据 | 让模型返回数据，再由算子负责保存 |
| 使用 `os.path.join("outputs", ...)` | 改用 `paths.task_output_dir(...)` |
| 在算子的模块顶层导入 `torch` | 在函数内部导入 |
| 评估阶段导入 `run.generate()` 或加载生成模型 | 仅对已有的产物进行解析和评分 |
| 在推理代码周围使用 `except Exception: pass` 来捕获异常 | 允许程序抛出真实的回溯信息，以便定位问题 |
