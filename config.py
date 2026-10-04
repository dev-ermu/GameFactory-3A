"""
config.py — 项目唯一配置源。

所有配置项集中在一个 `Settings` 实例。其它模块一律：

    from config import settings
    settings.godot_executable

**不要**再直接读 `os.environ`。`.env` 由 pydantic-settings 在构造时解析，优先级为
「构造参数 > 进程环境变量 > `.env` 文件」——因此进程环境变量压过 `.env` 是默认行为，
测试也可以用 `Settings(_env_file=None, ...)` 构造完全隔离的实例，或用
`monkeypatch.setattr(settings, "字段", 值)` 直接改属性。
"""

import os
import sys
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: 仓库根目录 —— 本文件就放在这里，所以只需向上一级。
REPO_ROOT: Path = Path(__file__).resolve().parent

#: 用户唯一需要编辑的文件。
ENV_FILE: Path = REPO_ROOT / ".env"

#: 随仓库提交的模板。
ENV_EXAMPLE_FILE: Path = REPO_ROOT / ".env.example"


class ConfigError(RuntimeError):
    """必需配置项缺失或不可用。"""


def _a(*names: str) -> AliasChoices:
    """旧名回退链：按顺序取第一个有值的别名。"""
    return AliasChoices(*names)


class Settings(BaseSettings):
    """整个项目的配置项。

    字段名即 `.env` 里的键（小写不敏感匹配）；命名空间不同的地方用
    `validation_alias` 显式声明，并保留旧名作为回退。
    """

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
        # 空字符串一律视为「未设置」。不这样的话 `GODOT_EXECUTABLE=` 会被解析成
        # `Path(".")`（当前目录），而适配器要的是「没配就去 PATH 里发现」。
        env_ignore_empty=True,
    )

    # 通用
    output_root: Path = Field(REPO_ROOT / "test_data" / "outputs", validation_alias="AAAGF_OUTPUT_ROOT")
    api_cache: str | None = Field(None, validation_alias=_a("AAAGF_API_CACHE", "GAMEFACTORY3A_API_CACHE"))

    # 任务槽位的后端开关
    backend_3d_object: str = Field("trellis2", validation_alias="AAAGF_3D_BACKEND")
    backend_tpose: str = Field("qwen_edit", validation_alias="TPOSE_GEN_BACKEND")
    backend_audio_dialogue: str = Field("qwen3_tts", validation_alias="AAAGF_DIALOGUE_BACKEND")
    backend_audio_sound_effect: str = Field("woosh", validation_alias="AAAGF_SOUND_EFFECT_BACKEND")
    backend_cg_video: str = Field("seedance", validation_alias="GAMEFACTORY3A_VIDEO_BACKEND")
    backend_3d_scene: str = Field("worldmirror", validation_alias="AAAGF_SCENE_BACKEND")

    # 云服务商凭证与模型名称
    tripo_api_base: str = ""
    tripo_api_key: str = ""
    tripo_model: str = "v3.1-20260211"
    meshy_api_base: str = ""
    meshy_api_key: str = ""
    meshy_model: str = "meshy-6"
    ark_api_base: str = ""
    ark_api_key: str = ""
    seedream_model: str = "doubao-seedream-5-0-260128"
    seedance_model: str = "doubao-seedance-2-0-260128"
    seed_audio_api_base: str = ""
    seed_audio_api_key: str = ""
    seed_audio_model: str = "seed-audio-1.0"
    seed_audio_speaker_id: str = ""
    minimax_api_base: str = ""
    minimax_api_key: str = ""
    minimax_video_model: str = "MiniMax-Hailuo-2.3"
    minimax_h3_runtime: str = "auto"
    tokenhub_api_base: str = ""
    tokenhub_api_key: str = ""

    # Godot 相关配置项
    godot_project: Path | None = Field(None, validation_alias="A3GAME_GODOT_PROJECT")
    godot_executable: Path = Field(validation_alias="A3GAME_GODOT_EXECUTABLE")
    godot_runtime_host: str = Field("127.0.0.1", validation_alias="A3GAME_GODOT_RUNTIME_HOST")
    godot_runtime_port: int = Field(30050, validation_alias="A3GAME_GODOT_RUNTIME_PORT")
    godot_editor_timeout: int = Field(300, validation_alias="A3GAME_GODOT_EDITOR_TIMEOUT")
    godot_import_timeout: int = Field(300, validation_alias="A3GAME_GODOT_IMPORT_TIMEOUT")
    godot_data_root: Path | None = Field(None, validation_alias="A3GAME_GODOT_DATA_ROOT")
    godot_artifact_registry: Path | None = Field(None, validation_alias="A3GAME_GODOT_ARTIFACT_REGISTRY")
    godot_world_registry_root: Path | None = Field(None, validation_alias="A3GAME_GODOT_WORLD_REGISTRY_ROOT")

    # UE5
    # 端口与 transport 的默认值镜像 `engine_adapters/ue5/config.py` 的 DEFAULT_* 常量。
    ue_project: Path | None = Field(None, validation_alias="A3GAME_UE_PROJECT")
    ue_root: Path | None = Field(None, validation_alias="A3GAME_UE_ROOT")
    ue_host: str = Field("127.0.0.1", validation_alias=_a("A3GAME_UE_HOST", "UE_HOST"))
    ue_port: int = Field(30010, validation_alias=_a("A3GAME_UE_PORT", "UE_PORT"))
    ue_runtime_host: str = Field("127.0.0.1", validation_alias="A3GAME_UE_RUNTIME_HOST")
    ue_runtime_port: int = Field(30020, validation_alias="A3GAME_UE_RUNTIME_PORT")
    ue_python_plugin_path: Path | None = Field(None, validation_alias="A3GAME_UE_PYTHON_PLUGIN_PATH")
    ue_python_transport: str = Field("remote_execution", validation_alias="A3GAME_UE_PYTHON_TRANSPORT")
    ue_data_root: Path | None = Field(None, validation_alias=_a("A3GAME_UE_DATA_ROOT", "A3GAME_DATA_ROOT"))
    ue_artifact_registry: Path | None = Field(None, validation_alias=_a("A3GAME_UE_ARTIFACT_REGISTRY", "A3GAME_ARTIFACT_REGISTRY"))
    ue_world_registry_root: Path | None = Field(None, validation_alias=_a("A3GAME_UE_WORLD_REGISTRY_ROOT", "A3GAME_WORLD_REGISTRY_ROOT"))

    # ── Unity 3D ──────────────────────────────────────────────────────────────
    # 端口默认值镜像 `engine_adapters/unity3d/config.py` 的 DEFAULT_* 常量。
    unity_project: Path | None = Field(None, validation_alias=_a("A3GAME_UNITY_PROJECT", "AAAGF_UNITY_PROJECT"))
    unity_root: Path | None = Field(None, validation_alias=_a("A3GAME_UNITY_ROOT", "AAAGF_UNITY"))
    unity_host: str = Field("127.0.0.1", validation_alias=_a("A3GAME_UNITY_HOST", "UNITY_HOST"))
    unity_port: int = Field(30010, validation_alias=_a("A3GAME_UNITY_PORT", "UNITY_PORT"))
    unity_runtime_host: str = Field("127.0.0.1", validation_alias="A3GAME_UNITY_RUNTIME_HOST")
    unity_runtime_port: int = Field(30030, validation_alias="A3GAME_UNITY_RUNTIME_PORT")
    unity_editor_timeout: int = Field(300, validation_alias="A3GAME_UNITY_EDITOR_TIMEOUT")
    unity_data_root: Path | None = Field(None, validation_alias=_a("A3GAME_UNITY_DATA_ROOT", "A3GAME_DATA_ROOT"))
    unity_artifact_registry: Path | None = Field(None, validation_alias=_a("A3GAME_UNITY_ARTIFACT_REGISTRY", "A3GAME_ARTIFACT_REGISTRY"))
    unity_world_registry_root: Path | None = Field(None, validation_alias=_a("A3GAME_UNITY_WORLD_REGISTRY_ROOT", "A3GAME_WORLD_REGISTRY_ROOT"))

    # ── Blender ───────────────────────────────────────────────────────────────
    blender_project: Path | None = Field(None, validation_alias="A3GAME_BLENDER_PROJECT")
    blender_root: Path | None = Field(None, validation_alias=_a("A3GAME_BLENDER_ROOT", "AAAGF_BLENDER"))

    # ── three.js ──────────────────────────────────────────────────────────────
    # 端口与 transport 镜像 `engine_adapters/three_js/config.py`；合法 transport
    # 是 `http` / `websocket`（`SUPPORTED_RUNTIME_TRANSPORTS`），不是 `ws`。
    three_project: Path | None = Field(None, validation_alias="A3GAME_THREE_PROJECT")
    three_root: Path | None = Field(None, validation_alias="A3GAME_THREE_ROOT")
    three_node_root: Path | None = Field(None, validation_alias="A3GAME_NODE_ROOT")
    three_package_manager: str = Field("npm", validation_alias="A3GAME_THREE_PACKAGE_MANAGER")
    three_host: str = Field("127.0.0.1", validation_alias=_a("A3GAME_THREE_HOST", "THREE_HOST"))
    three_port: int = Field(5173, validation_alias=_a("A3GAME_THREE_PORT", "THREE_PORT"))
    three_runtime_host: str = Field("127.0.0.1", validation_alias="A3GAME_THREE_RUNTIME_HOST")
    three_runtime_port: int = Field(30040, validation_alias="A3GAME_THREE_RUNTIME_PORT")
    three_runtime_transport: str = Field("http", validation_alias="A3GAME_THREE_RUNTIME_TRANSPORT")
    three_preview_root: Path | None = Field(None, validation_alias="A3GAME_THREE_PREVIEW_ROOT")
    three_data_root: Path | None = Field(None, validation_alias=_a("A3GAME_THREE_DATA_ROOT", "A3GAME_DATA_ROOT"))
    three_artifact_registry: Path | None = Field(None, validation_alias=_a("A3GAME_THREE_ARTIFACT_REGISTRY", "A3GAME_ARTIFACT_REGISTRY"))
    three_world_registry_root: Path | None = Field(None, validation_alias=_a("A3GAME_THREE_WORLD_REGISTRY_ROOT", "A3GAME_WORLD_REGISTRY_ROOT"))

    # ── 浏览器服务 ─────────────────────────────────────────────────────────────
    browser_engine: str = Field("godot", validation_alias="A3GAME_BROWSER_ENGINE")
    browser_admin_host: str = Field("127.0.0.1", validation_alias="A3GAME_BROWSER_ADMIN_HOST")
    browser_admin_port: int = Field(30100, validation_alias="A3GAME_BROWSER_ADMIN_PORT")
    browser_public_url: str = Field("", validation_alias="A3GAME_BROWSER_PUBLIC_URL")
    browser_gateway_host: str = Field("127.0.0.1", validation_alias="A3GAME_BROWSER_GATEWAY_HOST")
    browser_gateway_port: int = Field(30101, validation_alias="A3GAME_BROWSER_GATEWAY_PORT")
    browser_pixel_host: str = Field("127.0.0.1", validation_alias="A3GAME_BROWSER_PIXEL_HOST")
    browser_session_port_stride: int = Field(2, validation_alias="A3GAME_BROWSER_SESSION_PORT_STRIDE")
    browser_base_runtime_port: int = Field(30200, validation_alias="A3GAME_BROWSER_BASE_RUNTIME_PORT")
    browser_base_pixel_http_port: int = Field(30300, validation_alias="A3GAME_BROWSER_BASE_PIXEL_HTTP_PORT")
    browser_base_pixel_sfu_port: int = Field(30301, validation_alias="A3GAME_BROWSER_BASE_PIXEL_SFU_PORT")
    browser_base_pixel_streamer_port: int = Field(30302, validation_alias="A3GAME_BROWSER_BASE_PIXEL_STREAMER_PORT")
    browser_pixel_start_timeout: int = Field(30, validation_alias="A3GAME_BROWSER_PIXEL_START_TIMEOUT")
    browser_max_sessions: int = Field(8, validation_alias="A3GAME_BROWSER_MAX_SESSIONS")
    browser_cg_video_max_workers: int = Field(2, validation_alias="A3GAME_BROWSER_CG_VIDEO_MAX_WORKERS")
    browser_preview_map: str = Field("", validation_alias="A3GAME_BROWSER_PREVIEW_MAP")
    browser_upload_game_id: str = Field("", validation_alias="A3GAME_BROWSER_UPLOAD_GAME_ID")
    browser_upload_run_id: str = Field("", validation_alias="A3GAME_BROWSER_UPLOAD_RUN_ID")

    # 单元测试相关配置项。所有测试强制要求从项目根目录开始运行，保证工作路径是项目根目录。
    test_data_dir: str = "./tests/data"


