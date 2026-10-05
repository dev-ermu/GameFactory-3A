"""
engine_adapters/blender/game/interactive.py

Playing a generated mechanic, instead of watching one.

`kernel.Game.run()` steps the rules `total_ticks` times as fast as the CPU
allows and bakes a keyframe per tick. This module steps the *same* `tick()` on a
wall-clock timer inside a live Blender window, with a human filling the input
surface from `controls.py`, and draws it with EEVEE in the viewport instead of
Cycles to a file.

Three things make that safe to bolt onto rules written for a batch bake:

- **The timestep does not change.** `game.dt` stays `1/fps`; the timer only
  decides *when* a tick happens, never how big it is. A frame that arrives late
  runs the same 33 ms of game as a frame that arrives on time, and a very late
  frame runs several of them (capped, see `MAX_CATCHUP_TICKS`). Scaling the step
  by real elapsed time is the classic way to make a fixed-step simulation
  explode the moment the window is dragged.
- **Nothing bakes.** `Recorder.capture()` is never called here, so a ten-minute
  session does not accumulate eighteen thousand keyframes per object. The
  recorder still exists for the objects' sake; it is simply not fed.
- **The rules do not know.** A game reads `self.controls`; whether that came
  from a keyboard or from its own policy is not its concern.

Requires a real Blender window — `blender --python play.py`, *not*
`--background`. There is no offscreen path here on purpose: an interactive mode
that cannot be seen has nothing to offer over the batch mode that already works.


运行已生成的游戏机制，而非仅观看预渲染结果。

`kernel.Game.run()`会按照CPU允许的速度将规则执行`total_ticks`次，并为每一帧生成关键帧。而本模块则是在Blender实时窗口内的时钟计时器上执行*相同的*`tick()`逻辑，玩家通过`controls.py`定义的输入界面进行操作，且渲染时采用EEVEE引擎在视口中显示，而非使用Cycles渲染到文件。

以下三点确保了该方式能安全地应用于原本为批量渲染编写的规则：

- **时间步长保持不变。**`game.dt`的值始终为`1/fps`；计时器仅决定帧何时更新，而不会改变单次更新的时长。延迟到达的帧会执行与按时到达帧相同的33毫秒游戏逻辑，若帧延迟严重，则会连续执行多帧逻辑（上限由`MAX_CATCHUP_TICKS`设定）。若按实际经过时间缩放步长，一旦拖动窗口，固定步长的模拟就会直接崩溃。
- **不会进行任何烘焙操作。**此处绝不会调用`Recorder.capture()`，因此哪怕运行十分钟，每个物体也不会累积一万八千个关键帧。记录器虽仍存在，但并未被投入使用，是为了适配物体的需要而已。
- **游戏规则层面毫无察觉。**游戏会读取`self.controls`；至于这些数据来自键盘输入还是游戏自身策略，游戏并不关心。

运行本程序需要打开真实的Blender窗口——需使用命令`blender --python play.py`，而非`--background`模式。我们特意没有提供离屏渲染路径：无法可视化的交互模式，相比已经能正常工作的批量渲染模式并无优势。
"""

import time
from typing import Optional

from . import controls as controls_mod
from . import recorder

#: How many simulation steps one frame may run to catch up. Beyond this the
#: session accepts being behind: the alternative is a stall that gets longer
#: every frame, which is how a slow render turns into a frozen window.
# 单帧内最多可执行的模拟步数，用于追赶延迟的帧。超过该数值后，
# 程序允许存在延迟：否则每帧延迟都会不断累积，最终导致画面卡顿，慢速渲染甚至会令窗口完全冻结。
MAX_CATCHUP_TICKS = 4

#: Viewport shading. `MATERIAL` is EEVEE with the scene's materials and is what
#: makes the emissive HUD and the glow pools read; `RENDERED` also works but
#: pays for the world's ambient sampling every frame.
# 视口着色模式。`MATERIAL`模式采用EEVEE引擎并应用场景材质，
# 能正确显示发光式HUD和光晕效果；`RENDERED`模式虽也可行，但每帧都要进行全局环境采样，性能开销更大。
VIEW_SHADING = "MATERIAL"


