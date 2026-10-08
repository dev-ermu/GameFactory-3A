#!/usr/bin/env python3
"""Infer a source-to-Puppeteer mapping for the gen-motion retarget function."""

import argparse
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import bpy  # type: ignore
from mathutils import Matrix, Vector  # type: ignore


def world_head(armature: bpy.types.Object, name: str) -> Vector:
    return armature.matrix_world @ armature.data.bones[name].head_local


def subtree_size(
    armature: bpy.types.Object,
    name: str,
    cache: Dict[str, int],
) -> int:
    if name not in cache:
        cache[name] = 1 + sum(
            subtree_size(armature, child.name, cache)
            for child in armature.data.bones[name].children
        )
    return cache[name]


def find_hips(armature: bpy.types.Object) -> str:
    cache: Dict[str, int] = {}
    candidates = [
        bone.name for bone in armature.data.bones if len(bone.children) >= 3
    ]
    if not candidates:
        candidates = [
            bone.name
            for bone in armature.data.bones
            if len(bone.children) >= 2
        ]
    if not candidates:
        roots = [
            bone.name for bone in armature.data.bones if bone.parent is None
        ]
        if len(roots) != 1:
            raise ValueError(
                "Auto mapping requires a connected humanoid skeleton with one root"
            )
        return roots[0]
    return max(
        candidates,
        key=lambda name: subtree_size(armature, name, cache),
    )


def walk_chain(
    armature: bpy.types.Object,
    start: str,
    maximum: int = 64,
) -> List[str]:
    chain = [start]
    current = armature.data.bones[start]
    while len(chain) < maximum and len(current.children) == 1:
        current = current.children[0]
        chain.append(current.name)
    return chain


def first_branch(
    armature: bpy.types.Object,
    start: str,
) -> Optional[str]:
    current = armature.data.bones[start]
    while True:
        if len(current.children) >= 2:
            return current.name
        if not current.children:
            return None
        current = current.children[0]


def classify(
    armature: bpy.types.Object,
    transform: Matrix,
) -> Dict[str, object]:
    """Classify hips, spine, two arms and two legs structurally."""
    bones = armature.data.bones

    def position(name: str) -> Vector:
        return transform @ world_head(armature, name)

    def tip(name: str) -> str:
        return walk_chain(armature, name)[-1]

    def tip_position(name: str) -> Vector:
        return position(tip(name))

    hips = find_hips(armature)
    hips_position = position(hips)
    children = [child.name for child in bones[hips].children]
    if len(children) < 3:
        raise ValueError(
            f"Auto mapping could not find a humanoid hip junction at {hips!r}"
        )

    leg_roots = [
        name for name in children if tip_position(name).z < hips_position.z
    ]
    spine_candidates = [
        name for name in children if tip_position(name).z >= hips_position.z
    ]
    if not spine_candidates:
        spine_candidates = [max(children, key=lambda name: tip_position(name).z)]
        leg_roots = [
            name for name in children if name not in spine_candidates
        ]
    spine_root = max(
        spine_candidates,
        key=lambda name: tip_position(name).z,
    )

    chest = first_branch(armature, spine_root)
    pre_chest: List[str] = []
    current = bones[spine_root]
    while current.name != (chest or current.name):
        pre_chest.append(current.name)
        current = current.children[0]
    if chest:
        pre_chest.append(chest)

    arm_roots: List[str] = []
    neck_chain: List[str] = []
    if chest:
        chest_children = [child.name for child in bones[chest].children]
        if len(chest_children) < 2:
            raise ValueError(
                f"Auto mapping chest {chest!r} has too few branches"
            )
        if len(chest_children) == 2:
            # Puppeteer can emit a compact humanoid where the chest branches
            # directly into two arms and has no explicit neck/head bones.
            arm_roots = chest_children
        else:
            neck_root = max(
                chest_children,
                key=lambda name: tip_position(name).z,
            )
            arm_roots = [
                name for name in chest_children if name != neck_root
            ]
            neck_chain = walk_chain(armature, neck_root)
    else:
        neck_chain = walk_chain(armature, spine_root)
        pre_chest = []

    leg_roots.sort(key=lambda name: tip_position(name).x)
    arm_roots.sort(key=lambda name: tip_position(name).x)
    leg_chains = tuple(
        walk_chain(armature, root)[:4] for root in leg_roots[:2]
    )
    arm_chains = tuple(
        walk_chain(armature, root)[:4] for root in arm_roots[:2]
    )
    spine = [hips] + pre_chest

    if (
        len(leg_chains) != 2
        or any(len(chain) < 2 for chain in leg_chains)
        or len(arm_chains) != 2
        or any(len(chain) < 2 for chain in arm_chains)
        or len(spine) < 2
    ):
        raise ValueError(
            "Auto mapping supports conventional humanoids only; could not "
            "identify two arms, two legs and a spine"
        )
    return {
        "hips": hips,
        "spine": spine,
        "neck": neck_chain,
        "legs": leg_chains,
        "arms": arm_chains,
    }


