"""
engine_adapters/blender/runtime/assets/resolver.py

Turns the paths in a command into paths on this machine.

Commands are written once and sent to whatever runtime is listening, which may
not share a filesystem with their author. A `/Library/...` path is therefore
virtual — it resolves against a root this process is configured with, so one
command file works against a laptop and a render box. Anything else is literal.

该函数用于将命令中的路径转换为当前机器上的实际路径。

命令只需编写一次即可发送给任何正在监听的运行环境，而这些运行环境可能与命令编写者所使用的文件系统并不相同。因此，`/Library/...` 这类路径属于虚拟路径——它们会基于该进程所配置的根目录进行解析，如此一来，同一个命令文件就能在笔记本电脑和渲染服务器上正常运行。其他路径则会被直接视为字面意义上的路径。

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
