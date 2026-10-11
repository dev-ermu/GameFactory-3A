# unity3d/import_generated

将`models/gen_3d_object`生成的文件转换为Unity **预制件（prefab）**。

> 范围说明：该目录是**生成资源的导入器**。引擎接口函数和服务端代码已在任务1中迁移到上一级目录`engine_adapters/unity3d/`中；需将两者区分开。

## 文件说明

| 文件 | 运行环境 | 用途 |
|------|----------|------|
| `ImportGeneratedMesh.cs` | Unity编辑器（`Assets/Editor/`目录下） | 执行导入→生成预制件→验证→生成报告的操作 |
| `../../../scripts/import_generated_asset.py` | 宿主Python环境 | 定位Unity安装路径，将该脚本复制到项目中并启动，读取导入报告 |

## 快速入门

运行此命令前，必须先在对应的Unity Hub中激活Unity编辑器（或已打开已授权的编辑器）。授权管理由Unity Hub负责，而非此导入器；若返回退出码199，或出现缺失LicensingClient IPC通道的情况，均表明宿主环境不满足前置要求。

```bash
python scripts/import_generated_asset.py \
    --src test_data/outputs/<game>/<run>/assets/3d_object/<task>/model.glb \
    --engine unity --unity-project D:/proj/MyGame
```

启动器会先将`ImportGeneratedMesh.cs`复制到`<project>/Assets/Editor/`目录下——因为Unity仅编译位于名为`Editor`的文件夹中的编辑器代码，因此无法直接引用仓库中的该文件。若你已自行将该文件纳入项目，可添加`--no-install-editor-script`参数跳过复制步骤。

直接调用方式如下：

```bash
Unity -batchmode -quit -nographics -projectPath D:/proj/MyGame \
      -executeMethod ImportGeneratedMesh.RunFromCLI \
      --src C:/out/model.glb --dest Assets/Generated/Meshes \
      --name Sword_001 --report C:/out/unity_import.json
```

在编辑器中也有对应的操作入口：**3AGameFactory ▸ Import generated mesh…**。

## 前置条件：glTF支持

Unity没有内置的glTF导入器。需为每个项目单独安装一次glTFast：

```
窗口 ▸ 包管理器 ▸ + ▸ 按名称添加包 ▸ com.unity.cloud.gltfast
```

也可将其添加到`Packages/manifest.json`文件中：

```json
{ "dependencies": { "com.unity.cloud.gltfast": "6.16.0" } }
```

`ImportGeneratedMesh.cs`对该包**没有编译时依赖**——它会将相关文件复制到`Assets/`目录下，交由ScriptedImporter处理，若最终未生成有效资源则会返回可操作的错误信息。采用编辑时导入的方式是经过设计的：这样生成的真实资源可被预制件、VFX Graph和Timeline引用，而运行时的`GltfImport`无法实现这一点。

FBX和OBJ格式无需额外安装插件。若无法为项目添加glTFast，可生成FBX格式文件：`MeshyModel(output_format="fbx")`。

## 输出结果

```
Assets/Generated/Meshes/Sword_001.glb        导入的源资产
Assets/Generated/Prefabs/Sword_001.prefab    可拖入场景的预制件
```

导入报告：```json
{
  "ok": true,
  "assetPath": "Assets/Generated/Meshes/Sword_001.glb",
  "prefabPath": "Assets/Generated/Prefabs/Sword_001.prefab",
  "triangles": 24418, "vertices": 12907, "meshes": 1, "materials": 1,
  "materialDetails": ["model_material_0 | shader=glTF-pbrMetallicRoughness | tex: baseColorTexture=texture_0, normalTexture=texture_2"],
  "boundTextures": 4,
  "boundsCenter": [0,0,0], "boundsExtents": [0.35,0.71,0.04],
  "warnings": []
}
```

之所以存在`materialDetails`和`boundTextures`字段，是因为仅通过材质数量无法区分带纹理的资源和无纹理的白色材质资源：即便网格、材质和预制体都存在，也可能所有纹理槽都是空的。这种情况通常是glTFast与渲染管线不匹配导致的，现在系统会针对此类情况发出警告，而非默默忽略。

这里输出的是预制体而非单纯的网格文件，是因为预制体根节点用于存储枢轴偏移量和归一化缩放参数，且粒子系统和VFX Graph引用的是预制体。

