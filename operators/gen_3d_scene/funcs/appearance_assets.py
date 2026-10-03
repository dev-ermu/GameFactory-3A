"""Re-generate a scene's props with an appearance-grade backend (Meshy / Tripo).

Why this exists
---------------
TRELLIS.2 reconstructs *a* shape from *one* view, and on a 512-pixel
synthetic reference that is exactly what it does: the silhouette is right
and everything the camera could not see is guessed. Rendered in-game the
guess reads as holes — a ranger missing the back of the hood, a pistol
whose slide dissolves into the grip, pine trees with a bite taken out of
the canopy. No amount of relighting fixes a mesh that is not closed.

Meshy and Tripo are text-to-3D services with a *multi-view* prior and a
texture pass. For "make this prop look good" they are strictly better and
cost cents, so appearance work belongs here rather than in a second
reconstruction pass.

What it does **not** do
-----------------------
It does not invent new gameplay assets and it does not rename anything.
Every entry re-generates an ``asset_id`` a game already references, so the
game code needs no change to benefit — except for the three genuinely new
ids (``explorer_sword``, ``racer_car_body``, ``racer_wheel``), which exist
because a fused vehicle mesh cannot steer or spin and the fix is to ship
the shell and the moving part as separate assets.

The two facts glTF cannot carry are declared per entry, same as
``asset_pack.py``: ``forward_axis`` and ``height_metres``. A generated
mesh arrives normalised into a unit box, so without the second one every
prop is one metre tall.

Usage::

    from operators.gen_3d_scene.funcs import appearance_assets

    appearance_assets.upgrade_appearance()                  # everything
    appearance_assets.upgrade_appearance(
        assets=["arena_pistol"], provider="meshy")

    python -m operators.gen_3d_scene.funcs.appearance_assets \
        --games game_arcade_racer --workers 4

Credentials: ``MESHY_API_KEY`` or ``TRIPO_API_KEY``, read at the first
call. Nothing here spends a credit twice — the wrappers' own response
cache is pointed at ``test_data/.appearance_cache``, so a re-run with an
unchanged prompt is free.
"""

import concurrent.futures
import io
import json
import logging
import shutil
import struct
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = REPO_ROOT / "test_data" / "outputs"
CACHE_DIR = REPO_ROOT / "test_data" / ".appearance_cache"

GAME_IDS: tuple[str, ...] = (
    "game_arcade_racer",
    "game_archer_explorer",
    "game_fps_pistol_arena",
    "game_sidescroll_brawler",
)

#: Face budget per role. Props are scenery seen at 10-30 m, a weapon fills
#: a third of the screen, a character is the thing the player stares at.
POLYCOUNT_BY_ROLE: dict[str, int] = {
    "prop": 30_000,
    "weapon": 40_000,
    "vehicle": 50_000,
    "avatar": 60_000,
}


# ── the plan ─────────────────────────────────────────────────────────────────
#
# Prompt-writing rules that actually changed the output, kept because they
# are the reusable part:
#
# * Name the *whole* object and say "complete" / "single object". The
#   services happily return a bust when the prompt names a character.
# * Say which way is up and how it stands. "standing upright" removes most
#   of the lying-on-its-side results.
# * Forbid what must not be in the mesh. A bow prompt without "no
#   character" returns an archer holding a bow about a third of the time.
# * For anything with moving parts, ask for the shell alone. "no wheels,
#   hollow open wheel arches" is the difference between a car that can
#   drive and a diecast model.

