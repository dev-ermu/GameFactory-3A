"""
engine_adapters/blender/game/kernel.py

The loop, the world and the report that every generated game shares.

A game subclass supplies three things — `build()`, `tick()` and `summary()` —
and gets back a fixed-timestep simulation, a baked animation, a video, a
`.blend` and a JSON report. Nothing here knows what genre it is running.

**Fixed timestep, always.** The tick rate is the frame rate, so tick N is
frame N and an event logged at tick N is findable in the video at N/fps
seconds. Nothing in this package reads a wall clock to advance the simulation:
a Cycles render between two ticks would be integrated as a one-second step and
teleport everything. The wall clock only ever measures.

**Determinism is a requirement, not a nicety.** The seed is part of the spec
and every random draw comes from `self.rng`, so a generated mechanic that
scored badly can be re-run and watched. A benchmark that cannot reproduce its
own failure cannot diagnose it.

这是所有生成的游戏所共享的循环、世界以及报告模块。

游戏子类需要提供三个函数：`build()`、`tick()` 和 `summary()`，最终会生成固定时间步长的模拟结果、预烘焙动画、视频、`.blend` 文件以及 JSON 格式的报告。该模块本身并不关心所运行的游戏类型。

**始终采用固定时间步长。**  tick速率即帧率，因此第N个tick对应第N帧；在第N个tick记录的事件，可在视频中于N/fps秒处找到。该模块中的任何部分都不会通过读取系统时钟来推进模拟：若在两个tick之间执行Cycles渲染，会被整合为1秒的时间步长，进而导致物体位置瞬间跳跃。系统时钟仅用于计时。

**确定性是一项硬性要求，而非可有可无的特性。** 随机种子是规格说明的一部分，所有随机操作均通过`self.rng`生成，因此表现不佳的生成机制可以被重新运行并观察其过程。无法复现自身故障的基准测试，也无法定位故障原因。
"""

import argparse
import json
import platform
import random
import sys
import time
from math import radians
from pathlib import Path
from typing import Any, Optional, Sequence

from . import assets, prims
from .recorder import Recorder, write_report


def _bpy():
    try:
        import bpy  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "engine_adapters.blender.game must run inside a bpy interpreter"
        ) from e
    return bpy


# ── Scene setup ───────────────────────────────────────────────────────────────

def reset_scene() -> None:
    """Empty the file. `--factory-startup` still ships the default cube."""
    bpy = _bpy()
    bpy.ops.wm.read_factory_settings(use_empty=True)


def setup_world(color: Sequence[float] = (0.05, 0.06, 0.09), strength: float = 0.35,
                hdri: Optional[str] = None, hdri_rotation: float = 0.0,
                gradient: Optional[Sequence[Sequence[float]]] = None,
                backdrop: float = 1.0) -> None:
    """
    The sky, in one of three flavours: flat colour, a gradient, or an HDRI.

    It is the fill light as well as the backdrop: with Cycles capped at two
    bounces there is little indirect light, and without an ambient term
    everything facing away from the sun renders black.

    Which one to reach for is an art-direction decision, not a quality ladder. An
    HDRI is a measured environment and lights photographic surfaces convincingly
    for the cost of one texture lookup; put low-poly models in front of it and
    the two read as different pictures pasted together. A gradient is the
    stylised counterpart — no asset to fetch, and it lets flat-shaded geometry
    sit in a scene that agrees with it.

    `backdrop` multiplies what the *camera* sees without touching what the sky
    lights with, and above 1.0 it is the only way to get a daylight sky. Brightness
    and fill are one product otherwise: a sky dim enough not to flood the scene
    from every direction at once renders darker than the grass under it, which
    reads as dusk, and a sky bright enough to look like daylight washes the colour
    out of everything. Only applies to the gradient sky — an HDRI is a measured
    environment and rescaling one of its two roles is what makes it stop matching.

    A missing HDRI file falls back rather than raising: a sky is a backdrop, and
    losing it is not worth failing a run that is otherwise fine.

    
    天空效果有三种表现形式：纯色、渐变或HDRI。

    它同时充当补光光源与背景：由于Cycles渲染器最多仅支持两次光线反弹，间接光照效果较弱；若没有环境光参数，背对太阳的物体会呈现黑色。

    选择哪种表现形式属于美术设计决策，而非画质等级的差异。HDRI能真实还原环境中的光照效果，可为摄影级表面提供逼真的照明，仅需一次纹理采样开销；但将低多边形模型置于HDRI环境中时，两者呈现的画面会显得格格不入。渐变则是风格化的替代方案——无需加载额外资源，能让平面着色几何物体融入与其风格协调的场景中。
    `backdrop`功能会对相机拍摄到的画面进行叠加处理，但不会影响天空光照效果；当该参数值大于1.0时，这是生成日光天空的唯一途径。否则的话，亮度与补光效果会合二为一：如果天空亮度不足，无法从各个方向均匀照亮场景，那么其亮度就会低于下方的草地，从而呈现出黄昏的效果；而如果天空亮度过高、类似日光，又会导致所有物体的色彩被冲淡。该功能仅适用于渐变天空——HDRI是一种经过测量的环境数据，对其参数进行重新缩放会导致其与真实环境不再匹配。
    如果缺少HDRI文件，程序会采用备用方案而非报错：毕竟天空只是背景而已，为了它而导致原本正常的渲染流程失败实在不值得。
    """
    bpy = _bpy()
    world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    # `use_nodes` is deprecated from 5.0; a new world already has a shader tree.
    if world.node_tree is None:
        world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is None:
        return

    background.inputs[0].default_value = (*color, 1.0)
    background.inputs[1].default_value = strength
    if hdri:
        _link_hdri(bpy, world, hdri, hdri_rotation)
    elif gradient:
        _link_gradient(bpy, world, gradient, backdrop)


