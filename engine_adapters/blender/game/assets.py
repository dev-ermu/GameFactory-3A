"""
engine_adapters/blender/game/assets.py

Turning an asset reference in a spec into a path on this machine.

A generated game's spec has to be able to name an asset without naming a
filesystem: the same `spec.json` is read on the machine that generated it, on a
reviewer's laptop and in CI, and an absolute path pins it to the first of those.
Three forms are accepted, in the order a spec is likely to use them:

    /Library/hdris/city_night_2k.hdr    under the asset root (`BLENDER_ASSET_ROOT`)
    assets/textures/asphalt_01          relative to the repo, or to the cwd
    D:/refs/custom.hdr                  absolute, used as given

`/Library/` and `BLENDER_ASSET_ROOT` are the convention
`engine_adapters/blender/runtime/assets/resolver.py` already uses for the live
runtime; the same reference resolves the same way here, so an asset fetched once
is addressable from both.
"""

import os
import re
from pathlib import Path
from typing import NamedTuple, Optional, Sequence

LIBRARY_PREFIX = "/Library/"

#: Imported models are parked in this collection, excluded from the view layer.
#: One import per file, however many instances use it.
SOURCE_COLLECTION = "aaagf_asset_sources"

#: `.../engine_adapters/blender/game/assets.py` -> the repo. Derived from this
#: file rather than from `AAAGF_REPO_ROOT`, because it is always right and the
#: environment variable is only sometimes set.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def asset_root() -> Path:
    """Where `/Library/...` references live. `<repo>/assets` unless overridden."""
    return Path(os.environ.get("BLENDER_ASSET_ROOT") or (_REPO_ROOT / "assets"))


def resolve(reference: str) -> Optional[Path]:
    """
    The path a reference names, or None when nothing is there.

    Returning None rather than raising is deliberate: every caller of this is
    decorating a scene — a sky, a road surface — and a missing file should cost
    the run its looks, not its result. The callers say what they fell back to.
    """
    if not reference:
        return None

    if reference.startswith(LIBRARY_PREFIX):
        candidates = [asset_root() / reference[len(LIBRARY_PREFIX):]]
    else:
        path = Path(reference)
        candidates = [path] if path.is_absolute() else [_REPO_ROOT / path, path]

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


# ── Models ────────────────────────────────────────────────────────────────────

def _bpy():
    try:
        import bpy  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover - host-side import guard
        raise RuntimeError(
            "engine_adapters.blender.game.assets must run inside a bpy interpreter"
        ) from e
    return bpy


def source(reference: str):
    """
    Import a model file **once** and return the collection holding it.

    Cached by file, for the same reason `prims` shares its unit meshes: three
    cars from one glTF should cost one glTF. The imported objects are parked in a
    collection that is excluded from the view layer, so the source itself neither
    renders nor draws — only the instances of it do.

    Returns None when the file is missing or has no importer, so a caller can
    fall back to the primitives it would otherwise have built.
    """
    path = resolve(reference)
    if path is None:
        print(f"[assets] no model at {reference}")
        return None

    bpy = _bpy()
    name = f"aaagf_src_{path.stem}"
    existing = bpy.data.collections.get(name)
    if existing is not None:
        return existing

    from ..import_generated.import_mesh import import_file  # noqa: PLC0415

    before = set(bpy.data.objects.keys())
    try:
        imported = import_file(bpy, path)
    except Exception as exc:                                 # noqa: BLE001
        print(f"[assets] could not import {path.name}: {exc}")
        return None
    imported = imported or [bpy.data.objects[k] for k in bpy.data.objects.keys()
                            if k not in before]
    if not imported:
        print(f"[assets] {path.name} imported nothing")
        return None

    collection = bpy.data.collections.new(name)
    _parked(bpy).children.link(collection)
    for obj in imported:
        for holder in list(obj.users_collection):
            holder.objects.unlink(obj)
        collection.objects.link(obj)
    return collection