APPEARANCE_PLAN: dict[str, dict[str, Any]] = {
    # ── game_archer_explorer ────────────────────────────────────────────
    "explorer_bow": {
        "game": "game_archer_explorer",
        "role": "weapon",
        "subdir": "weapons",
        "asset_type": "prop",
        "height_metres": 1.05,
        "forward_axis": "+z",
        "prompt": (
            "A stylised fantasy recurve longbow standing vertically, carved "
            "dark walnut limbs with silver leaf inlay and faintly glowing "
            "teal runes along the grip, a single taut bowstring from tip to "
            "tip, one complete symmetrical object, no character, no arrow, "
            "game-ready asset on a plain background"
        ),
        "notes": (
            "Held in the left hand. Authored blade-plane in XY so the "
            "string runs along +Y; the runtime yaws it into the hand."
        ),
    },
    "explorer_sword": {
        "game": "game_archer_explorer",
        "role": "weapon",
        "subdir": "weapons",
        "asset_type": "prop",
        "height_metres": 1.0,
        "forward_axis": "+z",
        "prompt": (
            "A stylised fantasy longsword standing blade upward, straight "
            "double-edged polished steel blade with a central fuller, a "
            "swept crossguard set with a teal gem, leather-wrapped grip and "
            "a round pommel, one complete object, no hand, no scabbard, "
            "game-ready asset on a plain background"
        ),
        "notes": "New id: the orbiting sword used to be a procedural box stack.",
    },
    "explorer_pine": {
        "game": "game_archer_explorer",
        "role": "prop",
        "subdir": "props",
        "asset_type": "prop",
        "height_metres": 9.0,
        "forward_axis": "+z",
        "prompt": (
            "A stylised conifer pine tree, straight thick brown bark trunk "
            "rising into six layered tiers of dark blue-green needle "
            "foliage, complete unbroken conical silhouette, standing "
            "upright, low-poly game-ready environment asset"
        ),
        "notes": "Scattered by the hundreds, so the silhouette matters more than detail.",
    },
    "explorer_ruin": {
        "game": "game_archer_explorer",
        "role": "prop",
        "subdir": "props",
        "asset_type": "prop",
        "height_metres": 5.0,
        "forward_axis": "+z",
        "prompt": (
            "A ruined ancient stone archway, two weathered grey granite "
            "pillars carrying a cracked keystone arch, moss and ivy in the "
            "joints, rubble blocks around the base, standing upright, "
            "complete, game-ready environment asset"
        ),
        "notes": "Landmark prop; the arch has to be walk-through, not solid.",
    },
    "explorer_chest": {
        "game": "game_archer_explorer",
        "role": "prop",
        "subdir": "props",
        "asset_type": "prop",
        "height_metres": 0.85,
        "forward_axis": "+z",
        "prompt": (
            "A fantasy treasure chest, closed barrel-vaulted lid, dark oak "
            "planks bound with riveted brass bands, an ornate gold lock "
            "plate on the front face, complete single object, game-ready"
        ),
        "notes": "Pickup target. The lock plate identifies the front (+Z).",
    },
    "explorer_hero": {
        "game": "game_archer_explorer",
        "role": "avatar",
        "subdir": "avatars",
        "asset_type": "avatar",
        "height_metres": 1.78,
        "forward_axis": "+z",
        "prompt": (
            "A stylised fantasy ranger archer game character, full body from "
            "head to boots, standing upright in a relaxed A-pose with both "
            "arms lowered and held slightly away from the torso, empty open "
            "hands, symmetrical, hooded forest-green cloak over brown "
            "studded leather armour, belt pouches, tall laced boots, no "
            "weapons and no bow, complete closed mesh, clean topology, "
            "T-pose friendly proportions"
        ),
        "symmetry_mode": "on",
        "notes": (
            "A-pose on purpose: the runtime's autoRigHumanoid gate needs "
            "height/width >= 1.45, and the old explorer_ranger measured "
            "0.78 because it was reconstructed holding a bow."
        ),
    },
    # ── game_fps_pistol_arena ───────────────────────────────────────────
    "arena_pistol": {
        "game": "game_fps_pistol_arena",
        "role": "weapon",
        "subdir": "weapons",
        "asset_type": "prop",
        # A pistol's *height*, grip to sight rib. The FPS rescales weapons by
        # their measured barrel length anyway (see `modelLength` in
        # player.js), so this only has to be plausible rather than exact.
        "height_metres": 0.15,
        # Blank on purpose: the FPS loads weapons with `orient: false` and
        # derives facing from the vertices via `alignWeaponModel`, because a
        # quarter-turn guess whose losing side points the barrel at the
        # player's own face is not a guess worth making.
        "forward_axis": "",
        # Named, real, and *described*. The name alone carries most of the
        # weight with a text-to-3D model, but naming without describing
        # gives up control of the silhouette — and the silhouette is the
        # whole reason to pick a Desert Eagle: the slab slide and the
        # triangular shroud are recognisable at viewmodel distance where
        # fine detail is not.
        #
        # The old prompt asked for a "sci-fi handgun ... glowing cyan energy
        # cell", which is why it looked like a toy. Nothing about a made-up
        # gun constrains the generator, so it invents, and invented
        # mechanisms do not read as machined.
        "prompt": (
            "A Desert Eagle Mark XIX .50 AE semi-automatic pistol, large "
            "slab-sided rectangular slide, prominent triangular barrel "
            "shroud with a ventilated top rib, brushed stainless steel "
            "finish, black checkered grip panels, squared trigger guard, "
            "blade front sight and notched rear sight, ejection port on the "
            "right side, single complete solid object, realistic modern "
            "firearm, no hand, no holster, no ammunition, no loose "
            "magazine, hard-surface game-ready asset"
        ),
        "symmetry_mode": "off",
        "notes": (
            "Viewmodel; 20 cm from the camera for the whole match, so it "
            "gets the weapon texture budget (1536)."
        ),
    },
    "arena_rifle": {
        "game": "game_fps_pistol_arena",
        "role": "weapon",
        "subdir": "weapons",
        "asset_type": "prop",
        # Receiver to magazine floor.
        "height_metres": 0.24,
        "forward_axis": "",
        # The curved magazine is doing the work here. It is the one feature
        # that identifies an AK at a glance, so it is named first and the
        # wood furniture second; both survive being seen small, which is
        # the only test that matters for a viewmodel.
        "prompt": (
            "An AK-47 assault rifle, curved 30-round banana magazine, "
            "orange-brown wooden handguard, wooden pistol grip and fixed "
            "wooden stock, long gas tube above the barrel, slanted muzzle "
            "brake, front sight post on the gas block, stamped steel "
            "receiver with the charging handle on the right side, single "
            "complete solid object, realistic modern firearm, no hand, no "
            "sling, no bayonet, no ammunition, hard-surface game-ready asset"
        ),
        "symmetry_mode": "off",
        "notes": (
            "Fills the automatic slot. `player.js` already looked for this "
            "id, so nothing in gameplay changes when it is staged."
        ),
    },
    "arena_knife": {
        "game": "game_fps_pistol_arena",
        "role": "weapon",
        "subdir": "weapons",
        "asset_type": "prop",
        # Tip to pommel: a 7-inch blade on a 5-inch handle.
        "height_metres": 0.3,
        "forward_axis": "",
        # `alignWeaponModel` needs an elongated object to find an axis in,
        # and a knife is the most elongated thing in the game, so it passes
        # easily. What it must *not* have is a sheath: a blade inside a
        # scabbard is one fused lump with no discernible edge.
        "prompt": (
            "A US Navy SEAL fixed-blade combat knife, clip-point blade with "
            "a matte black non-reflective coating, partial saw serrations "
            "along the spine near the base, brushed steel crossguard, black "
            "textured rubber handle with deep finger grooves, lanyard hole "
            "through the pommel, single complete solid object, realistic, "
            "no sheath, no scabbard, no hand, hard-surface game-ready asset"
        ),
        "symmetry_mode": "off",
        "notes": (
            "Melee slot. No muzzle, no ammunition — see MELEE_PROFILE in "
            "player.js, which reuses the hitscan path at 2.2 m."
        ),
    },
    "arena_crate": {
        "game": "game_fps_pistol_arena",
        "role": "prop",
        "subdir": "props",
        "asset_type": "prop",
        "height_metres": 1.0,
        "forward_axis": "+z",
        "prompt": (
            "A military supply crate, closed cube, olive drab steel panels "
            "with reinforced corner brackets, recessed latches, a yellow "
            "and black hazard stripe across the lid, complete single "
            "object, game-ready"
        ),
        "notes": "Cover geometry — a cube box collider matches it exactly.",
    },
    "arena_pillar": {
        "game": "game_fps_pistol_arena",
        "role": "prop",
        "subdir": "props",
        "asset_type": "prop",
        "height_metres": 4.0,
        "forward_axis": "+z",
        "prompt": (
            "A sci-fi arena support pillar, tall octagonal brushed-metal "
            "column with vertical glowing cyan light strips, bolted base "
            "plate and a flared capital, standing upright, complete, "
            "game-ready environment asset"
        ),
        "notes": "Tall cover. Emissive strips carry the arena's colour key.",
    },
    # ── game_arcade_racer ───────────────────────────────────────────────
    "racer_car_body": {
        "game": "game_arcade_racer",
        "role": "vehicle",
        "subdir": "vehicles",
        "asset_type": "prop",
        # Not a real car's roof height: the shell is 3.8x longer than it is
        # tall, and this is the height that scales it to the 4.9 m x 2.15 m
        # footprint the game's chassis and wheelbase already assume.
        "height_metres": 1.28,
        # Deliberately blank, not "+z". A text-to-3D car arrives on an
        # arbitrary axis — this one came out lying along X — so any declared
        # forward axis is a guess, and a wrong guess is worse than none:
        # `orientModel` would apply it, `alignCarShell` would then measure
        # the already-turned mesh and apply its own correction, and the two
        # would compose into a car facing a third direction. Leaving it
        # empty makes `alignCarShell` the single owner of car orientation.
        "forward_axis": "",
        "prompt": (
            "A sleek arcade sports car body shell with no wheels, hollow "
            "open wheel arches, low wide mid-engine silhouette, glossy "
            "crimson paint with a black centre racing stripe, tinted "
            "windscreen and side glass, rear wing, front splitter, side "
            "air intakes, headlights and tail light bar, one complete "
            "object, absolutely no tyres and no rims, game-ready asset"
        ),
        "symmetry_mode": "on",
        "notes": (
            "SHELL ONLY. The wheels are racer_wheel instances parented to "
            "the vehicle's own pivots so they steer and spin; a fused car "
            "cannot do either, which is why the old racer_car looked like "
            "a diecast toy sliding across the track."
        ),
    },
    "racer_wheel": {
        "game": "game_arcade_racer",
        "role": "prop",
        "subdir": "vehicles",
        "asset_type": "prop",
        # Tyre diameter. Must equal 2 * TYRE_RADIUS in the game's
        # vehicle.js, which is also what the pivot heights and the rolling
        # rate are derived from. It was 0.9, matched to an oversized
        # placeholder torus rather than to the car.
        "height_metres": 0.68,
        # A wheel is a disc about its axle; the game applies the one
        # rotation it needs. Nothing here can be inferred from the mesh.
        "forward_axis": "",
        "prompt": (
            "A single sports car wheel, wide black racing tyre with a "
            "shallow tread pattern and a glossy sidewall, five-spoke "
            "polished silver alloy rim with a red brake caliper visible "
            "behind it, one complete object, nothing else, game-ready asset"
        ),
        "symmetry_mode": "on",
        "notes": (
            "Authored upright; the runtime rotates it onto the axle. "
            "height_metres is the tyre diameter."
        ),
    },
    "racer_palm": {
        "game": "game_arcade_racer",
        "role": "prop",
        "subdir": "props",
        "asset_type": "prop",
        "height_metres": 6.0,
        "forward_axis": "+z",
        "prompt": (
            "A tropical coconut palm tree, slender curved brown trunk with "
            "ringed bark, a full crown of eight long arching green fronds, "
            "two coconuts at the crown, complete unbroken silhouette, "
            "standing upright, game-ready environment asset"
        ),
        "notes": "Trackside scenery, read at speed — silhouette over detail.",
    },
    "racer_barrier": {
        "game": "game_arcade_racer",
        "role": "prop",
        "subdir": "props",
        "asset_type": "prop",
        "height_metres": 1.0,
        "forward_axis": "+z",
        "prompt": (
            "A race track safety barrier block, solid concrete slab with a "
            "sloped base and a flat top rail, alternating red and white "
            "chevron stripes on the front face, scuff marks, complete "
            "single object, game-ready"
        ),
        "notes": "Lines both track edges; the striped face must be the +Z face.",
    },
    "racer_gantry": {
        "game": "game_arcade_racer",
        "role": "prop",
        "subdir": "props",
        "asset_type": "prop",
        "height_metres": 7.0,
        "forward_axis": "+z",
        "prompt": (
            "A race circuit start and finish gantry arch, two white steel "
            "truss legs supporting a horizontal banner beam, chequered flag "
            "panel on the beam, a row of red starting lights underneath, "
            "standing upright, complete, game-ready environment asset"
        ),
        "notes": "Straddles the track at the start line; the beam clears 5 m.",
    },
    # ── game_sidescroll_brawler ─────────────────────────────────────────
    "brawler_dumpster": {
        "game": "game_sidescroll_brawler",
        "role": "prop",
        "subdir": "props",
        "asset_type": "prop",
        "height_metres": 1.3,
        "forward_axis": "+z",
        "prompt": (
            "An urban steel dumpster, closed flat lid, dented dark green "
            "painted panels, rust streaks, colourful graffiti tags on the "
            "long side, four small caster wheels, complete single object, "
            "game-ready"
        ),
        "notes": "Alley set dressing, seen from the side only.",
    },
    "brawler_streetlamp": {
        "game": "game_sidescroll_brawler",
        "role": "prop",
        "subdir": "props",
        "asset_type": "prop",
        "height_metres": 4.5,
        "forward_axis": "+z",
        "prompt": (
            "A city street lamp post, tall dark cast-iron pole on a fluted "
            "base, a single curved arm at the top carrying a glass "
            "cobra-head lantern housing, standing upright, complete, "
            "game-ready environment asset"
        ),
        "notes": "The lamp head is where the game parents its PointLight.",
    },
}


