# UI生成任务

游戏UI生成技能：

```text
{{UI_GENERATION_SKILL_PATH}}
```

已准备的任务包：

```text
{{TASK_PACKET_PATH}}
```

工作区：

```text
{{WORKSPACE}}
```

项目与模块：

```text
project={{PROJECT_NAME}}
mechanic={{GAMEPLAY_MODULE_NAME}}
ui={{UI_MODULE_NAME}}
```

官方引擎：

```text
{{ENGINE}}
```

有序交付计划：

```json
{{DELIVERY_PLAN}}
```

现有的引擎上下文目录：

```text
{{ENGINE_CONTEXT_ROOT}}
```

机制实现参考根路径：

```json
{{MECHANIC_EXAMPLE_ROOTS}}
```

任务建议的机制参考路径（若存在）：

```json
{{MECHANIC_EXAMPLE_PATHS}}
```

原生UI实现参考根路径：

```text
{{UI_EXAMPLE_ROOTS}}
```

任务建议的原生UI参考路径（若存在）：

```json
{{UI_EXAMPLE_PATHS}}
```

所需的浏览器运行示例：

```json
{{BROWSER_PLAY_EXAMPLE_PATHS}}
```

允许的工程参考用途：

```json
{{EXAMPLE_REFERENCE_PURPOSES}}
```

浏览器运行的任务交接说明：

```json
{{BROWSER_PLAY_HANDOFF}}
```

任务详情：

```json
{{TASK_JSON}}
```

通用要求：

```text
{{GENERAL_REQUIREMENT}}
```

设计文档：

```text
{{DESIGN_DOCUMENT}}
```

UI需求：

```text
{{REQUIREMENT}}
```

验收标准：

```json
{{ACCEPTANCE_CRITERIA}}
```

最终确定的机制产物与契约：

```text
artifact={{MECHANIC_ARTIFACT_PATH}}
contract={{MECHANIC_CONTRACT_PATH}}
```

```json
{{MECHANIC_CONTRACT_JSON}}
```

机制的公共路径与运行时适配器：

```json
{{MECHANIC_PUBLIC_PATHS}}
```

```json
{{MECHANIC_RUNTIME_ADAPTER}}
```

已解析的原生绑定：

```json
{{RESOLVED_BINDINGS}}
```

屏幕、约束条件、视口以及禁止出现的UI元素：

```json
{{SCREENS}}
```

```json
{{VIEW_CONSTRAINTS}}
```

```json
{{VIEWPORTS}}
```

```json
{{FORBIDDEN_UI}}
```

参考图片：

```json
{{REFERENCE_IMAGE_PATHS}}
```

所需的上下文使用清单：

```text
{{CONTEXT_USED_PATH}}
```

首先生成`engine_native`，随后根据交接信息中的浏览器服务API和仓库前端参考，在`generated_ui/browser_play/`目录下生成`browser_play`。请查看对应的浏览器运行示例，了解完整的创建或恢复会话流程，以及引擎中立的`stream_url`交接方式。机制和原生UI示例仅作为代码参考，不会限制所生成游戏的类型、呈现形式或交互设计。仅在原生阶段使用声明的机制绑定，切勿生成后端源代码。浏览器运行版本必须包含带版本的`browser_play_manifest.json`，以及一个用于调用公共浏览器服务入口点的轻量启动脚本。按照任务包定义生成原生/Web UI源代码、测试用例、清单文件、测试用数据、截图方案以及溯源信息。切勿扫描整个示例项目目录。应挑选用于学习插件/模块边界、构建配置、公开绑定模式、引擎原生UI代码以及浏览器交互逻辑所需的最小规模的结构化参考文件集。这些文件可能源自完全不同的游戏类型——射击类游戏的示例或许能为MOBA、策略游戏、模拟类游戏或创新型游戏提供正确的模块与控件架构参考。

切勿将此类示例用作基础插件、继承目标、视觉模板、玩法模板、复制用的脚手架代码或运行时依赖项。最终生成的UI应由当前任务需求与设计输入决定，仅记录实际查阅的文件路径即可。

每条`examples_used`条目都必须包含从上述允许的工程参考用途中选取的、非空的目的列表。

无需寻找类型、机制、HUD、摄像机或视觉风格相匹配的示例，只要挑选能讲解工程结构与API用法的同引擎参考内容即可。即便没有类似的示例，也绝非输入缺失或阻碍因素；可根据任务要求生成所需的原生UI及浏览器播放体验。
