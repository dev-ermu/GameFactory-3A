"""What each game needs generated, and how big it is in metres.

A generated three.js game looks like programmer art for two reasons, and
only one is about lighting. The other is that its world is built from
capsules and boxes because nothing else was available. TRELLIS.2 removes
that constraint, but only if somebody says *which* props — and that list
is content, not code.

The height matters as much as the subject. A generated mesh arrives
normalised into a unit box, so a crate and a water tower come out the
same size, and "scale until it looks right" is how a scene ends up with a
chair taller than a doorway.

Prompts describe **one object, facing the camera, on a plain background,
uncropped, evenly lit**. That is not taste. Single-image reconstruction
turns the photographed side into a fixed axis of the output, bakes cast
shadows into the albedo permanently, invents whatever the image did not
show, and ends the mesh where a crop ended the subject.
"""

from typing import Any

#: Appended to every prompt.
#:
#: Kept short on purpose: CLIP truncates at 77 tokens, so a long style
#: suffix silently throws away the end of the sentence — and the subject
#: is the part that matters. What survives here is only what was observed
#: to change the output:
#:
#: * "one single … standing alone" — asked for a *game asset*, a
#:   text-to-image model produces concept art, and concept art is a
#:   two-view turnaround. Two figures in one image reconstruct as two
#:   fused figures.
#: * "full body, whole object in frame" — a distilled model at 512 px
#:   zooms in, and a cropped subject reconstructs as a truncated mesh.
#: * "plain white background" — a busy backdrop is matted into the
#:   silhouette and reconstructs as lumps attached to the subject.
#: * "no shadow" — a cast shadow is baked into the albedo permanently,
#:   under every light the game later uses.
#:
#: None of this is reliable, which is why `frame_subject` exists: the
#: prompt asks, the framing pass enforces.
PROMPT_STYLE = (
    "one single object standing alone, wide shot, small in the centre of "
    "a large empty white background, whole object in frame with margin, "
    "facing the viewer, soft even light, no shadow, stylised game art"
)

#: The axis a single-image reconstruction places the input view on.
#: Recorded as a *heuristic*, so the review pass still happens.
GENERATED_FORWARD_AXIS = "+z"

#: Triangle and texture budgets for a browser drawing 60 frames a second.
#: The model wrapper defaults to 1 000 000 triangles and a 4K atlas, which
#: is right for a showcase render and wrong for a web game: a 4K atlas is
#: 16 MB of download per prop, and a million-triangle chair spends its
#: budget where nobody looks.
#:
#: Measured on a generated character: 76k triangles with a 2K atlas is a
#: 9.8 MB file. That is affordable once, for something the player looks at
#: from two metres away, and not affordable eleven times for scenery.
#: Triangle and texture budgets, per role, for a browser drawing 60 frames
#: a second. The model wrapper defaults to 1 000 000 triangles and a 4K
#: atlas: right for a showcase render, ruinous for a web game.
#:
#: These are the numbers `agent_skills/asset_qa/generated_asset_review.md`
#: tells a reviewer to enforce, so they belong here rather than in a
#: reviewer's head — a budget that only exists in prose gets violated by
#: the next run. A first pass generated everything at 80 000, which put a
#: 48 000-triangle crate in an arena shooter and 5 MB on the download for
#: a box the player hides behind.
#:
#: Triangle counts cannot be fixed afterwards: decimating a textured mesh
#: outside the generator throws its UVs away, and TRELLIS.2 bakes the
#: texture *after* it decimates. The budget has to be right at generation.
BUDGET_BY_ROLE: dict[str, tuple[int, int]] = {
    #  role         triangles  texture
    "avatar": (40_000, 2048),   # the player looks at this from 2 m
    "weapon": (20_000, 1024),   # held, so seen close but small on screen
    "prop": (20_000, 1024),     # interacted with, one or two per scene
    "scenery": (8_000, 1024),   # repeated dozens of times
    "landmark": (20_000, 1024),  # seen once, at a distance
}

DEFAULT_DECIMATION_TARGET = BUDGET_BY_ROLE["prop"][0]
DEFAULT_TEXTURE_SIZE = BUDGET_BY_ROLE["prop"][1]

