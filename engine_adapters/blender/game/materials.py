"""
engine_adapters/blender/game/materials.py

Named, cached Principled materials.

Cached by name because a level built from primitives asks for the same six
materials a few hundred times, and a fresh datablock per request costs both
memory and render prep time. The name is the cache key, so asking for an
existing name returns the existing material and ignores the new parameters —
which is what a level builder wants and would be a trap in an asset pipeline.

Emission is a first-class argument rather than a separate shader: everything
readable in a dark headless render — HUD bars, tracers, checkpoint gates, hit
sparks — is emissive, and routing it through the Principled node keeps one
material type in the file.


命名并缓存后的Principled材质。

之所以按名称缓存，是因为由基础几何体构成的关卡会多次请求相同的六种材质；若每次请求都新建一个数据块，不仅会占用更多内存，还会延长渲染准备时间。名称作为缓存键，因此当请求已存在的名称时，会直接返回现有材质，而忽略新参数——这正是关卡构建器所期望的行为；若在资产管线中使用这种机制则会引发问题。

发光属性被当作一等参数处理，而非单独的着色器：在无头黑暗渲染场景下可见的所有元素——HUD进度条、轨迹线、检查点门、击中火花等——都属于发光物体；将其通过Principled节点处理，就能在文件中仅保留一种材质类型。
"""

from typing import Optional, Sequence

from . import assets

#: Input socket names on the Principled BSDF. Renamed in 4.0 ("Emission" became
#: "Emission Color"); this package targets 4.x and up, where these are stable.
_BASE_COLOR = "Base Color"
_EMISSION_COLOR = "Emission Color"
_EMISSION_STRENGTH = "Emission Strength"


def _bpy():
    try:
        import bpy  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover - host-side import guard
        raise RuntimeError(
            "engine_adapters.blender.game.materials must run inside a bpy "
            "interpreter (Blender --background, or a Python with the bpy wheel)"
        ) from e
    return bpy


def _rgba(color: Sequence[float], alpha: float = 1.0) -> tuple:
    if len(color) == 4:
        return tuple(color)
    r, g, b = color
    return (r, g, b, alpha)


def solid(
    name: str,
    color: Sequence[float],
    *,
    roughness: float = 0.6,
    metallic: float = 0.0,
    emission: Optional[Sequence[float]] = None,
    emission_strength: float = 0.0,
    alpha: float = 1.0,
):
    """
    Return (creating once) a Principled material called `name`.

    `emission` defaults to `color`, so `emission_strength=4` is enough to make
    anything glow in its own colour.
    """
    bpy = _bpy()
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:  # a node setup we did not build; leave it alone
        return mat

    bsdf.inputs[_BASE_COLOR].default_value = _rgba(color, alpha)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = alpha
    if alpha < 1.0:
        mat.blend_method = "BLEND"

    if emission_strength > 0.0:
        bsdf.inputs[_EMISSION_COLOR].default_value = _rgba(emission or color, 1.0)
        bsdf.inputs[_EMISSION_STRENGTH].default_value = emission_strength

    return mat


def glow(name: str, color: Sequence[float], strength: float = 6.0, alpha: float = 1.0):
    """A pure emitter — used for HUD, tracers and anything that must read in shadow."""
    return solid(name, color, roughness=1.0, emission=color,
                 emission_strength=strength, alpha=alpha)


#: Map suffix -> the Principled input it drives. Matches what
#: `scripts/fetch_polyhaven.py` writes, so a fetched surface needs no renaming.
TEXTURE_SUFFIXES = {"diff": _BASE_COLOR, "rough": "Roughness", "nor_gl": "Normal"}


