"""Build WorldFlexVFXBinder requests for action-attached Niagara effects."""

import json
from pathlib import Path
from typing import Any

from .vfx_functions import DEFAULT_SYSTEM_PATHS


def _object_path(asset_path: str) -> str:
    asset_name = asset_path.rsplit("/", 1)[-1]
    return asset_path if "." in asset_name else f"{asset_path}.{asset_name}"


def build_punch_fire_binding(
    animation_path: str,
    mesh_path: str,
    *,
    hand_bone: str = "RightHand",
    system_path: str = DEFAULT_SYSTEM_PATHS["fire"],
    speed_threshold: float = 400.0,
    min_duration: float = 0.12,
    scale: float = 0.45,
    remove_existing: bool = False,
) -> dict[str, Any]:
    """Create a 3A rule: attach timed fire during the fast punch window."""
    for label, value in (("animation_path", animation_path), ("mesh_path", mesh_path),
                         ("system_path", system_path)):
        if not value.startswith("/Game/"):
            raise ValueError(f"{label} must be an Unreal /Game/ asset path")
    if not hand_bone.strip():
        raise ValueError("hand_bone cannot be empty")
    if speed_threshold <= 0 or min_duration <= 0 or scale <= 0:
        raise ValueError("threshold, duration and scale must be positive")

    return {
        "version": 1,
        "track": "A3GameVFX",
        "remove_existing": remove_existing,
        "bindings": [{
            "anim": animation_path,
            "mesh": mesh_path,
            "rules": [{
                "rule": "speed_trail",
                "bone": hand_bone,
                "niagara": _object_path(system_path),
                "speed_threshold": speed_threshold,
                "min_duration": min_duration,
                "scale": [scale, scale, scale],
            }],
        }],
    }


def write_binding(path: str | Path, binding: dict[str, Any]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(binding, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination


def commandlet_arguments(
    rules_path: str | Path,
    report_path: str | Path,
    *,
    apply: bool = False,
    collect_curves: bool = True,
) -> list[str]:
    """Return arguments to append to UnrealEditor-Cmd.exe and the .uproject."""
    return [
        "-run=WorldFlexVFXBind",
        f"-Rules={Path(rules_path).resolve().as_posix()}",
        f"-Report={Path(report_path).resolve().as_posix()}",
        f"-Apply={str(apply).lower()}",
        f"-Curves={str(collect_curves).lower()}",
    ]
