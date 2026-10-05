"""
First-person arena shooter — generated mechanic, Blender runtime.

Rules implemented
-----------------
Hitscan weapon with a magazine, a reload, per-shot cone spread and a fire
interval; ray-cast damage that respects cover, so a shot into a crate is a miss
rather than a hit through it; enemies that acquire, strafe, take cover and shoot
back on their own cadence; health, death and a round that ends when the arena is
clear or the player is down.

Everything is driven from `spec.json` — arena size, cover density, enemy count
and stats, and the whole weapon block — so the same template generates a
close-quarters shotgun brawl or a long-range duel without editing code.

Why the shooting is a ray cast
------------------------------
The obvious cheap version is a distance-and-angle check, and it produces a
mechanic that shoots through walls. Cover is the entire point of an arena
shooter, so the shot is a real `scene.ray_cast` against the built level and
whatever it strikes first is what it hit. That also makes the demo honest: the
accuracy number in the report counts shots that reached a body.

The player is an AI. A generated mechanic has to be judged unattended, so the
"player" is a scripted policy driving the same input surface a human would.

第一人称竞技场射击游戏——程序生成的机制，基于Blender运行时开发。

已实现的规则
------------
具备弹匣、装填机制、每发子弹的散射范围以及射击间隔的射线扫描武器；伤害判定会考虑掩体因素，因此射向箱子的子弹会被判定为脱靶，而非穿透箱子造成伤害；敌人能够自主寻找掩体、进行侧移、利用掩体还击；游戏包含生命值系统、死亡机制，当竞技场内没有敌人或玩家死亡时，当前回合即告结束。

所有参数均由`spec.json`文件驱动——包括竞技场大小、掩体密度、敌人数量与属性，以及整套武器参数——因此无需修改代码，同一模板就能生成近战霰弹枪混战或远程决斗场景。

为何采用射线扫描判定射击结果
------------------------------
最简单的实现方式是仅检查距离和角度，但这种方式会导致子弹能穿透墙壁。而掩体正是竞技场射击游戏的核心要素，因此射击判定实际上是对构建好的关卡进行`scene.ray_cast`射线检测，最先被击中的物体即为命中目标。这种方式也能保证演示的真实性：报告中的命中率统计的是真正击中敌人身体的子弹数量。

玩家角色由人工智能控制。由于程序生成的机制需在无人干预的情况下运行，因此“玩家”实际上是由脚本控制的决策逻辑，其输入方式与人类玩家一致。
"""

import os
import sys
from math import atan2, cos, degrees, hypot, radians, sin
from pathlib import Path
from random import Random


def _bootstrap_repo_root() -> Path:
    """Find GameFactory-3A so `engine_adapters` imports, wherever this was copied."""
    env = os.environ.get("GAMEFACTORY3A_ROOT") or os.environ.get("AAAGF_REPO_ROOT")
    if env and (Path(env) / "engine_adapters").is_dir():
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        if (parent / "engine_adapters" / "blender" / "game").is_dir():
            return parent
    raise RuntimeError(
        "cannot locate the GameFactory-3A repo root; set GAMEFACTORY3A_ROOT")


_ROOT = _bootstrap_repo_root()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine_adapters.blender.game import (  # noqa: E402
    assets, camera_rigs, clips, figures, hud, kernel, materials, prims,
)

#: How far ahead of the eye a shot starts. The shooter's own body is in the
#: scene and a ray from inside it hits the shooter; nudging past the collision
#: radius is cheaper and more predictable than hiding the body and forcing a
#: depsgraph rebuild on every trigger pull.
# 子弹发射点相对于眼睛位置的前移距离。玩家的身体本身存在于场景中，从体内发出的射线会命中玩家自身；将发射点设置在碰撞半径之外，比隐藏身体并每次扣动扳机时都触发依赖图重建要更简便且可控。
MUZZLE_OFFSET = 0.75

#: Ticks a tracer / flash / spark stays visible.
# 拖尾特效/闪光特效/火花特效的可见时长（单位： tick）。
VFX_HOLD = 3

#: Visible streak length. Hitscan still goes the full weapon range.
TRACER_METRES = 1.6
TRACER_RADIUS = 0.0045
TRACER_RADIUS_ENEMY = 0.0035

#: How far a human player may look up or down. Short of 90° on purpose: at
#: exactly straight up the yaw axis and the view axis coincide and the horizon
#: spins around the crosshair.
#  可见的子弹轨迹长度。射线扫描的实际杀伤范围仍可达武器的全射程。
MAX_PITCH = 85.0

#: Sprint multiplier on `move_speed` while the run key is held.
RUN_MULTIPLIER = 1.55

#: Height an enemy figure is normalised to, in metres. Measured off the collider
#: it stands over rather than off a person: the block figure is 2.0 m to the crown
#: of its head sphere, and since those blocks remain the hurtbox, matching them is
#: what keeps the silhouette on screen and the shape being shot at in agreement.
FIGURE_HEIGHT = 2.0

#: How far forward an enemy holds its arms, 0 hanging to 1 level. Short of level
#: so the weapon still reads as carried rather than presented.
ENEMY_AIM = 0.82

#: Length a weapon model is normalised to, in metres.
WEAPON_LENGTH = 0.46

#: Where the viewmodel sits in camera space (+X right, +Y up, -Z forward).
#: Further forward (more −Z) so a scoped rifle's optic sits in frame instead
#: of living inside the near clip / filling the corner as a stock close-up.
WEAPON_MOUNT = (0.06, -0.14, -0.46)

#: Poly Haven firearms: longest axis is X, muzzle at **+X**.
#: Rx(+90) Ry(+90) Rz(180) sends +X -> −Z (camera forward) with sights up.
#: The previous Ry(−90) pointed the muzzle at the lens; this is a 180° yaw flip.
VIEWMODEL_ROTATION = (radians(90.0), radians(90.0), radians(180.0))

#: Same guns on an actor that faces +Y: Rz(+90) sends +X to +Y.
HELD_WEAPON_ROTATION = (0.0, 0.0, radians(90.0))

#: Mixamo (Soldier / Michelle) already faces +Y after the glTF importer's
#: Y-up -> Z-up conversion. The Kenney default of 180 would turn them around.
MIXAMO_YAW = 0.0

#: Planar keep-out for a Mixamo soldier. Shoulders and the walk cycle's
#: planted foot sit ~0.55 m off the root; 0.45 left them inside crates.
BODY_RADIUS = 0.64


