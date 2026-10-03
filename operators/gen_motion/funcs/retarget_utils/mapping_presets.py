"""
Source-skeleton registry for retargeting.

``SOURCE_SKELETONS`` describes reusable clip-side bone names (Mixamo, CMU, …)
by anatomical slot. Full bone maps are not checked in: Puppeteer joints are
per-mesh, so pass ``mapping_path`` or let ``mapping_auto`` derive one.

CLI: ``--list`` / ``--identify motion.bvh``
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


# Anatomical slots in humanoid walk order; profiles may omit some (e.g. no toes).
SLOTS: tuple[str, ...] = (
    "hips",
    "spine",
    "spine1",
    "spine2",
    "neck",
    "head",
    "left_shoulder",
    "left_upper_arm",
    "left_forearm",
    "left_hand",
    "right_shoulder",
    "right_upper_arm",
    "right_forearm",
    "right_hand",
    "left_thigh",
    "left_shin",
    "left_foot",
    "left_toe",
    "right_thigh",
    "right_shin",
    "right_foot",
    "right_toe",
)


@dataclass(frozen=True)
class SourceSkeleton:
    """One motion library's bone naming, by anatomical slot."""

    name: str
    description: str
    bones: dict[str, str]
    notes: tuple[str, ...] = ()

    @property
    def root(self) -> str:
        return self.bones["hips"]

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "root_bone": self.root,
            "slot_count": len(self.bones),
            "bones": dict(self.bones),
            "notes": list(self.notes),
        }


def _humanoid(
    *,
    hips: str,
    spine: Sequence[str],
    neck: str,
    head: str,
    shoulder: str,
    upper_arm: str,
    forearm: str,
    hand: str,
    thigh: str,
    shin: str,
    foot: str,
    toe: str | None,
    left: str,
    right: str,
    axial: str = "{}",
) -> dict[str, str]:
    """Build slot→bone names from limb stems + side/axial format strings."""
    bones = {
        "hips": axial.format(hips),
        "neck": axial.format(neck),
        "head": axial.format(head),
    }
    for slot, name in zip(("spine", "spine1", "spine2"), spine):
        bones[slot] = axial.format(name)
    limbs = (
        ("shoulder", shoulder),
        ("upper_arm", upper_arm),
        ("forearm", forearm),
        ("hand", hand),
        ("thigh", thigh),
        ("shin", shin),
        ("foot", foot),
        ("toe", toe),
    )
    for slot, stem in limbs:
        if stem is None:
            continue
        bones[f"left_{slot}"] = left.format(stem)
        bones[f"right_{slot}"] = right.format(stem)
    return bones


SOURCE_SKELETONS: dict[str, SourceSkeleton] = {
    "mixamo": SourceSkeleton(
        name="mixamo",
        description=(
            "Adobe Mixamo, and every clip auto-rigged through it. The "
            "'mixamorig:' prefix makes this the easiest source to recognise."
        ),
        bones=_humanoid(
            hips="Hips",
            spine=("Spine", "Spine1", "Spine2"),
            neck="Neck",
            head="Head",
            shoulder="Shoulder",
            upper_arm="Arm",
            forearm="ForeArm",
            hand="Hand",
            thigh="UpLeg",
            shin="Leg",
            foot="Foot",
            toe="ToeBase",
            left="mixamorig:Left{}",
            right="mixamorig:Right{}",
            axial="mixamorig:{}",
        ),
        notes=(
            "Downloaded FBX is centimetre-scale; retarget with "
            "global_scale=0.01 against a metre-scale Puppeteer rig.",
            "'Without Skin' downloads carry the armature only, which is what "
            "retargeting wants.",
        ),
    ),
    "momask_bvh": SourceSkeleton(
        name="momask_bvh",
        description=(
            "The BVH this repo's own text-to-motion stage writes: HumanML3D "
            "joints exported by MoMask at 20 fps, unprefixed Mixamo names."
        ),
        bones=_humanoid(
            hips="Hips",
            spine=("Spine", "Spine1", "Spine2"),
            neck="Neck",
            head="Head",
            shoulder="Shoulder",
            upper_arm="Arm",
            forearm="ForeArm",
            hand="Hand",
            thigh="UpLeg",
            shin="Leg",
            foot="Foot",
            toe=None,
            left="Left{}",
            right="Right{}",
        ),
        notes=(
            "20 fps natively — pass that through instead of resampling, or "
            "the clip plays at the wrong speed.",
            "No toe bones: HumanML3D's 22-joint skeleton ends at the foot.",
        ),
    ),
    "cmu_bvh": SourceSkeleton(
        name="cmu_bvh",
        description=(
            "CMU Graphics Lab mocap in the widely mirrored BVH conversion "
            "(cgspeed and friends). Free, enormous, and unevenly clean."
        ),
        bones=_humanoid(
            hips="Hips",
            spine=("LowerBack", "Spine", "Spine1"),
            neck="Neck",
            head="Head",
            shoulder="Shoulder",
            upper_arm="Arm",
            forearm="ForeArm",
            hand="Hand",
            thigh="UpLeg",
            shin="Leg",
            foot="Foot",
            toe="ToeBase",
            left="Left{}",
            right="Right{}",
        ),
        notes=(
            "Inch-scale in most conversions; check the hip height before "
            "trusting root translation.",
            "Carries extra LHipJoint / LowerBack style helper bones that no "
            "slot maps to. Harmless — unmapped source bones are ignored.",
        ),
    ),
    "ue5_mannequin": SourceSkeleton(
        name="ue5_mannequin",
        description=(
            "Unreal's SK_Mannequin / Manny skeleton, which most marketplace "
            "and MetaHuman-adjacent animation ships against."
        ),
        bones=_humanoid(
            hips="pelvis",
            spine=("spine_01", "spine_02", "spine_03"),
            neck="neck_01",
            head="head",
            shoulder="clavicle",
            upper_arm="upperarm",
            forearm="lowerarm",
            hand="hand",
            thigh="thigh",
            shin="calf",
            foot="foot",
            toe="ball",
            left="{}_l",
            right="{}_r",
        ),
        notes=(
            "Centimetre-scale and Z-up; Blender's FBX importer converts on "
            "the way in, so retarget in metres as usual.",
            "A 'root' bone sits under the pelvis. Leave it unmapped and let "
            "root translation come from the hips.",
        ),
    ),
    "smplx": SourceSkeleton(
        name="smplx",
        description=(
            "SMPL / SMPL-X joint naming, which most motion-research code and "
            "AMASS-derived datasets emit."
        ),
        bones=_humanoid(
            hips="pelvis",
            spine=("spine1", "spine2", "spine3"),
            neck="neck",
            head="head",
            shoulder="collar",
            upper_arm="shoulder",
            forearm="elbow",
            hand="wrist",
            thigh="hip",
            shin="knee",
            foot="ankle",
            toe="foot",
            left="left_{}",
            right="right_{}",
        ),
        notes=(
            "The names are off by one against every other convention here: "
            "SMPL's 'left_shoulder' is the upper arm and 'left_foot' is the "
            "toe. The slot table already accounts for that.",
        ),
    ),
}


