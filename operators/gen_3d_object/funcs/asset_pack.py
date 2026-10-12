"""Take a CC0 mesh from the Khronos sample library instead of generating one.

Generation is the right answer when an asset has to match a concept, and the
wrong answer when it does not: a shipping crate, a rigged mannequin, a
calibration target. Those are solved problems with published CC0 models, and a
billed image-to-3D call re-derives them worse and slower than a download.

Every file fetched here comes from `KhronosGroup/glTF-Sample-Assets`, which is
CC0 and engine-neutral. Nothing here touches an engine: the model lands in the
task output directory as an ordinary artifact with a `meta.json` beside it, so
whatever imports it later is a separate decision.

Downloads are cached under `outputs/runs/_asset_pack_cache/` by asset id,
so a re-run costs no network and cannot drift: the bytes that passed QA once are
the bytes every later run sees.
"""

from __future__ import annotations

import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from pipeline.common import paths

#: Registered task kind - keys into paths.TASK_* tables.
TASK_KIND = "3d_object"

#: Base for every asset URL. Khronos maintains the glTF sample library and
#: ships it CC0, which is the point: a generated asset has licence questions,
#: a downloaded one has none.
_KHRONOS = (
    "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets"
    "/main/Models"
)

#: Cache root. Under outputs/ rather than a user-level cache directory so a
#: deleted checkout does not leave hundreds of megabytes behind.
CACHE_ROOT = paths.OUTPUT_ROOT / "_asset_pack_cache"

#: Seconds before a download is abandoned. The files are tens of megabytes, so
#: this is generous on purpose - a slow link should not look like a broken one.
DOWNLOAD_TIMEOUT = 120

#: asset_id -> one entry per published model.
#:
#: `asset_type` is what a consumer asks for, not what the file happens to be:
#: a caller saying "avatar" wants something it can put a skeleton on, and the
#: library has exactly one entry that qualifies.
ASSET_PACK: dict[str, dict[str, Any]] = {
    "box": {
        "asset_type": "prop",
        "file": "Box/glTF-Binary/Box.glb",
        "description": "Unit cube, textured. The cheapest sanity check there is.",
        "triangles": 12,
    },
    "box_textured": {
        "asset_type": "prop",
        "file": "BoxTextured/glTF-Binary/BoxTextured.glb",
        "description": "Cube with a baked texture; useful when UVs matter.",
        "triangles": 12,
    },
    "lantern": {
        "asset_type": "prop",
        "file": "Lantern/glTF-Binary/Lantern.glb",
        "description": "Detailed hard-surface prop with metal and glass.",
        "triangles": 756,
    },
    "duck": {
        "asset_type": "creature",
        "file": "Duck/glTF-Binary/Duck.glb",
        "description": "Textured low-poly bird; small, and not a box.",
        "triangles": 4212,
    },
    "damaged_helmet": {
        "asset_type": "prop",
        "file": "DamagedHelmet/glTF-Binary/DamagedHelmet.glb",
        "description": "PBR hard-surface hero prop; the best normal-map test.",
        "triangles": 25232,
    },
    "avocado": {
        "asset_type": "prop",
        "file": "Avocado/glTF-Binary/Avocado.glb",
        "description": "Organic curved surface; catches smoothing errors.",
        "triangles": 686,
    },
    "xbot": {
        "asset_type": "avatar",
        "file": "Xbot/glTF-Binary/Xbot.glb",
        "description": "Rigged humanoid in a neutral pose. Rig-and-skin test.",
        "triangles": 3896,
        "skeleton": True,
    },
    "robot_expressive": {
        "asset_type": "avatar",
        "file": "RobotExpressive/glTF-Binary/RobotExpressive.glb",
        "description": "Rigged robot with blend shapes; tests morph targets.",
        "triangles": 23358,
        "skeleton": True,
    },
}


def asset_url(asset_id: str) -> str:
    """Absolute download URL for one pack entry."""
    return f"{_KHRONOS}/{ASSET_PACK[asset_id]['file']}"


def _cache_path(asset_id: str) -> Path:
    """Where this entry is cached on disk."""
    return CACHE_ROOT / f"{asset_id}.glb"


