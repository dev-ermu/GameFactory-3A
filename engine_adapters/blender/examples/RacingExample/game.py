"""
Third-person circuit racer — generated mechanic, Blender runtime.

Rules implemented
-----------------
A closed circuit generated from a periodic radius function, driven by a
kinematic bicycle model with throttle, brake, steering and grip; sequential
checkpoints that must be taken in order, so cutting the course does not score a
lap; per-lap timing; an off-track state that costs grip and is recorded; rival
cars racing the same line with their own pace; and overtake detection from
signed race progress.

Why a bicycle model
-------------------
Steering a car by rotating it and translating along its facing looks correct
standing still and wrong the moment it moves: the car pivots on the spot and
never slides. The bicycle model gives a yaw *rate* proportional to speed and
steering angle, so slow corners need more lock than fast ones, and separating
the velocity direction from the heading gives understeer and drift for free.
Both are what a chase camera actually films.

Progress, laps and overtakes all come off one number — arc length along the
centreline — which is what makes "who is ahead" answerable at all on a loop.
"""

import os
import sys
from math import atan2, cos, degrees, pi, radians, sin, tan
from pathlib import Path
from typing import Optional


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
    assets, camera_rigs, hud, kernel, materials, prims,
)

#: Full steering lock, in radians of front-wheel angle. Also the clamp inside
#: `Car.drive`, so a human holding a direction cannot ask for more lock than the
#: rivals' pursuit controller can.
MAX_STEER_LOCK = 0.62

#: Bumper to bumper, in metres — the size of the car built from primitives. A
#: model named by the task is normalised to this, so an asset authored at any
#: scale sits on the same grid slots and reads the same against the track width.
CAR_LENGTH = 4.3


def _rolling_radius(wheel, scale: float) -> float:
    """
    A wheel's radius in world metres, measured off its own mesh.

    Taken from the asset instead of assumed, because it sets how fast the wheel
    turns: guess it small and the wheels blur, guess it large and the car looks
    like it is sliding on ice. The mesh is measured in its local frame and scaled
    by what the model was normalised by, since the wheel's own transform is the
    steering and spin this then feeds.
    """
    heights = [corner[2] for corner in wheel.bound_box]
    return max(1e-3, (max(heights) - min(heights)) * scale * 0.5)


class Circuit:
    """
    The centreline, sampled once and then only ever queried.

    A racing line is needed several times per tick per car — to steer at, to
    measure lap progress with, and to decide whether a car is on the road — so
    it is a polyline with cumulative arc length rather than a curve to evaluate.
    Nearest-point search starts from each car's previous index, because a car
    moves a metre or two per tick and a global search over 200 points per car
    per tick is the whole simulation budget.
    """

    def __init__(self, samples: int, radius: float, wobble: float, lobes: int,
                 width: float):
        self.n = samples
        self.width = width
        self.points: list[tuple] = []
        for i in range(samples):
            a = 2.0 * pi * i / samples
            r = radius * (1.0 + wobble * sin(lobes * a) + wobble * 0.45 * cos(2 * a))
            self.points.append((cos(a) * r, sin(a) * r))

        self.seg_len: list[float] = []
        self.cum: list[float] = [0.0]
        for i in range(samples):
            x0, y0 = self.points[i]
            x1, y1 = self.points[(i + 1) % samples]
            d = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
            self.seg_len.append(d)
            self.cum.append(self.cum[-1] + d)
        self.length = self.cum[-1]

    def tangent_yaw(self, i: int) -> float:
        x0, y0 = self.points[i % self.n]
        x1, y1 = self.points[(i + 1) % self.n]
        return degrees(atan2(-(x1 - x0), (y1 - y0))) % 360.0

    def normal(self, i: int) -> tuple:
        return camera_rigs.right(self.tangent_yaw(i))

    def point_at(self, i: int, offset: float = 0.0) -> tuple:
        x, y = self.points[i % self.n]
        nx, ny = self.normal(i)[:2]
        return (x + nx * offset, y + ny * offset)

    def nearest(self, x: float, y: float, hint: int = 0, window: int = 14) -> tuple:
        """Return `(index, distance)` of the closest sample, searching near `hint`."""
        best_i, best_d = hint % self.n, 1e18
        for k in range(-window, window + 1):
            i = (hint + k) % self.n
            px, py = self.points[i]
            d = (px - x) ** 2 + (py - y) ** 2
            if d < best_d:
                best_d, best_i = d, i
        return best_i, best_d ** 0.5


