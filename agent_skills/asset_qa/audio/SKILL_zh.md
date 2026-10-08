# 音频生成与质量审核技能

当游戏开发计划需要**对话、语音台词、音效、拟音、环境音或其他离线WAV资源**时，可使用此项技能。这属于资产生成范畴，并非运行时音频播放相关需求；资产通过审核后，再在选定的游戏引擎中使用。

## 范围与输出

音频处理流程如下：

```text
任务字典 / JSONL → GenAudioOperator → 选定的音频模型 → WAV + meta.json
```

- 模型实现路径：`<REPO_PATH>/models/gen_audio/`
- 任务与产物处理逻辑：`<REPO_PATH>/operators/gen_audio/`
- 运行器与批量执行逻辑：`<REPO_PATH>/pipeline/assets_gen/gen_audio/`
- 免费 Smoke 测试入口：`<REPO_PATH>/tests/harness/`
- 生成结果存储路径：`<REPO_PATH>/test_data/outputs/<game_id>/<run_id>/assets/audio/<task_id>/`

输出路径可通过 `<REPO_PATH>/pipeline/common/paths.py` 获取。机械音效和UI相关音频应存放在对应游戏的运行目录下，而非根目录下的 `<REPO_PATH>/test_data/outputs/mechanic/` 或 `<REPO_PATH>/test_data/outputs/ui/` 目录中。

## 生成前的规划

针对每一项音频任务，需记录以下信息：

1. 对应的游戏场景与音源（玩家、敌人、世界环境、UI、过场动画）；
2. 资产类型：`dialogue`（对话）或 `sound_effect`（音效）；
3. 游戏代码要求该音频的播放时长（发射速率间隔、动画长度、循环周期），以及语言/语音要求、情感表达、距离感、视角设定和任何叙事语境相关信息；
4. 风格参考、音量/混音要求、是否需要循环，以及验收标准；

切勿要求生成器模仿有版权的真人表演者声音，或在未取得相应授权的情况下使用参考录音。绝对不要将音频API密钥或私有参考录音提交到代码库。

## 后端选择

| 需求场景 | 推荐获取方式 | 备注 |
|---|---|---|
| 角色对话/文本转语音 | Qwen3-TTS 或 Seed Audio | 需选择已获授权且适合该游戏的语音，同时记录说话人配置信息。 |
| 快速生成的云端对话或音效 | Seed Audio 1.0 | 该API同时支持两种需求，可输出离线WAV资产。 |



对于**枪声、雷声、雨声、风声、脚步声、引擎声及撞击声**，建议选用所选引擎音频库中收录的真实录音，或经过许可审核的免费资源库（CC0 / CC-BY）——现有资源库已能很好地覆盖这类音效，且真实录音的效果比生成的模拟音效更具说服力。需记录录音来源与许可信息，且不得将非商用素材纳入产品构建中。只有在找不到合适的现成音效或该音效属于虚构内容（如能量武器音效、魔法咒语音效）时，才考虑生成。

**需使音效片段长度与代码需求相匹配**，随后获取或裁剪至相应长度：
- 从游戏代码中获取所需长度——包括射击间隔、动画时长、循环周期等。对于生成任务，需对比`meta.json`中的`requested_duration_sec`与实际输出的`duration_sec`。
- 单次播放音效：开头无静音段，结尾长度需短于重新触发间隔，否则快速连续播放会导致声音失真；循环环境音效则需实现无缝衔接，音量无突兀变化。
- 导入前需在音频工具中完成裁剪或淡入处理；绝不可通过在游戏代码中截取播放时间来修正长度不符的音效素材。

## 环境搭建

### 本地后端依赖

### 共享云API依赖
```bash
bash scripts/asset_env_setup/audio/cloud_api_install.sh
```

```bash
```
```bash
python pipeline/assets_gen/gen_audio/run.py \
  --only-audio-type sound_effect \
  --no-auto-download
```

## Seed Audio 1.0云后端Seed Audio无需更改任务JSON文件，即可占用现有的音频插槽：

- `audio_type=dialogue`：角色语音；
- `audio_type=sound_effect`：一次性音效、拟音和环境音。

它在流水线边界处同步处理，会生成离线的WAV音频资源。
默认的中国区端点为
`https://openspeech.bytedance.com/api/v3/tts/create`。

### 凭证与可选配置

```bash
export SEED_AUDIO_API_KEY=<你的火山引擎Seed Audio API密钥>
export AAAGF_API_CACHE=test_data/outputs/_api_cache

# 可选配置：
export SEED_AUDIO_MODEL=seed-audio-1.0
export SEED_AUDIO_API_BASE=https://openspeech.bytedance.com
export SEED_AUDIO_SPEAKER_ID=<已注册的Seed Audio发音人资源ID>
export AAAGF_DIALOGUE_BACKEND=seed_audio
export AAAGF_SOUND_EFFECT_BACKEND=seed_audio
```

任务中Qwen风格的`speaker_id`值（例如`Vivian`）不会发送给Seed Audio。若要指定发音人，需使用`SEED_AUDIO_SPEAKER_ID`参数来指定已注册的Seed Audio发音人。如果提供了`reference_audio_path`，则内存中的参考音频会优先于该发音人ID生效。仅在相关授权允许的情况下才可使用参考录音。

### Seed Audio命令

生成对话音频：

```bash
python pipeline/assets_gen/gen_audio/run.py \
  --dialogue-backend seed_audio \
  --audio-type dialogue \
  --text "发现目标" \
  --task-id spotted_target
```

生成音效：

```bash
python pipeline/assets_gen/gen_audio/run.py \
  --sound-effect-backend seed_audio \
  --audio-type sound_effect \
  --prompt "a single close futuristic rifle shot, dry, no music" \
  --duration-sec 2 \
  --task-id rifle_shot
```

通过JSONL批量文件同时生成两类音频：

```bash
python pipeline/assets_gen/gen_audio/run.py \
  --dialogue-backend seed_audio \
  --sound-effect-backend seed_audio \
  --game gameA_cyberpunk_shooter
```

## 常见问题解答与验证

1. 在进行任何付费云服务调用前，先运行免费检查：

   ```bash
   python tests/harness/smoke.py --kind audio --backend seed_audio
   python tests/test_api_audio.py
   ```

   接口契约测试会使用虚拟HTTP客户端，不会消耗任何配额。

2. 集成前先检查WAV文件：确保一次性音效中没有多余的音乐、无 clipping现象、无突然截断或明显的背景噪音，且时长符合要求。对比实际生成的`duration_sec`值与游戏代码所需的时长，确认一次性音效没有多余的起始静音，循环播放时衔接自然无痕迹。

3. 将音频资源集成到目标游戏中，并测试相关动作或场景。检查触发时机、音量衰减、循环播放效果、对话的可懂度、空间定位效果、混音平衡性，以及与要求的风格是否一致。

4. 录制一段包含音频的低分辨率游戏实况视频；如果无法录制音频，需说明具体的平台限制。

5. 需在任务元数据中包含提供商/模型信息、提示词或文本内容、源/参考音频的授权情况、后端配置、缓存状态以及审核结果。切勿仅仅因为存在WAV文件就宣称其已通过审核。只有当该资源在游戏中的表现及风格符合预定的验收标准时，才算被正式接受。
