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
"""

import time
from typing import Optional

from . import controls as controls_mod
from . import recorder

#: How many simulation steps one frame may run to catch up. Beyond this the
#: session accepts being behind: the alternative is a stall that gets longer
#: every frame, which is how a slow render turns into a frozen window.
MAX_CATCHUP_TICKS = 4

#: Viewport shading. `MATERIAL` is EEVEE with the scene's materials and is what
#: makes the emissive HUD and the glow pools read; `RENDERED` also works but
#: pays for the world's ambient sampling every frame.
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
    """
    bpy = _bpy()
    scene = bpy.context.scene
    scene.camera = game.camera
    # EEVEE for interactivity. Cycles in a viewport is a slideshow, and the
    # generated materials are flat emissive-and-diffuse, which EEVEE renders
    # near-identically to the Cycles video.
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
    space.shading.use_scene_world = True
    space.shading.use_scene_lights = True
    # The overlays are Blender's, not the game's: gizmos, grid and the text in
    # the corner all draw over the HUD and none of them are part of the game.
    space.overlay.show_overlays = False
    space.show_gizmo = False
    # Hiding a region re-inits the area, and that reads the window from the
    # context rather than from the area. A startup script has no context window,
    # so it has to be supplied here or the re-init dereferences null.
    with bpy.context.temp_override(window=window, area=area):
        space.show_region_ui = False
        space.show_region_toolbar = False
        space.show_region_header = False

    if fullscreen:
        _fullscreen(bpy, window, area)
    return area


def _largest_view3d(bpy):
    """The biggest 3D viewport, and the window it lives in."""
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
        """One fixed step of the game. False means the session should end."""
        game = self.game
        # Sampled at the time of the tick it will drive, which is the same
        # instant `Game.run()` samples a replay at. Polling at the *current*
        # time and then advancing looks equivalent and is not: it shifts every
        # input one tick earlier than the replay of it, and a replay that does
        # not reproduce the session is worse than no replay at all.
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
