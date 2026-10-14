"""
models/gen_3d_object/

三维单体生成后端。它们都满足 `operators/gen_3d_object/operator.py` 中的
同一插槽契约：

    request_and_save(image, output_path, seed, decimation_target, texture_size) -> str

| 类            | 文件               | 说明                                    |
|---------------|--------------------|-----------------------------------------|
| `TripoModel`  | `tripo_model.py`   | Tripo3D 云 API，官方 SDK `tripo3d`       |
| `MeshyModel`  | `meshy_model.py`   | 占位实现，调用即报错（未在大陆备案）    |

导入本包不会引入 `torch` 或任何本地权重设施。
"""

from .meshy_model import MeshyModel
from .tripo_model import TripoModel

__all__ = ["MeshyModel", "TripoModel"]