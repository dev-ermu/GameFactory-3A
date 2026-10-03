"""Chain parts into an assembly, using `attach` instead of coordinates.

The COMPOSED half of the routing split, and deliberately only the mechanism: a
rifle's part list and a car's wheelbase are content, and they live with the
build that wants them. What is general is the *joining*. Worked chains are
below each function, in the examples.

WHY A CHAIN AND NOT A LIST OF POSITIONS. Every gap in the assets here was an
absolute position that went stale: a muzzle 9 mm off its barrel, a sling loop
26 mm past a rail. Each was found by the connectivity gate, measured by hand,
and fixed with a number that broke again when a neighbour's size changed. A
chain states the relationship instead — "the muzzle sits on the end of the
barrel" — and the resolver solves the position from the parts' actual extents,
including when the target is rotated and its occupied extent is not its `size`.

WHY THIS IS NOT `compose`. `compose` assembles a *spec* — subject, units,
materials, the part list. This assembles the *parts*, by filling in the
`attach` relations between them. A body-plus-kit figure uses `compose` and
never needs this; a rifle uses both.
"""

from typing import Any, Iterable, Sequence

#: Axis each part is chained along when a link does not say. Z, because
#: `forward` is `+z` for every asset here and a chained assembly is usually
#: chained front-to-back.
DEFAULT_AXIS = "z"


class AssemblyError(ValueError):
    """A chain that cannot be built.

    Separate from `SpecError` so the message can name the link rather than
    surfacing as a dangling `attach.to` from inside the resolver's graph walk.
    """


def chain(
    parts: Sequence[dict[str, Any]],
    *,
    axis: str = DEFAULT_AXIS,
    gap: float = 0.0,
) -> list[dict[str, Any]]:
    """Attach each part to the one before it, front to back.

    ``parts`` are ordinary spec parts. The first keeps whatever ``at`` it has
    and anchors the assembly; each subsequent part gets an ``attach`` naming
    its predecessor, so the chain solves in one pass through the resolver.

    A part that already carries ``attach`` or ``parent`` is left alone — it has
    said where it goes, and overwriting that would make the order of this
    function's arguments outrank an explicit relation. That is what lets a
    chain carry a branch: state the odd one out, chain the rest.

        chain([receiver, barrel, muzzle])        # muzzle -> barrel -> receiver
        chain([body, nose], axis="z", gap=0.002) # a 2 mm shut line

    Per-link control is by ``link`` on a part, which is not a spec field and is
    removed here:

        {"id": "muzzle", ..., "link": {"axis": "z", "gap": 0.001,
                                       "my": "min", "their": "max"}}
    """

    if axis not in ("x", "y", "z"):
        raise AssemblyError(
            f"axis must be 'x', 'y' or 'z'; got {axis!r}. A chain runs along "
            "one axis, and the parts' own extents decide the distances."
        )

    chained: list[dict[str, Any]] = []
    previous: str | None = None

    for index, original in enumerate(parts):
        part = dict(original)
        link = part.pop("link", None) or {}

        if "id" not in part:
            raise AssemblyError(
                f"the part at position {index} has no `id`. A chain attaches "
                "parts by name, so every link needs one."
            )

        already_placed = part.get("attach") or part.get("parent")
        if previous is not None and not already_placed:
            attach: dict[str, Any] = {
                "to": link.get("to", previous),
                "axis": link.get("axis", axis),
                "gap": float(link.get("gap", gap)),
            }
            # Faces default to opposing, which is what the resolver does too;
            # stated only when a link overrides them, so a chained part's
            # `attach` stays readable.
            for face in ("my", "their"):
                if face in link:
                    attach[face] = link[face]
            if "offset" in link:
                attach["offset"] = list(link["offset"])
            part["attach"] = attach

        chained.append(part)
        previous = part["id"]

    return chained


def group(
    parts: Sequence[dict[str, Any]],
    *,
    to: str,
    axis: str = DEFAULT_AXIS,
    gap: float = 0.0,
) -> list[dict[str, Any]]:
    """Attach every part to one hub, rather than to each other.

    The other assembly shape: four wheels on a chassis are not a chain, they
    are four things on the same host. Chaining them would make each wheel's
    position depend on the previous wheel, so removing one would move the rest.

    ``to`` is the hub's id. It is not checked here because it may legitimately
    be defined after these parts — the resolver walks the dependency graph and
    refuses a dangling name with the full part list in hand.
    """

    grouped: list[dict[str, Any]] = []
    for original in parts:
        part = dict(original)
        link = part.pop("link", None) or {}
        if not (part.get("attach") or part.get("parent")):
            attach: dict[str, Any] = {
                "to": link.get("to", to),
                "axis": link.get("axis", axis),
                "gap": float(link.get("gap", gap)),
            }
            for face in ("my", "their"):
                if face in link:
                    attach[face] = link[face]
            if "offset" in link:
                attach["offset"] = list(link["offset"])
            part["attach"] = attach
        grouped.append(part)
    return grouped


def mirrored(
    parts: Sequence[dict[str, Any]],
    *,
    axis: str = "x",
    suffix: tuple[str, str] = ("-l", "-r"),
) -> list[dict[str, Any]]:
    """Both sides of a symmetric assembly, from one side's description.

    Wheels, landing skids, twin barrels. Authoring both sides by hand is how
    the two halves drift apart: the left one gets a fix the right one does not.

    Ids gain ``suffix``, and any ``attach.to`` naming a part in this same group
    is renamed to that side's copy — otherwise the mirrored half would attach
    to the original half and both sides would pile up on one side.
    """

    index = {"x": 0, "y": 1, "z": 2}[axis]
    own = {part["id"] for part in parts}
    out: list[dict[str, Any]] = []

    for side, sign in zip(suffix, (-1.0, 1.0)):
        for original in parts:
            part = {key: (list(value) if isinstance(value, list) else value)
                    for key, value in original.items()}
            part["id"] = f"{original['id']}{side}"

            at = list(part.get("at") or (0.0, 0.0, 0.0))
            at[index] = sign * abs(float(at[index]))
            part["at"] = at

            for relation, key in (("attach", "to"), ("parent", None)):
                value = part.get(relation)
                if not value:
                    continue
                if key is None:
                    if value in own:
                        part[relation] = f"{value}{side}"
                else:
                    value = dict(value)
                    if value.get(key) in own:
                        value[key] = f"{value[key]}{side}"
                    part[relation] = value

            out.append(part)

    return out
