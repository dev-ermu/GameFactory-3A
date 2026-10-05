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

对战格斗游戏——基于生成的机制，Blender运行时。

已实现的规则
----------
两名格斗者位于一维战斗线上，采用真实的状态机和帧数据机制：每次攻击都有以tick为单位的启动、生效及恢复阶段，且仅生效阶段才会产生碰撞箱。
防御、硬直伤害、击飞效果、连招计数、回合胜利判定以及回合计时等功能都是这一机制的自然结果，而非独立的系统。

为何采用帧数据而非距离检测？
------------------------
若采用“距离足够近时按下攻击键即可触发攻击”的机制，游戏将毫无深度可言：既无法惩罚未命中攻击，也无法实现攻防互换，更没有防御的理由。
攻击的启动阶段意味着发动攻击是一种承诺；恢复阶段则意味着未命中的重击可成为免费的反击机会；生效帧则允许两次攻击相互抵消。
报告中所有有趣的现象——反击、攻防互换、被防御的连招——都由这三个数值决定，它们被记录在`spec.json`文件中，因此无需修改代码就能重新调整游戏平衡。

两名格斗者均为人工智能。它们仅通过配置文件指定的攻击/防御/重击权重来区分，这些差异足以让它们在屏幕上呈现出截然不同的角色特征。
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
# 格斗者处于忙碌状态时，人类输入的攻击指令会被保留多久。
# 在30Hz的帧率下，6个tick对应200毫秒——这个时间足够让玩家在攻击恢复结束前按下按键，
# 又短到不会让玩家在几秒后突然按下按键制造意外效果。
INPUT_BUFFER_TICKS = 6

#: Skeleton heights, in metres above the floor. Collected here because the body
#: is assembled from stacked primitives and the segments have to meet: a figure
#: whose hips are a centimetre above its legs reads as broken from ten metres
#: away, and the legs-to-total ratio is most of what makes it read as a person
#: rather than a bollard.
# 骨骼高度，单位为米，指相对于地面的高度。将这些数值汇总于此是因为角色模型由多个基础几何体堆叠而成，各部位必须衔接紧密：
# 如果角色的髋部比腿部高出1厘米，从十米外看就会显得畸形；而腿部与整体身高的比例正是判断其是否为人类而非路障的关键。
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
#: 角色模型的标准化高度，单位为米：即角色头部球体所在位置。此处参考的是方块尺寸而非真人尺寸，因为姿势——进而碰撞箱——都是基于方块尺寸来衡量的；若模型尺寸与方块不符，就会导致出拳动作偏离正确位置。
FIGURE_HEIGHT = HEAD_Z + 0.20

#: Yaw, in the actor convention `figures.face` speaks (0 is +Y), that turns a
#: figure to look down +X. Fighters face along the fight line, so a fighter's
#: `facing` of +-1 is this angle times that sign.
#: 按照角色设定中`figures.face`的定义，使角色面向+X方向的偏航角（0对应+Y方向）。格斗角色通常沿战斗线朝向对手，因此当角色的`facing`值为±1时，对应的就是该角度乘以相应符号。
FACING_YAW = -90.0

#: Which arm throws the lead punch. `figures.reach` takes >= 0 as the right one,
#: and the block body's lead arm is on the same side.
#: 负责打出先手拳的手臂。`figures.reach`中将≥0的值定义为右手，而方块模型的先手手臂也位于同一侧。
LEAD_ARM = 1

#: Where the layers of the back of the stage sit, in metres along +Y.
#:
#: Separated rather than shared, and the numbers are the whole reason this is a
#: named block: the kit's wall is 1.2 m deep once scaled and its column 1.2 m
#: square, so putting both on the primitive pillar's own y buries one inside the
#: other and the two z-fight into a smear of stone. The columns stand *proud* of
#: the wall, which is what an engaged column does anyway, and the clutter stands
#: clear of both — and of the fight, which is the front two thirds of the stage.

# 舞台背面各层结构在+Y方向上的位置，单位为米。
# 这些数值被分开设定而非共用，也正是它们让这块区域被命名为独立方块的原因：缩放后道具墙的深度为1.2米，其柱子的截面也为1.2米见方；
# 若将两者都放置在基础柱子的Y轴位置上，就会导致一个物体嵌入另一个物体内部，且两者的Z轴位置还会重叠形成一团乱石。
# 柱子会突出于墙面之外，这其实也是承重柱的正常形态；而杂物则会被放置在两者之外——同时也远离战斗区域，战斗区域占舞台前三分之二的位置。
WALL_Y = 5.0
COLUMN_Y = 4.2
CLUTTER_Y = (3.05, 3.65)

