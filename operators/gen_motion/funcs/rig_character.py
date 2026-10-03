"""Character rigging step: thin pass-through to an injected model."""

from typing import Any

# Keep in sync with retarget_utils.formats (minus .fbx — Puppeteer does not read it).
SUPPORTED_MESH_FORMATS = (".glb", ".gltf", ".obj", ".ply", ".stl")


def normalise_mesh_format(value: str) -> str:
    """Return a validated lower-case mesh extension with leading dot."""
    ext = str(value).lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    if ext not in SUPPORTED_MESH_FORMATS:
        raise ValueError(
            f"mesh_format must be one of {', '.join(SUPPORTED_MESH_FORMATS)}, "
            f"got {value!r}"
        )
    return ext


def rig_character(
    mesh: bytes,
    model: Any,
    *,
    mesh_format: str = ".glb",
    seed: int = 42,
    post_filter: bool = True,
) -> dict:
    """
    Predict skeleton + skin weights.

    Skin indices refer to the mesh handed to the model — do not reorder
    vertices between this step and retargeting.
    """
    if not isinstance(mesh, (bytes, bytearray)) or not mesh:
        raise ValueError("rig_character needs non-empty mesh file bytes.")

    artifacts = model.infer(
        bytes(mesh),
        mesh_format=normalise_mesh_format(mesh_format),
        seed=seed,
        post_filter=post_filter,
    )
    if not isinstance(artifacts, dict):
        raise RuntimeError(
            f"Rigging model returned {type(artifacts).__name__}, expected a dict."
        )
    missing = [
        key
        for key in ("rig_text", "skeleton_text", "mesh_obj_bytes")
        if not artifacts.get(key)
    ]
    if missing:
        raise RuntimeError(
            f"Rigging model missing {', '.join(missing)}; "
            f"keys present: {sorted(artifacts)}"
        )
    return artifacts


__all__ = [
    "SUPPORTED_MESH_FORMATS",
    "normalise_mesh_format",
    "rig_character",
]
