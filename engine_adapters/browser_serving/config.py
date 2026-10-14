"""Configuration for browser serving and its local frontends.

取值一律走 `config.settings`（项目唯一配置源），不再读 `os.environ`；
旧名回退链由 `Settings` 的 `validation_alias` 承担。
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

# 仓库根入 sys.path：`config` 是顶层模块，因此适配器不必 import `pipeline/`
# 也能读到项目唯一的配置源（`model_require.md` R1.1）。
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import settings


def _text(value: object) -> str:
    """把 `settings` 字段值转成去空白字符串；`None` 与空值一律返回 `""`。"""
    return "" if value is None else str(value).strip()


def _optional_path(value: object) -> Path | None:
    """把路径类配置转成 `Path`；未配置或空值返回 `None`。"""
    text = _text(value)
    return Path(text).expanduser().resolve(strict=False) if text else None


@dataclass(frozen=True)
class BrowserServingConfig:
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 7870
    admin_host: str = "127.0.0.1"
    admin_port: int = 7860
    public_gateway_url: str = "http://127.0.0.1:7870"
    browser_play_dir: Path | None = None
    upload_game_id: str = "_browser_uploads"
    upload_run_id: str = "browser_uploads"
    default_engine: str = "ue5"
    ue_project: Path | None = None
    ue_root: Path | None = None
    ue_host: str = "127.0.0.1"
    ue_remote_port: int = 30010
    unity_project: Path | None = None
    unity_root: Path | None = None
    unity_host: str = "127.0.0.1"
    unity_port: int = 30010
    unity_webgl_build: Path | None = None
    godot_project: Path | None = None
    godot_executable: Path | None = None
    godot_host: str = "127.0.0.1"
    godot_runtime_port: int = 30050
    godot_auto_open_browser: bool = False
    runtime_host: str = "127.0.0.1"
    base_runtime_port: int = 31020
    pixel_host: str = "127.0.0.1"
    base_pixel_http_port: int = 18080
    base_pixel_streamer_port: int = 18888
    base_pixel_sfu_port: int = 18889
    session_port_stride: int = 10
    max_sessions: int = 8
    preview_map: str = ""
    render_offscreen: bool = True
    dry_run: bool = False
    pixel_use_frontend: bool = False
    cg_video_enabled: bool = True
    cg_video_allow_cloud: bool = False
    cg_video_prebuilt_only: bool = False
    pixel_start_timeout: float = 120.0
    cg_video_max_workers: int = 1

    @classmethod
    def from_settings(cls) -> "BrowserServingConfig":
        """按 `config.settings` 构造一份配置快照。"""
        gateway_port = int(settings.browser_gateway_port)

        public_url = _text(settings.browser_public_url) or (
            f"http://127.0.0.1:{gateway_port}"
        )

        runtime_host = (
            _text(settings.unity_runtime_host)
            or _text(settings.ue_runtime_host)
            or "127.0.0.1"
        )

        return cls(
            gateway_host=_text(settings.browser_gateway_host) or "127.0.0.1",
            gateway_port=gateway_port,
            admin_host=_text(settings.browser_admin_host) or "127.0.0.1",
            admin_port=int(settings.browser_admin_port),
            public_gateway_url=public_url.rstrip("/"),
            browser_play_dir=_optional_path(settings.browser_play_dir),
            upload_game_id=(
                _text(settings.browser_upload_game_id) or "_browser_uploads"
            ),
            upload_run_id=_text(settings.browser_upload_run_id) or "browser_uploads",
            default_engine=_text(settings.browser_engine) or "ue5",
            ue_project=_optional_path(settings.ue_project),
            ue_root=_optional_path(settings.ue_root),
            ue_host=_text(settings.ue_host) or "127.0.0.1",
            ue_remote_port=int(settings.ue_port),
            unity_project=_optional_path(settings.unity_project),
            unity_root=_optional_path(settings.unity_root),
            unity_host=_text(settings.unity_host) or "127.0.0.1",
            unity_port=int(settings.unity_port),
            unity_webgl_build=_optional_path(settings.unity_webgl_build),
            godot_project=_optional_path(settings.godot_project),
            godot_executable=_optional_path(settings.godot_executable),
            godot_host=_text(settings.godot_host) or "127.0.0.1",
            godot_runtime_port=int(settings.godot_runtime_port),
            godot_auto_open_browser=bool(settings.godot_auto_open_browser),
            runtime_host=runtime_host,
            base_runtime_port=int(settings.browser_base_runtime_port),
            pixel_host=_text(settings.browser_pixel_host) or "127.0.0.1",
            base_pixel_http_port=int(settings.browser_base_pixel_http_port),
            base_pixel_streamer_port=int(settings.browser_base_pixel_streamer_port),
            base_pixel_sfu_port=int(settings.browser_base_pixel_sfu_port),
            session_port_stride=int(settings.browser_session_port_stride),
            max_sessions=int(settings.browser_max_sessions),
            preview_map=_text(settings.browser_preview_map),
            render_offscreen=bool(settings.browser_render_offscreen),
            dry_run=bool(settings.browser_dry_run),
            pixel_use_frontend=bool(settings.browser_pixel_use_frontend),
            cg_video_enabled=bool(settings.browser_cg_video_enabled),
            cg_video_allow_cloud=bool(settings.browser_cg_video_allow_cloud),
            cg_video_prebuilt_only=bool(settings.browser_cg_video_prebuilt_only),
            pixel_start_timeout=float(settings.browser_pixel_start_timeout),
            cg_video_max_workers=int(settings.browser_cg_video_max_workers),
        )
