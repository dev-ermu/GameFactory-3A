"""Plate armour, as pieces that attach to a body rather than to coordinates.

This is the "then armour it" half. Each piece names the body part it is worn
on, and nothing else — no absolute position, because a plate's position *is*
its relationship to a limb. Consequences:

  * a longer arm carries its vambrace, because the vambrace is a child of the
    forearm rather than a coincidence at the same height;
  * an engine rotating `forearm-l` swings the armour with it;
  * a different body template with the same part ids wears the same kit.

The last point is what makes this a template rather than a subroutine. A kit
declares what it attaches *to* by name, and any figure providing those names
can wear it.

Each piece is a manufactured object, which is why the whole kit is stated
rather than generated: `suits_code_asset` routes "plate armour cuirass" to
`code` and the wearer to `generate`, and this file is the `code` half.
"""

from typing import Any

#: Body part ids a kit expects to find. A figure that provides these can wear
#: any kit written against them; one that cannot will be refused by name when
#: the resolver looks for the parent.
REQUIRED_BODY_PARTS = (
    "torso", "pelvis", "head", "neck",
    "upperarm-l", "forearm-l", "hand-l",
    "upperarm-r", "forearm-r", "hand-r",
    "thigh-l", "shin-l", "foot-l",
    "thigh-r", "shin-r", "foot-r",
)

#: Roles a kit uses, for the caller's material table.
KIT_MATERIAL_ROLES = ("steel", "mail", "leather", "brass", "cloth")


def plate_armour(materials: dict[str, str] | None = None,
                 *, include: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """A full harness, each piece parented to the limb it is worn on.

    ``include`` selects a subset by piece id prefix, so a caller can dress a
    figure in greaves and gauntlets alone without editing this file — which is
    the point of it being data.
    """

    names = {"steel": "steel", "mail": "mail", "leather": "leather",
             "brass": "brass", "cloth": "cloth"}
    names.update(materials or {})
    steel = names["steel"]
    leather = names["leather"]
    brass = names["brass"]
    cloth = names["cloth"]

    pieces: list[dict[str, Any]] = [
        # Cuirass: attached to the torso rather than positioned on it, so a
        # taller figure does not need the number recomputed.
        {
            "id": "cuirass", "kind": "lathe", "size": [1.0, 1.0, 1.0],
            "at": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0],
            "material": steel, "segments": 26, "parent": "torso",
            "profile": [
                [0.0, 0.152], [0.072, 0.146], [0.120, 0.114],
                [0.144, 0.058], [0.150, -0.010], [0.142, -0.078],
                [0.120, -0.128], [0.072, -0.158], [0.0, -0.164],
            ],
        },
        {
            "id": "cuirass-ridge", "kind": "box", "size": [0.026, 0.270, 0.030],
            "at": [0.0, 0.0, 0.130], "rotation": [0.0, 0.0, 0.0],
            "material": steel, "chamfer": 0.44, "parent": "cuirass",
        },
        {
            "id": "gorget", "kind": "box", "size": [0.160, 0.070, 0.150],
            "at": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0],
            "material": steel, "chamfer": 0.30, "parent": "neck",
            "attach": {"to": "neck", "axis": "y", "my": "max",
                       "their": "mid", "gap": 0.02},
        },
        {
            "id": "faulds", "kind": "box", "size": [0.300, 0.130, 0.210],
            "at": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0],
            "material": steel, "chamfer": 0.24, "parent": "pelvis",
        },
        {
            "id": "belt", "kind": "box", "size": [0.270, 0.045, 0.190],
            "at": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0],
            "material": leather, "chamfer": 0.30, "parent": "pelvis",
            "attach": {"to": "pelvis", "axis": "y", "my": "max",
                       "their": "max", "gap": 0.0},
        },
        {
            "id": "belt-buckle", "kind": "box", "size": [0.055, 0.050, 0.020],
            "at": [0.0, 0.0, 0.104], "rotation": [0.0, 0.0, 0.0],
            "material": brass, "chamfer": 0.30, "parent": "belt",
        },
        {
            # A hanging panel: an extrude, which is what extrude is for.
            "id": "tabard", "kind": "extrude", "size": [1.0, 1.0, 0.016],
            "at": [0.0, -0.130, 0.112], "rotation": [0.0, 0.0, 0.0],
            "material": cloth, "segments": 8, "parent": "pelvis",
            "profile": [
                [-0.115, 0.155], [0.115, 0.155], [0.135, -0.02],
                [0.085, -0.215], [0.0, -0.255], [-0.085, -0.215],
                [-0.135, -0.02],
            ],
        },
    ]

    for side, sign in (("l", -1.0), ("r", 1.0)):
        pieces += [
            # Pauldron: layered lames as three tori, on the upper arm — which
            # is what makes a raised arm take its shoulder plate along.
            *[
                {
                    "id": f"pauldron-{side}{index + 1}", "kind": "torus",
                    "size": [radius * 2, radius * 2, 0.048],
                    "at": [sign * 0.012, 0.078 - drop, 0.0],
                    "rotation": [90.0, 0.0, 0.0],
                    "material": steel, "segments": 18,
                    "parent": f"upperarm-{side}",
                }
                for index, (radius, drop) in enumerate(
                    ((0.115, 0.0), (0.105, 0.036), (0.092, 0.066)))
            ],
            {
                "id": f"rerebrace-{side}", "kind": "cylinder",
                "size": [0.115, 0.170, 0.115],
                "at": [0.0, 0.020, 0.0], "rotation": [0.0, 0.0, 0.0],
                "material": steel, "segments": 16,
                "parent": f"upperarm-{side}",
            },
            {
                "id": f"couter-{side}", "kind": "sphere",
                "size": [0.115, 0.100, 0.115],
                "at": [0.0, 0.098, 0.0], "rotation": [0.0, 0.0, 0.0],
                "material": steel, "segments": 14,
                "parent": f"forearm-{side}",
            },
            {
                "id": f"vambrace-{side}", "kind": "cylinder",
                "size": [0.105, 0.160, 0.105],
                "at": [0.0, 0.010, 0.0], "rotation": [0.0, 0.0, 0.0],
                "material": steel, "segments": 16,
                "parent": f"forearm-{side}",
            },
            {
                "id": f"gauntlet-{side}", "kind": "cylinder",
                "size": [0.105, 0.075, 0.105],
                "at": [0.0, 0.042, 0.0], "rotation": [0.0, 0.0, 0.0],
                "material": steel, "segments": 16,
                "parent": f"hand-{side}",
            },
            {
                "id": f"cuisse-{side}", "kind": "cylinder",
                "size": [0.155, 0.260, 0.155],
                "at": [0.0, 0.075, 0.0], "rotation": [0.0, 0.0, 0.0],
                "material": steel, "segments": 16,
                "parent": f"thigh-{side}",
            },
            {
                "id": f"poleyn-{side}", "kind": "sphere",
                "size": [0.145, 0.130, 0.145],
                "at": [0.0, 0.215, 0.0], "rotation": [0.0, 0.0, 0.0],
                "material": steel, "segments": 14,
                "parent": f"shin-{side}",
            },
            {
                "id": f"greave-{side}", "kind": "cylinder",
                "size": [0.130, 0.280, 0.130],
                "at": [0.0, 0.025, 0.0], "rotation": [0.0, 0.0, 0.0],
                "material": steel, "segments": 16,
                "parent": f"shin-{side}",
            },
            {
                # Standing on the foot's own sole rather than sharing its
                # centre: the boot is 0.105 deep around a 0.070 foot, so a
                # shared centre hung it 0.017 m below the floor. Stated as
                # `attach` so the relationship holds for a figure with
                # different feet, instead of a nudge right for one body.
                "id": f"sabaton-{side}", "kind": "box",
                "size": [0.115, 0.105, 0.245],
                "at": [0.0, 0.0, 0.012], "rotation": [0.0, 0.0, 0.0],
                "material": steel, "chamfer": 0.30, "parent": f"foot-{side}",
                "attach": {"to": f"foot-{side}", "axis": "y", "my": "min",
                           "their": "min", "gap": 0.0},
            },
        ]

    if include is not None:
        pieces = [
            piece for piece in pieces
            if any(piece["id"].startswith(prefix) for prefix in include)
        ]
    return pieces