## 坐标系说明

glTF和Unity均采用Y轴向上的度量单位制，因此无需进行坐标轴转换（而UE5采用Z轴向上、厘米为单位的坐标系）。glTFast会处理左右手坐标系的差异。

## `--usage`参数——共三个层级，默认值为非VFX类型

| `--usage`参数值 | 适用场景 | 三角形数量 | 枢轴位置 | 缩放设置 |
|-----------------|----------|------------|----------|----------|
| `asset`（默认值） | 道具、武器、角色 | 保持原样 | 保持原样 | 保持原样 |
| `vfx_standalone` | 护盾/光束/刀光弧——单个网格，无粒子效果 | 保持原样 | 重新居中（若物体从地面生长，可使用`--pivot bottom`参数） | 可选 |
| `vfx_particle` | 碎片/剑雨效果——由粒子系统实例化的网格 | 每个网格的三角形数量乘以实例数即为预算值 | 重新居中 | 归一化为1单位 |

Unity在导入时无法进行网格简化操作。如果超出`--target-tris`设定的三角形数量限制，系统会给出相应提示，并建议重新生成低多边形模型（在云端后端设置中可将`low_poly`参数设为True），这样既能降低资源开销，也能更好地保留UV信息。

## 渲染管线说明

材质信息通过glTFast的着色器传入。内置渲染管线、URP和HDRP分别需要不同的着色器变体集；在判断“材质显示异常”的问题前，需先确认目标项目使用的渲染管线。该脚本不会重写材质——对于`vfx_standalone`类型的资源，通常需要手动将材质替换为自发光/半透明/菲涅尔材质。

## 验证结果

在**Unity 6000.5.2f1**环境下，使用`com.unity.cloud.gltfast` 6.16.0版本的内置渲染管线进行批量测试：
- 无纹理GLB文件，设置`usage=asset`：生成预制体，包含12个三角形，数据可完整回传；
- **带纹理**的GLB文件（立方体模型，嵌入PNG贴图，PBR材质）：包含12个三角形、24个顶点、1种材质，无警告信息。可通过`tests/harness/stubs.py:make_textured_glb()`命令复现该测试，无需API密钥；
- `usage=vfx_particle`：枢轴被重新居中到原点，最大边界被归一化为1单位，这些数值在重新测量的边界数据中得到了验证；
- 通过`--summary`参数批量处理，重新导入时会覆盖之前的预制体。**未经验证**：URP/HDRP材质转换（目前仅支持内置渲染管线），以及FBX/OBJ路径问题。

## 手动检查结果

批量导入工具只会输出数值；只有靠人眼才能察觉“网格面朝向错误”或“纹理贴图位置不对”等问题。若要检查导入结果，请按以下步骤操作：

1. 打开Unity Hub ▸ 添加 ▸ 从磁盘添加项目 ▸ 选择项目文件夹，使用匹配的编辑器版本打开该项目（**注意**：在编辑器中打开项目时切勿运行批量导入——正在运行的编辑器会显示其自身的内容浏览器视图，导致新写入的资源显示为缺失状态）；
2. 在Project窗口中定位到`Assets/Generated/Prefabs/`目录，将预制体拖入场景；
3. 检查报告无法涵盖的三项内容：模型的轮廓、纹理是否落在正确位置，以及模型方向（glTF和Unity均采用Y轴向上的坐标系，因此若资产呈面朝下的状态，说明是源文件有问题，而非导入设置错误）；
4. 选中预制体根节点下的网格对象，对照报告中提到的`triangles`数值，查看Inspector面板中的网格信息。

首次打开新项目时，由于需要解析软件包并重建`Library/`文件夹，会花费几分钟时间。`Library/`文件夹属于可删除的临时文件——当软件包编译出现问题时，删除它即可解决问题。

### 如果Unity以退出码1结束且没有任何报告

请查看报告旁边的`.unity.log`文件。若编译错误出现在`com.unity.collections`、`com.unity.test-framework`和glTFast相关模块中，说明项目的软件包缓存解析不一致——此时只需删除`<项目目录>/Library/`文件夹后重新运行即可。此处曾出现过此类情况，重新解析软件包后问题便解决了。
