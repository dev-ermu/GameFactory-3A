# UE5适配器迁移清单

状态：UEClient v1版本、引擎原生自动化测试执行、AAAGamePlayable运行时框架、UE脚本仓库、预览工具、参考游戏玩法插件提取、已实现的API文档以及引擎中立的Mechanic Agent协议均已完成。Stub类型的非交互式Codex后端、引擎中立的Mechanic Operator以及仅用于生成的Pipeline runner也已实现。一个真实的Codex FPS项目已经成功编译出Editor/游戏目标版本，通过了自动生成的自动化测试，并通过单独执行的UEClient验证，成功加载了导入的资源。由于引擎执行不属于Agent编排范畴，早期的自动导入功能已被从`GenMechanicOperator`中移除。符合规范的现有制品评估器、UE执行迁移、受限修复协调器、实时追踪/证据捕获以及平台服务等功能仍待实现。

源代码仓库：

```text
D:\Desktop\game\OpenWL_Avatar
```

目标仓库：

```text
D:\Desktop\game\3AGameFactory
```

本清单旨在将现有的OpenWL Unreal相关代码及服务代码迁移至3AGameFactory架构中。在此过程中，现有的A/B/C分层结构、`design_doc.txt`文件、`pipeline_task.jsonl`文件以及输出布局均不会改变。

## 实施进度

2026年8月2日已完成的内容：- 确定`from engine_adapters.ue5 import UEClient`为唯一的公共Python入口点，并采用带版本号的结果契约；
- 将配置以及远程控制/Python执行传输功能迁移到私有模块中；
- 迁移资产导入、验证、注册表管理、PBR、特效、高斯泼溅、PLY格式处理、生成的场景以及世界草稿/打包逻辑；
- 将公共资产解析方式更改为基于仓库任务标识`(game_id, run_id, task_kind, task_id, artifact_key)`；
- 规定`pipeline.common.paths`以及每个任务的`meta.json`是任务描述符指向资产文件或插件目录的唯一路径；
- 新增所有v1命名空间：`project`、`assets`、`animation`、`bindings`、`world`、`reflection`、`plugin`、`build`、`runtime`和`observe`；
- 迁移通用参与者、控制器、实体、绑定以及标准化输入会话状态相关逻辑，移除Fighter/FPS/Racing类的命令字段；
- 将运行时UDP桥接功能迁移至`runtime/_internal/bridge/`目录下，并将其与`UEClient.runtime.sessions`关联起来；
- 从迁移后的UE适配器中移除`serving.*`、`serving.paths`以及平台服务相关的导入项；
- 将`OpenWLPlayable`重构为`AAAGamePlayable`，其中仅包含公共接口、数据类型、组件以及世界/运行时子系统；
- 新增原子化的`sync_session`运行时命令，确保参与者、控制器、实体和绑定状态能够同步建立；
- 新增采用生成式风格的Gameplay Plugin测试套件，该套件会注册自身的实体工厂并实现自定义的Pawn类；
- 移植了针对特定资产、特效、PBR、高斯泼溅、PLY格式、世界、插件、构建、运行时、反射以及公共契约的测试；
- 使用UE 5.4版本编译该框架及测试套件，同时针对编辑器目标和游戏目标进行测试；验证结果表明无头游戏世界能够接收UDP格式的`sync_session`指令，并能成功生成/绑定相应实体；
- 将`project.create()`的功能调整为生成最小的C++宿主模块，同时包含游戏和编辑器目标，但不包含具体的游戏玩法默认设置；
- 迁移`create_project`、`import_asset`和`run`等命令行接口的行为；最终的仓库封装代码位于`scripts/ue`目录下，且仅调用`engine_adapters/ue5/cli.py`中的公共UEClient实现；
- 将导入启动器从任意源路径改为基于仓库任务描述符进行工作；
- 将运行启动器的功能限定为仅负责启动Unreal引擎；网关/浏览器服务相关功能不再混入UE脚本中；
- 当生成的插件声明依赖`AAAGamePlayable`时，`plugin.install()`会自动同步并启用该组件；
- 验证结果表明，新创建的脚本化项目能够成功安装框架及生成的测试套件，运行UHT工具，并使用UE 5.4编译两个插件模块。

完成于2026年8月3日：- 将公共的Windows/Linux封装器移至仓库级别的`scripts/ue`目录；
- 将Python命令行接口实现保留在`engine_adapters/ue5/cli.py`中，由封装器调用该接口，而命令行接口仅导入公共的`UEClient`；
- 把预览角色、控制器以及GameMode行为提取到可选的、由适配器管理的`AAAGamePreview`插件中；
- 将具体的Arena Fighter、FPS以及赛车类角色/Pawn、控制器、GameMode、HUD、标准化输入处理逻辑，还有实体工厂注册功能，提取到`engine_adapters/ue5/examples`下的独立可选插件中；
- 新增静态依赖测试，防止`AAAGamePlayable`依赖于预览/示例插件，同时避免示例插件引用框架的私有头文件；
- 使用UE 5.4版本为编辑器和游戏目标编译预览插件及这三个参考插件。
- 新增`engine_adapters/ue5/testing/`目录，并公开`ue.testing.run_automation_tests()`函数；
- 自动化测试成功的条件需同时满足：进程状态正常，且能解析出全新的`index.json`报告，报告中至少有一条匹配的测试用例且所有测试均通过；
- 即便测试/进程失败，也会保留最新的自动化测试报告，同时返回命令输出、诊断信息、超时状态以及结构化的测试数量数据；
- 新增针对配置缺失、模拟运行、测试成功、警告、测试失败、报告为空/不一致/无效/过期、进程失败以及超时等场景的专项测试；
- 在`ue5_api.md`中记录了Agent/Operator/Evaluator的执行权限边界及其契约测试相关内容；
- 通过公共API，使用UE 5.4版本编译并执行了生成式`AAAGame.GeneratedGameplay.Smoke`测试。
- 新增与引擎无关的`game_generation.md`技能描述，以及`system.md`、`task.md`和`repair.md`提示词模板；
- 将具体的引擎调用方式改为通过只读路径精确引用选定的单个API文件，而非在提示词中嵌入完整的API内容；
- 新增由Operator提供的通用项目和游戏所属模块标识符；
- 新增可序列化为JSON的Mechanic Agent请求/结果契约，明确了工作区/只读边界以及明确的测试/基准测试权限；
- 新增CPU安全的`StubAgent`，仅实现`model.run(request)`功能；
- 分别记录创建的、修改的和删除的Agent文件；
- 新增16项针对跨引擎提示词、请求/结果、沙盒环境、修复机制、鸭子类型以及Stub契约的专项测试。
- 实现了`GenMechanicOperator(model, output_dir, run_id, default_game_id)`、`run()`和`run_batch()`函数；
- 实现了任务/需求加载、稳定的项目/模块命名、提示词渲染、对`model.run(request)`的验证、Agent文件所有权检查、转录/结果持久化、工件检查以及失败的`meta.json`处理功能；
- 将`AAAGamePlayable`与规范化的生成插件源码同步到Stub生成的UE项目中；
- 实现了`pipeline/mechanic/run.py`，其中包含`load_model`、`make_operator`、`generate`、`run_from_jsonl`和`main`函数；
- 新增7项Operator/运行器测试，使Mechanic相关的专项测试总数达到23项。- 将真实的 `fps_core_001` JSONL 文件通过 Stub 后端在 `fps_baseline_v1` 环境下运行，生成标准的项目/插件/演示/元数据布局。