def textured(
    name: str,
    directory,
    *,
    metres: float = 4.0,
    roughness: float = 1.0,
    normal_strength: float = 1.0,
    fallback: Sequence[float] = (0.5, 0.5, 0.5),
):
    """
    A PBR surface from a directory of maps, projected in **world metres**.

    Deliberately not UV mapped, for two reasons that both come from `prims`.
    The unit meshes are built with `bmesh` and carry no UV layer at all, and they
    are *shared* and scaled per object — so one set of UVs would be stretched by
    whatever each object's scale happens to be, and a 60 m ground plane and a
    1 m crate wearing the same material would show the texture at wildly
    different sizes.

    Feeding world position into a box projection sidesteps both: `metres` is the
    real-world size of one tile, so a road and the kerb beside it agree at the
    seam, and nothing has to be unwrapped. The cost is that the projection does
    not follow a curve — fine for asphalt or grass, wrong for anything with a
    direction in it, like arrows painted on a road.

    Maps are matched by the suffixes in `TEXTURE_SUFFIXES`; whatever is missing
    is simply not connected, and a directory with nothing in it falls back to a
    plain `solid()` so a missing download cannot fail a run.
    """
    bpy = _bpy()
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing

    resolved = assets.resolve(str(directory))
    found = _find_maps(resolved) if resolved is not None else {}
    if not found:
        print(f"[materials] no texture maps at {directory} — using a flat colour")
        return solid(name, fallback, roughness=roughness)

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        return mat
    bsdf.inputs["Roughness"].default_value = roughness

    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    geometry = nodes.new("ShaderNodeNewGeometry")
    mapping = nodes.new("ShaderNodeMapping")
    scale = 1.0 / max(1e-3, metres)
    mapping.inputs["Scale"].default_value = (scale, scale, scale)
    links.new(geometry.outputs["Position"], mapping.inputs["Vector"])

    for suffix, socket in TEXTURE_SUFFIXES.items():
        path = found.get(suffix)
        if path is None:
            continue
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = bpy.data.images.load(str(path), check_existing=True)
        # Box projection blends three planar samples by the shading normal, which
        # is what makes this work on a cube's sides as well as its top.
        texture.projection = "BOX"
        texture.projection_blend = 0.25
        links.new(mapping.outputs["Vector"], texture.inputs["Vector"])

        if socket == "Normal":
            texture.image.colorspace_settings.name = "Non-Color"
            normal_map = nodes.new("ShaderNodeNormalMap")
            normal_map.inputs["Strength"].default_value = normal_strength
            links.new(texture.outputs["Color"], normal_map.inputs["Color"])
            links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
        elif socket == "Roughness":
            texture.image.colorspace_settings.name = "Non-Color"
            links.new(texture.outputs["Color"], bsdf.inputs["Roughness"])
        else:
            links.new(texture.outputs["Color"], bsdf.inputs[socket])

    return mat


def surface(name: str, spec: Optional[dict], *, color: Sequence[float],
            roughness: float = 0.6, metres: float = 4.0):
    """
    The surface a spec asks for: a fetched PBR texture, or the flat colour.

    This is the one call a template should make for a large visible surface —
    ground, road, arena floor, walls. With no `surfaces` block in the spec a
    generated game looks exactly as it did before, which keeps the flat look as
    the reproducible default and makes texturing an opt-in per task.

    Spec shape::

        "surfaces": {
            "road":   {"texture": "/Library/textures/asphalt_pit_lane", "metres": 8},
            "ground": {"texture": "assets/textures/rocky_terrain", "metres": 12}
        }
    """
    if not spec or not spec.get("texture"):
        return solid(name, color, roughness=roughness)
    return textured(name, spec["texture"],
                    metres=float(spec.get("metres", metres)),
                    roughness=float(spec.get("roughness", 1.0)),
                    normal_strength=float(spec.get("normal_strength", 1.0)),
                    fallback=color)


def _find_maps(directory) -> dict:
    """
    Suffix -> file, for the maps present in `directory`.

    Matched on `_<suffix>_` rather than an exact filename because the resolution
    is part of what a fetch writes (`asphalt_pit_lane_diff_2k.jpg`), and the
    material should not care which resolution was pulled.
    """
    if not directory.is_dir():
        return {}
    found = {}
    for path in sorted(directory.iterdir()):
        for suffix in TEXTURE_SUFFIXES:
            if f"_{suffix}_" in path.name and suffix not in found:
                found[suffix] = path
    return found


def assign(obj, material) -> None:
    """Replace an object's material slots with exactly `material`."""
    obj.data.materials.clear()
    obj.data.materials.append(material)


# ── Shared palette ────────────────────────────────────────────────────────────
#
# One palette across all three genres, so a reviewer comparing two generated
# games is comparing the mechanics rather than the art direction.

PALETTE = {
    "concrete":  (0.22, 0.23, 0.26),
    "asphalt":   (0.09, 0.09, 0.11),
    "steel":     (0.45, 0.47, 0.52),
    "crate":     (0.36, 0.24, 0.13),
    "player":    (0.15, 0.55, 0.95),
    "enemy":     (0.85, 0.16, 0.20),
    "ally":      (0.20, 0.80, 0.45),
    "hazard":    (0.95, 0.62, 0.10),
    "neon_cyan": (0.10, 0.90, 0.95),
    "neon_pink": (0.95, 0.15, 0.65),
    "white":     (0.90, 0.90, 0.92),
    "black":     (0.02, 0.02, 0.03),
}


def palette(name: str, **kw):
    """`palette("enemy")` — a solid material in one of the shared colours."""
    return solid(f"pal_{name}", PALETTE[name], **kw)
