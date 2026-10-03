"""Download the freely licensed glTF pack, when generating is overkill.

three.js ships no models, so a game with no generated art has nothing to
show. Three CC0 files cover that case, cost nothing, and arrive in
seconds — which is the entire reason this exists next to a16 GB
generative model.

Kept deliberately small: a list of URLs, a cache, and one function. Each
entry declares the two facts glTF cannot carry, both established by
rendering the model and looking at it (see
``agent_skills/asset_qa/imported_asset_orientation.md``):

* ``forward_axis`` — all three face **+Z** while the runtime treats -Z as
  forward, so all three need a 180° correction;
* ``height_metres`` — the Fox is authored 79 units tall and the ToyCar at
  1/10000 scale, so "as authored" is never a usable size.

Rejected after checking, because the reasoning is the reusable part:
DamagedHelmet (CC BY-NC), Duck (SCEA), Sponza (CryEngine) and the
Mixamo-derived characters on licence; Lantern (9.2 MB) and AntiqueCamera
(17 MB) on cost, being PBR showcase pieces with 4K atlases.
"""

import urllib.request
from pathlib import Path
from typing import Any, Iterable

from pipeline.common import paths

from .asset_import import import_asset, stage_task_output

_THREE = "https://raw.githubusercontent.com/mrdoob/three.js/dev/examples/models"
_KHRONOS = (
    "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets"
    "/main/Models"
)

#: asset_id -> everything needed to fetch, place and orient one model.
ASSET_PACK: dict[str, dict[str, Any]] = {
    "robot_expressive": {
        "url": f"{_THREE}/gltf/RobotExpressive/RobotExpressive.glb",
        "asset_type": "avatar",
        "forward_axis": "+z",
        "height_metres": 1.8,
        "licence": "CC0-1.0",
        "attribution": (
            "Robot Expressive by Tomas Laulhe (quaternius), CC0 1.0; "
            "modifications by Don McCurdy."
        ),
        "notes": "Eyes and visor on the +Z side.456 KB, 14 clips.",
        "games": (
            "game_fps_pistol_arena",
            "game_sidescroll_brawler",
            "game_archer_explorer",
        ),
    },
    "fox": {
        "url": f"{_KHRONOS}/Fox/glTF-Binary/Fox.glb",
        "asset_type": "prop",
        "forward_axis": "+z",
        "height_metres": 0.5,
        "licence": "CC0-1.0 (model), CC-BY-4.0 (rig and animation)",
        "attribution": (
            "Fox by PixelMannen, CC0 1.0; rig and animation by tomkranis, "
            "CC BY 4.0; glTF conversion by @AsoboStudio and @scurest, "
            "CC BY 4.0."
        ),
        "notes": "Snout points +Z, brush -Z. Authored 79 units tall.",
        "games": ("game_archer_explorer",),
    },
    "toy_car": {
        "url": f"{_KHRONOS}/ToyCar/glTF-Binary/ToyCar.glb",
        "asset_type": "prop",
        "forward_axis": "+z",
        "height_metres": 1.4,
        "licence": "CC0-1.0",
        "attribution": "Toy Car, public domain (CC0 1.0), Khronos Group.",
        "notes": (
            "Bonnet faces +Z. Scenery, not a drivable car: body and wheels "
            "are one fused mesh, so nothing can steer or spin."
        ),
        "games": ("game_arcade_racer",),
    },
}

CACHE_DIR = paths.OUTPUT_ROOT.parent / ".asset_cache"


def download(asset_id: str, cache_dir: Path | None = None) -> Path:
    """Fetch one pack file into the cache, or reuse what is there."""

    entry = ASSET_PACK[asset_id]
    directory = Path(cache_dir or CACHE_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / entry["url"].rsplit("/", 1)[-1]
    if target.is_file() and target.stat().st_size > 0:
        return target
    request = urllib.request.Request(
        entry["url"], headers={"User-Agent": "3AGameFactory/1.0"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()
    target.write_bytes(payload)
    return target


def fetch_asset_pack(
    games: Iterable[str] = (),
    assets: Iterable[str] = (),
    *,
    run_id: str = paths.DEFAULT_RUN_ID,
    import_into_project: bool = True,
) -> list[dict[str, Any]]:
    """Download the pack and stage it into each game that uses it."""

    wanted_games = set(games)
    wanted_assets = set(assets)
    results: list[dict[str, Any]] = []
    for asset_id, entry in ASSET_PACK.items():
        if wanted_assets and asset_id not in wanted_assets:
            continue
        targets = [
            game
            for game in entry["games"]
            if not wanted_games or game in wanted_games
        ]
        if not targets:
            continue
        source = download(asset_id)
        for game_id in targets:
            task_id = f"asset-{asset_id.replace('_', '-')}"
            staged = stage_task_output(
                game_id,
                task_id,
                source,
                run_id=run_id,
                meta={
                    "asset_id": asset_id,
                    "asset_type": entry["asset_type"],
                    "source_url": entry["url"],
                    "licence": entry["licence"],
                    "attribution": entry["attribution"],
                    "forward_axis": entry["forward_axis"],
                    "scale_hint_metres": entry["height_metres"],
                    "notes": entry["notes"],
                },
            )
            record = {"asset_id": asset_id, **staged}
            if import_into_project:
                record.update(
                    import_asset(
                        game_id,
                        task_id,
                        asset_id=asset_id,
                        asset_type=entry["asset_type"],
                        run_id=run_id,
                        forward_axis=entry["forward_axis"],
                        scale_hint_metres=entry["height_metres"],
                        verified_by="agent_vision",
                        notes=entry["notes"],
                        preview=False,
                    )
                )
            results.append(record)
    return results