#: Elevation, as sin(angle), that the gradient finishes climbing at.
#:
#: Measured rather than chosen: a 40 mm lens on a 16:9 frame spans 28 degrees
#: vertically, and a chase camera aimed slightly down leaves only about 5 degrees
#: of sky above the skyline — sin 5 deg = 0.09. A ramp spread over the hemisphere
#: puts 95% of itself out of shot, and sampling the frame showed the sky varying
#: by 4% from horizon to top edge, which is a flat wash. Finishing just past the
#: top of frame spends the whole ramp where it can be seen. The cost is that a
#: camera tilted well up sees a uniform zenith, which a chase camera never is.
GRADIENT_TOP = 0.12


def _link_gradient(bpy, world, gradient: Sequence[Sequence[float]],
                   backdrop: float = 1.0) -> None:
    """
    A two-colour sky: `gradient` is (horizon, zenith).

    Driven by the **z of the view direction**, which is what a world shader's
    generated coordinate gives — verified by rendering it as greyscale, because
    the neighbouring candidates are wrong in ways that look plausible:
    `Geometry > Incoming` is the same gradient upside down.

    `backdrop` splits the sky's two jobs apart with `Is Camera Ray`, which both
    EEVEE Next and Cycles honour here: the multiply lands only on rays coming from
    the lens, so the sky can be a daylight backdrop while lighting the scene as
    gently as `strength` asks. Without it the two are one number.
    """
    horizon, zenith = gradient[0], gradient[1]
    nodes, links = world.node_tree.nodes, world.node_tree.links

    coordinates = nodes.new("ShaderNodeTexCoord")
    separate = nodes.new("ShaderNodeSeparateXYZ")
    height = nodes.new("ShaderNodeMapRange")
    height.inputs["From Min"].default_value = 0.0
    height.inputs["From Max"].default_value = GRADIENT_TOP
    ramp = nodes.new("ShaderNodeValToRGB")
    # Eased, so the horizon band is a soft haze rather than a visible seam.
    ramp.color_ramp.interpolation = "EASE"
    ramp.color_ramp.elements[0].color = (*horizon, 1.0)
    ramp.color_ramp.elements[1].color = (*zenith, 1.0)

    links.new(coordinates.outputs["Generated"], separate.inputs["Vector"])
    links.new(separate.outputs["Z"], height.inputs["Value"])
    links.new(height.outputs["Result"], ramp.inputs["Fac"])

    sky = ramp.outputs["Color"]
    if abs(backdrop - 1.0) > 1e-3:
        path = nodes.new("ShaderNodeLightPath")
        gain = nodes.new("ShaderNodeMix")
        gain.data_type = "FLOAT"
        gain.inputs["A"].default_value = 1.0        # rays that light the scene
        gain.inputs["B"].default_value = backdrop   # rays that reach the lens
        links.new(path.outputs["Is Camera Ray"], gain.inputs["Factor"])

        brighten = nodes.new("ShaderNodeMix")
        brighten.data_type = "RGBA"
        brighten.blend_type = "MULTIPLY"
        brighten.inputs["Factor"].default_value = 1.0
        links.new(sky, brighten.inputs["A"])
        # A float into a colour socket arrives as grey, which is the scale wanted.
        links.new(gain.outputs["Result"], brighten.inputs["B"])
        sky = brighten.outputs["Result"]

    links.new(sky, nodes["Background"].inputs[0])