2026年8月4日完成的内容：
- 实现了 `CodexAgent`，支持非交互式的 `codex exec` 命令、工作区写入沙箱机制、超时处理、JSON 事件记录、使用情况统计，以及生成/修改/删除文件的快照功能；
- 在不更改鸭子类型接口 `model.run(request)` 或 Operator 构造函数契约的前提下，接入了 `--backend codex` 参数；
- 在 `fps_skill_validation_v1` 目录下生成了 `AAAGameCyberPrisonFPS` 游戏以及独立的 `CyberPrisonFPS` 游戏玩法插件；
- 通过公共的 UEClient 操作，从 `fps_baseline_v1` 导入废弃监狱场景、玩家/敌人角色模型、步枪以及七种特定角色的动作数据；
- 使用 UE 5.4 成功编译了 `AAAGameCyberPrisonFPS` 和 `AAAGameCyberPrisonFPSEditor`；
- 执行 `AAAGame.CyberPrisonFPS.*` 测试：共发现3个测试用例，全部通过，无失败用例；
- 启动监狱地图并保留了相关日志，证明玩家模型、步枪能够正常加载，右手部位可正确附着武器，同时生成了三个敌人角色，触发了追击/攻击状态，且玩家受到伤害的逻辑也正常运行；
- 为 `GenMechanicOperator` 添加了自动导入A层的功能：包括编辑器准备工作、编辑器生命周期管控、原生场景导入、角色/武器导入、骨骼-角色动作导入、单项导入结果记录以及导入清单生成；
- 通过 `AAAGAME_UE_ROOT` 参数支持了运行器 `--ue-root` 选项；
- 新增了针对自动导入功能的 Operator 专项测试；目前该专项的 Mechanic Agent/Operator 套件包含25个通过的测试用例。

2026年8月4日完成的架构修正内容：
- 替换了自动导入 Operator 的部署方式，同时保留了现有的 UEClient 实现及验证依据；
- 从 `GenMechanicOperator` 中移除了所有引擎适配器导入、UE 项目/插件同步、描述符导入、编辑器生命周期管理以及执行元数据相关功能；
- 将 Operator 的功能简化为技能/提示词/上下文组装、调用 `model.run(request)` 进行生成/修复、工作区变更验证以及 Agent 证据记录；
- 移除了生成过程中的项目/插件/启动完整性检查逻辑；
- 将 `pipeline/mechanic/run.py` 恢复为 Pipeline README中描述的仅用于生成的五函数API，同时移除了 `--ue-root` 参数；
- 将引擎 API 参考路径明确设为任务/命令行输入项；
- 预留 `pipeline/mechanic/eval.py` 用于现有产物的评估；
- 所有31个Mechanic Agent/Operator/运行器测试用例均通过，且确认 `operators/gen_mechanic` 目录下已不存在 `engine_adapters` 或 `UEClient` 的相关引用。

尚未完成的事项：- 通过`pipeline.common.paths`实现`pipeline/mechanic/eval.py`；
- 将描述符导入、项目准备、权威构建、生成的测试以及运行时证据迁移到UE评估/执行流程中；
- 将受限的构建/测试修复逻辑独立出来，既不放入用于生成的`run.py`，也不放入用于评估的`eval.py`中；
- 回放完整的实时确定性FPS轨迹，并捕获有效的游戏窗口截图；
- 通过符合架构规范的协调器复现完整的Codex/导入/构建/测试/运行时流程，同时从Pipeline/评估器证据中更新元数据；
- 定义任务专属的状态、输入、事件、观测以及UI绑定模式；
- 在该机制契约稳定之后才实施UI生成工作；
- 将平台服务迁移至`engine_adapters/z_other_serving`。

## 当前框架验证阶段

当前已实现的生成里程碑如下：

```text
test_samples
    |
    v
GenMechanicOperator
    |
    v
CodexAgent
    |
    v
持久化的机制源工件
```

这证明了真实的Agent执行能力以及持久化的工作区变更报告功能，且不会将该操作符局限于某一特定引擎。单独保留的验证工件则证明了UE导入、构建、生成的测试以及运行时启动功能正常。不过它尚未证明存在符合架构规范的闭环流程：

```text
生成 + 现有工件评估 + 修复协调
    + 实时轨迹 + 截图 = 可复现的可玩游戏
```

实施优先级确定如下：

```text
P0  真实机制闭环
    真实Agent → 评估器的导入/构建/测试环节 → 修复协调器
    → 实时轨迹/证据 → 可玩的fps_core_001

P1  机制契约稳定化
    任务定义的状态/输入/事件/观测/UI模式

P2  UI Agent
    GenUIOperator → 平视显示器/HUD/菜单/结束状态 → 截图与元数据

P3  完整游戏流水线
    图层A资源 → 机制模块 → UI → 打包/评估
```

P0阶段的验收标准是：能够启动UE游戏，玩家可进入地图、移动、攻击、影响并击败敌人，达到胜利/失败状态，且能通过评估器执行的自动化测试，同时保留构建、测试、轨迹及运行时证据。

绝不能仅仅因为存在`fps_hud_001`就启动UI相关工作。P1阶段必须首先验证并固定UI所需的面向机制的字段，包括基础状态集：

