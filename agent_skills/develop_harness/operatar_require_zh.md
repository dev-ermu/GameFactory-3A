# operatar_require.md — `operators/`目录下的合约

> 文件名保留了代码库骨架中使用的拼写。若想修正此问题，可通过 `git mv operatar_require.md operator_require.md` 重命名——毕竟没有代码是通过该文件名引用它的。

**算子（operator）**的作用是将*一个任务字典*转换为*磁盘上的产物*。它负责定义任务的语义（提示词、步骤顺序、产物命名、元数据），并且刻意设计为**与模型无关**：任何符合预期方法签名的封装均可被注入使用。

参考实现：`<REPO_PATH>/operators/gen_3d_object/`（单次调用场景）、`<REPO_PATH>/operators/gen_tpose_image/`（包含`funcs/`的多步骤场景）。

---

## 目录结构

```
operators/<task>/
├── __init__.py
├── operator.py       # 对应的类——Gen<Task>Operator
├── funcs/            # 解耦后的算法步骤，每个逻辑步骤对应一个文件
└── metrics/          # 特定任务的评估逻辑，通过`operator.eval()`暴露
```

特意将`metrics/`放在同一目录下：评分逻辑与该算子的产物布局紧密关联。

---

## R1 — 硬性规则

| 编号 | 规则 | 原因 |
|---|---|---|
| R1.1 | **除了`pipeline.common.paths`外，禁止从`<REPO_PATH>/pipeline/`导入任何内容**，且即便导入`paths`也**必须放在方法内部，而非模块顶层**。 | 以此保持层级边界清晰，避免导入循环问题。 |
| R1.2 | **绝不要加载模型**。模型需通过构造函数以已加载状态传入。 | 这样`run.py`可一次性加载模型并在整个批次中复用，同时方便测试时注入模拟对象。 |
| R1.3 | **禁止使用`argparse`，禁止读取环境变量，禁止调用`sys.exit`**。 | 命令行接口的功能由`run.py`负责。 |
| R1.4 | **绝不要硬编码输出路径**。需使用`paths.task_output_dir(...)`。 | 确保路径布局有统一的依据。 |
| R1.5 | **禁止用`try/except`吞掉推理错误**。应让错误带着真实回溯信息抛出。 | 静默的部分结果比直接崩溃更糟糕。 |
| R1.6 | 重量级依赖（`torch`、`scipy`以及`funcs/`模块）需**放在`run()`内部加载**。 | 该模块必须能在没有权重文件的CPU机器上完成导入。 |

## R2 — 构造函数

```python
def __init__(
    self,
    model: Any,                          # 或gen_model / mask_model / ...
    output_dir: Optional[str] = None,    # 传统扁平模式
    run_id: str = "default",
    default_game_id: Optional[str] = None,
):
```

| 编号 | 规则 |
|---|---|
| R2.1 | 已加载的模型对象是**首要的位置参数**。 |
| R2.2 | 辅助模型标记为`Optional`且默认值为`None`；算子会优雅地降级运行（比如`mask_model`缺失时，T型姿势会保持不透明状态）。 |
| R2.3 | 除存储参数和创建目录外，**不做任何实际工作**。不执行推理，也不进行下载操作。 |
| R2.4 | 模型之后的所有参数均有默认值，因此仅传入`model`就能实例化算子。 |
| R2.5 | 需存储`run_id`和`default_game_id`；它们是任务级别而非批次级别所需的参数。 |

### 输出模式解析

根据是否提供了`output_dir`，分为两种模式：| `output_dir` | 模式 | 路径 |
|---|---|---|
| `None`（默认值） | **按游戏分类** | `paths.task_output_dir(game_id, kind, task_id, run_id)`，生成的产物文件名固定为`model.glb`、`tpose_fg.png`，外加`meta.json` |
| 字符串 | **旧版扁平模式** | `<output_dir>/<task_id>.<ext>` —— 完全复现历史行为，不会生成`meta.json` |

将此逻辑封装到一个私有辅助函数（`_resolve_out_path`）中，以保持`run()`函数的代码线性。每种模式的判断最多只能出现一次。

## R3 — `run(inp: dict) -> dict`

这是唯一的公共入口点。输入一个任务，输出一个字典。

| # | 规则 |
|---|------|
| R3.1 | 函数签名必须为`run(self, inp: dict) -> dict`。不能有其他位置参数。 |
| R3.2 | 通过`inp.get(key, default)`读取所有字段。只有主要输入（图像/提示词/动作数据）可以是必填项。 |
| R3.3 | `task_id`的默认值为`f"task_{int(time.time())}"`——即使缺少该字段也不会导致程序崩溃。 |
| R3.4 | `game_id`由`paths.infer_game_id(inp, fallback=self.default_game_id)`生成。切勿手动从路径中解析该值。 |
| R3.5 | `seed`的默认值为`42`。 |
| R3.6 | 需将相对输入路径基于代码库根目录进行解析——这样无论当前工作目录是什么，jsonl路径都能正常解析。 |
| R3.7 | 仅测量模型调用期间的耗时，而非I/O操作耗时：`t0 = time.time()` … `elapsed = time.time() - t0`。 |
| R3.8 | 仅按游戏分类模式下才通过`paths.write_task_meta()`写入`meta.json`。 |
| R3.9 | 同时提供`run_batch(self, inputs: list[dict]) -> list[dict]`，其实只是对`run`函数的列表推导实现。 |
| R3.10 | 提供`eval(self, result: dict, task: dict) -> dict`；该函数会调用`metrics.evaluate(result, task)`，仅读取已存在的产物文件，且不会被`run()`调用。 |