class Car:
    """A kinematic bicycle with a body made of primitives."""

    def __init__(self, game, name: str, color, *, index: int, offset: float,
                 top_speed: float, accel: float, grip: float, is_player: bool):
        self.game = game
        self.name = name
        self.is_player = is_player
        self.top_speed = top_speed
        self.accel = accel
        self.grip = grip
        self.offset = offset          # preferred lateral line, metres
        self.speed = 12.0
        self.steer = 0.0
        self.yaw = 0.0
        self.x = self.y = 0.0
        self.node = 0                 # nearest centreline index
        self.progress = 0.0           # unwrapped arc length, metres
        self.lap = 0
        self.lap_started = 0.0
        self.lap_times: list[float] = []
        self.off_track_ticks = 0
        self.spin = 0.0               # wheel angle, radians, unwrapped
        self.model_wheels: list = []   # (object, does it steer) when a model is on
        self.wheel_radius = 0.3
        self.next_checkpoint = 0
        self.checkpoints_taken = 0
        self.lap_start_progress = 0.0
        self.cp_at_lap_start = 0

        body_mat = materials.solid(f"car_{name}_body", color, roughness=0.32,
                                   metallic=0.55)
        glass = materials.solid(f"car_{name}_glass", (0.05, 0.07, 0.10),
                                roughness=0.12, metallic=0.2)
        tyre = materials.solid("car_tyre", (0.035, 0.035, 0.04), roughness=0.95)
        lamp = materials.glow(f"car_{name}_lamp", (1.0, 0.93, 0.75), strength=2.6)
        brake = materials.glow(f"car_{name}_brake", (1.0, 0.12, 0.08), strength=2.2)

        self.root = prims.empty(f"car_{name}", into="Actors")
        body = [
            prims.spawn(prims.BOX, f"car_{name}_chassis", location=(0.0, 0.0, 0.46),
                        scale=(0.86, 2.15, 0.24), material=body_mat,
                        into="Actors", parent=self.root),
            prims.spawn(prims.BOX, f"car_{name}_cabin", location=(0.0, -0.25, 0.83),
                        scale=(0.70, 0.95, 0.22), material=glass,
                        into="Actors", parent=self.root),
            prims.spawn(prims.BOX, f"car_{name}_wing", location=(0.0, -2.02, 0.92),
                        scale=(0.85, 0.10, 0.05), material=body_mat,
                        into="Actors", parent=self.root),
        ]
        for sx in (-1, 1):
            body.append(prims.spawn(
                prims.BOX, f"car_{name}_lamp{sx}",
                location=(0.52 * sx, 2.12, 0.52), scale=(0.20, 0.05, 0.09),
                material=lamp, into="Actors", parent=self.root,
                shadow=False, collide=False))
            body.append(prims.spawn(
                prims.BOX, f"car_{name}_brake{sx}",
                location=(0.55 * sx, -2.12, 0.60), scale=(0.18, 0.05, 0.08),
                material=brake, into="Actors", parent=self.root,
                shadow=False, collide=False))
        # The unit cylinder runs along +Z, so a wheel is that axis laid onto X by
        # a 90 degree Y rotation. Steering is then the Z term, which in Blender's
        # default XYZ order is applied last and is therefore a world-Z turn —
        # exactly what a steered wheel does. (Rolling would have to be a local-Z
        # rotation applied *first*, which that order cannot express; it is left
        # out rather than faked, since an untextured tyre shows no roll anyway.)
        self.wheels = []
        for i, (wx, wy) in enumerate([(-0.92, 1.42), (0.92, 1.42),
                                      (-0.92, -1.42), (0.92, -1.42)]):
            wheel = prims.spawn(
                prims.CYLINDER, f"car_{name}_wheel{i}", location=(wx, wy, 0.38),
                rotation=(0.0, radians(90.0), 0.0), scale=(0.38, 0.38, 0.16),
                material=tyre, into="Actors", parent=self.root)
            self.wheels.append(wheel)
        self.front_wheels = self.wheels[:2]

        # A model, when the task named one, replaces the blocks rather than
        # joining them: it is hung off the same root the rules already move, so
        # nothing about the simulation changes.
        self.visual = self._attach_model(game.spec, name, body + self.wheels)

        game.recorder.track(self.root, channels=("location", "rotation_euler"))
        for wheel, _ in self.model_wheels:
            game.recorder.track(wheel, channels=("rotation_euler",))
        if self.visual is None:
            for wheel in self.front_wheels:
                game.recorder.track(wheel, channels=("rotation_euler",))

    def _attach_model(self, spec: dict, name: str, parts: list):
        """
        Hang the car model this task asked for, and hide the blocks it replaces.

        `models.<car name>` wins over `models.car`, so one task can give the
        player a different chassis from the field without naming every rival.

        Unpacked rather than instanced because the wheels have to turn, and a
        collection instance has no parts to turn. The half turn is not a taste
        call: glTF is authored -Z forward and the importer maps that onto -Y,
        while every rule here drives along +Y, so without it the whole field
        races backwards — which is what these cars were doing.
        """
        models = spec.get("models") or {}
        reference = models.get(name) or models.get("car")
        if not reference:
            return None
        model = assets.unpack(reference, f"car_{name}_visual", parent=self.root,
                              rotation=(0.0, 0.0, radians(180.0)),
                              length=CAR_LENGTH, into="Actors")
        if model is None:
            return None
        for part in parts:
            part.hide_render = True
            part.hide_set(True)

        # Kenney's kits name their nodes `wheel-front-left` and so on. Anything
        # that is not a wheel simply rides along with the body.
        self.model_wheels = [(obj, "front" in key)
                             for key, obj in sorted(model.parts.items())
                             if "wheel" in key]
        if self.model_wheels:
            self.wheel_radius = _rolling_radius(self.model_wheels[0][0],
                                                model.scale)
        else:
            print(f"[car] {reference} has no wheel nodes; its wheels will not turn")
        return model.root

    # ── placement ─────────────────────────────────────────────────────────────

    def place(self, circuit: Circuit, node: int, checkpoints: list) -> None:
        """
        Put the car on the grid and arm the checkpoint sequence from there.

        A car does not start on the timing line, so its first gate is whichever
        one is next *ahead of its own grid slot*. Starting every car expecting
        gate zero is why a car placed three metres past the line has to drive
        two laps for one to be counted.
        """
        self.node = node
        self.x, self.y = circuit.point_at(node, self.offset)
        self.yaw = circuit.tangent_yaw(node)
        self.progress = circuit.cum[node]
        self.lap_start_progress = self.progress
        self.next_checkpoint = min(
            range(len(checkpoints)),
            key=lambda k: (checkpoints[k] - node) % circuit.n or circuit.n)
        self.sync(0.0)

    def sync(self, roll: float) -> None:
        self.root.location = (self.x, self.y, 0.0)
        self.root.rotation_euler = (0.0, radians(roll), radians(self.yaw))

    # ── driving ───────────────────────────────────────────────────────────────

    def drive(self, circuit: Circuit, dt: float, throttle: float, steer: float,
              off_track: bool) -> None:
        """
        One step of the bicycle model.

        Yaw rate is `v / wheelbase * tan(steer)`: the same lock turns a fast car
        less than a slow one, which is why braking into a corner works here at
        all. Off the road the grip term drops, so a car that cuts a corner
        washes wide instead of teleporting back onto the line.
        """
        wheelbase = 2.84
        grip = self.grip * (0.45 if off_track else 1.0)
        limit = self.top_speed * (0.62 if off_track else 1.0)

        if throttle >= 0.0:
            self.speed += self.accel * throttle * dt
        else:
            self.speed += self.accel * 2.1 * throttle * dt
        drag = 0.016 * self.speed * self.speed * dt
        self.speed = max(1.5, min(limit, self.speed - drag))

        self.steer += (steer - self.steer) * min(1.0, 9.0 * dt)
        self.steer = max(-MAX_STEER_LOCK, min(MAX_STEER_LOCK, self.steer))

        yaw_rate = (self.speed / wheelbase) * tan(self.steer) * grip
        self.yaw = (self.yaw + degrees(yaw_rate) * dt) % 360.0

        f = camera_rigs.forward(self.yaw)
        self.x += f[0] * self.speed * dt
        self.y += f[1] * self.speed * dt

        self._turn_wheels(dt)

    def _turn_wheels(self, dt: float) -> None:
        """
        Roll every wheel and steer the front pair. Visual only, after the fact.

        Rolling is derived from how far the car actually moved rather than driven
        by its own timer, so a wheel cannot spin while the car is stopped — the
        tell that gives away a fake. Left unwrapped past a full turn: modulo would
        make the angle jump from 2*pi back to 0, and the recorder interpolates
        linearly between keyframes, so the wheel would unwind across that jump.

        The rotation order carries the argument. On a model wheel, `(spin, 0,
        steer)` in Blender's default XYZ applies X first, in the wheel's own
        frame, and Z last — roll about the axle, then steer about vertical, which
        is the sequence a real hub uses. The primitive wheel is a cylinder laid
        onto X by a 90 degree Y term, and that middle rotation sits between the
        two, leaving no way to spell rolling; a plain black cylinder shows no roll
        anyway, so it only steers.
        """
        if self.model_wheels:
            self.spin += (self.speed * dt) / self.wheel_radius
            for wheel, steers in self.model_wheels:
                wheel.rotation_euler = (self.spin, 0.0,
                                        self.steer if steers else 0.0)
            return
        for wheel in self.front_wheels:
            wheel.rotation_euler = (0.0, radians(90.0), self.steer)

    def advance_progress(self, circuit: Circuit) -> None:
        """
        Unwrap arc length, so lap counting and "who is ahead" are one number.

        The index alone cannot answer either question on a loop: it wraps to
        zero every lap, and two cars either side of the seam compare backwards.
        Accumulating signed arc length instead gives a value that only grows.
        """
        previous = self.node
        self.node, _ = circuit.nearest(self.x, self.y, hint=previous)

        step = (self.node - previous) % circuit.n
        if step > circuit.n // 2:            # crossed the seam backwards
            step -= circuit.n
        if step > 0:
            self.progress += sum(circuit.seg_len[(previous + k) % circuit.n]
                                 for k in range(step))
        elif step < 0:
            self.progress -= sum(circuit.seg_len[(self.node + k) % circuit.n]
                                 for k in range(-step))


