"""Tighten framing for the six UE VFX review Level Sequences."""
from __future__ import annotations

import unreal

from ue5_test_paths import content_path


CAMERAS = {
    content_path("Preview/seq_NS_Fire"): (
        unreal.Vector(170.0, 108.0, 120.0),
        unreal.Vector(0.0, 0.0, 100.0),
    ),
    content_path("Preview/seq_NS_Smoke_Plume"): (
        unreal.Vector(200.0, 127.0, 128.0),
        unreal.Vector(0.0, 0.0, 110.0),
    ),
    content_path("Sequences/seq_sp_ink_full_c0"): (
        unreal.Vector(235.0, 0.0, 105.0),
        unreal.Vector(0.0, 0.0, 70.0),
    ),
    content_path("Sequences/seq_sp_ice_full_c0"): (
        unreal.Vector(235.0, 0.0, 105.0),
        unreal.Vector(0.0, 0.0, 70.0),
    ),
    content_path("Sequences/seq_sp_cyber_full_c0"): (
        unreal.Vector(235.0, 0.0, 105.0),
        unreal.Vector(0.0, 0.0, 70.0),
    ),
    content_path("Sequences/seq_punch_fire_review_c0"): (
        unreal.Vector(0.0, 420.0, 140.0),
        unreal.Vector(0.0, 0.0, 80.0),
    ),
}


def find_camera_binding(sequence: unreal.LevelSequence) -> unreal.MovieSceneBindingProxy:
    cameras = []
    for binding in sequence.get_spawnables():
        template = binding.get_object_template()
        if template is not None and isinstance(template, unreal.CineCameraActor):
            cameras.append(binding)
    if len(cameras) != 1:
        raise RuntimeError(
            f"expected one CineCamera spawnable in {sequence.get_path_name()}, "
            f"found {len(cameras)}"
        )
    return cameras[0]


def set_camera_transform(
    sequence: unreal.LevelSequence,
    binding: unreal.MovieSceneBindingProxy,
    location: unreal.Vector,
    target: unreal.Vector,
) -> unreal.Rotator:
    for track in list(binding.get_tracks()):
        if isinstance(track, unreal.MovieScene3DTransformTrack):
            binding.remove_track(track)

    track = binding.add_track(unreal.MovieScene3DTransformTrack)
    section = track.add_section()
    section.set_range(sequence.get_playback_start(), sequence.get_playback_end())
    channels = section.get_all_channels()
    rotation = unreal.MathLibrary.find_look_at_rotation(location, target)

    for index, value in enumerate((location.x, location.y, location.z)):
        channels[index].add_key(unreal.FrameNumber(0), float(value))
    for index, value in enumerate((rotation.roll, rotation.pitch, rotation.yaw)):
        channels[3 + index].add_key(unreal.FrameNumber(0), float(value))
    for index in (6, 7, 8):
        channels[index].add_key(unreal.FrameNumber(0), 1.0)
    return rotation


def main() -> None:
    loaded = {}
    for path in CAMERAS:
        sequence = unreal.EditorAssetLibrary.load_asset(path)
        if sequence is None:
            raise RuntimeError(f"missing review sequence: {path}")
        loaded[path] = (sequence, find_camera_binding(sequence))

    for path, (location, target) in CAMERAS.items():
        sequence, binding = loaded[path]
        rotation = set_camera_transform(sequence, binding, location, target)
        unreal.EditorAssetLibrary.save_asset(path)
        unreal.log(
            f"[AAAGF_CAMERA_TIGHTEN] {path} "
            f"location=({location.x:.1f},{location.y:.1f},{location.z:.1f}) "
            f"target=({target.x:.1f},{target.y:.1f},{target.z:.1f}) "
            f"rotation=({rotation.pitch:.2f},{rotation.yaw:.2f},{rotation.roll:.2f})"
        )


main()
