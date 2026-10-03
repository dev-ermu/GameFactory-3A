"""
Versus fighting game — generated mechanic, Blender runtime.

Rules implemented
-----------------
Two fighters on a 1D fight line with a real state machine and real frame data:
every attack has startup, active and recovery windows measured in ticks, and a
hitbox that only exists during the active window. Blocking, chip damage,
hitstun, pushback, combo counting, round wins and a round timer are all
consequences of that, not separate systems.

Why frame data rather than a distance check
-------------------------------------------
"Close enough and pressing attack" gives a game with no depth and nothing to
show: no whiff punishing, no trades, no reason to block. Startup means an
attack is a commitment; recovery means a whiffed heavy is a free punish; active
frames mean two attacks can trade. All the interesting events in the report —
punishes, trades, blocked strings — fall out of those three numbers, and they
are in `spec.json` so the balance can be regenerated without touching code.

Both fighters are AI. They differ only in the aggression / block / heavy
weights the spec gives them, which is enough to make the two read as different
characters on screen.
"""

import os
import sys
from math import cos, radians, sin
from pathlib import Path
from random import Random


def _bootstrap_repo_root() -> Path:
    env = os.environ.get("GAMEFACTORY3A_ROOT") or os.environ.get("AAAGF_REPO_ROOT")
    if env and (Path(env) / "engine_adapters").is_dir():
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        if (parent / "engine_adapters" / "blender" / "game").is_dir():
            return parent
    raise RuntimeError("cannot locate the GameFactory-3A repo root; set GAMEFACTORY3A_ROOT")


_ROOT = _bootstrap_repo_root()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine_adapters.blender.game import (  # noqa: E402
    assets, camera_rigs, clips, figures, hud, kernel, materials, prims,
)

IDLE, WALK, ATTACK, BLOCK, HITSTUN, KO = "idle", "walk", "attack", "block", "hitstun", "ko"

#: How long a human's attack press is remembered while the fighter is busy.
#: Six frames at 30 Hz is 200 ms — long enough to press just before recovery
#: ends, short enough that a press cannot come out a second later as a surprise.
INPUT_BUFFER_TICKS = 6

#: Skeleton heights, in metres above the floor. Collected here because the body
#: is assembled from stacked primitives and the segments have to meet: a figure
#: whose hips are a centimetre above its legs reads as broken from ten metres
#: away, and the legs-to-total ratio is most of what makes it read as a person
#: rather than a bollard.
LEG_HALF = 0.39      # legs span 0 .. 0.78
HIP_HEIGHT = 0.86    # waist pivot, and where the lean bends
TORSO_Z = 1.18
ARM_Z = 1.22
HEAD_Z = 1.62        # top of head ≈ 1.82 m
SHOULDER_X = 0.10    # inside the torso, so the arm is never rooted in mid-air

#: Height a character model is normalised to, in metres: the crown of the block
#: figure's head sphere. Quoted off the blocks rather than off a person because
#: the blocks are what the pose — and therefore the hitbox — is measured in, and a
#: model that does not agree with them punches from the wrong shoulder.
FIGURE_HEIGHT = HEAD_Z + 0.20

#: Yaw, in the actor convention `figures.face` speaks (0 is +Y), that turns a
#: figure to look down +X. Fighters face along the fight line, so a fighter's
#: `facing` of +-1 is this angle times that sign.
FACING_YAW = -90.0

#: Which arm throws the lead punch. `figures.reach` takes >= 0 as the right one,
#: and the block body's lead arm is on the same side.
LEAD_ARM = 1

#: Where the layers of the back of the stage sit, in metres along +Y.
#:
#: Separated rather than shared, and the numbers are the whole reason this is a
#: named block: the kit's wall is 1.2 m deep once scaled and its column 1.2 m
#: square, so putting both on the primitive pillar's own y buries one inside the
#: other and the two z-fight into a smear of stone. The columns stand *proud* of
#: the wall, which is what an engaged column does anyway, and the clutter stands
#: clear of both — and of the fight, which is the front two thirds of the stage.
WALL_Y = 5.0
COLUMN_Y = 4.2
CLUTTER_Y = (3.05, 3.65)

#: How far the arms come up when a fighter is merely standing. Not zero: a
#: fighting game's idle is a stance, and arms hanging at the sides read as a
#: bystander who wandered into the ring.
IDLE_GUARD = 0.34