def setup_world_from_spec(spec: dict) -> None:
    """
    The sky a spec asks for. Used by both the render and the play path.

    The two paths build the same world from the same keys, and they were reading
    them separately — which is how a mechanic ends up looking one way in its
    video and another way in the window it is played in.
    """
    gradient = spec.get("sky_gradient")
    setup_world(
        color=tuple(spec.get("sky_color", (0.05, 0.06, 0.09))),
        strength=float(spec.get("sky_strength", 0.35)),
        hdri=spec.get("sky_hdri"),
        hdri_rotation=float(spec.get("sky_hdri_rotation", 0.0)),
        gradient=[tuple(gradient[0]), tuple(gradient[1])] if gradient else None,
        backdrop=float(spec.get("sky_backdrop", 1.0)),
    )


def _link_hdri(bpy, world, path: str, rotation: float) -> None:
    """
    Feed an equirectangular image into the world's background colour.

    The mapping node is not optional decoration: an HDRI's sun sits at a fixed
    compass bearing, and without a way to turn it the level has to be built to
    suit the sky. `rotation` is degrees around Z, which is the only axis worth
    turning a sky about.
    """
    image_path = assets.resolve(path)
    if image_path is None or not image_path.is_file():
        print(f"[world] no HDRI at {path} — keeping the flat sky")
        return
    try:
        image = bpy.data.images.load(str(image_path), check_existing=True)
    except RuntimeError as exc:
        print(f"[world] could not load HDRI {image_path}: {exc}")
        return

    nodes, links = world.node_tree.nodes, world.node_tree.links
    environment = nodes.new("ShaderNodeTexEnvironment")
    environment.image = image
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Rotation"].default_value = (0.0, 0.0, radians(rotation))
    coordinates = nodes.new("ShaderNodeTexCoord")

    links.new(coordinates.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], environment.inputs["Vector"])
    background = nodes["Background"]
    links.new(environment.outputs["Color"], background.inputs[0])


def add_sun(name: str = "sun", energy: float = 3.0,
            rotation: Sequence[float] = (0.9, 0.1, 0.7),
            angle: float = 0.12):
    """A key light. `angle` softens the shadow edge; hard shadows read as CG."""
    bpy = _bpy()
    data = bpy.data.lights.new(name, type="SUN")
    data.energy = energy
    data.angle = angle
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.rotation_euler = tuple(rotation)
    return obj


# ── Ray casting ───────────────────────────────────────────────────────────────

def cast(origin, direction, distance: float, solid=None, *, limit: int = 12):
    """
    Ray-cast the scene, ignoring everything that is not a named collider.

    `solid` is an **allow-list** of object names, so scenery is transparent to a
    shot by construction rather than by remembering to mark it. Blender has no
    "draws but does not block" flag — `hide_render` still stops a ray,
    `hide_viewport` removes the object from the window too — so an unwanted hit is
    stepped over instead: the ray restarts 0.1 mm past it, since restarting on the
    surface re-hits it and burns the budget standing still.

    Drop-in for `scene.ray_cast`, same return shape. `limit` caps the walk and
    reports a miss when exceeded, which is the safe way to fail.
    """
    import mathutils  # noqa: PLC0415

    bpy = _bpy()
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()

    start = mathutils.Vector(origin)
    heading = mathutils.Vector(direction)
    remaining = float(distance)
    for _ in range(limit):
        result = bpy.context.scene.ray_cast(graph, start, heading,
                                           distance=remaining)
        hit, point, _, _, obj, _ = result
        if not hit or solid is None or obj.name in solid:
            return result
        remaining -= (point - start).length + 1e-4
        if remaining <= 0.0:
            break
        start = point + heading * 1e-4
    return (False, mathutils.Vector((0.0, 0.0, 0.0)),
            mathutils.Vector((0.0, 0.0, 0.0)), -1, None, mathutils.Matrix())