class RacingCircuit(kernel.Game):
    genre = "racing"

    default_spec = {
        # Long enough for the race to actually finish: two laps of the default
        # circuit run about 27 s, and the run stops as soon as the flag drops.
        # A demo that ends mid-lap reports `finished: false`, which is a worse
        # answer than a slightly longer render.
        "duration_sec": 30.0,
        "fps": 30,
        "resolution": (960, 540),
        "samples": 16,
        "seed": 5,
        "sky_color": (0.16, 0.22, 0.34),
        "sky_strength": 0.65,
        "sky_hdri": "/Library/hdris/kloofendal_puresky_2k.hdr",
        "track": {
            "samples": 144,
            "radius": 48.0,
            "wobble": 0.22,
            "lobes": 3,
            "width": 15.0,
            "checkpoints": 6,
        },
        "target_laps": 2,
        "player": {"top_speed": 41.0, "accel": 15.5, "grip": 1.0,
                   "lookahead": 15.0},
        "rivals": [
            {"name": "rival_a", "top_speed": 38.5, "accel": 14.0, "offset": -4.2},
            {"name": "rival_b", "top_speed": 39.8, "accel": 14.6, "offset": 4.2},
        ],
    }

    # ── build ─────────────────────────────────────────────────────────────────

    def build(self) -> None:
        t = self.spec["track"]
        self.circuit = Circuit(int(t["samples"]), float(t["radius"]),
                               float(t["wobble"]), int(t["lobes"]),
                               float(t["width"]))
        self.target_laps = int(self.spec["target_laps"])

        # Outdoor daylight, so the sun has to out-light the sky by a wide margin:
        # the sky fills from every direction at once, and at anything near parity
        # it cancels the shading that tells you a car is a solid object. A 0.2 rad
        # disc was also blurring shadows over about a car length, which took away
        # the contact between wheel and road.
        kernel.add_sun(energy=5.0, rotation=(radians(46), radians(8), radians(120)),
                       angle=0.05)
        self._build_ground()
        self._build_road()
        self._build_props()
        self._build_checkpoints(int(t["checkpoints"]))
        self._build_cars()   # needs checkpoint_nodes, so it follows the gates
        self._build_camera_and_hud()

        self.overtakes = 0
        self.off_track_events = 0
        self._was_off = False
        self._rival_order = self._order()

    def _surface(self, key: str) -> Optional[dict]:
        """The `surfaces.<key>` block, when the task asked for a textured look."""
        return (self.spec.get("surfaces") or {}).get(key)

    def _build_ground(self) -> None:
        grass = materials.surface("race_ground", self._surface("ground"),
                                  color=(0.10, 0.20, 0.12), roughness=0.95,
                                  metres=12.0)
        # Wide enough that its edge is never the horizon. At a little over the
        # track radius the plane ends inside the chase camera's view, and a
        # straight seam across mid-frame with sky below it reads as a green table
        # floating in the void rather than as ground going away from you. Two
        # triangles cost nothing, so the cheap fix is to put the edge past
        # anything the player will look at; `make_camera` clips at 2 km, which
        # this stays well inside.
        extent = float(self.spec["track"]["radius"]) * 12.0
        prims.spawn(prims.PLANE, "ground", location=(0.0, 0.0, -0.06),
                    scale=(extent, extent, 1.0), material=grass, into="Level")

    def _build_road(self) -> None:
        """
        The road surface as one swept ribbon, with kerbs and rails as blocks.

        Kerb blocks are sized to *meet* rather than overlap, and sit a
        centimetre above the road: two coplanar surfaces at the same height are
        the other way to get a striped track.
        """
        road_mat = materials.surface("race_road", self._surface("road"),
                                     color=(0.07, 0.07, 0.085), roughness=0.7,
                                     metres=8.0)
        kerb_a = materials.solid("race_kerb_a", (0.85, 0.10, 0.10), roughness=0.6)
        kerb_b = materials.solid("race_kerb_b", (0.92, 0.92, 0.92), roughness=0.6)
        rail = materials.glow("race_rail", (0.25, 0.85, 1.0), strength=2.0)

        half = self.circuit.width * 0.5
        normals = [self.circuit.normal(i)[:2] for i in range(self.circuit.n)]
        prims.ribbon("road", self.circuit.points, normals, half, z=0.02,
                     material=road_mat, into="Level")

        for i in range(self.circuit.n):
            x0, y0 = self.circuit.points[i]
            x1, y1 = self.circuit.points[(i + 1) % self.circuit.n]
            mx, my = (x0 + x1) * 0.5, (y0 + y1) * 0.5
            yaw = self.circuit.tangent_yaw(i)
            length = self.circuit.seg_len[i]
            nx, ny = normals[i]

            kerb = kerb_a if (i // 2) % 2 == 0 else kerb_b
            for side in (-1.0, 1.0):
                prims.spawn(prims.BOX, f"kerb{i}_{int(side)}",
                            location=(mx + nx * half * side, my + ny * half * side,
                                      0.05),
                            rotation=(0.0, 0.0, radians(yaw)),
                            scale=(0.55, length * 0.5, 0.05),
                            material=kerb, into="Level", collide=False)
                if i % 3 == 0:
                    prims.spawn(prims.BOX, f"rail{i}_{int(side)}",
                                location=(mx + nx * (half + 2.2) * side,
                                          my + ny * (half + 2.2) * side, 0.55),
                                rotation=(0.0, 0.0, radians(yaw)),
                                scale=(0.14, length * 1.1, 0.30),
                                material=rail, into="Level", shadow=False,
                                collide=False)

    def _build_props(self) -> None:
        """
        Dress the circuit with models, spaced along each edge in metres.

        Spacing is measured along the line the props actually stand on, not along
        the centreline, and the difference is not academic: a prop line 9 m outside
        a 15 m corner is more than half again as long as the centreline through it,
        so centreline spacing opens a gap at every joint on the outside of every
        bend while overlapping on the inside. Walking the offset points and
        accumulating the distance between them gives a barrier run that closes up
        on both sides, and it costs one square root per node.

        Spec shape, each entry optional::

            "props": {
                "barrier": {"model": "/Library/models/.../barrierRed.glb",
                            "spacing": 9.0, "length": 3.0, "offset": 2.4},
                "post":    {"model": "...", "spacing": 60.0, "height": 9.0,
                            "offset": 7.0, "sides": [1], "yaw": 90}
            }
        """
        props = self.spec.get("props") or {}
        half = self.circuit.width * 0.5
        for role, entry in props.items():
            reference = entry.get("model")
            if not reference:
                continue
            spacing = max(0.25, float(entry.get("spacing", 12.0)))
            lateral = half + float(entry.get("offset", 2.4))
            yaw_offset = float(entry.get("yaw", 0.0))
            sides = [float(s) for s in entry.get("sides", (-1.0, 1.0))]
            measures = {k: float(entry[k]) for k in ("length", "height") if k in entry}

            placed = 0
            for side in sides:
                for k, (x, y, yaw) in enumerate(
                        self._along_edge(lateral * side, spacing)):
                    made = assets.instance(
                        reference, f"{role}{k}_{int(side)}",
                        location=(x, y, 0.0),
                        rotation=(0.0, 0.0, radians(yaw + yaw_offset)),
                        into="Level", **measures)
                    if made is None:
                        # The asset is missing; one report per role, not per post.
                        break
                    placed += 1
            if placed:
                print(f"[props] {placed} x {role}")

    def _along_edge(self, lateral: float, spacing: float):
        """
        Yield `(x, y, yaw)` every `spacing` metres along a line beside the track.

        Interpolates *within* each segment rather than only landing on the
        circuit's nodes. Nodes are about two metres apart here, so snapping to them
        puts a floor under the spacing that a two-metre barrier cannot close — the
        run would still be gapped no matter what the spec asked for, and the reason
        would be invisible in the spec.

        Yaw comes from the offset line's own direction, not the centreline's. They
        differ through a corner, and it is the barrier that has to look straight.
        """
        n = self.circuit.n
        edge = [self.circuit.point_at(i, lateral) for i in range(n)]
        carried = 0.0
        for i in range(n):
            ax, ay = edge[i]
            bx, by = edge[(i + 1) % n]
            length = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
            if length < 1e-9:
                continue
            yaw = degrees(atan2(-(bx - ax), (by - ay))) % 360.0
            step = carried
            while step < length:
                fraction = step / length
                yield (ax + (bx - ax) * fraction,
                       ay + (by - ay) * fraction, yaw)
                step += spacing
            carried = step - length

    def _build_checkpoints(self, count: int) -> None:
        post = materials.solid("race_post", (0.16, 0.17, 0.20), roughness=0.5)
        gate_mat = materials.glow("race_gate", (1.0, 0.75, 0.15), strength=2.0)
        start_mat = materials.glow("race_start", (0.30, 1.0, 0.45), strength=2.4)

        self.checkpoint_nodes = [int(i * self.circuit.n / count) for i in range(count)]
        half = self.circuit.width * 0.5
        for k, node in enumerate(self.checkpoint_nodes):
            yaw = self.circuit.tangent_yaw(node)
            nx, ny = self.circuit.normal(node)[:2]
            cx, cy = self.circuit.points[node]
            mat = start_mat if k == 0 else gate_mat
            for side in (-1.0, 1.0):
                prims.spawn(prims.BOX_GROUND, f"cp{k}_post{int(side)}",
                            location=(cx + nx * (half + 1.0) * side,
                                      cy + ny * (half + 1.0) * side, 0.0),
                            rotation=(0.0, 0.0, radians(yaw)),
                            scale=(0.28, 0.28, 3.0), material=post,
                            into="Level", collide=False)
            prims.spawn(prims.BOX, f"cp{k}_beam", location=(cx, cy, 5.8),
                        rotation=(0.0, 0.0, radians(yaw)),
                        scale=(half + 1.2, 0.22, 0.30), material=mat,
                        into="Level", shadow=False, collide=False)

    def _resolve_rivals(self) -> list:
        """
        Overlay the spec's rivals on the defaults, entry by entry.

        `Game.__init__` merges nested dicts but replaces lists outright. The
        grid is the exception: entries are positional, so a task that only wants
        to slow one rival down should be able to give its `top_speed` without
        also restating its name, accel and starting offset.
        """
        defaults = self.default_spec["rivals"]
        given = self.spec.get("rivals") or defaults
        return [kernel.merge_spec(defaults[i] if i < len(defaults) else {}, entry)
                for i, entry in enumerate(given)]

    def _build_cars(self) -> None:
        p = self.spec["player"]
        self.player = Car(self, "player", materials.PALETTE["player"], index=0,
                          offset=0.0, top_speed=float(p["top_speed"]),
                          accel=float(p["accel"]), grip=float(p["grip"]),
                          is_player=True)
        self.player.place(self.circuit, 4, self.checkpoint_nodes)

        self.rivals: list[Car] = []
        palette = [materials.PALETTE["hazard"], materials.PALETTE["ally"],
                   materials.PALETTE["neon_pink"]]
        for i, spec in enumerate(self._resolve_rivals()):
            car = Car(self, spec["name"], palette[i % len(palette)], index=i + 1,
                      offset=float(spec["offset"]),
                      top_speed=float(spec["top_speed"]),
                      accel=float(spec["accel"]), grip=1.0, is_player=False)
            car.place(self.circuit, 4 + (i + 1) * 3, self.checkpoint_nodes)
            self.rivals.append(car)
        self.cars = [self.player] + self.rivals

    def _build_camera_and_hud(self) -> None:
        self.camera = camera_rigs.make_camera("race_cam", lens=34.0)
        self.chase = camera_rigs.ChaseRig(self.camera, distance=11.0, height=4.2,
                                          pitch=-11.0, stiffness=0.16)
        self.cockpit = camera_rigs.FirstPersonRig(self.camera, eye_height=0.95,
                                                  forward_offset=0.45)
        self.first_person = False
        self.rig = self.chase
        self.recorder.track(self.camera, channels=("location", "rotation_euler"))

        self.hud = hud.Hud(self.camera, self.resolution)
        self.speed_bar = self.hud.bar("speed", (-0.93, -0.86), width=0.52,
                                      height=0.05, color=(0.30, 0.85, 1.0))
        self.hud.label("speed_txt", "SPEED", (-0.93, -0.74), size=0.05)
        self.lap_pips = self.hud.pip_row("lap", (0.42, 0.86), self.target_laps,
                                         size=0.045, gap=0.075,
                                         color=(0.35, 1.0, 0.5))
        self.hud.label("lap_txt", "LAP", (0.42, 0.74), size=0.05)
        self.pos_pips = self.hud.pip_row("pos", (0.42, -0.86), len(self.spec["rivals"]) + 1,
                                         size=0.038, gap=0.062,
                                         color=(1.0, 0.85, 0.25))
        self.hud.label("pos_txt", "POS", (0.42, -0.74), size=0.05)
        self.offtrack_flash = self.hud.vignette("off", color=(1.0, 0.55, 0.1),
                                                strength=2.0, alpha=0.22)
        self.hud.register(self.recorder)
        self.lap_pips.set(0)

    # ── simulation ────────────────────────────────────────────────────────────

    def tick(self) -> None:
        for car in self.cars:
            self._drive_car(car)
            car.advance_progress(self.circuit)
            self._check_lap(car)

        self._check_overtakes()
        self._update_camera_and_hud()

        if self.player.lap >= self.target_laps:
            self.finish("target_laps_reached")

    def _drive_car(self, car: Car) -> None:
        """
        Get this car's throttle and steering, then step the vehicle model.

        The split matters: a human's car and a rival's car go through the same
        `Car.drive()`, so the grip, the drag and the off-track penalty are not
        re-implemented for the player. Only the two numbers coming in differ.
        """
        if car.is_player and self.human:
            throttle, steer = self._player_drive()
        else:
            throttle, steer = self._pursue(car)

        _, distance = self.circuit.nearest(car.x, car.y, hint=car.node)
        off_track = distance > self.circuit.width * 0.5
        if car.is_player:
            if off_track and not self._was_off:
                self.off_track_events += 1
                self.offtrack_flash.trigger(3)
                self.log("off_track", speed=round(car.speed, 1))
            self._was_off = off_track
        if off_track:
            car.off_track_ticks += 1

        car.drive(self.circuit, self.dt, throttle, steer, off_track)
        roll = -car.steer * min(1.0, car.speed / car.top_speed) * 9.0
        car.sync(roll)

    def _player_drive(self) -> tuple:
        """
        Throttle and steering from one tick of human intent.

        Brake arrives as negative throttle because that is the pedal the vehicle
        model already has, and it applies 2.1× the force there — which is what
        makes braking into a corner work instead of just coasting.
        """
        c = self.controls
        throttle = float(c.throttle) - float(c.brake)
        steer = -float(c.steer) * MAX_STEER_LOCK    # + steer is right, + yaw is left

        if c.handbrake:
            # Lock up and let the front end bite: an arcade handbrake, there so
            # a hairpin taken too fast is recoverable rather than a wall.
            throttle = -1.0
            steer *= 1.3
        return throttle, max(-MAX_STEER_LOCK, min(MAX_STEER_LOCK, steer))

    def _pursue(self, car: Car) -> tuple:
        """
        Pure pursuit: aim at a point down the road, brake for what is past it.

        Look-ahead scales with speed, which is what stops a fast car sawing at
        the wheel on a straight and understeering into every corner entry.
        """
        lookahead = 9.0 + car.speed * 0.42
        step = max(1, int(lookahead / max(0.5, self.circuit.length / self.circuit.n)))
        aim_node = (car.node + step) % self.circuit.n
        ax, ay = self.circuit.point_at(aim_node, car.offset)

        wanted = degrees(atan2(-(ax - car.x), (ay - car.y))) % 360.0
        error = (wanted - car.yaw + 180.0) % 360.0 - 180.0
        steer = max(-MAX_STEER_LOCK, min(MAX_STEER_LOCK, radians(error) * 1.25))

        # Brake for the corner *after* the one being steered through.
        far_node = (car.node + step * 2) % self.circuit.n
        curvature = abs((self.circuit.tangent_yaw(far_node)
                         - self.circuit.tangent_yaw(car.node) + 180.0) % 360.0 - 180.0)
        throttle = 1.0
        if curvature > 26.0 and car.speed > car.top_speed * 0.55:
            throttle = -0.75
        elif curvature > 14.0 and car.speed > car.top_speed * 0.78:
            throttle = -0.2
        return throttle, steer

    def _check_lap(self, car: Car) -> None:
        """
        A lap is a full circuit of arc length *with every gate taken in order*.

        Distance alone would credit a lap to a car that drove up and down the
        same straight; gates alone would credit one to a car that reversed over
        the line. Requiring both is what makes the count mean something, and it
        works from any grid slot because both quantities are measured from where
        the car started rather than from the timing line.
        """
        gates = len(self.checkpoint_nodes)
        target = self.checkpoint_nodes[car.next_checkpoint]
        if (car.node - target) % self.circuit.n < 6:
            car.checkpoints_taken += 1
            car.next_checkpoint = (car.next_checkpoint + 1) % gates

        travelled = car.progress - car.lap_start_progress
        if (travelled >= self.circuit.length * 0.97
                and car.checkpoints_taken - car.cp_at_lap_start >= gates):
            lap_time = self.time - car.lap_started
            car.lap_started = self.time
            car.lap_start_progress = car.progress
            car.cp_at_lap_start = car.checkpoints_taken
            car.lap += 1
            car.lap_times.append(round(lap_time, 2))
            self.log("lap_complete", car=car.name, lap=car.lap,
                     lap_time=round(lap_time, 2),
                     avg_speed_kmh=round(travelled / max(lap_time, 0.01) * 3.6, 1))

    #: Metres one car must be clear by before the running order changes. Two
    #: cars side by side differ by centimetres of arc length and would otherwise
    #: swap places every tick, turning a single wheel-to-wheel battle into
    #: dozens of "overtakes".
    ORDER_DEADBAND = 2.5

    def _order(self) -> list:
        return [c.name for c in sorted(self.cars, key=lambda c: -c.progress)]

    def _check_overtakes(self) -> None:
        candidate = self._order()
        if candidate == self._rival_order:
            return

        by_name = {c.name: c for c in self.cars}
        settled = self._rival_order.index("player")
        proposed = candidate.index("player")
        if settled == proposed:
            return

        # Only accept the swap once the player is clear of the car being passed.
        other = self._rival_order[proposed]
        margin = by_name["player"].progress - by_name[other].progress
        if abs(margin) < self.ORDER_DEADBAND:
            return

        self._rival_order = candidate
        if proposed < settled:
            self.overtakes += 1
            self.log("overtake", position=proposed + 1, passed=other,
                     margin_m=round(abs(margin), 1))
        else:
            self.log("overtaken", position=proposed + 1, by=other)

    def _update_camera_and_hud(self) -> None:
        if self.human and self.controls.pressed("camera_toggle"):
            self.first_person = not self.first_person
            self.log("camera_mode", first_person=self.first_person)
        elif not self.human and self.time > 8.0 and not self.first_person:
            # Unattended demo: a few seconds of chase, then the cockpit so both
            # rigs appear in the video.
            self.first_person = True
            self.log("camera_mode", first_person=True)

        ratio = self.player.speed / self.player.top_speed
        if self.first_person:
            self.camera.data.lens = 28.0
            self.cockpit.update((self.player.x, self.player.y, 0.0),
                                self.player.yaw, pitch=-4.0)
        else:
            self.camera.data.lens = 34.0
            self.chase.update((self.player.x, self.player.y, 0.9), self.player.yaw,
                              speed_ratio=ratio)
        self.speed_bar.set(ratio)
        self.lap_pips.set(min(self.player.lap, self.target_laps))
        self.pos_pips.set(len(self.cars) - self._order().index("player"))
        self.offtrack_flash.advance()

    # ── report ────────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        times = self.player.lap_times
        return {
            "laps_completed": self.player.lap,
            "target_laps": self.target_laps,
            "lap_times_sec": times,
            "best_lap_sec": min(times) if times else None,
            "finished": self.player.lap >= self.target_laps,
            "final_position": self._order().index("player") + 1,
            "field_size": len(self.cars),
            "overtakes": self.overtakes,
            "off_track_events": self.off_track_events,
            "off_track_ratio": round(self.player.off_track_ticks / max(1, self.frame), 3),
            "top_speed_kmh": round(self.player.top_speed * 3.6, 1),
            "avg_speed_kmh": round(self.player.progress / max(self.time, 0.01) * 3.6, 1),
            "track_length_m": round(self.circuit.length, 1),
            "rival_laps": {c.name: c.lap for c in self.rivals},
        }

    def verdict(self, summary: dict) -> tuple:
        problems = []
        if summary["laps_completed"] == 0:
            problems.append("no lap was completed — checkpoints or timing broken")
        if summary["avg_speed_kmh"] < 30:
            problems.append("field never got up to speed")
        if summary["off_track_ratio"] > 0.35:
            problems.append("car spent most of the race off the road")
        if not any(c.lap > 0 for c in self.rivals):
            problems.append("rivals completed no lap — AI is not racing")
        return (not problems), problems


if __name__ == "__main__":
    kernel.main(RacingCircuit)