class Fighter:
    """
    One character: a state machine, a body of primitives, and its own AI.

    The body faces along the fight line (the X axis), not along +Y like actors
    in the other genres, because a side-on camera wants the character's profile
    and its reach measured in screen-horizontal metres. `facing` is +1 or -1 and
    is the only orientation this genre needs.
    """

    def __init__(self, game, name: str, color, *, x: float, facing: int,
                 stats: dict, style: dict, model: str | None = None):
        self.game = game
        self.name = name
        self.stats = stats
        self.style = style
        self.max_hp = float(stats["hp"])
        self.hp = self.max_hp
        self.x = x
        self.y = 0.0
        self.facing = facing
        self.state = IDLE
        self.state_ticks = 0
        self.attack: dict | None = None
        self.attack_tick = 0
        self.hit_registered = False
        self.combo = 0
        self.max_combo = 0
        self.rounds_won = 0
        self.landed = 0
        self.blocked = 0
        self.whiffed = 0
        self.taken = 0
        self.opponent: "Fighter" | None = None
        self.lean = 0.0
        #: Metres of ground covered, for the stride cycle. Distance rather than a
        #: clock, so the legs stop when the fighter does — see `figures.walk`.
        self.walked = 0.0
        self._last_x = x

        skin = materials.solid(f"fight_{name}_skin", color, roughness=0.45)
        trim = materials.solid(f"fight_{name}_trim",
                               tuple(min(1.0, c * 1.5 + 0.12) for c in color),
                               roughness=0.35, metallic=0.5)
        dark = materials.solid("fight_dark", (0.07, 0.07, 0.09), roughness=0.6)

        # Two nested roots, and the split matters. `root` is on the floor and
        # carries position and the knockout topple. `waist` sits at hip height
        # and carries the lean, so leaning forward for a punch bends the body
        # over planted feet instead of tipping the whole fighter like a skittle.
        # Everything above the hips therefore hangs off `waist` in *waist* space,
        # which is why the z offsets below are measured from HIP_HEIGHT.
        self.root = prims.empty(f"fighter_{name}", location=(x, 0.0, 0.0),
                                into="Actors")
        self.waist = prims.empty(f"fighter_{name}_waist",
                                 location=(0.0, 0.0, HIP_HEIGHT), into="Actors")
        self.waist.parent = self.root

        self.hips = prims.spawn(prims.BOX, f"{name}_hips", location=(0.0, 0.0, 0.0),
                                scale=(0.17, 0.22, 0.14), material=trim,
                                into="Actors", parent=self.waist)
        self.torso = prims.spawn(prims.BOX, f"{name}_torso",
                                 location=(0.0, 0.0, TORSO_Z - HIP_HEIGHT),
                                 scale=(0.19, 0.25, 0.30), material=skin,
                                 into="Actors", parent=self.waist)
        self.head = prims.spawn(prims.SPHERE, f"{name}_head",
                                location=(0.0, 0.0, HEAD_Z - HIP_HEIGHT),
                                scale=(0.18, 0.19, 0.20), material=skin,
                                into="Actors", parent=self.waist)
        self.visor = prims.spawn(
            prims.BOX, f"{name}_visor",
            location=(0.15 * facing, 0.0, HEAD_Z - HIP_HEIGHT + 0.02),
            scale=(0.06, 0.14, 0.05),
            material=materials.glow(f"fight_{name}_eye", (1.0, 0.85, 0.25),
                                    strength=1.2),
            into="Actors", parent=self.waist, shadow=False, collide=False)

        # A fighting stance, not a standing pose: lead leg forward, back leg
        # braced. Side on, two legs at the same x would read as one post.
        self.legs = [
            prims.spawn(prims.CYLINDER, f"{name}_leg{side}",
                        location=(along * facing, 0.13 * side, LEG_HALF),
                        scale=(0.085, 0.095, LEG_HALF),
                        material=dark, into="Actors", parent=self.root)
            for side, along in ((1, 0.17), (-1, -0.15))
        ]

        # The lead arm is the one that punches; it is animated by moving this
        # object in the waist's local space, so the hitbox and the picture come
        # from the same number.
        self.arm = prims.spawn(prims.CYLINDER, f"{name}_arm", scale=(0.095, 0.095, 0.30),
                               material=skin, into="Actors", parent=self.waist)
        # Glove, not chrome. On `trim` the fist is a metallic ball reflecting the
        # sky, and against a matte arm the eye reads two objects with a gap
        # between them rather than one limb.
        glove = materials.solid(f"fight_{name}_glove",
                                tuple(min(1.0, c * 1.25 + 0.06) for c in color),
                                roughness=0.5)
        self.fist = prims.spawn(prims.SPHERE, f"{name}_fist", scale=(0.125, 0.125, 0.125),
                                material=glove, into="Actors", parent=self.waist)
        self.back_arm = prims.spawn(prims.CYLINDER, f"{name}_backarm",
                                    location=(-0.13 * facing, -0.24,
                                              TORSO_Z - HIP_HEIGHT + 0.04),
                                    rotation=(radians(18), 0.0, 0.0),
                                    scale=(0.085, 0.085, 0.24), material=skin,
                                    into="Actors", parent=self.waist)
        self.guard = prims.spawn(
            prims.BOX, f"{name}_guard",
            location=(0.30 * facing, 0.0, TORSO_Z - HIP_HEIGHT),
            scale=(0.05, 0.24, 0.28),
            material=materials.glow(f"fight_{name}_guard", (0.30, 0.62, 0.95),
                                    strength=0.95),
            into="Actors", parent=self.waist, shadow=False, collide=False,
            visible=False)

        for obj in (self.root, self.waist, self.arm, self.fist, self.torso, self.head):
            game.recorder.track(obj, channels=("location", "rotation_euler"))
        game.recorder.track(self.guard, channels=("hide_render",))
        self._rest_arm()

        # A character model over the blocks, if the task named one. Hung on
        # `root` rather than `waist` because the model brings its own hip joint:
        # `figures.lean` bends it at that, and doubling the bend by hanging it off
        # an already-leaning waist folds the figure in half.
        #
        # The blocks are veiled, not deleted, and that is the same rule the
        # shooter follows for a different reason. Nothing here ray-casts — a
        # fighting game's hitbox is arithmetic — but the arithmetic reads
        # `self.fist.location`, so the block pose *is* the hitbox and it has to
        # keep being computed whether or not anyone can see it. `self.guard` is
        # left alone: it is a readability affordance rather than anatomy, and a
        # glowing plate in front of a blocking character is wanted either way.
        self.figure = None
        self.clip = None
        if model:
            source = assets.source(model)
            skinned = source is not None and any(o.type == "ARMATURE" for o in source.objects)
            veil = (self.hips, self.torso, self.head, self.visor, self.arm,
                    self.fist, self.back_arm, *self.legs)
            if skinned:
                self.clip = clips.attach(model, f"fighter_{name}_clip", host=self.root,
                                         height=FIGURE_HEIGHT, into="Actors", veil=veil)
                if self.clip is not None:
                    self.clip.track(game.recorder)
            else:
                self.figure = figures.attach(
                    model, f"fighter_{name}_model", host=self.root,
                    height=FIGURE_HEIGHT, into="Actors", veil=veil)
                if self.figure is not None:
                    self.figure.track(game.recorder)

    # ── posing ────────────────────────────────────────────────────────────────

    def _rest_arm(self, extend: float = 0.0, crouch: float = 0.0) -> None:
        """
        Place the lead arm. `extend` 0 -> guard, 1 -> fully committed.

        Reach is deliberately read back off this pose by `fist_x()` rather than
        stored separately: a hitbox that does not track the visible fist is how
        a fighting game ends up with hits that visibly miss.
        """
        reach = max(0.26, 0.30 + extend * float(self.stats["reach"]))
        z = ARM_Z - HIP_HEIGHT - crouch * 0.16 - extend * 0.02

        # Span the gap rather than guess at it. The upper arm runs from a fixed
        # shoulder inside the torso to wherever the fist is, so the two are
        # joined at every value of `extend` — including the wind-up, where the
        # fist comes back past a fixed-length arm and used to float free of it.
        shoulder = SHOULDER_X * self.facing
        fist = reach * self.facing
        self.arm.location = ((shoulder + fist) * 0.5, -0.02, z)
        self.arm.rotation_euler = (0.0, radians(90.0 * self.facing), 0.0)
        self.arm.scale = (0.095, 0.095, max(0.10, abs(fist - shoulder) * 0.5))
        self.fist.location = (fist, -0.02, z)

    def fist_x(self) -> float:
        """
        World x of the fist — the hitbox.

        Computed rather than read off `matrix_local`, which is only refreshed on
        a depsgraph update and would be one tick stale here. Leaning into a
        punch rotates the fist about the waist, worth a few centimetres of reach
        at full commit; the trig is cheap and keeps hitbox and picture identical.
        """
        fx, _, fz = self.fist.location
        return self.x + fx * cos(self.lean) + fz * sin(self.lean)

    def pose(self) -> None:
        """Push simulation state onto the body once per tick."""
        # Only stepping counts toward the stride. Pushback and the separation
        # shove move `x` too, and folding those in makes a fighter's legs shuffle
        # every time it gets hit — a walk cycle advancing without a walk, which is
        # the tell distance-driven animation exists to avoid.
        travelled = abs(self.x - self._last_x)
        self._last_x = self.x
        if self.state == WALK:
            self.walked += travelled

        crouch = 0.0
        lean = 0.0
        extend = 0.0

        if self.state == ATTACK and self.attack is not None:
            a = self.attack
            total = a["startup"] + a["active"] + a["recovery"]
            t = self.attack_tick
            if t < a["startup"]:
                extend = -0.22 * (t / max(1, a["startup"]))       # wind up
                lean = -4.0
            elif t < a["startup"] + a["active"]:
                extend = 1.0
                lean = 9.0
            else:
                remaining = (total - t) / max(1, a["recovery"])
                extend = max(0.0, remaining) * 0.7
                lean = 4.0
        elif self.state == BLOCK:
            crouch, lean, extend = 0.35, -7.0, -0.1
        elif self.state == HITSTUN:
            lean = -16.0
            crouch = 0.25
        elif self.state == KO:
            lean = 0.0
        elif self.state == WALK:
            crouch = 0.06 + 0.05 * sin(self.game.time * 11.0)

        if self.state == KO:
            # Fall flat: this one *is* about the root, which is on the floor, so
            # the whole fighter goes over rather than folding at the waist.
            # A death clip already contains that fall — stacking a root tumble
            # on top of it puts the mesh through the floor.
            fall = min(1.0, self.state_ticks / 12.0)
            if self.clip is None or not self.clip.has("death"):
                self.root.rotation_euler = (0.0, radians(-84.0 * fall * self.facing), 0.0)
                self.root.location = (self.x, 0.0, 0.06 * fall)
            else:
                self.root.rotation_euler = (0.0, 0.0, 0.0)
                self.root.location = (self.x, self.y, 0.0)
            self.lean = 0.0
            self.waist.rotation_euler = (0.0, 0.0, 0.0)
        else:
            self.root.rotation_euler = (0.0, 0.0, 0.0)
            self.root.location = (self.x, self.y, 0.0)
            self.lean = radians(lean * self.facing)
            self.waist.rotation_euler = (0.0, self.lean, 0.0)

        self.waist.location = (0.0, 0.0, HIP_HEIGHT - crouch * 0.12)
        self.torso.location = (0.0, 0.0, TORSO_Z - HIP_HEIGHT - crouch * 0.06)
        self.head.location = (0.0, 0.0, HEAD_Z - HIP_HEIGHT - crouch * 0.10)
        self.guard.hide_render = self.state != BLOCK
        self._rest_arm(extend=extend, crouch=crouch)
        self._pose_figure(crouch=crouch, lean=lean, extend=extend)

    def _pose_figure(self, *, crouch: float, lean: float, extend: float) -> None:
        """
        Drive the character model from the same three numbers the blocks use.

        Fed the *outputs* of `pose` rather than reading the state machine again:
        two readings of one state drift apart on the next edit and the picture
        stops agreeing with the hitbox.
        """
        clip = self.clip
        if clip is not None:
            clip.face(FACING_YAW * self.facing)
            t = self.state_ticks / max(self.game.fps, 1)
            if self.state == KO:
                clip.play("death", t, loop=False)
            elif self.state == ATTACK:
                role = "kick" if self.attack and self.attack.get("name") == "heavy" else "punch"
                played = clip.play(role, t, loop=False)
                if not played and role == "kick":
                    played = clip.play("jump", t, loop=False)
                if not played:
                    clip.play("idle", self.game.time)
                    # Mixamo humans often have no punch clip. A short lunge still
                    # reads as the hit the blocks already registered.
                    pitch = -24.0 * extend if role == "punch" else -10.0
                    clip.root.rotation_euler = (
                        radians(pitch), 0.0,
                        radians(FACING_YAW * self.facing + clip.yaw_offset))
            elif self.state == HITSTUN:
                if not clip.play("hit", t, loop=False):
                    clip.play("idle", self.game.time)
            elif self.state == WALK:
                clip.play("walk", self.walked / 1.4)
            elif self.state == BLOCK:
                if not clip.play("block", t):
                    clip.play("idle", self.game.time)
            else:
                clip.play("idle", self.game.time)
            return

        f = self.figure
        if f is None:
            return
        f.rest()
        f.face(FACING_YAW * self.facing)
        if self.state == KO:
            return

        f.lean(-lean, crouch=crouch * 0.12)
        if self.state == ATTACK:
            reach = max(0.26, 0.30 + extend * float(self.stats["reach"]))
            if self.attack and self.attack.get("name") == "heavy" and f.leg_right is not None:
                f.reach(LEAD_ARM, max(0.0, extend * 0.4), distance=0.22)
                rest, _ = f._rest[f.leg_right]
                f.leg_right.rotation_euler = (rest[0] + radians(-70.0 * extend),
                                              rest[1], rest[2])
            else:
                f.reach(LEAD_ARM, extend, distance=reach)
        elif self.state == BLOCK:
            f.guard()
        elif self.state == HITSTUN:
            f.guard(0.5)
        else:
            f.walk(self.walked)
            f.guard(IDLE_GUARD)

    # ── state machine ─────────────────────────────────────────────────────────

    def enter(self, state: str) -> None:
        self.state = state
        self.state_ticks = 0

    def can_act(self) -> bool:
        return self.state in (IDLE, WALK, BLOCK)

    def start_attack(self, kind: str) -> None:
        self.attack = dict(self.stats["attacks"][kind], name=kind)
        self.attack_tick = 0
        self.hit_registered = False
        self.enter(ATTACK)
        self.game.log("attack_start", fighter=self.name, attack=kind)

    def distance(self) -> float:
        """Metres apart on the fight line. Depth is staging, not the hit axis."""
        return abs(self.opponent.x - self.x)