def _parked(bpy):
    """
    The excluded parent collection every imported source hangs under.

    Returning this and not `scene.collection` is the whole point: getting it wrong
    links every source at the scene root, so one copy of every prop, wall and
    character in the library stands **piled up at the world origin**. That does not
    read as a bug — it reads as a stray asset or a broken texture, until a camera
    happens to point at (0, 0, 0).

    Excluded via the view layer rather than hidden per object: an excluded
    collection is out of the depsgraph entirely, so it cannot render, draw or be
    hit by `scene.ray_cast`, while a collection *instance* of it still resolves.
    """
    scene = bpy.context.scene
    existing = bpy.data.collections.get(SOURCE_COLLECTION)
    if existing is None:
        existing = bpy.data.collections.new(SOURCE_COLLECTION)
        scene.collection.children.link(existing)
    layer = scene.view_layers[0].layer_collection.children.get(SOURCE_COLLECTION)
    if layer is not None:
        layer.exclude = True
    return existing


def bounds(collection) -> tuple:
    """`(low, high)` corners of everything in `collection`, in its own space."""
    lows = [float("inf")] * 3
    highs = [float("-inf")] * 3
    for obj in collection.objects:
        for corner in obj.bound_box:
            point = obj.matrix_world @ _vector(corner)
            for axis in range(3):
                lows[axis] = min(lows[axis], point[axis])
                highs[axis] = max(highs[axis], point[axis])
    if lows[0] == float("inf"):
        return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    return (tuple(lows), tuple(highs))


def size(collection) -> tuple:
    """The bounding box extent of everything in `collection`."""
    low, high = bounds(collection)
    return tuple(high[axis] - low[axis] for axis in range(3))


def footing(collection, anchor: str = "base") -> tuple:
    """
    The offset from a model's origin to the point it should be placed by:
    horizontally its centre, vertically whichever face `anchor` names.

    Needed because an origin is a modelling artifact, not a handle. Kit assets are
    built to tile on a grid, so theirs tend to sit on a **corner** of the tile —
    every one of Kenney's props measures the same (-0.35, 0.65) — and one authored
    inside a larger scene can be anywhere at all. Placing by the origin puts the
    geometry that far off the mark, multiplied by whatever the model was scaled by:
    a barrier normalised from 0.25 to 2 metres is scaled eight times, so a
    centimetres-long offset lands it metres away from the kerb it was aimed at.

    `anchor="base"` is the default because most props stand on something: a spec
    says a barrier is 2.4 m to the side of the track, meaning where it *lands*.
    `anchor="top"` is for the ones that are described by the surface they present —
    a floor tile or a platform slab, where what matters is the height you stand on
    and the thickness underneath is the model's business, not the caller's.
    """
    low, high = bounds(collection)
    return ((low[0] + high[0]) * 0.5, (low[1] + high[1]) * 0.5,
            high[2] if anchor == "top" else low[2])


def _vector(values):
    import mathutils  # noqa: PLC0415

    return mathutils.Vector(values)


def _anchored(collection, location: Sequence[float], rotation: Sequence[float],
              factor: Sequence[float], anchor: str) -> tuple:
    """
    Where to put the object so the *model* lands on `location`.

    The correction is scaled and then rotated, in that order, because it is
    measured in the model's own space and the transform it has to survive is the
    object's own scale and rotation. `factor` is per axis, so a model squashed to
    fit a box is still anchored by the face it ends up presenting.
    """
    if anchor == "origin":
        return tuple(location)

    measured = footing(collection, anchor)
    offset = _vector(tuple(measured[axis] * factor[axis] for axis in range(3)))
    offset.rotate(_euler(rotation))
    return tuple(location[axis] - offset[axis] for axis in range(3))


def _euler(rotation: Sequence[float]):
    import mathutils  # noqa: PLC0415

    return mathutils.Euler(tuple(rotation), "XYZ")