```text
game_state
player_health
magazine_ammo
reserve_ammo
enemies_remaining
is_reloading
objective_text
```

UI必须遵循稳定的绑定契约，而非直接绑定到生成的机制所使用的具体角色类、武器组件、物品实现或Gameplay Ability类。

## 验证快照

截至2026年8月4日已完成的内容：- 执行命令 `python -m unittest discover -s tests -p 'test_ue5_*.py' -v` 后，所有 86 项测试均通过；
- 扫描结果显示，`engine_adapters/ue5` 目录下不存在对 `serving.*` 或 `z_other_serving` 的引用；
- 扫描结果显示，在 `AAAGamePlayable`、运行时会话、生成的配置文件以及迁移后的脚本中，不存在与 Fighter、FPS、Racing、Punch、Kick、steering、throttle、boost、handbrake、Preview Character 或 Preview GameMode 相关的耦合关系；
- 生成的配置文件中不包含任何框架的私有头文件；
- 在 `D:\UE\UE_5.4` 环境下，`OpenWLScriptContractTestEditor` 和 `OpenWLScriptContractTest` 均能成功编译；
- 无头模式下的运行时日志包含以下内容：

  ```text
  [AAAGame] 已注册生成的游戏玩法实体工厂
  [AAAGame] 运行时会话同步：实体=entity_contract，控制器=controller_contract，结果=ok
  ```

- `scripts\ue\create_project.cmd` 已创建，且 `AAAGameScriptMigrationTestFullEditor` 编译成功；
- 通过 `UEClient.plugin.install` 安装机械装置配置文件后，`AAAGameScriptMigrationTestFullEditor` 成功运行 UHT，并编译了 `AAAGamePlayable` 以及 `GeneratedGameplayPlugin`；
- `AAAGameScriptMigrationTestFullEditor` 成功编译了 `AAAGamePreview`、`ArenaFighterExample`、`FPSExample` 和 `RacingExample`；
- `AAAGameScriptMigrationTestFull` 针对 Win64 开发游戏目标编译了上述相同的可选插件，证实其不存在仅编辑器依赖项；
- `AAAGameScriptMigrationTestFullEditor` 成功编译了 `GeneratedGameplayAutomationTests.cpp`；
- 调用 `ue.testing.run_automation_tests()` 命令，在 UE 5.4 环境下运行 `AAAGame.GeneratedGameplay.Smoke` 测试，返回结果如下：

  ```text
  returncode = 0
  tests_found = 1
  tests_passed = 1
  tests_failed = 0
  ```
- 执行命令 `python -m unittest test.test_gen_mechanic_agent_contract -v` 后，所有 17 项机械代理上下文/契约测试均通过；
- 自定义的非 UE API 参考文件通过了相同的请求契约测试，证实该代理协议不依赖于 UE 特定的调用；
- 执行命令 `python -m unittest test.test_gen_mechanic_agent_contract test.test_gen_mechanic_operator -v` 后，所有 31 项针对性机械测试均通过，这些测试涵盖持久化生成/修复、Operator 纯净性、轻量级生成器运行行为以及引擎 API 参考的显式处理等内容；
- 执行命令 `pipeline/mechanic/run.py --backend stub --game gameA_cyberpunk_shooter --run-id fps_baseline_v1` 后，`fps_core_001` 任务完成，生成的文件包括：

  ```text
  project/AAAGameFpsCore001.uproject
  generated_plugin/
  demo_outputs/agent_request.json
  demo_outputs/agent_result.json
  demo_outputs/agent_transcript.jsonl
  meta.json
  ```这只是源文件/构件合约结果。
`authoritative_validation=false`，且构建/测试状态为`not_run`。
- 执行命令`pipeline/mechanic/run.py --backend codex --game gameA_cyberpunk_shooter --run-id fps_skill_validation_v1 --agent-timeout 1800 --agent-max-turns 16`后，生成了`AAAGameCyberPrisonFPS`和`CyberPrisonFPS`；
- 公共UEClient操作将所有11个已声明的A层角色导入到生成的项目中：包含272个原生场景文件，以及28个导入的虚拟形象、武器、骨骼、材质/纹理和运动资源；
- `AAAGameCyberPrisonFPS`和`AAAGameCyberPrisonFPSEditor`均使用UE 5.4编译，返回码为0；
- 执行`ue.testing.run_automation_tests("AAAGame.CyberPrisonFPS")`后，结果显示找到3项测试，全部通过，无失败项；
- 运行时日志确认监狱地图已加载，玩家和步枪资源已解析，步枪被附着在`RightHand`上，生成了3个敌人，敌人的攻击对玩家造成了伤害；
- 留存下来的截图拍摄的是IDE界面而非游戏画面，不能作为视觉证据；完整的实时追踪回放结果尚未出炉；
- 被忽略的构件的`meta.json`文件已修正，其中记录了实际的导入、构建、生成测试及运行时冒烟测试证据，但未赋予基准测试结果。
- 重新统计磁盘数据后与元数据一致：共有272个原生场景文件、28个导入的资源文件，总计300个UE资源文件，大小为2,472,307,641字节；所有记录的构建、测试、运行时及视觉证据路径均存在。
- 对留存的视觉证据文件重新核查后发现显示的是VS Code界面而非游戏画面，因此该文件仍被判定为无效。

每次输出被重定向时，本地PowerShell配置文件都会触发重复的PowerShell `Set-PSReadLineOption`提示信息。这并非Unreal引擎的故障。
UnrealBuildTool可能需要提升沙盒权限，因为它会在`C:\Users\Y4624\AppData\Local\UnrealBuildTool`目录下轮换日志文件。Unreal Editor自动化运行也需要用户AppData路径的写入权限，以存储DerivedDataCache、Trace和日志数据。

## 临时验证项目
通过`.tmp/`目录，Git会忽略以下所有路径：

| 路径 | 用途 |
| --- | --- |
| `.tmp/OpenWLScriptContractTest` | 由旧版OpenWL脚本创建，后转换为新框架边界；编辑器/游戏编译及无头UDP运行时验证均通过 |
| `.tmp/AAAGameScriptMigrationTestFull` | 由迁移后的`create_project.cmd`创建；框架、生成的测试夹具、预览版及所有参考插件在编辑器和游戏中均能编译 |
| `.tmp/AAAGameScriptMigrationTest` | 项目创建成功；首次沙盒内构建中断仅因UBT无法轮换AppData日志文件 |
| `.tmp/AAAGamePlayableContractTest` | 早期手动编写的简易C++合约测试夹具 |
| `.tmp/script_outputs` | 用于验证基于描述符的脚本操作的临时任务元数据和生成的插件构件 |