### 返回的字典

必填键：

| 键名 | 类型 | 说明 |
|-----|------|------|
| `task_id` | `str` | 原样返回 |
| `elapsed_sec` | `float` | 保留两位小数 |
| `<artifact>_path` | `str` | 每个产物对应一个路径，例如`glb_path`、`tpose_rgba_path` |
| `game_id` | `str` | 旧版扁平模式下该值为`""` |
| `task_kind` | `str` | 模块级别的`TASK_KIND`常量 |
| `output_dir` | `str` | 存放该任务所有产物的目录 |

**兼容性说明：**这些键会被`run.py`、`eval.py`以及`<REPO_PATH>/test/`使用。添加新键是安全的；但删除、重命名或更改键的用途会导致不兼容——`<REPO_PATH>/tests/harness/smoke.py`将会运行失败。

可选产物对应的值为`None`，而非缺失键（参见`tpose_rgb_path`）。

## R4 — 模块级常量

```python
TASK_KIND = "3d_object"      # 需在pipeline/common/paths.py中注册
GLB_FILENAME = "model.glb"   # 按游戏分类模式下的产物文件名
```

产物文件名应为常量，切勿在调用时动态生成f-string：在按游戏分类模式下，`task_id`本身已是目录名，因此文件名必须**通用**（如`model.glb`，而非`sword_001.glb`）。这样能简化后续的文件匹配操作。

## R5 — `funcs/`| # | 规则 |
|---|------|
| R5.1 | 每个逻辑步骤对应一个文件；公共函数的名称与文件名保持一致。 |
| R5.2 | 近似纯函数：接收PIL/numpy/基本数据类型以及注入的模型，返回PIL/numpy。**不执行磁盘写入操作**。 |
| R5.3 | 私有辅助函数以 `_` 为前缀；只有流水线函数是公开的。 |
| R5.4 | 提示词模板作为模块常量存放于此（参见 `TPOSE_PROMPT`），绝不允许放在 `operator.py` 中。 |
| R5.5 | 当中间结果有用时，设置 `return_intermediate: bool = False`；若设为 `True`，则返回包含各阶段结果的字典。 |
| R5.6 | 模型类型调度（掩码模型与深度模型）在此处处理，既不在模型中处理，也不在运算符中处理。 |
| R5.7 | 重命名参数时需保留向后兼容的别名（参见 `depth_model` → `mask_model`）。 |

## R6 — `metrics/` 目录相关规则

| # | 规则 |
|---|------|
| R6.1 | 需提供 `evaluate(result: dict, task: dict) -> dict[str, float]` 接口。 |
| R6.2 | 输入为运算符返回的字典加上原始任务字典——从 `result["output_dir"]` 中读取生成物。 |
| R6.3 | 返回扁平、可序列化为JSON的 `{metric_name: float}` 结构。禁止嵌套，也禁止包含numpy标量。 |
| R6.4 | 绝不重新生成任何内容。指标计算仅读取数据。 |
| R6.5 | 需要依赖大型模型的指标，应将其作为注入参数传入，处理方式与运算符一致。 |
| R6.6 | 若生成物缺失或损坏，则将对应指标值设为 `0.0`，同时添加键名为 `"error"` 的错误信息，切勿抛出异常。 |

## R7 — 文档字符串模板

```python
"""
operators/<task>/operator.py

Gen<Task>Operator —— 接收一个已加载的<模型类型>，将输入字典处理为<生成物描述>。

该运算符刻意设计为与模型无关：可注入任何实现了<预期接口>的对象。

输出布局有两种模式，由是否指定 `output_dir` 决定：
  * 按游戏划分（默认）：test_data/outputs/<game_id>/<run_id>/assets/<种类>/<task_id>/
  * 扁平模式（传统方式）：<output_dir>/<task_id>.<扩展名>

使用示例：
    ...
"""
```

## R8 — 检查清单

- [ ] 已在 `<REPO_PATH>/pipeline/common/paths.py` 中设置并注册 `TASK_KIND`。
- [ ] 模型以注入方式传入，绝不在运算符内部加载。
- [ ] 当 `output_dir=None` 时采用按游戏划分的布局；若指定 `output_dir="..."` 则保持传统的遗留行为。
- [ ] 运算符中包含 `run(inp: dict) -> dict` 和 `run_batch(...)` 方法。
- [ ] 返回的字典中包含 `task_id`、`elapsed_sec`、`<生成物>_path`、`game_id`、`task_kind`、`output_dir` 字段。
- [ ] 不删除或重命名已有的返回键。
- [ ] 按游戏划分模式下会写入 `meta.json` 文件。
- [ ] 算法步骤存放在 `funcs/` 目录下，提示词作为常量定义在那里。
- [ ] `metrics/evaluate(result, task)` 和 `operator.eval(result, task)` 接口已存在（或明确标注了待实现计划）。
- [ ] 代码中不含 `argparse` 调用、模型加载逻辑，也无硬编码的输出路径。
- [ ] 该模块在仅安装CPU版本且无权重文件的情况下可正常导入。
- [ ] 已在 `<REPO_PATH>/tests/harness/stubs.py` 中注册存根（`STUB_OPERATOR_KWARGS` 和 `OPERATOR_LOCATION`）。
- [ ] 运行 `python tests/harness/smoke.py --kind <种类>` 测试通过（覆盖两种输出模式）。