class ArenaFighter(kernel.Game):
    genre = "fighting"

    default_spec = {
        "duration_sec": 27.0,
        "fps": 30,
        "resolution": (960, 540),
        "samples": 16,
        "seed": 3,
        "sky_color": (0.10, 0.11, 0.19),
        "sky_strength": 0.75,
        "stage_half_width": 7.5,
        "stage_depth": 1.8,
        "sun_shadows": False,
        "rounds_to_win": 2,
        "round_seconds": 12.0,
        "fighters": [
            {
                "name": "vanta", "color": [0.20, 0.45, 0.95],
                "stats": {
                    "hp": 64.0, "walk_speed": 3.1, "reach": 0.62,
                    "attacks": {
                        "jab":   {"damage": 8.0,  "startup": 3, "active": 3,
                                  "recovery": 6,  "pushback": 0.22, "chip": 0.18},
                        "heavy": {"damage": 18.0, "startup": 8, "active": 4,
                                  "recovery": 15, "pushback": 0.75, "chip": 0.22},
                    },
                },
                "style": {"aggression": 0.62, "block": 0.30, "heavy": 0.30},
            },
            {
                "name": "kirin", "color": [0.95, 0.30, 0.22],
                "stats": {
                    "hp": 64.0, "walk_speed": 3.5, "reach": 0.55,
                    "attacks": {
                        "jab":   {"damage": 7.0,  "startup": 2, "active": 3,
                                  "recovery": 5,  "pushback": 0.20, "chip": 0.15},
                        "heavy": {"damage": 20.0, "startup": 9, "active": 4,
                                  "recovery": 17, "pushback": 0.85, "chip": 0.25},
                    },
                },
                "style": {"aggression": 0.72, "block": 0.20, "heavy": 0.36},
            },
        ],
        "hitstun_ticks": 9,
        "block_stun_ticks": 5,
        "combo_window_ticks": 22,
        #: Index into `fighters` that a human takes when playing. 0 is the one
        #: on the left, which is the side the camera favours.
        "human_fighter": 0,
    }

    # ── build ─────────────────────────────────────────────────────────────────

    def build(self) -> None:
        self.half = float(self.spec["stage_half_width"])
        self.rounds_to_win = int(self.spec["rounds_to_win"])
        self.round_ticks = int(float(self.spec["round_seconds"]) * self.fps)

        # Decoration draws from its own stream. Which column is the cracked one
        # must not consume a draw the AI was going to make, or turning the art on
        # would change who wins — and then the two runs cannot be compared, which
        # is the only reason to generate them. Seeded off the spec seed, so the
        # dressing is as reproducible as the fight.
        self.look = Random(self.seed ^ 0x5A17)

        # A sun points along its own -Z, so `rotation_euler.x = θ` sends the
        # light toward `(0, sin θ, -cos θ)` — that is, it arrives *from* -Y,
        # the side the camera is on. Key from the camera side and rim from
        # behind: a side-on fight is silhouettes otherwise, which is what the
        # first pass of this stage looked like.
        # Both energies are spec-driven because the sky is: an HDRI arrives with
        # its own key light baked in, and two suns tuned against a flat gradient
        # then blow the stone out to white. A task that supplies an environment
        # turns these down; one that does not gets the numbers the flat sky wants.
        kernel.add_sun("key", energy=float(self.spec.get("sun_energy", 4.2)),
                       rotation=(radians(54), radians(-10), radians(12)),
                       angle=0.25,
                       shadows=bool(self.spec.get("sun_shadows", False)))
        kernel.add_sun("rim", energy=float(self.spec.get("rim_energy", 2.6)),
                       rotation=(radians(-38), radians(14), radians(-8)),
                       angle=0.4,
                       shadows=bool(self.spec.get("sun_shadows", False)))
        self._build_stage()

        a_spec, b_spec = self._resolve_fighters()
        self.a = Fighter(self, a_spec["name"], tuple(a_spec["color"]),
                         x=-2.6, facing=1, stats=a_spec["stats"],
                         style=a_spec["style"], model=a_spec.get("model"))
        self.b = Fighter(self, b_spec["name"], tuple(b_spec["color"]),
                         x=2.6, facing=-1, stats=b_spec["stats"],
                         style=b_spec["style"], model=b_spec.get("model"))
        self.a.opponent, self.b.opponent = self.b, self.a
        self.fighters = [self.a, self.b]

        # Which corner a player takes. Only consulted when someone is playing;
        # unattended, both fighters run their own style and nothing changes.
        self.human_fighter = self.fighters[int(self.spec.get("human_fighter", 0))]
        self._buffered: list = [None, 0]

        self._build_vfx()
        self._build_camera_and_hud()

        self.round_no = 1
        self.round_tick = 0
        self.round_results: list[dict] = []
        self.match_over = False
        self._last_hit_tick = {self.a.name: -999, self.b.name: -999}

        # Round 1 begins here rather than in `_finish_round`, which only ever
        # sees rounds 2 and 3. Without this the log carries one `round_start`
        # for two `round_end`s, and anyone counting events to reconstruct the
        # match finds the numbers do not add up.
        self.log("round_start", round_no=self.round_no)

    def _resolve_fighters(self) -> list:
        """
        Overlay the spec's fighters on the defaults, entry by entry.

        `Game.__init__` merges nested dicts but replaces lists outright, because
        a partial list has no general meaning. A roster is the exception: the
        two entries are positional and mean the same thing every time, so a task
        that wants a fighter with more health should be able to say exactly that
        without also restating both attacks' frame data. Merging per index gives
        it that, and a task supplying a whole fighter still overrides everything.
        """
        defaults = self.default_spec["fighters"]
        given = self.spec.get("fighters") or defaults
        return [kernel.merge_spec(defaults[i] if i < len(defaults) else {}, entry)
                for i, entry in enumerate(given)]

    def _build_stage(self) -> None:
        floor = materials.solid("fight_floor", (0.24, 0.22, 0.29), roughness=0.55)
        ring = materials.glow("fight_ring", (0.95, 0.35, 0.75), strength=2.0)
        back = materials.solid("fight_back", (0.11, 0.11, 0.17), roughness=0.9)
        pillar = materials.solid("fight_pillar", (0.28, 0.28, 0.36), roughness=0.5,
                                 metallic=0.6)
        lamp = materials.glow("fight_lamp", (0.45, 0.85, 1.0), strength=3.0)

        prims.spawn(prims.BOX_GROUND, "stage", location=(0.0, 0.0, -0.6),
                    scale=(self.half + 1.2, 4.6, 0.3), material=floor, into="Level")
        for side in (-1, 1):
            prims.spawn(prims.BOX, f"stage_edge{side}",
                        location=(self.half * side, 0.0, 0.02),
                        scale=(0.16, 4.6, 0.03), material=ring,
                        into="Level", shadow=False, collide=False)
        prims.spawn(prims.BOX_GROUND, "backdrop", location=(0.0, 5.4, -0.6),
                    scale=(self.half + 6.0, 0.4, 5.2), material=back, into="Level")

        dressed_columns = bool(self._models("column"))
        for i in range(-3, 4):
            column = prims.spawn(prims.BOX_GROUND, f"back_pillar{i}",
                                 location=(i * 3.1, 4.5, -0.3),
                                 scale=(0.42, 0.42, 3.2),
                                 material=pillar, into="Level")
            if dressed_columns:
                # Veiled rather than left showing through the stack: unlike a
                # shooter's cover these blocks are pure scenery — nothing in this
                # genre casts a ray — so there is no shape to keep agreeing with.
                prims.veil(column)
                self._stack_column(i, i * 3.1, COLUMN_Y)
            prims.spawn(prims.BOX, f"back_lamp{i}", location=(i * 3.1, 4.1, 5.4),
                        scale=(0.40, 0.10, 0.10), material=lamp,
                        into="Level", shadow=False, collide=False)

        self._dress_stage()

    # ── dressing ──────────────────────────────────────────────────────────────
    #
    # Everything below is scenery, and scenery in this genre is unusually free:
    # a fighting game's hitbox is `abs(fist_x - opponent.x)`, so there is no ray
    # for a prop to get in the way of and no collider whose proportions a model
    # has to match. The one rule left is the one that matters everywhere — the
    # dressing may not touch `self.rng`, `x`, `facing` or `hp` — and it is kept by
    # drawing from `self.look` and writing only to objects it created.

    def _models(self, key: str) -> list:
        """
        The `models.<key>` references a task gave, always as a list.

        A list rather than one reference because a wall repeated fourteen times
        reads as a loop; drawing from a handful is what makes it read as a place.
        A bare string is accepted and wrapped.
        """
        entry = (self.spec.get("models") or {}).get(key)
        if not entry:
            return []
        return [entry] if isinstance(entry, str) else list(entry)

    def _stack_column(self, index: int, x: float, y: float) -> None:
        """
        Build one back column out of stacked kit segments.

        Stacked rather than stretched, which is the difference between an arena
        column and a smeared one: the kit's column is a metre tall on a 0.6 m
        square, and asking one copy for six metres gives a ten-to-one spike with
        its capital moulding pulled into a thin band. Repeating the segment keeps
        the moulding the size it was drawn at, which is what modular kits are for.

        The top segment may be a damaged variant — a broken column reads as an old
        arena, and the whole point of a list of models is that the choice is the
        task's to make.

        Every segment gets the **same** scale factor, taken once off the whole
        column, rather than each being normalised to the course height. The
        difference is the broken one: it is three quarters of a column by design,
        so making it two metres tall makes it 1.4 times too wide as well, and the
        stack ends in a stone mushroom. One factor keeps the kit's own proportions,
        which is the only reason to pick a modular kit.
        """
        options = self._models("column")
        broken = self._models("column_broken") or options
        pitch = float(self.spec.get("column_segment_metres", 2.0))
        courses = max(1, int(float(self.spec.get("column_metres", 6.0)) / pitch))
        base = assets.source(options[0])
        native = assets.size(base)[2] if base is not None else 0.0
        if native <= 1e-6:
            return
        factor = pitch / native
        for course in range(courses):
            top = course == courses - 1
            assets.instance(
                self.look.choice(broken if top else options),
                f"column{index}_{course}", location=(x, y, course * pitch),
                rotation=(0.0, 0.0, radians(90.0 * self.look.randrange(4))),
                scale=factor, into="Level")

    def _dress_stage(self) -> None:
        """Tile the floor, wall in the back, and put clutter along its foot."""
        self._tile_floor()
        self._build_back_wall()
        self._scatter_clutter()

    def _tile_floor(self) -> None:
        """
        Cover the stage slab with kit floor tiles on a whole-tile grid.

        Sized with `length` and not `height`: a floor tile is a plane with zero
        thickness, and normalising by height divides by that zero. The count comes
        from the slab rather than the pitch from the spec, for the reason the
        shooter's walls did — a leftover remainder is a stripe of flat colour along
        one edge, and here that edge is the one the camera looks across.
        """
        tiles = self._models("floor")
        if not tiles:
            return
        pitch = float(self.spec.get("floor_tile_metres", 2.0))
        span_x, span_y = self.half + 1.2, 4.6
        across = max(1, round(span_x * 2.0 / pitch))
        deep = max(1, round(span_y * 2.0 / pitch))
        step_x, step_y = span_x * 2.0 / across, span_y * 2.0 / deep
        for i in range(across):
            for j in range(deep):
                assets.instance(
                    self.look.choice(tiles), f"floortile{i}_{j}",
                    # A millimetre proud of the slab. Coplanar is the other way to
                    # get a flickering floor, and the slab has to stay: a tile is
                    # a square with nothing under it.
                    location=(-span_x + step_x * (i + 0.5),
                              -span_y + step_y * (j + 0.5), 0.001),
                    rotation=(0.0, 0.0, radians(90.0 * self.look.randrange(4))),
                    length=step_x, into="Level")

    def _build_back_wall(self) -> None:
        """
        A run of kit wall in front of the backdrop slab, gates and all.

        Set in front of the slab rather than replacing it, so a gap between two
        segments shows dark stone instead of the sky — the same reason the
        shooter's panels sit proud of a wall that stays.
        """
        walls = self._models("wall")
        if not walls:
            return
        gates = self._models("wall_gate") or walls
        pitch = float(self.spec.get("wall_segment_metres", 2.0))
        span = (self.half + 6.0) * 2.0
        across = max(1, round(span / pitch))
        courses = max(1, int(float(self.spec.get("wall_metres", 6.0)) / pitch))
        for course in range(courses):
            for k in range(across):
                # Gates belong at ground level and nowhere else. Upstairs they are
                # doorways onto a six-metre drop, which is the mistake the shooter
                # made with its windows.
                pool = gates if (course == 0 and k % 5 == 2) else walls
                assets.instance(
                    self.look.choice(pool), f"backwall{course}_{k}",
                    location=(-span * 0.5 + pitch * (k + 0.5), WALL_Y,
                              course * pitch),
                    height=pitch, into="Level")

    def _scatter_clutter(self) -> None:
        """
        Props along the foot of the back wall, off the fight line.

        Kept to the back strip *and* out of the middle, and the second constraint
        is the one that had to be learnt: the camera is a side view that closes in
        on the two fighters, so a statue behind the centre of the stage ends up
        directly behind the action, and the first pass of this had a trophy growing
        out of a fighter's head. Anything within `keep_clear` of the centre line is
        pushed outward, which leaves the middle of the frame to the fight.
        """
        props = self._models("clutter")
        if not props:
            return
        count = int(self.spec.get("clutter_count", 10))
        clear = float(self.spec.get("clutter_keep_clear", 4.6))
        reach = self.half + 5.0
        for i in range(count):
            offset = self.look.uniform(clear, reach)
            side = 1.0 if self.look.random() < 0.5 else -1.0
            assets.instance(
                self.look.choice(props), f"clutter{i}",
                location=(offset * side,
                          self.look.uniform(*CLUTTER_Y), 0.0),
                rotation=(0.0, 0.0, self.look.uniform(0.0, 6.283)),
                height=self.look.uniform(0.8, 1.6), into="Level")

    def _build_vfx(self) -> None:
        # A hit and a block have to be told apart at a glance, so the two
        # markers differ in colour — which only works if neither clips to white.
        # Under the Standard view transform an emitter is as coloured as its
        # dimmest channel survives, so the strengths stay near 1 and the size
        # carries the impact instead of the brightness.
        hit_mat = materials.glow("fight_hit", (1.0, 0.80, 0.28), strength=1.15)
        block_mat = materials.glow("fight_block", (0.40, 0.80, 1.0), strength=1.0)
        self.impacts = []
        for i in range(6):
            obj = prims.spawn(prims.SPHERE, f"impact{i}", scale=(0.16, 0.16, 0.16),
                              material=hit_mat, into="VFX", shadow=False,
                              collide=False, visible=False)
            self.recorder.track(obj, channels=("location", "scale", "hide_render"))
            self.impacts.append(obj)
        self.block_fx = []
        for i in range(4):
            obj = prims.spawn(prims.SPHERE, f"blockfx{i}", scale=(0.14, 0.14, 0.14),
                              material=block_mat, into="VFX", shadow=False,
                              collide=False, visible=False)
            self.recorder.track(obj, channels=("location", "hide_render"))
            self.block_fx.append(obj)
        self._impact_cursor = 0
        self._block_cursor = 0
        self._expiry: list[tuple] = []

    def _build_camera_and_hud(self) -> None:
        self.camera = camera_rigs.make_camera("fight_cam", lens=48.0)
        self.rig = camera_rigs.SideViewRig(self.camera, height=1.55, distance=6.5,
                                           min_distance=5.2, max_distance=9.5,
                                           stiffness=0.12, margin=2.1)
        self.recorder.track(self.camera, channels=("location", "rotation_euler"))

        self.hud = hud.Hud(self.camera, self.resolution)
        self.hp_a = self.hud.bar("hp_a", (-0.94, 0.86), width=0.40, height=0.055,
                                 color=(0.30, 0.65, 1.0))
        self.hp_b = self.hud.bar("hp_b", (0.94, 0.86), width=0.40, height=0.055,
                                 color=(1.0, 0.38, 0.28), grow_left=True)
        self.hud.label("name_a", self.a.name.upper(), (-0.94, 0.74), size=0.05)
        self.hud.label("name_b", self.b.name.upper(), (0.94, 0.74), size=0.05,
                       align="RIGHT")
        self.round_a = self.hud.pip_row("round_a", (-0.94, 0.68), self.rounds_to_win,
                                        size=0.035, gap=0.055, color=(1.0, 0.85, 0.3))
        self.round_b = self.hud.pip_row("round_b", (0.80, 0.68), self.rounds_to_win,
                                        size=0.035, gap=0.055, color=(1.0, 0.85, 0.3))
        self.timer_bar = self.hud.bar("timer", (-0.12, 0.90), width=0.24,
                                      height=0.035, color=(0.95, 0.95, 0.6))
        self.ko_flash = self.hud.vignette("ko", color=(1.0, 0.85, 0.4),
                                          strength=2.5, alpha=0.30)
        self.hud.register(self.recorder)
        self.round_a.set(0)
        self.round_b.set(0)

    # ── simulation ────────────────────────────────────────────────────────────

    def tick(self) -> None:
        if not self.match_over:
            self.round_tick += 1
            for fighter in self.fighters:
                self._think(fighter)
            for fighter in self.fighters:
                self._advance(fighter)
            self._separate()
            self._resolve_round()

        for fighter in self.fighters:
            fighter.pose()
        self._expire_vfx()
        self._update_hud()

    # ── ai ────────────────────────────────────────────────────────────────────

    def _think(self, f: Fighter) -> None:
        """
        Choose an action. Only fighters that can act get a choice — everything
        else is already committed, which is the whole point of frame data.
        """
        if f.state == KO:
            return
        if self.human and f is self.human_fighter:
            # Ahead of the `can_act` gate: a human's input has to be *seen* on
            # frames they cannot act on, so it can be buffered. See below.
            self._fight_input(f)
            return
        if not f.can_act():
            return

        style = f.style
        distance = f.distance()
        reach = 0.30 + float(f.stats["reach"]) + 0.42
        opponent = f.opponent

        # React to a committed attack: block it, or walk out of its range.
        # Both defences matter — blocking trades chip damage for safety, while
        # stepping back makes the attacker whiff and hands over their whole
        # recovery window. Without the second one nothing ever misses, and an
        # attack that cannot miss is not a commitment.
        threatened = (opponent.state == ATTACK
                      and opponent.attack_tick <= opponent.attack["startup"] + 1
                      and distance < reach + 0.5)
        if threatened:
            roll = self.rng.random()
            if roll < float(style["block"]) * 2.2:
                if f.state != BLOCK:
                    f.enter(BLOCK)
                return
            if roll < float(style["block"]) * 2.2 + 0.16:
                f.x -= float(f.stats["walk_speed"]) * self.dt * 1.6 * f.facing
                if f.state != WALK:
                    f.enter(WALK)
                return

        if distance <= reach:
            if self.rng.random() < float(style["aggression"]):
                kind = "heavy" if self.rng.random() < float(style["heavy"]) else "jab"
                f.start_attack(kind)
            elif self.rng.random() < float(style["block"]):
                f.enter(BLOCK)
            else:
                f.enter(IDLE)
            return

        # A poke thrown at the edge of range: sometimes it catches an advance,
        # sometimes it is the mistake the opponent punishes.
        if (distance <= reach * 1.4
                and self.rng.random() < float(style["aggression"]) * 0.20):
            f.start_attack("jab")
            return

        # Out of range: close, unless deliberately spacing.
        if f.state == BLOCK:
            f.enter(IDLE)
        step = float(f.stats["walk_speed"]) * self.dt
        towards = 1.0 if opponent.x > f.x else -1.0
        backing = self.rng.random() > float(style["aggression"]) + 0.25
        f.x += step * towards * (-0.55 if backing and distance < reach * 2.2 else 1.0)
        # A little depth so the two don't occupy the same silhouette — a small
        # offset, not a walk to opposite walls, or they leave the camera's plane.
        target_y = 0.35 if f is self.a else -0.35
        f.y += (target_y - f.y) * min(1.0, 3.0 * self.dt)
        depth = float(self.spec.get("stage_depth", 1.8))
        f.y = max(-depth, min(depth, f.y))
        f.facing = 1 if opponent.x > f.x else -1
        if f.state != WALK:
            f.enter(WALK)

    # ── the human ─────────────────────────────────────────────────────────────

    def _fight_input(self, f: Fighter) -> None:
        """
        One tick of the player's fighter: buffered attacks, held guard, walking.

        Attacks are edge-triggered and buffered rather than read as a hold. Held
        would mean a player resting on the button attacks on every actionable
        frame, which removes the timing that makes frame data interesting; plain
        edge-triggered without a buffer would drop every press that lands during
        startup, recovery or hitstun, and a game that ignores a third of your
        inputs feels broken rather than strict.
        """
        c = self.controls
        if c.pressed("heavy_attack"):
            self._buffered = ["heavy", INPUT_BUFFER_TICKS]
        elif c.pressed("light_attack"):
            self._buffered = ["jab", INPUT_BUFFER_TICKS]

        if not f.can_act():
            self._buffered[1] = max(0, self._buffered[1] - 1)
            return

        if self._buffered[1] > 0:
            kind = self._buffered[0]
            self._buffered = [None, 0]
            f.start_attack(kind)
            return

        if c.block:
            if f.state != BLOCK:
                f.enter(BLOCK)
            else:
                # Guard held: keep it fresh, or `_advance` times the block out
                # after a few frames and opens a gap the player never asked for.
                f.state_ticks = 0
            return
        if f.state == BLOCK:
            f.enter(IDLE)

        if c.move_x or c.move_y:
            # +X is screen-right; +Y is into the stage, Street-Fighter 2.5D.
            speed = float(f.stats["walk_speed"]) * self.dt
            f.x += float(c.move_x) * speed
            f.y += float(c.move_y) * speed * 0.65
            depth = float(self.spec.get("stage_depth", 1.8))
            f.y = max(-depth, min(depth, f.y))
            if f.state != WALK:
                f.enter(WALK)
        elif f.state != IDLE:
            f.enter(IDLE)

    def _advance(self, f: Fighter) -> None:
        """Run one tick of whatever the fighter is committed to."""
        f.state_ticks += 1

        if f.state == KO:
            return
        if f.state == HITSTUN:
            if f.state_ticks >= int(self.spec["hitstun_ticks"]):
                f.enter(IDLE)
            return
        if f.state == BLOCK:
            if f.state_ticks > int(self.spec["block_stun_ticks"]) * 3:
                f.enter(IDLE)
            return
        if f.state != ATTACK or f.attack is None:
            return

        a = f.attack
        f.attack_tick += 1
        active_from = a["startup"]
        active_to = a["startup"] + a["active"]

        if active_from < f.attack_tick <= active_to and not f.hit_registered:
            self._try_hit(f)

        if f.attack_tick >= active_to + a["recovery"]:
            if not f.hit_registered:
                f.whiffed += 1
                self.log("whiff", fighter=f.name, attack=a["name"])
            f.attack = None
            f.enter(IDLE)

    def _try_hit(self, attacker: Fighter) -> None:
        """
        The hitbox is the fist; the hurtbox is the opponent's torso column.

        Both come from the posed body, so what connects is what the camera sees.
        """
        defender = attacker.opponent
        if defender.state == KO:
            return
        separation = abs(attacker.fist_x() - defender.x)
        if separation > 0.42:
            return

        attacker.hit_registered = True
        a = attacker.attack
        facing_the_hit = defender.facing != attacker.facing

        if defender.state == BLOCK and facing_the_hit:
            chip = float(a["damage"]) * float(a["chip"])
            defender.hp = max(0.0, defender.hp - chip)
            defender.x += a["pushback"] * attacker.facing * 0.6
            attacker.blocked += 1
            defender.enter(BLOCK)
            self._flash(self.block_fx, "block", defender)
            self.log("blocked", attacker=attacker.name, defender=defender.name,
                     attack=a["name"], chip=round(chip, 1),
                     defender_hp=round(defender.hp, 1))
            return

        # Catching a fighter inside their own startup is a counter hit — worth
        # recording separately, because it is the payoff for the whiff-bait.
        if defender.state == ATTACK:
            self.log("counter_hit", attacker=attacker.name, defender=defender.name,
                     interrupted=defender.attack["name"] if defender.attack else None)

        damage = float(a["damage"])
        defender.hp = max(0.0, defender.hp - damage)
        defender.x += a["pushback"] * attacker.facing
        defender.taken += 1
        attacker.landed += 1

        # A combo is a hit that lands before the previous one's stun expired.
        if self.frame - self._last_hit_tick[attacker.name] <= int(
                self.spec["combo_window_ticks"]):
            attacker.combo += 1
        else:
            attacker.combo = 1
        attacker.max_combo = max(attacker.max_combo, attacker.combo)
        self._last_hit_tick[attacker.name] = self.frame

        self._flash(self.impacts, "impact", defender,
                    scale=0.11 + 0.004 * damage)
        self.log("hit", attacker=attacker.name, defender=defender.name,
                 attack=a["name"], damage=round(damage, 1),
                 combo=attacker.combo, defender_hp=round(defender.hp, 1))

        if defender.hp <= 0.0:
            defender.enter(KO)
            self.ko_flash.trigger(5)
            self.log("ko", winner=attacker.name, loser=defender.name,
                     round_no=self.round_no)
        else:
            defender.enter(HITSTUN)
            defender.attack = None

    def _separate(self) -> None:
        """Keep the fighters out of each other and on the stage."""
        gap = self.b.x - self.a.x
        minimum = 0.72
        if abs(gap) < minimum:
            push = (minimum - abs(gap)) * 0.5 * (1.0 if gap >= 0 else -1.0)
            self.a.x -= push
            self.b.x += push
        for f in self.fighters:
            f.x = max(-self.half + 0.4, min(self.half - 0.4, f.x))
            if f.state != KO:
                f.facing = 1 if f.opponent.x > f.x else -1

    # ── rounds ────────────────────────────────────────────────────────────────

    def _resolve_round(self) -> None:
        loser = next((f for f in self.fighters if f.state == KO), None)
        timeout = self.round_tick >= self.round_ticks

        if loser is None and not timeout:
            return
        # Let the knockdown play before resetting.
        if loser is not None and loser.state_ticks < 18:
            return

        if loser is not None:
            winner = loser.opponent
            reason = "ko"
        else:
            winner = max(self.fighters, key=lambda f: f.hp)
            reason = "timeout"

        winner.rounds_won += 1
        self.round_results.append({
            "round": self.round_no, "winner": winner.name, "by": reason,
            "seconds": round(self.round_tick / self.fps, 2),
            "winner_hp_left": round(winner.hp, 1),
        })
        self.log("round_end", round_no=self.round_no, winner=winner.name,
                 by=reason, rounds_won=winner.rounds_won)

        if winner.rounds_won >= self.rounds_to_win:
            self.match_over = True
            self.log("match_end", winner=winner.name,
                     score=f"{self.a.rounds_won}-{self.b.rounds_won}")
            self.finish("match_decided")
            return

        self.round_no += 1
        self.round_tick = 0
        for f, x in zip(self.fighters, (-2.6, 2.6)):
            f.hp = f.max_hp
            f.x = x
            f.y = 0.0
            f.combo = 0
            f.attack = None
            f.enter(IDLE)
        self.a.facing, self.b.facing = 1, -1
        self.log("round_start", round_no=self.round_no)

    # ── vfx / hud ─────────────────────────────────────────────────────────────

    def _flash(self, pool: list, key: str, defender: Fighter,
               scale: float = 0.15) -> None:
        cursor = self._impact_cursor if key == "impact" else self._block_cursor
        obj = pool[cursor % len(pool)]
        if key == "impact":
            self._impact_cursor += 1
            obj.scale = (scale, scale, scale)
        else:
            self._block_cursor += 1
        obj.location = (defender.x + 0.28 * defender.facing, -0.15, ARM_Z)
        obj.hide_render = False
        self._expiry.append((obj, self.frame + 3))

    def _expire_vfx(self) -> None:
        alive = []
        for obj, until in self._expiry:
            if self.frame >= until:
                obj.hide_render = True
            else:
                alive.append((obj, until))
        self._expiry = alive

    def _update_hud(self) -> None:
        self.hp_a.set(self.a.hp / self.a.max_hp)
        self.hp_b.set(self.b.hp / self.b.max_hp)
        self.round_a.set(self.a.rounds_won)
        self.round_b.set(self.b.rounds_won)
        self.timer_bar.set(max(0.0, 1.0 - self.round_tick / self.round_ticks))
        self.ko_flash.advance()
        self.rig.update((self.a.x, 0.0, 1.0), (self.b.x, 0.0, 1.0))

    # ── report ────────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        return {
            "rounds_played": len(self.round_results),
            "rounds": self.round_results,
            "match_winner": (self.a.name if self.a.rounds_won > self.b.rounds_won
                             else self.b.name if self.b.rounds_won > self.a.rounds_won
                             else None),
            "score": f"{self.a.rounds_won}-{self.b.rounds_won}",
            "match_decided": self.match_over,
            "hits_landed": {f.name: f.landed for f in self.fighters},
            "attacks_blocked": {f.name: f.blocked for f in self.fighters},
            "whiffs": {f.name: f.whiffed for f in self.fighters},
            "max_combo": {f.name: f.max_combo for f in self.fighters},
            "hp_left": {f.name: round(f.hp, 1) for f in self.fighters},
            "knockouts": self.count_events("ko"),
        }

    def verdict(self, summary: dict) -> tuple:
        problems = []
        if sum(summary["hits_landed"].values()) == 0:
            problems.append("no attack ever connected — hitboxes are not reaching")
        if sum(summary["attacks_blocked"].values()) == 0:
            problems.append("nothing was ever blocked — blocking is inert")
        if summary["knockouts"] == 0:
            problems.append("no knockout — damage or health is misconfigured")
        if sum(summary["whiffs"].values()) == 0:
            problems.append("no attack ever whiffed — range check may always pass")
        if not summary["match_decided"]:
            problems.append("match never resolved within the run")
        return (not problems), problems


if __name__ == "__main__":
    kernel.main(ArenaFighter)