#: game_id -> assets to generate. `asset_id`, `type`, `height` and
#: `prompt` are required; `faces` overrides the heuristic axis and
#: `triangles` overrides the budget.
GAME_ART_PLANS: dict[str, tuple[dict[str, Any], ...]] = {
    "game_fps_pistol_arena": (
        {
            "asset_id": "arena_marine",
            "type": "avatar",
            "height": 1.85,
            "prompt": (
                "stylised sci-fi security marine in light armour, standing "
                "in a neutral A-pose, arms slightly away from the body"
            ),
        },
        {
            "asset_id": "arena_pistol",
            "type": "weapon",
            "height": 0.22,
            "prompt": (
                "chunky stylised sci-fi semi-automatic pistol, side "
                "profile, matte gunmetal with one warm indicator light"
            ),
        },
        {
            "asset_id": "arena_crate",
            "type": "prop",
            "height": 1.0,
            "prompt": (
                "scuffed industrial supply crate with reinforced corners "
                "and a stencilled hazard stripe"
            ),
        },
        {
            "asset_id": "arena_pillar",
            "role": "landmark",
            "type": "prop",
            "height": 4.0,
            "prompt": (
                "weathered concrete arena pillar with exposed steel "
                "banding at the base"
            ),
        },
    ),
    "game_sidescroll_brawler": (
        {
            "asset_id": "brawler_fighter",
            "type": "avatar",
            "height": 1.8,
            "prompt": (
                "stylised street brawler in a sleeveless jacket and hand "
                "wraps, standing in a neutral A-pose"
            ),
        },
        {
            "asset_id": "brawler_thug",
            "type": "avatar",
            "height": 1.9,
            "prompt": (
                "stocky stylised enemy thug in a boiler suit, standing in "
                "a neutral A-pose"
            ),
        },
        {
            "asset_id": "brawler_streetlamp",
            "role": "scenery",
            "type": "prop",
            "height": 4.5,
            "prompt": (
                "bent city street lamp with a cracked amber lantern head"
            ),
        },
        {
            "asset_id": "brawler_dumpster",
            "type": "prop",
            "height": 1.3,
            "prompt": (
                "dented steel dumpster with a half-open lid and faded paint"
            ),
        },
    ),
    "game_arcade_racer": (
        {
            "asset_id": "racer_car",
            "type": "prop",
            "height": 1.25,
            "prompt": (
                "stylised arcade race car with exaggerated wide rear "
                "wheels, low nose and a roof scoop, seen from the front"
            ),
            "notes": (
                "The visual only: wheels stay primitives driven by "
                "gameplay, because a generated mesh is one fused body and "
                "a car whose wheels do not turn looks worse than a box "
                "that does."
            ),
        },
        {
            "asset_id": "racer_barrier",
            "role": "scenery",
            "type": "prop",
            "height": 1.0,
            "prompt": (
                "red and white striped track barrier segment on a steel "
                "frame"
            ),
        },
        {
            "asset_id": "racer_gantry",
            "role": "landmark",
            "type": "prop",
            "height": 7.0,
            "prompt": (
                "arcade start-finish gantry with chequered banner and two "
                "lattice support towers"
            ),
        },
        {
            "asset_id": "racer_palm",
            "role": "scenery",
            "type": "prop",
            "height": 6.0,
            "prompt": (
                "stylised roadside palm tree with a leaning trunk and "
                "broad fronds"
            ),
        },
    ),
    "game_archer_explorer": (
        {
            "asset_id": "explorer_ranger",
            "type": "avatar",
            "height": 1.78,
            "prompt": (
                "stylised wilderness ranger in a hooded cloak with a "
                "quiver, standing in a neutral A-pose"
            ),
        },
        {
            "asset_id": "explorer_bow",
            "type": "weapon",
            "height": 1.2,
            "prompt": (
                "curved wooden recurve bow with leather-wrapped grip, "
                "side profile"
            ),
        },
        {
            "asset_id": "explorer_chest",
            "type": "prop",
            "height": 0.8,
            "prompt": (
                "banded wooden treasure chest with iron fittings, lid "
                "closed"
            ),
        },
        {
            "asset_id": "explorer_pine",
            "role": "scenery",
            "type": "prop",
            "height": 9.0,
            "prompt": (
                "stylised low-poly pine tree with layered dark green "
                "canopy"
            ),
        },
        {
            "asset_id": "explorer_ruin",
            "role": "landmark",
            "type": "prop",
            "height": 5.0,
            "prompt": "crumbling mossy stone arch ruin, partially collapsed",
        },
    ),
}