class FpsArena(kernel.Game):
    genre = "fps"

    default_spec = {
        "duration_sec": 16.0,
        "fps": 30,
        "resolution": (960, 540),
        "samples": 16,
        "seed": 11,
        "arena_size": 34.0,
        "cover_count": 16,
        "sky_color": (0.07, 0.09, 0.14),
        "sky_strength": 0.45,
        "player": {
            "hp": 100.0,
            "move_speed": 5.4,
            "turn_rate": 260.0,
            "eye_height": 1.62,
            "preferred_range": 9.0,
        },
        "weapon": {
            "damage": 26.0,
            "fire_interval": 0.13,
            "mag_size": 12,
            "reload_time": 1.25,
            "spread_deg": 1.9,
            "range": 60.0,
        },
        "weapons": [
            {"name": "pistol", "damage": 22.0, "fire_interval": 0.18,
             "mag_size": 10, "reload_time": 1.1, "spread_deg": 1.4, "range": 45.0},
            {"name": "rifle", "damage": 26.0, "fire_interval": 0.11,
             "mag_size": 18, "reload_time": 1.4, "spread_deg": 1.9, "range": 70.0},
        ],
        "enemy_count": 6,
        "enemy": {
            "hp": 60.0,
            "damage": 6.0,
            "move_speed": 2.9,
            "fire_interval": 1.15,
            "accuracy": 0.42,
            "engage_range": 22.0,
        },
        "sky_hdri": "/Library/hdris/industrial_sunset_2k.hdr",
        "alley_length": 18.0,
        "alley_width": 4.2,
    }

    # ── build ─────────────────────────────────────────────────────────────────

    def build(self) -> None:
        self.p = self.spec["player"]
        loadout = list(self.spec.get("weapons") or [self.spec["weapon"]])
        self.loadout = loadout
        self.weapon_index = 0
        self.w = dict(self.spec["weapon"], **loadout[0])
        self.e = self.spec["enemy"]
        size = float(self.spec["arena_size"])
        self.half = size * 0.5

        # Decoration draws from its own random stream, and that is a rule rather
        # than tidiness. Picking which crate model goes in slot three off
        # `self.rng` would consume draws the rules were going to make, so every
        # later spread cone and accuracy roll would shift — turning the art on
        # would change the gameplay, and the two runs could not be compared.
        # Seeded from the same spec seed, so the art is reproducible too.
        self.look = Random(self.seed ^ 0x5A17)

        # Every collider the rules cast against, by name. An allow-list, so that
        # scenery is transparent to a bullet by construction rather than by
        # remembering to mark it — see `kernel.cast`, and `_ray` below.
        self.solid: set[str] = set()

        # Panel thicknesses, measured once per reference rather than per panel.
        self._depths: dict = {}

        # Two suns, not one. A single low sun over an arena full of vertical
        # cover leaves every crate a black silhouette against the floor, which
        # is exactly the surface the player has to read to know what is cover.
        # The fill is a quarter of the key: enough to keep the shadow side
        # readable, not so much that the arena stops looking lit from anywhere.
        kernel.add_sun("key", energy=float(self.spec.get("sun_energy", 2.9)),
                       rotation=(radians(48), radians(6), radians(38)),
                       angle=float(self.spec.get("sun_angle", 0.12)))
        kernel.add_sun("fill", energy=float(self.spec.get("fill_energy", 0.8)),
                       rotation=(radians(-34), radians(-10), radians(-140)))
        self._build_arena(size)
        self._build_enemies()
        self._build_player()
        self._build_vfx_pools()
        self._build_hud()

        # Combat state
        self.hp = float(self.p["hp"])
        self.ammo = int(self.w["mag_size"])
        self.reload_left = 0.0
        self.fire_cooldown = 0.0
        self.shots = 0
        self.hits = 0
        self.kills = 0
        self.damage_dealt = 0.0
        self.damage_taken = 0.0
        self.incoming = 0
        self.cleared_at = None

    # ── assets ────────────────────────────────────────────────────────────────

    def _models(self, key: str) -> list:
        """
        The `models.<key>` references a task gave, always as a list.

        A list rather than one reference because an arena wall repeated thirty
        times reads as a corridor in a loop; drawing from a handful of panels is
        what makes it read as a place. A bare string is accepted and wrapped, so a
        spec that wants one model does not have to write brackets.
        """
        entry = (self.spec.get("models") or {}).get(key)
        if not entry:
            return []
        return [entry] if isinstance(entry, str) else list(entry)

    def _pick(self, key: str):
        """One reference from `models.<key>`, off the decoration stream."""
        options = self._models(key)
        return self.look.choice(options) if options else None

    def _collider(self, obj, dressed: bool):
        """
        Register a primitive as something bullets stop on, and veil it if dressed.

        The registration is the load-bearing half: `_ray` only reports hits against
        names in this set, so a shot behaves identically whether or not a model was
        found for this piece of level.
        """
        self.solid.add(obj.name)
        if dressed:
            prims.veil(obj)
        return obj

    # ── level ─────────────────────────────────────────────────────────────────

    def _build_arena(self, size: float) -> None:
        half = self.half
        surfaces = self.spec.get("surfaces") or {}
        floor_mat = materials.surface(
            "fps_floor", surfaces.get("floor"),
            color=(0.18, 0.17, 0.15), roughness=0.88, metres=6.0)
        wall_mat = materials.surface(
            "fps_wall", surfaces.get("wall"),
            color=(0.22, 0.21, 0.19), roughness=0.82, metres=3.2)
        crate_mat = materials.solid("fps_crate", (0.28, 0.24, 0.18), roughness=0.55,
                                    metallic=0.35)
        pillar_mat = materials.solid("fps_pillar", (0.22, 0.23, 0.25), roughness=0.45,
                                     metallic=0.55)
        # Bright enough to be the brightest thing in a dim arena, dim enough to
        # stay cyan and pink rather than clipping to two white lines.
        neon = materials.glow("fps_neon", materials.PALETTE["neon_cyan"], strength=0.22)
        neon_b = materials.glow("fps_neon_b", (0.85, 0.45, 0.20), strength=0.18)

        floor = prims.spawn(prims.PLANE, "floor", scale=(half, half, 1.0),
                            material=floor_mat, into="Level")
        self._scene_placed = self._place_scene(size)
        self._collider(floor, self._scene_placed)

        # `scale` on a unit primitive is a half-extent: a 2 m cube scaled by
        # (0.5, 0.5, 1.2) is 1 x 1 x 2.4 m. Sizing cover as if scale were the
        # full dimension is how an arena ends up full of three-storey crates.
        wall_h = 2.6
        panels = self._models("wall")
        for i, (x, y, sx, sy) in enumerate([
            (0.0, -half, half, 0.4),
            (half, 0.0, 0.4, half), (-half, 0.0, 0.4, half),
        ]):
            wall = prims.spawn(prims.BOX_GROUND, f"wall{i}", location=(x, y, 0.0),
                               scale=(sx, sy, wall_h), material=wall_mat,
                               into="Level")
            self._collider(wall, self._scene_placed)
            if panels and not self._scene_placed:
                self._dress_wall(i, x, y, sx, sy, wall_h, panels)
            if not self._scene_placed:
                prims.spawn(prims.BOX_GROUND, f"wall_strip{i}",
                            location=(x * 0.97, y * 0.97, 3.9),
                            scale=(sx * 0.92 if sx > sy else 0.06,
                                   sy * 0.92 if sy > sx else 0.06, 0.06),
                            material=neon if i % 2 == 0 else neon_b,
                            into="Level", shadow=False, collide=False)

        # Cover. Laid out on a jittered ring rather than uniformly at random:
        # pure uniform placement clumps, and a clump in the middle of a small
        # arena means the AI never gets a clean line and the demo shows nothing.
        self.cover: list[tuple] = []
        count = int(self.spec["cover_count"])
        crates = self._models("crate")
        pillars = self._models("pillar")
        for i in range(count):
            angle = (i / count) * 6.28318 + self.rng.uniform(-0.22, 0.22)
            radius = half * self.rng.uniform(0.28, 0.78)
            x, y = cos(angle) * radius, sin(angle) * radius
            # Keep the player's spawn pocket empty so the first stride is not
            # a shoulder through a crate.
            spawn_y = -half * 0.55
            if hypot(x, y - spawn_y) < 3.4:
                push = 3.4 / max(hypot(x, y - spawn_y), 0.2)
                x, y = x * push, spawn_y + (y - spawn_y) * push
            if i % 4 == 3:
                h = self.rng.uniform(1.5, 2.1)
                self._collider(
                    prims.spawn(prims.BOX_GROUND, f"pillar{i}", location=(x, y, 0.0),
                                scale=(0.34, 0.34, h), material=pillar_mat,
                                into="Level"),
                    self._dress_cover(f"pillar{i}", pillars, (x, y), 0.0,
                                      (0.68, 0.68, h * 2.0)))
                self.cover.append((x, y, hypot(0.34, 0.34) + 0.28))
            else:
                w_ = self.rng.uniform(0.45, 0.8)
                d_ = self.rng.uniform(0.45, 0.8)
                h = self.rng.uniform(0.5, 0.95)
                yaw = self.rng.uniform(0, 3.14)
                self._collider(
                    prims.spawn(prims.BOX_GROUND, f"crate{i}",
                                location=(x, y, 0.0), rotation=(0.0, 0.0, yaw),
                                scale=(w_, d_, h), material=crate_mat,
                                into="Level"),
                    self._dress_cover(f"crate{i}", crates, (x, y), yaw,
                                      (w_ * 2.0, d_ * 2.0, h * 2.0)))
                # Circle that contains the box, not the inscribed one. Using
                # max(w_, d_) left the corners open, which is the walk-through.
                self.cover.append((x, y, hypot(w_, d_) + 0.28))

        self._build_alley(half, wall_h, wall_mat, floor_mat, neon)

    def _place_scene(self, size: float) -> bool:
        """Drop in a complete environment GLB. Colliders stay the hull we built.

        Skip collision-only meshes (three.js `collision-world`): they do not
        match the cover layout, so walking the rules-legal path clips through
        the imported geometry.
        """
        refs = [r for r in self._models("scene")
                if "collision_world" not in r.lower()
                and "collision-world" not in r.lower()]
        if not refs:
            return False
        length = float(self.spec.get("scene_length", size * 1.08))
        made = assets.instance(refs[0], "level_scene", location=(0.0, 0.0, 0.0),
                               length=length, into="Level")
        return made is not None

    def _build_alley(self, half: float, wall_h: float, wall_mat, floor_mat, neon) -> None:
        """A factory hall opening onto a narrow alley along +Y.

        The +Y wall of the hall stays as cover; the alley is a second volume
        connected by overlapping floors so a player walking north enters it
        without a loading screen. Width is a few metres — an alley, not a road.
        """
        length = float(self.spec.get("alley_length", 18.0))
        width = float(self.spec.get("alley_width", 4.2))
        y0 = half
        self._collider(
            prims.spawn(prims.PLANE, "alley_floor",
                        location=(0.0, y0 + length * 0.5, 0.0),
                        scale=(width * 0.5, length * 0.5, 1.0),
                        material=floor_mat, into="Level"), False)
        for side, x in ((-1, -width * 0.5), (1, width * 0.5)):
            self._collider(
                prims.spawn(prims.BOX_GROUND, f"alley_wall{side}",
                            location=(x, y0 + length * 0.5, 0.0),
                            scale=(0.22, length * 0.5, wall_h),
                            material=wall_mat, into="Level"), False)
        self._collider(
            prims.spawn(prims.BOX_GROUND, "alley_end",
                        location=(0.0, y0 + length, 0.0),
                        scale=(width * 0.5, 0.22, wall_h),
                        material=wall_mat, into="Level"), False)
        prims.spawn(prims.BOX_GROUND, "alley_strip",
                    location=(0.0, y0 + length * 0.5, 3.6),
                    scale=(0.05, length * 0.45, 0.05),
                    material=neon, into="Level", shadow=False, collide=False)
        # Doorway gap: two short walls on the hall's +Y face leave a 3 m opening.
        gap = 1.6
        for i, x in enumerate((-half * 0.55, half * 0.55)):
            self._collider(
                prims.spawn(prims.BOX_GROUND, f"alley_doorjamb{i}",
                            location=(x, y0, 0.0),
                            scale=(half * 0.45 - gap * 0.5, 0.22, wall_h),
                            material=wall_mat, into="Level"), False)


    def _dress_wall(self, index: int, x: float, y: float, sx: float, sy: float,
                    height: float, panels: list) -> None:
        """
        Clad the inside face of one wall with kit panels, tiled exactly.

        The pitch is **derived from the wall, not chosen**: a whole number of panels
        is fitted across the span and each is scaled to that pitch, so the run
        closes with neither the gaps nor the overlapping z-fighting seams that a
        fixed size and a leftover remainder give. This is the same lesson the
        racing barriers taught, arrived at from the other end — there the spacing
        was wrong for a fixed prop, here the prop is sized to fit the spacing.

        Courses stack by the same pitch until the slab is covered, and the last one
        is allowed to overshoot the top: a wall panel 3 cm above a 5.2 m wall is
        outside every camera in the level, whereas a course short leaves a stripe of
        flat colour where the wall meets nothing.

        Each panel is set a centimetre proud of the slab's face, and its body is
        allowed to sit inside the slab — a 0.8 m wall swallows a 0.78 m panel almost
        exactly. Flush would be coplanar, which is the other way to get a flickering
        wall, and standing it fully in front of the slab would mean bullets stopping
        visibly inside it.
        """
        span = 2.0 * max(sx, sy)
        thickness = min(sx, sy)
        along_x = sx > sy
        # Toward the middle. Exactly one of x, y is +-half for these four walls, so
        # the sign of their sum says which way is out.
        inward = -1.0 if (x + y) > 0.0 else 1.0

        wanted = float(self.spec.get("wall_panel_metres", 2.6))
        across = max(1, round(span / wanted))
        pitch = span / across
        courses = max(1, round(height * 2.0 / pitch))

        # Doors and windows belong at ground level. Put the same mixed list on
        # every course and the arena grows a row of doorways 2.6 m up a wall,
        # opening onto nothing — which is what it did.
        upper = self._models("wall_upper") or panels
        for course in range(courses):
            for k in range(across):
                reference = self.look.choice(panels if course == 0 else upper)
                # Measured, not assumed: the panel's depth decides how far back it
                # has to sit for its *face* to land a centimetre proud, and a kit
                # mixes 0.3 m walls with 0.5 m pillars in the same folder.
                depth = self._panel_depth(reference) * pitch
                lateral = thickness + 0.01 - depth * 0.5
                offset = -span * 0.5 + pitch * (k + 0.5)
                location = ((x + offset, y + inward * lateral) if along_x
                            else (x + inward * lateral, y + offset))
                assets.instance(
                    reference, f"panel{index}_{course}_{k}",
                    location=(location[0], location[1], course * pitch),
                    rotation=(0.0, 0.0, 0.0 if along_x else radians(90.0)),
                    height=pitch, into="Level")

    def _panel_depth(self, reference: str) -> float:
        """A panel's thickness as a fraction of its height, cached per reference."""
        cached = self._depths.get(reference)
        if cached is not None:
            return cached
        collection = assets.source(reference)
        extent = assets.size(collection) if collection is not None else None
        ratio = (min(extent[0], extent[1]) / extent[2]
                 if extent and extent[2] > 1e-6 else 0.3)
        self._depths[reference] = ratio
        return ratio

    def _dress_cover(self, name: str, options: list, centre: tuple, yaw: float,
                     box: tuple) -> bool:
        """
        Stand a prop in for one piece of cover, at exactly the collider's size.

        Fitted per axis rather than scaled uniformly, which is the one place that
        is right: the collider's proportions come out of the level's own random
        stream, so a model that keeps its own would either sit inside its collider,
        and bullets would stop in the air beside it, or outside, and they would
        pass through its visible edge. A crate stretched a little is still a crate.

        Returns whether anything was placed, which is what decides if the block
        underneath gets veiled.
        """
        if not options:
            return False
        made = assets.instance(self.look.choice(options), f"{name}_model",
                               location=(centre[0], centre[1], 0.0),
                               rotation=(0.0, 0.0, yaw), fit=box, into="Level")
        return made is not None

    def _build_enemies(self) -> None:
        body_mat = materials.solid("fps_enemy", materials.PALETTE["enemy"],
                                   roughness=0.55)
        head_mat = materials.solid("fps_enemy_head", (0.95, 0.45, 0.30),
                                   roughness=0.5)
        eye_mat = materials.glow("fps_enemy_eye", (1.0, 0.85, 0.2), strength=3.0)

        self.enemies: list[kernel.Actor] = []
        count = int(self.spec["enemy_count"])
        for i in range(count):
            angle = (i / count) * 6.28318 + 0.4
            radius = self.half * 0.66
            x, y = cos(angle) * radius, sin(angle) * radius
            actor = self.spawn_actor(
                f"enemy{i}", None, position=(x, y, 0.0),
                yaw=degrees(atan2(-x, y)) % 360, team="enemy",
                hp=float(self.e["hp"]), fire_cd=self.rng.uniform(0.3, 1.4),
                strafe=1.0 if i % 2 == 0 else -1.0,
            )
            # Parts hang off an unscaled root, so the actor origin is on the
            # floor and toppling the root topples the whole figure.
            body = prims.spawn(prims.CYLINDER, f"enemy{i}_body",
                               location=(0.0, 0.0, 0.74), scale=(0.36, 0.36, 0.74),
                               material=body_mat, into="Actors", parent=actor.obj)
            head = prims.spawn(prims.SPHERE, f"enemy{i}_head",
                               location=(0.0, 0.0, 1.72), scale=(0.26, 0.26, 0.28),
                               material=head_mat, into="Actors", parent=actor.obj)
            visor = prims.spawn(prims.BOX, f"enemy{i}_visor",
                                location=(0.0, 0.22, 1.74), scale=(0.16, 0.06, 0.045),
                                material=eye_mat, into="Actors", parent=actor.obj,
                                shadow=False)
            arms = [prims.spawn(prims.CYLINDER, f"enemy{i}_arm{side}",
                                location=(0.44 * side, 0.06, 0.98),
                                scale=(0.10, 0.10, 0.42), material=body_mat,
                                into="Actors", parent=actor.obj)
                    for side in (-1, 1)]
            actor.state["parts"] = [body, head, visor]
            actor.state["walked"] = 0.0

            # The hurtbox is these blocks, and it stays these blocks. An arm is a
            # collider but not a hurtbox, which is why hitting one already logged
            # `shot_blocked` rather than damage — registering them keeps that.
            self.solid.update(part.name for part in actor.state["parts"] + arms)
            actor.state["figure"] = self._dress_enemy(
                i, actor, actor.state["parts"] + arms)
            self.enemies.append(actor)

    def _dress_enemy(self, index: int, actor, blocks: list):
        """
        Stand a kit character over one enemy's blocks and leave the rules alone.

        The figure is hung off the actor's own root, so it inherits the position
        and yaw the rules were already driving and the topple on death comes for
        free. `face(0.0)` therefore asks for no turn of its own — only the model's
        half-turn from glTF's -Y forward, which the root does not know about.

        The blocks are veiled, not hidden: they are still what a bullet meets.
        They line up with the figure to within a few centimetres, measured — the
        model is normalised to the collider's 2.0 m so their heads end level, and
        its torso at +-0.30 m sits inside the 0.36 m capsule. Its shoulders reach
        4 cm wider than the capsule and its outstretched arms 5 cm wider, so a
        shot clipping the very edge of a sleeve is a miss. That is the price of
        having the hitbox be the thing the rules were tuned against.
        """
        reference = self._pick("enemy")
        if reference is None:
            return None
        source = assets.source(reference)
        skinned = source is not None and any(o.type == "ARMATURE" for o in source.objects)
        if skinned:
            clip = clips.attach(reference, f"enemy{index}_clip", host=actor.obj,
                                height=FIGURE_HEIGHT, veil=blocks,
                                yaw_offset=MIXAMO_YAW)
            if clip is not None:
                clip.face(0.0)
                clip.track(self.recorder)
                actor.state["clip"] = clip
            weapon = self._pick("enemy_weapon")
            if weapon:
                assets.instance(weapon, f"enemy{index}_weapon", parent=actor.obj,
                                location=(0.18, 0.22, 1.12),
                                rotation=HELD_WEAPON_ROTATION,
                                length=0.72, into="Actors", anchor="origin")
            return None
        figure = figures.attach(reference, f"enemy{index}_figure", host=actor.obj,
                                height=FIGURE_HEIGHT, veil=blocks)
        if figure is None:
            return None
        figure.face(0.0)
        weapon = self._pick("enemy_weapon")
        if figure.arm_right is not None:
            figure.aim(ENEMY_AIM)
            if weapon:
                figure.hold(1, weapon, f"enemy{index}_weapon",
                            length=WEAPON_LENGTH, rotation=HELD_WEAPON_ROTATION)
        elif weapon:
            # A single-mesh soldier has no hand to hang a gun on, so the
            # rifle rides the actor root at chest height.
            assets.instance(weapon, f"enemy{index}_weapon", parent=actor.obj,
                            location=(0.18, 0.22, 1.12),
                            rotation=HELD_WEAPON_ROTATION,
                            length=0.72, into="Actors", anchor="origin")
        # Without this the video shows a figure sliding about in its build pose:
        # a channel that is never keyed holds whatever it had on frame one.
        figure.track(self.recorder)
        return figure

    def _build_player(self) -> None:
        self.player = kernel.Actor("player", None, position=(0.0, -self.half * 0.55, 0.0),
                                   yaw=0.0, team="player")
        self.pitch = 0.0

        self.camera = camera_rigs.make_camera("fps_cam", lens=32.0, clip_start=0.02)
        self.rig = camera_rigs.FirstPersonRig(self.camera,
                                              eye_height=float(self.p["eye_height"]))
        self.recorder.track(self.camera, channels=("location", "rotation_euler"))

        # A viewmodel: parented to the camera, so it is screen-space and its
        # recoil is a local transform the recorder bakes like anything else.
        #
        # `self.gun` is an empty carrying nothing but that recoil, with the blocks
        # and any model hung under it. The alternative — recoiling the block itself
        # — makes the block's own (0.035, 0.035, 0.20) the parent scale of anything
        # added, so a 0.46 m blaster arrives 9 cm long and squashed flat. Same
        # reason the enemies hang their parts off an unscaled root.
        gun_mat = materials.solid("fps_gun", (0.13, 0.14, 0.17), roughness=0.55,
                                  metallic=0.35)
        self.gun = prims.empty("viewmodel", parent=self.camera,
                               location=WEAPON_MOUNT, into="Viewmodel",
                               display=0.01)
        # Kept low-gloss on purpose — a mirror-metal weapon a few centimetres
        # from a 26 mm lens reflects the whole arena and blows out to a white
        # slab across the bottom of frame. The grip and sight are in metres now
        # that their parent is unscaled, which is the same three blocks the box
        # used to carry in its own squashed units.
        blocks = [
            prims.spawn(prims.BOX, "viewmodel_body", scale=(0.035, 0.035, 0.20),
                        material=gun_mat, into="Viewmodel", parent=self.gun,
                        collide=False),
            prims.spawn(prims.BOX, "viewmodel_grip", location=(0.0, -0.003, 0.024),
                        scale=(0.032, 0.070, 0.110), material=gun_mat,
                        into="Viewmodel", parent=self.gun, collide=False),
            prims.spawn(prims.BOX, "viewmodel_sight", location=(0.0, 0.032, -0.150),
                        scale=(0.018, 0.012, 0.100),
                        material=materials.glow("fps_sight", (0.2, 1.0, 0.9),
                                                strength=2.5),
                        into="Viewmodel", parent=self.gun, shadow=False,
                        collide=False),
        ]
        self.gun_rest = tuple(self.gun.location)
        self.recorder.track(self.gun, channels=("location", "rotation_euler"))

        self.viewmodels = []
        weapon_lengths = [0.55, 1.38]
        for i, reference in enumerate(self._models("weapon") or []):
            made = assets.instance(reference, f"viewmodel_model{i}", parent=self.gun,
                                   rotation=VIEWMODEL_ROTATION,
                                   length=weapon_lengths[i] if i < len(weapon_lengths)
                                   else WEAPON_LENGTH,
                                   anchor="origin",
                                   into="Viewmodel")
            if made is None:
                continue
            for flag in ("visible_shadow", "visible_diffuse", "visible_glossy",
                         "visible_transmission", "visible_volume_scatter"):
                setattr(made, flag, False)
            prims.show(made, i == 0)
            self.viewmodels.append(made)
        if self.viewmodels:
            for block in blocks:
                prims.veil(block)

        # Parent to the gun empty so mount / recoil carry the flash with them.
        self.muzzle = prims.spawn(
            prims.SPHERE, "muzzle_flash", location=(0.0, 0.04, -0.58),
            scale=(0.022, 0.022, 0.034),
            material=materials.glow("fps_muzzle", (1.0, 0.78, 0.28), strength=8.0),
            into="Viewmodel", parent=self.gun, shadow=False)
        prims.show(self.muzzle, False)
        self.recorder.track(self.muzzle, channels=("hide_render",))
        self.muzzle_left = 0

    def _build_vfx_pools(self) -> None:
        """
        Fixed pools of tracers and sparks, cycled round-robin.

        Spawning objects mid-simulation would work, but every new object needs
        its own keyframe history from frame 1 or it pops into existence at the
        origin; a pool is allocated before the bake starts and only ever toggles
        visibility.
        """
        # Impact markers are small and only moderately hot. The render uses the
        # Standard view transform, which clips instead of rolling off, so an
        # emitter is only as coloured as its *dimmest* channel: red at strength 8
        # is (8, 1.6, 1.6) and arrives as a white disc. Keeping the strength
        # under 1/channel means a body hit still reads red and a wall spark
        # orange, which is the whole point of having two of them.
        tracer_mat = materials.glow("fps_tracer", (1.0, 0.78, 0.35), strength=4.6)
        slug_mat = materials.glow("fps_slug", (1.0, 0.88, 0.45), strength=5.0)
        spark_mat = materials.glow("fps_spark", (1.0, 0.55, 0.18), strength=2.6)
        blood_mat = materials.glow("fps_impact_body", (1.0, 0.2, 0.2), strength=3.2)

        # Pooled objects are switched with `prims.show`, which hides them in the
        # window as well as in the video. Toggling `hide_render` alone leaves all
        # twenty-eight of them parked at the origin for the whole of a live
        # session — the video was right and the window was a heap of spheres.
        self.tracers = []
        self.slugs = []
        for i in range(10):
            obj = prims.spawn(prims.CYLINDER, f"tracer{i}", scale=(0.0045, 0.0045, 0.01),
                              material=tracer_mat, into="VFX", shadow=False)
            prims.show(obj, False)
            self.recorder.track(obj, channels=("location", "rotation_euler", "scale",
                                                "hide_render"))
            self.tracers.append(obj)
            slug = prims.spawn(prims.SPHERE, f"slug{i}", scale=(0.006, 0.006, 0.014),
                               material=slug_mat, into="VFX", shadow=False)
            prims.show(slug, False)
            self.recorder.track(slug, channels=("location", "rotation_euler", "scale",
                                                "hide_render"))
            self.slugs.append(slug)

        self.sparks = []
        for i in range(10):
            obj = prims.spawn(prims.SPHERE, f"spark{i}", scale=(0.075, 0.075, 0.075),
                              material=spark_mat, into="VFX", shadow=False)
            prims.show(obj, False)
            self.recorder.track(obj, channels=("location", "hide_render"))
            self.sparks.append(obj)

        self.body_hits = []
        for i in range(8):
            obj = prims.spawn(prims.SPHERE, f"bodyhit{i}", scale=(0.11, 0.11, 0.11),
                              material=blood_mat, into="VFX", shadow=False)
            prims.show(obj, False)
            self.recorder.track(obj, channels=("location", "hide_render"))
            self.body_hits.append(obj)

        self._pool_cursor = {"tracer": 0, "slug": 0, "spark": 0, "body": 0}
        self._expiry: list[tuple] = []   # (object, tick it should hide on)

    def _build_hud(self) -> None:
        self.hud = hud.Hud(self.camera, self.resolution)
        self.hp_bar = self.hud.bar("hp", (-0.93, -0.86), width=0.46, height=0.05,
                                   color=(0.25, 0.95, 0.45))
        self.hud.label("hp_txt", "HP", (-0.93, -0.74), size=0.05)
        self.ammo_pips = self.hud.pip_row("ammo", (0.30, -0.86),
                                          int(self.w["mag_size"]),
                                          size=0.030, gap=0.048,
                                          color=(1.0, 0.85, 0.25))
        self.hud.label("ammo_txt", "AMMO", (0.30, -0.74), size=0.05)
        self.kill_pips = self.hud.pip_row("kills", (0.30, 0.86),
                                          int(self.spec["enemy_count"]),
                                          size=0.030, gap=0.048,
                                          color=(1.0, 0.30, 0.30))
        self.hud.label("kill_txt", "TARGETS", (0.30, 0.75), size=0.05)
        self.damage_flash = self.hud.vignette("dmg", color=(0.95, 0.1, 0.1),
                                              strength=3.0, alpha=0.30)
        self.hud.crosshair("cross")
        self.hud.register(self.recorder)
        self.kill_pips.set(0)

    # ── simulation ────────────────────────────────────────────────────────────

    def tick(self) -> None:
        alive = [e for e in self.enemies if e.alive]

        self._player_think(alive)
        self._enemies_think(alive)
        self._expire_vfx()

        # Head bob is a walking cue, so it is scaled by how much walking is
        # happening. A constant bob is invisible in a video of a policy that
        # never stops moving, and nauseating in a window when standing still.
        bob = sin(self.time * 9.0) * 0.022
        if self.human:
            bob *= min(1.0, abs(self.controls.move_x) + abs(self.controls.move_y))
        self.rig.update(self.player.position, self.player.yaw, self.pitch,
                        bob=bob)
        self._update_hud()

        if not alive and self.cleared_at is None:
            self.cleared_at = self.time
            self.log("arena_cleared", seconds=round(self.time, 2))
            self.finish("arena_cleared")
        if self.hp <= 0.0:
            self.finish("player_down")

    # ── the player ────────────────────────────────────────────────────────────

    def _player_think(self, alive: list) -> None:
        """
        Weapon bookkeeping, then whoever is playing gets to decide.

        The cooldown and the reload timer run above the split because they are
        rules, not decisions: a magazine refills on the same schedule whether a
        person or the policy pulled the trigger, and that is what makes a played
        session comparable with a rendered one.
        """
        dt = self.dt
        self.fire_cooldown = max(0.0, self.fire_cooldown - dt)

        if self.reload_left > 0.0:
            self.reload_left -= dt
            if self.reload_left <= 0.0:
                self.ammo = int(self.w["mag_size"])
                self.log("reload_complete", ammo=self.ammo)

        if self.hp <= 0.0:
            return
        if self.human:
            self._player_input(alive)
        elif alive:
            self._player_policy(alive)

    def _player_input(self, alive: list) -> None:
        """Aim, move and shoot from one tick of human intent."""
        c = self.controls
        dt = self.dt

        self.player.yaw = (self.player.yaw + c.yaw_delta) % 360.0
        self.pitch = max(-MAX_PITCH, min(MAX_PITCH, self.pitch + c.pitch_delta))

        # Diagonals are normalised: without this, holding W and D moves 41%
        # faster than holding W, and every player who notices holds both.
        mx, my = c.move_x, c.move_y
        magnitude = (mx * mx + my * my) ** 0.5
        if magnitude > 1.0:
            mx, my = mx / magnitude, my / magnitude

        speed = float(self.p["move_speed"]) * (RUN_MULTIPLIER if c.run else 1.0)
        f = camera_rigs.forward(self.player.yaw)
        r = camera_rigs.right(self.player.yaw)
        self._move_clamped(self.player,
                           (f[0] * my + r[0] * mx) * speed * dt,
                           (f[1] * my + r[1] * mx) * speed * dt,
                           radius=BODY_RADIUS)

        if c.pressed("weapon_next") and len(self.loadout) > 1:
            self._cycle_weapon()

        if self.reload_left > 0.0:
            return
        mag_size = int(self.w["mag_size"])
        if c.reload and self.ammo < mag_size:
            self.reload_left = float(self.w["reload_time"])
            self.log("reload_start", requested=True)
        elif c.fire and self.ammo <= 0:
            # Pulling an empty trigger reloads. The alternative is a player
            # holding a dead mouse button wondering what broke.
            self.reload_left = float(self.w["reload_time"])
            self.log("reload_start", dry_fire=True)
        elif c.fire and self.fire_cooldown <= 0.0:
            self._fire(alive)

    def _player_policy(self, alive: list) -> None:
        """The unattended player: acquire the nearest enemy, hold range, fire."""
        dt = self.dt
        target = min(alive, key=lambda e: e.planar_distance_to(self.player))
        dx = target.x - self.player.x
        dy = target.y - self.player.y
        wanted_yaw = degrees(atan2(-dx, dy)) % 360.0
        error = (wanted_yaw - self.player.yaw + 180.0) % 360.0 - 180.0

        turn = float(self.p["turn_rate"]) * dt
        self.player.yaw = (self.player.yaw + max(-turn, min(turn, error))) % 360.0

        # Pitch onto the target's chest, so the shot and the picture agree.
        distance = max(0.1, (dx * dx + dy * dy) ** 0.5)
        eye_z = self.player.z + float(self.p["eye_height"])
        self.pitch = degrees(atan2((target.z + 1.05) - eye_z, distance))

        self._player_move(target, distance, dt)

        if abs(error) < 6.0 and self.reload_left <= 0.0:
            if self.ammo <= 0:
                self.reload_left = float(self.w["reload_time"])
                self.log("reload_start")
            elif self.fire_cooldown <= 0.0:
                self._fire(alive)

        if (self.time > 5.0 and len(self.loadout) > 1
                and not getattr(self, "_switched", False)):
            self._switched = True
            self._cycle_weapon()

    def _cycle_weapon(self) -> None:
        self.weapon_index = (self.weapon_index + 1) % len(self.loadout)
        self.w = dict(self.spec["weapon"], **self.loadout[self.weapon_index])
        self.ammo = int(self.w["mag_size"])
        self.reload_left = 0.0
        name = self.w.get("name", f"weapon{self.weapon_index}")
        self.log("weapon_switch", weapon=name, index=self.weapon_index)
        models = self._models("weapon")
        if models and hasattr(self, "viewmodels"):
            for i, obj in enumerate(self.viewmodels):
                prims.show(obj, i == self.weapon_index % len(self.viewmodels))

    def _player_move(self, target, distance: float, dt: float) -> None:
        speed = float(self.p["move_speed"])
        preferred = float(self.p["preferred_range"])
        f = camera_rigs.forward(self.player.yaw)
        r = camera_rigs.right(self.player.yaw)

        # Close to preferred range, and strafe the rest of the time — a shooter
        # AI that only walks at its target films like a turret.
        advance = 0.0
        if distance > preferred + 1.5:
            advance = 1.0
        elif distance < preferred - 1.5:
            advance = -1.0
        strafe = sin(self.time * 1.35) * 0.85

        dx = (f[0] * advance + r[0] * strafe) * speed * dt
        dy = (f[1] * advance + r[1] * strafe) * speed * dt
        self._move_clamped(self.player, dx, dy, radius=BODY_RADIUS)

    def _move_clamped(self, actor, dx: float, dy: float, radius: float) -> None:
        """Move, then push back out of the walls and any cover it entered."""
        limit = self.half - 1.0 - radius
        alley = float(self.spec.get("alley_length", 18.0))
        aw = float(self.spec.get("alley_width", 4.2)) * 0.5 - radius - 0.2

        def _walls(x: float, y: float) -> tuple[float, float]:
            x = max(-limit, min(limit, x))
            y = max(-limit, min(limit + alley, y))
            if y > self.half - 0.5:
                x = max(-aw, min(aw, x))
            return x, y

        nx, ny = _walls(actor.x + dx, actor.y + dy)
        # Extra passes: one crate can shove a shoulder into the next, and a
        # Mixamo walk plant sits outside a single-circle test.
        for _ in range(4):
            for cx, cy, cr in self.cover:
                ddx, ddy = nx - cx, ny - cy
                d = (ddx * ddx + ddy * ddy) ** 0.5
                keep = cr + radius + 0.26
                if d < 1e-6:
                    nx, ny = cx + keep, cy
                elif d < keep:
                    nx = cx + ddx / d * keep
                    ny = cy + ddy / d * keep
            for other in getattr(self, "enemies", ()):
                if other is actor or not other.alive:
                    continue
                ddx, ddy = nx - other.x, ny - other.y
                d = (ddx * ddx + ddy * ddy) ** 0.5
                keep = radius + BODY_RADIUS + 0.16
                if d < 1e-6:
                    nx = other.x + keep
                elif d < keep:
                    nx = other.x + ddx / d * keep
                    ny = other.y + ddy / d * keep
            if actor is not self.player:
                ddx, ddy = nx - self.player.x, ny - self.player.y
                d = (ddx * ddx + ddy * ddy) ** 0.5
                keep = radius + BODY_RADIUS + 0.16
                if 1e-6 < d < keep:
                    nx = self.player.x + ddx / d * keep
                    ny = self.player.y + ddy / d * keep
            nx, ny = _walls(nx, ny)
        actor.x, actor.y = nx, ny

    # ── shooting ──────────────────────────────────────────────────────────────

    def _fire(self, alive: list) -> None:
        import mathutils  # noqa: PLC0415

        self.fire_cooldown = float(self.w["fire_interval"])
        self.ammo -= 1
        self.shots += 1

        spread = float(self.w["spread_deg"])
        yaw = self.player.yaw + self.rng.gauss(0.0, spread)
        pitch = self.pitch + self.rng.gauss(0.0, spread)
        direction = mathutils.Vector(camera_rigs.aim_vector(yaw, pitch))

        eye = self.rig.eye(self.player.position)
        origin = mathutils.Vector(eye) + direction * MUZZLE_OFFSET

        hit, point, _, _, obj, _ = self._ray(origin, direction, float(self.w["range"]))
        end = point if hit else (origin + direction * float(self.w["range"]))

        self._show_tracer(origin, end)
        prims.show(self.muzzle, True)
        self.muzzle_left = VFX_HOLD
        self._recoil()

        victim = self._actor_for(obj) if hit else None
        if victim is not None and victim.alive:
            self.hits += 1
            damage = float(self.w["damage"])
            victim.state["hp"] -= damage
            self.damage_dealt += damage
            self._show(self.body_hits, "body", end)
            if victim.state["hp"] <= 0.0:
                self._kill(victim)
            else:
                self.log("enemy_hit", enemy=victim.name,
                         hp_left=round(victim.state["hp"], 1))
        elif hit:
            self._show(self.sparks, "spark", end)
            self.log("shot_blocked", surface=getattr(obj, "name", "?"))
        else:
            self.log("shot_missed")

    def _ray(self, origin, direction, distance: float):
        """
        Cast against the colliders this level built, and nothing else.

        `self.solid` is every wall, crate, pillar and body part the rules reason
        about; the scenery hung over them, the HUD and the viewmodel are not in it
        and a shot passes through them. That is what lets the art be changed
        without changing a single event — see `kernel.cast`, which also refreshes
        the depsgraph first, because actors were moved this tick by assigning
        `obj.location` and Blender does not update `matrix_world` until it is
        evaluated. Skipping that tests the shot against last tick's positions,
        which at 5 m/s is a body-width of error.
        """
        return kernel.cast(origin, direction, distance, self.solid)

    def _actor_for(self, obj):
        """Map a hit object back to its actor, including hit parts like heads."""
        if obj is None:
            return None
        name = obj.name
        for enemy in self.enemies:
            if enemy.obj.name == name or any(p.name == name
                                             for p in enemy.state["parts"]):
                return enemy
        return None

    def _kill(self, victim) -> None:
        victim.alive = False
        victim.state["hp"] = 0.0
        self.kills += 1
        self.log("enemy_killed", enemy=victim.name, at=round(self.time, 2),
                 kills=self.kills)

    def _recoil(self) -> None:
        self.gun.location = (self.gun_rest[0],
                             self.gun_rest[1] + 0.012,
                             self.gun_rest[2] + 0.030)
        self.gun.rotation_euler = (radians(-4.0), 0.0, 0.0)

    # ── enemies ───────────────────────────────────────────────────────────────

    def _enemies_think(self, alive: list) -> None:
        dt = self.dt
        for enemy in self.enemies:
            if not enemy.alive:
                self._settle_corpse(enemy, dt)
                continue

            dx = self.player.x - enemy.x
            dy = self.player.y - enemy.y
            distance = max(0.1, (dx * dx + dy * dy) ** 0.5)
            enemy.yaw = degrees(atan2(-dx, dy)) % 360.0

            f = camera_rigs.forward(enemy.yaw)
            r = camera_rigs.right(enemy.yaw)
            advance = 1.0 if distance > float(self.e["engage_range"]) * 0.55 else -0.25
            strafe = enemy.state["strafe"] * 0.9
            speed = float(self.e["move_speed"])
            was = (enemy.x, enemy.y)
            self._move_clamped(enemy,
                               (f[0] * advance + r[0] * strafe) * speed * dt,
                               (f[1] * advance + r[1] * strafe) * speed * dt,
                               radius=BODY_RADIUS)
            if self.rng.random() < 0.012:
                enemy.state["strafe"] *= -1.0

            enemy.obj.location = (enemy.x, enemy.y, 0.0)
            enemy.obj.rotation_euler = (0.0, 0.0, radians(enemy.yaw))
            # Distance actually covered, not speed times dt: the clamp against
            # walls and cover is what decides how far it got, and a stride driven
            # by intent keeps walking on the spot against a crate.
            enemy.state["walked"] += hypot(enemy.x - was[0], enemy.y - was[1])
            self._pose_enemy(enemy, distance)

            enemy.state["fire_cd"] -= dt
            if enemy.state["fire_cd"] <= 0.0 and distance < float(self.e["engage_range"]):
                enemy.state["fire_cd"] = float(self.e["fire_interval"])
                self._enemy_shoot(enemy, distance)

    def _pose_enemy(self, enemy, distance: float) -> None:
        """
        Put the figure into the pose this tick's numbers already describe.

        Reads state and writes only to the model, so there is nothing here a
        metric could see. The order matters: the walk sets all four limbs, then
        the aim overrides the arms, which leaves the legs striding while the
        weapon stays levelled at the player — a walk cycle that lets go of the gun
        to swing its arms is the tell that gives away a procedural pose.
        """
        figure = enemy.state.get("figure")
        clip = enemy.state.get("clip")
        if clip is not None:
            if not enemy.alive:
                fallen = enemy.state.get("fall", 0.0)
                if clip.has("death"):
                    clip.play("death", fallen * 0.8, loop=False)
                else:
                    clip.play("idle", 0.0)
                    clip.overlay_knockdown(fallen)
                return
            speed = float(self.e["move_speed"]) if distance > 2.4 else 0.0
            clip.locomote(enemy.state["walked"], speed=speed, clock=self.time)
            if distance < float(self.e["engage_range"]):
                clip.overlay_aim(0.85)
            return
        if figure is None:
            return
        figure.walk(enemy.state["walked"])
        figure.aim(ENEMY_AIM)
        # The enemy's eye line is fixed at 1.35 m by the rules; matching the head
        # to it is what makes the figure look like it is the thing shooting.
        eye_z = self.player.z + float(self.p["eye_height"])
        figure.look(degrees(atan2(eye_z - 1.35, max(distance, 0.5))))

    def _enemy_shoot(self, enemy, distance: float) -> None:
        import mathutils  # noqa: PLC0415

        self.incoming += 1
        eye = mathutils.Vector((enemy.x, enemy.y, 1.35))
        aim = mathutils.Vector(self.rig.eye(self.player.position)) - eye
        length = aim.length
        if length < 1e-4:
            return
        aim /= length

        # Cover protects the player too: the same ray that stops the player's
        # shots stops the enemy's, so hiding behind a crate actually works.
        # The player has no body mesh in a first-person view, so anything the
        # ray reaches before the eye position is, by definition, in the way.
        hit, point, _, _, _, _ = self._ray(eye + aim * 0.7, aim, length)
        self._show_tracer(eye + aim * 0.7, point if hit else eye + aim * length,
                          enemy_shot=True)
        if hit:
            self._show(self.sparks, "spark", point)
            self.log("enemy_shot_blocked", enemy=enemy.name)
            return

        if self.rng.random() < float(self.e["accuracy"]) * (1.0 - min(distance / 40.0, 0.6)):
            damage = float(self.e["damage"])
            self.hp = max(0.0, self.hp - damage)
            self.damage_taken += damage
            self.damage_flash.trigger()
            self.log("player_hit", enemy=enemy.name, hp_left=round(self.hp, 1))
        else:
            self.log("enemy_missed", enemy=enemy.name)

    def _settle_corpse(self, enemy, dt: float) -> None:
        """Topple over the first second of death, then stay down."""
        fallen = enemy.state.get("fall", 0.0)
        if fallen < 1.0:
            fallen = min(1.0, fallen + dt * 2.4)
            enemy.state["fall"] = fallen
            # Authored death clips already contain the fall. Mixamo Soldier
            # does not ship one — tumble the root and crumple the pose so a
            # kill is a knockdown, not a freeze. Keep Z small so the mesh
            # settles on the floor instead of through it.
            clip = enemy.state.get("clip")
            if clip is None or not clip.has("death"):
                enemy.obj.rotation_euler = (radians(74.0 * fallen), 0.0,
                                            radians(enemy.yaw))
                enemy.obj.location = (enemy.x, enemy.y, 0.06 * fallen)
        self._pose_enemy(enemy, 0.0)

    # ── vfx / hud ─────────────────────────────────────────────────────────────

    def _show_tracer(self, a, b, enemy_shot: bool = False) -> None:
        import mathutils  # noqa: PLC0415

        start = mathutils.Vector(a)
        end = mathutils.Vector(b)
        delta = end - start
        length = delta.length
        if length < 1e-6:
            return
        direction = delta.normalized()
        streak = min(length, TRACER_METRES)
        tip = start + direction * streak

        index = self._pool_cursor["tracer"] % len(self.tracers)
        self._pool_cursor["tracer"] += 1
        obj = self.tracers[index]
        prims.stretch_between(obj, start, tip,
                              radius=TRACER_RADIUS_ENEMY if enemy_shot else TRACER_RADIUS)
        prims.show(obj, True)
        self._expiry.append((obj, self.frame + VFX_HOLD))

        slug = self.slugs[index % len(self.slugs)]
        slug.location = tuple(start + direction * min(length, streak * 0.85))
        slug.rotation_euler = delta.to_track_quat("Z", "Y").to_euler()
        slug.scale = (0.006, 0.006, 0.014)
        prims.show(slug, True)
        self._expiry.append((slug, self.frame + VFX_HOLD))

    def _show(self, pool: list, key: str, location) -> None:
        index = self._pool_cursor[key] % len(pool)
        self._pool_cursor[key] += 1
        obj = pool[index]
        obj.location = tuple(location)
        prims.show(obj, True)
        self._expiry.append((obj, self.frame + VFX_HOLD))

    def _expire_vfx(self) -> None:
        still_live = []
        for obj, until in self._expiry:
            if self.frame >= until:
                prims.show(obj, False)
            else:
                still_live.append((obj, until))
        self._expiry = still_live

        if self.muzzle_left > 0:
            self.muzzle_left -= 1
            if self.muzzle_left == 0:
                prims.show(self.muzzle, False)

        # Ease the viewmodel back to rest after recoil.
        gx, gy, gz = self.gun.location
        rx, ry, rz = self.gun_rest
        k = 0.35
        self.gun.location = (rx + (gx - rx) * (1 - k), ry + (gy - ry) * (1 - k),
                             rz + (gz - rz) * (1 - k))
        self.gun.rotation_euler = (self.gun.rotation_euler[0] * (1 - k), 0.0, 0.0)

    def _update_hud(self) -> None:
        self.hp_bar.set(self.hp / float(self.p["hp"]))
        self.ammo_pips.set(0 if self.reload_left > 0 else self.ammo)
        self.kill_pips.set(self.kills)
        self.damage_flash.advance()

    # ── report ────────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        accuracy = (self.hits / self.shots) if self.shots else 0.0
        return {
            "shots_fired": self.shots,
            "shots_on_target": self.hits,
            "accuracy": round(accuracy, 3),
            "kills": self.kills,
            "enemies": len(self.enemies),
            "arena_cleared": self.cleared_at is not None,
            "clear_time_sec": round(self.cleared_at, 2) if self.cleared_at else None,
            "player_hp_left": round(self.hp, 1),
            "damage_dealt": round(self.damage_dealt, 1),
            "damage_taken": round(self.damage_taken, 1),
            "enemy_shots": self.incoming,
            "reloads": self.count_events("reload_complete"),
        }

    def verdict(self, summary: dict) -> tuple:
        """
        A shooter is working when the whole loop fired at least once: shots left
        the gun, some connected, something died, cover stopped something, and
        the player was shot at. Any of these missing means a broken rule, not a
        bad player.
        """
        problems = []
        if summary["shots_fired"] == 0:
            problems.append("weapon never fired")
        if summary["shots_on_target"] == 0:
            problems.append("no shot ever hit an enemy")
        if summary["kills"] == 0:
            problems.append("no enemy was killed")
        if summary["enemy_shots"] == 0:
            problems.append("enemies never returned fire")
        if not self.count_events("shot_blocked") and not self.count_events(
                "enemy_shot_blocked"):
            problems.append("cover never blocked a shot — geometry may be ignored")
        return (not problems), problems


if __name__ == "__main__":
    kernel.main(FpsArena)
