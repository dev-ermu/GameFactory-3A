# model_require_zh.md — `models/` 目录的规范

`<REPO_PATH>/models/` 下的文件是**对单个模型的精简封装**。它知晓模型的权重、数据类型、运行设备以及该模型的原生 API。它完全不了解任务、jsonl 文件、游戏项目或输出目录相关信息。

> 必需接口：每个模型都必须实现 `__init__()` 和 `infer()`。
> 每个模型对应一个文件：`<REPO_PATH>/models/<家族名>/<模型名>_model.py`，类名为 `<名称>Model`。
> 模型专用的辅助函数应放在 `<REPO_PATH>/models/<家族名>/<模型名>_utils/` 目录下。

> **封装闭源云 API**（如 Tripo、Meshy、Rodin、Kling 等）？本规范默认模型使用本地权重。请查阅 `api_model_require_zh.md`——该文档新增了 **R9** 条款，用于覆盖 R2.1–R2.3、R3.3/R3.4、R3.6 及 R4 条款，适用于远程模型，同时明确了偏差情况的标注规则。

示例：
- 生成类模型：`<REPO_PATH>/models/gen_3d_object/tripo_model.py`、`<REPO_PATH>/models/gen_image/seedream_model.py`

本仓库没有工具类模型这一层：不存在任何本地权重封装，`models/tools/` 目录也不存在。T型姿势渲染所需的前景提取来自提示词所钉死的纯白背景，而非抠图模型。

---

## R1 — 硬性规则

| 编号 | 规则 | 原因 |
|---|------|-----|
| R1.1 | **禁止从 `<REPO_PATH>/operators/` 或 `<REPO_PATH>/pipeline/` 导入任何内容。** | 依赖关系只能向下传递。 |
| R1.2 | **绝不构造输出路径。返回内存中的数据（PIL / numpy / tensor / trimesh）。** | 输出文件的存放由操作符模块负责。 |
| R1.3 | **禁止使用 `argparse`，也不得编写 `if __name__ == "__main__"` 相关的业务逻辑。** | 命令行接口功能由 `run.py` 实现。 |
| R1.4 | **不涉及任务语义。不得使用 `task_id`、`game_id`，也不得为特定任务编写提示词模板。** | 提示词相关逻辑属于 `<REPO_PATH>/operators/<任务名>/funcs/` 目录。 |
| R1.5 | 重量级依赖（`torch`、`diffusers`、第三方库）若属于可选依赖，应放在 `__init__` 或 `_load()` 内部，以便该模块能在仅搭载 CPU 的设备上被导入。 | `<REPO_PATH>/tests/harness/smoke.py` 必须能在没有模型权重的情况下导入整个流程链。 |
| R1.6 | 当缺少环境前提条件时，需快速抛出包含**可操作指引**的错误信息。 | 可参考 `tripo_model.py` 中对缺失 API Key 的检查逻辑。 |

### R1.2 — 唯一例外情况

仅当底层库的数据序列化效率高于通过内存进行数据来回传输时，才允许提供 `infer_and_save(..., output_path)` 这类便捷方法（例如 TRELLIS.2 可直接导出带纹理图集的 GLB 文件）。相关要求如下：
- 输出路径由调用方传入，模型内部绝不能直接生成该路径；
- 需对父目录执行 `mkdir(parents=True, exist_ok=True)` 操作；
- 该方法需返回路径字符串；
- 模型中必须同时存在返回内存数据的 `infer()` 方法。

### R1.2.1 — 可选的中间过程观测功能

此功能为可选，默认禁用。模型可以设置 `observe_intermediates=False` 和/或 `on_intermediate=None`，以返回用于调试或监控的内存中的中间阶段元数据或预览图。除非明确启用，否则模型不得计算、打印或保存中间结果；显示、持久化及审核功能由操作符/流水线模块负责。

---

## R2 — 构造函数

```python
def __init__(self, model_path: str | list[str], device: str = "cuda", **model_specific):
```| # | 规则 |
|---|------|
| R2.1 | 第一个位置参数表示模型权重路径——可以是本地路径或HuggingFace仓库ID；若某个封装器需要加载多个模型，则使用`list[str]`类型。 |
| R2.2 | 将该参数命名为`model_path`。 |
| R2.3 | 默认设备设置为`device: str = "cuda"`，且必须支持指定为`"cpu"`。 |
| R2.4 | 在加载模型前，需将所有构造函数参数存储到`self`中，以便实现`unload()`/`load()`操作的往返调用。 |
| R2.5 | 所有额外参数都需有可用的默认值。仅通过`Model(path)`即可完成初始化。 |

