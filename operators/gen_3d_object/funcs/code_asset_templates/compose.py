"""Compose a figure from a body template and the kit it wears.

The layer the earlier builds were missing. Those were scripts under
`test_data` that each performed a composition; the only way to make a
different figure was to copy one and edit it. Here composition is a function
over templates, and the operator's input is data.

The order is the one that was asked for and the one that works: build a bare
body, then put things on it. Not because it is tidier — because armour worn on
a limb has to *move with* the limb, and that is a parent-child relation the
body has to exist to receive.

    body = humanoid.body_parts()
    kit  = plate_armour.plate_armour() + plate_armour.sword()
    spec = compose(subject="knight", body=body, worn=kit, ...)

`compose` does one thing the caller should not have to: it checks that every
piece has something to attach to *before* the resolver runs, so a kit written
against a body that does not provide `forearm-l` is refused by name rather
than as a resolution failure deep in a graph walk.
"""

from typing import Any, Iterable, Sequence

#: Materials every template here refers to by role. Supplied as a default so a
#: caller composing a first figure gets something visible, and overridable
#: entry by entry — a template must not decide what a game looks like.
DEFAULT_MATERIALS: dict[str, dict[str, Any]] = {
    "skin": {"baseColor": [0.86, 0.71, 0.62, 1.0], "roughness": 0.52},
    "flesh": {"baseColor": [0.30, 0.28, 0.32, 1.0], "roughness": 0.70},
    "steel": {"baseColor": [0.62, 0.64, 0.68, 1.0], "metallic": 1.0, "roughness": 0.24},
    "mail": {"baseColor": [0.26, 0.27, 0.30, 1.0], "metallic": 0.85, "roughness": 0.62},
    "blade": {"baseColor": [0.78, 0.80, 0.84, 1.0], "metallic": 1.0, "roughness": 0.12},
    "brass": {"baseColor": [0.72, 0.55, 0.22, 1.0], "metallic": 1.0, "roughness": 0.28},
    "leather": {"baseColor": [0.22, 0.13, 0.09, 1.0], "roughness": 0.78},
    "cloth": {"baseColor": [0.44, 0.09, 0.13, 1.0], "roughness": 0.86,
              "doubleSided": True},
    "shieldFace": {"baseColor": [0.36, 0.08, 0.11, 1.0], "metallic": 0.1,
                   "roughness": 0.44},
}


class CompositionError(ValueError):
    """A kit and a body that do not fit together.

    Distinct from `SpecError`: this is caught before validation, so the
    message can name the missing body part rather than reporting a dangling
    parent from inside a graph walk.
    """


def compose(
    *,
    subject: str,
    body: Sequence[dict[str, Any]],
    worn: Iterable[dict[str, Any]] = (),
    replace: dict[str, dict[str, Any]] | None = None,
    drop: Iterable[str] = (),
    height_metres: float,
    forward: str = "+z",
    asset_type: str = "avatar",
    materials: dict[str, dict[str, Any]] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Assemble a spec from a body, what it wears, and any substitutions.

    ``replace`` swaps a part by id, which is what makes a hybrid figure a
    configuration rather than a different script: replacing ``head`` with a
    ``mesh`` part pointing at a generated GLB changes one entry and leaves the
    kit, the hierarchy and the gates untouched.

    ``drop`` removes parts by id — the bare-body version of the same idea, for
    a figure whose helm covers a head nobody will see.

    Refuses a piece whose parent is not present, by name. A kit written for a
    body that does not provide ``forearm-l`` is a mismatch between two
    templates, and saying so beats a dangling reference reported from inside
    the resolver.
    """

    dropped = set(drop)
    substitutions = dict(replace or {})

    parts: list[dict[str, Any]] = []
    for part in list(body) + list(worn):
        part_id = part["id"]
        if part_id in dropped:
            continue
        if part_id in substitutions:
            # Merged, not overwritten: a caller replacing a head with a
            # generated mesh should not have to restate its parent or its
            # attachment, which are facts about the *figure* rather than about
            # the head.
            merged = {**part, **substitutions.pop(part_id)}
            parts.append(merged)
        else:
            parts.append(dict(part))

    if substitutions:
        raise CompositionError(
            f"`replace` names parts that are not in this figure: "
            f"{', '.join(sorted(substitutions))}. Check the id against the "
            "template, since a silent no-op here would look like a template "
            "that ignored the substitution."
        )

    present = {part["id"] for part in parts}
    orphans = [
        f"{part['id']} -> {part['parent']}"
        for part in parts
        if part.get("parent") and part["parent"] not in present
    ]
    if orphans:
        raise CompositionError(
            f"{len(orphans)} worn piece(s) have nothing to attach to: "
            f"{', '.join(orphans)}. Either the body template does not provide "
            "that part, or it was removed by `drop` while something was still "
            "wearing it."
        )

    table = {**DEFAULT_MATERIALS, **(materials or {})}
    used = {part.get("material", "default") for part in parts}
    return {
        "subject": subject,
        "asset_type": asset_type,
        "units": "metres",
        "forward": forward,
        "height_metres": height_metres,
        "notes": notes,
        # Only the materials actually referenced, so a spec carries what it
        # uses rather than the whole default table.
        "materials": {name: table[name] for name in sorted(used) if name in table},
        "parts": parts,
    }