请勿将`.tmp`目录下的文件视为源代码。正式代码仍存储在`engine_adapters/ue5`和`test/fixtures`目录下。## 下一步实施计划：FPS机制生成

在FPS机制生成流程正常运行之前，平台服务将被推迟。后续工作按以下顺序推进。

### A阶段——添加引擎原生测试功能 [已完成]

1. [已完成] 添加`engine_adapters/ue5/testing/`目录，并将其暴露为`ue.testing`。
2. [已完成] 实现以下功能：

   ```python
   ue.testing.run_automation_tests(
       test_filter,
       *,
       report_dir="",
       extra_args=(),
       timeout=None,
       dry_run=False,
   )
   ```

3. [已完成] 将`ue.testing`视为由操作员和评估员负责的公共适配器API。代码Agent负责生成测试源，但不会执行该API或声明基准测试结果是否合格。
4. [已完成] 返回命令、进程输出、结构化诊断信息、报告产物以及解析后的测试数量。
5. [已完成] 补充缺失配置、模拟运行、测试成功、测试失败、进程异常、超时以及报告解析相关的测试用例。
6. [已完成] 使用UE 5.4编译并执行一个最简化的生成式UE自动化测试。
7. [已完成] 在该方法和测试通过后更新`ue5_api.md`文档。

### B阶段——定义机制Agent上下文 [已完成]

1. [已完成] 添加一个与引擎无关的技能：

   ```text
   operators/gen_mechanic/skills/game_generation.md
   ```

2. [已完成] 该技能会读取任务需求、验收标准、生成的资产描述、选定的引擎API参考文档以及可选的只读示例。
3. [已完成] 该技能中不包含任何特定引擎的方法名、FPS实现代码、HUD设计或示例依赖项。
4. [已完成] 添加与引擎无关的`system.md`、`task.md`和`repair.md`提示词模板。
5. [已完成] 要求Agent生成引擎原生的游戏逻辑源码以及引擎原生的游戏逻辑测试源码，由操作员来执行这些测试。

### C阶段——添加类模型Agent后端 [Codex相关功能已完成]

1. [已完成] 保持注入的构造函数参数名为`model`，与现有的资产操作员保持一致。
2. [已完成] 针对机制操作员所需的`model.run(request)`行为，添加`StubAgent`和`CodexAgent`两种实现方式。Claude相关功能留待未来可选实现。
3. [已完成] 不要引入公开的`CodeAgentModel`类，也不要更改现有的资产模型参数名。
4. [已完成] 在真正的Agent后端可用前，先实现对CPU资源友好的Stub版本。

### D阶段——实现机制操作员 [Agent编排功能已完成]

`GenMechanicOperator`必须与现有的操作员管理接口保持一致：

```python
GenMechanicOperator(
    model,
    output_dir=None,
    run_id="default",
    default_game_id=None,
)

run(inp: dict) -> dict
run_batch(inputs: list[dict]) -> list[dict]
```

该操作员负责：- 阅读任务及要求；
- 确定标准任务输出目录；
- 选择技能、引擎API参考文档、提示词以及可选的示例；
- 调用注入的Agent模型；
- 验证生成/修改/删除的工作区报告；
- 通过同一个Agent契约来渲染生成与修复请求；
- 写入`meta.json`并保存失败的工作区数据。

该Agent掌握具体的游戏玩法架构、游戏专属类、输入映射、移动逻辑、动画绑定、动作、AI、规则以及生成的测试源码。

已实现的功能：
- 任务/输出解析及持久化目录创建；
- 基于API参考路径生成与引擎无关的提示词/请求；
- 直接调用鸭子类型化的`model.run(request)`方法；
- 对生成/修改/删除的文件进行验证；
- 保存生成/修复请求及相关证据；
- 禁止Agent向`meta.json`、`demo_outputs/`和`evaluation/`目录写入数据；
- 保存故障相关 artifacts。

待完成事项：
- 任何引擎执行操作都不应属于该Operator的职责范围；
- 构建/测试失败时，仅能通过未来的外部协调器触发修复模式。

### 阶段E – 实现机制流水线[生成路径已完成]
`pipeline/mechanic/run.py`必须与现有的资源运行器接口保持一致：

```python
load_model(...)
make_operator(model, output_dir=None, run_id="default",
              default_game_id=None)
generate(inp, operator)
run_from_jsonl(tasks_path, operator, game_filter=None)
main()
```

该运行器保留了标准的`--game`、`--tasks`、`--run-id`、`--out-dir`和`--device`参数，同时新增了Agent后端、模型、超时时间、最大轮次以及明确的引擎API参考选项。

当前的运行器支持Stub和Codex后端，仅用于生成操作，会拒绝未实现的Claude后端。引擎执行相关的参数不应包含在该运行器中。

### 阶段F – 运行并保存`fps_core_001`
1. 从`test_data/test_samples`中读取`fps_core_001`及其相关要求。
2. 使用来自`fps_baseline_v1`的A层描述符。
3. 生成一个完整的UE项目，将`AAAGamePlayable`源码拷贝进去，并生成/安装独立的FPS玩法插件。
4. 仅将`FPSExample`作为可选的只读实现参考。
5. 构建编辑器与目标游戏版本。
6. 通过`ue.testing`执行Agent生成的自动化测试。
7. 重放指定的FPS轨迹并捕获运行时证据。
8. 保存成功与失败的源项目。

Stub运行模式仍作为源契约的基准。Codex验证运行完成了步骤1-6，保留了源码、导入的资源，编辑器/游戏版本构建成功，且有3项生成的测试通过。这些构建/测试步骤在生成操作后执行，现在需要通过合规的评估器以及外部受限的修复协调器来整合。步骤7尚未完全完成：观察到了运行时启动和战斗AI的表现，但未能捕获完整的实时轨迹以及有效的游戏窗口截图。

### 阶段G – 稳定机制契约[P1]在FPS机制模块可复现之后：