# ── Actors ────────────────────────────────────────────────────────────────────

class Actor:
    """
    A transform the rules move and the recorder bakes.

    Position is kept here as plain floats and pushed to Blender by `sync()`,
    rather than read back out of `obj.location` each tick. Blender does not
    refresh `matrix_world` until the depsgraph runs, so a rule that both moved
    an actor and then measured it would read the previous tick's position.

    Actors face **+Y** at yaw 0, matching `camera_rigs`.
    """

    def __init__(self, name: str, obj, *, position=(0.0, 0.0, 0.0), yaw: float = 0.0,
                 team: str = "neutral", **state):
        self.name = name
        self.obj = obj
        self.x, self.y, self.z = (float(v) for v in position)
        self.yaw = float(yaw)
        self.team = team
        self.vx = self.vy = self.vz = 0.0
        self.alive = True
        self.state: dict[str, Any] = dict(state)

    @property
    def position(self) -> tuple:
        return (self.x, self.y, self.z)

    def move(self, dx: float, dy: float, dz: float = 0.0) -> None:
        self.x += dx
        self.y += dy
        self.z += dz

    def distance_to(self, other: "Actor | Sequence[float]") -> float:
        p = other.position if isinstance(other, Actor) else other
        return ((self.x - p[0]) ** 2 + (self.y - p[1]) ** 2 + (self.z - p[2]) ** 2) ** 0.5

    def planar_distance_to(self, other: "Actor | Sequence[float]") -> float:
        p = other.position if isinstance(other, Actor) else other
        return ((self.x - p[0]) ** 2 + (self.y - p[1]) ** 2) ** 0.5

    def sync(self, *, roll: float = 0.0, pitch: float = 0.0) -> None:
        """Push the simulated transform onto the Blender object."""
        from math import radians

        self.obj.location = (self.x, self.y, self.z)
        self.obj.rotation_euler = (radians(pitch), radians(roll), radians(self.yaw))


# ── Spec ──────────────────────────────────────────────────────────────────────

def merge_spec(defaults: dict, override: Optional[dict]) -> dict:
    """
    Overlay a task's spec on a game's defaults, recursing into nested blocks.

    A shallow merge would make `{"weapon": {"damage": 40}}` erase `mag_size`,
    `reload_time` and the rest of the weapon, which is the opposite of what a
    task tuning one number means. Nested dicts are therefore merged key by key;
    lists are replaced wholesale, since a partial list override has no sensible
    reading.
    """
    merged = dict(defaults)
    for key, value in (override or {}).items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = merge_spec(current, value)
        else:
            merged[key] = value
    return merged


# ── The game ──────────────────────────────────────────────────────────────────