# ── generation ───────────────────────────────────────────────────────────────


def _build_model(provider: str, role: str, api_key: str | None):
    """Instantiate the requested backend, configured for appearance work."""

    provider = provider.lower()
    if provider == "meshy":
        from models.gen_3d_object.meshy_model import MeshyModel

        return MeshyModel(
            model_path="meshy-6",
            device="cpu",
            api_key=api_key,
            cache_dir=str(CACHE_DIR),
            output_format="glb",
            # Standard, not lowpoly: the complaint is that the meshes look
            # cheap, and `lowpoly` is a stylisation, not a quality setting.
            low_poly=False,
            texture=True,
            enable_pbr=True,
            topology="triangle",
            should_remesh=True,
            # Text-to-3D preview geometry is untextured. Refine is what
            # separates "a grey blob of the right shape" from an asset.
            refine=True,
            timeout=1800,
            verbose=False,
        )
    if provider == "tripo":
        from models.gen_3d_object.tripo_model import TripoModel

        return TripoModel(
            model_path="v3.1",
            device="cpu",
            api_key=api_key,
            cache_dir=str(CACHE_DIR),
            texture=True,
            pbr=True,
            texture_quality="detailed",
            geometry_quality="detailed",
            low_poly=False,
            timeout=1800,
            verbose=False,
        )
    raise ValueError(
        f"provider={provider!r} is not one of 'meshy', 'tripo'. Both are "
        "appearance-grade; Tripo needs TRIPO_API_KEY, Meshy MESHY_API_KEY."
    )


