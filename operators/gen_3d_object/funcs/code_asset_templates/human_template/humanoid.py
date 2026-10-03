"""A humanoid figure: a body to armour, as content rather than as a script.

WHY THIS IS A TEMPLATE AND NOT AN OPERATOR. A composition is content. The
operator's job is to evaluate, gate and hand off a spec; deciding that a
knight has pauldrons is a decision about a game. Every earlier build here got
that backwards — the rifle, the car and the knight were Python scripts under
test_data, so the only way to make a different figure was to edit code that
lived beside an artefact. As a template it is an *input*: read it, override
what differs, evaluate.

WHY THE BODY COMES FIRST. Armour is worn. Written as a flat list of absolute
positions, that is a coincidence — a vambrace at y 1.05 happens to coincide
with a forearm at y 1.05, and moving the arm silently separates them. Here
the body is a nesting hierarchy and every plate `parent`s to the limb it sits
on, so an engine rotating `forearm-l` carries the vambrace with it, and a
longer arm carries its armour up.

WHEN TO USE THIS AND WHEN TO MEASURE INSTEAD. This figure is *stated*: its
landmarks are nominal proportions, so a kit fitted to them needs no generator
and no network. `figure_fit` is the other half — it *measures* the same
landmarks off a generated mesh, and its numbers differ from these by up to
0.157 m on the same nominal height, because a generated body has its own
proportions. Use this to state a figure; use `figure_fit` to wear kit on one
that already exists. Do not use these numbers to fit anything to a mesh.

Sizes are in metres for a 1.72 m figure. Anything can be overridden by the
caller; `LANDMARKS` exists so a caller who scales the figure does not have to
rediscover where the knee is.
"""

from typing import Any

#: Where the joints are, in metres, for the figure below. Named because every
#: plate in every kit template reads off them: a poleyn at KNEE_Y is on the
#: knee by construction, not by eye.
#:
#: NOMINAL, NOT MEASURED. These describe the figure `body_parts` builds, and
#: nothing else. `figure_fit.landmarks_for` returns the same key names read off
#: a real mesh, and on the T-pose body those disagree with these by 0.157 m at
#: the elbow and 0.103 m at the shoulder. The names match on purpose, so a kit
#: written against one can be fitted with the other — but that only works while
#: it is clear which is which. Fitting armour to a generated mesh using these
#: numbers puts the plates where the body is not.
LANDMARKS: dict[str, float] = {
    "height": 1.72,
    "ankle_y": 0.09,
    "knee_y": 0.48,
    "hip_y": 0.92,
    "waist_y": 1.02,
    "chest_y": 1.24,
    "shoulder_y": 1.42,
    "neck_y": 1.50,
    "head_y": 1.62,
    "elbow_y": 1.16,
    "wrist_y": 0.95,
    "shoulder_x": 0.19,
    "leg_x": 0.095,
}


def _limb(part_id: str, radius: float, top: float, bottom: float,
          x: float, material: str, parent: str | None = None,
          segments: int = 14) -> dict[str, Any]:
    """One tapered limb segment as a lathe.

    A lathe and not a cylinder because a limb tapers, and the taper is what
    stops an arm reading as a pipe. Positions are absolute for root segments
    and local for nested ones, which is what `parent` means.
    """
    length = top - bottom
    part: dict[str, Any] = {
        "id": part_id, "kind": "lathe", "size": [1.0, 1.0, 1.0],
        "at": [x, (top + bottom) / 2.0, 0.0], "rotation": [0.0, 0.0, 0.0],
        "material": material, "segments": segments,
        "profile": [
            [0.0, -length / 2],
            [radius * 0.82, -length / 2],
            [radius, -length / 2 + length * 0.18],
            [radius * 0.94, length / 2 - length * 0.20],
            [radius * 0.78, length / 2],
            [0.0, length / 2],
        ],
    }
    if parent:
        part["parent"] = parent
    return part