1. 定义并验证机制状态暴露契约；
2. 定义并验证标准化的游戏输入所有权规则；
3. 定义并验证下游模块所使用的游戏玩法事件；
4. 定义UI绑定契约，同时不暴露具体生成类的内部实现；
5. 将稳定的契约记录到机制模块的元数据以及Agent上下文中。

### 阶段H - 实现UI Agent [P2]

阶段G完成后：

1. 实现`GenUIOperator`，即UI Agent的后端集成部分，包括提示词、技能、运行器、截图以及元数据功能；
2. 依据稳定的机制绑定契约生成`fps_hud_001`；
3. 实现所需的HUD、暂停、胜利和失败状态界面；
4. 明确区分UE运行时HUD与浏览器/平台前端的选择逻辑，不新增顶层的任务类型。

### 阶段I - 整合完整游戏流水线 [P3]

在机制和UI模块均可独立复现之后：

1. 通过`pipeline/full_pipeline`整合现有的Layer A、机制模块和UI模块；
2. 打包并验证最终可游玩的垂直切片版本；
3. 实现基于模块的评估机制，且不会触发模块重新生成；
4. 根据所选的UI/运行时交付路径需求，恢复平台服务迁移流程；
5. 仅在公共服务API存在后，才填写`z_other_serve_func.md`文件。

源`OpenWL_Avatar`工作树中可能包含未提交的文件。继续从中复制/读取内容，无需删除、移动、重置或重写源文件。

## 对话参考目标：机制与UI生成

本节记录了后续Codex对话所遵循的约定参考目标。它遵循现有README中定义的结构，不会引入新的层级、任务类型、Operator或输出目录。

### UE与前端分离

- `engine_adapters/ue5`负责Unreal项目、资产、世界、插件、构建、运行时、反射及观测操作。
- `engine_adapters/z_other_serving`负责平台网关、浏览器服务、Pixel Streaming集成以及面向前端平台的运营操作。
- UE脚本仅负责创建、导入、构建和启动Unreal，不会启动平台网关或浏览器前端。
- 平台服务仅能通过公开的`UEClient(api_version="v1")` API访问Unreal。前端、路由及应用使用场景不得导入UE适配器的内部实现。

### Agent API参考- 保持`agent_skills/engine_context/ue5_api.md`与真实的公共`UEClient` API以及`AAAGamePlayable`公共头文件同步。
- 待公共`z_other_serving` API问世后，完善`agent_skills/engine_context/z_other_serve_func.md`。切勿将拟定的API当作已实现的API来记录。
- 位于`operators/gen_mechanic/skills`下的机械师Agent技能必须以`ue5_api.md`作为必需的参考文档。
- 位于`operators/gen_ui/skills`下的UI Agent技能必须将`z_other_serve_func.md`作为浏览器/平台前端开发所需的参考文档；UE运行时HUD开发也可参考`ue5_api.md`。
- 这些参考文件描述了可调用的API及其边界。各游戏的具体行为与参数仍由用户的需求及任务JSONL文件决定。

### 生成的游戏插件流程

机械师Operator与注入的Agent模型遵循以下流程：
1. 流水线从`test_data/test_samples`中读取一个任务，将其传递给Operator，且不会修改输入文件。
2. Operator会读取需求、资产描述、`game_generation.md`、提示词、选定的引擎API参考路径，以及可选的只读示例路径。完整的API文档并不会嵌入到提示词模板中。
3. Agent根据所引用的公共API，生成对应选定引擎的游戏专属扩展模块以及引擎原生测试源码。
4. Agent根据需求设计游戏专属的输入映射、移动逻辑、动画绑定、动作、AI、规则及状态。
5. Operator会验证Agent提交的工作区变更报告，并将请求内容、结果、对话记录以及`meta.json`保存到标准的`paths.task_output_dir()`目录下，即便出现失败情况也会如此保存。
6. 后续的评估器会通过`pipeline.common.paths`定位到该已有产物，准备选定的引擎项目、导入依赖项、进行构建与测试，再通过引擎适配器捕获运行时证据。
7. 结构化的评估失败信息可能会由外部受限协调器传回同一Operator，以进入修复模式。

Agent不得手动复制适配器的内部代码、修改`AAAGamePlayable`、包含框架的私有头文件，也不得将框架自带的具体角色类、Pawn类、控制器类或GameMode类用作所生成游戏的基类。具体的游戏玩法类、规则、动作、AI、武器及状态均会根据用户需求在独立的游戏插件中生成。

### UI实现入口- `fps_hud_001`仍作为只读的未来任务定义存在，而P0和P1任务尚未完成。
- 只有当`fps_core_001`可运行、其生成的测试通过Evaluator负责的`ue.testing`验证，且运行时相关数据被妥善保存后，才会开始UI生成工作。
- 在生成UI代码之前，机制模块必须先提供稳定的状态/事件绑定契约。
- UI代码必须绑定到该契约，而非绑定到某些具体的实体字段，比如特定的角色生命值成员、武器组件的弹药成员，或是背包/游戏性抽象系统（GAS）的实现细节。
- 只要绑定契约保持兼容，后续对机制模块的重构即便改变了具体类结构，也无需强制重新生成UI。

### 流水线部署
- `pipeline/mechanic/run.py`负责筛选任务、加载基于Agent的`model`，将其注入`GenMechanicOperator`，批量驱动生成流程，并写入总结信息。
- `GenMechanicOperator`会整合需求说明、引擎引用、Skill、提示词、示例上下文、输出工作区、生成/修复Agent请求以及Agent元数据。
- Agent请求具有机制模块特异性，但与引擎无关；所选的API参考文档决定了具体的引擎调用方式。
- `pipeline/mechanic/eval.py`必须读取现有的机制模块产物，并使用公开的引擎适配器API，且无需导入生成运行器。
- `pipeline/ui/run.py`通过`GenUIOperator`执行对应的UI/前端生成工作。
- 机制模块和UI的输出会分别作为独立的标准产物留存。
- `pipeline/full_pipeline/run.py`会将现有的资源、机制模块及UI产物整合为最终的可运行版本，但它不会构建`UEClient`。
- 评估工作与生成流程分离，会读取为指定`run_id`已写入的产物进行评估。

### 统一的Operator与运行器契约
机制模块和UI生成遵循与资源生成相同的管理规范：

```text
Operator构造函数：model、output_dir、run_id、default_game_id
Operator方法：run(inp)、run_batch(inputs)
运行器函数：load_model、make_operator、generate、run_from_jsonl、main
```