#: 全局唯一实例。模块导入即完成 `.env` 解析。
settings = Settings()


# ── 字段名 → 环境变量名 ─────────────────────────────────────────────────────────
# 报错信息与 `.env` 片段要给人看**键名**，取值却一律走 `settings`。下表由
# `Settings.model_fields` 推导，不手写，避免两处漂移。
def _alias_of(name: str, field: Any) -> str:
    """字段的首选环境变量名；没有显式别名时就是字段名的大写形式。"""
    alias = field.validation_alias
    if alias is None:
        return name.upper()
    if isinstance(alias, str):
        return alias
    return str(getattr(alias, "choices", alias)[0])


#: `Settings` 字段名 -> `.env` 里的键名
FIELD_ENV_OF: dict[str, str] = {
    _name: _alias_of(_name, _field)
    for _name, _field in Settings.model_fields.items()
}


def _text(value: Any) -> str:
    """把字段值转成去空白字符串；`None` 与空值一律返回 `""`。"""
    if value is None:
        return ""
    if isinstance(value, Path):
        value = str(value)
    return str(value).strip()


# ── 云服务商的必需配置项 ───────────────────────────────────────────────────────
#: 服务商短标识 -> 报错里显示的可读名称。**只用于提示信息**，不参与取值。
CLOUD_LABELS: dict[str, str] = {
    "tripo": "Tripo3D",
    "meshy": "Meshy",
    "ark": "Volcengine Ark (Seedream / Seedance)",
    "seed_audio": "Seed Audio (Volcengine Speech)",
    "minimax": "MiniMax (Hailuo)",
    "tokenhub": "Tencent Cloud TokenHub (Tripo rigging / animation)",
}

