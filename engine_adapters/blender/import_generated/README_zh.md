# Blender/导入生成资源

将`models/`目录生成的文件转换为经过处理、测量后的Blender资产。

> 范围说明：该目录是**生成资产的导入器**。上一级目录`engine_adapters/blender/`中的绑定/重定向/预览代码对应“Blender如何实现X功能”；而本目录的功能是“如何将我们的产物导入Blender”。需将两者区分开。

## 文件说明

| 文件 | 运行环境 | 用途 |
|------|---------|------|
| `import_mesh.py` | `bpy`解释器 | 导入→处理→测量→导出→生成报告 |
| `../../../scripts/import_generated_asset.py` | 宿主Python环境 | 定位Blender，启动上述脚本，读取生成的报告 |

## 快速入门

```bash
# 通过启动器导入单个资产
python scripts/import_generated_asset.py --engine blender \
    --src test_data/outputs/<game>/<run>/assets/3d_object/<task>/model.glb \
    --blender-preview

# 导入某次生成任务产生的所有资产
python scripts/import_generated_asset.py --engine blender \
    --summary test_data/outputs/<game>/<run>/3d_object_results_summary.json
```

也可以直接调用Blender。参数会通过名为`AAAGF_IMPORT_JOB`的**作业文件**传递——该文件名与UE5导入器使用的名称一致，因此启动器会为每种引擎生成对应格式的作业文件：

```bash
echo '{"src":"/out/model.glb","dest":"/out/library","name":"Sword_001",
       "usage":"asset","export":["glb"],"report":"/out/blender_import.json"}' > /out/job.json
AAAGF_IMPORT_JOB=/out/job.json AAAGF_BLENDER_EXIT_ON_DONE=1 \
blender --background --factory-startup --python import_mesh.py
```

`AAAGF_BLENDER_EXIT_ON_DONE`参数至关重要：执行`blender --background --python x.py`时，无论脚本返回什么结果，进程都会退出并返回0；如果没有该参数，导入失败的情况会被检查退出码的用户误认为是成功。

也可以使用普通的命令行参数，只需在Blender的`--`之后传入即可：

```bash
blender --background --factory-startup --python import_mesh.py -- \
    --src /out/model.glb --dest /out/library --usage vfx_particle --preview
```

## 支持的格式

| 格式 | 对应的操作符 | 说明 |
|------|--------------|------|
| `.glb` / `.gltf` | `import_scene.gltf` | 所有后端的默认输出格式；坐标轴和单位转换会自动完成 |
| `.fbx` | `import_scene.fbx` | |
| `.obj` | `wm.obj_import`，否则为`import_scene.obj` | Blender 4.x版本用C++版本的导入器替换了Python版本的导入器 |
| `.ply` | `wm.ply_import`，否则为`import_mesh.ply` | 在涉及任何引擎之前，用于查看世界导出数据 |
| `.stl` | `wm.stl_import`，否则为`import_mesh.stl` | |
| `.usd` / `.usda` / `.usdc` / `.usdz` | `wm.usd_import` | |
| `.abc` | `wm.alembic_import` | |

对于这三种格式，程序会尝试查找对应的操作符，因此同一文件在Blender 3.6和4.x版本中都能正常使用。如果构建版本中未提供任一操作符，程序会输出提示信息，列出缺失的两个操作符名称，而非抛出`AttributeError`异常。

## “处理”涵盖的内容| 步骤 | 执行时机 | 为何在此处处理而非在引擎中处理 |
|------|------|--------------------------------------|
| 合并网格 | 只要导入时生成了多个网格，就始终执行 | 游戏资产应视为一个对象；在测量前合并网格后，得到的`tris`（三角形数量）才是引擎实际识别的数值。 |
| 设置枢轴点 | 通过`--pivot`参数指定，或采用层级默认设置 | 该操作作用于**网格数据**，而非对象的变换属性，因为导出工具会忽略变换信息。 |
| 归一化缩放 | 通过`--normalize-scale`参数启用 | 将最大边界尺寸调整为1米（UE5导入工具中该值为100，实际单位为厘米）。 |
| 简化网格 | 通过`--target-tris`参数指定 | 应用简化网格修饰符。这只是备选方案而非首选——详见下文说明。 |
| 导出 | 通过`--export glb fbx blend`参数指定 | 这是整个流程的最终目的：为引擎提供其支持的格式。一个参数可对应多个值——重复指定`--export`会覆盖之前的设置而非累加。 |
| 预览 | 通过`--preview`参数启用 | 生成一帧Cycles-CPU渲染结果；`../render_preview.py`脚本可提供更丰富的预览功能。 |

## `--usage`参数——分为三个层级，默认选项并非VFX用途

该参数与UE5导入工具的设定一致，因此无论资产被哪个引擎使用，`--usage`参数的含义都相同。

| `--usage`参数 | 适用场景 | 三角形数量 | 枢轴点 | 缩放 |
|-----------|-----|-----------|-------|-------|
| `asset`（默认） | 道具、武器、角色 | 保持原样 | 保持原样 | 保持原样 |
| `vfx_standalone` | 单个网格，无粒子效果 | 保持原样 | 重新居中 | 可选 |
| `vfx_particle` | 由粒子系统实例化的网格 | 预算 = 每个网格的三角形数 × 实例数量 | 重新居中 | 归一化为1米 |

