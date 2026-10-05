"""Blender (`bpy`) adapters: asset import, headless preview, gameplay, runtime.

Motion retarget lives in ``operators.gen_motion.funcs.retarget_utils``
(driven by ``retarget_motion.py``), not in this package.

Blender（`bpy`）适配器：资产导入、无头预览、游戏玩法及运行时支持。

动作重定向功能位于`operators.gen_motion.funcs.retarget_utils`中（由 `retarget_motion.py` 驱动），并不属于本软件包。
"""

from .blender_client import BlenderClient

__all__ = ["BlenderClient"]