def _bpy():
    import bpy  # noqa: PLC0415

    return bpy


# ── Viewport ──────────────────────────────────────────────────────────────────

def prepare_window(game, *, fullscreen: bool = True, shading: str = VIEW_SHADING):
    """
    Point the biggest 3D viewport through the game camera and make it playable.

    A generated game's HUD is geometry parented to its camera, so a viewport in
    a user perspective shows the level with the HUD floating in the middle of it.
    Camera view is not a preference here; it is the only view the game is
    composed for.

    将最大的3D视口对准游戏摄像机，使其可交互。
    生成的游戏HUD是由依附于摄像机的几何物体构成的，因此从用户视角看到的视口会显示出游戏场景，而HUD则悬浮在场景中央。
    这里的摄像机视图并非可选项；它正是游戏所采用的唯一视图。
    """
    bpy = _bpy()
    scene = bpy.context.scene
    scene.camera = game.camera
    # EEVEE for interactivity. Cycles in a viewport is a slideshow, and the
    # generated materials are flat emissive-and-diffuse, which EEVEE renders
    # near-identically to the Cycles video.
    # 为了交互性选择EEVEE渲染器。Cycles渲染器在视口中只会以幻灯片形式显示，
    # 而且生成的材质仅为平面发光+漫反射类型，EEVEE的渲染效果与Cycles视频版几乎一致。
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    scene.render.resolution_x, scene.render.resolution_y = game.resolution
    # Tone mapping is a scene setting, so the viewport reads the same one the
    # render does — but only the render path went through `configure_render` to
    # set it. A played session was therefore graded by Blender's default AgX
    # while the video of it was graded Standard, and the flat saturated palette
    # these games are built from came out of the window looking fogged.
    # 色调映射属于场景设置，因此视口会采用与渲染相同的色调映射参数——
    # 不过只有渲染流程会通过`configure_render`来设置该参数。因此，游戏运行时的色调映射采用Blender默认的AgX模式，
    # 而生成的视频则采用Standard色调映射，导致这些游戏所用的高饱和度扁平调色板效果大打折扣。
    try:
        scene.view_settings.view_transform = recorder.VIEW_TRANSFORM
        scene.view_settings.look = "None"
    except TypeError:
        pass  # A build without it keeps its default; a grade is not worth failing on.

    window, area = _largest_view3d(bpy)
    if area is None:
        return None
    space = area.spaces.active
    space.region_3d.view_perspective = "CAMERA"
    space.shading.type = shading
    # Material preview lights the viewport with a built-in studio HDRI and
    # ignores the scene's own world and lamps unless told otherwise. Left at the
    # default, a session is lit by Blender rather than by the game: the sky set
    # up in `setup_world` and the key light from `add_sun` are both invisible,
    # and the window stops being evidence of what the render will look like.
    # 材质预览模式下，视口会使用内置的演播室级HDRI光源进行照明，除非另有指定，否则会忽略场景自身的环境光和灯光。
    # 若保持默认设置，视口将由Blender而非游戏本身提供照明：`setup_world`中设置的天空以及`add_sun`添加的主光源都会不可见，
    # 导致视口无法反映真实的渲染效果。
    space.shading.use_scene_world = True
    space.shading.use_scene_lights = True
    # The overlays are Blender's, not the game's: gizmos, grid and the text in
    # the corner all draw over the HUD and none of them are part of the game.
    # 这些覆盖层属于Blender自带的，并非游戏内容：虚拟控件、网格以及角落的文本都会覆盖在HUD之上，且它们均不属于游戏的一部分。
    space.overlay.show_overlays = False
    space.show_gizmo = False
    # Hiding a region re-inits the area, and that reads the window from the
    # context rather than from the area. A startup script has no context window,
    # so it has to be supplied here or the re-init dereferences null.
    # 隐藏某个区域会导致该区域重新初始化，此时会读取上下文中的窗口信息而非区域自身的信息。启动脚本没有上下文窗口，
    # 因此必须在此处指定，否则重新初始化时会引用空值。
    with bpy.context.temp_override(window=window, area=area):
        space.show_region_ui = False
        space.show_region_toolbar = False
        space.show_region_header = False

    if fullscreen:
        _fullscreen(bpy, window, area)
    return area


