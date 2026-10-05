# pipeline_require.md — `pipeline/`目录的契约

Pipeline目录会暴露一个小型的公共生成API：`run.load_*()`用于加载或复用所需的模型，`run.make_operator()`会将模型注入到Operator中，而`run.generate(inp, operator)`则用于生成一个资源。`run.py`会为Benchmark批量调用同一个`generate()`入口；`eval.py`仅用于对已有产物进行评分。

> 适用范围：本契约仅适用于`<REPO_PATH>/pipeline/assets_gen/`目录。公共API为`load_*()` → `make_operator()` → `generate(inp, operator)`；`run.py`负责批量执行，`eval.py`则构成资源生成的Benchmark链路。
>
> 对于已经加载好模型的调用方而言，`operator.run(inp)`是更低层级的、已注入模型的API。

```
pipeline/
├── common/paths.py                  # 所有输入输出路径的唯一权威来源
└── assets_gen/<task>/
    ├── run.py                       # 公共`generate()`接口 + Benchmark批量驱动程序
    └── eval.py                      # 仅用于Benchmark评分
```

参考实现：`<REPO_PATH>/pipeline/assets_gen/gen_3d_object/run.py`。

---

## R1 — 硬性规则

| # | 规则 | 原因 |
|---|------|-----|
| R1.1 | 该脚本能在**任意当前工作目录（CWD）下正常运行**——在导入任何本地模块前，需先将仓库根目录添加到`sys.path`中。 | 用户通常会通过`python pipeline/.../run.py`的方式调用它。 |
| R1.2 | **绝不要手动构建输出路径**，所有路径均来自`pipeline.common.paths`。 | 保证路径定义的一致性，作为唯一权威来源。 |
| R1.3 | `run.py`仅负责生成产物；`eval.py`从已有的`run_id`中读取产物并仅计算指标。 | 职责划分清晰：评估环节既不会导入生成相关代码，也不会触发资源生成流程。 |
| R1.4 | 每个必需的模块级函数都必须以指定名称存在。`<REPO_PATH>/test/`目录会导入这些函数进行测试。 | 这些函数是API的一部分，而非单纯为了符合编码风格要求。 |
| R1.5 | 模型导入操作必须放在`load_*()`内部，算子导入操作必须放在`make_operator()`内部。 | 这样即使没有CUDA环境，`--help`参数也能正常工作，同时烟雾测试也能正常导入该模块。 |
| R1.6 | 除了修改`sys.path`和定义常量外，导入时绝不能产生任何副作用。 | 该模块会被测试代码导入使用。 |

## R2 — `run.py`的必备结构

```python
TASK_KIND = "3d_object"                       # 在paths.py中注册的任务类型
DEFAULT_CKPT = "<hf/repo-id>"                 # 每个模型槽位的默认检查点
DEFAULT_TASKS = paths.collect_jsonl(TASK_KIND)

def load_model(ckpt, device="cuda", **kw): ...        # 每个模型槽位对应的加载函数
def make_operator(model, output_dir=None,
                  run_id=paths.DEFAULT_RUN_ID,
                  default_game_id=None): ...          # 唯一的 wiring 接入点
def generate(inp: dict, operator) -> dict: ...        # 对算子的轻量级封装
def run_from_jsonl(tasks_path, operator,
                   game_filter=None) -> list[dict]: ...
def main(): ...
if __name__ == "__main__": main()
```| # | 规则 |
|---|------|
| R2.1 | 任务所需的每个模型对应一个 `load_<slot>_model()` 函数（如 `load_gen_model`、`load_mask_model` 等）。每个函数都会输出正在加载的模型信息。 |
| R2.2 | `make_operator()` 需与操作符的构造函数一一对应，且直接原样传递参数。切勿在此处自行设定默认值。 |
| R2.3 | `generate(inp, operator)` 只需一行代码：`return operator.run(inp)`。 |
| R2.4 | `run_from_jsonl()` 通过 `paths.iter_tasks(tasks_path, game_filter=...)` 来迭代处理任务——切勿手动打开文件并执行 `json.loads`。 |
| R2.5 | 运行任务前和结束后各记录一行日志，日志中需包含 `game_id`、`task_id` 和 `elapsed_sec` 字段。 |
| R2.6 | `main()` 的职责仅为：解析命令行参数 → 加载模型 → 创建操作符 → 根据需求分支为单任务演示或批量处理 → 写入总结报告。别无其他功能。 |

## R3 — 标准命令行参数

所有任务中这些参数均保持一致，用户只需学习一次即可：

| 参数 | 默认值 | 说明 |
|------|---------|------|
| `--ckpt` / `--gen-ckpt` / `--mask-ckpt` | 优先读取环境变量，若未设置则取 `DEFAULT_*_CKPT` | 模型权重；可为本地路径或 Hugging Face 仓库 ID |
| `--game` | `None` | 限制仅处理某个游戏项目；也可作为 `default_game_id` 的备选值 |
| `--tasks` | `None` | 指定具体的 jsonl 文件，会覆盖 `--game` 的参数查找逻辑 |
| `--run-id` | `"default"` | 运行结果的存储目录名；设为 `"auto"` 时会调用 `paths.new_run_id()` 生成新目录名 |
| `--out-dir` | `None` | 传统扁平化输出模式；会绕过按游戏划分的目录结构 |
| `--device` | `"cuda"` | 指定运算设备 |
| `--image` / `--task-id` / 其他任务参数 | — | 单任务演示模式，无需使用 jsonl 文件 |

