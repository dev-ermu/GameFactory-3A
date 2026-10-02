"""Unreal Editor integration smoke test for the reusable VFX functions."""
from __future__ import annotations

import sys
from pathlib import Path

import unreal

from ue5_test_paths import content_path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from engine_adapters.ue5.vfx import (  # noqa: E402
    spawn_dust,
    spawn_explosion,
    spawn_fire,
    spawn_smoke,
    spawn_styled_effect,
    stop_effect,
)


REVIEW_ASSETS = (
    content_path("Sequences/seq_sp_ink_full_c0"),
    content_path("Sequences/seq_sp_ice_full_c0"),
    content_path("Sequences/seq_sp_cyber_full_c0"),
    content_path("Sequences/seq_punch_fire_review_c0"),
    content_path("Review/MRQ_PunchFire768"),
)


def main() -> None:
    actors = []
    try:
        actors.append(spawn_fire((0, 0, -10000), auto_activate=False))
        actors.append(spawn_smoke((0, 0, -10000), auto_activate=False))
        actors.append(spawn_explosion((0, 0, -10000), auto_activate=False))
        actors.append(spawn_dust((0, 0, -10000), auto_activate=False))
        for style in ("ink", "frost", "cyber"):
            actors.append(spawn_styled_effect(
                "fire", style, (0, 0, -10000), auto_activate=False
            ))
        missing = [
            path for path in REVIEW_ASSETS
            if unreal.EditorAssetLibrary.load_asset(path) is None
        ]
        if missing:
            raise RuntimeError(f"review assets failed to load: {missing}")
        unreal.log(
            "[AAAGF_VFX_TEST] PASS: four natural and three stylized VFX "
            "templates spawned; review sequences/config loaded"
        )
    finally:
        for actor in actors:
            stop_effect(actor, destroy=True)


main()