def _largest_view3d(bpy):
    """The biggest 3D viewport, and the window it lives in.
    最大的3D视图窗口及其所属的窗口
    """
    best_window, best_area, best_size = None, None, 0
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            size = area.width * area.height
            if size > best_size:
                best_window, best_area, best_size = window, area, size
    return best_window, best_area


def _fullscreen(bpy, window, area) -> None:
    """
    Maximise the viewport, tolerating a context Blender will not accept.

    `screen.screen_full_area` needs the area in the override and still refuses
    in some window states; a session that is merely not maximised is fine, so
    this never raises.

    
    将视图窗口最大化，即便Blender的上下文环境不允许这么做。

    `screen.screen_full_area`需要传入对应的区域参数，但在某些窗口状态下仍会报错；
    只要窗口未被最大化就没问题，因此该操作不会引发异常。
    """
    try:
        with bpy.context.temp_override(window=window, area=area,
                                       region=area.regions[-1]):
            bpy.ops.screen.screen_full_area(use_hide_panels=True)
    except Exception:                                    # noqa: BLE001
        pass


# ── The loop ──────────────────────────────────────────────────────────────────

class Session:
    """
    The loop itself: fixed steps, a pause, and an end.

    Kept out of the operator because a `bpy.types.Operator` cannot be
    instantiated from Python — Blender constructs it — so anything living on the
    operator can only be tested by a person sitting in front of Blender. This
    class is the part with the rules in it, and it is testable headless.
    
    主循环本身：包含固定的执行步骤、暂停逻辑以及结束条件。

    之所以将其独立于运算符之外，是因为无法通过Python实例化`bpy.types.Operator`——
    Blender会负责创建该类实例——因此依附于运算符的任何逻辑都只能由坐在Blender前的人来测试。
    而这个类包含了具体的执行规则，可脱离界面进行无头测试。
    """

    def __init__(self, game, source) -> None:
        self.game = game
        self.source = source
        self.ticks = 0
        self.frames_drawn = 0
        self.paused = False
        #: Why the session ended, for the play report. "quit" is the player's
        #: choice; anything else is the game deciding it is over.
        self.reason = "running"
        self._pause_held = False
        self._debt = 0.0

    # ── stepping ──────────────────────────────────────────────────────────────

    def step(self) -> bool:
        """One fixed step of the game. False means the session should end.
        游戏的单次固定执行步骤。返回False意味着会话应结束。
        """
        game = self.game
        # Sampled at the time of the tick it will drive, which is the same
        # instant `Game.run()` samples a replay at. Polling at the *current*
        # time and then advancing looks equivalent and is not: it shifts every
        # input one tick earlier than the replay of it, and a replay that does
        # not reproduce the session is worse than no replay at all.
        # 该数值在对应tick触发时采样，与`Game.run()`采样回放数据的时刻一致。
        # 若直接在*当前*时间采样再推进，效果并不等效：会导致所有输入比回放数据早一个tick，
        # 而无法复现原会话的回放结果，这种无效的回放还不如没有回放。
        upcoming = (game.frame + 1) * game.dt
        controls = self.source.poll(upcoming)

        if controls.pause and not self._pause_held:
            self.paused = not self.paused
            print(f"[play] {'paused' if self.paused else 'resumed'}")
        self._pause_held = controls.pause

        if controls.quit:
            self.reason = "quit"
            return False
        if self.paused:
            return True

        game.controls = controls
        game.frame += 1
        game.time = upcoming
        game.tick()
        self.ticks += 1

        # A moment of the end state before the window closes, for the same
        # reason the rendered video holds on it: a cut on the winning hit reads
        # as a crash rather than a result.
        if game.finished_at is not None and game.time - game.finished_at > 2.5:
            done = [e for e in game.events if e["kind"] == "run_finished"]
            self.reason = done[-1].get("reason", "finished") if done else "finished"
            return False
        return True

    def advance(self, elapsed: float) -> tuple:
        """
        Run however many whole steps `elapsed` seconds of real time has earned.

        Returns `(steps_run, still_running)`. The timestep never changes: real
        time only decides *how many* steps happen, because scaling a fixed step
        by measured elapsed time is what makes a simulation explode the first
        time a frame takes 200 ms.

        执行“真实时间”经过`elapsed`秒所对应的完整时间步。
        
        返回值形式为`(已执行的步数, 是否仍在运行)`。时间步长固定不变：
        真实时间仅决定要执行多少步——因为若按测量的流逝时间缩放固定步长，
        一旦某帧耗时达到200毫秒，模拟就会直接崩溃。
        """
        self._debt += max(0.0, elapsed)
        step = self.game.dt
        ran = 0
        while self._debt >= step and ran < MAX_CATCHUP_TICKS:
            self._debt -= step
            ran += 1
            if not self.step():
                return ran, False
        if ran >= MAX_CATCHUP_TICKS:
            # Further behind than we will chase: forget the debt instead of
            # carrying it and falling further behind every frame.
            self._debt = 0.0
        if ran:
            self.frames_drawn += 1
        return ran, True


