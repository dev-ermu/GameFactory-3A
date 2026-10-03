"""
models/gen_3d_object/

Single-asset 3D generation backends. All of them satisfy the same slot in
`operators/gen_3d_object/operator.py`:

    infer_and_save(image, output_path, seed, decimation_target, texture_size) -> str

| class          | file                 | kind                        |
|----------------|----------------------|-----------------------------|
| `Trellis2Model`| `trellis_2_model.py` | local weights, GPU          |
| `TripoModel`   | `tripo_model.py`     | cloud API (Tripo3D)         |
| `MeshyModel`   | `meshy_model.py`     | cloud API (Meshy)           |

The cloud wrappers import nothing heavier than the stdlib at module level, so
importing this package stays cheap. `Trellis2Model` is resolved lazily because
importing it manipulates `sys.path` for the vendored TRELLIS.2 tree.
"""

from typing import Any

from .meshy_model import MeshyModel
from .tripo_model import TripoModel

__all__ = ["MeshyModel", "TripoModel", "Trellis2Model"]


def __getattr__(name: str) -> Any:
    """Lazy re-export of the local-weight backend (PEP 562)."""
    if name == "Trellis2Model":
        from .trellis_2_model import Trellis2Model
        return Trellis2Model
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