def download(asset_id: str, *, offline: bool = False) -> Path:
    """Return the local path of one pack entry, fetching it if needed.

    Raises KeyError on an unknown id, FileNotFoundError when `offline=True`
    and nothing is cached, and RuntimeError when the fetch fails.
    """
    if asset_id not in ASSET_PACK:
        raise KeyError(f"unknown asset_id {asset_id!r}; known: {sorted(ASSET_PACK)}")

    target = _cache_path(asset_id)
    if target.is_file() and target.stat().st_size > 0:
        return target

    if offline:
        raise FileNotFoundError(
            f"{asset_id} is not cached at {target} and offline=True was "
            "requested; run once online to populate the cache"
        )

    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    url = asset_url(asset_id)
    partial = target.with_suffix(".glb.part")

    try:
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response:
            with open(partial, "wb") as handle:
                shutil.copyfileobj(response, handle)
    except urllib.error.URLError as exc:
        # A half-written file is worse than none: the next run would find it,
        # see a non-zero size, and treat a truncated mesh as a cached good one.
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"failed to download {asset_id} from {url}: {exc}. Check network "
            f"access, or pre-populate {CACHE_ROOT} for an offline run."
        ) from exc

    if partial.stat().st_size == 0:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"{url} returned an empty body for {asset_id}")

    # Rename only after the body is complete, so the cache never holds a
    # partial file under the name callers trust.
    partial.replace(target)
    return target

def stage_asset(
    asset_id: str,
    *,
    game_id: str,
    task_id: str,
    run_id: str = paths.DEFAULT_RUN_ID,
    offline: bool = False,
) -> dict[str, Any]:
    """Write one pack entry into a task output directory.

    The result is an ordinary task artifact: a ``.glb`` plus a ``meta.json``
    beside it, in the same layout every other `3d_object` task produces. No
    engine is contacted, so the same call works whatever the target is.

    Args:
        asset_id: Key of `ASSET_PACK`.
        game_id: Game project the asset belongs to.
        task_id: Names the output directory.
        run_id: Generation run this belongs to.
        offline: Fail instead of fetching (see `download`).

    Returns:
        The written `meta.json` contents, including the final `glb_path`.
    """
    entry = ASSET_PACK[asset_id]
    source = download(asset_id, offline=offline)

    task_dir = paths.task_output_dir(game_id, TASK_KIND, task_id, run_id=run_id)
    staged = task_dir / source.name
    if staged.resolve() != source.resolve():
        shutil.copyfile(source, staged)

    meta = {
        "game_id": game_id,
        "run_id": run_id,
        "task_kind": TASK_KIND,
        "task_id": task_id,
        "glb_path": staged.name,
        "bytes": staged.stat().st_size,
        "source": "asset_pack",
        "asset_id": asset_id,
        "asset_type": entry["asset_type"],
        "description": entry["description"],
        "triangles": entry["triangles"],
        "skeleton": bool(entry.get("skeleton", False)),
        "licence": "CC0 (Khronos glTF-Sample-Assets)",
        "upstream": asset_url(asset_id),
        "cached_from": str(source),
    }
    paths.write_task_meta(task_dir, meta)
    return meta


def fetch_asset_pack(
    *,
    game_id: str,
    asset_ids: tuple[str, ...] = ("box", "duck"),
    task_id_prefix: str = "asset",
    run_id: str = paths.DEFAULT_RUN_ID,
    offline: bool = False,
) -> list[dict[str, Any]]:
    """Stage several pack entries as sibling tasks under one game.

    Args:
        game_id: Game project the assets belong to.
        asset_ids: Keys of `ASSET_PACK`, in the order they should be staged.
        task_id_prefix: Prepended to each asset id to form the task id, so the
            same asset fetched in two runs stays distinguishable.
        run_id: Generation run this belongs to.
        offline: Fail instead of fetching (see `download`).

    Returns:
        One meta dict per staged asset.
    """
    unknown = [a for a in asset_ids if a not in ASSET_PACK]
    if unknown:
        raise KeyError(f"unknown asset ids {unknown}; known: {sorted(ASSET_PACK)}")

    return [
        stage_asset(
            asset_id,
            game_id=game_id,
            task_id=f"{task_id_prefix}_{asset_id}",
            run_id=run_id,
            offline=offline,
        )
        for asset_id in asset_ids
    ]


def describe_pack() -> list[dict[str, Any]]:
    """Summarise the pack for an agent choosing what to fetch."""
    return [
        {
            "asset_id": asset_id,
            "asset_type": entry["asset_type"],
            "description": entry["description"],
            "triangles": entry["triangles"],
            "skeleton": bool(entry.get("skeleton", False)),
            "cached": _cache_path(asset_id).is_file(),
        }
        for asset_id, entry in ASSET_PACK.items()
    ]