#: 每个云服务商必需的字段后缀 -> `.env` 片段里的占位提示。
#: 端点必填而非带默认值：公开端点并非在所有网络下都可达，硬编码回退会一直表现得像
#: 「配置正常」，直到第一次计费调用失败。
_CLOUD_REQUIRED: tuple[tuple[str, str], ...] = (
    ("api_base", "<API base URL, required>"),
    ("api_key", "<API key, required>"),
)


def _cloud_fields(provider_key: str) -> tuple[str, ...]:
    """服务商短标识 -> 它必需的 `Settings` 字段名。

    命名规律固定为 `<key>_api_base` / `<key>_api_key`，所以**新增服务商只需在
    `Settings` 上加这两个字段**，本模块不用改——同一份配置事实只声明一次。
    """
    return tuple(f"{provider_key}_{suffix}" for suffix, _ in _CLOUD_REQUIRED)


def _env_name(field_name: str) -> str:
    """`Settings` 字段名 -> `.env` 里的键名。"""
    return FIELD_ENV_OF.get(field_name, field_name.upper())

# ── 兼容层：把配置发布到 os.environ ────────────────────────────────────────────
# 目标状态是「只有 settings 一个来源」。迁移尚未完成：`models/common/cloud_api.py`
# 与 `pipeline/common/paths.py` 在 import 时调用 `load()`，且 7 个
# `engine_adapters/*/config.py` 仍直读 `os.environ`。下面这个函数是过渡桥，
# 新代码不要调用它——直接读 `settings`。
_LOADED = False


