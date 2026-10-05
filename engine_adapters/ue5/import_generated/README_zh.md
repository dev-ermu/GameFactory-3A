# ue5/import_generated

该脚本可将`models/gen_3d_object`生成的文件转换为可在UE5中使用的资产。

> 范围说明：此目录是**生成资产的导入器**。引擎接口函数及相关代码已在任务1中被迁移到上一级目录`engine_adapters/ue5/`中；需将两者区分开。

## 文件说明

| 文件 | 运行环境 | 用途 |
|------|---------|------|
| `import_mesh.py` | Unreal的Python环境 | 执行导入→验证→生成报告 |
| `../../../scripts/import_generated_asset.py` | 宿主Python环境 | 定位编辑器、启动上述脚本并读取生成的报告 |

## 快速入门

```bash
# 导入单个资产
python scripts/import_generated_asset.py \
    --src test_data/outputs/<game>/<run>/assets/3d_object/<task>/model.glb \
    --engine ue5 --uproject D:/proj/MyGame/MyGame.uproject

# 导入某次生成任务产生的所有资产
python scripts/import_generated_asset.py --engine ue5 \
    --summary test_data/outputs/<game>/<run>/3d_object_results_summary.json
```

也可直接调用引擎。参数会通过名为`AAAGF_IMPORT_JOB`的**作业文件**传递，因为`-script="file.py --a b"`这种写法需要同时兼容Shell和UE自身的参数解析器，且路径中的引号会在传输过程中丢失：

```bat
echo {"src":"C:/out/model.glb","dest":"/Game/Generated/Meshes", ^
      "name":"Sword_001","usage":"asset","report":"C:/out/ue5_import.json"} > C:/out/job.json
set AAAGF_IMPORT_JOB=C:/out/job.json
set AAAGF_UE_QUIT_WHEN_DONE=1
UnrealEditor.exe MyGame.uproject ^
  -ExecutePythonScript=engine_adapters/ue5/import_generated/import_mesh.py ^
  -unattended -nopause -nosplash -stdout
```

### 为何选择完整版编辑器而非命令小程序

默认情况下，`--ue-mode editor`参数会启动`UnrealEditor.exe`；而`--ue-mode commandlet`参数会启动`UnrealEditor-Cmd.exe -run=pythonscript`，这种方式启动更快且不会弹出窗口。

**但该命令小程序模式在UE 5.7中无法正常工作。** AssetTools的两个入口点（`import_assets_automated`和`import_asset_tasks`）虽然能完成资产导入，但在同步Content Browser时会触发断言错误，原因是命令小程序没有Slate应用程序。`FSlateApplication::Get()`函数会在此处报错。实际上网格体是先被构建并保存的，因此崩溃表现类似“导入成功但随后出现堆栈转储”。这是实测结果，并非猜测：

```
LogStaticMesh: 已构建静态网格体 /Game/Generated/Meshes/StubSword
LogInterchangeEngine: Interchange导入完成 [.../stub_sword.glb]
LogWindows: 错误：断言失败：CurrentApplication.IsValid()
            [SlateApplication.h] [行号：321]
```

`InterchangeManager.import_asset`函数可绕过AssetTools且不会引发崩溃，但通过脚本调用的方式是异步的：它会在资产实际生成前就返回结果。因此该函数仅作为备选方案，并非最佳解决方案。

若未来版本修复了同步问题，`--ue-mode commandlet`又会成为更快捷的选择，无需改动其他代码。

在编辑器的Python控制台中，也可使用常规的CLI参数：

```python
import import_mesh
import_mesh.main(["--src", "C:/out/model.glb", "--dest", "/Game/Generated/Meshes"])
```该项目需要启用**Python编辑器脚本插件**：

```json
"Plugins": [ { "Name": "PythonScriptPlugin", "Enabled": true } ]
```

`--report`参数会始终输出处理结果，因此调用方无需解析日志来获取结果：

```json
{
  "ok": true,
  "asset_path": "/Game/Generated/Meshes/Sword_001",
  "tris": 24418, "vertices": 12907, "lods": 1,
  "bounds": {"origin": [...], "box_extent": [...], "sphere_radius": 71.4},
  "materials": ["Material_0"],
  "warnings": []
}
```