def plan_for_game(game_id: str) -> list[dict[str, Any]]:
    """The recorded plan for one game, with defaults filled in."""

    entries: list[dict[str, Any]] = []
    for entry in GAME_ART_PLANS.get(game_id, ()):
        filled = dict(entry)
        filled.setdefault("type", "prop")
        filled.setdefault("height", 1.0)
        filled.setdefault("faces", GENERATED_FORWARD_AXIS)
        # `role` picks the budget; it defaults to the asset type, so only
        # scenery and landmarks — which are about how *often* a thing is
        # drawn rather than what it is — need to say so.
        filled.setdefault("role", filled["type"])
        triangles, texture = BUDGET_BY_ROLE.get(
            filled["role"],
            (DEFAULT_DECIMATION_TARGET, DEFAULT_TEXTURE_SIZE),
        )
        filled.setdefault("triangles", triangles)
        filled.setdefault("texture", texture)
        filled.setdefault("notes", "")
        filled["task_id"] = (
            f"gen-{filled['asset_id'].replace('_', '-')}"
        )
        filled["full_prompt"] = (
            f"{filled['prompt'].strip().rstrip('.')}. {PROMPT_STYLE}"
        )
        entries.append(filled)
    return entries


def describe_plans() -> str:
    lines: list[str] = []
    for game_id in GAME_ART_PLANS:
        lines.append(game_id)
        for entry in plan_for_game(game_id):
            lines.append(
                f"  {entry['asset_id']:22s} {entry['type']:8s} "
                f"{entry['height']:>5.2f} m  {entry['prompt'][:52]}"
            )
    return "\n".join(lines)


def neutral_canvas(size: int = 1024):
    """A plain studio backdrop for an image *editor* to paint over.

    This repository's image model edits rather than generates, so it needs
    something to start from. The soft vertical gradient is not decoration:
    it gives the editor a floor-and-sky cue, so subjects come out upright.
    """

    from PIL import Image, ImageDraw

    top, bottom = (226, 228, 232), (188, 191, 197)
    canvas = Image.new("RGB", (size, size), top)
    draw = ImageDraw.Draw(canvas)
    for row in range(size):
        blend = row / max(1, size - 1)
        draw.line(
            [(0, row), (size, row)],
            fill=tuple(
                int(round(top[i] * (1 - blend) + bottom[i] * blend))
                for i in range(3)
            ),
        )
    return canvas