## R3 — 推理规则

| # | 规则 |
|---|------|
| R3.1 | 仅设置一个公开的推理入口：**`infer()`**。 |
| R3.2 | 接收输入**对象**，而非文件路径。支持`Image.Image`、`np.ndarray`、字符串提示词，绝不允许传入`"path/to/x.png"`这类路径。 |
| R3.3 | 若模型属于随机性算法，需支持参数`seed: int = 42`，且实际要为该生成器设置种子。 |
| R3.4 | 在固定的设备上，对于相同的`(输入, 种子)`组合，输出结果必须确定一致。 |
| R3.5 | 返回类型需在文档字符串中明确说明且保持稳定，不得直接返回裸元组。 |
| R3.6 | 推理过程需包裹在`torch.no_grad()`或`torch.inference_mode()`上下文中。 |
| R3.7 | 除非显式开启`verbose`标志，否则不得打印进度信息。 |

## R4 — 生命周期管理规则

| # | 规则 |
|---|------|
| R4.1 | 当模型占用的显存超过1GB时，需提供`unload()`方法：将模型移至CPU，执行`del`、`gc.collect()`以及`torch.cuda.empty_cache()`操作。 |
| R4.2 | `unload()`方法是幂等的——即使调用两次或在加载失败后仍可安全调用。 |
| R4.3 | 若存在`unload()`方法，调用`infer()`时应能透明地重新加载模型。 |
| R4.4 | 云端后端完全不需要生命周期管理：调用之间不驻留任何资源，因此没有需要卸载的东西。 |

## R6 — 模型可替换性

用于同一算子插槽的两个封装器必须能够互换，且不会引发算子的行为变化。具体来说，共用同一插槽的两个云端后端——`TripoModel`与`MeshyModel`——都符合
`infer_and_save(image, output_path, seed, decimation_target, texture_size)`这一接口规范，因此`<REPO_PATH>/operators/gen_3d_object/operator.py`可以在不改动自身代码的情况下切换后端。

为现有插槽添加第二个后端时需注意：
1. 必须与现有的函数签名及返回类型完全一致；
2. 若语义确实存在差异，应由**算子的`funcs/`模块**来处理这种差异，而非由模型本身处理；
3. 需将其添加到`<REPO_PATH>/models/README_zh.md`中的候选模型表中。

## R7 — 文档字符串模板

```python
"""
<Name>Model — <一句话说明：它封装了什么以及输出结果是什么>。

参考来源：<论文链接 / Hugging Face模型卡片 / 代码仓库URL>

<任何环境前置要求：编译好的扩展、最低显存要求、额外的pip依赖项。>

使用示例：
    from models.<家族名>.<模型名>_model import <Name>Model
    model = <Name>Model(model_path="<hf/repo-id>")
    out = model.infer(image, seed=42)
"""
```

每个公开方法都需注明参数（`Args`）、返回值（`Returns`），若是数组类型还需说明**形状及数值范围**。

## R8 — 检查清单
- [ ] 一个文件对应一个模型，文件名为`<模型名>_model.py`，类名为`<Name>Model`
- [ ] `<REPO_PATH>/models/<家族名>/__init__.py`中已导出该模型（工具类模型需在两个`__init__.py`中均导出）
- [ ] `model_path`参数既支持本地路径，也支持Hugging Face模型库ID
- [ ] 指定`device="cpu"`时可正常运行
- [ ] 未从`<REPO_PATH>/operators/`或`<REPO_PATH>/pipeline/`导入任何内容
- [ ] 未在代码内部构造输出路径（或者说：`output_path`是作为参数传入的）
- [ ] 参数`seed`可被接收并生效；相同种子值会产生相同的输出结果
- [ ] 推理过程中使用了`torch.no_grad()`或`inference_mode()`
- [ ] 针对大型模型提供了`unload()`方法，且该方法是幂等的
- [ ] 已文档化返回结果的形状、数据类型及数值范围
- [ ] 已将其添加到`<REPO_PATH>/models/README_zh.md`的表格中
- [ ] `<REPO_PATH>/tests/harness/stubs.py`中存在对应的桩代码，且执行`python tests/harness/smoke.py --kind <kind>`测试能通过