def generate(
    asset_id: str,
    *,
    provider: str = "meshy",
    api_key: str | None = None,
    seed: int = 42,
    out_dir: Path | None = None,
) -> Path:
    """Generate one plan entry and return the GLB path.

    The file lands in ``out_dir`` (default ``test_data/.appearance_cache/
    generated``) and is *not* staged: generating and staging are separate
    so a bad result can be inspected and re-rolled with a new seed before
    it replaces a working asset.
    """

    spec = APPEARANCE_PLAN[asset_id]
    model = _build_model(provider, spec["role"], api_key)
    directory = Path(out_dir or CACHE_DIR / "generated")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{asset_id}.glb"

    kwargs: dict[str, Any] = {}
    if provider.lower() == "meshy" and spec.get("symmetry_mode"):
        kwargs["symmetry_mode"] = spec["symmetry_mode"]

    try:
        model.infer_and_save(
            None,
            output_path=str(target),
            seed=seed,
            decimation_target=POLYCOUNT_BY_ROLE[spec["role"]],
            prompt=spec["prompt"],
            **kwargs,
        )
        logger.info(
            "[appearance] %s via %s: %s", asset_id, provider, model.last_call_info
        )
    finally:
        model.unload()
    return target


# ── bounds, without a mesh library ───────────────────────────────────────────


