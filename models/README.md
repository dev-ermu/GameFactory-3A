# models/

针对单个生成模型的轻量级封装。**每个模型对应一个文件**。

每个封装都应提供统一的接口（`__init__()`、`request()`、`release()`），以便操作符在无需了解具体实现细节的情况下切换后端。

规范文档位于 `agent_skills/develop_harness/` 目录：`model_require.md` 规定封装形态，`model_require.md`（R9）针对闭源云 API——R9 覆盖 R2.1–R2.3、R3.3/R3.4、R3.6 与 R4 条款，适用于远程模型。通用的云端处理逻辑（HTTP 重试、错误分类、响应缓存、提交请求→轮询状态→下载结果）被封装在 `models/common/cloud_api.py` 中——请勿为每个服务提供商重复实现这些逻辑。

本目录下的生成后端**全部为云端 API**。本仓库不下载模型权重：凭证写在 `.env` 中，安装脚本只负责安装各服务商所需的 Python 依赖。

## 已实现的封装

| 插槽 | 类别 | 文件 | 类型 | 所需条件 |
|------|-------|------|------|-------|
| `gen_3d_object` | `TripoModel` | `gen_3d_object/tripo_model.py` | 云端 API | `$TRIPO_API_KEY |
| `gen_3d_object` | `MeshyModel` | `gen_3d_object/meshy_model.py` | 云端 API | `$MESHY_API_KEY |
| `gen_image` | `SeedreamModel` | `gen_image/seedream_model.py` | 云端 API | `$ARK_API_KEY |
| `gen_cg_video` | `SeedanceModel` | `gen_cg_video/seedance_model.py` | 云端 API | `$ARK_API_KEY |
| `gen_audio` | `SeedAudioModel` | `gen_audio/seed_audio_model.py` | 云端 API | `$SEED_AUDIO_API_KEY；同一个类同时服务于对话和音效插槽 |
| `gen_motion` | `TripoRiggingModel` | `gen_motion/tripo_rigging_model.py` | 云端 API | `$TRIPO_API_KEY`；骨骼绑定、重定向、动画与格式转换由同一服务商完成 |

## 选择 `gen_3d_object` 后端

两个后端提供相同的 `request_and_save(image, output_path, seed, decimation_target, texture_size)` 接口，因此 `Gen3DObjectOperator` 无需修改代码即可切换（R6）：

| | Tripo | Meshy |
|---|---|---|
| 免费套餐 | 注册即送 2000 积分 | 每月 100 积分 |
| 支持格式 | GLB（转换端点尚未接入） | GLB、FBX、OBJ、USDZ、STL |
| 文生 3D | 单个任务 | 预览+精修（计为两个收费任务） |
| 低多边形模型 | `smart_low_poly`、P 系列模型 | `model_type="lowpoly"` |
| 面数限制 | `face_limit` | `target_polycount`，范围为 10 万到 30 万 |

选择方式：

```
python pipeline/assets_gen/gen_3d_object/run.py --backend {tripo,meshy}
```

## 子模块

本目录下没有任何封装从磁盘读取权重。这里全部是通过HTTP访问的云端API，既没有本地模型，也没有检查点路径，更没有任何需要下载的东西。

| 目录                | 用途                          | 候选模型 |
|--------------------|------------------------------|------------------|
| `gen_3d_object/`   | 单个 3D 资产生成              | Tripo、Meshy、Rodin、CSM、Step1X-3D、Direct3D-S2 |
| `gen_motion/`      | 动作生成与骨骼绑定模型         | Tripo 骨骼绑定；MDM、MLD、T2M-GPT 为候选模型 |
| `gen_cg_video/`    | 电影级/CG 视频生成            | Seedance、Kling、Veo、Sora、Runway Gen-4、Hailuo、Vidu |
| `gen_audio/`       | 角色语音、对话及游戏音效生成   | Seed Audio；其他语音及音效后端为候选模型 |
| `reasoning/`       | 流水线中使用的 LLM/VLM        | Claude、GPT、GLM、Kimi、DeepSeek、Gemini、Qwen、Llama、Mistral |
| `common/`          | 共享管道：HTTP、重试、缓存、glTF 写入器 | — |
| `unified_model/`   | 复合/多模态流水线            | 例如端到端的资产+动作生成模型 |