def frame_subject(
    image: Any,
    *,
    margin: float = 0.12,
    background: tuple[int, int, int] = (255, 255, 255),
    min_area_fraction: float = 0.004,
    matte: bool = True,
) -> tuple[Any, dict[str, Any]]:
    """Reduce a concept image to **one** subject, centred with margin.

    A text-to-image model cannot be talked reliably out of its two
    failure modes — it draws a turnaround sheet, and it zooms in — and at
    the guidance scale a distilled model requires, negative prompts do
    nothing at all. So framing is enforced afterwards, deterministically,
    with no model involved.

    The pass finds connected non-background regions, keeps the largest,
    and re-frames it on a square canvas. That fixes both failures with one
    mechanism: a second figure is a second component and is discarded, and
    a subject that filled the frame gets its margin back.

    With ``matte`` it also writes an **alpha channel** from the same mask.
    That is worth more than it looks: image-to-3D uses a supplied alpha
    channel when there is one and reaches for a segmentation model only
    when there is not. Against a flat backdrop the mask is exact, so the
    cheap answer is also the better one — and it removes a dependency on
    a gated model that would otherwise have to be downloaded to do a job
    already done.

    Returns ``(image, info)``. ``info`` reports what was found, including
    ``touched_border`` — a subject that ran off the edge of the *original*
    image is genuinely incomplete, and no amount of cropping invents the
    missing part. That is a regenerate, and saying so beats reconstructing
    a legless ranger.
    """

    import numpy as np
    from PIL import Image

    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = np.asarray(rgb, dtype=np.int16)

    # "Not background" rather than "dark": a white prop on white needs the
    # same treatment as a dark one, and both differ from the backdrop.
    distance = np.abs(pixels - np.asarray(background, dtype=np.int16)).max(
        axis=2
    )
    mask = distance > 24

    # Label on a coarse grid: components only need to be distinguished,
    # not measured, and 96x96 makes a pure-python flood fill instant.
    grid = 96
    step_y = max(1, height // grid)
    step_x = max(1, width // grid)
    coarse = mask[::step_y, ::step_x]
    rows, cols = coarse.shape

    labels = np.zeros((rows, cols), dtype=np.int32)
    boxes: list[tuple[int, int, int, int, int]] = []
    current = 0
    for row in range(rows):
        for col in range(cols):
            if not coarse[row, col] or labels[row, col]:
                continue
            current += 1
            stack = [(row, col)]
            labels[row, col] = current
            top = bottom = row
            left = right = col
            size = 0
            while stack:
                y, x = stack.pop()
                size += 1
                top = min(top, y)
                bottom = max(bottom, y)
                left = min(left, x)
                right = max(right, x)
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if (
                        0 <= ny < rows
                        and 0 <= nx < cols
                        and coarse[ny, nx]
                        and not labels[ny, nx]
                    ):
                        labels[ny, nx] = current
                        stack.append((ny, nx))
            boxes.append((size, top, bottom, left, right, current))

    info: dict[str, Any] = {
        "component_count": len(boxes),
        "reframed": False,
        "matted": False,
        "touched_border": False,
        "coverage": 0.0,
    }
    if not boxes:
        info["notes"] = "no subject found; the image is uniform background"
        return rgb, info

    total = rows * cols
    kept = [item for item in boxes if item[0] >= total * min_area_fraction]
    kept.sort(reverse=True)
    size, top, bottom, left, right, label = kept[0]
    info["component_count"] = len(kept)
    info["coverage"] = round(size / total, 4)

    if matte:
        # Restrict the mask to the chosen component, so a second figure is
        # erased rather than merely cropped out of shot.
        #
        # The coarse label grid is only a seed: pasted straight into the
        # alpha channel it leaves stair-stepped fragments of whatever it
        # was meant to remove. Growing the seed inside the full-resolution
        # mask instead — a bounded morphological reconstruction — snaps the
        # boundary back onto real pixel edges. It needs only about one
        # iteration per grid cell, because the seed already covers the
        # component; it is filling gaps, not exploring.
        seed = np.repeat(
            np.repeat(labels == label, step_y, axis=0), step_x, axis=1
        )
        chosen = np.zeros_like(mask)
        rows_kept = min(seed.shape[0], height)
        cols_kept = min(seed.shape[1], width)
        chosen[:rows_kept, :cols_kept] = seed[:rows_kept, :cols_kept]
        chosen &= mask
        for _ in range(max(step_y, step_x) + 2):
            grown = chosen.copy()
            grown[1:, :] |= chosen[:-1, :]
            grown[:-1, :] |= chosen[1:, :]
            grown[:, 1:] |= chosen[:, :-1]
            grown[:, :-1] |= chosen[:, 1:]
            grown &= mask
            if grown.sum() == chosen.sum():
                break
            chosen = grown
        alpha = np.where(chosen, 255, 0).astype(np.uint8)
        rgb = Image.merge(
            "RGBA", (*rgb.split(), Image.fromarray(alpha, mode="L"))
        )
        info["matted"] = True

    # Back to full resolution, inclusive of the sampled cell.
    y0 = max(0, top * step_y)
    y1 = min(height, (bottom + 1) * step_y)
    x0 = max(0, left * step_x)
    x1 = min(width, (right + 1) * step_x)
    info["touched_border"] = bool(
        y0 <= step_y or x0 <= step_x or y1 >= height - step_y
        or x1 >= width - step_x
    )

    # Square, centred, with margin — the framing image-to-3D expects.
    side = max(y1 - y0, x1 - x0)
    side = int(round(side * (1.0 + 2.0 * margin))) or 1
    centre_y = (y0 + y1) // 2
    centre_x = (x0 + x1) // 2
    canvas = Image.new(
        rgb.mode,
        (side, side),
        (*background, 0) if rgb.mode == "RGBA" else background,
    )
    crop_x0 = centre_x - side // 2
    crop_y0 = centre_y - side // 2
    source_box = (
        max(0, crop_x0),
        max(0, crop_y0),
        min(width, crop_x0 + side),
        min(height, crop_y0 + side),
    )
    canvas.paste(
        rgb.crop(source_box),
        (max(0, -crop_x0), max(0, -crop_y0)),
    )
    info["reframed"] = True
    info["subject_box"] = [x0, y0, x1, y1]
    return canvas.resize((width, height), Image.LANCZOS), info


def score_framing(info: dict[str, Any]) -> tuple:
    """Rank a candidate concept image. Lower is better.

    Three things decide whether an image reconstructs cleanly, in order of
    severity:

    1. **Completeness** — a subject touching the border was partly never
       drawn, and the mesh will be truncated. Nothing downstream fixes it.
    2. **Framing** — a subject occupying a tenth of the frame wastes
       resolution; one occupying all of it has no margin. Somewhere around
       a third is right.
    3. **Singularity** — extra components are extra geometry, and the
       largest-component crop only removes them if they are separate.
    """

    coverage = float(info.get("coverage") or 0.0)
    return (
        1 if info.get("touched_border") else 0,
        round(abs(coverage - 0.34), 3),
        max(0, int(info.get("component_count") or 1) - 1),
    )


def concept_image(
    entry: dict[str, Any],
    image_model: Any | None = None,
    *,
    size: int = 1024,
    frame: bool = True,
    candidates: int = 6,
) -> tuple[Any, str, dict[str, Any]]:
    """Return ``(PIL image, provenance, framing info)`` for one entry.

    Cheapest and most controllable first: an approved image the plan
    points at, then a text-to-image model, then an editor over the
    neutral canvas.

    A distilled generator renders in a fraction of a second and cannot be
    talked reliably into leaving margin around its subject, so framing is
    **selected** rather than requested: ``candidates`` images are drawn
    from consecutive seeds and the best-framed one wins. Six candidates
    cost about two seconds, against several minutes to reconstruct a
    truncated mesh nobody can use.
    """

    from PIL import Image

    if entry.get("image_path"):
        image = Image.open(str(entry["image_path"])).convert("RGB")
        if not frame:
            return image, "plan_image", {"reframed": False}
        framed, info = frame_subject(image)
        return framed, "plan_image", info

    prompt = entry.get("full_prompt") or entry["prompt"]
    base_seed = int(entry.get("seed", 42))
    if image_model is None:
        raise ValueError(
            f"{entry['asset_id']} has no image_path and no image model "
            "was supplied; pass one or point the entry at an image"
        )

    def draw(seed: int):
        if hasattr(image_model, "generate"):
            return image_model.generate(prompt=prompt, seed=seed), "generate"
        if hasattr(image_model, "edit"):
            return (
                image_model.edit(
                    neutral_canvas(size), prompt=prompt, seed=seed
                ),
                "edit",
            )
        raise TypeError(
            "The image model exposes neither generate() nor edit(); see "
            "models/gen_image/qwen_edit.py for the interface"
        )

    attempts = max(1, int(candidates)) if frame else 1
    best: tuple | None = None
    for index in range(attempts):
        seed = base_seed + index * 1000
        raw, provenance = draw(seed)
        if not frame:
            return raw, provenance, {"reframed": False, "seed": seed}
        framed, info = frame_subject(raw)
        info["seed"] = seed
        info["candidates_tried"] = index + 1
        score = score_framing(info)
        if best is None or score < best[0]:
            best = (score, framed, provenance, info)
        if score[0] == 0 and score[1] <= 0.12:
            break  # complete and well framed: no reason to keep drawing
    assert best is not None
    return best[1], best[2], best[3]
