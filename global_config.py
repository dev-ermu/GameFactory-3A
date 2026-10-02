"""
global_config.py

本项目的唯一配置读取模块。

把 `.env.example` 复制成仓库根目录的 `.env`，之后只改这一个文件。它提供云服务商的
凭证与 API 根地址、各任务槽位的后端选择，以及产物与缓存路径。

放在仓库顶层是因为 `models/` 不能 import `pipeline/`（model_require.md R1.1），而两层
都要读同一份配置。只依赖标准库，不 import 项目内任何模块。

用到的服务商，其 API 根地址是必填项，没有默认值：公开端点并非在所有网络下都可达，
静默回退只会在第一次计费调用时才暴露。模型侧由 `cloud_api.require_api_base()` 执行，
Pipeline 侧由本模块的 `require_cloud()` 执行。

本模块**只登记变量名**，不登记端点与注册页面：那两样由服务商维护、可能变更，
写死在代码里只会变成过期信息。用户从服务商控制台或文档取当前值填进 `.env`。

每个服务商需要两项：`*_API_BASE`、`*_API_KEY`；两项齐全才算配置完成
（`Provider.configured`），缺任何一项都会在 `require_cloud()` 里被列出。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

#: 仓库根目录 —— 本文件就放在这里，所以只需向上一级。
REPO_ROOT: Path = Path(__file__).resolve().parent

#: 用户唯一需要编辑的文件。
ENV_FILE: Path = REPO_ROOT / ".env"

#: 随仓库提交的模板。
ENV_EXAMPLE_FILE: Path = REPO_ROOT / ".env.example"


class ConfigError(RuntimeError):
    """必需配置项缺失或不可用。"""


# 服务商注册表
@dataclass(frozen=True)
class Provider:
    """一个闭源云服务商，以及配置它所需的变量。

    Attributes:
        key:               `require_cloud()` 使用的短标识。
        label:             用于提示信息的可读名称。
        env_base:          保存**必填** API 根地址的环境变量名。
        env_key:           保存 API Key 的环境变量名。
        env_models:        覆盖模型版本号的环境变量名。
        suggested_models:  上述变量对应的默认模型版本号。

    本类**只记录环境变量名**，不记录任何 URL 字面量：端点由服务商自行维护，域名
    和路径可能随时变更，写死在代码里只会变成过期信息。这些值统一由用户在 `.env`
    里填写；代码里出现 URL 的地方都应改为读取本表登记的变量名。

    `env_base` / `env_key` 两者都是**必填**：两者共同参与 `configured` 判定。这样
    缺配置会在 `require_cloud()` 里被一次性列出。
    """

    key: str
    label: str
    env_base: str
    env_key: str
    env_models: tuple[str, ...] = ()
    suggested_models: tuple[str, ...] = ()

    def base(self) -> str | None:
        value = os.environ.get(self.env_base, "").strip()
        return value or None

    def api_key(self) -> str | None:
        value = os.environ.get(self.env_key, "").strip()
        return value or None

    @property
    def configured(self) -> bool:
        """API 根地址与 Key 是否都已配置。"""
        return not self.missing()

    def missing(self) -> list[str]:
        """尚未配置的变量名列表。"""
        missing = []
        if not self.base():
            missing.append(self.env_base)
        if not self.api_key():
            missing.append(self.env_key)
        return missing


PROVIDERS: dict[str, Provider] = {
    # 3D 物体，首选
    "tripo": Provider(
        key="tripo",
        label="Tripo3D",
        env_base="TRIPO_API_BASE",
        env_key="TRIPO_API_KEY",
        env_models=("TRIPO_MODEL",),
        suggested_models=("v3.1-20260211",),
    ),
    # 3D 物体，备选（可直接产出 FBX / OBJ / USDZ）
    "meshy": Provider(
        key="meshy",
        label="Meshy",
        env_base="MESHY_API_BASE",
        env_key="MESHY_API_KEY",
        env_models=("MESHY_MODEL",),
        suggested_models=("meshy-6",),
    ),
    # 图像（Seedream）与视频（Seedance）共用一把 Key
    "ark": Provider(
        key="ark",
        label="Volcengine Ark (Seedream / Seedance)",
        env_base="ARK_API_BASE",
        env_key="ARK_API_KEY",
        env_models=("SEEDREAM_MODEL", "SEEDANCE_MODEL"),
        suggested_models=("doubao-seedream-5-0-260128",
                          "doubao-seedance-2-0-260128"),
    ),
    # 对白 + 音效
    "seed_audio": Provider(
        key="seed_audio",
        label="Seed Audio (Volcengine Speech)",
        env_base="SEED_AUDIO_API_BASE",
        env_key="SEED_AUDIO_API_KEY",
        env_models=("SEED_AUDIO_MODEL",),
        suggested_models=("seed-audio-1.0",),
    ),
    # 视频（Hailuo）
    "minimax": Provider(
        key="minimax",
        label="MiniMax (Hailuo)",
        env_base="MINIMAX_API_BASE",
        env_key="MINIMAX_API_KEY",
        env_models=("MINIMAX_VIDEO_MODEL",),
        suggested_models=("MiniMax-Hailuo-2.3",),
    ),
    # 云端绑骨 / 动画 / 格式转换（Tripo 系模型，经腾讯云网关）
    "tokenhub": Provider(
        key="tokenhub",
        label="Tencent Cloud TokenHub (Tripo rigging / animation)",
        env_base="TOKENHUB_API_BASE",
        env_key="TOKENHUB_API_KEY",
    ),
}

#: 各任务槽位选择后端的变量。集中在这里，使 `.env` 模板与诊断输出保持一致。
BACKEND_SWITCHES: dict[str, tuple[str, tuple[str, ...], str]] = {
    "3d_object": ("AAAGF_3D_BACKEND", ("trellis2", "tripo", "meshy"), "trellis2"),
    "tpose": ("TPOSE_GEN_BACKEND", ("qwen_edit", "seedream"), "qwen_edit"),
    "audio_dialogue": ("AAAGF_DIALOGUE_BACKEND", ("qwen3_tts", "seed_audio"),
                       "qwen3_tts"),
    "audio_sound_effect": ("AAAGF_SOUND_EFFECT_BACKEND", ("woosh", "seed_audio"),
                           "woosh"),
    "cg_video": ("GAMEFACTORY3A_VIDEO_BACKEND", ("seedance", "minimax-h3"),
                 "seedance"),
    "3d_scene": ("AAAGF_SCENE_BACKEND", ("worldmirror", "worldplay"),
                 "worldmirror"),
}


# .env 加载
_LOADED = False
_LOADED_VALUES: dict[str, str] = {}


def _expand(value: str, seen: dict[str, str]) -> str:
    """展开 `.env` 取值中的 ``${NAME}`` / ``${NAME:-默认值}``。

    查找顺序：**本文件中更靠前**定义的条目 → 进程环境变量。不支持前向引用——
    与其它 dotenv 实现一样，文件是自上而下解析的。
    """
    out = []
    i = 0
    while i < len(value):
        if value.startswith("${", i):
            end = value.find("}", i + 2)
            if end != -1:
                body = value[i + 2:end].strip()
                name, sep, fallback = body.partition(":-")
                resolved = seen.get(name) or os.environ.get(name) or ""
                if not resolved and sep:
                    resolved = fallback
                out.append(resolved)
                i = end + 1
                continue
        out.append(value[i])
        i += 1
    return "".join(out)


def parse_env_file(path: Path) -> dict[str, str]:
    """解析 dotenv 文件，只用标准库，不引入 `python-dotenv` 依赖。

    支持 ``NAME=value``、``export NAME=value``、以 `#` 开头的注释行、空行，以及
    取值两侧的单／双引号。**不**处理行内 ``#`` 注释，因为 API 端点里合法地含有 ``#``。
    """
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if not name or not name.replace("_", "").isalnum():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[name] = _expand(value, values)
    return values


def load(*, override: bool = True, verbose: bool | None = None) -> bool:
    """把 `<repo>/.env` 载入 `os.environ`。幂等。

    `.env` 被视为权威的唯一配置来源，因此默认会**覆盖**进程中已有的同名变量。
    每次覆盖都会提示（除非显式 `verbose=False`）。

    Returns:
        本次调用真的读取了文件时返回 True；已加载过或文件不存在时返回 False。
    """
    global _LOADED
    if _LOADED:
        return False
    _LOADED = True

    if not ENV_FILE.is_file():
        return False

    if verbose is None:
        verbose = sys.stderr.isatty()

    values = parse_env_file(ENV_FILE)
    if not values:
        return False

    for name, value in values.items():
        existing = os.environ.get(name)
        if existing is not None and existing != value and override and verbose:
            sys.stderr.write(
                f"[config] {name} in {ENV_FILE.name} overrides the environment "
                f"value\n"
            )
        if existing is not None and not override:
            continue
        os.environ[name] = value
        _LOADED_VALUES[name] = value
    return True


def loaded_values() -> dict[str, str]:
    """来自 `.env` 的条目（不含文件原文，可安全打印）。"""
    return dict(_LOADED_VALUES)


# 通用访问器
def get(name: str, default: str | None = None) -> str | None:
    """读取环境变量，可给默认值。空字符串视同未设置。"""
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def is_set(name: str) -> bool:
    """该环境变量是否已被显式赋了非空值。"""
    return bool(os.environ.get(name, "").strip())


def require(name: str, *, who: str = "3AGameFactory", hint: str | None = None) -> str:
    """取必需的环境变量，缺失时抛出带 `.env` 修复方法的 `ConfigError`。"""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    detail = f"\n  {hint}" if hint else ""
    raise ConfigError(
        f"{who} requires {name}, which is not configured.\n"
        f"  1. cp {ENV_EXAMPLE_FILE.name} {ENV_FILE.name}   "
        f"# at the repository root\n"
        f"  2. set {name}=<value> in {ENV_FILE.name}{detail}"
    )


# 云服务商校验
def require_cloud(*provider_keys: str, context: str | None = None) -> dict[str, tuple[str, str]]:
    """校验给定的每个服务商，其 API 根地址、Key 与控制台页面都已配置。

    Args:
        *provider_keys: `PROVIDERS` 的键。
        context:        正在配置什么，用于失败提示。

    Returns:
        ``{provider_key: (base_url, api_key)}``。

    Raises:
        ConfigError: 列出**真正缺失**的那些变量（已经填好的不再重复列出），以及
            该写进 `.env` 的具体内容。
    """
    resolved: dict[str, tuple[str, str]] = {}
    missing_lines: list[str] = []
    missing_names: list[str] = []
    unknown: list[str] = []

    for key in provider_keys:
        spec = PROVIDERS.get(key)
        if spec is None:
            unknown.append(key)
            continue
        unset = spec.missing()
        if unset:
            missing_names.extend(unset)
            missing_lines.extend(
                _template_lines(spec, only_missing=True).splitlines()
            )
            continue
        resolved[key] = (spec.base(), spec.api_key())  # type: ignore[arg-type]

    if unknown:
        raise ConfigError(
            f"unknown provider key(s) {unknown}; known: {sorted(PROVIDERS)}"
        )

    if missing_lines:
        who = f"{context} " if context else ""
        raise ConfigError(
            f"{who}needs cloud configuration, but these variables are unset:\n"
            + "\n".join(missing_lines)
            + f"\n\nPut them in {ENV_FILE} (copy {ENV_EXAMPLE_FILE.name} first)."
            + "".join(f"\n  - {note}" for note in _missing_notes(missing_names))
        )
    return resolved


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
        sys.stderr.write(f"\n[config] {exc}\n\n")
        raise SystemExit(exit_code) from exc
    if announce and resolved:
        labels = ", ".join(PROVIDERS[key].label for key in resolved)
        print(f"[config] ok  cloud configured: {labels}")
    return resolved


def _template_lines(spec: Provider, *, only_missing: bool = False) -> str:
    """生成某个服务商可以直接粘进 `.env` 的配置片段。

    Args:
        only_missing: 只输出**尚未配置**的变量。`require_cloud()` 用它，否则一条
            「以下变量未设置」的提示会把用户已经填好的项也列进去。

    这里**不给端点示例**：端点由服务商维护、可能变更，写死在代码里只会变成过期
    信息。当前值由用户从该服务商的控制台或文档取得。
    """
    missing = set(spec.missing()) if only_missing else None

    def wanted(name: str) -> bool:
        return missing is None or name in missing

    lines = [f"    # {spec.label}"]
    if wanted(spec.env_base):
        lines.append(f"    {spec.env_base}=<API base URL, required>")
    if wanted(spec.env_key):
        lines.append(f"    {spec.env_key}=<API key, required>")
    if not only_missing:
        # 模型版本号只是可选的默认值提示，缺失列表里不需要它们。
        for env_model, model in zip(spec.env_models, spec.suggested_models):
            lines.append(f"    # {env_model}={model}")
    return "\n".join(lines)


def cloud_env_template(provider_keys: list[str] | tuple[str, ...] | None = None) -> str:
    """可打印的 `.env` 片段；不传参数则给出全部服务商。"""
    keys = list(provider_keys) if provider_keys else list(PROVIDERS)
    blocks = []
    for key in keys:
        blocks.append(_template_lines(PROVIDERS[key]))
        blocks.append("")
    return "\n".join(blocks).rstrip()


# 共享路径
def output_root() -> Path:
    """产物根目录：`AAAGF_OUTPUT_ROOT`，默认 `<repo>/test_data/outputs`。"""
    override = os.environ.get("AAAGF_OUTPUT_ROOT", "").strip()
    return Path(override).expanduser() if override else REPO_ROOT / "test_data" / "outputs"


def api_cache_dir() -> str | None:
    """云 API 响应缓存目录；关闭缓存时返回 None。

    优先 `AAAGF_API_CACHE`；仍兼容旧名 `GAMEFACTORY3A_API_CACHE`，使既有配置继续可用。
    """
    for name in ("AAAGF_API_CACHE", "GAMEFACTORY3A_API_CACHE"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


# 诊断
def describe() -> dict[str, object]:
    """当前生效配置的机器可读快照（不含密钥明文）。"""
    providers = {}
    for key, spec in PROVIDERS.items():
        providers[key] = {
            "label": spec.label,
            "base_env": spec.env_base,
            "base": spec.base(),
            "base_configured": bool(spec.base()),
            "key_env": spec.env_key,
            "key_configured": bool(spec.api_key()),
            "configured": spec.configured,
        }
    switches = {}
    for slot, (env_name, choices, default) in BACKEND_SWITCHES.items():
        switches[slot] = {
            "env": env_name,
            "choices": list(choices),
            "default": default,
            "value": get(env_name, default),
            "explicit": is_set(env_name),
        }
    return {
        "repo_root": str(REPO_ROOT),
        "env_file": str(ENV_FILE),
        "env_file_exists": ENV_FILE.is_file(),
        "env_example_exists": ENV_EXAMPLE_FILE.is_file(),
        "loaded_from_env_file": sorted(_LOADED_VALUES),
        "output_root": str(output_root()),
        "api_cache": api_cache_dir(),
        "providers": providers,
        "backends": switches,
    }


# 在 import 时即完成加载是刻意为之：`pipeline/common/paths.py` 与
# `models/common/cloud_api.py` 都会 import 本模块，因此 `.env` 会在它们读取
# 任何一个变量之前进入 `os.environ`。
load()
