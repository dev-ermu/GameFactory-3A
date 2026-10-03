"""
models/gen_3d_object/trellis_2_model.py

Thin wrapper around TRELLIS.2 image-to-3D pipeline.
Handles model loading and inference only.
GLB export is also provided here for convenience.

Usage:
    from models.gen_3d_object.trellis_2_model import Trellis2Model
    model = Trellis2Model(model_path="path/to/TRELLIS.2-4B")
    glb = model.infer(image)        # PIL.Image → trimesh.Scene (GLB)
    glb.export("output.glb")
"""

import os
import sys
from pathlib import Path
from typing import Optional

from PIL import Image

# --- path setup: make trellis2 importable ------------------------------------
# NOTE: we deliberately do NOT put `o-voxel/` on sys.path, because that would
# shadow the pip-installed `o_voxel` package (which is the one that actually
# contains the compiled `_C.so`). We only need the pure-python `trellis2/`
# from the repo; `o_voxel` should always resolve to the installed package.
_UTILS_DIR = Path(__file__).parent / "trellis_utils" / "trellis_2_utils"
_utils_str = str(_UTILS_DIR)
if _utils_str not in sys.path:
    sys.path.insert(0, _utils_str)
# ------------------------------------------------------------------------------

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


class Trellis2Model:
    """
    Wraps Trellis2ImageTo3DPipeline for easy load + infer.

    Args:
        model_path (str): Local path or HuggingFace repo id to TRELLIS.2 weights.
        device (str): "cuda" or "cpu".
        pipeline_type (str): One of "512", "1024", "1024_cascade", "1536_cascade".
        low_vram (bool): Offload model components to CPU between sampling steps.
    """

    def __init__(
        self,
        model_path: str,
        device: str = "cuda",
        pipeline_type: str = "1024_cascade",
        low_vram: bool = True,
    ):
        # Fail fast with a clear message if the o-voxel C++ extension is missing.
        # (Otherwise the error gets swallowed inside pipeline loading and shows
        #  up as a confusing HuggingFace 401.)
        try:
            import o_voxel
            assert hasattr(o_voxel, "_C"), "o_voxel._C missing"
        except Exception as e:
            raise RuntimeError(
                "o-voxel C++ extension is not built. Please run:\n"
                "  cd models/gen_3d_object/trellis_utils/trellis_2_utils/o-voxel\n"
                "  pip install . --no-build-isolation\n"
                f"(original error: {e})"
            ) from e

        from trellis2.pipelines import Trellis2ImageTo3DPipeline

        self.device = device
        self.pipeline_type = pipeline_type

        self.model_path = model_path
        self._pipeline = Trellis2ImageTo3DPipeline.from_pretrained(model_path)
        self._pipeline.cuda() if device == "cuda" else self._pipeline.to(device)

    # --------------------------------------------------------------------------

    def infer(
        self,
        image: Image.Image,
        seed: int = 42,
        num_samples: int = 1,
        decimation_target: int = 1_000_000,
        texture_size: int = 4096,
        export_glb: bool = True,
    ) -> "trimesh.Scene | list":
        """
        Run image-to-3D inference and (optionally) return a trimesh GLB Scene.

        Args:
            image: Input PIL image.  Background is removed automatically if
                   the image has no alpha channel.
            seed:  Random seed for reproducibility.
            num_samples: Number of independent samples to generate (usually 1).
            decimation_target: Target face count for GLB mesh simplification.
            texture_size: PBR texture atlas resolution.
            export_glb: If True, convert output to trimesh.Scene (GLB-ready).
                        If False, return raw MeshWithVoxel objects.

        Returns:
            If export_glb=True: trimesh.Scene (call .export("out.glb"))
            If export_glb=False: list[MeshWithVoxel]
        """
        meshes = self._pipeline.run(
            image,
            num_samples=num_samples,
            seed=seed,
            pipeline_type=self.pipeline_type,
        )

        if not export_glb:
            return meshes

        import o_voxel

        mesh = meshes[0]
        mesh.simplify(16_777_216)  # nvdiffrast vertex limit

        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices,
            faces=mesh.faces,
            attr_volume=mesh.attrs,
            coords=mesh.coords,
            attr_layout=mesh.layout,
            voxel_size=mesh.voxel_size,
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=decimation_target,
            texture_size=texture_size,
            remesh=True,
            remesh_band=1,
            remesh_project=0,
            verbose=False,
        )
        return glb

    def infer_and_save(
        self,
        image: Image.Image,
        output_path: str,
        seed: int = 42,
        decimation_target: int = 1_000_000,
        texture_size: int = 4096,
    ) -> str:
        """Convenience: run inference and save the GLB to disk, return path."""
        glb = self.infer(
            image,
            seed=seed,
            decimation_target=decimation_target,
            texture_size=texture_size,
            export_glb=True,
        )
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        glb.export(str(out), extension_webp=False)
        return str(out)