## 文件格式

| 格式 | 路径 | 说明 |
|------|------|------|
| `.glb` / `.gltf` | Interchange glTF转换器 | 所有后端的默认输出格式；单文件，纹理内嵌 |
| `.fbx` | `FbxImportUI`（新版本中也可使用Interchange） | 当项目无法使用glTF时的备选格式 |
| `.obj` / `.usd` | Interchange | 此处未经过测试 |

如果`.glb`格式无法生成任何内容，请**启用glTF导入插件**——脚本会明确提示这一点，而非静默失败。

## 坐标系——已验证，非假设

glTF采用Y轴向上、右手定则、公制单位；而UE采用Z轴向上、左手定则、厘米单位。**转换器会完成全部坐标转换**，因此无需预先旋转或缩放文件。在UE 5.7中测试一个尺寸为1.0 × 1.0 × 1.1米的GLB文件时：

```
"bounds": {"origin": [50.0, 55.0, 50.0], "box_extent": [50.0, 55.0, 50.0]}
```

1米对应100 uu，glTF中的Z轴（即1.1米维度）在UE中对应Y轴。三角形和顶点数量完全匹配（12个三角形，36个顶点）。

每次导入的结果报告中都会包含边界信息，因此可以针对每个资产进行核查，而非仅凭文档中的假设判断。

## `--usage`参数——分为三个层级，默认值为非VFX类型

`gen_3d_object`主要生成普通游戏资产，VFX属于可选分支。

| `--usage` | 适用场景 | 三角形数量 | 轴心点 | 缩放 |
|-----------|---------|-----------|-------|-------|
| `asset`（默认值） | 道具、武器、角色 | 保持原样 | 保持原样 | 保持原样 |
| `vfx_standalone` | 能量护盾/光束/刀光弧——单个网格，无粒子效果 | 保持原样 | 重新居中（若物体从地面生长，可使用`--pivot bottom`参数） | 可选 |
| `vfx_particle` | 剑风暴/碎片/群集——由Niagara实例化的网格 | 每个网格的三角形数量乘以实例数即为预算 | 重新居中 | 标准化为1米 |

`--target-tris`仅为建议性参数，默认不设置上限：对于一把在屏幕上仅占据40像素且带有发光效果的剑来说，2000个三角形就足够了；而Nanite技术和GPU模拟进一步提升了这一上限。具体需根据实际帧时间来判断。

**应在生成阶段就减少多边形数量，而非事后处理**——使用`TripoModel(low_poly=True)`或`decimation_target=...`参数可保留UV坐标和法线信息；若事后对拥有200万个面的网格进行简化，则会丢失这些信息。如果超过`--target-tris`设定的数值，脚本会尝试进行简化，并会记录相应警告信息。

## 验证结果

已在**UE 5.7**环境下测试，启用`--ue-mode editor`参数，分别在空白项目和真实项目中运行（其中一个是VFX项目，其`.uproject`文件中原本未启用Python插件；本次运行时通过`--ue-extra=-EnablePlugins=PythonScriptPlugin`临时开启该插件，且未修改项目文件）。一个**带纹理的**GLB文件（立方体，内嵌PNG图像，PBR材质）：

```json
{
    "ok": true,
    "asset_path": "/Game/Generated/Meshes/AAAGF_SmokeCube",
    "tris": 12,
    "vertices": 24,
    "lods": 1,
    "bounds": {"origin": [50,50,50], "box_extent": [50,50,50]},
    "materials": ["StubCheckerMaterial"],
    "warnings": [
        "导入了3个资源（…/Textures/StubChecker、…/Materials/StubCheckerMaterial、…/StaticMeshes/stub_cube_textured）",
        "资源已从…/stub_cube_textured移动至…/AAAGF_SmokeCube"
    ]
}
```

几何数据、单位转换、材质、内嵌纹理以及磁盘上的三个`.uasset`文件均符合预期。可通过`tests/harness/stubs.py:make_textured_glb()`复现该测试场景，无需使用API密钥。