对于机制模块和UI而言，`model`是代码Agent的执行后端。流水线不会区分所注入的模型是神经推理封装还是工具型Agent。

机制模块Agent的结果中会以工作区相对路径的形式报告`generated_files`、`modified_files`和`deleted_files`。

### 机制模块输出布局
所有文件均存放在以下路径中：

```text
test_data/outputs/<game_id>/<run_id>/mechanic/<task_id>/
```

预期的文件布局如下：

```text
<task_id>/
├── project/
│   ├── <Project>.uproject
│   ├── Config/
│   ├── Content/
│   ├── Source/
│   └── Plugins/
│       ├── AAAGamePlayable/
│       └── <GeneratedGameplayPlugin>/
├── generated_plugin/
├── launch.cmd
├── launch.sh
├── demo_outputs/
│   ├── trace.json
│   ├── trace_result.json
│   ├── build.log
│   ├── agent_transcript.jsonl
│   ├── automation/
│   └── screenshots/
└── meta.json
````project/`目录包含可完整运行的游戏。`generated_plugin/`目录存放的是由Agent生成的、用于安装/同步的标准插件产物。
`demo_outputs/`目录则保存生成的验证证据，失败的项目及相关日志也会被保留。

## 固定边界规则
- `engine_adapters/ue5`是虚幻引擎环境适配器，并非游戏生成器。
- `UEClient(api_version="v1")`是供Agent和平台服务代码使用的唯一公开Python API。
- Agent代码不得导入虚幻引擎适配器的内部模块。
- 源插件`OpenWLPlayable`已被迁移为`AAAGamePlayable`，属于运行时扩展框架。
- `AAAGamePlayable`不得为生成的游戏提供具体的角色、Pawn、控制器或游戏模式，作为这些游戏的玩法基础。
- 机制类Agent会在生成的项目内创建独立的玩法插件，且仅依赖`AAAGamePlayable`的公共头文件。
- 格斗类、第一人称射击类、赛车类实现仅作为参考示例。
- `ue.testing`属于操作员/评估器功能。Agent负责生成测试源码，但不会执行该API或声明基准测试结果是否达标。
- 生成的项目源码及失败项目的源码均属于持久化的机制类产物。
- 平台服务代码位于`engine_adapters/z_other_serving`目录下，仅能通过`UEClient`调用虚幻引擎相关功能。
- 完整流水线负责协调各操作员，绝不会导入`UEClient`。

## 资源清单摘要
目前OpenWL源码包含以下内容：

| 范围 |  tracked文件数 | 分类 |
| --- | ---: | --- |
| `serving/` | 273 | 虚幻引擎实现、平台服务、Blender运行时及共享合约 |
| `serving/engines/unreal/` | 153 | 虚幻引擎适配器实现及虚幻引擎专属调试UI |
| `OpenWLPlayable`插件 | 29 | 运行时基础设施，混杂有格斗类/第一人称射击类/赛车类/预览版实现 |
| `scripts/ue/` | 7 | 公开的创建/导入/运行启动器 |
| 游戏模板/示例 | 47 | 竞技场格斗、第一人称射击、赛车类参考示例 |

OpenWL源码工作区存在未提交的文件。迁移时必须从源码中复制内容，不得删除、移动、重置或重写源码文件。

## 分类标签说明
| 标签 | 含义 |
| --- | --- |
| `COPY` | 移动文件时需更新导入路径并进行针对性清理 |
| `REFACTOR` | 保留原有功能，但调整依赖关系或公共接口 |
| `SPLIT` | 当前源码文件承担了多个目标层的职责 |
| `REFERENCE` | 作为可选的Agent参考内容保留；不会自动安装 |
| `PLATFORM` | 移动到`z_other_serving`目录；必须调用`UEClient` |
| `SUPERSEDE` | 用新的稳定公开API替换原有内容 |
| `DEFER` | 不属于虚幻引擎5迁移范畴 |

