"""Configuration for the stable GodotClient API."""

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# 仓库根入 sys.path：`config` 是顶层模块，因此适配器不必 import `pipeline/`
# 也能读到项目唯一的配置源（`model_require.md` R1.1）。
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import settings

SUPPORTED_API_VERSIONS = ("v1",)
DEFAULT_API_VERSION = "v1"
DEFAULT_RUNTIME_HOST = "127.0.0.1"
DEFAULT_RUNTIME_PORT = 30050
DEFAULT_WORLD_ID = "world_001"
DEFAULT_EDITOR_TIMEOUT = 300
DEFAULT_IMPORT_TIMEOUT = 300
DEFAULT_IMPORT_ROOT = "assets/imported"

#: 本适配器支持的最低 Godot 版本。`4.4` 是 `res://` 资源 UID 与
#: `--import` 行为稳定的起点；更低版本的导入产物布局不同，测试与运行都不可靠。
MINIMUM_GODOT_VERSION: tuple[int, int] = (4, 4)
DEFAULT_AVATAR_DEST = "assets/imported/avatars"
DEFAULT_MOTION_DEST = "assets/imported/motions"
DEFAULT_SCENE_DEST = "assets/imported/scenes"
DEFAULT_ENVIRONMENT_DEST = "assets/imported/environments"
DEFAULT_EFFECT_DEST = "assets/imported/effects"
DEFAULT_MATERIAL_DEST = "assets/imported/materials"
DEFAULT_TEXTURE_DEST = "assets/imported/textures"
DEFAULT_PROP_DEST = "assets/imported/props"
DEFAULT_WEAPON_DEST = "assets/imported/weapons"
DEFAULT_AUDIO_DEST = "assets/imported/audio"

GODOT_ASSET_TYPE_DEFAULT_DESTS = {
    "avatar": DEFAULT_AVATAR_DEST,
    "motion": DEFAULT_MOTION_DEST,
    "scene": DEFAULT_SCENE_DEST,
    "environment": DEFAULT_ENVIRONMENT_DEST,
    "effect": DEFAULT_EFFECT_DEST,
    "material": DEFAULT_MATERIAL_DEST,
    "texture": DEFAULT_TEXTURE_DEST,
    "prop": DEFAULT_PROP_DEST,
    "static_mesh": DEFAULT_PROP_DEST,
    "weapon": DEFAULT_WEAPON_DEST,
    "audio": DEFAULT_AUDIO_DEST,
}


def _text(value: object) -> str:
    """把 `settings` 字段值转成去空白字符串；`None` 与空值一律返回 `""`。

    取值一律走 `settings`（项目唯一配置源），**不再读 `os.environ`**：旧名回退链由
    `Settings.godot_*` 的 `validation_alias` 承担，测试改用
    `mock.patch.multiple(settings, godot_executable=...)` 注入。
    """
    return "" if value is None else str(value).strip()


def probe_godot_version(executable: str | Path) -> tuple[int, ...]:
    """运行 `<godot> --version` 并返回版本号元组，例如 ``(4, 7, 1)``。

    真实引擎那一层测试用它做闸门：拿不到版本号就抛错——那意味着
    `A3GAME_TEST_GODOT_EXECUTABLE` 指向的不是可用的 Godot，静默跳过等于没测。

    Args:
        executable: Godot 可执行文件路径。

    Returns:
        版本号的数字元组；只含前导数字段（`4.7.1.stable` -> ``(4, 7, 1)``）。

    Raises:
        RuntimeError: 探测失败或输出里没有版本号。
    """
    import re as _re
    import subprocess

    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(
            f"could not run {executable} --version: {exc}"
        ) from exc
    output = f"{completed.stdout}\n{completed.stderr}"
    match = _re.search(r"(\d+(?:\.\d+)*)", output)
    if not match:
        raise RuntimeError(
            f"{executable} --version produced no version number: {output!r}"
        )
    return tuple(int(part) for part in match.group(1).split("."))


def _optional_path(value: str | Path | None) -> Path | None:
    if value is None or not str(value).strip():
        return None
    path = Path(str(value).strip()).expanduser()
    if os.name == "nt" and path.is_absolute():
        return Path(os.path.abspath(str(path)))
    return path.resolve(strict=False)


def _unresolved_absolute_path(value: str | Path | None) -> Path | None:
    """Return an absolute path while retaining symbolic-link components."""

    if value is None or not str(value).strip():
        return None
    return Path(os.path.abspath(str(Path(str(value).strip()).expanduser())))


def normalize_godot_project_directory(
    value: str | Path | None,
    *,
    resolve: bool = True,
) -> Path | None:
    """Map a project directory or its ``project.godot`` marker to the root."""

    path = _unresolved_absolute_path(value)
    if path is None:
        return None
    project_dir = path.parent if path.name.lower() == "project.godot" else path
    return project_dir.resolve(strict=False) if resolve else project_dir