def _glb_bounds(path: Path) -> dict[str, list[float]] | None:
    """World-space AABB of a GLB, from accessor min/max and node transforms.

    Reading the accessor bounds glTF already stores beats decoding vertex
    buffers, and walking the node tree beats assuming identity transforms
    — a service that emits ``scale: [0.01, 0.01, 0.01]`` on the root would
    otherwise report a prop a hundred times too big. Pure stdlib on
    purpose: staging must not need trimesh on the machine that runs it.
    """

    from models.common.glb_utils import glb_json_chunk

    data = path.read_bytes()
    try:
        gltf = glb_json_chunk(data)
    except Exception:  # pragma: no cover - non-GLB input
        return None

    accessors = gltf.get("accessors") or []
    meshes = gltf.get("meshes") or []
    nodes = gltf.get("nodes") or []

    def matrix_of(node: dict[str, Any]) -> list[float]:
        if node.get("matrix"):
            return [float(v) for v in node["matrix"]]
        tx, ty, tz = node.get("translation") or (0.0, 0.0, 0.0)
        qx, qy, qz, qw = node.get("rotation") or (0.0, 0.0, 0.0, 1.0)
        sx, sy, sz = node.get("scale") or (1.0, 1.0, 1.0)
        # Column-major, as glTF stores it.
        r00 = 1 - 2 * (qy * qy + qz * qz)
        r01 = 2 * (qx * qy + qz * qw)
        r02 = 2 * (qx * qz - qy * qw)
        r10 = 2 * (qx * qy - qz * qw)
        r11 = 1 - 2 * (qx * qx + qz * qz)
        r12 = 2 * (qy * qz + qx * qw)
        r20 = 2 * (qx * qz + qy * qw)
        r21 = 2 * (qy * qz - qx * qw)
        r22 = 1 - 2 * (qx * qx + qy * qy)
        return [
            r00 * sx, r01 * sx, r02 * sx, 0.0,
            r10 * sy, r11 * sy, r12 * sy, 0.0,
            r20 * sz, r21 * sz, r22 * sz, 0.0,
            float(tx), float(ty), float(tz), 1.0,
        ]

    def multiply(a: list[float], b: list[float]) -> list[float]:
        out = [0.0] * 16
        for column in range(4):
            for row in range(4):
                out[column * 4 + row] = sum(
                    a[k * 4 + row] * b[column * 4 + k] for k in range(4)
                )
        return out

    def transform(m: list[float], point: tuple[float, float, float]):
        x, y, z = point
        return (
            m[0] * x + m[4] * y + m[8] * z + m[12],
            m[1] * x + m[5] * y + m[9] * z + m[13],
            m[2] * x + m[6] * y + m[10] * z + m[14],
        )

    identity = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    seen = 0

    def visit(index: int, parent: list[float]) -> None:
        nonlocal seen
        if index < 0 or index >= len(nodes):
            return
        node = nodes[index]
        world = multiply(parent, matrix_of(node))
        mesh_index = node.get("mesh")
        if isinstance(mesh_index, int) and 0 <= mesh_index < len(meshes):
            for primitive in meshes[mesh_index].get("primitives") or []:
                accessor_index = (primitive.get("attributes") or {}).get("POSITION")
                if not isinstance(accessor_index, int):
                    continue
                accessor = accessors[accessor_index]
                low, high = accessor.get("min"), accessor.get("max")
                if not (low and high):
                    continue
                for cx in (low[0], high[0]):
                    for cy in (low[1], high[1]):
                        for cz in (low[2], high[2]):
                            wx, wy, wz = transform(world, (cx, cy, cz))
                            for axis, value in enumerate((wx, wy, wz)):
                                lo[axis] = min(lo[axis], value)
                                hi[axis] = max(hi[axis], value)
                            seen += 1
        for child in node.get("children") or []:
            visit(int(child), world)

    scenes = gltf.get("scenes") or []
    roots = (
        scenes[int(gltf.get("scene", 0))].get("nodes")
        if scenes
        else range(len(nodes))
    )
    for root in roots or []:
        visit(int(root), identity)

    if seen == 0:
        return None
    return {
        "min": [round(v, 6) for v in lo],
        "max": [round(v, 6) for v in hi],
        "size": [round(hi[i] - lo[i], 6) for i in range(3)],
        "center": [round((hi[i] + lo[i]) / 2, 6) for i in range(3)],
    }


def _split_glb(data: bytes) -> tuple[dict[str, Any], bytes]:
    """Return ``(json, bin)`` for a binary glTF container."""

    magic, _version, total = struct.unpack("<III", data[:12])
    if magic != 0x46546C67:
        raise ValueError("not a GLB container")
    offset = 12
    document: dict[str, Any] | None = None
    binary = b""
    while offset < total:
        length, kind = struct.unpack("<II", data[offset : offset + 8])
        chunk = data[offset + 8 : offset + 8 + length]
        if kind == 0x4E4F534A:
            document = json.loads(chunk.decode("utf-8"))
        elif kind == 0x004E4942:
            binary = chunk
        offset += 8 + length + ((-length) % 4)
    if document is None:
        raise ValueError("GLB has no JSON chunk")
    return document, binary


def _pack_glb(document: dict[str, Any], binary: bytes) -> bytes:
    json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((-len(json_chunk)) % 4)
    binary = binary + b"\x00" * ((-len(binary)) % 4)
    total = 12 + 8 + len(json_chunk) + (8 + len(binary) if binary else 0)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(json_chunk), 0x4E4F534A) + json_chunk
    if binary:
        out += struct.pack("<II", len(binary), 0x004E4942) + binary
    return bytes(out)