**应在生成阶段就进行简化，而非在此处处理。** 使用`TripoModel(low_poly=True)`或`decimation_target=...`参数能在保留UV坐标和法线信息的同时简化网格；而对已完成的网格应用简化修饰符则会破坏这些信息。`--target-tris`参数总会输出相关警告提示这一点。

## 报告即约定

`--report`参数会始终详细描述处理结果，因此调用方无需解析日志：

```json
{
  "ok": true,
  "object": "Sword_001",
  "tris": 24418, "vertices": 12907, "source_tris": 24418,
  "bounds": {"min": [...], "max": [...]},
  "dimensions": [0.31, 0.08, 1.04],
  "materials": ["Material_0"],
  "exports": {"glb": "/out/library/Sword_001.glb"},
  "preview": "/out/library/Sword_001_preview.png",
  "warnings": []
}
```

`source_tris`数值是启动Blender之前由启动器从文件中读取的，因此若其与`tris`数值不一致，说明是处理过程改变了网格，而非导入环节导致了数据丢失。

## 世界场景导出

世界场景导出文件并非网格文件，而是Gaussian-splat格式的PLY文件加上一个或多个多边形PLY文件。需先通过`scripts/prepare_world_asset.py`脚本处理——该脚本会合并各部分并修复表面问题——之后才能像其他资产一样导入生成的`world.glb`文件。直接导入原始的碰撞体PLY文件虽可行，且可用于查看生成器输出的内容，但这类文件会呈现为“三角形杂乱堆”：顶点不共享、图层间有缝隙、缠绕方向混乱。

## 已验证该操作在 **Blender 5.0.1** 环境下执行，通过 Python 3.11 版本的 pip `bpy` 安装包运行，未启用显示功能且未使用 GPU。导入、三个层级处理、轴心点调整、归一化、简化多边形数量操作，以及三种导出格式的处理、Cycles-CPU 渲染静帧和旋转动画生成、整个场景数据链的处理均为手动操作；下述数值均来自该次操作会话。如需复现操作步骤：

```bash
pip install bpy numpy scipy pillow      # 该安装包仅支持 Python 3.11 版本

python scripts/prepare_world_asset.py --src <export_dir> \
    --out-dir /tmp/world --task-id arena --up z --min-component-faces 4
python engine_adapters/blender/import_generated/import_mesh.py \
    --src /tmp/world/world.glb --dest /tmp/lib --name Arena --preview
```

路由的宿主端相关逻辑——作业文件、参数配置、层级默认值、操作符表等——由 `tests/test_world_asset.py` 负责覆盖测试，该测试无需依赖 Blender。

以下数据均为实测结果，而非估算：

| | |
|---|---|
| GLB 格式往返转换 | 输入为包含12个三角形的立方体，输出后仍为12个三角形，`glb -> Blender -> glb -> Blender` 流程结束后模型尺寸完全一致 |
| 坐标轴转换 | glTF 格式的 `(x, y, z)` 坐标在 Blender 中会被转换为 `(x, -z, y)`；使用 `--up z` 参数生成的 Z轴朝上的场景最终会呈扁平状态，坐标变为 `[2, 1, 0]` |
| 修复后的场景 | 包含258个三角形、154个顶点——与 `prepare_world_asset.py` 输出的结果完全一致 |
| 多边形简化 | 原始模型有258个三角形，设置 `--target-tris 60` 参数后最终简化为60个三角形，同时会触发相应警告信息 |
| `vfx_particle` 粒子系统 | 边界被重新居中到 ±0.5 / ±0.25 范围内，最大边界尺寸被归一化为 1.0 米 |
| 原始碰撞体 PLY 文件 | 包含126个三角形、378个顶点，证明PLY 文件中的顶点并未共用角落 |

最严格的验证方式是在导入后使用 `bmesh` 统计边界边数量，因此修复效果是根据 Blender 的拓扑结构来评估的，而非依据执行修复的代码：`0` 条非流形边，恰好有 **48** 条边界边，这对应着边长为2×1、每单位细分8次的平面模型的外轮廓——所有内部裂缝均已闭合，仅保留了该捕获区域自身的边界。若未经修复，同一输入模型会有765条边界边，分散为255个独立的零散部分。

## Blender 5.0 的两项变更

这两项变更已被妥善处理，且都属于那种看似与其他问题相关的故障类型：
- **相对输出路径会导致内容无法写入**。Blender 会将相对路径解析为相对于.blend 文件的路径，而无头模式下的导入操作没有对应的.blend 文件；即便如此，`render()` 函数仍会返回 `FINISHED` 状态。现已将所有输出路径转为绝对路径，且仅在确认文件已写入磁盘后才会将其列入报告。
- **pip 安装包中完全不包含 FFMPEG 写入器**——`file_format` 枚举列表中根本没有对应选项，因此无法导出与 `--export` 参数相关的视频，而这一情况在 Blender 应用程序中并不会提示。预览功能会回退为 PNG 序列格式，并在警告信息中说明这一点。

旧版的 `import_mesh.*` 操作符在 5.0 版本中已被移除（对应命名空间为空），这正是为何代码中会对这两个名称进行探测而非直接硬编码的原因。
