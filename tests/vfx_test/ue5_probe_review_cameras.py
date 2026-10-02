"""Report CineCamera spawnable templates used by the UE VFX review sequences."""
from __future__ import annotations

import unreal

from ue5_test_paths import content_path


SEQUENCES = (
    content_path("Preview/seq_NS_Fire"),
    content_path("Preview/seq_NS_Smoke_Plume"),
    content_path("Sequences/seq_sp_ink_full_c0"),
    content_path("Sequences/seq_sp_ice_full_c0"),
    content_path("Sequences/seq_sp_cyber_full_c0"),
    content_path("Sequences/seq_punch_fire_review_c0"),
)


def describe_camera(binding: unreal.MovieSceneBindingProxy) -> str | None:
    if not hasattr(binding, "get_object_template"):
        return None
    template = binding.get_object_template()
    if template is None or not isinstance(template, unreal.CineCameraActor):
        return None
    location = template.get_actor_location()
    rotation = template.get_actor_rotation()
    component = template.get_editor_property("camera_component")
    if component is None:
        components = template.get_components_by_class(unreal.CineCameraComponent)
        component = components[0] if components else None
    focal_length = (
        component.get_editor_property("current_focal_length")
        if component is not None
        else float("nan")
    )
    relative_location = (
        component.get_editor_property("relative_location")
        if component is not None
        else unreal.Vector()
    )
    relative_rotation = (
        component.get_editor_property("relative_rotation")
        if component is not None
        else unreal.Rotator()
    )
    track_summary = []
    for track in binding.get_tracks():
        for section in track.get_sections():
            values = []
            for channel in section.get_all_channels():
                keys = channel.get_keys()
                values.append(keys[0].get_value() if keys else channel.get_default())
            track_summary.append(f"{track.get_class().get_name()}={values}")
    return (
        f"binding={binding.get_name()} "
        f"location=({location.x:.3f},{location.y:.3f},{location.z:.3f}) "
        f"rotation=({rotation.pitch:.3f},{rotation.yaw:.3f},{rotation.roll:.3f}) "
        f"relative_location=({relative_location.x:.3f},{relative_location.y:.3f},"
        f"{relative_location.z:.3f}) "
        f"relative_rotation=({relative_rotation.pitch:.3f},{relative_rotation.yaw:.3f},"
        f"{relative_rotation.roll:.3f}) "
        f"focal_length={focal_length:.3f} tracks={track_summary}"
    )


def main() -> None:
    failed = False
    for path in SEQUENCES:
        sequence = unreal.EditorAssetLibrary.load_asset(path)
        if sequence is None:
            unreal.log_error(f"[AAAGF_CAMERA_PROBE] missing {path}")
            failed = True
            continue
        cameras = [
            description
            for binding in sequence.get_spawnables()
            if (description := describe_camera(binding)) is not None
        ]
        if not cameras:
            unreal.log_error(f"[AAAGF_CAMERA_PROBE] no CineCamera spawnable in {path}")
            failed = True
            continue
        for description in cameras:
            unreal.log(f"[AAAGF_CAMERA_PROBE] {path} {description}")
    if failed:
        raise RuntimeError("one or more review sequence cameras could not be inspected")


main()