def optimise(
    path: Path,
    *,
    max_texture: int = 1024,
    # 92, not 88. Both services already deliver JPEG, so a resize is a
    # *second* lossy generation, and that is where visible artifacts come
    # from. The extra quality costs about 15% of the bytes and removes it.
    jpeg_quality: int = 92,
) -> dict[str, Any]:
    """Shrink a generated GLB's embedded textures, in place.

    Meshy and Tripo both return 2048² PBR sets, which is right for a
    render and wrong for a browser: one tree arrives as 9 MB and a
    dressed forest is a 60 MB download before the first frame. Halving
    each axis is a 4x saving that is invisible on scenery seen at ten
    metres, and it is the difference between a game that starts and a
    game that appears to hang.

    Two details make this safe to do generically:

    * every ``bufferView`` is rewritten in order with recomputed offsets,
      so accessors — which address data *relative to their view* — stay
      valid without being touched;
    * an all-black emissive map (which is what these services emit for
      anything that does not actually glow) is reduced to a stub and its
      ``emissiveFactor`` zeroed, removing a full-size texture *and* the
      self-lit look that comes from ``emissiveFactor: [1, 1, 1]``.

    Returns a summary. A file that is not a GLB, or has no embedded
    images, is left untouched rather than rejected — this is an
    optimisation, and it must never be the reason an asset is lost.
    """

    from PIL import Image

    original = path.read_bytes()
    try:
        document, binary = _split_glb(original)
    except Exception:  # pragma: no cover - non-GLB input
        return {"optimised": False, "reason": "not a GLB"}

    images = document.get("images") or []
    views = document.get("bufferViews") or []
    if not images or not views:
        return {"optimised": False, "reason": "no embedded images"}

    # bufferView index -> replacement bytes.
    replacements: dict[int, bytes] = {}
    emissive_views: set[int] = set()
    data_images = _non_colour_images(document)
    for index, image in enumerate(images):
        view_index = image.get("bufferView")
        if not isinstance(view_index, int):
            continue
        view = views[view_index]
        start = int(view.get("byteOffset", 0))
        payload = binary[start : start + int(view["byteLength"])]
        try:
            picture = Image.open(io.BytesIO(payload))
            picture.load()
        except Exception:  # pragma: no cover - unreadable image
            continue

        # An emissive slot that is uniformly black carries no information.
        is_emissive = any(
            (material.get("emissiveTexture") or {}).get("index") is not None
            and _texture_image(document, material["emissiveTexture"]["index"])
            == index
            for material in document.get("materials") or []
        )
        extrema = picture.convert("L").getextrema()
        if is_emissive and extrema[1] <= 8:
            emissive_views.add(view_index)
            stub = Image.new("RGB", (4, 4), (0, 0, 0))
            buffer = io.BytesIO()
            stub.save(buffer, format="JPEG", quality=70)
            replacements[view_index] = buffer.getvalue()
            continue

        longest = max(picture.size)
        if longest <= max_texture:
            continue
        ratio = max_texture / longest
        resized = picture.resize(
            (max(1, round(picture.width * ratio)), max(1, round(picture.height * ratio))),
            Image.LANCZOS,
        )
        buffer = io.BytesIO()
        # Preserve the *source's* format class rather than choosing one by
        # slot. A normal, roughness or occlusion map is data — its channels
        # are a vector or a scalar, and lossy compression mixes them into
        # blotchy shading on anything glossy — so if the service sent it
        # losslessly, keep it lossless.
        #
        # But Meshy and Tripo both send JPEG already, so for them the loss
        # has *already* happened, and re-encoding to PNG cannot undo it: on
        # the pistol that cost 3.3x the bytes and recovered nothing. What
        # actually made the pistol look soft was a second lossy generation
        # at quality 88 on top of a halved resolution. So the rule is not
        # "never JPEG a data map", it is **never be the one who introduces
        # the loss** — and when re-encoding is unavoidable, do it once and
        # at high quality.
        source_lossless = (picture.format or "").upper() in ("PNG", "BMP", "TIFF")
        lossless = resized.mode in ("RGBA", "LA", "P") or (
            source_lossless and index in data_images
        )
        if lossless:
            mode = "RGBA" if resized.mode in ("RGBA", "LA", "P") else "RGB"
            resized.convert(mode).save(buffer, format="PNG", optimize=True)
            image["mimeType"] = "image/png"
        else:
            resized.convert("RGB").save(
                buffer, format="JPEG", quality=int(jpeg_quality), optimize=True
            )
            image["mimeType"] = "image/jpeg"
        replacements[view_index] = buffer.getvalue()

    if not replacements:
        return {"optimised": False, "reason": "already within budget"}

    rebuilt = bytearray()
    for view_index, view in enumerate(views):
        payload = replacements.get(view_index)
        if payload is None:
            start = int(view.get("byteOffset", 0))
            payload = binary[start : start + int(view["byteLength"])]
        # glTF requires a view's offset to satisfy its component
        # alignment; 4 bytes covers every type the services emit.
        while len(rebuilt) % 4:
            rebuilt += b"\x00"
        view["byteOffset"] = len(rebuilt)
        view["byteLength"] = len(payload)
        rebuilt += payload

    buffers = document.get("buffers") or [{}]
    buffers[0]["byteLength"] = len(rebuilt)
    buffers[0].pop("uri", None)
    document["buffers"] = buffers

    if emissive_views:
        for material in document.get("materials") or []:
            if material.get("emissiveTexture") is not None:
                material["emissiveFactor"] = [0.0, 0.0, 0.0]

    path.write_bytes(_pack_glb(document, bytes(rebuilt)))
    return {
        "optimised": True,
        "bytes_before": len(original),
        "bytes_after": path.stat().st_size,
        "textures_resized": len(replacements) - len(emissive_views),
        "emissive_stubbed": len(emissive_views),
    }


