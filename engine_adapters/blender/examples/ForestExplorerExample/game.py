"""
Third-person forest explorer — generated mechanic, Blender runtime.

Chests open on interact; monsters can be killed; melee slash and a real
light-arrow projectile share a cooldown. The hero starts armed — opening the
chest is a recon beat, not a weapon pickup. Unattended, an AI drives the same
Controls surface a human would.

第三人称森林探险游戏——采用程序生成的机制，基于Blender运行时开发。

互动时宝箱会打开；怪物可被击杀；近战劈砍与真正的光箭投射物共享冷却时间。主角初始即携带武器——打开宝箱只是侦察行为，并非拾取武器。若无人操控，AI会接管角色，其控制逻辑与人类玩家一致。
"""

import os
import sys
from math import atan2, cos, degrees, hypot, radians, sin
from pathlib import Path


def _bootstrap_repo_root() -> Path:
    env = os.environ.get("GAMEFACTORY3A_ROOT") or os.environ.get("AAAGF_REPO_ROOT")
    if env and (Path(env) / "engine_adapters").is_dir():
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        if (parent / "engine_adapters" / "blender" / "game").is_dir():
            return parent
    raise RuntimeError("cannot locate GameFactory-3A; set GAMEFACTORY3A_ROOT")


_ROOT = _bootstrap_repo_root()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine_adapters.blender.game import (  # noqa: E402
    assets, camera_rigs, clips, figures, hud, kernel, materials, prims,
)

SLASH_RANGE = 2.1
ARROW_RANGE = 7.2
ARROW_SPEED = 18.0
ARROW_HIT = 1.12
TREE_SPACING = 1.85
BOW_FACE_LIMIT = 7.0
CAMPFIRE = (-2.85, 3.15)
DAYNIGHT_BLEND_TICKS = 18
FIGURE_HEIGHT = 1.82
RUN_MULTIPLIER = 1.6
SLASH_TICKS = 16
DRAW_TICKS = 12
SWITCH_TICKS = 14
LID_TICKS = 20
PICKUP_TICKS = 22
SWORD_HEIGHT = 0.68
TURN_RATE = 5.5
YAW_MOVE_LIMIT = 50.0
# Supply chest sits to the player's right so a chase camera looking +Y sees
# the lid open without the body covering it.
# 补给宝箱位于玩家右侧，这样朝向+Y方向的追踪摄像机就能看到开箱过程，且不会被身体遮挡。
SWORD_CHEST = (2.70, 1.80)
# Mixamo faces +Y after the glTF Y-up conversion. KayKit's bind faces −Y,
# so offset 0 moonwalks them (the "walking backwards / upside down" look).
# Mixamo格式模型在glTF Y轴转换后朝向+Y；KayKit绑定的模型朝向−Y，因此偏移量为0时会出现倒着行走的效果（“向后走/上下颠倒”的视觉表现）。
MIXAMO_YAW = 0.0
KAYKIT_YAW = 180.0
# Kenney blocky dolls: glTF faces −Y, so the figure adapter's +180 is required.
# Kenney系列方块人模型：glTF格式下朝向−Y，因此需要通过角色适配器将其旋转+180度来调整。
DOLL_YAW = 180.0
MONSTER_HEIGHT = 1.92
DOLL_HEAD_SCALE = 1.62
PLAYER_RADIUS = 0.48
MONSTER_RADIUS = 0.48
# Death_A crumples ~1 m off the root. Melee keep-out is only ~1.1 m, so the
# falling mesh lands inside the hero unless the corpse is drawn further out.
# Sim x/y stay at the kill spot (gameplay radii unchanged); this is visual.
# Death_A模型会在离地面约1米处蜷缩；近战攻击的避让范围仅约1.1米，因此若尸体不向外移动，掉落的模型就会嵌入主角体内。
# 模拟的世界坐标x/y仍保持在击杀点（游戏玩法中的碰撞范围不变），这只是视觉上的处理。
CORPSE_SLIDE = 1.75
TRAIL_BEADS = 5
WALL_HALF = 15.0
WALL_HEIGHT = 3.4
SEGMENT = 2.05


