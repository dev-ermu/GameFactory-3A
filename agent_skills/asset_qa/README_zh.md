# `agent_skills/asset_qa` — 资产生成与视觉质量检查

该目录包含具备视觉识别能力的编码智能体所使用的资产生成与质量检查相关技能。当项目计划确定需要制作新资产时，可在宣布生成的或导入的内容可正式发布之前使用这些技能。

`<REPO_PATH>/agent_skills/asset_qa/` 涵盖了资产工作中需要依赖视觉或运行时判断的环节：比如网格模型的方向是否正确、缩放比例是否合理、是否符合要求的风格，以及能否在游戏中正常播放动画。仅靠文件解析和结构检查无法回答这些问题。

路径均以仓库根目录为起点，表示为`<REPO_PATH>/...`；具体规则可参考`<REPO_PATH>/agent_skills/setting_overview.md`中的“路径规范”章节。`<REPO_PATH>/engine_adapters/`、`<REPO_PATH>/pipeline/`、`<REPO_PATH>/scripts/`和`<REPO_PATH>/test_data/`与`<REPO_PATH>/agent_skills/`同级，并非其子目录。

## 技能对照表

| 资产任务 | 对应技能 | 适用场景 |
|---|---|---|
| 图像预处理与T型姿势生成 | `<REPO_PATH>/agent_skills/asset_qa/image/SKILL.md` | 单物体重建输入、角色T型姿势图像、透明度通道处理及图像质量检查 |
| 3D物体生成与审核 | `<REPO_PATH>/agent_skills/asset_qa/3d_object/SKILL.md` | 道具、虚拟形象、武器、网格模型质量评估、来源追溯及发布可行性审核 |
| 导入资产的朝向调整 | `<REPO_PATH>/agent_skills/asset_qa/3d_object/orientation_review.md` | 前向轴校准、缩放调整、地面接触判定、附着点设置及引擎导入审核 |
| 3D场景生成 | `<REPO_PATH>/agent_skills/asset_qa/3d_scene/SKILL.md` | 场景生成或组装、布局规划、环境质量评估及场景级审核 |
| 动画处理 | `<REPO_PATH>/agent_skills/asset_qa/motion/SKILL.md` | 骨骼绑定、动画生成/获取、动作重定向、导入操作及游戏内动画效果审核 |
| CG视频制作 | `<REPO_PATH>/agent_skills/asset_qa/cg_video/SKILL.md` | CG提示词设计、后端工具选择、视频生成、瑕疵排查及视频质量检查 |

导入已审核通过的资产或场景前，请先阅读`<REPO_PATH>/agent_skills/engine_context/`中的对应引擎规范文档。这些文档规定了格式要求、坐标约定、公共API、项目结构以及运行时验证规则。

## 环境配置指南

在执行相关生成任务前，请先使用下方的特定任务安装脚本。所有路径均相对于仓库根目录`<REPO_PATH>/`。位于`<REPO_PATH>/scripts/asset_env_setup/`目录下的`cloud_api_install.sh`为通用实现脚本；新的代理工作流应调用特定任务的入口点，而非直接调用该共享脚本。

| 资产类型       | 标准配置命令                                                                 | 额外配置说明                                                                 |
|----------------|------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| 图像/T-pose    | 目前无需全局安装脚本                                                         | 请参阅`<REPO_PATH>/scripts/asset_env_setup/image/`目录下的`cloud_api_install.sh`、`qwen_image_install.sh`，以及`<REPO_PATH>/agent_skills/asset_qa/image/SKILL.md` |
| 3D物体         | `bash scripts/asset_env_setup/3d_object/cloud_api_install.sh`                | 本地TRELLIS.2模型：执行`bash scripts/asset_env_setup/3d_object/trellis2_install.sh` |
| 3D场景         | 目前无需全局安装脚本                                                         | 请参阅`<REPO_PATH>/scripts/asset_env_setup/3d_scene/README.md`，并根据需要选用对应的引擎资产库 |
| 动作数据       | `bash scripts/asset_env_setup/gen_motion/install.sh`                          | 随后执行`source scripts/asset_env_setup/gen_motion/runtime_env.sh`            |
| 音频           | `bash scripts/asset_env_setup/audio/cloud_api_install.sh`                     | 本地检查点相关信息请参阅`<REPO_PATH>/agent_skills/asset_qa/audio/SKILL.md`     |
| CG视频         | `bash scripts/asset_env_setup/cg_video/cloud_api_install.sh`                 | 本地MiniMax H3模型：执行`bash scripts/asset_env_setup/cg_video/minimax_h3_install.sh` |

## 付费云后端：使用前需征求用户许可

对于成熟的资产类型——**3D物体、图像/T-pose、音频、CG视频**——推荐使用闭源云API作为首选方案，因为它们的可靠性远高于本地/开源方案。由于这些服务会消耗用户的费用，代理程序必须**暂停并询问用户**，而不能默认用户已拥有相应的访问密钥。