#: How far the arms come up when a fighter is merely standing. Not zero: a
#: fighting game's idle is a stance, and arms hanging at the sides read as a
#: bystander who wandered into the ring.
# 格斗角色处于站立状态时双臂抬升的高度。该值不为零：格斗游戏中的待机状态其实是一种防御姿态，若双臂垂在身侧，看起来就像误入赛场的外人。
IDLE_GUARD = 0.34


class Fighter:
    """
    One character: a state machine, a body of primitives, and its own AI.

    The body faces along the fight line (the X axis), not along +Y like actors
    in the other genres, because a side-on camera wants the character's profile
    and its reach measured in screen-horizontal metres. `facing` is +1 or -1 and
    is the only orientation this genre needs.

    
    单个角色：包含状态机、基础几何体构成的身体以及专属人工智能。
    该角色的身体沿战斗线（X轴）朝向对手，而非其他类型游戏中沿+Y方向，因为侧视镜头需要呈现角色侧面轮廓，且其攻击范围需以屏幕水平方向的米为单位来衡量。`facing`取值为+1或-1，也是此类游戏所需的唯一方向参数。
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
        #: 角色移动时覆盖的地面距离，用于步幅循环计算。此处采用距离而非时间计时，这样当角色停止移动时双腿也会随之停下——详见`figures.walk`。
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
        # 采用两级骨骼结构，这种拆分很有必要。`root`位于地面，负责定位以及击倒后的倾倒效果；`waist`则位于髋部高度，负责控制身体倾斜——这样出拳时身体会围绕固定的双脚弯曲，而不会像保龄球一样整个摔倒。因此，髋部以上的所有部位都基于`waist`在*腰部空间*中定位，正因如此，下方的z轴偏移量都是以HIP_HEIGHT为基准计算的。
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
        # 这是战斗姿态而非普通站立姿势：前腿向前伸展，后腿支撑身体。从侧面看，若两条腿处于同一x坐标上，就会显得像一根柱子。
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
        # 主动臂就是负责出拳的那条手臂；通过在该腰部的局部空间中移动这个物体来实现其动画效果，因此碰撞箱和模型使用的是同一组参数。
        self.arm = prims.spawn(prims.CYLINDER, f"{name}_arm", scale=(0.095, 0.095, 0.30),
                               material=skin, into="Actors", parent=self.waist)
        # Glove, not chrome. On `trim` the fist is a metallic ball reflecting the
        # sky, and against a matte arm the eye reads two objects with a gap
        # between them rather than one limb.
        # 手套并非金属材质。在`trim`模式下，拳头会呈现为反射天空的金属球；而若与哑光质地的手臂搭配，人眼会将其识别为两个有间隙的物体，而非一个完整的肢体。
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

        # 角色模型位于方块之上，若该任务名为“one”。该模型被挂载在`root`节点而非`waist`节点上，因为该模型自带髋部关节：`figures.lean`会在该处使模型弯曲，若将其挂载在已然倾斜的腰部节点上，会导致弯曲程度加倍，进而使角色身体对折。
        # 这些方块只是被隐藏而非删除，射击类游戏遵循同样的规则，不过原因有所不同。此处并无射线检测操作——格斗游戏中的碰撞箱是通过数学计算得出的——但计算过程会读取`self.fist.location`数据，因此方块的姿态就是碰撞箱，无论是否有人能看到它，都需持续计算其姿态。`self.guard`则保持原样：它只是为了提升代码可读性而设置的标识，并非实际的解剖结构；无论如何，我们都希望看到阻挡角色前方有发光的护盾板。
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

        
        设定主臂的姿态。`extend`值为0时代表处于防御状态，为1时则完全伸出。
        我们特意通过`fist_x()`函数从该姿态中读取伸展距离，而非单独存储该数值：如果碰撞箱无法跟随可见的拳头移动，格斗游戏就会出现攻击明显未命中却判定为命中的情况。
        """
        reach = max(0.26, 0.30 + extend * float(self.stats["reach"]))
        z = ARM_Z - HIP_HEIGHT - crouch * 0.16 - extend * 0.02

        # Span the gap rather than guess at it. The upper arm runs from a fixed
        # shoulder inside the torso to wherever the fist is, so the two are
        # joined at every value of `extend` — including the wind-up, where the
        # fist comes back past a fixed-length arm and used to float free of it.
        # 填补间隙而非凭猜测行事。上臂从躯干内固定的肩部延伸到拳头所在位置，因此在`extend`的所有取值下两者都是相连的——包括蓄力阶段，此时拳头会回缩到固定长度的手臂后方，甚至会脱离手臂独立移动。
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

        
        拳头的世界坐标x值——即碰撞箱位置。
        该数值是计算得出的，而非直接读取`matrix_local`，因为后者仅在依赖图更新时才会刷新，在此处会存在一帧的延迟。出拳时的身体倾斜会使拳头绕腰部旋转，全力出拳时这种偏移可达几厘米；而三角函数运算成本极低，能确保碰撞箱与视觉表现完全一致。
        """
        fx, _, fz = self.fist.location
        return self.x + fx * cos(self.lean) + fz * sin(self.lean)

    def pose(self) -> None:
        """Push simulation state onto the body once per tick. 每个tick将模拟状态同步到角色身上。"""
        # Only stepping counts toward the stride. Pushback and the separation
        # shove move `x` too, and folding those in makes a fighter's legs shuffle
        # every time it gets hit — a walk cycle advancing without a walk, which is
        # the tell distance-driven animation exists to avoid.

        # 只有迈步动作才会计入步态统计。后冲和分离推挤也会改变`x`值，如果把它们也算进去，角色每次被击中时腿部都会出现拖步现象——也就是没有实际行走却出现步行循环，这正是基于距离驱动的动画机制所要避免的情况。
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
            # 平摔：这种情况涉及的是位于地面上的根部，因此整个角色会向前倾倒而非在腰部弯曲。
            # 死亡动画中已经包含了这种摔倒效果——若再叠加根部的翻滚动画，会导致模型穿透地面。
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

        根据方块系统使用的同一组三个数值来驱动角色模型。直接传入`pose`的*输出结果*，而非重新读取状态机：
        因为对同一状态的两次读取在下次编辑时会产生偏差，导致画面与碰撞框不再匹配。
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
                    # Mixamo制作的人形模型通常没有拳击动画。不过短促的前冲动作仍能被判定为已触发的攻击。
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
        # 玩家操控的角色在fighters列表中的索引。0代表左侧角色，也是摄像机偏好的一侧。
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
        # 装饰效果源自其独立的数据流。被标记为“有裂纹”的那一列，绝不能占用AI原本要生成的绘制结果；否则一旦开启该装饰效果，就会改变战斗胜负——如此一来，两次运行结果便无法对比，而这正是生成这些结果的唯一目的。装饰效果的种子基于规格参数中的种子生成，因此装饰效果与战斗过程一样具备可复现性。
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
        # 太阳的光线沿自身的-Z轴发射，因此设置`rotation_euler.x = θ`会使光线朝向`(0, sin θ, -cos θ)`方向——也就是说光线从-Y轴方向射来，也就是摄像机所在的一侧。
        # 来自摄像机侧的-key光与背后的rim光：若从侧面观察战斗场景，只会看到轮廓而已，这正是该阶段初次渲染时的样子。
        # 这两种光源均由规格参数驱动，因为天空本身也是如此：HDRI贴图自带内置的key光，而两束经过调校、匹配平面渐变背景的太阳光会将石头表面渲染成白色。
        # 提供环境设定的任务会下调这些光源的强度；未提供环境设定的任务则会采用平面天空所需的参数值。
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
        # 玩家选择的起始角落。仅在有玩家操控时才会参考该设定；若无玩家操控，两名格斗者会各自按原有风格行动，不会有任何变化。
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
        # 第一轮从此处开始，而非在`_finish_round`中启动——后者只会处理第二轮和第三轮。
        # 若非如此，日志中会出现一次`round_start`对应两次`round_end`的情况，而任何试图通过统计事件来还原比赛过程的人都会发现数据对不上。
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

        将配置文件中定义的格斗者信息覆盖到默认设置上，逐条处理。
        `Game.__init__`会合并嵌套字典，但会直接替换列表——因为不完整的列表没有通用意义。
        不过角色列表是个例外：其中两项元素的位置是固定的，且每次含义都相同。
        因此，需要更高生命值的格斗者的任务就能直接指定这一需求，无需重复声明两种攻击的帧数据。
        按索引合并的方式正好能满足这一需求；而如果任务提供了完整的格斗者配置，则会覆盖所有现有设置。
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
                # 这些柱子纯粹属于装饰性元素，不会像射击游戏中的掩体那样被玩家穿透；
                # 此类游戏中并不会进行光线投射计算，因此无需让模型形状与碰撞体保持一致。
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
    # 下文中的所有内容均为装饰性元素，而此类游戏中的装饰自由度极高：
    # 格斗游戏中的碰撞箱计算方式为 `abs(fist_x - opponent.x)`，因此道具不会阻碍光线投射，
    # 也无需匹配特定碰撞体的比例要求。唯一需要遵守的规则就是通用规则——
    # 装饰内容不得触碰 `self.rng`、`x`、`facing` 或 `hp` 这些变量；
    # 该规则通过仅从 `self.look` 中读取数据、且仅对自行创建的对象进行修改来得以遵守。

    def _models(self, key: str) -> list:
        """
        The `models.<key>` references a task gave, always as a list.

        A list rather than one reference because a wall repeated fourteen times
        reads as a loop; drawing from a handful is what makes it read as a place.
        A bare string is accepted and wrapped.
        
        之所以采用列表形式而非单个引用，是因为重复十四次的墙壁会被视作循环语句；
        只有从少量模型中选取元素绘制，才能营造出真实场景的效果。纯字符串也会被自动包装为列表。
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

        通过堆叠组件片段来构建一根背景柱。

        采用堆叠方式而非拉伸方式，这是竞技场柱子与普通柱状物的区别：
        该套组件的柱子标准高度为1米，底座为0.6米见方的正方形；
        若直接用单个副本构建6米高的柱子，会导致柱头装饰被拉伸成细条状，比例严重失调。
        重复使用组件片段能保持装饰元素的原始比例，这正是模块化组件的设计初衷。

        顶部的组件可能是损坏变体——断裂的柱子能体现出竞技场的陈旧感；
        而提供多个模型选项的目的，就是让任务策划能够自行决定最终选用哪种样式。

        每个段落采用**相同的**缩放系数，该系数从整个柱体尺寸中一次性提取，而非针对每个段落按柱高进行归一化处理。
        其中有个特殊的断裂部分：它设计上仅为四分之三柱长，因此将其设为两米高时，其宽度也会相应超出1.4倍，最终这个断裂的柱体末端会形成一个石蘑菇状结构。
        有一个缩放因子能保持套件自身的比例，这也是选择模块化套件的唯一理由。
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
        """Tile the floor, wall in the back, and put clutter along its foot.
        铺设舞台地面、搭建后方墙壁，并在舞台边缘放置杂物。
        """
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

        在整块瓷砖网格上用套件中的地板砖覆盖舞台基底。
        尺寸是根据`length`而非`height`来确定的：地砖是一种厚度为零的平面，若按高度来归一化，就会除以零。
        数量的计算依据是板块大小而非规格说明中的间距，原因与射击游戏中的墙面处理一致——剩余的零散部分会形成沿某一边缘分布的扁平色带，而此处该边缘正是摄像机所朝向的边缘。
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

        背景板前方的一排装饰墙，包括大门在内。

        将其设置在板块前方而非替换原有板块，这样两段墙体之间的缝隙会露出深色石材而非天空——这与射击游戏中装饰面板凸出于原有墙面的原因相同。
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
                # 大门只能位于地面层，别处不可。在楼上，它们会变成通往六米深落差的门口，这正是射击游戏里窗户设计所犯的错误。
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

        背景墙底部、战斗线之外的杂物摆放。物体被限制在背景区域且不能出现在画面中央——第二条限制规则需要特别注意：
        摄像机采用侧视角，会聚焦在两名格斗者身上，因此舞台中央后方的雕像最终会恰好位于战斗场景的正后方。
        最初的设计中，有奖杯从一名格斗者的头顶生长出来。任何处于中心线“禁止区域”内的物体都会被向外推挤，从而把画面中央留给战斗场景。
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
        
        # 击中和格挡效果必须能一眼区分，因此两种标记物的颜色不同——这一设计的前提是它们都不会呈现白色。
        # 在标准视图变换下，发射器的颜色由其最暗通道的数值决定，因此强度值会保持在1附近，而尺寸而非亮度则用来体现冲击力度。
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
        
        选择行动。只有能够行动的格斗角色才会做出选择——其余角色的行动早已确定，
        这正是帧数据存在的意义。
        """
        if f.state == KO:
            return
        if self.human and f is self.human_fighter:
            # Ahead of the `can_act` gate: a human's input has to be *seen* on
            # frames they cannot act on, so it can be buffered. See below.
            # 在`can_act`判断之前：人类的输入必须在其无法行动的帧中被“读取”，
            # 这样才能被缓存起来。详见下文说明。
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
        # 应对已经发动的攻击：要么格挡，要么撤出攻击范围。
        # 两种防御方式都很重要——格挡能以减少受击伤害为代价换取安全，而后撤则会让攻击者扑空，从而让其整个恢复窗口白白浪费。
        # 如果没有后撤机制，就不存在“扑空”的情况，而无法扑空的攻击也就称不上是真正的进攻承诺。
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
        # 在攻击范围边缘发出的试探性攻击：有时能命中前冲的对手，有时则会成为被对手反击的破绽。
        if (distance <= reach * 1.4
                and self.rng.random() < float(style["aggression"]) * 0.20):
            f.start_attack("jab")
            return

        # Out of range: close, unless deliberately spacing.
        # 超出攻击范围：除非刻意保持距离，否则应靠近对手。
        if f.state == BLOCK:
            f.enter(IDLE)
        step = float(f.stats["walk_speed"]) * self.dt
        towards = 1.0 if opponent.x > f.x else -1.0
        backing = self.rng.random() > float(style["aggression"]) + 0.25
        f.x += step * towards * (-0.55 if backing and distance < reach * 2.2 else 1.0)
        # A little depth so the two don't occupy the same silhouette — a small
        # offset, not a walk to opposite walls, or they leave the camera's plane.
        # 为了不让两个角色占据同一画面空间，需要留一点纵深——只需微小偏移即可，无需走到屏幕两端，以免超出摄像机的拍摄范围。
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

        玩家操控的角色每一帧的逻辑：包括攻击指令缓存、防御状态维持以及移动处理。
        攻击采用边沿触发机制并会被缓存，而非持续按住触发。若采用持续按住的方式，玩家只需按住按键就能在每一帧触发攻击，这会抹去让帧数据变得有趣的时间差要素；
        若仅采用无缓存的边沿触发机制，那么在技能启动、恢复或硬直期间按下的指令都会被忽略；而一款会忽略三分之一输入的操作的游戏，给人的感觉会是漏洞百出，而非严谨克制。
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
                # 防御持续按住：需保持该状态，否则经过几帧后`_advance`函数会让角色解除防御状态，
                # 从而留下玩家并未期望出现的防御空档。
                f.state_ticks = 0
            return
        if f.state == BLOCK:
            f.enter(IDLE)

        if c.move_x or c.move_y:
            # +X is screen-right; +Y is into the stage, Street-Fighter 2.5D.
            # +X代表屏幕向右方向；+Y代表朝向舞台内部，《街头霸王》2.5D玩法中的设定。
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
        """Run one tick of whatever the fighter is committed to.
        执行 fighter 当前所处状态的下一个时间步操作。
        """
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
        攻击判定框是拳头；受击判定框是对手的躯干区域。两者都源自设定的身体姿态，因此连接点就是摄像机所捕捉到的画面。
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
        # 如果击中了正处于出招前摇阶段的对手，这属于反击命中——需要单独记录，因为这是诱骗对手落空后的回报。
        if defender.state == ATTACK:
            self.log("counter_hit", attacker=attacker.name, defender=defender.name,
                     interrupted=defender.attack["name"] if defender.attack else None)

        damage = float(a["damage"])
        defender.hp = max(0.0, defender.hp - damage)
        defender.x += a["pushback"] * attacker.facing
        defender.taken += 1
        attacker.landed += 1

        # A combo is a hit that lands before the previous one's stun expired.
        # 连击指的是在前一次攻击的硬直时间结束前发生的命中。
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
        """Keep the fighters out of each other and on the stage.
        让对战双方彼此分开并保持在擂台上"""
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
        # 在重置前先播放击倒动画。
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
