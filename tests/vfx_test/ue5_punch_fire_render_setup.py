"""Create an isolated MRQ preset for the A3Game punch/fire review."""
from __future__ import annotations

import os

import unreal

from ue5_test_paths import content_path


SOURCE_CONFIG = content_path("Preview/MRQ_Preview768")
DEST_CONFIG = content_path("Review/MRQ_PunchFire768")
OUTPUT_DIR = os.environ.get("AAAGF_PUNCH_FIRE_OUTPUT_DIR", "")


def main() -> None:
    if not OUTPUT_DIR:
        raise RuntimeError("AAAGF_PUNCH_FIRE_OUTPUT_DIR is required")
    if unreal.EditorAssetLibrary.does_asset_exist(DEST_CONFIG):
        unreal.EditorAssetLibrary.delete_asset(DEST_CONFIG)
    if not unreal.EditorAssetLibrary.duplicate_asset(SOURCE_CONFIG, DEST_CONFIG):
        raise RuntimeError(f"could not duplicate MRQ config: {SOURCE_CONFIG}")

    config = unreal.EditorAssetLibrary.load_asset(DEST_CONFIG)
    if config is None:
        raise RuntimeError(f"could not load duplicated MRQ config: {DEST_CONFIG}")
    output = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    output.output_directory = unreal.DirectoryPath(OUTPUT_DIR)
    output.file_name_format = "{frame_number}"
    output.output_resolution = unreal.IntPoint(768, 768)
    output.output_frame_rate = unreal.FrameRate(30, 1)
    output.zero_pad_frame_numbers = 4
    unreal.EditorAssetLibrary.save_loaded_asset(config)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    unreal.log(f"[AAAGF_PUNCH_FIRE] MRQ ready: {DEST_CONFIG} -> {OUTPUT_DIR}")


main()
