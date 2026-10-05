# three_js/import_generated/

这是将`models/`目录生成的文件转换为three.js运行时可识别格式的桥梁。

## 为何它比UE5中的对应模块更精简

虚幻引擎必须先对源网格进行*导入*操作：运行Interchange工具，构建`StaticMesh`/`SkeletalMesh`类型的uasset文件，生成碰撞数据，再进行编译。而网页端无需导入步骤——`.glb`文件本身就是运行时格式。将其部署到指定位置只需简单的文件复制操作，适配器已在`assets/_internal/service.py`中完成了这一步骤。

网页端仍需确认文件能够正常加载，同时需要获取与流水线记录一致的三角形数量、材质数量、动画数量及边界信息。这正是`import_mesh.mjs`所实现的功能，它使用的是游戏运行时将采用的同一套`GLTFLoader`。

| 路径 | 运行环境 |
| --- | --- |
| `import_mesh.mjs` | 宿主Node环境，需安装项目所需的`three`库 |
| `engine_adapters/three_js/assets/_internal/inspectors.py` | 宿主Python环境，无需Node支持 |
| `scripts/import_generated_asset.py` | 宿主Python环境——用于定位工具链、启动导入程序并读取其JSON报告 |

我们特意设计了两种检查器：Python版可直接解析glTF容器，因此无需依赖Node进程即可完成验证；Node版则用于证明真正的加载器能正常处理该文件。验证环节使用前者，发布证据生成则采用后者。

## 使用方法

```bash
node engine_adapters/three_js/import_generated/import_mesh.mjs \
    --source test_data/outputs/<game>/<run>/3d_object/<task>/mesh.glb \
    --usage asset \
    --report .a3game/reports/import-mesh.json
```

使用层级与其他引擎保持一致——包括`asset`、`vfx_standalone`、`vfx_particle`等，每种层级都对应特定的三角形数量、纹理数量及字节数限制。超出三角形数量限制会导致导入失败；超出纹理或字节数限制则会触发警告。

## 报告格式

```json
{
  "ok": true,
  "operation": "import_generated.import_mesh",
  "errors": [],
  "warnings": [],
  "payload": {
    "source": "...", "asset_name": "mesh", "usage": "asset",
    "bytes": 1048576, "meshes": 3, "skinnedMeshes": 1,
    "triangles": 41280, "materialCount": 2, "textureCount": 5,
    "animationCount": 4, "animations": ["idle", "walk", "run", "attack"],
    "bounds": { "min": [], "max": [], "size": [], "center": [] }
  }
}
```

## 前置条件

- Node 20或更高版本；
- 项目中已安装`three`库——需先调用`ThreeClient.project.install_dependencies()`；
- 对于Draco压缩的文件，还需通过`--draco-decoder <dir>`参数指定解码器目录，该目录在运行时会通过`/draco/`路径被访问。

## 不属于此处的功能

请勿在此处执行文件部署、编写资产清单或注册脚本生成的产物。这些功能由公共的`ThreeClient.assets.*`命名空间负责管理，以确保注册表始终作为唯一可信数据源。