| 资产类型       | 推荐的付费后端               | 购买/获取API密钥页面                                                                 | 环境变量               |
|----------------|----------------------------|------------------------------------------------------------------------------------|------------------------|
| 3D物体         | Tripo，其次是Meshy          | <https://platform.tripo3d.ai/api-keys>、<https://www.meshy.ai/api>                 | `TRIPO_API_KEY`、`MESHY_API_KEY` |
| 图像/T-pose    | 通过火山引擎Ark平台调用的Seedream | <https://console.volcengine.com/ark>                                              | `ARK_API_KEY`          |
| 音频           | 通过火山引擎调用的Seed Audio | <https://console.volcengine.com/speech/>                                          | `SEED_AUDIO_API_KEY`   |
| CG视频         | 通过Ark平台调用的Seedance，其次是MiniMax Hailuo | <https://console.volcengine.com/ark>、<https://platform.minimax.io/user-center/basic-information/interface-key> | `ARK_API_KEY`、`MINIMAX_API_KEY` |所有配置项都要写入 **`<REPO_PATH>/.env`** 这个唯一的配置文件（执行 `cp .env.example .env` 即可创建），该文件会被 `<REPO_PATH>/config.py` 读取。每个服务提供商都需要同时设置 `*_API_BASE` 和 `*_API_KEY` 两个参数；其中基础URL是必填项，且没有默认取值，因为公共端点并非在所有网络中都能访问。

3D模型、图像/T姿态以及音频的本地处理路径是默认选项，但该方式需要配备CUDA GPU，还需占用数十GB的权重文件和磁盘空间。如果当前机器无法运行本地处理流程，可在 `.env` 文件中将该选项切换为云后端，并填入对应服务提供商的 `*_API_BASE` 和 `*_API_KEY`：只要这两个参数未设置，Pipeline运行器就会拒绝启动，因此无法使用的本地路径会立刻被识别出来，而不会在任务中途才暴露问题。

首次调用付费服务前，请遵循以下步骤：

1. **暂停操作**。切勿直接运行付费后端，绝对不要编造、猜测或复用来自其他无关来源的密钥。
2. **单条消息询问**，内容需包含：推荐的服务提供商及理由；上述购买/获取API密钥的链接；该提供商当前的定价页面（从该控制台可找到链接），以及你对该批次任务的**预估费用**——即单价乘以任务数量、时长或分辨率，再加上重试所需的额外费用；同时要明确请求用户购买访问权限并将密钥提供给你。
3. **等待用户的明确答复**。是否付费由用户决定，而非默认选项。
4. **若获得批准**，优先让用户自行导出密钥；否则仅将密钥设置在会话环境中。绝不要把密钥写入JSONL文件、任务元数据、缓存键、日志或提交记录中。
5. **若被拒绝，或预算不足以支持付费服务**，请如实告知用户，并切换为针对该资产类型的已文档说明的本地/开源替代方案。如果没有任何路径能生成可交付的资产，应直接汇报这一缺口，而非悄悄降低质量。
6. 在消耗积分前，先运行该技能对应的免费 Smoke 测试/合约检查；对于规模较大或需要重复处理的批次任务，还需事先再次征得用户确认。

## 审核工作流程

1. 以已获批的方案为准，参考其中规定的资产风格、角色定位及验收标准开展工作。
2. 通过选定的路径生成或获取资产。对于3D模型等成熟的资产类型，优先选择可靠的闭源/云API——按照上述“付费云后端”的要求，先获取用户的批准和密钥。对于动作生成、3D场景这类尚不成熟的路径，如果所选游戏引擎的资产库能提供更优质的可交付结果，则优先选用引擎库中的合规授权资产。
3. 执行针对该任务的结构性检查，以及选定技能对应的视觉质量检查。
4. 使用选定的 `<REPO_PATH>/agent_skills/engine_context/` 合约导入资产。
5. 在目标游戏中运行该资产，模拟相关玩家操作，查看低分辨率截图以排查方向、附着、动画、穿模、缩放、材质、特效、光照及风格等方面的问题。
6. 反复迭代直至资产符合预定的验收标准。对于外部获取的资产，需留存其来源、许可及出处信息。## 生成结果与测试文件的存放位置

- 所有生成的游戏结果均存放在 `<REPO_PATH>/test_data/outputs/` 目录下，按游戏、运行实例、任务类型及任务ID进行分类。请使用 `<REPO_PATH>/pipeline/common/paths.py` 来获取路径，切勿手动构造输出路径。
- 游戏机制与用户界面相关内容存放在各游戏的运行目录中，例如：`<REPO_PATH>/test_data/outputs/gameA_cyberpunk_shooter/default/mechanic/<task_id>/` 和 `<REPO_PATH>/test_data/outputs/gameA_cyberpunk_shooter/default/ui/<task_id>/`。请勿在根目录下创建 `<REPO_PATH>/test_data/outputs/mechanic/` 或 `<REPO_PATH>/test_data/outputs/ui/` 这类目录。
- `<REPO_PATH>/test/` 目录下存放的是可运行的、当前正在使用的测试脚本与冒烟测试脚本。相关人员应使用这些测试脚本来验证生成的资源、游戏代码或适配器流程是否能够正常运行；仅凭生成的文件本身并不能证明测试成功。
- `<REPO_PATH>/third_party/` 目录用于存放从外部克隆的仓库，比如 `trimesh` 以及引擎材质/资源包。这些内容属于外部依赖项：切勿修改或重新分发，使用前需仔细查看其上游许可协议及安装说明。

## 为何需要进行视觉质量检查

适配器能够验证资源的格式、层级结构、三角形数量、边界框以及动画结构，但无法判断对称网格的朝向是否正确、未直接显示的重建模型是否可用、车轮或武器附件的位置是否准确，也无法确认动画效果是否自然。因此，在视觉类资源被采纳之前，必须通过视觉模型或人工方式对渲染预览图和游戏画面进行审核。

对于运动剪辑资源，需将其对应的来源/许可元数据与运动资产一同保存，且切勿在产品版本中包含非商业用途的来源素材。