class Game:
    """
    Base class for a generated mechanic.

    Subclasses override:
        genre       -- label used in the report
        build()     -- level, actors, camera, HUD; register recordables
        tick()      -- one fixed step of the rules
        summary()   -- the metrics that say whether the mechanic worked

    and may override `verdict()` to decide pass/fail from those metrics.
    """

    genre = "generic"
    default_spec: dict[str, Any] = {}

    def __init__(self, spec: dict, out_dir: str | Path):
        self.spec = merge_spec(self.default_spec, spec)
        self.out_dir = Path(out_dir).resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)

        self.fps = int(self.spec.get("fps", 30))
        self.duration = float(self.spec.get("duration_sec", 14.0))
        self.dt = 1.0 / self.fps
        self.total_ticks = max(1, int(round(self.duration * self.fps)))
        self.resolution = tuple(self.spec.get("resolution", (960, 540)))
        self.samples = int(self.spec.get("samples", 24))
        self.seed = int(self.spec.get("seed", 7))
        self.rng = random.Random(self.seed)
        #: Decoration's own stream. Separate from `rng` because a draw spent
        #: choosing a crate model is a draw the rules do not make, so sharing one
        #: would make turning the art on change the gameplay — and then a run with
        #: assets and a run without cannot be compared.
        self.look = random.Random(self.seed ^ 0x5A17)

        self.frame = 0
        self.time = 0.0
        self.events: list[dict] = []
        self.actors: list[Actor] = []
        self.finished_at: Optional[float] = None

        self.recorder = Recorder(fps=self.fps, resolution=self.resolution)
        self.camera = None
        self.hud = None

        #: One tick of player intent, or None when the game's own policy drives.
        #: A subclass checks this to decide whose decision it is acting on — see
        #: `human` below and `controls.py` for what fills it.
        self.controls = None
        #: True only in a live window. Rules may use it to skip work that exists
        #: for the recording (settling a corpse for the camera, say) but must not
        #: change anything a metric is computed from, or a played run and a
        #: rendered run stop being comparable.
        self.interactive = False

    # ── hooks ─────────────────────────────────────────────────────────────────

    def build(self) -> None:
        raise NotImplementedError

    def tick(self) -> None:
        raise NotImplementedError

    def summary(self) -> dict:
        return {}

    def verdict(self, summary: dict) -> tuple[bool, list[str]]:
        """Default: a run that produced events and never crashed is a pass."""
        return bool(self.events), []

    # ── helpers for subclasses ────────────────────────────────────────────────

    @property
    def human(self) -> bool:
        """Whether a player is supplying input this run."""
        return self.controls is not None

    def models(self, key: str) -> list:
        """
        The `models.<key>` references a task gave, always as a list.

        A list rather than one reference because a wall repeated thirty times
        reads as a corridor in a loop. A bare string is wrapped, so a spec that
        wants one model need not write brackets.
        """
        entry = (self.spec.get("models") or {}).get(key)
        if not entry:
            return []
        return [entry] if isinstance(entry, str) else list(entry)

    def pick(self, key: str):
        """One reference from `models.<key>`, drawn off `look`. None if unset."""
        options = self.models(key)
        return self.look.choice(options) if options else None

    def log(self, kind: str, **data) -> dict:
        """
        Record a gameplay event against the tick it happened on.

        This log is the machine-readable half of the deliverable — an evaluator
        reads it to check that a mechanic fired at all, and a human uses the
        tick to find the moment in the video.
        """
        event = {"tick": self.frame, "t": round(self.time, 3), "kind": kind, **data}
        self.events.append(event)
        return event

    def spawn_actor(self, name: str, kind: Optional[str] = None, *,
                    position=(0.0, 0.0, 0.0), yaw: float = 0.0,
                    scale=(1.0, 1.0, 1.0), material=None,
                    team: str = "neutral", into: str = "Actors", **state) -> Actor:
        """
        An actor backed by one primitive, or by an empty root when `kind` is
        None — the latter for characters assembled from several parts, which
        must not inherit a body's non-uniform scale.
        """
        if kind is None:
            obj = prims.empty(name, location=position, into=into)
        else:
            obj = prims.spawn(kind, name, location=position, scale=scale,
                              material=material, into=into)
        actor = Actor(name, obj, position=position, yaw=yaw, team=team, **state)
        actor.sync()
        self.actors.append(actor)
        self.recorder.track(obj, channels=("location", "rotation_euler"))
        return actor

    def count_events(self, kind: str) -> int:
        return sum(1 for e in self.events if e["kind"] == kind)

    def finish(self, reason: str = "objective_complete") -> None:
        """End the run early — the objective was met, or the round is over."""
        if self.finished_at is None:
            self.finished_at = self.time
            self.log("run_finished", reason=reason)

    # ── the loop ──────────────────────────────────────────────────────────────

    def run(self, *, render: bool = True, device: str = "CPU",
            source=None) -> dict:
        """
        Simulate, bake and render the whole run.

        `source` is an optional input source (`controls.ScriptedSource`): with
        one, the run is played by a recorded human session instead of by the
        game's own policy, headless and at full render quality. It is the same
        loop either way, which is the only reason a replay is worth anything.
        """
        started = time.time()
        reset_scene()
        setup_world_from_spec(self.spec)

        self.build()
        if self.camera is None:
            raise RuntimeError(f"{type(self).__name__}.build() set no camera")

        build_seconds = time.time() - started

        sim_started = time.time()
        for i in range(1, self.total_ticks + 1):
            self.frame = i
            self.time = i * self.dt
            if source is not None:
                self.controls = source.poll(self.time)
            self.tick()
            self.recorder.capture(i)
            if self.finished_at is not None and self.time - self.finished_at > 1.2:
                # A moment of the end state on screen, then stop: a video that
                # cuts on the winning hit reads as a crash.
                break
        self.recorder.finish()
        sim_seconds = time.time() - sim_started

        summary = self.summary()
        ok, problems = self.verdict(summary)

        report: dict[str, Any] = {
            "ok": ok,
            "genre": self.genre,
            "game_class": type(self).__name__,
            "spec": self.spec,
            "seed": self.seed,
            "ticks": self.frame,
            "fps": self.fps,
            "driven_by": "input_replay" if source is not None else "policy",
            "sim_seconds": round(sim_seconds, 2),
            "build_seconds": round(build_seconds, 2),
            "duration_played_sec": round(self.frame / self.fps, 2),
            "tracked_objects": self.recorder.tracked_count,
            "event_counts": self._event_counts(),
            "metrics": summary,
            "problems": problems,
            "warnings": [],
            "artifacts": {},
            "environment": {
                "blender": _bpy().app.version_string,
                "python": platform.python_version(),
            },
        }

        if render:
            render_info = self.recorder.configure_render(samples=self.samples,
                                                         device=device)
            report["render"] = render_info
            report["warnings"].extend(render_info.get("warnings", []))

            video = self.recorder.render_video(self.out_dir / "gameplay.mp4")
            report["warnings"].extend(video.get("warnings", []))
            report["artifacts"]["video"] = video.get("video")
            report["artifacts"]["frames_dir"] = video.get("frames_dir")
            report["render_seconds"] = video.get("seconds")

            thumb_frame = max(1, int(self.frame * 0.6))
            report["artifacts"]["thumbnail"] = self.recorder.render_still(
                self.out_dir / "thumbnail.png", frame=thumb_frame)

        report["artifacts"]["blend"] = self.recorder.save_blend(
            self.out_dir / "session.blend")
        report["artifacts"]["events"] = write_report(
            self.out_dir / "demo_outputs" / "events.json",
            {"genre": self.genre, "fps": self.fps, "events": self.events})
        report["artifacts"]["report"] = str(self.out_dir / "demo_outputs" / "report.json")
        report["total_seconds"] = round(time.time() - started, 1)

        write_report(self.out_dir / "demo_outputs" / "report.json", report)
        return report

    def _event_counts(self) -> dict:
        counts: dict[str, int] = {}
        for e in self.events:
            counts[e["kind"]] = counts.get(e["kind"], 0) + 1
        return dict(sorted(counts.items()))