导入器针对Interchange的两个行为做了特殊处理，这些异常会在警告信息中体现而非被隐藏：
- 它会根据**源文件**命名资产，并将其存放在`<file>/StaticMeshes/`目录下，会忽略导入任务中的`destination_name`参数；之后会将网格移动到`<dest>/<name>`路径下；
- 它会将纹理和材质作为**独立的包**导出。若仅保存网格，它们会在内存中处于未保存状态，编辑器会因网格引用了尚未写入磁盘的材质而崩溃，因此每个导入的包都会被自动保存。

一个**真实生成的资产**（由Meshy工具从图像转为3D模型，大小8.4 MB，含19288个三角形、4种内嵌PBR纹理），导入到真实的VFX项目中后会生成6个已保存的资产：4个`Texture2D`、1个`Material`、1个`StaticMesh`。

对该资产使用`--usage vfx_particle`参数后验证结果同样正常：`automated`流程被跳过（该流程无法处理导入偏移量），流程转而执行`task`流程，通过复制的Interchange管线完成导入；最终得到的模型边界被重新居中，其`box_extent`值为[39.4, 47.4, 50.0]——即最大的边界值被归一化为恰好100 uu。

有个小问题：两种流程对生成的材质和纹理的存放位置不同。`automated`流程会将它们放在`<source>/Materials/`和`<source>/Textures/`目录下；而`task`流程则将它们直接存放在目标文件夹中。因此用两种方式导入同一个源文件时，会生成两组资源，每组分别被对应的网格引用。

**尚未验证的内容**：FBX/OBJ/USD格式的导入路径、多材质资产以及`--target-tris`缩减功能。所有可选的引擎属性在使用前都会通过`getattr`进行探测，因此若构建版本中缺少某个属性，只会会在报告中显示警告，而不会导致崩溃。

## 项目打开时请勿运行此程序

导入器会启动自己的编辑器进程。如果在编辑器已经打开项目的情况下运行该程序，就会导致同一个项目同时有两个编辑器实例：资源虽已写入磁盘，但打开的编辑器仍会显示内容浏览器中的旧视图，这看起来就像是“导入操作悄无声息地失败了”。请先关闭编辑器，或导入完成后重新打开编辑器。

## Nanite会改变`tris`的含义

UE 5.7会对导入的静态网格启用Nanite功能，此时`StaticMesh.get_num_triangles(0)`返回的会是**回退网格**的三角形数量——该回退网格是按照相对误差要求生成的，并非源模型的三角形密度。以上述资产为例进行测量可得：| | 三角形数量 |
|---|---|
| 源GLB文件 | 19,288 |
| Unity引擎 | 19,288 |
| UE中调用`get_num_triangles(0)`的结果 | **4,480** |

导入过程中没有数据丢失；只是这两款引擎识别出的网格数据不同。
UE自身的构建日志中会完整显示这三个数值：

```
LogStaticMesh: 邻接信息处理耗时[0.01秒]，三角形数量：19288，UV通道数：1     ← UE从文件中读取到的数据
LogStaticMesh: 回退处理耗时[0.15秒]，三角形数量：4480          ← get_num_triangles(0)返回的结果
LogStaticMesh: 约束簇处理：输入簇数量：311个，三角形数量：39188个
```

这39,188个三角形是整个Nanite簇层级结构中的三角形总数——包含19,288个叶子节点三角形，以及LOD有向无环图中更粗糙的父级层级三角形，数值约为前者的2倍，这属于正常现象。

因此相关报告中会包含`source_tris`（引擎启动前启动器从GLB文件中读取的三角形数量）以及紧邻`tris`字段的`nanite`块：

```json
{"tris": 4480, "source_tris": 19288,
 "nanite": {"enabled": true, "fallback_percent_triangles": 1.0,
            "fallback_relative_error": 1.0}}
```

计算网格粒子预算时应以`source_tris`为准，而非`tris`——同时要记住，Nanite本身就会大幅放宽这一预算限制（参见第B4.2节）。

## 法线贴图规范
glTF格式的法线贴图遵循OpenGL规范（绿色分量朝上）；而UE默认采用DirectX规范（绿色分量朝下）。Tripo甚至将其生成的法线贴图命名为`NormalGL_*`。转换工具理应能处理这种方向翻转问题，但一旦绿色通道处理不当，只会表现为光照方向错误，这类问题不会在报告中体现。首次导入带有法线贴图的资源时，值得用移动光源检查一下效果。
