# Audio generation and QA Skill

Use this Skill when a game plan requires **dialogue, voice lines, sound effects,
foley, ambience, or other offline WAV assets**. This is asset generation, not a
runtime audio-playback contract; use the selected engine context after an asset
has passed review.

## Scope and output

The audio chain is:

```text
Task dict / JSONL → GenAudioOperator → selected audio model → WAV + meta.json
```

- Model implementations: `<REPO_PATH>/models/gen_audio/`
- Task and artifact handling: `<REPO_PATH>/operators/gen_audio/`
- Runner and batch execution: `<REPO_PATH>/pipeline/assets_gen/gen_audio/`
- Free smoke checks: `<REPO_PATH>/tests/harness/`
- Generated results: `<REPO_PATH>/test_data/outputs/<game_id>/<run_id>/assets/audio/<task_id>/`

Use `<REPO_PATH>/pipeline/common/paths.py` for output locations. Mechanics and UI belong in
that game's run directory, not in root-level `<REPO_PATH>/test_data/outputs/mechanic/` or
`<REPO_PATH>/test_data/outputs/ui/` directories.

## Plan before generating

For every audio task, record:

1. the game moment and source (player, enemy, world, UI, cinematic);
2. asset type: `dialogue` or `sound_effect`;
3. duration **required by the game code** that will play it (fire-rate interval,
   animation length, loop period), plus language/voice requirements, emotional
   delivery, distance, perspective, and any diegetic context;
4. style references, loudness/mixing intent, looping need, and acceptance
   criteria;
   licence/provenance.

Do not ask a generator to imitate a named living performer or use reference
recordings without the required rights. Never commit audio API keys or private
reference recordings.

## Backend selection

| Need | Preferred route | Notes |
|---|---|---|
| Character dialogue / TTS | Qwen3-TTS or Seed Audio | Choose a voice that is licensed and suitable for the game; record speaker configuration. |
| Fast cloud dialogue or SFX | Seed Audio 1.0 | One API supports both slots and outputs an offline WAV asset. |

Use a local/open backend when offline execution, privacy, reproducibility, or
budget requires it. Use a cloud backend when it is permitted and gives the
planned quality. Do not silently substitute one backend for another: report the
fallback and its implications.

**When generation is the chosen route, prefer the Seed Audio cloud backend** for
privacy, or a declined budget rules it out. It is paid, so before the first call
**pause and follow *Paid cloud backend* in
`<REPO_PATH>/agent_skills/asset_qa/README.md`**: send the purchase/API-key page
(<https://console.volcengine.com/speech/>), state the estimated cost for the
planned line and one-shot count including retakes, ask the user to buy access and
supply `SEED_AUDIO_API_KEY`, and wait for an explicit answer. Local Qwen3-TTS and


For **gunshots, thunder, rain, wind, footsteps, engine and impact sounds**, prefer
a real recording from the selected engine's audio library or a licence-checked
free library (CC0 / CC-BY) — existing libraries cover these well, and a recording
is more convincing than a generated approximation. Record source and licence, and
keep non-commercial material out of a product build. Generate only when nothing
suitable can be sourced or the sound is fictional (energy weapon, magic spell).

**Match the clip length to what the code needs**, then obtain or trim to it:

- Take the required length from the game code — fire-rate interval, animation
  length, loop period. For generated tasks, compare `requested_duration_sec`
  against the delivered `duration_sec` in `meta.json`.
- One-shots: no leading silence, and a tail shorter than the retrigger interval,
  or rapid fire turns to mush. Looping ambience: seamless wrap, no level jump.
- Trim or fade in the audio tool before import; never fix a wrong-length asset by
  cutting playback in gameplay code.

## Environment setup

### Local backend dependencies

For Qwen3-TTS, install `qwen-tts` as described in the

### Shared cloud API dependency

```bash
bash scripts/asset_env_setup/audio/cloud_api_install.sh
```



```bash
```


```bash
python pipeline/assets_gen/gen_audio/run.py \
  --only-audio-type sound_effect \
```

externally configured model cache; do not commit them to source control.

## Seed Audio 1.0 cloud backend

Seed Audio can occupy either existing slot without changing the task JSON:

- `audio_type=dialogue`: character speech;
- `audio_type=sound_effect`: one-shots, foley, and ambience.

It is synchronous at the pipeline boundary and creates an offline WAV asset.
The default China endpoint is
`https://openspeech.bytedance.com/api/v3/tts/create`.

### Credentials and optional configuration

```bash
export SEED_AUDIO_API_KEY=<your-volcengine-seed-audio-api-key>
export AAAGF_API_CACHE=test_data/outputs/_api_cache

# Optional:
export SEED_AUDIO_MODEL=seed-audio-1.0
export SEED_AUDIO_API_BASE=https://openspeech.bytedance.com
export SEED_AUDIO_SPEAKER_ID=<registered-seed-audio-speaker-resource-id>
export AAAGF_DIALOGUE_BACKEND=seed_audio
export AAAGF_SOUND_EFFECT_BACKEND=seed_audio
```

The task's Qwen-style `speaker_id` values (for example `Vivian`) are not sent
to Seed Audio. Use `SEED_AUDIO_SPEAKER_ID` for a registered Seed Audio speaker.
When `reference_audio_path` is supplied, its in-memory audio takes precedence
over that speaker id. Only use a reference recording when its rights permit the
intended use.

### Seed Audio commands

Generate dialogue:

```bash
python pipeline/assets_gen/gen_audio/run.py \
  --dialogue-backend seed_audio \
  --audio-type dialogue \
  --text "发现目标" \
  --task-id spotted_target
```

Generate a sound effect:

```bash
python pipeline/assets_gen/gen_audio/run.py \
  --sound-effect-backend seed_audio \
  --audio-type sound_effect \
  --prompt "a single close futuristic rifle shot, dry, no music" \
  --duration-sec 2 \
  --task-id rifle_shot
```

Generate both types from a JSONL batch:

```bash
python pipeline/assets_gen/gen_audio/run.py \
  --dialogue-backend seed_audio \
  --sound-effect-backend seed_audio \
  --game gameA_cyberpunk_shooter
```

## QA and validation

1. Run free checks before any paid cloud call:

   ```bash
   python tests/harness/smoke.py --kind audio --backend seed_audio
   python tests/test_api_audio.py
   ```

   The API contract test uses a fake HTTP client and consumes no credits.

2. Inspect the WAV before integration: no unintended music in a one-shot, no
   clipping, abrupt cut, dominant background noise, or unsuitable duration.
   Compare the delivered `duration_sec` against the length the game code needs,
   check that a one-shot has no dead leading silence, and that a loop wraps
   without a seam.
3. Integrate the asset in the target game and exercise the related action or
   scene. Check trigger timing, attenuation, looping, dialogue intelligibility,
   spatial placement, mix balance, and consistency with the requested style.
4. Capture a representative low-resolution gameplay video where audio capture
   is available; report any platform limitation if it is not.
5. Preserve provider/model, prompt or text, source/reference rights, backend
   configuration, cache status, and review result in the task metadata.

Do not claim success merely because a WAV exists. The asset is accepted only
when its in-game behavior and style meet the planned acceptance criteria.