class ForestExplorer(kernel.Game):
    genre = "rpg"
    default_spec = {
        "duration_sec": 30.0, "fps": 30, "resolution": (960, 540),
        "samples": 16, "seed": 9, "forest_radius": 26.0, "tree_count": 400,
        "grass_count": 520,
        "chest_count": 1, "monster_count": 4,
        "sky_hdri": "/Library/hdris/forest_slope_2k.hdr",
        "sky_hdri_night": "/Library/hdris/dikhololo_night_2k.hdr",
        "sky_strength": 0.34, "sky_backdrop": 0.90, "sun_energy": 1.45,
        "fill_energy": 0.22, "fire_energy": 520.0, "night": False,
        "player": {"hp": 90.0, "move_speed": 2.2, "melee_damage": 28.0,
                   "arrow_damage": 18.0, "attack_interval": 0.70},
        "monster": {"hp": 32.0, "damage": 8.0, "move_speed": 1.85, "engage": 9.0},
    }

    def build(self) -> None:
        self.p, self.m = self.spec["player"], self.spec["monster"]
        self.radius = float(self.spec["forest_radius"])
        sword_models = self.models("sword")
        self.sword_ref = sword_models[0] if sword_models else None
        self._setup_day_night_world()
        self.light_sun = kernel.add_sun(
            "day_sun", energy=1.45,
            rotation=(radians(48), radians(12), radians(32)),
            angle=0.52, shadows=True)
        self.light_sun.data.color = (1.0, 0.94, 0.84)
        self.light_moon = kernel.add_sun(
            "moon", energy=0.0,
            rotation=(radians(62), radians(8), radians(205)),
            angle=0.62, shadows=True)
        self.light_moon.data.color = (0.55, 0.70, 1.0)
        self.light_fill = kernel.add_sun(
            "fill", energy=0.22,
            rotation=(radians(-38), radians(-12), radians(-150)),
            angle=1.10, shadows=False)
        self.light_fill.data.color = (1.0, 0.92, 0.82)
        self.obstacles: list[tuple] = []
        self.hp = float(self.p["hp"])
        self.attack_cd = 0.0
        self.slash_left = 0
        self.slash_hits: list = []
        self.pickup_left = 0
        # Knights arrive armed. The chest is an interact beat, not a saber drop.
        # 骑士们全副武装前来。宝箱属于可交互元素，并非剑类武器的掉落物。
        self.has_sword = True
        self.held_sword = None
        self.held_bow = None
        self.weapon = "sword"
        self.arrows: list[dict] = []
        self.draw_left = 0
        self.switch_left = 0
        self._pending_arrow = False
        self._arrow_target = None
        self._volleys: dict[str, int] = {}
        self.chests_opened = 0
        self.kills = 0
        self.damage_dealt = 0.0
        self.walked = 0.0
        self.player_speed = 0.0
        self._build_forest()
        self._build_chests()
        self._build_monsters()
        self._build_player()
        self._build_vfx()
        self._build_hud()
        night0 = bool(self.spec.get("night", False))
        self._daynight_target = 1.0 if night0 else 0.0
        self._daynight_blend = self._daynight_target
        self._auto_night = night0
        self._apply_day_night(self._daynight_blend)

    def _skinned(self, reference: str) -> bool:
        src = assets.source(reference)
        return src is not None and any(o.type == "ARMATURE" for o in src.objects)

    def _setup_day_night_world(self) -> None:
        """Two HDRIs mixed by Fac: 0 is a soft day, 1 is night.
        通过Fac参数混合两种HDRI贴图：0代表白天场景，1代表夜晚场景。
        """
        import bpy  # noqa: PLC0415

        world = bpy.context.scene.world
        nodes, links = world.node_tree.nodes, world.node_tree.links
        background = nodes.get("Background")
        if background is None:
            return
        for link in list(background.inputs[0].links):
            links.remove(link)

        def env_tex(name, path):
            resolved = assets.resolve(path)
            tex = nodes.new("ShaderNodeTexEnvironment")
            tex.name = name
            tex.label = name
            if resolved is not None and resolved.is_file():
                tex.image = bpy.data.images.load(str(resolved), check_existing=True)
            return tex

        day_path = self.spec.get("sky_hdri") or "/Library/hdris/forest_slope_2k.hdr"
        night_path = (self.spec.get("sky_hdri_night")
                      or "/Library/hdris/dikhololo_night_2k.hdr")
        day = env_tex("rpg_sky_day", day_path)
        night = env_tex("rpg_sky_night", night_path)
        mapping = nodes.new("ShaderNodeMapping")
        mapping.inputs["Rotation"].default_value = (0.0, 0.0, 0.0)
        coord = nodes.new("ShaderNodeTexCoord")
        links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], day.inputs["Vector"])
        links.new(mapping.outputs["Vector"], night.inputs["Vector"])

        day_dim = nodes.new("ShaderNodeMix")
        day_dim.data_type = "RGBA"
        day_dim.blend_type = "MULTIPLY"
        day_dim.inputs["Factor"].default_value = 1.0
        day_dim.inputs["B"].default_value = (0.38, 0.38, 0.38, 1.0)
        links.new(day.outputs["Color"], day_dim.inputs["A"])

        night_dim = nodes.new("ShaderNodeMix")
        night_dim.data_type = "RGBA"
        night_dim.blend_type = "MULTIPLY"
        night_dim.inputs["Factor"].default_value = 1.0
        night_dim.inputs["B"].default_value = (0.70, 0.70, 0.70, 1.0)
        links.new(night.outputs["Color"], night_dim.inputs["A"])

        mix = nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.inputs["Factor"].default_value = 0.0
        links.new(day_dim.outputs["Result"], mix.inputs["A"])
        links.new(night_dim.outputs["Result"], mix.inputs["B"])
        links.new(mix.outputs["Result"], background.inputs[0])
        background.inputs[1].default_value = 1.0
        self._sky_mix = mix

    def _toggle_day_night(self) -> None:
        self._daynight_target = 0.0 if self._daynight_target > 0.5 else 1.0
        self.log("day_night", mode="night" if self._daynight_target > 0.5 else "day")

    def _apply_day_night(self, night: float) -> None:
        """`night` 0 = soft day, 1 = campfire night. Keyframed for the bake.
        `night`值为0表示柔和白昼，为1表示篝火之夜。该参数用于烘焙时的关键帧设置。
        """
        n = max(0.0, min(1.0, night))
        d = 1.0 - n
        watts = float(self.spec.get("fire_energy", 520.0))
        self.light_sun.data.energy = 1.45 * d
        self.light_moon.data.energy = 0.30 * n
        self.light_fill.data.energy = 0.22 * d + 0.08 * n
        self.light_fill.data.color = (
            1.0 * d + 0.45 * n,
            0.92 * d + 0.58 * n,
            0.82 * d + 0.95 * n,
        )
        self.light_fire.data.energy = watts * (0.16 * d + 1.0 * n)
        self.light_fire_fill.data.energy = watts * (0.04 * d + 0.28 * n)
        if getattr(self, "_sky_mix", None) is not None:
            self._sky_mix.inputs["Factor"].default_value = n
        if getattr(self, "fire_core", None) is not None:
            glow = 0.35 + 0.65 * n
            self.fire_core.scale = (0.16 * glow, 0.16 * glow, 0.18 * glow)
            self.fire_flame.scale = (0.11 * glow, 0.11 * glow, 0.22 * glow)
            prims.show(self.fire_core, n > 0.12)
            prims.show(self.fire_flame, n > 0.12)
        frame = max(1, int(self.frame) + 1)
        for lamp in (self.light_sun, self.light_moon, self.light_fill,
                     self.light_fire, self.light_fire_fill):
            lamp.data.keyframe_insert("energy", frame=frame)
        self.light_fill.data.keyframe_insert("color", frame=frame)
        if getattr(self, "_sky_mix", None) is not None:
            self._sky_mix.inputs["Factor"].keyframe_insert("default_value", frame=frame)

    def _in_lane(self, x: float, y: float) -> bool:
        """Keep scenery out of the spawn, the chest, the fight, and the camera.
        确保场景元素不会出现在出生点、宝箱处、战斗区域以及摄像机视野内。
        """
        if hypot(x, y) < 6.2:
            return True
        if abs(x) < 6.2 and -4.2 < y < 14.5:
            return True
        if hypot(x - SWORD_CHEST[0], y - SWORD_CHEST[1]) < 5.5:
            return True
        return False

    def _obstruct_segment(self, x0, y0, x1, y1, radius: float = 0.50) -> None:
        """Approximate a long wall with overlapping keep-out circles.
        通过重叠的禁入圆形来模拟长墙效果。
        """
        length = hypot(x1 - x0, y1 - y0)
        steps = max(1, int(length / max(radius * 1.35, 0.4)))
        for i in range(steps + 1):
            t = i / steps
            self.obstacles.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, radius))

    def _in_clearing(self, x: float, y: float) -> bool:
        """The fight glade, the chest, and the campfire stay open.
        战斗空地、宝箱处以及篝火周围区域保持开放。
        """
        if hypot(x, y) < 6.5:
            return True
        if hypot(x - SWORD_CHEST[0], y - SWORD_CHEST[1]) < 3.4:
            return True
        if hypot(x - CAMPFIRE[0], y - CAMPFIRE[1]) < 1.9:
            return True
        return False

    def _occupied(self, x: float, y: float, keep: float) -> bool:
        if self._in_clearing(x, y):
            return True
        return any(hypot(x - ox, y - oy) < keep + or_ for ox, oy, or_ in self.obstacles)

    def _build_forest(self) -> None:
        """A forest glade: photoreal pines, grass, and a stone fire pit."""
        ground = materials.surface(
            "rpg_ground", (self.spec.get("surfaces") or {}).get("ground"),
            color=(0.08, 0.16, 0.07), roughness=0.95, metres=8.0)
        prims.spawn(prims.PLANE, "forest_floor",
                    scale=(self.radius + 12.0, self.radius + 12.0, 1.0),
                    material=ground, into="Level")
        self._scatter_campfire()
        self._scatter_trees()
        self._scatter_landmarks()
        self._scatter_ruins()
        self._scatter_grass()
        self._scatter_undergrowth()
        self._scatter_wisps()

    def _scatter_campfire(self) -> None:
        """Photoreal stone fire pit, branches, and a warm point light."""
        x, y = CAMPFIRE
        pit = "/Library/models/polyhaven/stone_fire_pit/stone_fire_pit_1k.gltf"
        wood = "/Library/models/polyhaven/dry_branches_medium_01/dry_branches_medium_01_1k.gltf"
        stones = "/Library/models/kenney_nature_kit/campfire_stones.glb"
        logs = "/Library/models/kenney_nature_kit/campfire_logs.glb"
        if assets.source(pit) is not None:
            assets.instance(pit, "campfire_ring", location=(x, y, 0.0),
                            height=0.48, into="Level")
        elif assets.source(stones) is not None:
            assets.instance(stones, "campfire_ring", location=(x, y, 0.0),
                            height=0.22, into="Level")
        if assets.source(wood) is not None:
            assets.instance(wood, "campfire_wood", location=(x, y, 0.06),
                            rotation=(0.0, 0.0, 0.7), height=0.32, into="Level")
        elif assets.source(logs) is not None:
            assets.instance(logs, "campfire_wood", location=(x, y, 0.04),
                            height=0.20, into="Level")
        ember = materials.glow("rpg_fire_core", (1.0, 0.55, 0.12), strength=18.0)
        flame = materials.glow("rpg_fire_flame", (1.0, 0.38, 0.05), strength=11.0)
        self.fire_core = prims.spawn(
            prims.SPHERE, "campfire_core", location=(x, y, 0.28),
            scale=(0.16, 0.16, 0.18), material=ember,
            into="Level", shadow=False, collide=False)
        self.fire_flame = prims.spawn(
            prims.SPHERE, "campfire_flame", location=(x, y, 0.48),
            scale=(0.11, 0.11, 0.22), material=flame,
            into="Level", shadow=False, collide=False)
        watts = float(self.spec.get("fire_energy", 520.0))
        self.light_fire = kernel.add_point(
            "campfire_light", energy=watts * 0.18,
            location=(x, y, 1.15),
            color=(1.0, 0.52, 0.18), radius=0.28, shadows=True)
        self.light_fire_fill = kernel.add_point(
            "campfire_fill", energy=watts * 0.05,
            location=(x, y, 2.40),
            color=(1.0, 0.62, 0.28), radius=0.55, shadows=False)
        self.obstacles.append((x, y, 0.62))
        self.recorder.track(self.fire_core, channels=("hide_render", "scale"))
        self.recorder.track(self.fire_flame, channels=("hide_render", "scale"))

    def _tree_height(self, ref: str | None, radius: float) -> float:
        low = (ref or "").lower()
        if "fir_tree" in low or "pine_tree" in low:
            return self.look.uniform(9.0, 13.0)
        if "sapling_medium" in low:
            return self.look.uniform(4.4, 6.4)
        if "sapling" in low:
            return self.look.uniform(2.3, 3.6)
        if "tree_small" in low:
            return self.look.uniform(5.0, 7.4)
        if radius > 14.0:
            return self.look.uniform(6.2, 8.5)
        return self.look.uniform(3.6, 5.8)

    def _tree_for_ring(self, trees: list, radius: float, index: int):
        """Keep the 12 m firs off the glade so the chase camera is not in a canopy."""
        if not trees:
            return None
        tall, medium, small = [], [], []
        for ref in trees:
            low = ref.lower()
            if "fir_tree" in low or "pine_tree" in low:
                tall.append(ref)
            elif "sapling_medium" in low or "tree_small" in low:
                medium.append(ref)
            else:
                small.append(ref)
        if radius < 9.2:
            pool = small or medium or trees
        elif radius < 13.5:
            pool = medium or small or trees
        else:
            pool = (tall + medium) or trees
        return pool[index % len(pool)]

    def _tree_gap(self, radius: float) -> float:
        """Inner hedge stays camera-safe; the stand beyond packs tighter."""
        if radius < 11.0:
            return TREE_SPACING
        if radius < 16.0:
            return 1.22
        return 1.05

    def _scatter_trees(self) -> None:
        trees = self.models("tree")
        n = int(self.spec.get("tree_count", 400))
        spots: list[tuple[float, float, float]] = []
        # Inner rings hold the glade edge. Outer rings used to starve because
        # tree_count was spent on the hedge first — counts now grow with
        # circumference so the floor past the first circle fills in.
        rings = (
            (6.9, 22), (8.2, 26), (9.4, 30),
            (10.6, 34), (11.7, 38), (12.8, 42), (13.9, 44),
            (15.0, 46), (16.1, 46), (17.2, 46), (18.3, 44),
            (19.4, 42), (20.5, 40), (21.6, 38), (22.7, 36),
            (23.8, 32), (24.9, 30), (26.0, 28),
        )
        for radius, count in rings:
            gap = self._tree_gap(radius)
            offset = 0.09 + radius * 0.017
            for i in range(count):
                angle = offset + i * (6.28318 / count)
                jitter = self.look.uniform(-0.55, 0.55)
                r = radius + jitter
                x, y = cos(angle) * r, sin(angle) * r
                if self._in_clearing(x, y):
                    continue
                if any(hypot(x - px, y - py) < gap for px, py, _r in spots):
                    continue
                spots.append((x, y, r))
        attempt = 0
        while len(spots) < n and attempt < n * 22:
            attempt += 1
            angle = self.look.uniform(0.0, 6.28318)
            r = self.look.uniform(11.4, max(14.0, self.radius - 0.2))
            x, y = cos(angle) * r, sin(angle) * r
            gap = self._tree_gap(r)
            if self._in_clearing(x, y):
                continue
            if any(hypot(x - px, y - py) < gap for px, py, _r in spots):
                continue
            spots.append((x, y, r))
        for i, (x, y, radius) in enumerate(spots):
            ref = self._tree_for_ring(trees, radius, i)
            h = self._tree_height(ref, radius)
            if ref:
                assets.instance(ref, f"tree{i}", location=(x, y, 0.0),
                                rotation=(0.0, 0.0, self.look.uniform(0, 6.28)),
                                height=h, into="Level")
            else:
                prims.spawn(prims.CYLINDER, f"tree{i}",
                            location=(x, y, h * 0.5),
                            scale=(0.35, 0.35, h * 0.5),
                            material=materials.solid("rpg_bark",
                                                     (0.28, 0.18, 0.10),
                                                     roughness=0.9),
                            into="Level")
            # Dense photoreal canopy is visual only. Keep-out stays on the
            # fire, chest, fallen trunk, stump and rocks so the scripted
            # 4-kill route can still thread the glade.
            if h >= 8.0:
                self.obstacles.append((x, y, 0.16))

    def _scatter_landmarks(self) -> None:
        """A fallen trunk and stump on the far rim — no Kenney castle keep."""
        trunk = "/Library/models/polyhaven/dead_tree_trunk/dead_tree_trunk_1k.gltf"
        stump = "/Library/models/polyhaven/tree_stump_01/tree_stump_01_1k.gltf"
        x, y = -15.4, 15.8
        if assets.source(trunk) is not None and not self._in_clearing(x, y):
            assets.instance(trunk, "fallen_trunk", location=(x, y, 0.0),
                            rotation=(0.0, 0.0, radians(38.0)),
                            height=1.35, into="Level")
            self.obstacles.append((x, y, 1.15))
        sx, sy = 14.6, -13.2
        if assets.source(stump) is not None and not self._in_clearing(sx, sy):
            assets.instance(stump, "forest_stump", location=(sx, sy, 0.0),
                            rotation=(0.0, 0.0, radians(-22.0)),
                            height=0.85, into="Level")
            self.obstacles.append((sx, sy, 0.70))

    def _scatter_grass(self) -> None:
        grasses = self.models("grass")
        if not grasses:
            grasses = [
                "/Library/models/polyhaven/grass_medium_01/grass_medium_01_1k.gltf",
                "/Library/models/polyhaven/grass_medium_02/grass_medium_02_1k.gltf",
            ]
        target = int(self.spec.get("grass_count", 520))
        placed = 0
        attempt = 0
        outer = max(10.0, self.radius - 0.35)
        while placed < target and attempt < target * 8:
            attempt += 1
            angle = self.look.uniform(0.0, 6.28318)
            # Most clumps go past the hedge — that is the bare dirt the camera
            # sees through the first ring.
            if self.look.random() < 0.72:
                r = self.look.uniform(8.2, outer)
                h = self.look.uniform(0.42, 0.82)
            else:
                r = self.look.uniform(1.6, 8.2)
                h = self.look.uniform(0.28, 0.52)
            x, y = cos(angle) * r, sin(angle) * r
            if hypot(x, y) < 1.35:
                continue
            if hypot(x - CAMPFIRE[0], y - CAMPFIRE[1]) < 1.25:
                continue
            if hypot(x - SWORD_CHEST[0], y - SWORD_CHEST[1]) < 1.15:
                continue
            ref = grasses[placed % len(grasses)]
            if assets.source(ref) is None:
                continue
            assets.instance(ref, f"grass{placed}", location=(x, y, 0.0),
                            rotation=(0.0, 0.0, self.look.uniform(0, 6.28)),
                            height=h, into="Level")
            placed += 1

    def _scatter_undergrowth(self) -> None:
        plants = self.models("plant")
        if not plants:
            return
        spots = []
        for i in range(96):
            angle = 0.14 + i * 0.21
            r = 6.2 + (i % 11) * 1.55
            spots.append((cos(angle) * r, sin(angle) * r))
        for i, (x, y) in enumerate(spots):
            if hypot(x - CAMPFIRE[0], y - CAMPFIRE[1]) < 1.7:
                continue
            if hypot(x, y) < 4.6:
                continue
            if hypot(x - SWORD_CHEST[0], y - SWORD_CHEST[1]) < 2.2:
                continue
            ref = plants[i % len(plants)]
            low = ref.lower()
            if "shrub" in low:
                h = self.look.uniform(0.85, 1.45)
            elif "fern" in low:
                h = self.look.uniform(0.45, 0.75)
            elif "moss" in low:
                h = self.look.uniform(0.12, 0.22)
            else:
                h = self.look.uniform(0.40, 0.70)
            assets.instance(ref, f"plant{i}", location=(x, y, 0.0),
                            rotation=(0.0, 0.0, self.look.uniform(0, 6.28)),
                            height=h, into="Level")

    def _scatter_ruins(self) -> None:
        ruins = self.models("ruin")
        spots = [(-10.6, 12.2), (11.4, 10.6), (-12.0, -8.4), (10.8, -11.2)]
        for i, (x, y) in enumerate(spots):
            if self._occupied(x, y, 2.2):
                continue
            if ruins:
                ref = ruins[i % len(ruins)]
                low = ref.lower()
                if "stump" in low:
                    h = 0.82
                elif "boulder" in low:
                    h = 1.15
                elif "moss" in low or "stone" in low:
                    h = 0.42
                elif "trunk" in low or "log" in low:
                    h = 1.15
                elif "rock" in low:
                    h = 1.35
                else:
                    h = 1.2
                assets.instance(ref, f"ruin{i}", location=(x, y, 0.0),
                                rotation=(0.0, 0.0, self.look.uniform(0, 6.28)),
                                height=h, into="Level")
                self.obstacles.append((x, y, self._model_radius(
                    ref, h, 0.50, fallback=0.90)))
            else:
                prims.spawn(prims.BOX_GROUND, f"ruin{i}", location=(x, y, 0.0),
                            scale=(1.1, 0.8, 1.4),
                            material=materials.solid("rpg_ruin",
                                                     (0.42, 0.40, 0.36),
                                                     roughness=0.88),
                            into="Level")
                self.obstacles.append((x, y, 1.05))

    def _scatter_wisps(self) -> None:
        """Dim fireflies: warm near the fire, cool deeper in the trees."""
        warm = materials.glow("rpg_wisp_a", (1.0, 0.72, 0.28), strength=5.5)
        cool = materials.glow("rpg_wisp_b", (0.45, 0.75, 1.0), strength=4.0)
        for i in range(12):
            if i < 5:
                angle = 0.40 + i * 0.95
                r = 1.1 + (i % 3) * 0.45
                x = CAMPFIRE[0] + cos(angle) * r
                y = CAMPFIRE[1] + sin(angle) * r
                mat, z = warm, 0.55 + (i % 3) * 0.28
            else:
                angle = 0.55 + i * 0.62
                r = 6.8 + (i % 4) * 1.5
                x, y = cos(angle) * r, sin(angle) * r
                if hypot(x, y) < 5.5:
                    continue
                mat, z = cool, 0.90 + (i % 4) * 0.35
            prims.spawn(prims.SPHERE, f"wisp{i}", location=(x, y, z),
                        scale=(0.07, 0.07, 0.07), material=mat,
                        into="Level", shadow=False, collide=False)

    def _yaw_for(self, reference) -> float:
        low = (reference or "").lower()
        if "kaykit" in low:
            return KAYKIT_YAW
        if "mixamo" in low:
            return MIXAMO_YAW
        if "blocky" in low or "character-" in low:
            return DOLL_YAW
        if "meshy" in low or "black_eagle" in low or "celestial" in low:
            return 180.0
        return 180.0

    def _plant(self, clip) -> None:
        """Slide the unpacked root so the posed feet sit on z = 0."""
        if clip is None or clip.root is None:
            return
        clip.play("idle", 0.0)
        from mathutils import Vector  # noqa: PLC0415
        import bpy  # noqa: PLC0415
        bpy.context.view_layer.update()
        deps = bpy.context.evaluated_depsgraph_get()
        lows = []
        stack = [clip.root]
        while stack:
            obj = stack.pop()
            stack.extend(obj.children)
            if obj.type != "MESH" or getattr(obj, "hide_render", False):
                continue
            evaluated = obj.evaluated_get(deps)
            mesh = evaluated.to_mesh()
            world = evaluated.matrix_world
            step = max(1, len(mesh.vertices) // 24000)
            for index, vertex in enumerate(mesh.vertices):
                if index % step:
                    continue
                lows.append((world @ vertex.co).z)
            evaluated.to_mesh_clear()
        if not lows:
            return
        clip.root.location = (
            clip.root.location[0], clip.root.location[1],
            clip.root.location[2] - min(lows) + 0.01,
        )

    def _build_chests(self) -> None:
        wood = materials.solid("rpg_chest", (0.42, 0.26, 0.10), roughness=0.7)
        gold = materials.glow("rpg_gold", (1.0, 0.82, 0.25), strength=2.4)
        crates = self.models("chest")
        self.chests = []
        self.chest_sword = None
        placements = [SWORD_CHEST]
        for i in range(1, int(self.spec["chest_count"])):
            angle, r = 2.4 + i * 1.9, 8.5 + i * 2.2
            placements.append((cos(angle) * r, sin(angle) * r))
        for i, (x, y) in enumerate(placements):
            box = prims.spawn(prims.BOX_GROUND, f"chest{i}", location=(x, y, 0.0),
                              scale=(0.45, 0.32, 0.28), material=wood, into="Level")
            lid = None
            mesh = None
            if crates:
                packed = assets.unpack(self.look.choice(crates), f"chest{i}_m",
                                       location=(x, y, 0.0), height=0.56, into="Level")
                if packed is not None:
                    prims.veil(box)
                    lid = packed.parts.get("lid")
                    mesh = packed.root
                    if lid is not None:
                        self.recorder.track(lid, channels=("rotation_euler",))
                    self.recorder.track(mesh, channels=("location", "rotation_euler",
                                                        "hide_render"))
                else:
                    mesh = assets.instance(crates[0], f"chest{i}_m",
                                           location=(x, y, 0.0), fit=(0.9, 0.64, 0.56),
                                           into="Level")
                    prims.veil(box)
                    if mesh is not None:
                        self.recorder.track(mesh, channels=("location", "rotation_euler",
                                                            "hide_render"))
            glow = prims.spawn(prims.SPHERE, f"chest{i}_g", location=(x, y, 0.55),
                               scale=(0.12, 0.12, 0.12), material=gold,
                               into="Level", shadow=False)
            self.recorder.track(glow, channels=("location", "hide_render"))
            chest = {"glow": glow, "x": x, "y": y, "open": False,
                     "lid": lid, "mesh": mesh, "lid_left": 0, "holds_sword": False}
            self.chests.append(chest)
            # Tight enough that the AI can still step inside the 1.8 m interact
            # radius; a 0.58 m crate circle plus the body left them stranded.
            self.obstacles.append((x, y, 0.40))

    def _model_radius(self, reference, height: float, fraction: float,
                      fallback: float = 0.6) -> float:
        """Planar keep-out from a model's XY bounds after height-normalising."""
        if not reference:
            return fallback
        collection = assets.source(reference)
        if collection is None:
            return fallback
        sx, sy, sz = assets.size(collection)
        if sz < 1e-6:
            return fallback
        scale = height / sz
        return max(0.42, min(1.55, 0.5 * max(sx, sy) * scale * fraction))

    def _hang_character(self, reference, name, host, veil=(),
                        height: float = FIGURE_HEIGHT):
        if not reference:
            return None, None
        if self._skinned(reference):
            clip = clips.attach(reference, name, host=host, height=height,
                                veil=veil, yaw_offset=self._yaw_for(reference))
            if clip is not None:
                clip.track(self.recorder)
                self._plant(clip)
            return clip, None
        fig = figures.attach(reference, name, host=host, height=height,
                             veil=veil, yaw_offset=self._yaw_for(reference))
        if fig is not None:
            fig.track(self.recorder)
        return None, fig

    def _corrupt_doll(self, fig, index: int) -> None:
        """Turn a Kenney blocky into a big-headed possessed doll."""
        if fig.head is not None:
            sx, sy, sz = fig.head.scale
            fig.head.scale = (sx * DOLL_HEAD_SCALE, sy * DOLL_HEAD_SCALE,
                              sz * DOLL_HEAD_SCALE)
            rest, _ = fig._rest[fig.head]
            fig._rest[fig.head] = (rest, tuple(fig.head.scale))
        body = materials.solid(f"rpg_doll_body{index}", (0.10, 0.03, 0.05),
                               roughness=0.78)
        head = materials.solid(f"rpg_doll_head{index}", (0.28, 0.05, 0.06),
                               roughness=0.48,
                               emission=(1.0, 0.12, 0.04), emission_strength=0.55)
        limb = materials.solid(f"rpg_doll_limb{index}", (0.07, 0.02, 0.03),
                               roughness=0.82)
        stack = [fig.root]
        while stack:
            obj = stack.pop()
            stack.extend(obj.children)
            if obj.type != "MESH":
                continue
            blob = obj.name.lower()
            mat = head if "head" in blob else (body if "torso" in blob else limb)
            mesh = obj.data.copy()
            mesh.materials.clear()
            mesh.materials.append(mat)
            obj.data = mesh
        if fig.head is not None:
            glow = materials.glow(f"rpg_doll_eye{index}", (1.0, 0.18, 0.05),
                                  strength=9.0)
            for side, name in ((-1, "l"), (1, "r")):
                prims.spawn(prims.SPHERE, f"{fig.root.name}_eye_{name}",
                            location=(0.11 * side, -0.18, 0.10),
                            scale=(0.055, 0.055, 0.055), material=glow,
                            into="Actors", parent=fig.head, shadow=False,
                            collide=False)

    def _build_monsters(self) -> None:
        skin = materials.solid("rpg_monster", (0.45, 0.12, 0.10), roughness=0.6)
        self.monsters = []
        n = int(self.spec["monster_count"])
        for i in range(n):
            if i == 0:
                x, y = 0.85, 6.2
            else:
                angle, r = 1.4 + i * (6.28318 / max(n, 1)), 8.4 + (i % 2) * 1.5
                x, y = cos(angle) * r, sin(angle) * r
            actor = self.spawn_actor(f"monster{i}", None, position=(x, y, 0.0),
                                     yaw=degrees(atan2(-x, y)) % 360, team="enemy",
                                     hp=float(self.m["hp"]))
            body = prims.spawn(prims.CYLINDER, f"monster{i}_b",
                               location=(0.0, 0.0, 0.7), scale=(0.32, 0.32, 0.7),
                               material=skin, into="Actors", parent=actor.obj)
            head = prims.spawn(prims.SPHERE, f"monster{i}_h",
                               location=(0.0, 0.0, 1.5), scale=(0.28, 0.28, 0.28),
                               material=skin, into="Actors", parent=actor.obj)
            actor.state["walked"] = 0.0
            actor.state["fall"] = 0.0
            roster = self.models("monster") or ([self.pick("player")] if self.pick("player") else [])
            clip, fig = self._hang_character(
                roster[i % len(roster)] if roster else None,
                f"monster{i}_m", actor.obj, veil=(body, head),
                height=MONSTER_HEIGHT)
            if fig is not None:
                self._corrupt_doll(fig, i)
            actor.state["clip"], actor.state["figure"] = clip, fig
            self.monsters.append(actor)

    def _build_player(self) -> None:
        self.player = self.spawn_actor("player", None, position=(0.0, 0.0, 0.0),
                                       yaw=0.0, team="player")
        body = materials.solid("rpg_hero", (0.20, 0.35, 0.55), roughness=0.5)
        torso = prims.spawn(prims.CYLINDER, "hero_body", location=(0.0, 0.0, 0.9),
                            scale=(0.22, 0.22, 0.9), material=body,
                            into="Actors", parent=self.player.obj)
        prims.veil(torso)
        self.hero_clip, self.hero_figure = self._hang_character(
            self.pick("player"), "hero", self.player.obj)
        self._equip_starting_weapons()
        self.camera = camera_rigs.make_camera("rpg_cam", lens=32.0)
        self.rig = camera_rigs.ChaseRig(self.camera, distance=5.4, height=3.65,
                                        pitch=-18.0, stiffness=0.28)
        self.recorder.track(self.camera, channels=("location", "rotation_euler"))

    def _build_vfx(self) -> None:
        core = materials.glow("rpg_arrow_core", (0.75, 0.95, 1.0), strength=14.0)
        glow = materials.glow("rpg_arrow", (0.35, 0.75, 1.0), strength=7.0)
        bead = materials.glow("rpg_arrow_bead", (0.45, 0.85, 1.0), strength=5.5)
        burst = materials.glow("rpg_arrow_hit", (0.85, 0.95, 1.0), strength=8.0)
        slash = materials.glow("rpg_slash", (1.0, 0.85, 0.35), strength=4.0)
        self.arrow_pool = []
        self.trail_pool = []
        self.burst_pool = []
        for i in range(8):
            bolt = prims.spawn(prims.CYLINDER, f"arrow{i}", scale=(0.045, 0.045, 0.28),
                               material=core, into="VFX", shadow=False)
            halo = prims.spawn(prims.SPHERE, f"arrow{i}_halo", scale=(0.09, 0.09, 0.16),
                               material=glow, into="VFX", shadow=False)
            prims.show(bolt, False)
            prims.show(halo, False)
            self.recorder.track(bolt, channels=("location", "rotation_euler", "scale",
                                                "hide_render"))
            self.recorder.track(halo, channels=("location", "rotation_euler",
                                                "hide_render"))
            trail = []
            for k in range(TRAIL_BEADS):
                obj = prims.spawn(prims.SPHERE, f"arrow{i}_t{k}",
                                  scale=(0.05, 0.05, 0.05), material=bead,
                                  into="VFX", shadow=False)
                prims.show(obj, False)
                self.recorder.track(obj, channels=("location", "scale", "hide_render"))
                trail.append(obj)
            self.arrow_pool.append({"bolt": bolt, "halo": halo, "trail": trail})
            hit = prims.spawn(prims.SPHERE, f"arrow_hit{i}", scale=(0.16, 0.16, 0.16),
                              material=burst, into="VFX", shadow=False)
            prims.show(hit, False)
            self.recorder.track(hit, channels=("location", "hide_render"))
            self.burst_pool.append(hit)
        self.slash = prims.spawn(prims.BOX, "slash_arc", scale=(0.04, 0.7, 0.35),
                                 material=slash, into="VFX", shadow=False)
        prims.show(self.slash, False)
        self.recorder.track(self.slash, channels=("location", "rotation_euler", "hide_render"))
        self._burst_cursor = 0
        self._arrow_cursor = 0
        self._burst_until: dict = {}

    def _build_hud(self) -> None:
        self.hud = hud.Hud(self.camera, self.resolution)
        self.hp_bar = self.hud.bar("hp", (-0.92, 0.86), width=0.42, height=0.05,
                                   color=(0.25, 0.85, 0.40))
        self.chest_pips = self.hud.pip_row("chests", (0.42, 0.86),
                                           int(self.spec["chest_count"]),
                                           size=0.04, gap=0.07, color=(1.0, 0.82, 0.25))
        self.kill_pips = self.hud.pip_row("kills", (0.42, -0.86),
                                          int(self.spec["monster_count"]),
                                          size=0.035, gap=0.06, color=(1.0, 0.35, 0.30))
        self.hud.register(self.recorder)

    def tick(self) -> None:
        self.player_speed = 0.0
        self.attack_cd = max(0.0, self.attack_cd - self.dt)
        self.slash_left = max(0, self.slash_left - 1)
        releasing = self.draw_left == 1
        self.draw_left = max(0, self.draw_left - 1)
        self.switch_left = max(0, self.switch_left - 1)
        if releasing and self._pending_arrow:
            self._release_arrow()
            self._pending_arrow = False
        if self.slash_left == max(1, SLASH_TICKS // 2) and self.slash_hits:
            for monster in self.slash_hits:
                if monster.alive:
                    self._hurt(monster, float(self.p["melee_damage"]), "slash")
            self.slash_hits = []
        if self.slash_left == 0:
            prims.show(self.slash, False)
        if self.pickup_left > 0:
            self.pickup_left -= 1
        self._animate_chests()
        step = 1.0 / float(DAYNIGHT_BLEND_TICKS)
        if self._daynight_blend < self._daynight_target:
            self._daynight_blend = min(self._daynight_target,
                                       self._daynight_blend + step)
        elif self._daynight_blend > self._daynight_target:
            self._daynight_blend = max(self._daynight_target,
                                       self._daynight_blend - step)
        if not self.human and not self._auto_night and self.time >= 7.0:
            self._toggle_day_night()
            self._auto_night = True
        self._apply_day_night(self._daynight_blend)
        alive = [m for m in self.monsters if m.alive]
        if self.hp > 0.0:
            (self._player_input if self.human else self._player_policy)(alive)
        self._pose_hero()
        self._monsters_think()
        self._fly_arrows()
        self._drive_camera()
        self.hp_bar.set(self.hp / float(self.p["hp"]))
        self.chest_pips.set(self.chests_opened)
        self.kill_pips.set(self.kills)
        if (self.kills >= len(self.monsters) and self.chests_opened >= len(self.chests)
                and self.finished_at is None):
            self.log("forest_cleared", seconds=round(self.time, 2))
            self.finish("forest_cleared")
        if self.hp <= 0.0:
            self.finish("player_down")

    def _face(self, dx, dy, *, limit: float = 16.0) -> bool:
        """Turn toward a vector. True once the body is lined up enough to shoot."""
        dist = hypot(dx, dy)
        if dist < 1e-4:
            return True
        wanted = degrees(atan2(-dx, dy)) % 360.0
        err = (wanted - self.player.yaw + 180.0) % 360.0 - 180.0
        self.player.yaw = (self.player.yaw + max(-TURN_RATE, min(TURN_RATE, err))) % 360.0
        self.player.sync()
        return abs(err) < limit

    def _steer(self, dx, dy, *, arrive: bool = False) -> None:
        dist = hypot(dx, dy)
        if dist < 1e-4:
            return
        wanted = degrees(atan2(-dx, dy)) % 360.0
        err = (wanted - self.player.yaw + 180.0) % 360.0 - 180.0
        self.player.yaw = (self.player.yaw + max(-TURN_RATE, min(TURN_RATE, err))) % 360.0
        # Don't slide sideways: wait until the body roughly faces the path.
        if abs(err) > YAW_MOVE_LIMIT:
            self.player.sync()
            return
        speed = float(self.p["move_speed"])
        if arrive and dist < 2.4:
            speed *= max(0.28, dist / 2.4)
        step = speed * self.dt
        self._move(self.player, dx / dist * step, dy / dist * step)
        self.walked += step

    def _sidestep_to(self, x, y) -> None:
        """
        Walk toward a point while staying faced down +Y.

        The sword chest is off to the right; turning to face it puts the chase
        camera behind the back and hides the pickup. Holding yaw at 0 keeps the
        chest on the right of the frame.
        """
        dx, dy = x - self.player.x, y - self.player.y
        dist = hypot(dx, dy)
        err = (0.0 - self.player.yaw + 180.0) % 360.0 - 180.0
        self.player.yaw = (self.player.yaw + max(-TURN_RATE, min(TURN_RATE, err))) % 360.0
        if dist < 1e-4:
            self.player.sync()
            return
        speed = float(self.p["move_speed"]) * 0.85
        if dist < 1.8:
            speed *= max(0.30, dist / 1.8)
        step = speed * self.dt
        self._move(self.player, dx / dist * step, dy / dist * step)
        self.walked += step

    def _drive_camera(self) -> None:
        if self.chests_opened == 0 or self.pickup_left > 0:
            # From the west, looking +X, so the camera sits in the spawn
            # clearing instead of inside the trees east of the chest.
            # Yaw −90 → forward (+1, 0); the rig stands off −X of the target.
            self.rig.distance = 4.2
            self.rig.height = 2.50
            self.rig.pitch = -12.0
            self.rig.update((self.player.x, self.player.y, 0.0), -90.0)
            return
        self.rig.distance = 5.4
        self.rig.height = 3.65
        self.rig.pitch = -18.0
        self.rig.update(self.player.position, self.player.yaw, speed_ratio=0.0)

    def _push_out(self, x: float, y: float, radius: float, actor=None) -> tuple:
        """Keep a body out of trunks, rocks, chests and other characters."""
        for _ in range(4):
            for cx, cy, cr in self.obstacles:
                ddx, ddy = x - cx, y - cy
                d = hypot(ddx, ddy)
                keep = cr + radius + 0.22
                if d < 1e-6:
                    x = cx + keep
                elif d < keep:
                    x = cx + ddx / d * keep
                    y = cy + ddy / d * keep
            for other in getattr(self, "monsters", ()):
                if other is actor or not other.alive:
                    continue
                or_ = MONSTER_RADIUS
                ddx, ddy = x - other.x, y - other.y
                d = hypot(ddx, ddy)
                keep = radius + or_ + 0.16
                if d < 1e-6:
                    x = other.x + keep
                elif d < keep:
                    x = other.x + ddx / d * keep
                    y = other.y + ddy / d * keep
            if actor is not self.player:
                ddx, ddy = x - self.player.x, y - self.player.y
                d = hypot(ddx, ddy)
                keep = radius + PLAYER_RADIUS + 0.16
                if 1e-6 < d < keep:
                    x = self.player.x + ddx / d * keep
                    y = self.player.y + ddy / d * keep
        return x, y

    def _move(self, actor, dx, dy, *, radius: float = PLAYER_RADIUS) -> None:
        limit = self.radius - 1.2
        x = max(-limit, min(limit, actor.x + dx))
        y = max(-limit, min(limit, actor.y + dy))
        x, y = self._push_out(x, y, radius, actor)
        x = max(-limit, min(limit, x))
        y = max(-limit, min(limit, y))
        actor.x, actor.y = x, y
        actor.sync()
        if actor is self.player:
            self.player_speed = hypot(dx, dy) / max(self.dt, 1e-6)

    def _player_input(self, alive: list) -> None:
        c = self.controls
        self.player.yaw = (self.player.yaw + c.yaw_delta) % 360.0
        mx, my = c.move_x, c.move_y
        mag = hypot(mx, my)
        if mag > 1.0:
            mx, my = mx / mag, my / mag
        speed = float(self.p["move_speed"]) * (RUN_MULTIPLIER if c.run else 1.0)
        f, r = camera_rigs.forward(self.player.yaw), camera_rigs.right(self.player.yaw)
        dx = (f[0] * my + r[0] * mx) * speed * self.dt
        dy = (f[1] * my + r[1] * mx) * speed * self.dt
        self._move(self.player, dx, dy)
        self.walked += hypot(dx, dy)
        if c.pressed("interact"):
            self._try_chest()
        if c.pressed("time_toggle"):
            self._toggle_day_night()
        if c.pressed("weapon_next") and self.has_sword:
            self._cycle_weapon()
        if c.pressed("fire") and self.attack_cd <= 0.0 and self.has_sword:
            if self.weapon == "bow":
                self._shoot_arrow()
            else:
                self._slash(alive)
        elif c.pressed("alt_fire") and self.attack_cd <= 0.0 and self.has_sword:
            if self.weapon != "bow":
                self._cycle_weapon()
                return
            self._shoot_arrow()

    def _player_policy(self, alive: list) -> None:
        if (self.pickup_left > 0 or self.slash_left > 0
                or self.switch_left > 0 or self.draw_left > 0):
            return
        closed = [c for c in self.chests if not c["open"]]
        if closed and self.chests_opened == 0:
            chest = closed[0]
            if hypot(chest["x"] - self.player.x, chest["y"] - self.player.y) > 1.15:
                self._sidestep_to(chest["x"], chest["y"])
            else:
                self._try_chest()
            return
        if alive:
            t = min(alive, key=lambda m: m.planar_distance_to(self.player))
            dx, dy = t.x - self.player.x, t.y - self.player.y
            dist = hypot(dx, dy)
            if dist > ARROW_RANGE:
                self._steer(dx, dy, arrive=True)
            elif dist > SLASH_RANGE * 0.88:
                shots = self._volleys.get(t.name, 0)
                if shots < 1:
                    if self.weapon != "bow":
                        self._cycle_weapon()
                        return
                    if self.attack_cd <= 0.0 and self._face(dx, dy, limit=BOW_FACE_LIMIT):
                        self._shoot_arrow()
                        self._volleys[t.name] = shots + 1
                else:
                    if self.weapon != "sword":
                        self._cycle_weapon()
                        return
                    self._steer(dx, dy, arrive=True)
            elif self.attack_cd <= 0.0:
                if self.weapon != "sword":
                    self._cycle_weapon()
                    return
                self._face(dx, dy)
                self._slash(alive)
            return
        closed = [c for c in self.chests if not c["open"]]
        if closed:
            c = min(closed, key=lambda k: hypot(k["x"] - self.player.x,
                                                k["y"] - self.player.y))
            dx, dy = c["x"] - self.player.x, c["y"] - self.player.y
            if hypot(dx, dy) > 1.2:
                self._steer(dx, dy, arrive=True)
            else:
                self._try_chest()

    def _try_chest(self) -> None:
        for chest in self.chests:
            if chest["open"]:
                continue
            if hypot(chest["x"] - self.player.x, chest["y"] - self.player.y) < 1.8:
                chest["open"] = True
                chest["lid_left"] = LID_TICKS
                self.chests_opened += 1
                prims.show(chest["glow"], False)
                self.log("chest_opened", index=self.chests_opened,
                         sword=False)
                self.pickup_left = PICKUP_TICKS
                return

    def _animate_chests(self) -> None:
        for chest in self.chests:
            if chest.get("lid_left", 0) <= 0:
                continue
            total = LID_TICKS
            t = 1.0 - (chest["lid_left"] - 1) / max(total, 1)
            chest["lid_left"] -= 1
            lid = chest.get("lid")
            mesh = chest.get("mesh")
            if lid is not None:
                lid.rotation_euler = (radians(-118.0) * t, 0.0, 0.0)
            elif mesh is not None:
                # One-piece crates tip the lid open in place rather than sinking.
                mesh.rotation_euler = (radians(-52.0) * t, 0.0, 0.0)

    def _grip_on_clip(self, clip, reference, name, bone_names, *,
                     location=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0),
                     height=None, length=None):
        """Parent a prop to a pose bone so authored clips carry it."""
        if clip is None or reference is None:
            return None
        bone = clip._bone(*bone_names)
        if bone is None or clip.armature is None:
            return None
        made = assets.instance(reference, name, parent=clip.armature,
                               location=location, rotation=rotation,
                               height=height, length=length,
                               into="Actors", anchor="origin")
        if made is None:
            return None
        made.parent_type = "BONE"
        made.parent_bone = bone.name
        made.matrix_parent_inverse.identity()
        made.location = location
        made.rotation_euler = rotation
        return made

    def _equip_starting_weapons(self) -> None:
        """The knight mesh already carries its blade; only the bow is a prop."""
        self.has_sword = True
        self.weapon = "sword"
        self._equip_bow()
        self._apply_weapon_visibility()

    def _equip_sword(self) -> None:
        if self.has_sword or not self.sword_ref:
            return
        if self.chest_sword is not None:
            prims.show(self.chest_sword, False)
        if self.hero_figure is not None:
            self.held_sword = self.hero_figure.hold(
                1, self.sword_ref, "hero_sword", height=SWORD_HEIGHT, grip=0.62)
        if self.held_sword is None:
            self.held_sword = self._grip_on_clip(
                self.hero_clip, self.sword_ref, "hero_sword",
                ("handslot.r", "wrist.r", "mixamorig:RightHand", "RightHand"),
                location=(0.0, 0.10, 0.0),
                rotation=(radians(90.0), 0.0, 0.0), height=SWORD_HEIGHT)
        if self.held_sword is None:
            self.held_sword = assets.instance(
                self.sword_ref, "hero_sword", parent=self.player.obj,
                location=(0.22, 0.16, 1.05), height=SWORD_HEIGHT,
                rotation=(radians(12.0), 0.0, radians(15.0)),
                into="Actors", anchor="origin")
        if self.held_sword is not None:
            self.recorder.track(self.held_sword,
                                channels=("location", "rotation_euler", "hide_render"))
        self.has_sword = True
        self.weapon = "sword"
        self._equip_bow()
        self._apply_weapon_visibility()
        self.log("sword_taken")

    def _equip_bow(self) -> None:
        if self.held_bow is not None:
            return
        bow_ref = self.pick("bow")
        # Hold the bow in front of the torso (actor +Y is forward). Bone-parenting
        # a procedural prop kept a stale parent-inverse and drove it through the
        # chest; a fixed forward offset stays outside the mesh.
        rest = (-0.58, 0.38, 1.36)
        rot = (0.0, 0.0, 0.0)
        if bow_ref and self.hero_figure is not None:
            self.held_bow = self.hero_figure.hold(
                -1, bow_ref, "hero_bow", length=0.95, grip=0.88)
        if self.held_bow is None and bow_ref:
            self.held_bow = assets.instance(
                bow_ref, "hero_bow", parent=self.player.obj,
                location=rest, length=0.95, rotation=rot,
                into="Actors", anchor="origin")
        if self.held_bow is None:
            self.held_bow = self._make_bow("hero_bow", self.player.obj)
            self.held_bow.location = rest
            self.held_bow.rotation_euler = rot
        if self.held_bow is not None:
            self.recorder.track(self.held_bow,
                                channels=("location", "rotation_euler", "hide_render"))
            for child in getattr(self.held_bow, "children", ()):
                self.recorder.track(child, channels=("hide_render",))

    def _make_bow(self, name: str, parent):
        """A small D-shaped bow when the library has no bow GLB."""
        wood = materials.solid("rpg_bow_wood", (0.32, 0.16, 0.07), roughness=0.72)
        cord = materials.solid("rpg_bow_string", (0.82, 0.78, 0.70), roughness=0.45)
        root = prims.empty(name, parent=parent, location=(-0.58, 0.38, 1.36),
                           into="Actors", display=0.02)
        prims.spawn(prims.CYLINDER, f"{name}_grip", location=(0.0, 0.0, 0.0),
                    scale=(0.020, 0.020, 0.09), material=wood,
                    into="Actors", parent=root, collide=False)
        prims.spawn(prims.CYLINDER, f"{name}_upper", location=(0.0, -0.04, 0.24),
                    rotation=(radians(16.0), 0.0, 0.0),
                    scale=(0.015, 0.015, 0.26), material=wood,
                    into="Actors", parent=root, collide=False)
        prims.spawn(prims.CYLINDER, f"{name}_lower", location=(0.0, -0.04, -0.24),
                    rotation=(radians(-16.0), 0.0, 0.0),
                    scale=(0.015, 0.015, 0.26), material=wood,
                    into="Actors", parent=root, collide=False)
        prims.spawn(prims.CYLINDER, f"{name}_string", location=(0.0, 0.12, 0.0),
                    scale=(0.005, 0.005, 0.44), material=cord,
                    into="Actors", parent=root, collide=False, shadow=False)
        return root

    def _cycle_weapon(self) -> None:
        if not self.has_sword or self.switch_left > 0:
            return
        self.weapon = "bow" if self.weapon == "sword" else "sword"
        self.switch_left = SWITCH_TICKS
        self._apply_weapon_visibility()
        self.log("weapon_switch", weapon=self.weapon)

    def _apply_weapon_visibility(self) -> None:
        self._show_tree(self.held_sword, self.weapon == "sword")
        self._show_tree(self.held_bow, self.weapon == "bow")

    def _show_tree(self, obj, on: bool) -> None:
        if obj is None:
            return
        prims.show(obj, on)
        for child in getattr(obj, "children", ()):
            self._show_tree(child, on)

    def _slash(self, alive: list) -> None:
        if not self.has_sword or self.weapon != "sword":
            return
        self.attack_cd = float(self.p["attack_interval"])
        self.slash_left = SLASH_TICKS
        f = camera_rigs.forward(self.player.yaw)
        self.slash.location = (self.player.x + f[0] * 1.1,
                               self.player.y + f[1] * 1.1, 1.15)
        self.slash.rotation_euler = (0.0, 0.0, radians(self.player.yaw))
        prims.show(self.slash, True)
        self.log("slash")
        self.slash_hits = [m for m in alive
                           if m.planar_distance_to(self.player) <= SLASH_RANGE]

    def _shoot_arrow(self) -> None:
        if not self.has_sword or self.weapon != "bow" or self._pending_arrow:
            return
        self.attack_cd = float(self.p["attack_interval"]) * 1.15
        self.draw_left = DRAW_TICKS
        self._pending_arrow = True
        self._arrow_target = self._aimed_monster()

    def _aimed_monster(self):
        f = camera_rigs.forward(self.player.yaw)
        best, best_d = None, 1e9
        for monster in self.monsters:
            if not monster.alive:
                continue
            dx, dy = monster.x - self.player.x, monster.y - self.player.y
            dist = hypot(dx, dy)
            if dist < 0.5 or dist > ARROW_RANGE + 2.4:
                continue
            if (dx * f[0] + dy * f[1]) / dist < 0.35:
                continue
            if dist < best_d:
                best, best_d = monster, dist
        return best

    def _arrow_aim(self) -> tuple:
        """Unit XY toward the nocked target, else along the knight's facing."""
        f = camera_rigs.forward(self.player.yaw)
        target = self._arrow_target
        if target is None or not target.alive:
            target = self._aimed_monster()
        if target is None:
            return f
        dx, dy = target.x - self.player.x, target.y - self.player.y
        dist = hypot(dx, dy)
        if dist < 1e-4:
            return f
        return (dx / dist, dy / dist)

    def _bow_nock(self) -> tuple:
        """World point in front of the chest — never from a stale bow matrix."""
        f = camera_rigs.forward(self.player.yaw)
        r = camera_rigs.right(self.player.yaw)
        return (self.player.x + f[0] * 0.62 + r[0] * (-0.10),
                self.player.y + f[1] * 0.62 + r[1] * (-0.10),
                1.32)

    def _release_arrow(self) -> None:
        aim = self._arrow_aim()
        origin = self._bow_nock()
        pack = self.arrow_pool[self._arrow_cursor % len(self.arrow_pool)]
        self._arrow_cursor += 1
        pack["bolt"].location = origin
        pack["halo"].location = origin
        prims.show(pack["bolt"], True)
        prims.show(pack["halo"], True)
        for bead in pack["trail"]:
            prims.show(bead, False)
        self.arrows.append({
            "pack": pack, "x": origin[0], "y": origin[1], "z": origin[2],
            "dx": aim[0] * ARROW_SPEED, "dy": aim[1] * ARROW_SPEED,
            "life": 1.5, "path": [origin],
        })
        self.log("arrow_shot")

    def _hide_arrow(self, pack) -> None:
        prims.show(pack["bolt"], False)
        prims.show(pack["halo"], False)
        for bead in pack["trail"]:
            prims.show(bead, False)

    def _burst(self, location) -> None:
        obj = self.burst_pool[self._burst_cursor % len(self.burst_pool)]
        self._burst_cursor += 1
        obj.location = tuple(location)
        prims.show(obj, True)
        self._burst_until[obj] = self.frame + 5

    def _fly_arrows(self) -> None:
        live = []
        for arrow in self.arrows:
            arrow["life"] -= self.dt
            arrow["x"] += arrow["dx"] * self.dt
            arrow["y"] += arrow["dy"] * self.dt
            pos = (arrow["x"], arrow["y"], arrow["z"])
            pack = arrow["pack"]
            prev = arrow["path"][-1]
            prims.stretch_between(pack["bolt"], prev, pos, radius=0.042)
            pack["halo"].location = pos
            arrow["path"].append(pos)
            if len(arrow["path"]) > TRAIL_BEADS + 1:
                arrow["path"] = arrow["path"][-(TRAIL_BEADS + 1):]
            for k, bead in enumerate(pack["trail"]):
                idx = len(arrow["path"]) - 2 - k
                if idx < 0:
                    prims.show(bead, False)
                    continue
                bead.location = arrow["path"][idx]
                fade = 1.0 - k / max(TRAIL_BEADS, 1)
                bead.scale = (0.055 * fade, 0.055 * fade, 0.055 * fade)
                prims.show(bead, True)
            hit = False
            for monster in self.monsters:
                if monster.alive and hypot(monster.x - arrow["x"],
                                           monster.y - arrow["y"]) < ARROW_HIT:
                    self._hurt(monster, float(self.p["arrow_damage"]), "arrow")
                    self._burst(pos)
                    hit = True
                    break
            if hit or arrow["life"] <= 0.0:
                self._hide_arrow(pack)
            else:
                live.append(arrow)
        self.arrows = live
        for obj in self.burst_pool:
            if self.frame >= self._burst_until.get(obj, 0):
                prims.show(obj, False)

    def _hurt(self, monster, damage: float, kind: str) -> None:
        monster.state["hp"] = monster.state.get("hp", float(self.m["hp"])) - damage
        self.damage_dealt += damage
        self.log("monster_hit", monster=monster.name, attack=kind,
                 hp_left=round(monster.state["hp"], 1))
        if monster.state["hp"] <= 0.0:
            monster.alive = False
            monster.state["fall"] = 0.0
            dx, dy = monster.x - self.player.x, monster.y - self.player.y
            dist = hypot(dx, dy) or 1.0
            monster.state["corpse_away"] = (dx / dist * CORPSE_SLIDE,
                                            dy / dist * CORPSE_SLIDE)
            self.kills += 1
            self.log("monster_killed", monster=monster.name)

    def _monsters_think(self) -> None:
        for monster in self.monsters:
            clip, fig = monster.state.get("clip"), monster.state.get("figure")
            if not monster.alive:
                fallen = min(1.0, monster.state.get("fall", 0.0) + self.dt * 1.35)
                monster.state["fall"] = fallen
                away = monster.state.get("corpse_away", (0.0, 0.0))
                # Start already offset so the first death frame is not inside
                # the hero, then ease the rest of the slide during the crumple.
                t = min(1.0, fallen / 0.32)
                ease = 0.50 + 0.50 * (1.0 - (1.0 - t) ** 2)
                vx = monster.x + away[0] * ease
                vy = monster.y + away[1] * ease
                if clip is not None:
                    clip.face(0.0)
                    if clip.has("death"):
                        # Authored death already puts the body on the floor.
                        # Tumbling the actor root on top of it is what planted
                        # Mixamo soldiers through the ground.
                        monster.obj.location = (vx, vy, monster.z)
                        monster.obj.rotation_euler = (0.0, 0.0,
                                                      radians(monster.yaw))
                        clip.play("death", fallen * 1.15, loop=False)
                    else:
                        monster.obj.rotation_euler = (radians(62.0 * fallen), 0.0,
                                                      radians(monster.yaw))
                        monster.obj.location = (vx, vy, 0.02 + 0.10 * fallen)
                        clip.play("idle", 0.0)
                        clip.overlay_knockdown(fallen)
                else:
                    monster.obj.rotation_euler = (radians(62.0 * fallen), 0.0,
                                                  radians(monster.yaw))
                    monster.obj.location = (vx, vy, 0.10 * fallen)
                continue
            dx, dy = self.player.x - monster.x, self.player.y - monster.y
            dist = hypot(dx, dy)
            monster.yaw = degrees(atan2(-dx, dy)) % 360.0
            hunting = self.has_sword
            if hunting and 1.3 < dist < float(self.m["engage"]):
                step = float(self.m["move_speed"]) * self.dt
                self._move(monster, dx / dist * step, dy / dist * step,
                           radius=MONSTER_RADIUS)
                monster.state["walked"] += step
            else:
                monster.sync()
            if hunting and dist < 1.45 and self.hp > 0.0 and self.rng.random() < 0.04:
                self.hp = max(0.0, self.hp - float(self.m["damage"]))
                self.log("player_hit", by=monster.name, hp_left=round(self.hp, 1))
            if clip is not None:
                clip.face(0.0)
                striking = hunting and dist < 1.45
                moving = hunting and dist > 1.3 and not striking
                if striking and clip.has("slash"):
                    clip.play("slash", (self.time * 1.15) % 1.2, loop=False)
                else:
                    clip.locomote(monster.state["walked"],
                                  speed=float(self.m["move_speed"]) if moving else 0.0,
                                  clock=self.time)
                    if striking:
                        clip.overlay_slash((self.time * 1.8) % 1.0)
            elif fig is not None:
                fig.rest()
                fig.face(0.0)
                if hunting and dist < 1.45:
                    fig.slash(1, (self.time * 1.6) % 1.0)
                elif hunting:
                    fig.walk(monster.state["walked"])

    def _pose_hero(self) -> None:
        if self.hero_clip is not None:
            self.hero_clip.face(0.0)
            if self.slash_left > 0:
                phase = 1.0 - self.slash_left / float(SLASH_TICKS)
                if self.hero_clip.play("slash", phase, loop=False):
                    pass
                else:
                    self.hero_clip.play("idle", self.time)
                    self.hero_clip.overlay_slash(phase)
            elif self.switch_left > 0:
                phase = 1.0 - self.switch_left / float(SWITCH_TICKS)
                self.hero_clip.play("idle", self.time)
                self.hero_clip.overlay_switch(phase)
            elif self.draw_left > 0:
                amount = 1.0 - self.draw_left / float(DRAW_TICKS)
                if self.hero_clip.has("aim"):
                    self.hero_clip.play("aim", min(0.90, amount), loop=False)
                elif self.hero_clip.has("shoot"):
                    self.hero_clip.play("shoot", min(0.55, amount * 0.65), loop=False)
                else:
                    self.hero_clip.play("idle", self.time)
                    self.hero_clip.overlay_draw(min(1.0, amount * 1.35))
            elif self.pickup_left > 0:
                phase = 1.0 - self.pickup_left / float(PICKUP_TICKS)
                if self.hero_clip.has("pickup"):
                    self.hero_clip.play("pickup", phase, loop=False)
                else:
                    self.hero_clip.play("idle", self.time)
                    self.hero_clip.overlay_switch(phase)
            else:
                self.hero_clip.locomote(self.walked, speed=self.player_speed,
                                        clock=self.time)
                if self.weapon == "bow":
                    self.hero_clip.overlay_draw(0.70)
        elif self.hero_figure is not None:
            self.hero_figure.rest()
            self.hero_figure.face(0.0)
            if self.slash_left > 0:
                phase = 1.0 - self.slash_left / float(SLASH_TICKS)
                self.hero_figure.slash(1, phase)
            elif self.draw_left > 0:
                self.hero_figure.aim(0.9)
            elif self.pickup_left > 0:
                self.hero_figure.pickup(1)
            else:
                self.hero_figure.walk(self.walked)
                if self.has_sword and self.weapon == "sword":
                    self.hero_figure.carry(1)
        self._pose_held_sword()
        self._pose_held_bow()

    def _pose_held_sword(self) -> None:
        """Swing a root-parented Meshy sword when there is no hand to hang it on."""
        if self.held_sword is None:
            return
        if getattr(self.held_sword, "parent_type", "") == "BONE":
            return
        if self.hero_figure is not None and self.hero_figure.arm_right is not None:
            return
        if self.weapon != "sword":
            return
        if self.slash_left > 0:
            phase = 1.0 - self.slash_left / float(SLASH_TICKS)
            p = max(0.0, min(1.0, phase))
            if p < 0.22:
                u = p / 0.22
                lift, sweep = 0.15 + 0.55 * u, -0.35 * u
            elif p < 0.72:
                u = (p - 0.22) / 0.50
                s = u * u * (3.0 - 2.0 * u)
                lift, sweep = 0.70 - 0.25 * s, -0.35 + 1.55 * s
            else:
                u = (p - 0.72) / 0.28
                lift, sweep = 0.45 * (1.0 - u), 1.20 * (1.0 - u)
            self.held_sword.location = (0.28 + 0.35 * sweep, 0.22 + 0.55 * lift, 1.15)
            self.held_sword.rotation_euler = (
                radians(-20.0 + 110.0 * sweep), radians(8.0), radians(25.0 - 70.0 * sweep))
        else:
            self.held_sword.location = (0.22, 0.16, 1.05)
            self.held_sword.rotation_euler = (radians(12.0), 0.0, radians(15.0))

    def _pose_held_bow(self) -> None:
        if self.held_bow is None:
            return
        if getattr(self.held_bow, "parent_type", "") == "BONE":
            return
        if self.hero_figure is not None and self.hero_figure.arm_left is not None:
            return
        if self.weapon != "bow":
            return
        if self.draw_left > 0:
            self.held_bow.location = (-0.48, 0.52, 1.38)
            self.held_bow.rotation_euler = (0.0, 0.0, 0.0)
        else:
            self.held_bow.location = (-0.58, 0.38, 1.36)
            self.held_bow.rotation_euler = (0.0, 0.0, 0.0)

    def summary(self) -> dict:
        return {
            "chests_opened": self.chests_opened, "chests_total": len(self.chests),
            "kills": self.kills, "monsters": len(self.monsters),
            "player_hp": round(self.hp, 1), "damage_dealt": round(self.damage_dealt, 1),
            "arrows_shot": self.count_events("arrow_shot"),
            "slashes": self.count_events("slash"),
            "sword_taken": self.count_events("sword_taken"),
            "weapon_switches": self.count_events("weapon_switch"),
            "cleared": self.kills >= len(self.monsters)
            and self.chests_opened >= len(self.chests),
        }

    def verdict(self, summary: dict) -> tuple:
        problems = []
        if summary["slashes"] + summary["arrows_shot"] == 0:
            problems.append("player never attacked")
        if summary["kills"] == 0:
            problems.append("no monster died")
        if summary.get("weapon_switches", 0) == 0:
            problems.append("never switched weapons")
        return (not problems, problems)


if __name__ == "__main__":
    kernel.main(ForestExplorer)
