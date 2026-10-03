"""View naming, with no third-party dependency.

Split out of the renderer on purpose. Importing `ThreeClient` must not
require `numpy` — the launchers run under a conda environment provisioned
for Node, where the only Python packages are the standard library — so
the constants that describe a view live here and the code that draws one
is imported only when a render is actually requested.
"""

#: Camera positions, named by the axis the camera sits on. "Looking from
#: +Z" is the only description of a view that cannot be misread.
VIEW_AXES: tuple[str, ...] = ("+z", "-z", "+x", "-x", "+y")

#: The four views that decide a facing direction. The top view is useful
#: context but never decides the answer.
HORIZONTAL_VIEW_AXES: tuple[str, ...] = ("+z", "-z", "+x", "-x")

#: Every axis a camera may be placed on.
SUPPORTED_VIEW_AXES: tuple[str, ...] = (
    "+x",
    "-x",
    "+y",
    "-y",
    "+z",
    "-z",
)

#: What the horizontal axis of each rendered image means, so a reader can
#: reason about left and right without guessing.
VIEW_SCREEN_RIGHT: dict[str, str] = {
    "+z": "+x",
    "-z": "-x",
    "+x": "-z",
    "-x": "+z",
    "+y": "+x",
    "-y": "+x",
}

#: Named view sets, so a caller does not have to spell axes out.
VIEW_SETS: dict[str, tuple[str, ...]] = {
    "horizontal": HORIZONTAL_VIEW_AXES,
    "all": VIEW_AXES,
    "front_back": ("+z", "-z"),
}

DEFAULT_VIEW_SET = "all"

VIEW_CONVENTION = (
    "A view named '+z' is rendered by a camera standing on the +Z axis "
    "looking at the origin. The model surface visible in that view is "
    "its +Z side."
)


def label_for(axis: str) -> str:
    right = VIEW_SCREEN_RIGHT.get(axis, "")
    suffix = f"  |  screen right = {right}" if right else ""
    return f"camera on {axis}{suffix}"


def resolve_axes(views: str | list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Accept a named view set or an explicit list of axes."""

    if isinstance(views, str):
        named = VIEW_SETS.get(views.strip().lower())
        if named is None:
            raise ValueError(
                f"Unknown view set {views!r}; use one of "
                f"{sorted(VIEW_SETS)} or a list of axes"
            )
        return named
    axes = tuple(str(item).strip().lower() for item in views)
    unknown = [axis for axis in axes if axis not in SUPPORTED_VIEW_AXES]
    if unknown:
        raise ValueError(
            f"Unknown view axes: {unknown}; supported: "
            f"{list(SUPPORTED_VIEW_AXES)}"
        )
    return axes or VIEW_SETS[DEFAULT_VIEW_SET]
