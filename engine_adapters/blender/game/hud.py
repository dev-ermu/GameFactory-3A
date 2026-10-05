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


这是一个以相机为父级、由几何体构成的屏幕空间HUD。

由于没有用于绘制覆盖层的视口——该工具包的核心特点就是无头运行——因此这个HUD实际上是位于镜头前方一米处的实体对象。将它们设为相机的子物体，就能直接让它们处于屏幕空间；而且由于它们是实体对象，其状态是可关键帧化的：比如逐渐缩短的血条对应`scale.x`属性，录制器会像处理其他动画一样记录这一变化。而渲染时绘制的覆盖层无法被记录，审阅者打开的`.blend`文件中也不会包含这个HUD。

锚点采用归一化屏幕坐标表示，左下角为`(-1, -1)`，右上角为`(1, 1)`，这里会利用相机自身的镜头参数和渲染宽高比进行转换，这样无论分辨率如何，控件都能保持在指定角落。

这里的元素都是自发光材质，不会被次级光线照射到：HUD不会照亮任何物体，也不会投射阴影，即便在场景的无光角落也能清晰可见。

为何HUD会被保留在光线投射的依赖图中
---------------------------------------------
过去创建HUD时会设置`collide=False`，`prims`模块会将这一参数转化为`hide_viewport`——这对射击场景来说是正确的，因为镜头前方30厘米的平面会挡住所有子弹，但这样一来HUD也会从**窗口中隐藏**。结果就是生成的游戏视频里有HUD，但玩家实际游玩时却看不到。

由于没有“仅绘制不投射”的标志，因此排除逻辑被转移到了投射器端：某个机制会将其生成的碰撞体传递给`kernel.cast`，其余物体天生就对光线透明。如果某个机制没有设置这一参数就进行光线投射，就会在枪口前方检测到HUD。

"""

from typing import Optional, Sequence

from . import materials, prims

#: Blender's default sensor width, in mm. Camera FOV is derived from it.
# Blender默认的传感器宽度，单位为毫米。相机视野由此推导而来。
SENSOR_MM = 36.0

#: How far in front of the lens the HUD plane sits.
#:
#: Held deliberately close — beyond `make_camera`'s 0.05 clip start, but nearer
#: than anything a game is likely to parent to the camera. A first-person
#: viewmodel is also camera-parented, and at the metre this used to sit at the
#: gun rendered *in front of* the ammo counter and covered it. Widget sizes are
#: derived from this distance and the lens, so moving the plane does not move
#: anything on screen.

# HUD平面距离镜头的前方距离。
# 该数值特意设得较近——超过`make_camera`设定的0.05米裁剪起始距离，但又比游戏中可能作为相机子物体的物体更靠近镜头。
# 第一人称视角的模型也是相机子物体，过去HUD设置在1米距离时，会遮挡位于弹药计数器前方的枪械模型。
# 控件尺寸是根据这一距离和镜头参数计算的，因此移动该平面并不会改变屏幕上的显示效果。
HUD_DISTANCE = 0.3


class Hud:
    """
    Screen-space widgets on one camera.

    Args:
        camera: the camera object to parent to.
        resolution: `(x, y)` in pixels — sets the aspect used for anchoring.
        distance: metres in front of the lens.
    
    单个相机上的屏幕空间控件。

    参数：
        camera：作为父级的相机对象。
        resolution：像素值的`(x, y)`元组——用于设定锚点计算所用的宽高比。
        distance：镜头前方的距离，单位为米。
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

        
        一种左对齐的填充条，带有深色背景板。

        `width`和`height`是以屏幕半宽、半高为基准的比例值，因此无论分辨率如何变化，条形图的比例都能保持不变。
        `grow_left`参数用于反转条形方向，方便为右侧角色显示生命值。
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

        一排离散的小灯——用于表示弹药量、剩余生命数、已跑圈数、获胜回合数等信息。
        离散状态用“小点”来表示比用“条形”更合适，而切换可见性时会生成阶跃曲线，这对于绝不可能呈现半亮状态的计数器来说再合适不过了。
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

        静态文本。文本内容永不改变——屏幕上所有会变化的元素要么是条形，要么是一排小点，因为文本无法设置关键帧，
        而且每帧重新生成的话也无法通过烘焙处理。
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

        
        在屏幕中心周围生成四个标记，其尺寸以半宽度的比例来计算。
        出于与条形图相同的原因，其尺寸也经过相对调整。以米为单位表示的十字准星在不同镜头下的尺寸各异，
        而若瞄准标记与实际弹着点不匹配，那还不如没有它。
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

        全屏着色效果，默认隐藏——用于显示伤害、增益或击倒状态。
        无头渲染模式下，这种彩色帧用于呈现那些介于两个姿态之间、否则无法被看到的瞬时事件。
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
        """Hand every widget's animated channels to the recorder.
        将所有小部件的动画通道交给录制器处理。
        """
        for widget in self.widgets:
            widget.register(recorder)


class Bar:
    """A fill bar. `set(0..1)` scales it; the recorder bakes `scale`.
    填充条。`set(0..1)` 可调整其填充比例；录制器会记录 `scale` 参数。
    """

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
    """`set(n)` lights the first n pips and hides the rest.
    `set(n)` 会点亮前 n 个指示点，隐藏其余指示点。
    """

    def __init__(self, pips: list):
        self.pips = pips

    def set(self, lit: int) -> None:
        for i, pip in enumerate(self.pips):
            prims.show(pip, i < lit)

    def register(self, recorder) -> None:
        for pip in self.pips:
            recorder.track(pip, channels=("hide_render",))


class Flash:
    """A one-shot full-screen tint; `trigger()` shows it for `hold` ticks.
    一种单次全屏着色效果；调用`trigger()`后它会持续显示`hold`个时钟周期。
    """

    def __init__(self, plane, hold: int = 2):
        self.plane = plane
        self.hold = hold
        self._left = 0

    def trigger(self, hold: Optional[int] = None) -> None:
        self._left = hold if hold is not None else self.hold

    def advance(self) -> None:
        """Call once per tick, after the rules have had their chance to trigger.
        每个时钟周期调用一次，在规则触发之后执行。
        """
        prims.show(self.plane, self._left > 0)
        if self._left > 0:
            self._left -= 1

    def register(self, recorder) -> None:
        recorder.track(self.plane, channels=("hide_render",))
