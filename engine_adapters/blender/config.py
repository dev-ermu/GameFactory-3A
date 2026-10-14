"""Configuration for the stable BlenderClient API.
稳定的BlenderClient API配置。

取值一律走 `config.settings`（项目唯一配置源），不再读 `os.environ`；
旧名回退链由 `Settings` 的 `validation_alias` 承担。
"""

import os
import shutil
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


def _text(value: object) -> str:
    """把 `settings` 字段值转成去空白字符串；`None` 与空值一律返回 `""`。"""
    return "" if value is None else str(value).strip()


def _optional_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if os.name == "nt" and path.is_absolute():
        return Path(os.path.abspath(str(path)))
    return path.resolve(strict=False)


@dataclass(frozen=True)
class BlenderClientConfig:
    """Resolved configuration used by BlenderClient and private code."""

    project_path: Path | None
    blender_root: Path | None
    api_version: str = DEFAULT_API_VERSION

    @classmethod
    def resolve(
        cls,
        project_path: str | Path | None = None,
        blender_root: str | Path | None = None,
        api_version: str = DEFAULT_API_VERSION,
    ) -> "BlenderClientConfig":
        version = str(api_version or "").strip()
        if version not in SUPPORTED_API_VERSIONS:
            supported = ", ".join(SUPPORTED_API_VERSIONS)
            raise ValueError(
                f"Unsupported BlenderClient api_version {version!r}; "
                f"supported versions: {supported}"
            )
        resolved_root = _optional_path(
            blender_root or _text(settings.blender_root)
        )
        resolved_project = _optional_path(
            project_path or _text(settings.blender_project)
        )
        return cls(
            project_path=resolved_project,
            blender_root=resolved_root,
            api_version=version,
        )

    @property
    def project_dir(self) -> Path | None:
        path = self.project_path
        if path is None:
            return None
        if path.suffix == ".py":
            return path.parent
        return path

    @property
    def project_file(self) -> Path | None:
        """Path to ``game.py``."""
        path = self.project_path
        if path is not None and path.suffix == ".py":
            return path if path.is_file() else None
        project_dir = self.project_dir
        if project_dir is None:
            return None
        candidate = project_dir / "game.py"
        return candidate if candidate.is_file() else None

    @property
    def blender_executable(self) -> Path | None:
        """Blender binary, or a Python with ``bpy``."""
        root = self.blender_root
        if root is not None:
            if root.is_file():
                return root
            nested = root / "blender"
            if nested.is_file():
                return nested
            nested_exe = root / "blender.exe"
            if nested_exe.is_file():
                return nested_exe
        on_path = shutil.which("blender")
        return Path(on_path).resolve(strict=False) if on_path else None