def sample_chain(chain: Sequence[str], count: int) -> List[str]:
    """Select ``count`` ordered bones while preserving both endpoints."""
    if count <= 0:
        return []
    if count >= len(chain):
        return list(chain)
    if count == 1:
        return [chain[0]]
    last = len(chain) - 1
    return [chain[round(index * last / (count - 1))] for index in range(count)]


def align_chains(
    name: str,
    source_chain: Sequence[str],
    target_chain: Sequence[str],
) -> Tuple[List[str], List[str]]:
    """Align optional compact Puppeteer chains without inventing bones."""
    count = min(len(source_chain), len(target_chain))
    if name == "spine":
        return sample_chain(source_chain, count), sample_chain(target_chain, count)
    if name.endswith("_arm"):
        # A compact Puppeteer arm normally omits proximal shoulder/upper-arm
        # joints, so align its remaining bones with the distal source chain.
        return list(source_chain[-count:]), list(target_chain[-count:])
    return list(source_chain[:count]), list(target_chain[:count])


def left_sign_from_mixamo(armature: bpy.types.Object) -> int:
    hips = world_head(armature, "mixamorig:Hips")
    left_leg = world_head(armature, "mixamorig:LeftUpLeg")
    return 1 if left_leg.x - hips.x >= 0 else -1


def resolve_left_sign(
    source: bpy.types.Object,
    explicit: Optional[int],
) -> int:
    if explicit is not None:
        return explicit
    try:
        return left_sign_from_mixamo(source)
    except (KeyError, TypeError):
        return 1


def split_left_right(
    chains: Sequence[List[str]],
    armature: bpy.types.Object,
    transform: Matrix,
    left_sign: int,
) -> Tuple[List[str], List[str]]:
    if len(chains) != 2:
        raise ValueError("Expected exactly two limb chains for auto mapping")
    first, second = chains
    first_x = (transform @ world_head(armature, first[-1])).x
    second_x = (transform @ world_head(armature, second[-1])).x
    return (
        (first, second)
        if first_x * left_sign > second_x * left_sign
        else (second, first)
    )


