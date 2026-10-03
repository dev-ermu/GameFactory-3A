"""Fetch the *environment* half of a scene: sky, IBL, ground, and VFX sprites.

``gen_3d_scene`` used to produce geometry and nothing else, which is why
every generated world looked like grey boxes under a flat blue clear
colour. A scene reads as real for three reasons, and only one of them is
geometry:

1. **Image-based lighting.** Without an environment map a PBR material
   has nothing to reflect and every surface reads as matte plastic. This
   is the single largest quality gap in a generated three.js scene.
2. **A sky that is not a colour.** ``scene.background = 0x87ceeb`` is the
   tell-tale of a generated game. An equirectangular photograph or HDRI
   costs one texture and fixes it.
3. **Surface texture.** A 200 m ground plane with a solid albedo has no
   scale cue, so the player cannot tell they are moving.

None of the three needs a generative model — they need *files*, and
three.js already ships a curated set of them under a permissive licence.
So this module is a catalogue, a cache, and a staging function, in the
same shape as ``operators/gen_3d_object/funcs/asset_pack.py`` and for the
same reason: the reusable part is the vetting, not the download.

Licence vetting (the part worth keeping)
----------------------------------------
* The ``equirectangular/*.hdr`` files in the three.js repository come
  from Poly Haven and are **CC0** — usable with no attribution.
* ``2294472375_24a3b8ef46_o.jpg`` is the public-domain sky photograph
  three.js uses in its own equirectangular examples.
* ``terrain/grasslight-big.jpg``, ``waternormals.jpg``,
  ``brick_diffuse.jpg``, ``disturb.jpg``, ``noise.png`` and the
  ``sprites/`` set ship under the three.js MIT licence.
* ``LittlestTokyo.glb`` is **CC-BY-4.0** and therefore carries a
  mandatory attribution string, recorded in the manifest entry so the
  game can display it. Anything more restrictive was rejected:
  DamagedHelmet (CC BY-NC), Duck (SCEA), Sponza (CryEngine).

Everything is staged straight into a game project's ``public/assets``
tree and registered in ``manifest.json``, because
``A3GameAssetLibrary`` already knows how to load ``hdr``, ``jpeg`` and
``png`` representations — the only thing it was missing was entries.

Usage::

    from operators.gen_3d_scene.funcs import scene_assets

    scene_assets.fetch_scene_assets()                    # all four games
    scene_assets.fetch_scene_assets(games=["game_archer_explorer"])
"""

import hashlib
import json
import shutil
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Sequence

# ── upstreams ────────────────────────────────────────────────────────────────

#: Pinned to a tag rather than ``dev``: an environment map that silently
#: changes shape between runs is a rendering bug that looks like a code bug.
_THREE_TAG = "r180"
_THREE = (
    f"https://raw.githubusercontent.com/mrdoob/three.js/{_THREE_TAG}/examples"
)

_MIT = "MIT (three.js examples)"
_CC0 = "CC0-1.0"

#: The four games this repository generates. Kept explicit so a typo in a
#: game id fails loudly instead of silently staging nothing.
GAME_IDS: tuple[str, ...] = (
    "game_arcade_racer",
    "game_archer_explorer",
    "game_fps_pistol_arena",
    "game_sidescroll_brawler",
)


# ── catalogue ────────────────────────────────────────────────────────────────
#
# ``kind`` decides where the file lands and what manifest ``type`` and
# ``representation`` it gets:
#
#   environment -> public/assets/environments/  type=environment
#   texture     -> public/assets/textures/      type=texture
#   scene       -> public/assets/imported/scenes/ type=scene
#
# ``games`` is the default staging set; ``fetch_scene_assets`` narrows it.