# ── The operator ──────────────────────────────────────────────────────────────

def make_operator(game, source, *, on_quit=None, session=None):
    """
    Build the modal operator class that feeds `session` from a Blender window.

    Made per session rather than registered once against globals because the
    operator needs this game and this input source, and Blender instantiates
    operator classes itself — there is nowhere to pass arguments in.

    构建用于从Blender窗口接收`session`数据的模态操作符类。
    
    由于每个会话需要对应的游戏实例和输入源，且Blender会自行实例化操作符类，
    没有地方可以传递参数，因此需为每个会话单独创建该类，而非注册到全局作用域。
    """
    bpy = _bpy()
    session = session if session is not None else Session(game, source)

    #: Blender reports these as events but they are not input.
    IGNORED = {"TIMER", "TIMER_REPORT", "TIMER0", "TIMER1", "TIMER_JOBS",
               "TIMER_AUTOSAVE", "NONE"}

    class AAAGF_OT_play(bpy.types.Operator):
        bl_idname = "aaagf.play"
        bl_label = "Play generated mechanic"
        bl_options = {"REGISTER"}

        _timer = None
        _last_wall = 0.0
        _centre = (0, 0)
        _started = 0.0

        # ── lifecycle ─────────────────────────────────────────────────────────

        def invoke(self, context, event):
            wm = context.window_manager
            self._timer = wm.event_timer_add(1.0 / max(1, game.fps),
                                             window=context.window)
            wm.modal_handler_add(self)
            self._last_wall = time.perf_counter()
            self._started = self._last_wall
            self._recentre(context)
            if game.genre == "fps":
                # A shooter needs the pointer out of the way and unbounded, so
                # the cursor is hidden and warped back to centre every tick.
                context.window.cursor_modal_set("NONE")
            print(f"[play] {game.genre} running at {game.fps} Hz — ESC to quit")
            return {"RUNNING_MODAL"}

        def _recentre(self, context) -> None:
            self._centre = (context.window.width // 2, context.window.height // 2)

        def finish(self, context, reason: str = "quit"):
            wm = context.window_manager
            if self._timer is not None:
                wm.event_timer_remove(self._timer)
                self._timer = None
            try:
                context.window.cursor_modal_restore()
            except Exception:                            # noqa: BLE001
                pass
            elapsed = max(1e-6, time.perf_counter() - self._started)
            print(f"[play] stopped ({reason}) — {session.ticks} ticks in "
                  f"{elapsed:.1f}s, {session.frames_drawn / elapsed:.1f} fps drawn")
            if on_quit is not None:
                on_quit(game, source, reason)
            return {"FINISHED"}

        # ── the loop ──────────────────────────────────────────────────────────

        def modal(self, context, event):
            if event.type == "TIMER":
                return self._on_timer(context)

            if event.type in ("MOUSEMOVE", "INBETWEEN_MOUSEMOVE"):
                if game.genre == "fps" and not session.paused:
                    source.mouse_moved(event.mouse_x - self._centre[0],
                                       event.mouse_y - self._centre[1])
                    context.window.cursor_warp(*self._centre)
                return {"RUNNING_MODAL"}

            if event.type == "WINDOW_DEACTIVATE":
                # Alt-tabbing away never delivers the key-up, so without this the
                # player walks forward into a wall for as long as they are gone.
                source.held.clear()
                return {"RUNNING_MODAL"}

            if event.type in IGNORED:
                return {"RUNNING_MODAL"}

            if event.value == "PRESS":
                source.key_down(event.type)
            elif event.value == "RELEASE":
                source.key_up(event.type)
            # Every other key is swallowed: an unhandled keystroke reaching
            # Blender mid-session is how a session ends with the timeline
            # scrubbed and a random object deleted.
            return {"RUNNING_MODAL"}

        def _on_timer(self, context):
            now = time.perf_counter()
            elapsed, self._last_wall = now - self._last_wall, now
            # Recomputed every frame rather than once, so resizing the window
            # does not leave mouse look measuring from the old centre and
            # drifting the view a little further every frame.
            self._recentre(context)

            ran, running = session.advance(elapsed)
            if not running:
                return self.finish(context, session.reason)
            if ran:
                _redraw(context)
            return {"RUNNING_MODAL"}

    AAAGF_OT_play.session = session
    return AAAGF_OT_play


def _redraw(context) -> None:
    for area in context.window.screen.areas:
        if area.type == "VIEW_3D":
            area.tag_redraw()


# ── Entry point ───────────────────────────────────────────────────────────────

def play(game, *, sensitivity: float = 1.0, fullscreen: bool = True,
         source=None, on_quit=None) -> dict:
    """
    Build the world, then hand it to a human.

    `game` is an unbuilt `kernel.Game`. This runs the same `build()` the batch
    path runs — same level, same actors, same HUD — so what is played is what
    was rendered, not a second implementation of it.
    """
    bpy = _bpy()
    from . import kernel  # noqa: PLC0415  (circular at module level)

    if bpy.app.background:
        # Checked before anything is built, and checked against this flag rather
        # than against "is there a viewport": a background Blender still reports
        # the startup file's areas, so looking for a VIEW_3D finds one and the
        # session then runs invisibly, forever, with nobody able to press a key.
        raise RuntimeError(
            "interactive play needs a Blender window: launch without "
            "--background. To drive the same rules headlessly, record a session "
            "and re-run it with --replay-input."
        )

    kernel.reset_scene()
    kernel.setup_world_from_spec(game.spec)
    game.build()
    if game.camera is None:
        raise RuntimeError(f"{type(game).__name__}.build() set no camera")

    game.interactive = True
    if source is None:
        source = controls_mod.KeyboardSource(game.genre, fps=game.fps,
                                            sensitivity=sensitivity)
    game.controls = controls_mod.Controls()

    area = prepare_window(game, fullscreen=fullscreen)
    if area is None:
        raise RuntimeError("no 3D viewport in this window to play in")

    operator = make_operator(game, source, on_quit=on_quit)
    bpy.utils.register_class(operator)

    print("\n" + controls_mod.help_text(game.genre) + "\n")
    # A timer rather than a direct call: the operator must start from Blender's
    # own event loop, and at script time the window is not yet interactive.
    bpy.app.timers.register(lambda: (bpy.ops.aaagf.play("INVOKE_DEFAULT"), None)[1],
                            first_interval=0.25)
    return {"operator": operator.bl_idname, "source": type(source).__name__}
