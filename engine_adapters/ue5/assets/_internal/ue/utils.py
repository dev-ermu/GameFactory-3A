"""Shared helpers for UE asset pipeline operations."""

import json
from pathlib import Path


def normalize_dest_path(dest_path: str, default: str) -> str:
    dest = (dest_path or default).strip().replace("\\", "/")
    if not dest:
        dest = default
    if not dest.startswith("/"):
        dest = f"/{dest}"
    dest = dest.rstrip("/") or "/Game"
    if dest != "/Game" and not dest.startswith("/Game/"):
        raise ValueError(f"UE 目标路径必须位于 /Game 下: {dest}")
    return dest


def validate_local_file(local_path: str, allowed_suffixes: tuple[str, ...]) -> str:
    path = Path(local_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"本地文件不存在: {path}")
    if not path.is_file():
        raise ValueError(f"不是文件路径: {path}")
    if path.suffix.lower() not in allowed_suffixes:
        allowed = ", ".join(allowed_suffixes)
        raise ValueError(f"不支持的文件类型 {path.suffix.lower()}，仅支持: {allowed}")
    return path.as_posix()


def format_ue_response(response: dict) -> str:
    return json.dumps(response, ensure_ascii=False, indent=2)
