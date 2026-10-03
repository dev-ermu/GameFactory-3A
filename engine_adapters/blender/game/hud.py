"""
engine_adapters/blender/game/hud.py

A screen-space HUD made of geometry parented to the camera.

There is no viewport to draw an overlay into — the whole point of this package
is that it runs headless — so the HUD is real objects sitting a metre in front
of the lens. Parenting them to the camera makes them screen-space for free, and
because they are objects their state is *keyframeable*: a health bar that
shrinks is `scale.x`, which the recorder bakes like any other animation. An
overlay drawn at render time could not be baked, and the `.blend` a reviewer
opens would have no HUD in it.

Anchors are in normalized screen coordinates, `(-1, -1)` bottom-left to
`(1, 1)` top-right, converted here using the camera's own lens and the render
aspect so a bar stays in its corner whatever the resolution.

Everything here is emissive and dropped out of secondary rays: the HUD must
light nothing, cast nothing, and stay readable in an unlit corner of a level.

Why the HUD is left in the ray-cast depsgraph
---------------------------------------------
It used to be spawned with `collide=False`, which `prims` implements as
`hide_viewport` — correct for the shooting, since a plane 30 cm in front of the
lens would stop every bullet, but it also removed the HUD from the **window**. So
every generated game had a HUD in its video and none while being played.

There is no "drawn but not cast" flag, so the exclusion moved to the caster: a
mechanic passes `kernel.cast` the colliders it built, and everything else is
transparent to a ray by construction. A mechanic that casts *without* that set
will find the HUD in front of its muzzle.
"""

from typing import Optional, Sequence

from . import materials, prims

#: Blender's default sensor width, in mm. Camera FOV is derived from it.
SENSOR_MM = 36.0

#: How far in front of the lens the HUD plane sits.
#:
#: Held deliberately close — beyond `make_camera`'s 0.05 clip start, but nearer
#: than anything a game is likely to parent to the camera. A first-person
#: viewmodel is also camera-parented, and at the metre this used to sit at the
#: gun rendered *in front of* the ammo counter and covered it. Widget sizes are
#: derived from this distance and the lens, so moving the plane does not move
#: anything on screen.
HUD_DISTANCE = 0.3