def _normalised_scale(collection, reference: str, length: Optional[float],
                      height: Optional[float], scale: float) -> float:
    """
    The uniform scale that makes a model the size a spec asked for, in metres.

    `length` measures the longest horizontal side and `height` the vertical one; a
    lamp post is described by its height and a car by its length, and quoting the
    wrong one of the two is how a post ends up as wide as a building.
    """
    if length is None and height is None:
        return scale
    extent = size(collection)
    wanted, measured = ((length, max(extent[0], extent[1])) if length is not None
                        else (height, extent[2]))
    if measured <= 1e-6:
        print(f"[assets] {reference} has no size to normalise; "
              f"scale left at {scale}")
        return scale
    return scale * (float(wanted) / measured)


def _fitted_scale(collection, reference: str, fit: Sequence[float]) -> tuple:
    """
    The per-axis scale that makes a model exactly `fit` metres in each direction.

    Deliberately **not** uniform, which is the one case where distorting a model
    is the right answer: a prop standing in for a collider the rules already cast
    against has to *be* that collider's size. Sized uniformly it is either smaller
    than its collider, and bullets stop in the air beside it, or larger, and they
    pass through its visible edge. Neither is fixable by choosing a nicer model,
    because the collider's proportions come out of the level's own random stream.

    So the crate is stretched and its bevels stretch with it, which on a box reads
    as a differently-sized box. Do not reach for this for anything whose shape
    carries meaning — a wheel, a figure, a barrel.
    """
    extent = size(collection)
    factors = []
    for axis in range(3):
        if extent[axis] <= 1e-6:
            print(f"[assets] {reference} is flat on axis {axis}; fit left at 1.0")
            factors.append(1.0)
        else:
            factors.append(float(fit[axis]) / extent[axis])
    return tuple(factors)


def instance(
    reference: str,
    name: str,
    *,
    parent=None,
    location: Sequence[float] = (0.0, 0.0, 0.0),
    rotation: Sequence[float] = (0.0, 0.0, 0.0),
    length: Optional[float] = None,
    height: Optional[float] = None,
    fit: Optional[Sequence[float]] = None,
    scale: float = 1.0,
    into: Optional[str] = None,
    anchor: str = "base",
):
    """
    An empty that instances a model's collection — the cheap way to reuse one.

    A collection instance is a single object holding a reference, so twenty of
    them cost twenty transforms rather than twenty copies of the mesh. It is also
    why this returns an empty and not the model: the rules move the empty, and
    the geometry follows.

    `length` and `height` normalise scale by a real-world measurement, so a spec
    can size an asset without knowing anything about how it was authored — a car
    is 4.2 m long whether it was modelled in metres, centimetres or arbitrary
    units. `fit=(x, y, z)` instead makes it exactly that box, per axis and
    therefore distorting: for a prop that has to match a collider, see
    `_fitted_scale`.

    Use `unpack` instead when a part of the model has to move on its own: an
    instance is one object holding a reference, and there is nothing inside it to
    animate.

    `location` is where the *model* goes, not where its origin goes — see
    `footing`. `anchor="top"` places it by its upper face instead, for a floor
    tile whose thickness the caller should not have to know; `anchor="origin"`
    places by the origin as authored.

    `rotation` is in radians, matching `prims`.
    """
    collection = source(reference)
    if collection is None:
        return None

    bpy = _bpy()
    obj = bpy.data.objects.new(name, None)
    obj.instance_type = "COLLECTION"
    obj.instance_collection = collection
    obj.empty_display_size = 0.01

    if fit is not None:
        factors = _fitted_scale(collection, reference, fit)
    else:
        uniform = _normalised_scale(collection, reference, length, height, scale)
        factors = (uniform, uniform, uniform)
    obj.scale = factors
    obj.rotation_euler = tuple(rotation)
    obj.location = _anchored(collection, location, rotation, factors, anchor)

    target = bpy.data.collections.get(into) if into else None
    (target or bpy.context.scene.collection).objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


