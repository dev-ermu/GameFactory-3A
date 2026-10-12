# Godot 4 安装指引

本项目**不再自动下载引擎**。Godot 由使用者自行安装，安装位置通过 `.env` 中的配置项告知本项目。这样每次使用都不会重新下载，也不会产生难以管理的安装目录。

本项目只支持 **Windows**。

## 步骤

### 1. 自行下载并安装 Godot

从 <https://godotengine.org/download/windows/> 下载 Godot 4.x（建议 `4.5.1-stable`），解压到任意目录。目录里应直接存在 `Godot.exe`。

### 2. 在 `.env` 中告知本项目

复制仓库根目录的 `.env.example` 为 `.env`，然后填写：

```bash
# .env
# Godot 可执行文件的绝对路径（指向 Godot.exe 本身，不是它所在的目录）
A3GAME_GODOT_EXECUTABLE=C:/tools/Godot/Godot.exe

# 本项目 Godot 项目的存放目录
A3GAME_GODOT_PROJECT=C:/projects/MyGame
```

路径请使用正斜杠 `/`。

若 `A3GAME_GODOT_EXECUTABLE` 留空，适配器会在两个常见位置兜底查找：`C:/Program Files/Godot/Godot.exe` 与 `%LOCALAPPDATA%/Programs/Godot/Godot.exe`。

### 3. 验证

```bat
python -m engine_adapters.godot --project "%A3GAME_GODOT_PROJECT%" validate-project
```

## AI 自动化流程

1. 确认 `.env` 中的 `A3GAME_GODOT_EXECUTABLE` 已设置，且该文件确实存在。
2. **不要**尝试下载或安装引擎——若可执行文件缺失，应向用户报错并终止，而不是自行获取。
3. 设置 `A3GAME_GODOT_PROJECT`，随后使用适配器命令行工具创建/验证项目、导入资源、运行测试并启动项目。

```bat
python -m engine_adapters.godot --project "%A3GAME_GODOT_PROJECT%" create-project --name MyGame
python -m engine_adapters.godot --project "%A3GAME_GODOT_PROJECT%" import-asset --source-json generated-asset.json --asset-type prop
python -m engine_adapters.godot --project "%A3GAME_GODOT_PROJECT%" launch-game
```

## 常见配置项

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `A3GAME_GODOT_EXECUTABLE` | Godot 可执行文件绝对路径 | 留空则查找常见安装位置 |
| `A3GAME_GODOT_PROJECT` | 本项目 Godot 项目目录 | 必填 |
| `A3GAME_GODOT_RUNTIME_HOST` | 运行时服务地址 | `127.0.0.1` |
| `A3GAME_GODOT_RUNTIME_PORT` | 运行时服务端口 | `30050` |
| `A3GAME_GODOT_EDITOR_TIMEOUT` | 编辑器命令超时（秒） | `300` |
| `A3GAME_GODOT_IMPORT_TIMEOUT` | 导入命令超时（秒） | `300` |