def _texture_image(document: dict[str, Any], texture_index: int) -> int | None:
    textures = document.get("textures") or []
    if 0 <= texture_index < len(textures):
        return textures[texture_index].get("source")
    return None


def _non_colour_images(document: dict[str, Any]) -> set[int]:
    """Image indices bound to a slot that carries data rather than colour.

    Normal, metallic-roughness and occlusion maps are sampled as numbers,
    so they have to survive re-encoding exactly. Everything else — base
    colour, emissive — is looked at, and can be compressed perceptually.

    An image used by both kinds of slot counts as data: keeping a colour
    map lossless costs bytes, while lossily compressing a normal map costs
    correctness.
    """

    found: set[int] = set()
    for material in document.get("materials") or []:
        slots = [material.get("normalTexture"), material.get("occlusionTexture")]
        pbr = material.get("pbrMetallicRoughness") or {}
        slots.append(pbr.get("metallicRoughnessTexture"))
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            texture_index = slot.get("index")
            if not isinstance(texture_index, int):
                continue
            image_index = _texture_image(document, texture_index)
            if isinstance(image_index, int):
                found.add(image_index)
    return found


def _glb_has_skin(path: Path) -> bool:
    from models.common.glb_utils import glb_json_chunk

    try:
        gltf = glb_json_chunk(path.read_bytes())
    except Exception:  # pragma: no cover
        return False
    return bool(gltf.get("skins"))


# ── staging ──────────────────────────────────────────────────────────────────


def find_projects(game_id: str, output_root: Path | None = None) -> list[Path]:
    root = Path(output_root or OUTPUT_ROOT) / game_id
    return sorted(
        manifest.parent.parent.parent
        for manifest in root.glob("*/mechanic/*/public/assets/manifest.json")
    )


def _artifact_id(asset_id: str, klass: str) -> str:
    import hashlib

    digest = hashlib.sha1(f"{asset_id}:{klass}".encode()).hexdigest()[:6]
    return f"web_{klass.lower()}_{asset_id}_{digest}"


#: Embedded texture budget per role, longest edge in pixels. A viewmodel
#: weapon fills a third of the screen and earns its detail; a tree does not.
TEXTURE_BUDGET_BY_ROLE: dict[str, int] = {
    # How close does the player's eye actually get? That is the only thing
    # that decides a texture budget, and it varies by more than an order of
    # magnitude across these roles. Measured on the pistol, at quality 92:
    # 2048 costs 6.2 MB, 1536 costs 1.0 MB, 1024 costs 0.5 MB.
    "prop": 1024,
    # A first-person view model is 20 cm from the camera and fills a quarter
    # of the screen for the entire match — it is the single most closely
    # inspected asset in any of these games. 1024 at quality 88 was what
    # made it look soft; 1536 at 92 is 2.25x the pixels for 1 MB, which is
    # the right end of that curve to sit on.
    "weapon": 1536,
    # The chase camera sits a few metres behind the car and the paint is the
    # showpiece, so it is worth more than scenery but far less than a gun.
    "vehicle": 1536,
    "avatar": 1024,
}