class Hud:
    """
    Screen-space widgets on one camera.

    Args:
        camera: the camera object to parent to.
        resolution: `(x, y)` in pixels — sets the aspect used for anchoring.
        distance: metres in front of the lens.
    """

    def __init__(self, camera, resolution: Sequence[int], distance: float = HUD_DISTANCE):
        self.camera = camera
        self.distance = distance
        self.widgets: list = []

        # Half-extents of the HUD plane, from the camera's own field of view.
        self.half_w = distance * (SENSOR_MM * 0.5) / camera.data.lens
        self.half_h = self.half_w * (resolution[1] / resolution[0])

    # ── placement ─────────────────────────────────────────────────────────────

    def _local(self, anchor: Sequence[float], offset: Sequence[float] = (0.0, 0.0)) -> tuple:
        """Normalized screen anchor -> camera-local metres."""
        return (
            anchor[0] * self.half_w + offset[0],
            anchor[1] * self.half_h + offset[1],
            -self.distance,
        )

    def _attach(self, obj) -> None:
        obj.parent = self.camera
        obj.matrix_parent_inverse.identity()

    # ── widgets ───────────────────────────────────────────────────────────────

    def bar(
        self,
        name: str,
        anchor: Sequence[float],
        *,
        width: float = 0.5,
        height: float = 0.045,
        color: Sequence[float] = (0.2, 0.9, 0.3),
        backing: Sequence[float] = (0.03, 0.03, 0.04),
        offset: Sequence[float] = (0.0, 0.0),
        grow_left: bool = False,
    ) -> "Bar":
        """
        A left-anchored fill bar with a dark backing plate.

        `width` and `height` are fractions of the half-extents, so a bar keeps
        its proportions at any resolution. `grow_left` mirrors it, for the
        right-hand fighter's health.
        """
        w = width * self.half_w
        h = height * self.half_h
        x, y, z = self._local(anchor, offset)
        sign = -1.0 if grow_left else 1.0

        plate = prims.spawn(
            prims.BAR, f"hud_{name}_plate",
            location=(x, y, z),
            scale=(sign * w, h, 1.0),
            material=materials.glow(f"hud_{name}_plate_mat", backing, strength=0.35),
            into="HUD", shadow=False,
        )
        fill = prims.spawn(
            prims.BAR, f"hud_{name}_fill",
            location=(x, y, z + 0.004),
            scale=(sign * w, h * 0.72, 1.0),
            # Strength 1.0, not more. The render clips rather than rolls off, so
            # a fill above 1 loses its two dimmest channels and every bar on
            # screen converges on white — which is exactly the information a
            # coloured bar exists to carry.
            material=materials.glow(f"hud_{name}_fill_mat", color, strength=1.0),
            into="HUD", shadow=False,
        )
        for obj in (plate, fill):
            self._attach(obj)

        widget = Bar(fill, base_x=sign * w)
        self.widgets.append(widget)
        return widget

    def pip_row(
        self,
        name: str,
        anchor: Sequence[float],
        count: int,
        *,
        size: float = 0.022,
        gap: float = 0.055,
        color: Sequence[float] = (0.95, 0.8, 0.2),
        offset: Sequence[float] = (0.0, 0.0),
    ) -> "PipRow":
        """
        A row of discrete lamps — ammo, lives, laps, rounds won.

        Discrete state reads better as pips than as a bar, and toggling
        visibility bakes to a step curve, which is exactly right for a
        counter that should never appear half-lit.
        """
        x, y, z = self._local(anchor, offset)
        s = size * self.half_h
        step = gap * self.half_w
        material = materials.glow(f"hud_{name}_pip_mat", color, strength=1.0)

        pips = []
        for i in range(count):
            pip = prims.spawn(
                prims.PLANE, f"hud_{name}_pip{i:02d}",
                location=(x + i * step, y, z),
                scale=(s * 0.45, s * 1.6, 1.0),
                material=material, into="HUD", shadow=False,
            )
            self._attach(pip)
            pips.append(pip)

        widget = PipRow(pips)
        self.widgets.append(widget)
        return widget

    def label(
        self,
        name: str,
        text: str,
        anchor: Sequence[float],
        *,
        size: float = 0.07,
        color: Sequence[float] = (0.9, 0.92, 0.95),
        offset: Sequence[float] = (0.0, 0.0),
        align: str = "LEFT",
    ):
        """
        Static text. The body never changes — every varying quantity on screen
        is a bar or a row of pips, because a text body cannot be keyframed and
        a per-frame rebuild would not survive the bake.
        """
        import bpy  # noqa: PLC0415

        curve = bpy.data.curves.new(f"hud_{name}_text", type="FONT")
        curve.body = text
        curve.align_x = align
        curve.align_y = "CENTER"
        obj = bpy.data.objects.new(f"hud_{name}_text", curve)
        prims.collection("HUD").objects.link(obj)

        x, y, z = self._local(anchor, offset)
        s = size * self.half_h
        obj.location = (x, y, z)
        obj.scale = (s, s, s)
        obj.visible_shadow = False
        obj.visible_diffuse = False
        obj.visible_glossy = False
        materials.assign(obj, materials.glow(f"hud_{name}_text_mat", color, strength=1.0))
        self._attach(obj)
        return obj

    def crosshair(
        self,
        name: str = "cross",
        *,
        gap: float = 0.020,
        arm: float = 0.014,
        thickness: float = 0.004,
        color: Sequence[float] = (0.85, 1.0, 0.95),
    ) -> list:
        """
        Four ticks around screen centre, as fractions of the half-extents.

        Sized relatively for the same reason the bars are: a crosshair given in
        metres is a different size on every lens, and an aiming reticle that
        does not match where the shot goes is worse than none.
        """
        material = materials.glow(f"hud_{name}_mat", color, strength=2.2)
        g, a = gap * self.half_w, arm * self.half_w
        t = thickness * self.half_w
        arms = []
        for tick, (ox, oy, sx, sy) in {
            "l": (-g, 0.0, a, t), "r": (g, 0.0, a, t),
            "u": (0.0, g, t, a), "d": (0.0, -g, t, a),
        }.items():
            obj = prims.spawn(
                prims.PLANE, f"hud_{name}_{tick}",
                location=(ox, oy, -self.distance * 0.99),
                scale=(sx, sy, 1.0), material=material,
                into="HUD", shadow=False,
            )
            self._attach(obj)
            arms.append(obj)
        return arms

    def vignette(
        self,
        name: str,
        color: Sequence[float] = (0.9, 0.1, 0.1),
        *,
        strength: float = 3.0,
        alpha: float = 0.35,
    ) -> "Flash":
        """
        A full-screen tint, hidden by default — damage, boost, KO.

        A frame of colour is how a headless render shows an instantaneous event
        that would otherwise fall between two poses and never be seen.
        """
        plane = prims.spawn(
            prims.PLANE, f"hud_{name}_flash",
            location=(0.0, 0.0, -self.distance * 0.98),
            scale=(self.half_w * 1.2, self.half_h * 1.2, 1.0),
            material=materials.glow(f"hud_{name}_flash_mat", color,
                                    strength=strength, alpha=alpha),
            into="HUD", shadow=False,
        )
        prims.show(plane, False)
        self._attach(plane)
        widget = Flash(plane)
        self.widgets.append(widget)
        return widget

    # ── recording ─────────────────────────────────────────────────────────────

    def register(self, recorder) -> None:
        """Hand every widget's animated channels to the recorder."""
        for widget in self.widgets:
            widget.register(recorder)


class Bar:
    """A fill bar. `set(0..1)` scales it; the recorder bakes `scale`."""

    def __init__(self, fill, base_x: float):
        self.fill = fill
        self.base_x = base_x
        self.value = 1.0

    def set(self, fraction: float) -> None:
        self.value = max(0.0, min(1.0, fraction))
        # Never scale to exactly zero: a zero-scale object has a degenerate
        # normal matrix and Cycles reports it as an invalid mesh every frame.
        self.fill.scale.x = self.base_x * max(self.value, 1e-4)

    def register(self, recorder) -> None:
        recorder.track(self.fill, channels=("scale",))


class PipRow:
    """`set(n)` lights the first n pips and hides the rest."""

    def __init__(self, pips: list):
        self.pips = pips

    def set(self, lit: int) -> None:
        for i, pip in enumerate(self.pips):
            prims.show(pip, i < lit)

    def register(self, recorder) -> None:
        for pip in self.pips:
            recorder.track(pip, channels=("hide_render",))


class Flash:
    """A one-shot full-screen tint; `trigger()` shows it for `hold` ticks."""

    def __init__(self, plane, hold: int = 2):
        self.plane = plane
        self.hold = hold
        self._left = 0

    def trigger(self, hold: Optional[int] = None) -> None:
        self._left = hold if hold is not None else self.hold

    def advance(self) -> None:
        """Call once per tick, after the rules have had their chance to trigger."""
        prims.show(self.plane, self._left > 0)
        if self._left > 0:
            self._left -= 1

    def register(self, recorder) -> None:
        recorder.track(self.plane, channels=("hide_render",))