def sword(materials: dict[str, str] | None = None,
          *, hand: str = "hand-r") -> list[dict[str, Any]]:
    """A longsword, parented to a hand so the figure is holding it.

    Parented rather than placed, because "in her right hand" is the fact; a
    coordinate is a consequence of it that goes stale when the arm moves.
    """
    names = {"blade": "blade", "brass": "brass", "leather": "leather"}
    names.update(materials or {})
    return [
        {
            # An extruded leaf outline gives a fuller and an edge bevel that
            # a box cannot.
            "id": "sword-blade", "kind": "extrude", "size": [1.0, 1.0, 0.030],
            "at": [0.0, 0.400, 0.020], "rotation": [0.0, 90.0, 0.0],
            "material": names["blade"], "segments": 8, "parent": hand,
            "profile": [
                [-0.021, -0.40], [0.021, -0.40], [0.026, -0.24],
                [0.024, 0.30], [0.0, 0.40], [-0.024, 0.30], [-0.026, -0.24],
            ],
        },
        {
            "id": "sword-guard", "kind": "box", "size": [0.200, 0.022, 0.042],
            "at": [0.0, 0.0, 0.020], "rotation": [0.0, 0.0, 0.0],
            "material": names["brass"], "chamfer": 0.30, "parent": hand,
        },
        {
            "id": "sword-grip", "kind": "cylinder", "size": [0.030, 0.115, 0.030],
            "at": [0.0, -0.065, 0.020], "rotation": [0.0, 0.0, 0.0],
            "material": names["leather"], "segments": 12, "parent": hand,
        },
        {
            "id": "sword-pommel", "kind": "sphere", "size": [0.048, 0.044, 0.048],
            "at": [0.0, -0.140, 0.020], "rotation": [0.0, 0.0, 0.0],
            "material": names["brass"], "segments": 14, "parent": hand,
        },
    ]


def shield(materials: dict[str, str] | None = None,
           *, hand: str = "hand-l") -> list[dict[str, Any]]:
    """A heater shield with a turned boss, parented to a hand."""
    names = {"shieldFace": "shieldFace", "brass": "brass"}
    names.update(materials or {})
    return [
        {
            "id": "shield", "kind": "extrude", "size": [1.0, 1.0, 0.032],
            "at": [-0.075, 0.150, -0.030], "rotation": [0.0, 82.0, 0.0],
            "material": names["shieldFace"], "segments": 8, "parent": hand,
            "profile": [
                [-0.175, 0.215], [0.175, 0.215], [0.185, 0.05],
                [0.125, -0.175], [0.0, -0.275], [-0.125, -0.175],
                [-0.185, 0.05],
            ],
        },
        {
            "id": "shield-boss", "kind": "lathe", "size": [1.0, 1.0, 1.0],
            "at": [-0.100, 0.170, -0.030], "rotation": [0.0, 0.0, 90.0],
            "material": names["brass"], "segments": 18, "parent": hand,
            "profile": [
                [0.0, -0.012], [0.062, -0.012], [0.058, 0.010],
                [0.040, 0.028], [0.0, 0.040],
            ],
        },
    ]