SCENE_ASSETS: dict[str, dict[str, Any]] = {
    # ── image-based lighting ────────────────────────────────────────────
    "env_forest_sunrise": {
        "kind": "environment",
        "url": f"{_THREE}/textures/equirectangular/spruit_sunrise_1k.hdr",
        "licence": _CC0,
        "attribution": "Spruit Sunrise HDRI, Greg Zaal / Poly Haven, CC0.",
        "notes": (
            "Low sun through conifers. The reference IBL for the archer "
            "forest: warm rim light, cool sky fill, sun near the horizon "
            "so long shadows read correctly."
        ),
        "sun": {"elevation": 6.0, "azimuth": 160.0},
        "games": ("game_archer_explorer",),
    },
    "env_golden_sunset": {
        "kind": "environment",
        "url": f"{_THREE}/textures/equirectangular/venice_sunset_1k.hdr",
        "licence": _CC0,
        "attribution": "Venice Sunset HDRI, Greg Zaal / Poly Haven, CC0.",
        "notes": (
            "Open water at sunset. Wide unobstructed horizon and strong "
            "orange key — what an arcade racer wants, because specular "
            "streaks along a car body are the whole point of car paint."
        ),
        "sun": {"elevation": 4.0, "azimuth": 250.0},
        "games": ("game_arcade_racer",),
    },
    "env_stone_hall": {
        "kind": "environment",
        "url": f"{_THREE}/textures/equirectangular/royal_esplanade_1k.hdr",
        "licence": _CC0,
        "attribution": "Royal Esplanade HDRI, Andreas Mischok / Poly Haven, CC0.",
        "notes": (
            "Enclosed stone hall with skylights. Bright but bounded, so "
            "an arena keeps metal highlights without an outdoor sky "
            "leaking in above the walls."
        ),
        "games": ("game_fps_pistol_arena",),
    },
    "env_city_overpass": {
        "kind": "environment",
        "url": f"{_THREE}/textures/equirectangular/pedestrian_overpass_1k.hdr",
        "licence": _CC0,
        "attribution": (
            "Pedestrian Overpass HDRI, Andreas Mischok / Poly Haven, CC0."
        ),
        "notes": (
            "Overcast street under concrete. Flat top light and grey "
            "bounce, which is exactly the look a night-time brawler "
            "wants once its own lamp posts supply the contrast."
        ),
        "games": ("game_sidescroll_brawler",),
    },
    "env_quarry_noon": {
        "kind": "environment",
        "url": f"{_THREE}/textures/equirectangular/quarry_01_1k.hdr",
        "licence": _CC0,
        "attribution": "Quarry 01 HDRI, Greg Zaal / Poly Haven, CC0.",
        "notes": "Hard midday sun over rock. Kept as the neutral daylight option.",
        "games": (),
    },
    # ── sky backdrops (a picture, not a colour) ─────────────────────────
    "sky_equirect_day": {
        "kind": "texture",
        "url": f"{_THREE}/textures/2294472375_24a3b8ef46_o.jpg",
        "representation": "jpeg",
        "licence": "Public domain",
        "attribution": "Sky photograph, public domain, via three.js examples.",
        "notes": (
            "Equirectangular daytime sky with cumulus. Assign as "
            "`scene.background` with EquirectangularReflectionMapping to "
            "get clouds; the Sky shader alone never produces any."
        ),
        "games": GAME_IDS,
    },
    # ── surfaces ────────────────────────────────────────────────────────
    "tex_grass_ground": {
        "kind": "texture",
        "url": f"{_THREE}/textures/terrain/grasslight-big.jpg",
        "representation": "jpeg",
        "licence": _MIT,
        "attribution": "Grass terrain texture, three.js examples (MIT).",
        "notes": "Tiling grass albedo. Repeat 40-80x over a 200 m ground plane.",
        "games": ("game_archer_explorer",),
    },
    "tex_water_normals": {
        "kind": "texture",
        "url": f"{_THREE}/textures/waternormals.jpg",
        "representation": "jpeg",
        "licence": _MIT,
        "attribution": "Water normal map, three.js examples (MIT).",
        "notes": (
            "Tiling normal map. Two copies scrolling at different speeds "
            "and angles is the cheapest convincing water in three.js, and "
            "it needs no Water addon or render target."
        ),
        "games": ("game_archer_explorer",),
    },
    "tex_brick_wall": {
        "kind": "texture",
        "url": f"{_THREE}/textures/brick_diffuse.jpg",
        "representation": "jpeg",
        "licence": _MIT,
        "attribution": "Brick diffuse texture, three.js examples (MIT).",
        "notes": "Tiling brick albedo for arena and alley walls.",
        "games": ("game_fps_pistol_arena", "game_sidescroll_brawler"),
    },
    "tex_grain_noise": {
        "kind": "texture",
        "url": f"{_THREE}/textures/disturb.jpg",
        "representation": "jpeg",
        "licence": _MIT,
        "attribution": "Grain texture, three.js examples (MIT).",
        "notes": (
            "Greyscale grain. Used as a roughness/bump break-up layer so "
            "asphalt and stone stop reading as a single flat value."
        ),
        "games": GAME_IDS,
    },
    # ── VFX sprites ─────────────────────────────────────────────────────
    "spr_glow": {
        "kind": "texture",
        "url": f"{_THREE}/textures/sprites/circle.png",
        "representation": "png",
        "licence": _MIT,
        "attribution": "Circle sprite, three.js examples (MIT).",
        "notes": "Soft round alpha. Smoke, dust, magic motes, headlight bloom.",
        "games": GAME_IDS,
    },
    "spr_spark": {
        "kind": "texture",
        "url": f"{_THREE}/textures/sprites/spark1.png",
        "representation": "png",
        "licence": _MIT,
        "attribution": "Spark sprite, three.js examples (MIT).",
        "notes": "Hot four-point star. Tyre sparks, muzzle flash, arrow trail.",
        "games": GAME_IDS,
    },
    "spr_flare": {
        "kind": "texture",
        "url": f"{_THREE}/textures/lensflare/lensflare0.png",
        "representation": "png",
        "licence": _MIT,
        "attribution": "Lens flare sprite, three.js examples (MIT).",
        "notes": "Large soft flare. Sun sprite, boost flame core, lamp haze.",
        "games": GAME_IDS,
    },
    # ── open-source scene geometry ──────────────────────────────────────
    "scene_city_diorama": {
        "kind": "scene",
        "url": f"{_THREE}/models/gltf/LittlestTokyo.glb",
        "licence": "CC-BY-4.0",
        "attribution": (
            "Littlest Tokyo by Glen Fox, CC BY 4.0 "
            "(https://artstation.com/artwork/1AGwX)."
        ),
        "notes": (
            "Animated city diorama, 4.1 MB, authored ~250 units wide with "
            "its own animation clip. Attribution is MANDATORY under "
            "CC-BY-4.0 — display `attribution` in the credits HUD of any "
            "game that stages it. Scale to taste and park it behind the "
            "fog line; it is scenery, never collision."
        ),
        "forward_axis": "+z",
        "height_metres": 26.0,
        "games": (),
    },
}


