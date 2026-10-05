# Godot 4自动化安装

该目录是AI代理应使用的非交互式入口点。请勿直接开始项目创建或资源导入：首先需发现/复用或安装引擎，验证对应的二进制文件，并读取生成的配置文件。

默认版本锁定为Godot `4.5.1-stable`；不会通过“最新版”查询悄悄更改运行版本。

## 一键安装命令

Linux或macOS系统：

```bash
scripts/engine_install/godot/install.sh --json > godot-install-result.json
```

Windows命令提示符下：

```bat
scripts\engine_install\godot\install.cmd --json > godot-install-result.json
```

该安装程序仅使用Python标准库，要求Python 3.14或更高版本。仓库中的Godot测试在Python 3.14环境下执行，以此作为兼容性校验标准。

成功的JSON结果会包含`ok=true`、操作类型、精确的版本与平台信息、官方下载链接、SHA-512校验值、已验证的可执行文件路径、PATH路径替换配置以及配置文件路径。任何非零退出码或`ok=false`均视为严重故障。

## AI自动化流程

1. 运行`install.sh --dry-run --json`（或`install.cmd`）并记录解析出的发布资源、目标架构、官方下载链接及路径信息。
2. 不带`--dry-run`参数运行安装程序。它会先验证显式指定的`--executable`参数、配置的`A3GAME_GODOT_*`可执行文件，或是PATH中的`godot4`/`godot`。若已有匹配的构建版本则直接复用；不符合锁定版本的构建将不被采纳。
3. 解析JSON数据，需确保`ok=true`且`verified_version`与请求的精确版本一致。切勿仅凭下载的压缩包就判定安装成功。
4. 在POSIX系统中加载生成的环境变量文件`.env`，或在Windows中调用生成的`.cmd`脚本；也可直接将返回的可执行文件路径赋值给`A3GAME_GODOT_EXECUTABLE`。
5. 设置`A3GAME_GODOT_PROJECT`变量，随后使用适配器命令行工具创建/验证项目、导入资源、运行测试并启动项目。

以下是路径独立且便于审查的示例：

```bash
scripts/engine_install/godot/install.sh \
  --version 4.5.1 \
  --install-root "$PWD/.tools/godot" \
  --cache-dir "$PWD/.cache/godot" \
  --bin-dir "$PWD/.tools/bin" \
  --config-dir "$PWD/.tools/config" \
  --json
export A3GAME_GODOT_EXECUTABLE="$PWD/.tools/bin/godot4"
export A3GAME_GODOT_PROJECT=/projects/MyGame
python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" \
  create-project --name MyGame
python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" \
  validate-project
```

## 安装程序保障| 需求 | 行为 |
| --- | --- |
| 非交互式 | 不弹出提示、不调用图形用户界面、不启用包管理器、无需获取管理员权限，也不修改 shell 配置文件 |
| 版本选择 | 仅支持精确的稳定版 `4.x[.y]`；默认版本为 `4.5.1`；若指定 `latest`、预发布版本或非 4 系列版本则会安装失败 |
| 架构支持 | Linux x86-64/x86-32/arm64/arm32；macOS 支持英特尔芯片及苹果硅芯片的通用版本；Windows 支持 x64/x86/arm64 |
| 下载源 | 从官方发布资源地址 `https://github.com/godotengine/godot/releases/download/<version>-stable/` 下载 |
| 完整性校验 | 会下载官方的 `SHA512-SUMS.txt` 文件，要求存档的哈希值能与文件中某一条记录完全匹配；若文件不存在或哈希值不匹配则安装会终止 |
| 解压处理 | 解压前会拒绝绝对路径、包含上级目录路径、重复路径、符号链接以及特殊节点 |
| 原子性操作 | 先解压到临时的同级暂存目录中并进行验证，验证通过后通过重命名完成部署；若替换过程失败，会恢复之前保留的目标文件 |
| 复用机制 | 只有当已安装的实例在架构、版本、资源及可执行文件清单上均匹配，且执行 `godot --headless --version` 命令能正常返回结果时，才会复用该实例 |
| 现有二进制文件 | 会按以下顺序查找：命令行参数 `--executable`、环境变量，最后是 PATH 路径；且仅会使用指定版本的二进制文件 |
| PATH/配置处理 | 会创建一个用户可写的 `godot4` 占位文件，同时生成对应的 JSON 配置文件以及 `.env`/`.cmd` 脚本；绝不会修改登录配置文件 |
| 安装后校验 | 会运行已安装的二进制文件，确保实际运行的 Godot 版本与请求的版本完全一致 |

使用 `--force` 参数时，仅会替换已明确指定的版本及平台对应的安装目标和 PATH 占位文件，不会影响其他版本的安装；指定 `--version 4.6.0` 时会与 `4.5.1` 版本并行安装，这就是升级路径。多次运行相同命令属于幂等操作，会返回 `action=reused-managed` 的结果。

如果调用方仅需使用绝对路径的可执行文件，可使用 `--no-path-shim` 参数；若要在不进行网络请求或文件系统写入的情况下查看解析结果，可使用 `--dry-run --json` 参数。运行 `install.py --help` 可查看所有路径及超时相关选项。

## 通过适配器继续使用
该目录特意仅包含跨平台安装程序。项目和游戏相关的操作由 `engine_adapters.godot` 模块负责；将这些功能封装在同一个命令行接口后，无需让代理程序为每项操作单独查找并读取对应的 shell 或批处理脚本。

安装完成后，可在 Linux、macOS 或 Windows 系统上直接通过适配器操作：

```bash
export A3GAME_GODOT_EXECUTABLE=/absolute/path/to/godot4
export A3GAME_GODOT_PROJECT=/projects/MyGame

python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" \
  create-project --name MyGame
python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" \
  install-framework
python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" \
  import-asset --source-json generated-asset.json --asset-type prop
python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" launch-game
```在Windows系统中，需将`python3`替换为`python`或`%A3GAME_PYTHON%`。传递给`--source-json`的JSON文件是一个包含`game_id`、`run_id`、`task_kind`、`task_id`以及可选的`artifact_key`字段的仓库任务标识信息；它并非任意的主机路径。若需兼容旧版直接文件导入流程，需显式调用`scripts/import_generated_asset.py --engine godot`。

构建过程需要`export_presets.cfg`文件中存在属于项目自身的预设配置：

```bash
python3 -m engine_adapters.godot --project "$A3GAME_GODOT_PROJECT" build \
  --preset "Linux/X11" --output builds/game.x86_64
```

首次进行适配器管理的导出操作时需使用新的输出文件。后续若要替换输出文件，仅当已签名的所有权清单与现有输出内容仍匹配时才允许；一旦输出文件被篡改、脱离管理范围、存在链接路径，或是涉及受保护的项目输入内容，在提交前就会触发报错。
