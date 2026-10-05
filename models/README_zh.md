# models/

针对单个生成模型的轻量级封装。**每个模型对应一个文件**。

每个封装都应提供统一的接口（例如 `load()`、`infer()`、`unload()`），以便操作员在无需了解具体实现细节的情况下切换后端。

共有两份规范文档，均位于 `agent_skills/develop_harness/` 目录下：针对本地权重模型的 `model_require.md`，以及当模型为闭源云API时的 `api_model_require.md`（R9）。通用的云端处理逻辑（HTTP重试、错误分类、响应缓存、提交请求→轮询状态→下载结果）被封装在 `models/common/cloud_api.py` 中——请勿为每个服务提供商重复实现这些逻辑。

## 已实现的封装| 插槽 | 类别 | 文件 | 类型 | 所需条件 |
|------|-------|------|------|-------|
| `gen_3d_object` | `Trellis2Model` | `gen_3d_object/trellis_2_model.py` | 本地权重 | GPU + o-voxel扩展 |
| `gen_3d_object` | `TripoModel` | `gen_3d_object/tripo_model.py` | 云端API | `$TRIPO_API_KEY` + `scripts/asset_env_setup/3d_object/cloud_api_install.sh` |
| `gen_3d_object` | `MeshyModel` | `gen_3d_object/meshy_model.py` | 云端API | `$MESHY_API_KEY` + `scripts/asset_env_setup/3d_object/cloud_api_install.sh` |
| `gen_3d_scene` | `WorldMirrorModel` | `gen_3d_scene/world_mirror_model.py` | 本地权重 | GPU |
| `gen_3d_scene` | `WorldPlayModel` | `gen_3d_scene/world_play_model.py` | 本地权重 | GPU + 需检出HY-WorldPlay代码库 |
| `gen_cg_video` | `SeedanceModel` | `gen_cg_video/seedance_model.py` | 云端API | `$ARK_API_KEY` + `scripts/asset_env_setup/cg_video/cloud_api_install.sh` |
| `gen_cg_video` | `MiniMaxH3Model` | `gen_cg_video/minimax_h3_model.py` | 云端API + 本地剪枝后的INT8权重 | `$MINIMAX_API_KEY` 或 `scripts/asset_env_setup/cg_video/minimax_h3_install.sh` |
| `gen_image` | `QwenEditModel` | `gen_image/qwen_edit_model.py` | 本地权重 | GPU |
| `gen_image` | `SeedreamModel` | `gen_image/seedream_model.py` | 云端API | `$ARK_API_KEY` + `scripts/asset_env_setup/image/cloud_api_install.sh` |
| `gen_image` | `SDXLTurboModel` | `gen_image/sdxl_turbo.py` | 本地权重 | GPU；仅用于概念设计，不用于游戏输出 |
| `gen_audio` | `SeedAudioModel` | `gen_audio/seed_audio_model.py` | 云端API | `$SEED_AUDIO_API_KEY` + `scripts/asset_env_setup/audio/cloud_api_install.sh`；同一个类同时服务于对话和音效插槽 |
| `gen_audio` | `Qwen3TTSModel` | `gen_audio/qwen3_tts_model.py` | 本地权重 | 需执行 `pip install -U qwen-tts`；可用于自定义语音/语音设计/语音克隆 |
| `gen_audio` | `WooshDFlowModel` | `gen_audio/woosh_model.py` | 本地权重 | 需要Woosh-DFlow、Woosh-AE、TextConditionerA检查点；相关权重遵循CC-BY-NC许可 |
| `gen_motion` | `PuppeteerModel` | `gen_motion/puppeteer_model.py` | 外部源 + 本地权重 | 需CUDA骨骼绑定运行时环境 |
| `gen_motion` | `MoMaskModel` | `gen_motion/momask_model.py` | 外部源 + 本地权重 | 可使用CPU或CUDA生成运行时环境 |
| `tools/image_matting` | `RMBGModel`、`DepthAnythingModel` | `tools/image_matting/{rmbg_model.py,depth_anything_model.py}` | 本地权重 | — |
| `tools/segmentation` | `SkySegmentationModel` | `tools/segmentation/sky.py` | 本地权重 | 需安装`onnxruntime`（CPU版本即可） |