def stage(
    project_dir: Path,
    asset_id: str,
    glb: Path,
    *,
    keep_backup: bool = True,
    optimise_textures: bool = True,
) -> dict[str, Any]:
    """Replace one asset in a project and rewrite its manifest entry.

    An existing entry is *updated in place*, keeping its ``artifact_id``,
    so gameplay that already resolved that id keeps working. Bounds are
    recomputed because the runtime's height normalisation divides by the
    authored height, and a stale one silently rescales the prop.
    """

    spec = APPEARANCE_PLAN[asset_id]
    assets_root = Path(project_dir) / "public" / "assets"
    destination = assets_root / "imported" / spec["subdir"] / f"{asset_id}.glb"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if keep_backup and destination.is_file():
        backup = destination.with_suffix(".glb.trellis.bak")
        if not backup.exists():
            shutil.copyfile(destination, backup)
    shutil.copyfile(glb, destination)
    optimisation: dict[str, Any] = {"optimised": False, "reason": "skipped"}
    if optimise_textures:
        # Done on the staged copy, never on the cached generation: the
        # cache is the billed artefact and must stay byte-identical to
        # what the service returned.
        try:
            optimisation = optimise(
                destination,
                max_texture=TEXTURE_BUDGET_BY_ROLE[spec["role"]],
            )
        except Exception as error:  # noqa: BLE001 - decoration, not correctness
            logger.warning("[appearance] %s not optimised: %s", asset_id, error)
            shutil.copyfile(glb, destination)
            optimisation = {"optimised": False, "reason": str(error)}

    url = "/assets/" + str(destination.relative_to(assets_root)).replace("\\", "/")
    manifest_path = assets_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    assets = manifest.setdefault("assets", {})

    existing_key = next(
        (k for k, v in assets.items() if v.get("asset_id") == asset_id), None
    )
    skinned = _glb_has_skin(destination)
    klass = "SkinnedMesh" if skinned else "Group"
    key = existing_key or _artifact_id(asset_id, klass)
    entry = dict(assets.get(key) or {})

    bounds = _glb_bounds(destination)
    height_units = float(bounds["size"][1]) if bounds else 0.0

    entry.update(
        {
            "animations": entry.get("animations") or [],
            "artifact_id": key,
            "asset_id": asset_id,
            "capabilities": {
                "animated": bool(entry.get("animations")),
                "collidable": False,
                "playable": False,
                "renderable": True,
                "skinned": skinned,
                "spawnable": True,
            },
            "category": entry.get("category", ""),
            "class": klass,
            "package_id": asset_id,
            "representation": "gltf_binary",
            "type": spec["asset_type"],
            "url": url,
        }
    )
    if bounds:
        entry["bounds"] = bounds
    orientation = dict(entry.get("orientation") or {})
    orientation.update(
        {
            "accessor_height_units": round(height_units, 6) or orientation.get(
                "accessor_height_units", 1.0
            ),
            "forward_axis": spec["forward_axis"],
            "runtime_forward_axis": "-z",
            "runtime_yaw_degrees": 180.0,
            "pitch_offset_degrees": 0.0,
            "roll_offset_degrees": 0.0,
            "yaw_offset_degrees": 0.0,
            "pivot": "as_authored",
            "up_axis": "+y",
            "scale_hint_metres": float(spec["height_metres"]),
            "needs_vision_check": True,
            "verified_by": "heuristic",
            "notes": (
                f"Regenerated for appearance ({spec['role']}). {spec['notes']}"
            ),
        }
    )
    entry["orientation"] = orientation
    entry["generation"] = {
        "backend": "appearance_assets",
        "prompt": spec["prompt"],
        "role": spec["role"],
    }
    # A raw generated mesh has no skeleton; drop a stale rigging claim so
    # the runtime does not look for bones that are gone.
    if not skinned:
        entry.pop("rigging", None)
    assets[key] = entry
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    return {
        "asset_id": asset_id,
        "artifact_id": key,
        "url": url,
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "bounds": bounds,
        "skinned": skinned,
        "optimisation": optimisation,
    }


def upgrade_appearance(
    games: Iterable[str] = (),
    assets: Iterable[str] = (),
    *,
    provider: str = "meshy",
    api_key: str | None = None,
    seed: int = 42,
    workers: int = 4,
    output_root: Path | None = None,
    generate_only: bool = False,
) -> list[dict[str, Any]]:
    """Generate and stage every matching plan entry.

    Generation runs concurrently because the backends are network-bound
    task queues: eighteen serial jobs is an hour, four at a time is a
    quarter of that, and the services rate-limit long before four hurts.
    Staging is serialised — the manifests are shared files.
    """

    wanted_games = set(games)
    wanted_assets = set(assets)
    unknown = wanted_assets - set(APPEARANCE_PLAN)
    if unknown:
        raise KeyError(
            f"unknown assets {sorted(unknown)}; plan has {sorted(APPEARANCE_PLAN)}"
        )

    selected = [
        asset_id
        for asset_id, spec in APPEARANCE_PLAN.items()
        if (not wanted_assets or asset_id in wanted_assets)
        and (not wanted_games or spec["game"] in wanted_games)
    ]

    generated: dict[str, Path] = {}
    failures: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max(1, int(workers))) as pool:
        futures = {
            pool.submit(
                generate,
                asset_id,
                provider=provider,
                api_key=api_key,
                seed=seed,
            ): asset_id
            for asset_id in selected
        }
        for future in concurrent.futures.as_completed(futures):
            asset_id = futures[future]
            try:
                generated[asset_id] = future.result()
            except Exception as error:  # noqa: BLE001 - reported, not raised
                failures.append({"asset_id": asset_id, "error": str(error)})
                logger.error("[appearance] %s failed: %s", asset_id, error)

    results: list[dict[str, Any]] = [
        {"asset_id": row["asset_id"], "error": row["error"], "staged": False}
        for row in failures
    ]
    if generate_only:
        results.extend(
            {"asset_id": asset_id, "path": str(path), "staged": False}
            for asset_id, path in sorted(generated.items())
        )
        return results

    for asset_id, path in sorted(generated.items()):
        game_id = APPEARANCE_PLAN[asset_id]["game"]
        for project_dir in find_projects(game_id, output_root):
            record = stage(project_dir, asset_id, path)
            results.append(
                {
                    "game_id": game_id,
                    "project": str(project_dir),
                    "staged": True,
                    **record,
                }
            )
    return results


if __name__ == "__main__":  # pragma: no cover - operator convenience
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", nargs="*", default=[])
    parser.add_argument("--assets", nargs="*", default=[])
    parser.add_argument("--provider", default="meshy", choices=("meshy", "tripo"))
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--generate-only", action="store_true")
    options = parser.parse_args()

    rows = upgrade_appearance(
        options.games,
        options.assets,
        provider=options.provider,
        api_key=options.api_key,
        seed=options.seed,
        workers=options.workers,
        generate_only=options.generate_only,
    )
    for row in rows:
        if row.get("error"):
            print(f"FAIL {row['asset_id']}: {row['error']}")
        else:
            size = row.get("bounds", {}).get("size") if row.get("bounds") else None
            print(
                f"ok   {row['asset_id']:<20} {row.get('bytes', 0) / 1024:>8.0f} KB "
                f"size={size} {row.get('url', row.get('path', ''))}"
            )