def load(*, override: bool = False, verbose: bool | None = None) -> bool:
    """把 `settings` 里**显式配置过**的值发布到 `os.environ`——过渡桥，新代码不要调用。

    保留它是因为 `cloud_api` / `paths` 在 import 时调用，且引擎适配器尚未迁移。
    等所有适配器都改读 `settings` 之后，本函数连同 `_LOADED` 一并删除。

    只发布 `model_fields_set` 里的项，**不发布字段默认值**：适配器在用户未配置时
    应当沿用它自己的默认值，而不是被这里猜出来的默认值覆盖。

    Args:
        override: `True` 时用配置值覆盖进程里已有的变量。默认 `False`，即
            **进程环境变量优先**（与 python-dotenv 一致）——测试因此可以用
            `monkeypatch.setenv("X", "")` 隔离某一项，而不会被 `.env` 抢回去。
        verbose: 覆盖是否提示；默认在 stderr 是 tty 时提示。

    Returns:
        本次调用真的发布了变量时返回 True。
    """
    global _LOADED
    if _LOADED:
        return False
    _LOADED = True

    if verbose is None:
        verbose = sys.stderr.isatty()

    published = 0
    # 只发布**显式配置过**的项（`model_fields_set`），不发布字段默认值。
    # 否则本文件里的默认值会变成对适配器自身默认值的强制覆盖——适配器没被用户配置
    # 时应当沿用它自己的默认（例如 three.js 的 transport=http）。
    for field_name in settings.model_fields_set:
        name = FIELD_ENV_OF.get(field_name)
        if name is None:
            continue
        value = _text(getattr(settings, field_name))
        if not value:
            continue
        existing = os.environ.get(name)
        if existing is not None and existing != value and verbose and override:
            sys.stderr.write(f"[config] {name} in .env overrides the environment value\n")
        if existing is not None and not override:
            continue
        os.environ[name] = value
        published += 1
    return published > 0


