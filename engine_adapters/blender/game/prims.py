"""
engine_adapters/blender/game/prims.py

Primitive meshes, shared between every object that uses them.

A level here is a few hundred boxes. Built with `bpy.ops.mesh.primitive_*` that
is a few hundred mesh datablocks, a few hundred operator calls and a context
dependency; built this way it is **one** datablock per shape, linked by however
many objects need it. Cycles instances the shared mesh, so an arena of 200
crates costs one crate's worth of geometry.

The consequence to remember: the meshes are shared, so deforming one deforms
every object that uses it. Everything in this package animates the *object*
(location / rotation / scale), never the mesh — which is also what makes the
simulation bakeable to keyframes.

Shapes are unit-sized and centred, except `BOX_GROUND` and `BAR`, whose origins
are deliberately off-centre:

    BOX        2 m cube, centred                 scale = half-extents
    BOX_GROUND 2 m cube, origin on its base      scale.z = height, sits on floor
    CYLINDER   r = 1, h = 2, along +Z, centred
    SPHERE     r = 1, centred
    CONE       r = 1 at base, h = 2, along +Z
    PLANE      2 x 2 in XY, centred
    BAR        1 x 1 in XY, origin at its LEFT edge — scale.x is a fill fraction
"""

from typing import Optional, Sequence

BOX = "box"
BOX_GROUND = "box_ground"
CYLINDER = "cylinder"
SPHERE = "sphere"
CONE = "cone"
PLANE = "plane"
BAR = "bar"

_MESH_PREFIX = "aaagf_unit_"


def _bpy():
    try:
        import bpy  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover - host-side import guard
        raise RuntimeError(
            "engine_adapters.blender.game.prims must run inside a bpy interpreter"
        ) from e
    return bpy


# ── Unit meshes ───────────────────────────────────────────────────────────────

def _build(kind: str):
    import bmesh  # noqa: PLC0415

    bpy = _bpy()
    bm = bmesh.new()

    if kind in (BOX, BOX_GROUND):
        bmesh.ops.create_cube(bm, size=2.0)
        if kind == BOX_GROUND:
            # Origin on the base: a wall of height h is then scale.z = h with no
            # z offset to work out, and nothing ever sinks halfway into the floor.
            bmesh.ops.translate(bm, verts=bm.verts, vec=(0.0, 0.0, 1.0))
    elif kind == CYLINDER:
        _cone(bmesh, bm, 1.0, 1.0, 2.0, 24)
    elif kind == CONE:
        _cone(bmesh, bm, 1.0, 0.0, 2.0, 20)
    elif kind == SPHERE:
        try:
            bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=1.0)
        except TypeError:  # pre-3.0 spelling
            bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, diameter=1.0)
    elif kind == PLANE:
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0)
    elif kind == BAR:
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
        bmesh.ops.translate(bm, verts=bm.verts, vec=(0.5, 0.0, 0.0))
    else:
        bm.free()
        raise ValueError(f"unknown primitive {kind!r}")

    mesh = bpy.data.meshes.new(_MESH_PREFIX + kind)
    bm.to_mesh(mesh)
    bm.free()

    if kind in (SPHERE, CYLINDER, CONE):
        for poly in mesh.polygons:
            poly.use_smooth = True
    return mesh


def _cone(bmesh, bm, radius1: float, radius2: float, depth: float, segments: int):
    """`create_cone` renamed its radius arguments; accept either spelling."""
    try:
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                              radius1=radius1, radius2=radius2, depth=depth)
    except TypeError:
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                              diameter1=radius1 * 2.0, diameter2=radius2 * 2.0,
                              depth=depth)


def unit(kind: str):
    """The shared mesh datablock for `kind`, built on first use."""
    bpy = _bpy()
    mesh = bpy.data.meshes.get(_MESH_PREFIX + kind)
    return mesh if mesh is not None else _build(kind)


# ── Collections ───────────────────────────────────────────────────────────────

def collection(name: str):
    """A scene collection called `name`, created and linked once."""
    bpy = _bpy()
    existing = bpy.data.collections.get(name)
    if existing is not None:
        return existing
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    return coll


# ── Objects ───────────────────────────────────────────────────────────────────

def spawn(
    kind: str,
    name: str,
    *,
    location: Sequence[float] = (0.0, 0.0, 0.0),
    rotation: Sequence[float] = (0.0, 0.0, 0.0),
    scale: Sequence[float] = (1.0, 1.0, 1.0),
    material=None,
    into: Optional[str] = None,
    parent=None,
    shadow: bool = True,
    visible: bool = True,
    collide: bool = True,
):
    """
    Link a new object using the shared `kind` mesh.

    `rotation` is in **radians** — this is the engine-side layer and everything
    that reaches it has already come through the degree-taking command API.

    `shadow=False` drops the object out of every secondary ray, which is what
    HUD elements and tracers want: they should light nothing and be lit by
    nothing.

    `collide=False` removes it from `scene.ray_cast` as well. This is not the
    same flag as visibility and the difference costs an afternoon: `hide_render`
    hides an object from the *camera* but leaves it in the view-layer depsgraph
    that ray casting queries, so a hidden HUD plane one metre in front of the
    lens silently blocks every shot the player fires. `hide_viewport` is the one
    that removes it from that depsgraph, and it does not affect rendering.
    """
    bpy = _bpy()
    obj = bpy.data.objects.new(name, unit(kind))
    obj.location = tuple(location)
    obj.rotation_euler = tuple(rotation)
    obj.scale = tuple(scale)

    if material is not None:
        _assign_object_material(obj, material)

    if not shadow:
        obj.visible_shadow = False
        obj.visible_diffuse = False
        obj.visible_glossy = False
        obj.visible_transmission = False
        obj.visible_volume_scatter = False

    if not visible:
        obj.hide_render = True

    if not collide:
        obj.hide_viewport = True

    target = collection(into) if into else bpy.context.scene.collection
    target.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def _assign_object_material(obj, material) -> None:
    """
    Put the material in an **object**-linked slot.

    The mesh is shared by design, so a mesh-linked material would repaint every
    object using that shape. Object-linked slots are per instance, which is what
    lets one cube mesh be a crate, a wall and a health bar in the same file.
    """
    if not obj.material_slots:
        obj.data.materials.append(None)
    slot = obj.material_slots[0]
    slot.link = "OBJECT"
    slot.material = material


