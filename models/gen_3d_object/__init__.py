"""
models/gen_3d_object/

Single-asset 3D generation backends. All of them satisfy the same slot in
`operators/gen_3d_object/operator.py`:

    infer_and_save(image, output_path, seed, decimation_target, texture_size) -> str

| class        | file             | kind                |
|--------------|------------------|---------------------|
| `TripoModel` | `tripo_model.py` | cloud API (Tripo3D) |
| `MeshyModel` | `meshy_model.py` | cloud API (Meshy)   |

Both are cloud APIs, so importing this package stays cheap: neither pulls in
`torch` nor any local checkpoint machinery.
"""

from .meshy_model import MeshyModel
from .tripo_model import TripoModel

__all__ = ["MeshyModel", "TripoModel"]