# ── Entry point plumbing ──────────────────────────────────────────────────────

def script_argv() -> list:
    """
    The script's own arguments under either interpreter.

    `blender --python x.py -- --spec a.json` hands the whole command line to the
    script; everything after the bare `--` is ours. The pip wheel has no
    separator.
    """
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return [a for a in sys.argv[1:] if not a.endswith(".py")]


def save_session(game: "Game", source, reason: str) -> dict:
    """
    Write what happened in a play session, and the input that caused it.

    Called when an interactive session ends. The timeline is the valuable half:
    a session is played at viewport quality on whatever machine the player has,
    and `--replay-input` turns it back into the same Cycles video the batch path
    produces. Metrics are written too, so a mechanic can be judged on how it
    played for a person rather than how it played for its own policy.
    """
    out = game.out_dir / "demo_outputs"
    out.mkdir(parents=True, exist_ok=True)
    artifacts = {}

    timeline = getattr(source, "timeline", None)
    if callable(timeline):
        artifacts["input_timeline"] = write_report(out / "input_timeline.json",
                                                   timeline())

    summary = game.summary()
    ok, problems = game.verdict(summary)
    artifacts["play_report"] = write_report(out / "play_report.json", {
        "ok": ok,
        "genre": game.genre,
        "game_class": type(game).__name__,
        "driven_by": "player",
        "ended": reason,
        "seed": game.seed,
        "ticks": game.frame,
        "fps": game.fps,
        "duration_played_sec": round(game.frame / game.fps, 2),
        "metrics": summary,
        "problems": problems,
        "event_counts": game._event_counts(),
        "events": game.events,
    })

    print(f"\n[play] {'PASS' if ok else 'FAIL'} — {round(game.frame / game.fps, 2)}s played")
    for key, value in summary.items():
        print(f"    {key}: {value}")
    for kind, n in game._event_counts().items():
        print(f"    event {kind}: {n}")
    for key, value in artifacts.items():
        print(f"    -> {key}: {value}")
    if "input_timeline" in artifacts:
        print("\nRe-render that session at full quality with:\n"
              f"    --replay-input {artifacts['input_timeline']} "
              f"--duration {round(game.frame / game.fps, 2)}")
    return artifacts


