# 3AGameFactory

**3AGameFactory让Coding Agent根据游戏需求生成可用于游戏构建的资产与引擎代码。**

全面开源，包含游戏生成Skill与资产框架。**它覆盖图片、3D 资产、动作、音频与 CG 视频生成**，并支持使用UE5、Blender、Unity、Godot 4 和 three.js构建游戏。

本项目原地址：<https://github.com/OpenDCAI/GameFactory-3A>

---

## 一、游戏演示

原项目连接有使用AI生成的游戏演示，可参考原链接。

## 二、快速开始

3AGameFactory由Coding Agent驱动，它读取本项目的Skills并调用相应Pipeline，例如：

* [Codex](https://github.com/openai/codex)
* [Claude Code](https://github.com/anthropics/claude-code) 
* [Gemini CLI](https://github.com/google-gemini/gemini-cli)

给出的3个例子都是终端形式。

### 2.1 使用方法

1. 打开Coding Agent，例如Codex、Claude Code或其它兼容Agent。
2. cd GameFactory-3A
3. 告诉Agent你的游戏需求，并要求它先阅读agent_skills/setting_overview.md。

### 2.2 <strong><span style="color: #d1242f;">重要提示</span></strong>

`agent_skills/setting_overview.md`是使用3AGameFactory生成资产、玩法、UI和特定引擎游戏时的入口文档。它会将Agent路由到对应的资产Skill和引擎API上下文。

### 2.3 配置项

我们所有的配置项都在`.env`文件中进行配置，也可以通过环境变量。由于配置项过多，通过`.env`文件配置更加方便管理。

#### 云端环境

将原项目进行了改造，原项目会优先考虑在本地运行大模型服务，然后调用。但是大部分人的机器是没有GPU，20G显存的，所以我们考虑将原项目本地运行大模型的逻辑全部删除。调用服务商的大模型服务。

**API根地址，API key是必填项，自行找到对应服务商进行申请**。

---

## 三、3AGameFactory能做什么？

| 能力 | 产物 | 主要 Pipeline 位置 |
|---|---|---|
| 图片与 T-pose 预处理 | 源图像、角色可用输入 | `pipeline/assets_gen/gen_tpose_image/` |
| 3D物体生成 | 道具、角色、武器与可复用网格 | `pipeline/assets_gen/gen_3d_object/` |
| 3D场景生成 | 重建的室内场景或组合式环境 | `pipeline/assets_gen/gen_3d_scene/` |
| 动作生成 | 骨骼、生成动作、重定向动画片段 | `pipeline/assets_gen/gen_motion/` |
| 音频生成 | 对话、音效、环境声与 WAV 资产 | `pipeline/assets_gen/gen_audio/` |
| CG视频生成 | 文本、首帧、首尾帧、参考图驱动的 MP4 | `pipeline/assets_gen/gen_cg_video/` |
| 玩法生成 | 引擎原生的机制与运行时行为 | `pipeline/code_gen/gen_mechanic/` |
| UI 生成 | HUD、菜单、界面与交互流程 | `pipeline/code_gen/gen_ui/` |
| 完整游戏切片 | 资产、玩法、UI 与评测的协同结果 | 由 Agent 依据 `agent_skills/setting_overview.md` 编排 |

### 3.1 支持的游戏构建引擎

| 引擎 | Agent 上下文 | 参考实现 |
|---|---|---|
| UE5 | `agent_skills/engine_context/ue5_api.md` | `engine_adapters/ue5/` |
| Blender | `agent_skills/engine_context/blender_api.md` | `engine_adapters/blender/` |
| Unity | `agent_skills/engine_context/unity3d_api.md` | `engine_adapters/unity3d/` |
| Godot 4 | `agent_skills/engine_context/godot_api.md` | `engine_adapters/godot/` |
| three.js | `agent_skills/engine_context/three_js_api.md` | `engine_adapters/three_js/` |

---

## 四、项目结构

```text
GameFactory-3A/
├── agent_skills/               # 供 Agent 阅读的工作流、QA Skill 与引擎 API 上下文
│   ├── setting_overview.md     # 游戏生成 Agent 从这里开始
│   ├── asset_qa/               # 资产生成与视觉 QA Skill
│   ├── code_gen/               # 将已验收资产整合为玩法和 UI 的 Skill
│   ├── develop_harness/        # models → operators → pipeline 的贡献者契约
│   └── engine_context/         # UE5、Blender、Unity、Godot、three.js 与浏览器 API 上下文
├── engine_adapters/            # 引擎参考代码与公开 Adapter API
├── models/                     # 本地模型与云模型封装
├── operators/                  # 组合已加载模型的任务逻辑
├── pipeline/                   # 生成与评测入口
│   ├── assets_gen/             # 图片、3D、场景、动作、音频与 CG 视频任务
│   ├── code_gen/               # 玩法（gen_mechanic）与 UI（gen_ui）代码生成
│   └── common/                 # 共享辅助模块；paths.py 是所有输入输出路径的唯一来源
├── scripts/                    # 环境配置、引擎启动器与导入工具
│   ├── asset_env_setup/        # 按资产任务组织的环境配置，含 gen_motion 运行时与权重安装
│   └── engine_install/         # UE5、Blender、Unity、Godot、three.js 的安装与启动脚本
├── test/                       # 用于验证流程实际可运行的契约、集成与 smoke 脚本
├── test_data/                  # 示例需求；生成的游戏结果位于 outputs/
└── third_party/                # 检出的外部仓库，例如 trimesh 与引擎材质/资产库
```

生成产物位于`test_data/outputs/`，并按照游戏、运行、任务类别和任务 ID
组织。Agent 与贡献者应使用 `pipeline/common/paths.py`，不要手工拼接输出路径。

---

## 许可证

3AGameFactory 基于 [Apache License 2.0](LICENSE) 开源。

第三方引擎、模型、权重以及从外部素材库获取的资产均遵循各自的许可证。
在将生成内容用于正式产品前，请先确认对应提供方的授权条款。