def show(obj, on: bool) -> None:
    """
    Show or hide an object in **both** the video and the window.

    `hide_render` alone covers the render path only, so a pooled tracer toggled
    with it flickers correctly in the video and then sits permanently in the middle
    of the interactive window. Anything the rules switch during a tick goes through
    here rather than assigning `hide_render` directly.
    """
    obj.hide_render = not on
    obj.hide_viewport = not on


#: The name of the shared do-not-draw material, so the whole scene reuses one.
VEIL_MATERIAL = "aaagf_veil"


def veil(obj) -> None:
    """
    Stop drawing an object **without** taking it out of the ray cast.

    What a collider wants once a model stands over it: the rules keep casting
    against the shape they were written against, and the picture is the model.
    Neither obvious flag does this — `hide_render` leaves it drawn in the viewport
    that `--play` shows, and `hide_viewport` takes it out of the depsgraph
    `scene.ray_cast` queries, so every shot passes through the enemy.

    So the geometry stays and is made to carry no light. Ray casting reads
    triangles and ignores materials, so the collider still stops bullets.
    """
    from . import materials  # noqa: PLC0415 - avoids an import cycle at module load

    _assign_object_material(obj, materials.solid(VEIL_MATERIAL, (0.0, 0.0, 0.0),
                                                 alpha=0.0, roughness=1.0))
    obj.hide_render = True
    obj.visible_shadow = False
    obj.visible_diffuse = False
    obj.visible_glossy = False
    obj.visible_transmission = False
    obj.visible_volume_scatter = False


def ribbon(
    name: str,
    centre: Sequence[Sequence[float]],
    normal: Sequence[Sequence[float]],
    half_width: float,
    *,
    z: float = 0.0,
    material=None,
    into: Optional[str] = None,
    closed: bool = True,
):
    """
    One flat surface swept along a polyline — a road, a river, a walkway.

    The obvious way to build a road is a box per segment, and it produces
    z-fighting: consecutive boxes must overlap to avoid gaps on the outside of
    a curve, and two coplanar top faces at the same height stripe the whole
    track with flickering seams. A single quad strip has neither problem, and
    collapses a 150-object road into one mesh.

    `centre` and `normal` are same-length sequences of 2D points and unit
    normals; the surface spans `half_width` either side of the centre line.
    """
    import bmesh  # noqa: PLC0415

    bpy = _bpy()
    bm = bmesh.new()
    count = len(centre)
    rows = []
    for (cx, cy), (nx, ny) in zip(centre, normal):
        rows.append((
            bm.verts.new((cx + nx * half_width, cy + ny * half_width, z)),
            bm.verts.new((cx - nx * half_width, cy - ny * half_width, z)),
        ))

    span = count if closed else count - 1
    for i in range(span):
        a_left, a_right = rows[i]
        b_left, b_right = rows[(i + 1) % count]
        bm.faces.new((a_left, b_left, b_right, a_right))

    bm.normal_update()
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    if material is not None:
        mesh.materials.append(material)
    target = collection(into) if into else bpy.context.scene.collection
    target.objects.link(obj)
    return obj


def empty(name: str, *, location: Sequence[float] = (0.0, 0.0, 0.0),
          into: Optional[str] = None, parent=None, display: float = 0.2):
    """
    An unscaled transform to hang parts off.

    A character built from primitives needs one: parenting a head to a body that
    is scaled (0.4, 0.4, 0.8) inherits that scale and delivers a squashed head
    at the wrong height. An empty root keeps the parts' own scales meaning what
    they say, and gives the rules a single transform to move and topple.

    `display` is the size of the cross drawn for it. An empty never renders, but it
    does draw in the viewport, so one parented a few centimetres in front of a
    playing camera needs shrinking or it is a wireframe across the middle of the
    window that no render will ever show.
    """
    bpy = _bpy()
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_size = display
    obj.location = tuple(location)
    target = collection(into) if into else bpy.context.scene.collection
    target.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def stretch_between(obj, a: Sequence[float], b: Sequence[float],
                    radius: float = 0.03) -> float:
    """
    Lay a unit `CYLINDER` along the segment a -> b and return its length.

    Tracers, barrier rails and limbs are all "a cylinder between two points",
    and doing it by hand each time gets the axis wrong: the unit cylinder runs
    along **+Z** and is 2 m long, so the scale is half the distance, not the
    distance.
    """
    import mathutils  # noqa: PLC0415

    start = mathutils.Vector(a)
    end = mathutils.Vector(b)
    delta = end - start
    length = delta.length
    if length < 1e-6:
        obj.scale = (radius, radius, 1e-4)
        return 0.0
    obj.location = (start + end) * 0.5
    obj.rotation_euler = delta.to_track_quat("Z", "Y").to_euler()
    obj.scale = (radius, radius, length * 0.5)
    return length