@dataclass(frozen=True)
class GodotClientConfig:
    """Resolved configuration used by GodotClient and private code."""

    project_path: Path | None
    godot_executable: Path | None
    api_version: str = DEFAULT_API_VERSION
    runtime_host: str = DEFAULT_RUNTIME_HOST
    runtime_port: int = DEFAULT_RUNTIME_PORT
    editor_timeout: int = DEFAULT_EDITOR_TIMEOUT
    import_timeout: int = DEFAULT_IMPORT_TIMEOUT
    project_path_input: Path | None = None

    @classmethod
    def resolve(
        cls,
        project_path: str | Path | None = None,
        godot_executable: str | Path | None = None,
        api_version: str = DEFAULT_API_VERSION,
        *,
        runtime_host: str | None = None,
        runtime_port: int | None = None,
        editor_timeout: int | None = None,
        import_timeout: int | None = None,
    ) -> GodotClientConfig:
        version = str(api_version or "").strip()
        if version not in SUPPORTED_API_VERSIONS:
            supported = ", ".join(SUPPORTED_API_VERSIONS)
            raise ValueError(
                f"Unsupported GodotClient api_version {version!r}; "
                f"supported versions: {supported}"
            )

        configured_project = project_path or _text(settings.godot_project)
        unresolved_project = _unresolved_absolute_path(configured_project)
        resolved_project = _optional_path(configured_project)
        resolved_executable = _unresolved_absolute_path(
            godot_executable or _text(settings.godot_executable)
        )
        resolved_host = (
            runtime_host or _text(settings.godot_runtime_host) or DEFAULT_RUNTIME_HOST
        )
        # 端口与超时在 `Settings` 里已有默认值（镜像本模块的 DEFAULT_* 常量）。
        # 注意用 `is None` 判定而不是 `or`：显式配的 `0` 是**合法输入**（随后由下面的
        # 范围检查报错），`or` 会把它当成「未配置」而悄悄换成默认值。
        resolved_port = runtime_port
        if resolved_port is None:
            configured_port = settings.godot_runtime_port
            resolved_port = (
                DEFAULT_RUNTIME_PORT if configured_port is None else int(configured_port)
            )
        if not 1 <= int(resolved_port) <= 65535:
            raise ValueError("Godot runtime UDP port must be between 1 and 65535")

        resolved_editor_timeout = editor_timeout
        if resolved_editor_timeout is None:
            configured_timeout = settings.godot_editor_timeout
            resolved_editor_timeout = (
                DEFAULT_EDITOR_TIMEOUT if configured_timeout is None
                else int(configured_timeout)
            )
        resolved_import_timeout = import_timeout
        if resolved_import_timeout is None:
            configured_timeout = settings.godot_import_timeout
            resolved_import_timeout = (
                DEFAULT_IMPORT_TIMEOUT if configured_timeout is None
                else int(configured_timeout)
            )
        if int(resolved_editor_timeout) <= 0:
            raise ValueError("editor_timeout must be greater than zero")
        if int(resolved_import_timeout) <= 0:
            raise ValueError("import_timeout must be greater than zero")

        return cls(
            project_path=resolved_project,
            godot_executable=resolved_executable,
            project_path_input=unresolved_project,
            api_version=version,
            runtime_host=str(resolved_host).strip() or DEFAULT_RUNTIME_HOST,
            runtime_port=int(resolved_port),
            editor_timeout=int(resolved_editor_timeout),
            import_timeout=int(resolved_import_timeout),
        )

    @property
    def project_dir(self) -> Path | None:
        path = self.project_path
        if path is None:
            return None
        input_path = self.project_path_input or path
        return path.parent if input_path.name.lower() == "project.godot" else path

    @property
    def project_file(self) -> Path | None:
        project_dir = self.project_dir
        return None if project_dir is None else project_dir / "project.godot"

    @property
    def project_dir_input(self) -> Path | None:
        """Original absolute project directory before resolving symbolic links."""

        path = self.project_path_input or self.project_path
        if path is None:
            return None
        return path.parent if path.name.lower() == "project.godot" else path

    @property
    def project_name(self) -> str:
        project_dir = self.project_dir
        return project_dir.name if project_dir is not None else ""

    @property
    def engine_version_hint(self) -> str:
        executable = self.godot_executable
        if executable is None:
            return ""
        match = re.search(r"(\d+\.\d+(?:\.\d+)?)", executable.name)
        return match.group(1) if match else ""

    @property
    def data_root(self) -> Path:
        configured = _text(settings.godot_data_root)
        if configured:
            unresolved = _unresolved_absolute_path(configured)
            if unresolved is not None:
                return unresolved
        project_dir = self.project_dir
        if project_dir is not None:
            return project_dir / ".a3game"
        return Path(__file__).resolve().parent / "_data"

    @property
    def artifact_registry_path(self) -> Path:
        configured = _text(settings.godot_artifact_registry)
        if configured:
            unresolved = _unresolved_absolute_path(configured)
            if unresolved is not None:
                return unresolved
        return self.data_root / "artifacts.json"

    @property
    def world_registry_root(self) -> Path:
        configured = _text(settings.godot_world_registry_root)
        if configured:
            unresolved = _unresolved_absolute_path(configured)
            if unresolved is not None:
                return unresolved
        return self.data_root / "worlds"
