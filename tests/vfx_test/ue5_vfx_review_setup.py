"""Create deterministic MRQ configs for fire/smoke visual review renders."""
from __future__ import annotations

import os

import unreal

from ue5_test_paths import content_path


SOURCE_CONFIG = content_path("Preview/MRQ_Preview512")
CONFIG_DIR = content_path("Preview")
OUTPUT_ROOT = os.environ.get("AAAGF_VFX_REVIEW_ROOT", "").replace("\\", "/")

CASES = {
    "fire": content_path("Preview/seq_NS_Fire"),
    "smoke": content_path("Preview/seq_NS_Smoke_Plume"),
}


def build_config(kind: str) -> str:
    source = unreal.EditorAssetLibrary.load_asset(SOURCE_CONFIG)
    if source is None:
        raise RuntimeError(f"missing source MRQ config: {SOURCE_CONFIG}")
    if unreal.EditorAssetLibrary.load_asset(CASES[kind]) is None:
        raise RuntimeError(f"missing review sequence: {CASES[kind]}")

    name = f"MRQ_AAAGF_{kind.title()}512"
    path = f"{CONFIG_DIR}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        unreal.EditorAssetLibrary.delete_asset(path)
    if not unreal.EditorAssetLibrary.duplicate_asset(SOURCE_CONFIG, path):
        raise RuntimeError(f"failed to duplicate MRQ config: {path}")

    config = unreal.EditorAssetLibrary.load_asset(path)
    output = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    output.output_directory = unreal.DirectoryPath(f"{OUTPUT_ROOT}/{kind}")
    output.file_name_format = "{frame_number}"
    output.output_resolution = unreal.IntPoint(512, 512)
    output.output_frame_rate = unreal.FrameRate(30, 1)
    unreal.EditorAssetLibrary.save_asset(path)
    return path


def main() -> None:
    if not OUTPUT_ROOT:
        raise RuntimeError("AAAGF_VFX_REVIEW_ROOT is required")
    configs = {kind: build_config(kind) for kind in CASES}
    unreal.log(f"[AAAGF_VFX_REVIEW] PASS: {configs}")


main()