## 虚幻引擎Python迁移矩阵| OpenWL源代码路径 | 目标路径 | 操作类型 | 说明 |
| --- | --- | --- | --- |
| `serving/engines/unreal/config.py` | `engine_adapters/ue5/config.py` | 重构 | 将UE引擎版本与UEClient API版本分离 |
| `serving/engines/unreal/environment.py` | `engine_adapters/ue5/_internal/environment.py` | 重构 | 移除具体的游戏玩法类默认值 |
| `serving/engines/unreal/cli.py` | `engine_adapters/ue5/project/`、`build/`、`runtime/`、`scripts/` | 拆分 | 项目/构建逻辑保留在UE适配器中；UI/网关启动功能移至平台层 |
| `serving/engines/unreal/editor/transport/**` | `engine_adapters/ue5/_internal/transport/**` | 复制 | 该类内容永远不会暴露给Agent |
| `serving/engines/unreal/editor/asset_pipeline/**` | `engine_adapters/ue5/assets/_internal/**` | 复制/重构 | 仅通过`ue.assets`和`ue.animation`接口暴露 |
| `serving/engines/unreal/editor/control/**` | `engine_adapters/ue5/world/_internal/`、`runtime/_internal/`、`observe/_internal/` | 拆分 | 现有的`UEClient`只是不完整的编辑器门面 |
| `serving/engines/unreal/editor/commands/**` | `engine_adapters/ue5/_internal/commands/**` | 重构 | 替换对平台请求/结果DTO的依赖 |
| `serving/engines/unreal/inspection/**` | `engine_adapters/ue5/assets/_internal/inspection/**` | 复制 | 通过资产查询/验证方法提供公开访问权限 |
| `serving/engines/unreal/project_content.py` | `engine_adapters/ue5/assets/_internal/project_content.py` | 复制/重构 | 负责项目内容扫描与注册表同步 |
| `serving/engines/unreal/services/asset_service.py` | `engine_adapters/ue5/assets/_internal/service.py` | 复制/重构 | 主要的资产导入实现逻辑 |
| `serving/engines/unreal/services/effect_*` | `engine_adapters/ue5/assets/_internal/effects/` | 复制/重构 | 保留包验证与安全暂存机制 |
| `serving/engines/unreal/services/material_binding_service.py` | `engine_adapters/ue5/bindings/_internal/materials.py` | 复制 | 通过`ue.bindings`接口公开访问 |
| `serving/engines/unreal/services/scene_*` | `engine_adapters/ue5/world/_internal/` 和 `assets/_internal/scenes/` | 拆分 | 将导入/包解析逻辑与世界操作逻辑分离 |
| `serving/engines/unreal/services/native_*` | `engine_adapters/ue5/assets/_internal/native_content/` | 复制 | 保留归档/路径遍历检查机制 |
| `serving/engines/unreal/services/runtime_*_bridge_service.py` | `engine_adapters/ue5/runtime/_internal/bridge/` | 复制/重构 | 移除对具体可玩角色的假设 |
| `serving/engines/unreal/services/runtime_session_service.py` | `engine_adapters/ue5/runtime/_internal/session.py` | 重构 | 保留控制器/实体状态；通过`ue.runtime`接口暴露 |
| `serving/engines/unreal/services/player_session_service.py` | `engine_adapters/ue5/runtime/_internal/` 和 `z_other_serving` | 拆分 | UE进程/端口相关逻辑保留在适配器中；浏览器/平台生命周期管理逻辑移至服务端层 || `serving/engines/unreal/services/pixel_streaming_server.py` | `engine_adapters/ue5/runtime/_internal/streaming.py` 以及 `z_other_serving` | `SPLIT` | UE信令流程支持与前端/查看器归属问题 |
| `serving/engines/unreal/services/import_*viewer_service.py` | `engine_adapters/z_other_serving` | `PLATFORM` | 查看器进程编排属于平台UI范畴 |
| `serving/engines/unreal/world/**` | `engine_adapters/ue5/world/_internal/**` | `COPY`/`REFACTOR` | 在UEClient背后保留当前的WorldSpec/包行为 |
| `serving/engines/unreal/runtime/commands/**` | `engine_adapters/ue5/runtime/_internal/commands/**` | `REFACTOR` | 移除固定的punch/kick/racing请求处理逻辑 |
| `serving/engines/unreal/adapter.py` | `engine_adapters/ue5/ue_client.py` 及私有组合逻辑 | `SUPERSEDE` | 旧版平台EngineAdapter并非Agent API |
| `serving/engines/unreal/capabilities.py` | 如有需要则采用UEClient契约元数据 | `SUPERSEDE` | 无需多引擎能力抽象层 |
| `serving/engines/unreal/gateway_debug/**` | `engine_adapters/z_other_serving` | `PLATFORM` | 重写代码以使用UEClient，而非内部服务 |
| `serving/ue_client.py` | 无 | `SUPERSEDE` | 旧文件仅包含`NotImplemented`占位符 |
| `serving/engines/unreal/editor/control/client.py` | 私有实现输入 | `SUPERSEDE` | 不得再作为第二个公开的UEClient |

## 需移除的跨包依赖

Unreal实现目前会导入平台专属的包：

| 依赖项 | 导入次数 | 解决方案 |
| --- | ---: | --- |
| `serving.contracts` | 12 | 在UE适配器中定义UEClient v1的请求/结果契约 |
| `serving.paths` | 8 | 替换为UE适配器配置/路径服务 |
| `serving.core` | 4 | 仅将UEClient所需的工件/世界数据内部化 |

迁移完成后，`engine_adapters/ue5`不得再导入`engine_adapters/z_other_serving`。

## OpenWLPlayable向AAAGamePlayable的C++分类调整

### 保留并重构为运行时框架

| 当前文件 | 操作 | 所需变更 |
| --- | --- | --- |
| `OpenWLPlayableModule.*` | `COPY` | 保留模块启动逻辑 |
| `OpenWLRuntimeSubsystem.*` | `REFACTOR` | 解除预览角色/游戏模式之间的耦合 |
| `OpenWLRuntimeInputReceiver.*` | `REFACTOR` | 保留传输/封装/就绪相关逻辑；移除Fighter命令及具体Actor类 |
| `OpenWLWorldSessionManager.*` | `REFACTOR` | 用接口、工厂及通用实体绑定机制取代`AOpenWLPlayableCharacter`的创建/控制逻辑 |
| `OpenWLPlayerState.*` | `REFACTOR` | 用身份数据/组件契约取代具体的PlayerState要求 |

目标公共头文件布局：

```text
Source/AAAGamePlayable/Public/
├── Interfaces/
├── Subsystems/
├── Components/
└── DataTypes/
```

生成的插件仅可包含这些公共头文件。私有头文件不属于契约范畴。

### 移出运行时框架| 当前文件 | 分类 | 目标 |
| --- | --- | --- |
| `OpenWLPlayableCharacter.*` | 格斗/第一人称射击游戏玩法，包含具体的移动/摄像机逻辑 | 参考游戏玩法插件 |
| `OpenWLPlayerController.*` | 格斗/第一人称射击/赛车游戏的按键与动作映射 | 参考游戏玩法插件 |
| `OpenWLGameMode.*` | 竞技场/第一人称射击/赛车游戏规则与角色生成逻辑 | 参考游戏玩法插件 |
| `OpenWLFighterHUD.*` | 格斗/第一人称射击/赛车游戏的人机界面 | 参考游戏玩法插件 |
| `OpenWLArcadeVehiclePawn.*` | 赛车功能实现 | 赛车参考插件 |
| `OpenWLPreviewCharacter.*` | 资产预览工具 | 由适配器单独维护的预览工具插件 |
| `OpenWLPreviewGameMode.*` | 资产预览工具 | 由适配器单独维护的预览工具插件 |
| `OpenWLPreviewPlayerController.*` | 资产预览工具 | 由适配器单独维护的预览工具插件 |

这些参考实现不得参与UEClient的运行，不得自动安装，也不得成为`AAAGamePlayable`的依赖项。

## 当前硬编码的游戏玩法耦合问题

在运行时框架边界生效前，必须移除以下内容：
- `DEFAULT_PLAYABLE_CLASS_PATH`指向`/Script/OpenWLPlayable.OpenWLPlayableCharacter`。
- 项目创建时会写入`GlobalDefaultGameMode=/Script/OpenWLPlayable.OpenWLGameMode`。
- 运行时启动会强制使用`/Script/OpenWLPlayable.OpenWLGameMode`。
- 预览模式启动会强制使用`/Script/OpenWLPlayable.OpenWLPreviewGameMode`。
- 展示与运行时桥接脚本会直接生成`OpenWLPlayableCharacter`实例。
- `RuntimeInputReceiver`负责实现格斗类动作及重启逻辑。
- `RuntimeInputReceiver`会直接创建`OpenWLPlayableCharacter`和`OpenWLPreviewCharacter`实例。
- `WorldSessionManager`负责创建并控制`OpenWLPlayableCharacter`实例。
- 运行时会话命令中包含拳击、踢击、赛车转向、油门、加速及手刹相关字段。
- 玩家前端将J/K/F/R键映射为格斗/第一人称射击游戏特有的动作。