def main(game_class, argv: Optional[list] = None) -> dict:
    """
    Standard `if __name__ == "__main__"` body for a generated game.

    Reads the spec from `--spec` (a JSON file, so quoting survives the `--`
    boundary), runs the game, prints the report and sets an exit code the shell
    can actually see.
    """
    parser = argparse.ArgumentParser(description=f"Run {game_class.__name__}")
    parser.add_argument("--spec", default=None, help="JSON spec file")
    parser.add_argument("--out-dir", default=".", help="Where artifacts are written")
    parser.add_argument("--duration", type=float, default=None,
                        help="Override spec duration_sec")
    parser.add_argument("--samples", type=int, default=None,
                        help="Override Cycles samples")
    parser.add_argument("--resolution", default=None, help="WxH, e.g. 1280x720")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--device", default="CPU",
                        help="Cycles device. CPU is the default because it always "
                             "works; AUTO/CUDA/OPTIX opt in to a GPU, which is "
                             "worth about 1.3x at gate resolution and 3x at 1080p "
                             "(see recorder._select_device for the numbers)")
    parser.add_argument("--no-render", action="store_true",
                        help="Simulate and bake only — a fast correctness check")
    play = parser.add_argument_group("interactive play")
    play.add_argument("--play", action="store_true",
                      help="Play it: a live window, keyboard and mouse, EEVEE in "
                           "the viewport. Needs a real Blender window, so launch "
                           "without --background")
    play.add_argument("--sensitivity", type=float, default=1.0,
                      help="Mouse look multiplier for --play")
    play.add_argument("--windowed", action="store_true",
                      help="Leave the Blender UI visible instead of maximising "
                           "the viewport")
    play.add_argument("--replay-input", default=None, metavar="FILE",
                      help="Drive the player from a recorded input timeline and "
                           "render it — the batch half of --play")
    args = parser.parse_args(argv if argv is not None else script_argv())

    spec: dict = {}
    if args.spec:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    if args.duration is not None:
        spec["duration_sec"] = args.duration
    if args.samples is not None:
        spec["samples"] = args.samples
    if args.seed is not None:
        spec["seed"] = args.seed
    if args.resolution:
        w, _, h = args.resolution.lower().partition("x")
        spec["resolution"] = (int(w), int(h))

    game = game_class(spec, args.out_dir)

    if args.play:
        from . import interactive  # noqa: PLC0415  (needs a window; not always)

        # No exit code and no report yet: the operator is still running when
        # this returns, and Blender's event loop is what plays the game.
        return interactive.play(game, sensitivity=args.sensitivity,
                               fullscreen=not args.windowed,
                               on_quit=save_session)

    source = None
    if args.replay_input:
        from .controls import ScriptedSource  # noqa: PLC0415

        source = ScriptedSource.from_file(args.replay_input, game.genre,
                                          fps=game.fps)
        print(f"[replay] driving the player from {args.replay_input}")

    report = game.run(render=not args.no_render, device=args.device,
                      source=source)

    print(f"\n[{game.genre}] {'PASS' if report['ok'] else 'FAIL'} "
          f"— {report['ticks']} ticks, {report['duration_played_sec']}s played")
    for key, value in report["metrics"].items():
        print(f"    {key}: {value}")
    for kind, n in report["event_counts"].items():
        print(f"    event {kind}: {n}")
    for problem in report["problems"]:
        print(f"    PROBLEM: {problem}")
    for warning in report["warnings"]:
        print(f"    warning: {warning}")
    for key, value in report["artifacts"].items():
        if value:
            print(f"    -> {key}: {value}")

    from .recorder import exit_code
    exit_code(report["ok"])
    return report