# ── cache and download ───────────────────────────────────────────────────────

CACHE_DIR = (
    Path(__file__).resolve().parents[3] / "test_data" / ".scene_asset_cache"
)


def download(asset_id: str, cache_dir: Path | None = None) -> Path:
    """Fetch one catalogue file into the cache, or reuse what is there."""

    entry = SCENE_ASSETS[asset_id]
    directory = Path(cache_dir or CACHE_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / entry["url"].rsplit("/", 1)[-1]
    if target.is_file() and target.stat().st_size > 0:
        return target
    request = urllib.request.Request(
        entry["url"], headers={"User-Agent": "3AGameFactory/1.0"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = response.read()
    target.write_bytes(payload)
    return target


# ── project discovery and manifest surgery ───────────────────────────────────

OUTPUT_ROOT = Path(__file__).resolve().parents[3] / "test_data" / "outputs"

#: ``kind`` -> (public subdirectory, manifest ``type``).
_PLACEMENT: dict[str, tuple[str, str]] = {
    "environment": ("environments", "environment"),
    "texture": ("textures", "texture"),
    "scene": ("imported/scenes", "scene"),
}

_REPRESENTATION_BY_SUFFIX = {
    ".hdr": "hdr",
    ".exr": "exr",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".webp": "webp",
    ".glb": "gltf_binary",
    ".gltf": "gltf_binary",
}


def find_projects(
    game_id: str, output_root: Path | None = None
) -> list[Path]:
    """Every generated Vite project of one game, newest run last.

    Resolved by globbing rather than concatenating, because a game may
    have several runs and each holds its own ``public/assets``.
    """

    root = Path(output_root or OUTPUT_ROOT) / game_id
    return sorted(
        manifest.parent.parent.parent
        for manifest in root.glob("*/mechanic/*/public/assets/manifest.json")
    )


def _artifact_id(asset_id: str, url_path: str) -> str:
    digest = hashlib.sha1(url_path.encode("utf-8")).hexdigest()[:6]
    return f"web_file_{asset_id}_{digest}"


def stage(
    project_dir: Path,
    asset_id: str,
    *,
    cache_dir: Path | None = None,
    replace_existing: bool = True,
) -> dict[str, Any]:
    """Copy one catalogue file into a project and register it.

    Returns ``{asset_id, artifact_id, url, path, staged}``. Registering
    is a manifest rewrite rather than an adapter call because these are
    not task outputs: they are third-party files with a licence, and the
    licence is the thing that has to survive into the project.
    """

    entry = SCENE_ASSETS[asset_id]
    kind = entry["kind"]
    subdir, manifest_type = _PLACEMENT[kind]
    source = download(asset_id, cache_dir)

    assets_root = Path(project_dir) / "public" / "assets"
    destination = assets_root / subdir / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if replace_existing or not destination.is_file():
        shutil.copyfile(source, destination)

    url = "/assets/" + str(destination.relative_to(assets_root)).replace(
        "\\", "/"
    )
    representation = entry.get("representation") or _REPRESENTATION_BY_SUFFIX[
        source.suffix.lower()
    ]
    artifact_id = _artifact_id(asset_id, url)

    manifest_path = assets_root / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text("utf-8"))
        if manifest_path.is_file()
        else {
            "api_version": "v1",
            "assets": {},
            "backend": "web",
            "engine": "three_js",
            "manifest_version": 1,
        }
    )
    record: dict[str, Any] = {
        "animations": [],
        "artifact_id": artifact_id,
        "asset_id": asset_id,
        "attribution": entry["attribution"],
        "capabilities": {
            "animated": False,
            "collidable": False,
            "playable": False,
            "renderable": True,
            "skinned": False,
            "spawnable": kind == "scene",
        },
        "category": kind,
        "class": "Scene" if kind == "scene" else "Texture",
        "licence": entry["licence"],
        "notes": entry["notes"],
        "package_id": asset_id,
        "representation": representation,
        "source_url": entry["url"],
        "type": manifest_type,
        "url": url,
    }
    if entry.get("sun"):
        record["sun"] = dict(entry["sun"])
    if kind == "scene":
        record["orientation"] = {
            "forward_axis": entry.get("forward_axis", "+z"),
            "runtime_forward_axis": "-z",
            "runtime_yaw_degrees": 180.0,
            "scale_hint_metres": float(entry.get("height_metres") or 0) or None,
            "up_axis": "+y",
            "verified_by": "declared",
            "notes": entry["notes"],
        }
    manifest.setdefault("assets", {})[artifact_id] = record
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    return {
        "asset_id": asset_id,
        "artifact_id": artifact_id,
        "url": url,
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "licence": entry["licence"],
        "staged": True,
    }


def fetch_scene_assets(
    games: Iterable[str] = (),
    assets: Iterable[str] = (),
    *,
    output_root: Path | None = None,
    cache_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Download the catalogue and stage it into every matching project.

    ``games`` and ``assets`` both narrow the work; empty means "the
    catalogue default". Every generated project of a game is staged, not
    just the newest, because a stale run that still builds is a run
    somebody will open.
    """

    wanted_games = set(games)
    wanted_assets = set(assets)
    unknown = wanted_assets - set(SCENE_ASSETS)
    if unknown:
        raise KeyError(
            f"unknown scene assets {sorted(unknown)}; "
            f"catalogue has {sorted(SCENE_ASSETS)}"
        )
    unknown_games = wanted_games - set(GAME_IDS)
    if unknown_games:
        raise KeyError(
            f"unknown games {sorted(unknown_games)}; expected {list(GAME_IDS)}"
        )

    results: list[dict[str, Any]] = []
    for asset_id, entry in SCENE_ASSETS.items():
        if wanted_assets and asset_id not in wanted_assets:
            continue
        targets: Sequence[str] = [
            game
            for game in (entry["games"] or ())
            if not wanted_games or game in wanted_games
        ]
        # An explicitly requested asset is staged even when the catalogue
        # lists no default game for it — that is what makes the optional
        # entries (quarry HDRI, Tokyo diorama) reachable without an edit.
        if wanted_assets and wanted_games and not targets:
            targets = sorted(wanted_games)
        for game_id in targets:
            for project_dir in find_projects(game_id, output_root):
                record = stage(project_dir, asset_id, cache_dir=cache_dir)
                results.append(
                    {"game_id": game_id, "project": str(project_dir), **record}
                )
    return results


def attribution_lines(project_dir: Path) -> list[str]:
    """Attribution strings a staged project is required to display.

    CC-BY content is usable only while the credit travels with it, so the
    game needs a way to ask what it owes without re-reading the licence.
    """

    manifest_path = Path(project_dir) / "public" / "assets" / "manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = json.loads(manifest_path.read_text("utf-8"))
    lines = []
    for entry in manifest.get("assets", {}).values():
        licence = str(entry.get("licence") or "")
        if licence.upper().startswith("CC-BY") and entry.get("attribution"):
            lines.append(str(entry["attribution"]))
    return sorted(set(lines))


if __name__ == "__main__":  # pragma: no cover - operator convenience
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", nargs="*", default=[])
    parser.add_argument("--assets", nargs="*", default=[])
    options = parser.parse_args()
    for row in fetch_scene_assets(options.games, options.assets):
        print(
            f"{row['game_id']:<24} {row['asset_id']:<20} "
            f"{row['bytes'] / 1024:>8.0f} KB  {row['url']}"
        )