def _normalise(name: str) -> str:
    """Lowercase, strip Mixamo prefixes, keep alphanumerics only."""
    text = name.strip().lower()
    for prefix in ("mixamorig:", "mixamorig1:", "mixamorig_"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return "".join(ch for ch in text if ch.isalnum())


def identify_source_skeleton(
    bone_names: Iterable[str],
) -> tuple[str | None, float]:
    """Match bone names to a known library; score = slots found / slots known."""
    present = {_normalise(name) for name in bone_names}
    if not present:
        return None, 0.0
    best_name, best_score = None, 0.0
    for profile in SOURCE_SKELETONS.values():
        wanted = {_normalise(bone) for bone in profile.bones.values()}
        score = len(wanted & present) / len(wanted)
        if score > best_score:
            best_name, best_score = profile.name, score
    if best_score < 0.6:
        return None, round(best_score, 3)
    return best_name, round(best_score, 3)


def read_bvh_bone_names(path: str | Path) -> list[str]:
    """Bone names from the BVH hierarchy (stops at ``MOTION``)."""
    names: list[str] = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            token = line.split()
            if not token:
                continue
            head = token[0].upper()
            if head == "MOTION":
                break
            if head in {"ROOT", "JOINT"} and len(token) > 1:
                names.append(token[1])
    return names


def identify_motion_file(path: str | Path) -> dict:
    """Identify a clip's source skeleton, as far as the format allows."""
    motion = Path(path)
    suffix = motion.suffix.lower()
    if suffix != ".bvh":
        return {
            "path": str(motion),
            "format": suffix.lstrip("."),
            "skeleton": None,
            "confidence": 0.0,
            "bone_count": None,
            "reason": (
                "Only BVH can be read without Blender. Derive the mapping "
                "with mapping_auto, which reads the FBX in a bpy subprocess."
            ),
        }
    bones = read_bvh_bone_names(motion)
    name, confidence = identify_source_skeleton(bones)
    return {
        "path": str(motion),
        "format": "bvh",
        "skeleton": name,
        "confidence": confidence,
        "bone_count": len(bones),
        "reason": (
            None
            if name
            else "No known profile matched; mapping_auto will derive one."
        ),
    }


def normalise_mapping(data: dict) -> dict:
    """Rename legacy keys (``mixamo``/``src`` → ``source``) on load."""
    result = dict(data)
    roots = dict(result.get("root_bones") or {})
    if "source" not in roots:
        for legacy in ("mixamo", "src"):
            if legacy in roots:
                roots["source"] = roots.pop(legacy)
                break
    if "puppeteer" not in roots and "target" in roots:
        roots["puppeteer"] = roots["target"]
    if roots:
        result["root_bones"] = roots

    chains = {}
    for chain_name, chain in (result.get("retarget_chains") or {}).items():
        chain = dict(chain)
        if "source" not in chain:
            for legacy in ("mixamo", "src"):
                if legacy in chain:
                    chain["source"] = chain.pop(legacy)
                    break
        chains[chain_name] = chain
    if chains:
        result["retarget_chains"] = chains
    return result


def read_rig_joint_names(rig_path: str | Path) -> list[str]:
    """Joint names from a Puppeteer ``.txt`` rig, without Blender."""
    names = []
    with open(rig_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            token = line.split()
            if len(token) >= 2 and token[0] == "joints":
                names.append(token[1])
    return names


def registry() -> dict:
    """Source-skeleton registry as plain data (agent / report)."""
    return {
        "source_skeletons": [
            profile.as_dict() for profile in SOURCE_SKELETONS.values()
        ],
        "default_strategy": (
            "Derive with mapping_auto, or pass mapping_path for a one-off. "
            "Source skeleton profiles describe the clip side only."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the registry as JSON.",
    )
    parser.add_argument(
        "--identify",
        default=None,
        help="Name the source skeleton of a BVH clip.",
    )
    args = parser.parse_args()

    if args.identify:
        payload = identify_motion_file(args.identify)
    else:
        payload = registry()
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()


__all__ = [
    "SLOTS",
    "SOURCE_SKELETONS",
    "SourceSkeleton",
    "identify_motion_file",
    "identify_source_skeleton",
    "normalise_mapping",
    "read_bvh_bone_names",
    "read_rig_joint_names",
    "registry",
]