def build_mapping(
    source_armature: bpy.types.Object,
    target_armature: bpy.types.Object,
    left_sign: Optional[int] = None,
) -> Tuple[Dict[str, str], Dict[str, dict], str, str]:
    """Build a topology/geometric mapping for a conventional humanoid."""
    identity = Matrix.Identity(4)
    source = classify(source_armature, identity)
    target = classify(target_armature, identity)
    sign = resolve_left_sign(source_armature, left_sign)

    source_left_leg, source_right_leg = split_left_right(
        source["legs"],
        source_armature,
        identity,
        sign,
    )
    target_left_leg, target_right_leg = split_left_right(
        target["legs"],
        target_armature,
        identity,
        sign,
    )
    source_left_arm, source_right_arm = split_left_right(
        source["arms"],
        source_armature,
        identity,
        sign,
    )
    target_left_arm, target_right_arm = split_left_right(
        target["arms"],
        target_armature,
        identity,
        sign,
    )

    raw_chains = {
        "spine": (source["spine"], target["spine"]),
        "left_arm": (source_left_arm, target_left_arm),
        "right_arm": (source_right_arm, target_right_arm),
        "left_leg": (source_left_leg, target_left_leg),
        "right_leg": (source_right_leg, target_right_leg),
    }
    if source["neck"] and target["neck"]:
        raw_chains["neck"] = (source["neck"], target["neck"])
    chains: Dict[str, dict] = {}
    bone_map: Dict[str, str] = {}
    for name, (source_chain, target_chain) in raw_chains.items():
        source_trimmed, target_trimmed = align_chains(
            name,
            source_chain,
            target_chain,
        )
        chains[name] = {
            "source": source_trimmed,
            "rig": target_trimmed,
        }
        for source_name, target_name in zip(
            source_trimmed,
            target_trimmed,
        ):
            bone_map.setdefault(source_name, target_name)

    if len(bone_map) < 8:
        raise ValueError(
            f"Auto mapping matched only {len(bone_map)} bones; refusing "
            "to emit an unreliable humanoid mapping"
        )
    return (
        bone_map,
        chains,
        str(source["hips"]),
        str(target["hips"]),
    )


def write_mapping(
    path: str,
    bone_map: Dict[str, str],
    chains: Dict[str, dict],
    source_root: str,
    target_root: str,
    source_label: str,
) -> None:
    payload = {
        "description": (
            f"{source_label} source to Puppeteer target; auto-generated "
            "from skeleton topology and world-pose geometry."
        ),
        "source_skeleton": source_label,
        "target_skeleton": "Puppeteer",
        "root_bones": {
            "source": source_root,
            "rig": target_root,
        },
        "bone_map": bone_map,
        "retarget_chains": chains,
        "notes": [
            "No joint indices are hardcoded.",
            "Only conventional connected humanoids are accepted.",
            "Compact chains are aligned by anatomical segment and available endpoints.",
        ],
    }
    output = Path(path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def generate_from_motion(
    mesh: str,
    rig: str,
    source_animation: str,
    output: str,
    *,
    global_scale: float = 1.0,
    left_sign: Optional[int] = None,
) -> None:
    """
    Build both armatures exactly as retargeting does, then infer the mapping.

    "Exactly as" is the whole point. A mapping inferred from a differently
    imported skeleton is a mapping for a skeleton that will not exist at
    retarget time — so this calls the same two builders rather than a cheaper
    parse, and pays a second Blender import to guarantee the bone names and
    world poses it reasons about are the ones ``world_delta`` will see.
    """
    from .rig_io import clear_bpy_data
    from .world_delta import build_puppeteer_rig, import_source_animation

    clear_bpy_data()
    _, target = build_puppeteer_rig(mesh, rig)
    target.name = "Puppeteer"
    source, _ = import_source_animation(
        source_animation,
        global_scale=global_scale,
    )
    source.hide_viewport = False
    source.name = "Source"
    bpy.context.scene.frame_set(int(bpy.context.scene.frame_start))

    bone_map, chains, source_root, target_root = build_mapping(
        source,
        target,
        left_sign,
    )
    extension = os.path.splitext(source_animation)[1].lower()
    label = "BVH" if extension == ".bvh" else "FBX"
    write_mapping(
        output,
        bone_map,
        chains,
        source_root,
        target_root,
        label,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mesh",
        "--glb",
        dest="mesh",
        required=True,
        help="Character mesh: .glb, .gltf, .obj, .ply, .stl or .fbx.",
    )
    parser.add_argument("--rig", required=True)
    parser.add_argument("--source-anim", required=True)
    parser.add_argument("--global-scale", type=float, default=1.0)
    parser.add_argument("--left-sign", type=int, choices=(-1, 1), default=None)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generate_from_motion(
        args.mesh,
        args.rig,
        args.source_anim,
        args.output,
        global_scale=args.global_scale,
        left_sign=args.left_sign,
    )


if __name__ == "__main__":
    main()
