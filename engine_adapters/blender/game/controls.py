"""
engine_adapters/blender/game/controls.py

The input surface a human drives, and the two things that can produce it.

Every generated mechanic already separates "what the player wants to do this
tick" from "what the rules do about it" — the scripted policies in
`engine_adapters/blender/examples/` exist to fill exactly that gap. This module
makes that gap an explicit object, so the same rules can be fed by:

- `KeyboardSource` — a live Blender window, keys and mouse (see `interactive.py`)
- `ScriptedSource` — a JSON timeline of held keys, which runs headless and
  renders to video like any other batch job
- nothing at all — the game's own AI policy, unchanged

Why one struct with every genre's fields on it rather than one per genre: the
consumer is a `tick()` that already knows its genre, and a shared struct means
the keyboard handler, the replay format and the debug overlay are written once.
A driving game reading `controls.throttle` and ignoring `controls.light_attack`
costs nothing; three parallel input classes would cost three of everything.

**Held, not edge-triggered.** A source reports what is *down* on this tick, and
the rules decide what a press means. Fighting games need "is block held", a rifle
needs "is the trigger down", and a menu needs "was this just pressed" — the last
one is `Controls.pressed()`, computed against the previous tick rather than
tracked by the source, so a dropped tick cannot lose an edge forever.

人类操作的输入界面，以及能够生成该界面的两种途径。

所有生成的机制都会将“玩家在当前帧的意图”与“规则对此的处理方式”分开——`engine_adapters/blender/examples/`目录下的脚本化策略正是为了填补这一空白。本模块将该空白转化为一个显式的对象，以便以下来源能共用同一套规则：

- `KeyboardSource`：实时运行的Blender窗口，包含键盘和鼠标输入（详见`interactive.py`）
- `ScriptedSource`：记录按键状态的JSON时间线，可无头运行并像其他批量任务一样渲染为视频
- 什么都不提供：直接使用游戏自身的人工智能策略，无需改动

为何采用包含所有类型字段的单一结构体，而非按类型拆分：因为调用方是已经知晓游戏类型的`tick()`函数，使用共享结构体意味着键盘处理逻辑、回放格式和调试覆盖层只需编写一次。赛车游戏读取`controls.throttle`而忽略`controls.light_attack`不会产生任何额外开销；若采用三个独立的输入类，则所有相关组件都需重复编写三份。
**采用持续按住检测模式，而非边沿触发模式。** 输入源仅报告当前帧中处于按下状态的键，具体按压行为由规则判定。格斗游戏需要判断“是否按住格挡键”，步枪需要判断“扳机是否按下”，菜单则需要判断“是否刚刚被按下”——最后一种情况通过`Controls.pressed()`函数实现，该函数基于上一帧状态计算，而非由输入源跟踪，因此即使某帧数据丢失，也不会永久丢失该操作信号。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

#: Degrees of view rotation per pixel of mouse movement. Roughly a 400 dpi
#: mouse at a normal sensitivity; `interactive.py` scales it by a CLI factor.
# 每像素鼠标移动对应的视角旋转角度。该数值对应常规灵敏度下400 DPI的鼠标；`interactive.py`会根据命令行参数对其缩放。
MOUSE_DEGREES_PER_PIXEL = 0.12

#: How fast the arrow-key fallback turns, in degrees a second. Present because
#: mouse capture is the first thing to break over a remote display, and a game
#: you cannot aim in is not testable.
# 方向键替代控制的旋转速度，单位为每秒度数。设置该参数的原因是远程显示环境下鼠标捕获功能最容易失效，而无法瞄准的游戏是无法进行测试的。
KEY_TURN_DEGREES_PER_SECOND = 130.0


@dataclass
class Controls:
    """
    One tick of intent. Axes are −1..1, buttons are held flags.

    Nothing here is in world units: `move_y = 1.0` is "forward as fast as this
    character goes", not a velocity. The rules own the speeds, which is what
    lets a spec change a car's top speed without touching the input path.

    一帧内的玩家操作意图。轴向数值范围为−1到1，按钮对应按住状态标志。
    这里的所有数值并非以世界单位表示：`move_y = 1.0` 的含义是“以该角色的最大速度向前移动”，而非指速度值。
    速度规则由系统本身定义，正因如此，即便不修改输入逻辑，也能通过规则调整车辆的最高时速。
    """
    # Movement, camera-relative for walkers and track-relative for drivers.
    move_x: float = 0.0          # + strafes right
    move_y: float = 0.0          # + moves forward
    # Aim, in degrees applied this tick — a delta, because a mouse has no
    # absolute position and a controller stick would be scaled to one.
    yaw_delta: float = 0.0
    pitch_delta: float = 0.0
    # Driving
    throttle: float = 0.0
    brake: float = 0.0
    steer: float = 0.0           # + steers right
    handbrake: bool = False
    # Buttons
    fire: bool = False
    reload: bool = False
    run: bool = False
    jump: bool = False
    light_attack: bool = False
    heavy_attack: bool = False
    block: bool = False
    # Session
    quit: bool = False
    pause: bool = False

    #: What was held on the previous tick, for `pressed()`. Not part of intent.
    previous: Optional["Controls"] = field(default=None, repr=False, compare=False)

    def pressed(self, name: str) -> bool:
        """True on the first tick a button is down — a press, not a hold."""
        if not getattr(self, name, False):
            return False
        return not (self.previous is not None and getattr(self.previous, name, False))

# ── Key bindings ──────────────────────────────────────────────────────────────

#: `field: (keys that push it +1, keys that push it −1)`.
#: Arrow keys shadow WASD everywhere so a keyboard with either hand works.
AXIS_BINDINGS: dict[str, dict[str, tuple]] = {
    "fps": {
        "move_y": (("W", "UP_ARROW"), ("S", "DOWN_ARROW")),
        "move_x": (("D",), ("A",)),
        "steer": (("RIGHT_ARROW",), ("LEFT_ARROW",)),   # fallback turning
    },
    "racing": {
        "throttle": (("W", "UP_ARROW"), ()),
        "brake": (("S", "DOWN_ARROW"), ()),
        "steer": (("D", "RIGHT_ARROW"), ("A", "LEFT_ARROW")),
    },
    "fighting": {
        # One axis, because a fighting game is a line. + is screen-right.
        "move_x": (("D", "RIGHT_ARROW"), ("A", "LEFT_ARROW")),
    },
    "rpg": {
        "move_y": (("W", "UP_ARROW"), ("S", "DOWN_ARROW")),
        "move_x": (("D",), ("A",)),
    },
}

#: `field: keys that hold it down`.
BUTTON_BINDINGS: dict[str, dict[str, tuple]] = {
    "fps": {
        "fire": ("LEFTMOUSE", "SPACE"),
        "reload": ("R",),
        "run": ("LEFT_SHIFT", "RIGHT_SHIFT"),
        "jump": ("E",),
    },
    "racing": {
        "handbrake": ("SPACE",),
        "run": ("LEFT_SHIFT", "RIGHT_SHIFT"),           # boost, where a game has one
    },
    "fighting": {
        "light_attack": ("J", "LEFTMOUSE"),
        "heavy_attack": ("K", "RIGHTMOUSE"),
        "block": ("L", "LEFT_SHIFT", "RIGHT_SHIFT"),
        "jump": ("SPACE",),
    },
    "rpg": {
        "fire": ("LEFTMOUSE", "SPACE"),
        "run": ("LEFT_SHIFT", "RIGHT_SHIFT"),
        "jump": ("E",),
    },
}

#: Same in every genre, and never bound to gameplay.
SESSION_BINDINGS = {"quit": ("ESC",), "pause": ("P",)}


def help_text(genre: str) -> str:
    """The one-screen control list, printed at start and drawn in the corner."""
    lines = {
        "fps": ["WASD / arrows  move", "mouse  aim", "left mouse or SPACE  fire",
                "R  reload", "SHIFT  run", "← →  turn (if the mouse is not captured)"],
        "racing": ["W / ↑  throttle", "S / ↓  brake", "A D / ← →  steer",
                   "SPACE  handbrake"],
        "fighting": ["A D / ← →  step", "J or left mouse  light attack",
                     "K or right mouse  heavy attack", "L or SHIFT  block"],
    }.get(genre, ["WASD  move"])
    return "\n".join(lines + ["P  pause", "ESC  quit"])


def bindings_for(genre: str) -> tuple[dict, dict]:
    """Axis and button tables for a genre, falling back to the FPS set."""
    axes = AXIS_BINDINGS.get(genre, AXIS_BINDINGS["fps"])
    buttons = BUTTON_BINDINGS.get(genre, BUTTON_BINDINGS["fps"])
    return axes, buttons


def from_held(held: Iterable[str], genre: str, *, dt: float = 1 / 30,
              mouse_dx: float = 0.0, mouse_dy: float = 0.0,
              sensitivity: float = 1.0,
              previous: Optional[Controls] = None) -> Controls:
    """
    Turn a set of currently-down key names into one tick of `Controls`.

    Held keys rather than a stream of press events on purpose: a tick that takes
    35 ms instead of 33 ms must not drop a step of movement, and asking "is W
    down now" cannot drift out of sync the way a queue of presses can.
    """
    down = {str(k) for k in held}
    axes, buttons = bindings_for(genre)
    controls = Controls(previous=previous)
    if previous is not None:
        # Keep the chain exactly one tick deep. `pressed()` only ever looks back
        # one, and left linked the ticks form a list that never frees: a session
        # is minutes long at 30 Hz, and none of it is wanted.
        previous.previous = None

    for name, (positive, negative) in axes.items():
        value = 0.0
        if any(k in down for k in positive):
            value += 1.0
        if any(k in down for k in negative):
            value -= 1.0
        setattr(controls, name, value)

    for name, keys in buttons.items():
        setattr(controls, name, any(k in down for k in keys))
    for name, keys in SESSION_BINDINGS.items():
        setattr(controls, name, any(k in down for k in keys))

    # Yaw is negated and pitch is not: actors here face +Y and increasing yaw
    # turns left (`camera_rigs.forward`), while Blender's mouse Y already grows
    # upward. So moving the mouse right turns right and pushing it forward looks
    # up, which is what every shooter does.
    controls.yaw_delta = -mouse_dx * MOUSE_DEGREES_PER_PIXEL * sensitivity
    controls.pitch_delta = mouse_dy * MOUSE_DEGREES_PER_PIXEL * sensitivity

    # Arrow-key turning for the FPS, where `steer` is not otherwise used: it is
    # the same intent as a mouse delta, so it is folded into the same field
    # instead of giving the rules a second thing to read.
    if genre == "fps" and controls.steer:
        controls.yaw_delta -= controls.steer * KEY_TURN_DEGREES_PER_SECOND * dt
        controls.steer = 0.0

    return controls


# ── Sources ───────────────────────────────────────────────────────────────────

class ScriptedSource:
    """
    A recorded input timeline, so a human-driven run can be reproduced headless.

    The point of this is not to fake a player. It is that the interactive path
    and the batch path must be the *same* path: if holding W for two seconds
    produces a different run in a window than it does in a render, then the
    video is not evidence of anything. A scripted source drives the identical
    `Controls` surface with no window, no timer and no wall clock.

    Timeline format (`spans`), seconds and key names::

        [{"from": 0.0, "to": 1.5, "keys": ["W"]},
         {"from": 1.2, "to": 1.3, "keys": ["LEFTMOUSE"]},
         {"at": 2.0, "mouse": [40, 0]}]

    Overlapping spans union, which is what holding two keys means.

    一种记录好的输入时间线，可用于在无界面环境下复现人类操作的过程。
    设计该类的目的并非模拟玩家行为。关键在于交互路径与批量渲染路径必须完全一致：如果按住W键两秒后在窗口中运行的结果与渲染出的结果不同，那么生成的视频就无法作为有效依据。ScriptedSource无需窗口、计时器或系统时钟，就能驱动完全一致的`Controls`数据。

    时间线格式（`spans`），包含秒数与按键名称：

        [{"from": 0.0, "to": 1.5, "keys": ["W"]},
         {"from": 1.2, "to": 1.3, "keys": ["LEFTMOUSE"]},
         {"at": 2.0, "mouse": [40, 0]}]

    重叠的时间段会合并，这对应了同时按下多个按键的情况。
    """

    def __init__(self, spans: list, genre: str, *, fps: int = 30,
                 sensitivity: float = 1.0) -> None:
        self.spans = list(spans or [])
        self.genre = genre
        self.fps = int(fps)
        self.sensitivity = float(sensitivity)
        self._previous: Optional[Controls] = None

    @classmethod
    def from_file(cls, path: str | Path, genre: str, **kwargs) -> "ScriptedSource":
        import json  # noqa: PLC0415

        data = json.loads(Path(path).read_text(encoding="utf-8"))
        spans = data["spans"] if isinstance(data, dict) else data
        return cls(spans, genre, **kwargs)

    def _tick(self, seconds: float) -> int:
        """
        Seconds to the tick they name.

        Every comparison here goes through this rather than comparing the floats
        directly. A timeline stores rounded seconds, and tick times are thirds of
        a hundredth — so `0.0333… < 0.033` decides a key was released a frame
        early, and one frame of a held trigger is one shot. Rounding to the
        nearest tick makes the boundaries exact, and ticks are what the
        simulation is counting in anyway.

        此处所有的比较操作都会经过这一步骤，而非直接对比浮点数。时间轴存储的是四舍五入后的秒数，而刻度时间则是百分之一秒的三分之一——因此 `0.0333… < 0.033` 这一判断会判定某个按键在一帧前就被释放了，而持续触发的按键在一帧内的输入仅会被算作一次触发。将时间四舍五入为最近的刻度后，时间边界就变得精确了，况且模拟程序本身也正是以刻度作为计数单位的。
        """
        return int(round(float(seconds) * self.fps))

    def held_at(self, t: float) -> set:
        tick = self._tick(t)
        down: set = set()
        for span in self.spans:
            if "at" in span:
                if self._tick(span["at"]) == tick:
                    down.update(span.get("keys", ()))
            elif self._tick(span.get("from", 0.0)) <= tick < self._tick(span.get("to", 0.0)):
                down.update(span.get("keys", ()))
        return down

    def mouse_at(self, t: float) -> tuple:
        tick = self._tick(t)
        dx = dy = 0.0
        for span in self.spans:
            mouse = span.get("mouse")
            if not mouse:
                continue
            if "at" in span:
                if self._tick(span["at"]) == tick:
                    dx += float(mouse[0])
                    dy += float(mouse[1])
            elif self._tick(span.get("from", 0.0)) <= tick < self._tick(span.get("to", 0.0)):
                # Spread over the span, so a sweep is a sweep and not a snap.
                dx += float(mouse[0]) / self.fps
                dy += float(mouse[1]) / self.fps
        return dx, dy

    def poll(self, t: float) -> Controls:
        """The `Controls` for the tick at time `t`."""
        dx, dy = self.mouse_at(t)
        controls = from_held(self.held_at(t), self.genre, dt=1.0 / self.fps,
                             mouse_dx=dx, mouse_dy=dy,
                             sensitivity=self.sensitivity,
                             previous=self._previous)
        self._previous = controls
        return controls


class KeyboardSource:
    """
    Live input from a Blender window, filled in by the modal operator.

    It holds no Blender types: the operator pushes key-down and key-up names in
    and this keeps the held set. That keeps every rule about what a key *means*
    in one file, and makes the whole thing testable without a window.

    来自Blender窗口的实时输入，由模态操作符填充数据。

    该类不依赖任何Blender类型：操作符会将按键按下和松开的名称传入，此类则负责维护当前按下的按键集合。这样一来，所有关于按键功能的规则都集中在同一个文件中，无需依赖窗口就能对整个功能进行测试。
    """

    def __init__(self, genre: str, *, fps: int = 30,
                 sensitivity: float = 1.0) -> None:
        self.genre = genre
        self.fps = int(fps)
        self.sensitivity = float(sensitivity)
        self.held: set = set()
        self._mouse = [0.0, 0.0]
        self._previous: Optional[Controls] = None
        self.log: list[dict] = []
        self._open_span: Optional[dict] = None

    def key_down(self, name: str) -> None:
        self.held.add(str(name))

    def key_up(self, name: str) -> None:
        self.held.discard(str(name))

    def mouse_moved(self, dx: float, dy: float) -> None:
        """Accumulate between ticks — several mouse events arrive per frame."""
        self._mouse[0] += float(dx)
        self._mouse[1] += float(dy)

    def poll(self, t: float) -> Controls:
        dx, dy = self._mouse
        self._mouse = [0.0, 0.0]
        controls = from_held(self.held, self.genre, dt=1.0 / self.fps,
                             mouse_dx=dx, mouse_dy=dy,
                             sensitivity=self.sensitivity,
                             previous=self._previous)
        self._previous = controls
        self._record(t, controls)
        return controls

    def _record(self, t: float, controls: Controls) -> None:
        """
        Append this tick to a replayable timeline.

        A session worth playing is a session worth re-rendering at full quality,
        and the only reliable way to get the same run twice is to keep the input
        rather than the outcome. Runs of identical keys collapse into one span;
        mouse movement is kept per tick, because a look is a shape over time and
        merging two sweeps into one average is a different look.

        将当前帧的输入数据追加到可回放的时间线中。
        值得回放的关卡必然也值得以全画质重新渲染，而要确保两次运行结果完全一致，唯一可靠的方式就是记录输入而非最终输出。相同的按键组合会被合并为一个时间段；而鼠标移动数据则按帧单独记录，因为视角变化是随时间连续变化的过程，将两个连续的鼠标移动轨迹合并成平均值会导致视角表现不一致。
        """
        end = round(t + 1.0 / self.fps, 4)
        keys = sorted(self.held - set(SESSION_BINDINGS["quit"]))
        # The open key-span is tracked by reference rather than as `log[-1]`,
        # because a mouse entry for this same tick may already sit at the end.
        if self._open_span is not None and self._open_span["keys"] == keys:
            self._open_span["to"] = end
        else:
            self._open_span = {"from": round(t, 4), "to": end, "keys": keys}
            self.log.append(self._open_span)

        if controls.yaw_delta or controls.pitch_delta:
            # Stored as the raw pixel delta the mouse produced, so a replay at a
            # different sensitivity is still the same gesture. Four decimals
            # because aiming is a feedback loop: a hundredth of a pixel of error
            # per tick is a missed shot a few hundred ticks later, and from there
            # the two runs are simply different fights.
            scale = MOUSE_DEGREES_PER_PIXEL * self.sensitivity
            self.log.append({"at": round(t, 4),
                             "mouse": [round(-controls.yaw_delta / scale, 4),
                                       round(controls.pitch_delta / scale, 4)]})

    def timeline(self) -> dict:
        return {"genre": self.genre, "fps": self.fps, "spans": self.log}