class Unpacked(NamedTuple):
    """A model brought in as separate objects. `parts` is keyed by node name."""

    root: object
    parts: dict
    scale: float


#: Blender's answer to a name that is already taken: `body` then `body.001`.
_SUFFIXED = re.compile(r"\.\d{3}$")


def unpack(
    reference: str,
    name: str,
    *,
    parent=None,
    location: Sequence[float] = (0.0, 0.0, 0.0),
    rotation: Sequence[float] = (0.0, 0.0, 0.0),
    length: Optional[float] = None,
    height: Optional[float] = None,
    scale: float = 1.0,
    into: Optional[str] = None,
    anchor: str = "base",
) -> Optional[Unpacked]:
    """
    A model as individual objects under one empty, so its parts can be animated.

    The counterpart to `instance`, and the choice between them is whether anything
    inside has to move. A collection instance is a single object holding a
    reference — twenty of them cost twenty transforms, which is why props use it —
    but there is no wheel inside one to turn. Copying the objects gives something
    per-part addressable; the copies **share their mesh data**, so three cars from
    one file still cost one file's worth of geometry, and the extra outlay is a
    handful of object headers.

    The model's **own hierarchy is kept**, and that is not a detail. A car kit
    names five meshes side by side, so flattening them costs nothing and it is
    what this used to do; a character parents its arms and head to its torso, and
    flattening that reads every one of those local offsets against the wrong
    parent — a figure asked for at 1.8 m arrived at 1.33 m with its head inside its
    chest. Keeping the chain also hands the caller a rig for free: rotating the
    torso takes the arms and head with it, which is exactly the joint a lean or a
    punch turns about.

    The root empty carries the normalising scale and the rotation, so a part's own
    `rotation_euler` stays its own — no unpicking a parent's orientation to work
    out which way a wheel spins.

    Keys have Blender's `.001` de-duplication suffix stripped, so a lookup by node
    name keeps working once a second model in the same scene brings in its own
    `body`.

    `location` is where the model goes rather than where its origin goes, as in
    `instance`; for a vehicle that means centred on the transform the rules move,
    with its wheels on the ground.
    """
    collection = source(reference)
    if collection is None:
        return None

    bpy = _bpy()
    root = bpy.data.objects.new(name, None)
    root.empty_display_size = 0.01
    factor = _normalised_scale(collection, reference, length, height, scale)
    root.scale = (factor, factor, factor)
    root.rotation_euler = tuple(rotation)
    root.location = _anchored(collection, location, rotation,
                              (factor, factor, factor), anchor)

    target = bpy.data.collections.get(into) if into else None
    target = target or bpy.context.scene.collection
    target.objects.link(root)
    if parent is not None:
        root.parent = parent

    # Everything is copied, including the empties a glTF brings in for its scene
    # and node roots, because they are the joints the meshes hang off. They cost
    # an object header each and dropping them is what broke the offsets.
    copies = {}
    for original in collection.objects:
        obj = original.copy()          # shares mesh data with the source
        # glTF nodes arrive in quaternion mode, where `rotation_euler` is stored
        # and **ignored** — it reads back exactly as set and the object never
        # turns. Everything that drives a part writes Euler angles, so this is the
        # point of unpacking. Blender converts the existing rotation on the mode
        # change, so nothing authored is lost.
        obj.rotation_mode = "XYZ"
        target.objects.link(obj)
        copies[original.name] = obj

    for original in collection.objects:
        obj = copies[original.name]
        parent = original.parent
        obj.parent = copies[parent.name] if parent is not None else root
        # Carried over rather than left at identity: Blender stores the offset a
        # parenting was made at here, and the local matrix is only correct when
        # read against it.
        obj.matrix_parent_inverse = original.matrix_parent_inverse.copy()

    parts = {_SUFFIXED.sub("", original.name): copies[original.name]
             for original in collection.objects if original.type == "MESH"}
    if not parts:
        print(f"[assets] {reference} unpacked no meshes")
    return Unpacked(root, parts, factor)