def _missing_notes(missing_names: list[str]) -> list[str]:
    """按**实际缺失的类别**给提示，避免在只缺 Key 时大谈端点。"""
    suffixes: tuple[tuple[str, str], ...] = (
        (
            "_API_BASE",
            "An API base URL is required, never defaulted: it is not recorded in "
            "code because providers change endpoints — take the current value "
            "from the provider's console.",
        ),
        (
            "_API_KEY",
            "API keys are secrets: keep them in .env and never commit them, and "
            "never put one in a task file, log line or cache key.",
        ),
    )
    return [
        note for suffix, note in suffixes
        if any(name.endswith(suffix) for name in missing_names)
    ]


def require_cloud(*provider_keys: str, context: str | None = None) -> dict[str, tuple[str, str]]:
    """校验若干云服务商已配置，缺失时抛 :class:`ConfigError`。

    必需项由 `Settings` 的字段名推导（见 `_cloud_fields`），不再另设注册表——同一份
    配置事实只在 `Settings` 上声明一次。片段里**不给端点示例**：端点由服务商维护、
    可能变更，写死在代码里只会变成过期信息；当前值由用户从控制台或文档取得。

    Returns:
        ``{provider_key: (api_base, api_key)}``；值只用于回显，绝不写进日志。
    """
    resolved: dict[str, tuple[str, str]] = {}
    missing: list[str] = []
    for key in provider_keys:
        if key not in CLOUD_LABELS:
            raise ConfigError(
                f"Unknown cloud provider {key!r}; known: {sorted(CLOUD_LABELS)}"
            )
        absent = [f for f in _cloud_fields(key) if not _text(getattr(settings, f, ""))]
        if absent:
            missing.extend(_env_name(f) for f in absent)
        else:
            base, api_key = _cloud_fields(key)
            resolved[key] = (
                _text(getattr(settings, base)),
                _text(getattr(settings, api_key)),
            )
    if not missing:
        return resolved

    where = f" for {context}" if context else ""
    absent_names = set(missing)
    blocks: list[str] = []
    for key in provider_keys:
        rows = [
            f"    {_env_name(f)}={placeholder}"
            for f, (_, placeholder) in zip(_cloud_fields(key), _CLOUD_REQUIRED)
            if _env_name(f) in absent_names
        ]
        if rows:
            blocks.append(f"    # {CLOUD_LABELS[key]}")
            blocks.extend(rows)
    message = "\n".join([
        f"Missing cloud configuration{where}:",
        *(f"  - {name}" for name in dict.fromkeys(missing)),
        "",
        f"Add them to {ENV_FILE} (template: {ENV_EXAMPLE_FILE.name}):",
        *blocks,
    ])
    notes = _missing_notes(missing)
    if notes:
        message = f"{message}\n" + "\n".join(f"  {note}" for note in notes)
    raise ConfigError(message)


def require_cloud_or_exit(
    provider_keys: tuple[str, ...] | list[str],
    *,
    context: str | None = None,
    exit_code: int = 2,
    announce: bool = True,
) -> dict[str, tuple[str, str]]:
    """给 CLI runner 用的 `require_cloud()`：打印干净的错误块后退出。

    退出码默认 2，与「本地算力不足」的退出码 3 区分开。
    """
    try:
        resolved = require_cloud(*provider_keys, context=context)
    except ConfigError as exc:
        if announce:
            sys.stderr.write(f"{exc}\n")
        raise SystemExit(exit_code) from exc
    if announce:
        names = ", ".join(provider_keys)
        sys.stderr.write(f"[config] cloud backend ready: {names}\n")
    return resolved


# ── 常用派生值 ─────────────────────────────────────────────────────────────────
def api_cache_dir() -> str | None:
    """云 API 响应缓存目录；关闭缓存时返回 None（`AAAGF_API_CACHE`）。"""
    return settings.api_cache or None

