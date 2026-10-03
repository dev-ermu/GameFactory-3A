"""
engine_adapters/blender/runtime/assets/resolver.py

Turns the paths in a command into paths on this machine.

Commands are written once and sent to whatever runtime is listening, which may
not share a filesystem with their author. A `/Library/...` path is therefore
virtual — it resolves against a root this process is configured with, so one
command file works against a laptop and a render box. Anything else is literal.
"""

import os
from pathlib import Path

#: Environment variable holding the directory `/Library/...` resolves against.
ASSET_ROOT_ENV = "BLENDER_ASSET_ROOT"

#: Prefix that marks a path as virtual.
LIBRARY_PREFIX = "/Library/"

DEFAULT_ASSET_ROOT = "./assets"


def asset_root() -> Path:
    return Path(os.environ.get(ASSET_ROOT_ENV, DEFAULT_ASSET_ROOT))


def resolve(path: str) -> Path:
    """`/Library/Avatars/Robot.glb` -> `<asset root>/Avatars/Robot.glb`."""
    if path.startswith(LIBRARY_PREFIX):
        return asset_root() / path[len(LIBRARY_PREFIX):]
    return Path(path)