def body_parts(materials: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """The bare figure: torso, head, arms, legs — nested, no armour.

    Returned as plain dicts so a caller can filter, rename or re-parent them
    without this module knowing what they are building.

    ``materials`` maps the roles used here (``skin``, ``flesh``) onto names in
    the caller's own material table, because a template cannot know whether a
    figure is skinned, mailed or painted.
    """

    names = {"skin": "skin", "flesh": "flesh"}
    names.update(materials or {})
    skin, flesh = names["skin"], names["flesh"]
    L = LANDMARKS

    parts: list[dict[str, Any]] = [
        # Torso is the root: every other part hangs off it or off a limb, so
        # moving the figure is one edit.
        {
            "id": "torso", "kind": "lathe", "size": [1.0, 1.0, 1.0],
            "at": [0.0, L["chest_y"] - 0.02, 0.0], "rotation": [0.0, 0.0, 0.0],
            "material": flesh, "segments": 24,
            "profile": [
                [0.0, 0.150], [0.062, 0.144], [0.104, 0.112],
                [0.122, 0.056], [0.124, -0.010], [0.113, -0.076],
                [0.100, -0.126], [0.060, -0.156], [0.0, -0.162],
            ],
        },
        {
            "id": "pelvis", "kind": "lathe", "size": [1.0, 1.0, 1.0],
            "at": [0.0, L["hip_y"] - 0.03, 0.0], "rotation": [0.0, 0.0, 0.0],
            "material": flesh, "segments": 20,
            "profile": [
                [0.0, 0.085], [0.098, 0.078], [0.112, 0.020],
                [0.104, -0.048], [0.070, -0.082], [0.0, -0.090],
            ],
        },
        # Attached rather than positioned: the neck sits on the torso, and
        # stating that means a longer torso carries the head up with it.
        {
            "id": "neck", "kind": "cylinder", "size": [0.072, 0.085, 0.072],
            "at": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0],
            "material": skin, "segments": 16,
            "attach": {"to": "torso", "axis": "y", "gap": -0.012},
        },
        {
            # Head as a lathe with a real profile: crown, brow, the undercut
            # at the temple, tapering to the jaw. A sphere gives a ball.
            "id": "head", "kind": "lathe", "size": [1.0, 1.0, 1.0],
            "at": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0],
            "material": skin, "segments": 30,
            "profile": [
                [0.0, 0.104], [0.033, 0.100], [0.062, 0.086],
                [0.079, 0.058], [0.0855, 0.024], [0.087, -0.004],
                [0.083, -0.036], [0.073, -0.068], [0.057, -0.094],
                [0.033, -0.112], [0.0, -0.118],
            ],
            "attach": {"to": "neck", "axis": "y", "gap": -0.020},
        },
    ]

    for side, sign in (("l", -1.0), ("r", 1.0)):
        arm_x = sign * L["shoulder_x"]
        leg_x = sign * L["leg_x"]
        parts += [
            _limb(f"upperarm-{side}", 0.052,
                  L["shoulder_y"] - 0.02, L["elbow_y"], arm_x, flesh),
            # Nested, and authored in world coordinates like everything else
            # here — the conversion to parent-local happens once, below, for
            # every parented part. Mixing the two conventions in one list is
            # what put the forearms on the centreline: they were written with a
            # local x of 0.0 and an absolute y, and a loop that subtracted the
            # parent's position from all three axes turned the 0.0 into +0.19.
            _limb(f"forearm-{side}", 0.044,
                  L["elbow_y"] + 0.01, L["wrist_y"], arm_x, flesh,
                  parent=f"upperarm-{side}"),
            {
                "id": f"hand-{side}", "kind": "box",
                "size": [0.075, 0.095, 0.090],
                "at": [arm_x, L["wrist_y"] - 0.048, 0.005],
                "rotation": [0.0, 0.0, 0.0],
                "material": skin, "chamfer": 0.34,
                "parent": f"forearm-{side}",
            },
            _limb(f"thigh-{side}", 0.075,
                  L["hip_y"] - 0.04, L["knee_y"], leg_x, flesh),
            _limb(f"shin-{side}", 0.058,
                  L["knee_y"] + 0.01, L["ankle_y"], leg_x, flesh,
                  parent=f"thigh-{side}"),
            {
                "id": f"foot-{side}", "kind": "box",
                "size": [0.095, 0.070, 0.215],
                "at": [leg_x, L["ankle_y"] - 0.055, 0.048],
                "rotation": [0.0, 0.0, 0.0],
                "material": skin, "chamfer": 0.30,
                "parent": f"shin-{side}",
            },
        ]

    # One conversion, for every parented part, on every axis. World coordinates
    # are what the whole file is authored in — they are readable against
    # `LANDMARKS` and they are what the gates measure — so the translation to
    # parent-local happens once, here.
    #
    # It used to apply only to `kind == "lathe"`, which meant the boxes had to
    # be authored as deltas while their siblings were authored absolutely. Two
    # conventions in one list is a bug waiting for someone to add a part: the
    # forearms were written with a local x and an absolute y and came out on the
    # centreline. Resolved in dependency order so a chain three deep is correct
    # at every level rather than only at the first.
    by_id = {part["id"]: part for part in parts}
    world = {part["id"]: list(part["at"]) for part in parts}

    def world_of(part_id: str) -> list[float]:
        return world[part_id]

    for part in parts:
        parent_id = part.get("parent")
        if not parent_id:
            continue
        if parent_id not in by_id:
            raise ValueError(
                f"{part['id']} is parented to {parent_id!r}, which this body "
                "does not contain. A kit written for another figure has to be "
                "re-parented rather than silently left at the origin."
            )
        anchor = world_of(parent_id)
        part["at"] = [world_of(part["id"])[axis] - anchor[axis]
                      for axis in range(3)]
    return parts


#: Roles the body uses, so a caller knows what to supply.
BODY_MATERIAL_ROLES = ("skin", "flesh")