`PuppeteerModel`和`MoMaskModel`会在隔离的子进程中运行其固定的上游代码库。此举可避免命名空间冲突，并能在骨骼绑定和运动生成阶段之间释放GPU内存。它们的代码库、权重、缓存及测试资源均属于外部运行时数据；只有这些封装层和可复现的安装脚本才需要纳入Git版本控制。三种`gen_3d_object`后端都提供了相同的`infer_and_save(image, output_path, seed, decimation_target, texture_size)`接口，因此`Gen3DObjectOperator`可以在不更改代码的情况下切换使用它们（R6）。你可以通过运行`python pipeline/assets_gen/gen_3d_object/run.py --backend {trellis2,tripo,meshy}`来选择其中一种后端。

| | Tripo | Meshy |
|---|---|---|
| 免费套餐 | 注册即送2000积分 | 每月100积分 |
| 支持格式 | GLB（转换端点尚未接入） | GLB、FBX、OBJ、USDZ、STL |
| 文生3D | 单个任务 | 预览+精修（计为两个收费任务） |
| 低多边形模型 | `smart_low_poly`、P系列模型 | `model_type="lowpoly"` |
| 面数限制 | `face_limit` | `target_polycount`，范围为10万到30万 |

两个`gen_3d_scene`封装器是链式协作关系，而非互相替代。`WorldPlayModel`会沿着参考图像的路径移动摄像头来生成帧画面，而`WorldMirrorModel`则根据帧画面重建几何结构，因此`Gen3DSceneOperator`会将它们分别置于不同的参数槽中。其中只有几何结构槽是必需的——如果任务已有现成的视频素材，或者仅需单视角内容，就完全不需要世界模型。`world_mirror_utils/`目录下存放的是支撑几何结构封装器的HunyuanWorldMirror定制源码；相关修改详情可查看其README文件。

`SkySegmentationModel`是同一流程中的第三个、规模较小的组件。深度估计模型无法表示“无穷远”的概念，因此会将天空设定在有限的深度上，且该深度与真实表面的阈值划分并不明显，最终天空会被网格化，形成覆盖整个场景的“幕布”。只有分割模型才能识别出这部分天空。

## 子模块

| 目录                | 用途                          | 候选模型 |
|--------------------|------------------------------|------------------|
| `gen_3d_object/`   | 单个3D资产生成               | TRELLIS.2、Hunyuan3D-2.1、TripoSG、Step1X-3D、Direct3D-S2、Craftsman3D、Michelangelo、Meshy、Tripo、Rodin、CSM、Luma Genie |
| `gen_3d_scene/`    | 整个场景/世界生成            | Hunyuan-WorldPlay2、FlashWorld、FantasyWorld |
| `gen_motion/`      | 动作生成与骨骼绑定模型       | 已实装Puppeteer和MoMask；MDM、MLD、T2M-GPT、MotionGPT为候选模型 |
| `gen_cg_video/`    | 电影级/CG视频生成            | LTX-2.3、HunyuanVideo、Wan、Mochi、CogVideoX、Open-Sora、Seedance 2、Kling 3、Veo 3、Sora 2、Runway Gen-4、Hailuo、Vidu |
| `gen_audio/`       | 角色语音、对话及游戏音效生成 | 已实装Seed Audio、Qwen3-TTS和Woosh-DFlow；其他语音及音效后端为候选模型 |
| `reasoning/`       | 流水线中使用的LLM/VLM        | Claude、GPT-5.5、GLM、Kimi、DeepSeek、Gemini、Qwen、Grok、Llama、Mistral |
| `tools/`           | 实用模型（深度估计、抠图、分割等） | Depth-Anything、RMBG、SAM等 |
| `unified_model/`   | 复合/多模态流水线            | 例如端到端的资产+动作生成模型 |
