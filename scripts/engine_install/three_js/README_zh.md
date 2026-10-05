# three.js 脚本

这些启动器只是对公开的 `ThreeClient(api_version="v1")` API的简单封装。

Python实现位于 `engine_adapters/three_js/cli.py` 文件中：

```text
scripts/three_js/*.sh 或 *.cmd -> engine_adapters.three_js.cli -> ThreeClient
```

## 工具链

与Unreal不同，three.js适配器无需安装引擎。它唯一的外部依赖是 `PATH` 环境变量中已安装的 **Node 20+** 工具链，因为该适配器会通过私有的Node传输机制来调用 `vite`、`vitest` 以及包管理器。

`setup_env.sh` 脚本会将该工具链配置为一个Conda环境，因此即便机器上没有系统级的Node也能正常运行：

```bash
scripts/three_js/setup_env.sh                # 创建或验证该环境
scripts/three_js/setup_env.sh --force        # 从头重新创建环境
scripts/three_js/setup_env.sh --print-activate # 仅显示激活环境的两条命令
```

在使用其他脚本之前，需先在任意Shell中激活该环境：

```bash
source <conda_root>/etc/profile.d/conda.sh
conda activate threejs
```

| 变量 | 含义 | 默认值 |
|---|---|---|
| `A3GAME_CONDA_ROOT` | Conda的安装路径前缀 | 先尝试 `$CONDA_EXE` 的路径前缀，然后是 `~/miniconda3`、`~/anaconda3`、`/opt/conda` |
| `A3GAME_THREE_CONDA_ENV` | 环境名称 | `threejs` |
| `A3GAME_NODE_VERSION` | 传递给Conda的Node版本规格 | `20.*` |
| `A3GAME_PYTHON` | 用于导入适配器的解释器 | `python3` |

经过验证的基础版本为：three.js r185（`three@0.185.0`）、Node 20、Vite 6。

## 创建项目

`create-project` 脚本会搭建一个基于Vite和three.js的宿主项目，将适配器自带的 `A3GamePlayable` 框架作为 `@a3game/playable` 安装，并运行包管理器。但该脚本不会安装任何游戏玩法相关内容。

```bash
scripts/three_js/create_project.sh \
  --project-path /path/to/GeneratedGame \
  --dev-port 5173

# 仅搭建项目结构，不执行npm安装，也不复制框架文件
scripts/three_js/create_project.sh \
  --project-path /path/to/GeneratedGame \
  --skip-install --skip-framework
```

## 导入资产

资产导入功能接受的是仓库中的任务标识，而非任意源路径。它会将文件暂存于 `public/` 目录下，记录相关 artifact，同时重写 `public/assets/manifest.json` 文件。

```bash
scripts/three_js/import_asset.sh \
  --project /path/to/GeneratedGame/package.json \
  --game-id gameA_cyberpunk_shooter \
  --task-id cyberpunk_sword_001 \
  --type prop \
  --artifact-key glb_path
```

若指定 `--type scene`，则会调用 `three.world.build`，将运行时场景图发布到 `public/assets/worlds/` 目录下，而非仅暂存网格数据。

## 资产的来源

这并非启动器：内容获取属于运营人员的工作范畴，因此相关逻辑位于 `operators/gen_3d_object/funcs/` 目录下，由Python代码调用。

```python
# Three平台的CC0授权模型，适用于对画质要求不高、无需GPU加速的场景——当生成过程过于复杂时可使用此方式。
from operators.gen_3d_object.funcs import fetch_asset_pack
fetch_asset_pack(games=["game_archer_explorer"])
```# 某款游戏实际所需的参数
从 `models/gen_3d_object/trellis_2_model.py` 导入 `Trellis2Model`，从 `operators/gen_3d_object/operator.py` 导入 `Gen3DObjectOperator`：
```python
op = Gen3DObjectOperator(model=Trellis2Model(model_path="…/TRELLIS.2-4B"))
op.run_art_plan("game_archer_explorer", image_model=…)
```
两者的输出结果完全一致：均为资产任务输出、用于声明朝向轴和高度（单位：米）的公共 `ThreeClient.assets` 导入项，以及一份审核表。二者都不会把文件复制到 `public/` 目录下。

如果下载过程需要代理，请设置 `https_proxy`。

## 启动开发服务器
```bash
scripts/three_js/run.sh --project /path/to/GeneratedGame/package.json
scripts/three_js/run.sh --project /path/to/GeneratedGame/package.json --wait-only
```
默认情况下服务器会绑定 `127.0.0.1`，因此机器外部无法访问。若要游玩托管在远程开发服务器上的游戏：
```bash
scripts/three_js/run.sh --project /path/to/package.json --dev-host 0.0.0.0
```
之后要么转发端口——执行 `ssh -N -L 5173:127.0.0.1:5173 <user>@<server>` 后再打开 `http://127.0.0.1:5173/`；要么在端口可访问的情况下直接打开 `http://<server_ip>:5173/`。WebGL内容会在浏览器的查看器中渲染，因此服务器无需配备GPU或显示器。

这些脚本不会启动平台网关和浏览器服务。

## 使用边界
这些启动器仅调用公共命名空间。它们绝不会触碰 `engine_adapters.three_js._internal`，绝不会对项目执行原生的 `npm` 命令，也绝不会向生成项目的 `packages/` 目录写入内容——这部分工作由 `three.plugin.install` 负责。
