"""
Synthetic humanoid assets for motion tests: mesh + Puppeteer rig + Mixamo BVH.

Not the pipeline itself — only sample inputs. Same topology (``HUMANOID``) on
both sides so ``mapping_auto`` can succeed. Authored Y-up in metres
(glTF convention; ``rig_io`` rotates into Blender Z-up).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Joint:
    """Rest pose (metres) and children."""

    slot: str
    position: tuple[float, float, float]
    children: list["Joint"] = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def _joint(slot: str, position, *children: Joint) -> Joint:
    return Joint(slot, position, list(children))


def _limb(side: str, sign: float) -> tuple[Joint, Joint]:
    """Arm + leg for one side; ``sign`` mirrors across X."""
    arm = _joint(
        f"{side}_shoulder",
        (0.06 * sign, 1.42, 0.0),
        _joint(
            f"{side}_upper_arm",
            (0.19 * sign, 1.40, 0.0),
            _joint(
                f"{side}_forearm",
                (0.44 * sign, 1.40, 0.0),
                _joint(f"{side}_hand", (0.66 * sign, 1.40, 0.0)),
            ),
        ),
    )
    leg = _joint(
        f"{side}_thigh",
        (0.11 * sign, 0.92, 0.0),
        _joint(
            f"{side}_shin",
            (0.11 * sign, 0.52, 0.0),
            _joint(
                f"{side}_foot",
                (0.11 * sign, 0.09, 0.0),
                _joint(f"{side}_toe", (0.11 * sign, 0.03, 0.13)),
            ),
        ),
    )
    return arm, leg


_LEFT_ARM, _LEFT_LEG = _limb("left", 1.0)
_RIGHT_ARM, _RIGHT_LEG = _limb("right", -1.0)

# ~1.8 m figure shared by mesh, rig, and BVH.
HUMANOID = _joint(
    "hips",
    (0.0, 0.95, 0.0),
    _joint(
        "spine",
        (0.0, 1.10, 0.0),
        _joint(
            "spine1",
            (0.0, 1.28, 0.0),
            _joint(
                "neck",
                (0.0, 1.47, 0.0),
                _joint("head", (0.0, 1.60, 0.0)),
            ),
            _LEFT_ARM,
            _RIGHT_ARM,
        ),
    ),
    _LEFT_LEG,
    _RIGHT_LEG,
)

MIXAMO_NAMES = {
    "hips": "mixamorig:Hips",
    "spine": "mixamorig:Spine",
    "spine1": "mixamorig:Spine1",
    "neck": "mixamorig:Neck",
    "head": "mixamorig:Head",
    "left_shoulder": "mixamorig:LeftShoulder",
    "left_upper_arm": "mixamorig:LeftArm",
    "left_forearm": "mixamorig:LeftForeArm",
    "left_hand": "mixamorig:LeftHand",
    "right_shoulder": "mixamorig:RightShoulder",
    "right_upper_arm": "mixamorig:RightArm",
    "right_forearm": "mixamorig:RightForeArm",
    "right_hand": "mixamorig:RightHand",
    "left_thigh": "mixamorig:LeftUpLeg",
    "left_shin": "mixamorig:LeftLeg",
    "left_foot": "mixamorig:LeftFoot",
    "left_toe": "mixamorig:LeftToeBase",
    "right_thigh": "mixamorig:RightUpLeg",
    "right_shin": "mixamorig:RightLeg",
    "right_foot": "mixamorig:RightFoot",
    "right_toe": "mixamorig:RightToeBase",
}

# slot -> (centre, half-extents) for the blocky skin.
_BLOCKS = {
    "hips": ((0.0, 0.98, 0.0), (0.16, 0.10, 0.10)),
    "spine1": ((0.0, 1.25, 0.0), (0.19, 0.20, 0.11)),
    "head": ((0.0, 1.62, 0.0), (0.10, 0.12, 0.10)),
    "left_upper_arm": ((0.31, 1.40, 0.0), (0.13, 0.06, 0.06)),
    "left_forearm": ((0.55, 1.40, 0.0), (0.12, 0.05, 0.05)),
    "right_upper_arm": ((-0.31, 1.40, 0.0), (0.13, 0.06, 0.06)),
    "right_forearm": ((-0.55, 1.40, 0.0), (0.12, 0.05, 0.05)),
    "left_thigh": ((0.11, 0.72, 0.0), (0.08, 0.20, 0.08)),
    "left_shin": ((0.11, 0.30, 0.0), (0.07, 0.22, 0.07)),
    "left_foot": ((0.11, 0.05, 0.06), (0.07, 0.05, 0.13)),
    "right_thigh": ((-0.11, 0.72, 0.0), (0.08, 0.20, 0.08)),
    "right_shin": ((-0.11, 0.30, 0.0), (0.07, 0.22, 0.07)),
    "right_foot": ((-0.11, 0.05, 0.06), (0.07, 0.05, 0.13)),
}


def build_mesh(path: str | Path):
    """Write concatenated boxes; format follows the file suffix."""
    import numpy as np
    import trimesh

    parts = []
    for centre, half in _BLOCKS.values():
        box = trimesh.creation.box(
            extents=[value * 2.0 for value in half],
        )
        box.apply_translation(np.asarray(centre, dtype=float))
        parts.append(box)
    mesh = trimesh.util.concatenate(parts)

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(output))
    return output


def build_rig(path: str | Path, mesh_path: str | Path) -> Path:
    """Puppeteer ``.txt``: ``joint0…N`` DFS names, nearest-joint skinning."""
    import numpy as np
    import trimesh

    joints = list(HUMANOID.walk())
    names = {id(joint): f"joint{index}" for index, joint in enumerate(joints)}

    lines = [
        f"joints {names[id(joint)]} "
        + " ".join(f"{value:.6f}" for value in joint.position)
        for joint in joints
    ]
    lines.append(f"root {names[id(HUMANOID)]}")
    for joint in joints:
        for child in joint.children:
            lines.append(f"hier {names[id(joint)]} {names[id(child)]}")

    mesh = trimesh.load(
        str(mesh_path),
        force="mesh",
        process=False,
        maintain_order=True,
    )
    vertices = np.asarray(mesh.vertices)
    positions = np.asarray([joint.position for joint in joints])
    nearest = np.argmin(
        ((vertices[:, None, :] - positions[None, :, :]) ** 2).sum(axis=2),
        axis=1,
    )
    for index, joint_index in enumerate(nearest):
        lines.append(f"skin {index} {names[id(joints[int(joint_index)])]} 1.0")

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def build_bvh(
    path: str | Path,
    *,
    frames: int = 12,
    fps: int = 30,
    scale: float = 1.0,
) -> Path:
    """Mixamo-named in-place walk; ``scale`` multiplies offsets (e.g. cm)."""
    moving = {
        "hips": (0.0, 6.0, 0.0),
        "left_thigh": (0.0, 22.0, 0.0),
        "right_thigh": (0.0, -22.0, 0.0),
        "left_shin": (0.0, -18.0, 0.0),
        "right_shin": (0.0, 18.0, 0.0),
        "left_upper_arm": (0.0, -16.0, 0.0),
        "right_upper_arm": (0.0, 16.0, 0.0),
    }

    ordered: list[Joint] = []
    hierarchy: list[str] = []

    def emit(joint: Joint, parent: Joint | None, depth: int) -> None:
        pad = "  " * depth
        offset = tuple(
            (value - base) * scale
            for value, base in zip(
                joint.position,
                parent.position if parent else (0.0, 0.0, 0.0),
            )
        )
        keyword = "ROOT" if parent is None else "JOINT"
        hierarchy.append(f"{pad}{keyword} {MIXAMO_NAMES[joint.slot]}")
        hierarchy.append(f"{pad}{{")
        hierarchy.append(
            f"{pad}  OFFSET "
            + " ".join(f"{value:.6f}" for value in offset)
        )
        hierarchy.append(
            f"{pad}  CHANNELS 6 Xposition Yposition Zposition "
            "Zrotation Xrotation Yrotation"
            if parent is None
            else f"{pad}  CHANNELS 3 Zrotation Xrotation Yrotation"
        )
        ordered.append(joint)
        for child in joint.children:
            emit(child, joint, depth + 1)
        if not joint.children:
            hierarchy.append(f"{pad}  End Site")
            hierarchy.append(f"{pad}  {{")
            hierarchy.append(f"{pad}    OFFSET 0.000000 {0.10 * scale:.6f} 0.000000")
            hierarchy.append(f"{pad}  }}")
        hierarchy.append(f"{pad}}}")

    emit(HUMANOID, None, 0)

    motion = []
    for frame in range(frames):
        phase = 2.0 * math.pi * frame / max(1, frames - 1)
        values: list[str] = []
        for joint in ordered:
            swing = moving.get(joint.slot)
            angles = (
                tuple(amount * math.sin(phase) for amount in swing)
                if swing
                else (0.0, 0.0, 0.0)
            )
            if joint is HUMANOID:
                values += [
                    "0.000000",
                    f"{HUMANOID.position[1] * scale:.6f}",
                    f"{0.25 * scale * frame / max(1, frames - 1):.6f}",
                ]
            values += [f"{angle:.6f}" for angle in angles]
        motion.append(" ".join(values))

    text = "\n".join(
        [
            "HIERARCHY",
            *hierarchy,
            "MOTION",
            f"Frames: {frames}",
            f"Frame Time: {1.0 / fps:.6f}",
            *motion,
            "",
        ]
    )
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return output


def build_all(root: str | Path, *, mesh_format: str = ".glb") -> dict[str, str]:
    """Build mesh, rig, and clip into one directory."""
    directory = Path(root)
    mesh = build_mesh(directory / f"character{mesh_format}")
    rig = build_rig(directory / "character_rig.txt", mesh)
    clip = build_bvh(directory / "walk.bvh")
    return {
        "mesh_path": str(mesh),
        "rig_path": str(rig),
        "motion_path": str(clip),
    }


__all__ = [
    "HUMANOID",
    "MIXAMO_NAMES",
    "Joint",
    "build_all",
    "build_bvh",
    "build_mesh",
    "build_rig",
]