## 平台服务迁移矩阵| OpenWL源代码路径 | 目标路径 | 操作类型 |
| --- | --- | --- |
| `serving/gateway/**` | `engine_adapters/z_other_serving/gateway/**` | `PLATFORM` |
| `serving/gateway/frontend/**` | `engine_adapters/z_other_serving/frontend/player/**` | `PLATFORM` |
| `serving/engines/unreal/gateway_debug/import_ui.py` | `engine_adapters/z_other_serving/frontend/asset_admin/` | `PLATFORM` |
| `serving/application/**` | `engine_adapters/z_other_serving/application/**` | `REFACTOR` |
| `serving/client/**` | `engine_adapters/z_other_serving/client/**` | `REFACTOR` |
| `serving/contracts/**` | `engine_adapters/z_other_serving/contracts/**` | `REFACTOR` |
| `serving/core/assets`、`artifacts`、`sessions`、`worlds` | `engine_adapters/z_other_serving/domain/**` | `REFACTOR` |
| `serving/core/games/**` | UE参考示例 | `REFERENCE` |
| `serving/infrastructure/**` | `engine_adapters/z_other_serving/infrastructure/**` | `PLATFORM` |
| `serving/bootstrap.py` | `engine_adapters/z_other_serving/bootstrap.py` | `REFACTOR` |
| `serving/paths.py` | 拆分为UE配置和平台配置 | `SPLIT` |
| `serving/docs/**` | Runtime Contract提取过程中的设计参考 | `REFERENCE` |
| `serving/blender_runtime/**` | 未来的Blender适配器开发工作 | `DEFER` |

迁移后的平台组合根可能会创建`UEClient`，但任何平台路由、应用用例或前端服务都不得导入UE内部模块。

## 脚本与示例

| 源路径 | 目标路径 | 操作类型 |
| --- | --- | --- |
| `scripts/ue/create_project.*` | `scripts/ue/` + `engine_adapters/ue5/cli.py` | `COMPLETE`：包装器调用公共的UEClient CLI |
| `scripts/ue/import_asset.*` | `scripts/ue/` + `engine_adapters/ue5/cli.py` | `COMPLETE`：仅支持基于描述符的导入 |
| `scripts/ue/run.*` | `scripts/ue/` + 未来的平台启动器 | `SPLIT`：Unreal启动已完成；平台启动待处理 |
| Fighter具体的C++实现 | `engine_adapters/ue5/examples/ArenaFighterExample/` | `COMPLETE` 参考插件 |
| FPS具体的C++实现 | `engine_adapters/ue5/examples/FPSExample/` | `COMPLETE` 参考插件 |
| 赛车类游戏具体的C++实现 | `engine_adapters/ue5/examples/RacingExample/` | `COMPLETE` 参考插件 |
| `examples/games/**` | 对应的参考示例目录 | `REFERENCE` |
| `scripts/games/generate.py` | 参考示例工具 | `REFERENCE` |

## 测试迁移矩阵

| 测试组 | 目标/角色 |
| --- | --- |
| 资产/特效/场景/材质/PLY/Gaussian测试 | `test/engine_adapters/ue5/` |
| Unreal CLI测试 | UEClient项目/构建/运行时测试 |
| Serving客户端测试 | `z_other_serving`相关测试 |
| GameSpec Arena/FPS/Racing测试 | 参考示例测试 |
| 现有的`test_ue_serving.py` | 拆分为UE环境测试和平台Serving测试 |
| 新的Runtime Framework测试 | 仅使用公共头文件编译一个最简化的生成式Gameplay插件 |
| 预览/参考插件边界测试 | 静态依赖测试，以及UE 5.4编辑器/游戏编译测试 |未纳入跟踪的OpenWL测试项目包括特效导入、GameSpec、高斯泼溅效果、PBR材质、PLY网格、客户端服务以及Unreal CLI，它们均属于迁移清单范畴，绝不能被遗漏。

## UEClient v1公共接口分类
该清单支持以下稳定的接口分组：
```text
ue.project
ue.assets
ue.animation
ue.bindings
ue.world
ue.reflection
ue.plugin
ue.build
ue.testing
ue.runtime
ue.observe
```
`ue.testing`用于执行引擎原生的操作符与评估器自动化测试。游戏生成代理会生成兼容的测试源码，但不会调用测试命名空间，也不会声明基准测试结果是否达标。

不同Unreal版本中，实现模块可能会有所变化。代理、技能组件、平台服务以及生成的项目自动化流程仅依赖以下代码：
```text
from engine_adapters.ue5 import UEClient
```

## 实现迁移顺序
1. [已完成] 搭建UEClient v1的包壳结构，确定稳定的结果契约。
2. [已完成] 迁移传输/配置相关的内部逻辑，且不对外暴露。
3. [已完成] 迁移资产导入、验证、注册表、场景、材质及特效相关逻辑。
4. [已完成] 将项目/构建/运行时流程逻辑及公共脚本从现有的CLI/服务中拆分出来。
5. [已完成] 将源插件`OpenWLPlayable`重构为`AAAGamePlayable`公共接口。
6. [已完成] 将预览工具及游戏专属代码从基础插件中移出，放入可选的预览/参考插件中。
7. [FPS演示之后待处理] 重写平台服务组合逻辑，使其仅使用UEClient。
8. [已完成] 移植测试用例，编译出最小的GeneratedGameplayPlugin测试套件。

## 第一步完成判定标准
满足以下条件时，该清单即视为完整：
- 每个OpenWL Unreal顶层包都有对应的目标与操作；
- 所有当前的OpenWLPlayable类均已完成分类；
- 平台及Unreal依赖冲突问题已被记录；
- 包括未纳入跟踪的测试在内，所有测试用例均已被纳入考量；
- 无需盲目移动源文件，即可启动下一步实现工作。