| # | 规则 |
|---|------|
| R3.1 | 检查点的优先级为：`命令行参数 > 环境变量 > DEFAULT_CKPT`，实现方式为 `default=os.environ.get("<VAR>", DEFAULT_CKPT)`。 |
| R3.2 | `--game` 参数的帮助信息中需通过 `paths.list_games()` 列出所有支持的游戏名称。 |
| R3.3 | 任务列表的解析逻辑为：`paths.resolve_tasks_path(TASK_KIND, args.tasks, args.game)` —— 优先使用指定的 jsonl 文件，其次使用该游戏自带的 `*_tasks.jsonl` 文件，最后才使用跨游戏的 `*_collect.jsonl` 文件。 |
| R3.4 | 单任务演示模式下需传入 `game_id=args.game`，这样临时运行的任务也能被存储在合理的目录下（若未指定 `game_id`，则存入 `_scratch` 目录）。 |
| R3.5 | 若任务结果为空，程序会打印提示信息并返回 0，这并不算作错误。 |

## R4 — 总结报告

```python
if args.out_dir:                       # 传统扁平化模式
    Path(args.out_dir, "results_summary.json").write_text(...)
else:                                  # 按游戏划分的模式
    paths.write_results_summary(results, TASK_KIND, run_id)
```

`write_results_summary()` 会按 `game_id` 对结果分组，针对每个游戏分别写入 `<task_kind>_results_summary.json` 文件，同时更新 `run_meta.json`（包含检查点、随机种子、Git commit hash、命令行参数等信息），并重新指向 `latest` 符号链接。切勿编写混合不同游戏结果的全局总结报告——这会破坏按项目划分的目录结构。

## R5 — `eval.py`

```python
# 定位指定 (game_id, run_id, TASK_KIND, task_id) 对应的已有产物。
# 通过 operator.eval(result, task) 计算其得分。
```| # | 规则 |
|---|------|
| R5.1 | 读取所请求的 `--game` / `--run-id` 对应的现有产物；绝不要导入 `run.py`、加载生成模型或触发生成操作。 |
| R5.2 | 从已解析的产物目录中，构建 `operator.eval(result, task)` 所需的最小结果字典。 |
| R5.3 | 各任务的得分需保存至 `paths.eval_output_dir(game, kind, task_id, run_id)/metrics.json`。 |
| R5.4 | 汇总结果并写入 `paths.eval_summary_path(game, run_id)`，其中包含各指标的平均值以及任务总数。 |
| R5.5 | 单个任务执行失败不得中止整个扫描流程：需将该错误记录到对应任务的 `metrics.json` 中，然后继续处理。 |
| R5.6 | 接受的 `--game` / `--run-id` / `--tasks` 参数与 `run.py` 中的参数一致。 |

## R6 — 注册任务类型

`<REPO_PATH>/pipeline/common/paths.py` 是唯一的注册点。需向四个表中各添加一条条目：

```python
TASK_LAYER["motion"]         = "assets"            # assets | mechanic | ui | pipeline
TASK_INPUT_DIR["motion"]     = "motion"            # test_samples/<game>/ 下的目录
TASK_JSONL["motion"]         = "motion_tasks.jsonl"
TASK_COLLECT_JSONL["motion"] = "motion_gen_collect.jsonl"
```

随后执行 `python tests/harness/smoke.py --kind motion`，即可验证这些表、运算符以及磁盘上的文件结构是否匹配。

## R7 — `tests/test_<task>.py`

| # | 规则 |
|---|------|
| R7.1 | 使用 `unittest` 框架；在 `setUpClass` 中仅加载一次模型。 |
| R7.2 | 从环境变量中获取检查点路径，默认值为 Hugging Face 仓库 ID。 |
| R7.3 | 使用 `run_id="_test"`，确保集成测试不会覆盖真实运行的数据。 |
| R7.4 | 从 `run.py` 中导入 `load_*` / `make_operator` / `run_from_jsonl`，绝不要重新构建处理链。 |
| R7.5 | 需断言：产物存在、大小合理、`elapsed_sec > 0`、父目录与 `paths.task_output_dir(...)` 一致，且 `meta.json` 文件存在。 |

## R8 — 检查清单

- [ ] 已设置 `TASK_KIND` 并在所有四个 `paths.py` 表中完成注册
- [ ] 已配置 `sys.path` 引导逻辑；可从任意当前工作目录下运行
- [ ] `load_*`、`make_operator`、`generate`、`run_from_jsonl`、`main` 均存在且名称完全一致
- [ ] 模型/运算符的导入操作均在函数内部完成
- [ ] 程序支持 `--game`、`--tasks`、`--run-id`、`--out-dir`、`--device` 等参数
- [ ] 可通过 `paths.iter_tasks` 迭代处理任务
- [ ] 可通过 `paths.write_results_summary` 生成汇总结果（支持按游戏模式输出）
- [ ] `eval.py` 仅读取现有产物，不会导入 `run.py` 或触发生成操作
- [ ] 执行 `python pipeline/assets_gen/<task>/run.py --help` 时无需依赖 CUDA 即可正常运行
- [ ] 执行 `python tests/harness/smoke.py --kind <kind>` 测试通过
