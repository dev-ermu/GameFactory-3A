"""Orientation contract for imported three.js content.

Nothing in glTF says which way a model faces. The format fixes the *up*
axis (+Y) and the unit (metre), and then leaves the facing direction to
whatever the author happened to model — the specification's "+Z is the
front" is a recommendation that exporters routinely ignore, and a
generated mesh has no author to ask at all.

That single missing fact is the most visible defect in a generated
three.js game: a character whose model faces +X strafes for its whole
walk cycle, and one that faces +Z runs backwards forever. No amount of
gameplay code detects it, because from the engine's point of view
nothing is wrong.

So the fact is recorded instead. This module defines:

* the **runtime convention** a prepared model must end up in
  (``-Z`` forward, ``+Y`` up — see``RUNTIME_FORWARD_AXIS``);
* the **orientation record** written into the artifact registry and the
  runtime manifest, which the framework applies at instantiation time;
* a **geometric analysis** that narrows the facing axis down to two
  candidates without rendering anything.

The last point is the honest limit of geometry: an axis-aligned bounding
box tells you which horizontal axis a biped is *thin* along — that is
the facing axis — but it cannot tell you whether the face is at the
positive or the negative end. Deciding the sign requires looking at the
model, which is what ``ThreeClient.preview`` and the
``imported_asset_orientation`` agent skill are for.
"""

import math
from typing import Any, Mapping

#: Local-space forward direction a prepared model must point along.
#:
#: The generated games derive facing with``Math.atan2(-x, -z)``, so a
#: yaw of zero means "travelling toward -Z". Every imported model is
#: rotated about +Y until its authored forward axis agrees with this.
RUNTIME_FORWARD_AXIS = "-z"

#: Up axis of the runtime. glTF fixes this, so it is a check, not a choice.
RUNTIME_UP_AXIS = "+y"

AXES: tuple[str, ...] = ("+x", "-x", "+y", "-y", "+z", "-z")

AXIS_VECTORS: dict[str, tuple[float, float, float]] = {
    "+x": (1.0, 0.0, 0.0),
    "-x": (-1.0, 0.0, 0.0),
    "+y": (0.0, 1.0, 0.0),
    "-y": (0.0, -1.0, 0.0),
    "+z": (0.0, 0.0, 1.0),
    "-z": (0.0, 0.0, -1.0),
}

AXIS_INDEX = {"x": 0, "y": 1, "z": 2}

_AXIS_ALIASES = {
    "x": "+x",
    "y": "+y",
    "z": "+z",
    "px": "+x",
    "py": "+y",
    "pz": "+z",
    "nx": "-x",
    "ny": "-y",
    "nz": "-z",
    "+x": "+x",
    "+y": "+y",
    "+z": "+z",
    "-x": "-x",
    "-y": "-y",
    "-z": "-z",
    "east": "+x",
    "west": "-x",
    "up": "+y",
    "down": "-y",
    "south": "+z",
    "north": "-z",
}

#: Asset types whose facing direction is observable and therefore matters.
#: A texture has no front; a character, a vehicle and a weapon all do.
DIRECTIONAL_ASSET_TYPES = {
    "avatar",
    "character",
    "npc",
    "prop",
    "static_mesh",
    "weapon",
    "vehicle",
    "environment",
    "scene",
}

#: Types for which a wrong facing is immediately visible in play.
VISION_CHECK_ASSET_TYPES = {
    "avatar",
    "character",
    "npc",
    "vehicle",
    "weapon",
}

#: Keys accepted as ``import_asset(options=...)`` orientation input.
ORIENTATION_OPTION_KEYS = (
    "forward_axis",
    "up_axis",
    "yaw_offset_degrees",
    "pitch_offset_degrees",
    "roll_offset_degrees",
    "scale_hint_metres",
    "pivot",
    "verified_by",
    "notes",
)

#: How the orientation record was established, weakest first.
VERIFICATION_SOURCES = (
    "unverified",
    "heuristic",
    "declared",
    "agent_vision",
    "human",
)

PIVOT_MODES = ("as_authored", "feet", "centre")


class OrientationError(ValueError):
    """Raised when an orientation declaration cannot be interpreted."""


def normalize_axis(value: Any, *, field: str = "axis") -> str:
    """Return one of :data:`AXES`, accepting the usual spellings.

    ``"Z"``, ``"+z"``, ``"pz"`` and ``"south"`` all mean the same thing;
    an agent should not have to guess which one this repository wants.
    """

    text = str(value or "").strip().lower().replace(" ", "")
    if not text:
        raise OrientationError(f"{field} is empty")
    resolved = _AXIS_ALIASES.get(text)
    if resolved is None:
        raise OrientationError(
            f"{field}={value!r} is not an axis; use one of {list(AXES)}"
        )
    return resolved


def axis_vector(axis: str) -> tuple[float, float, float]:
    return AXIS_VECTORS[normalize_axis(axis)]


def yaw_degrees_between(
    source_axis: str,
    target_axis: str = RUNTIME_FORWARD_AXIS,
) -> float:
    """Rotation about +Y, in degrees, that turns ``source`` into ``target``.

    three.js rotates about +Y with ``x' = x·cosθ + z·sinθ`` and
    ``z' = -x·sinθ + z·cosθ``, so this is a lookup over the four
    quarter turns rather than an arbitrary angle: both arguments name a
    cardinal axis.
    """

    source = normalize_axis(source_axis, field="source_axis")
    target = normalize_axis(target_axis, field="target_axis")
    if source[1] == "y" or target[1] == "y":
        raise OrientationError(
            "A forward axis must be horizontal; "
            f"got source={source} target={target}"
        )
    sx, _, sz = AXIS_VECTORS[source]
    tx, _, tz = AXIS_VECTORS[target]
    for degrees in (0.0, 90.0, 180.0, 270.0):
        radians = math.radians(degrees)
        cos = round(math.cos(radians))
        sin = round(math.sin(radians))
        if (
            abs(sx * cos + sz * sin - tx) < 1e-6
            and abs(-sx * sin + sz * cos - tz) < 1e-6
        ):
            return degrees
    raise OrientationError(
        f"No quarter turn maps {source} onto {target}"
    )


def runtime_yaw_degrees(orientation: Mapping[str, Any] | None) -> float:
    """Total yaw the runtime must apply for one orientation record."""

    if not orientation:
        return 0.0
    forward = orientation.get("forward_axis")
    yaw = float(orientation.get("yaw_offset_degrees") or 0.0)
    if forward:
        yaw += yaw_degrees_between(str(forward))
    return yaw % 360.0


# ── Geometric analysis ────────────────────────────────────────────────────────

def _bounds_size(bounds: Mapping[str, Any]) -> list[float] | None:
    size = bounds.get("size")
    if isinstance(size, list) and len(size) >= 3:
        return [abs(float(item)) for item in size[:3]]
    low = bounds.get("min")
    high = bounds.get("max")
    if (
        isinstance(low, list)
        and isinstance(high, list)
        and len(low) >= 3
        and len(high) >= 3
    ):
        return [
            abs(float(high[index]) - float(low[index]))
            for index in range(3)
        ]
    return None


def analyze_geometry(
    inspection: Mapping[str, Any],
    *,
    asset_type: str = "",
    bounds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Narrow the facing axis from the artifact's bounding box.

    Returns the evidence, never a decision: ``candidate_forward_axes``
    holds the two signs of the shallow horizontal axis, and
    ``sign_is_undecidable`` says so out loud. A caller that wants one
    answer has to look at the model.

    ``bounds`` overrides the box read out of the glTF accessors, and
    callers that have a real one should pass it. Accessor bounds are
    stated in each mesh's own space with node transforms *not* applied,
    so a model assembled from scaled nodes — which every exporter
    produces sooner or later — reports a box that is off by that scale.
    ``ThreeClient.preview`` composes the hierarchy and therefore knows
    the true extents; this function does not.
    """

    accessor_bounds = dict(inspection.get("bounds") or {})
    resolved_bounds = dict(bounds or accessor_bounds)
    size = _bounds_size(resolved_bounds)
    normalized_type = str(asset_type or "").strip().lower()
    evidence: dict[str, Any] = {
        "asset_type": normalized_type,
        "runtime_forward_axis": RUNTIME_FORWARD_AXIS,
        "runtime_up_axis": RUNTIME_UP_AXIS,
        "skinned": bool(inspection.get("skinned")),
        "animation_count": int(inspection.get("animation_count") or 0),
        "mesh_count": int(inspection.get("mesh_count") or 0),
        "node_count": int(inspection.get("node_count") or 0),
        "triangle_count": int(inspection.get("triangle_count") or 0),
        "bounds": resolved_bounds,
        "bounds_source": "supplied" if bounds else "gltf_accessors",
        "needs_vision_check": normalized_type in VISION_CHECK_ASSET_TYPES
        or normalized_type == "",
        "sign_is_undecidable": True,
        "candidate_forward_axes": ["-z", "+z"],
        "notes": [],
    }
    notes: list[str] = evidence["notes"]
    if not bounds:
        notes.append(
            "These extents come from the glTF accessors, which ignore "
            "node transforms. Treat them as proportions, not measurements;"
            " three.preview reports the composed size."
        )

    if not size:
        notes.append(
            "The glTF accessors declare no POSITION min/max, so the "
            "bounding box is unknown and geometry contributes nothing; "
            "decide the facing axis from rendered views alone."
        )
        return evidence

    width, height, depth = size
    evidence["size"] = [round(value, 6) for value in size]
    largest = max(size)
    if largest <= 0:
        notes.append("The bounding box is degenerate (zero extent).")
        return evidence

    evidence["height_units"] = round(float(height), 6)
    evidence["upright"] = height >= max(width, depth) * 0.9
    if not evidence["upright"]:
        dominant = "x" if width >= depth else "z"
        notes.append(
            f"The model is longest along {dominant.upper()}, not Y. Either "
            "it is a wide prop, or it was authored Z-up and needs a "
            "pitch correction — check the rendered top view before "
            "declaring a forward axis."
        )

    # A biped is wider across the shoulders than it is deep through the
    # chest, so the shallow horizontal axis is the facing axis. For a
    # vehicle the reverse holds: it is longest along the direction it
    # travels. Both are reliable; which rule applies is not, so the
    # ratio is reported and the caller is told to look.
    if depth <= width:
        shallow, deep = "z", "x"
        ratio = width / depth if depth > 1e-9 else float("inf")
    else:
        shallow, deep = "x", "z"
        ratio = depth / width if width > 1e-9 else float("inf")
    evidence["shallow_horizontal_axis"] = shallow
    evidence["deep_horizontal_axis"] = deep
    evidence["horizontal_aspect_ratio"] = (
        round(float(ratio), 4) if math.isfinite(ratio) else None
    )

    biped_like = normalized_type in {"avatar", "character", "npc"}
    facing_letter = shallow if biped_like else deep
    if not biped_like and normalized_type in {"vehicle"}:
        facing_letter = deep
    evidence["likely_facing_letter"] = facing_letter
    evidence["candidate_forward_axes"] = [
        f"-{facing_letter}",
        f"+{facing_letter}",
    ]

    if math.isfinite(ratio) and ratio < 1.15:
        notes.append(
            f"The horizontal extents are nearly equal (ratio {ratio:.2f}), "
            "so geometry does not even identify the facing *axis*. All "
            "four horizontal axes remain candidates."
        )
        evidence["candidate_forward_axes"] = ["-z", "+z", "-x", "+x"]

    centre = resolved_bounds.get("center")
    if isinstance(centre, list) and len(centre) >= 3:
        index = AXIS_INDEX[facing_letter]
        offset = float(centre[index])
        extent = size[index]
        if extent > 1e-9 and abs(offset) / extent > 0.08:
            leaning = "+" if offset > 0 else "-"
            evidence["centre_offset_hint_axis"] = (
                f"{leaning}{facing_letter}"
            )
            notes.append(
                "The bounding box centre is offset toward "
                f"{leaning}{facing_letter} along the facing axis, which "
                "is weak evidence that the face, muzzle or bonnet points "
                "that way — a nose protrudes, a spine does not. Confirm "
                "it against the rendered views; a backpack or a tail "
                "produces the same signal in reverse."
            )

    notes.append(
        "The sign of the facing axis cannot be recovered from a "
        "bounding box: a model facing +Z and the same model facing -Z "
        "have identical boxes. Render the four horizontal views and "
        "identify which one shows the face."
    )
    return evidence


# ── Orientation records ──────────────────────────────────────────────────────

def default_orientation(
    *,
    asset_type: str = "",
    inspection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """An explicitly *unverified* record.

    Written on every mesh import so that "nobody has checked this" is a
    fact in the manifest rather than an absence, and so the runtime can
    tell an unchecked model from a correct one.
    """

    normalized_type = str(asset_type or "").strip().lower()
    record: dict[str, Any] = {
        "forward_axis": "",
        "up_axis": RUNTIME_UP_AXIS,
        "yaw_offset_degrees": 0.0,
        "pitch_offset_degrees": 0.0,
        "roll_offset_degrees": 0.0,
        "runtime_forward_axis": RUNTIME_FORWARD_AXIS,
        "runtime_yaw_degrees": 0.0,
        "pivot": "as_authored",
        "scale_hint_metres": None,
        "verified_by": "unverified",
        "notes": "",
        # Anything with a front needs looking at, and stays flagged until
        # somebody has: a declared axis is a claim, a heuristic axis is a
        # guess, and only `agent_vision` or `human` means "checked".
        "needs_vision_check": normalized_type in DIRECTIONAL_ASSET_TYPES,
    }
    if inspection is not None:
        size = _bounds_size(dict(inspection.get("bounds") or {}))
        if size and size[1] > 0:
            # Accessor space, node transforms not applied: a proportion,
            # not a measurement. Recorded because it is free and because a
            # value wildly unlike `scale_hint_metres` is itself a signal.
            record["accessor_height_units"] = round(float(size[1]), 6)
    return record


def orientation_from_options(
    options: Mapping[str, Any],
    *,
    asset_type: str = "",
    inspection: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split ``options`` into ``(orientation_record, other_options)``.

    ``import_asset`` forwards unknown options into the artifact metadata
    verbatim, which is right for opaque hints and wrong for orientation:
    an orientation that only exists as ``option_forward_axis`` is
    invisible to the runtime. So it is parsed out here, validated, and
    promoted to a first-class record.
    """

    remaining = {
        key: value
        for key, value in options.items()
        if key not in ORIENTATION_OPTION_KEYS
    }
    declared = {
        key: options[key]
        for key in ORIENTATION_OPTION_KEYS
        if key in options and options[key] not in (None, "")
    }
    record = default_orientation(
        asset_type=asset_type,
        inspection=inspection,
    )
    if not declared:
        return record, remaining
    return apply_orientation_update(record, declared), remaining


def apply_orientation_update(
    orientation: Mapping[str, Any] | None,
    updates: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge a validated update into an orientation record."""

    record = dict(orientation or default_orientation())
    for key, value in updates.items():
        if value is None or value == "":
            continue
        if key == "forward_axis":
            axis = normalize_axis(value, field="forward_axis")
            if axis[1] == "y":
                raise OrientationError(
                    "forward_axis must be horizontal (+x/-x/+z/-z); a "
                    f"model cannot face {axis}"
                )
            record["forward_axis"] = axis
        elif key == "up_axis":
            record["up_axis"] = normalize_axis(value, field="up_axis")
        elif key in {
            "yaw_offset_degrees",
            "pitch_offset_degrees",
            "roll_offset_degrees",
        }:
            record[key] = float(value) % 360.0
        elif key == "scale_hint_metres":
            metres = float(value)
            if metres <= 0:
                raise OrientationError(
                    "scale_hint_metres must be positive"
                )
            record[key] = metres
        elif key == "pivot":
            pivot = str(value).strip().lower()
            if pivot not in PIVOT_MODES:
                raise OrientationError(
                    f"pivot must be one of {list(PIVOT_MODES)}"
                )
            record[key] = pivot
        elif key == "verified_by":
            source = str(value).strip().lower()
            if source not in VERIFICATION_SOURCES:
                raise OrientationError(
                    "verified_by must be one of "
                    f"{list(VERIFICATION_SOURCES)}"
                )
            record[key] = source
        elif key == "notes":
            record[key] = str(value)
        else:  # pragma: no cover - guarded by ORIENTATION_OPTION_KEYS
            raise OrientationError(f"Unknown orientation field: {key}")

    if record.get("up_axis") and record["up_axis"] != RUNTIME_UP_AXIS:
        # Nothing here silently transposes axes: a Z-up model needs a
        # pitch, and saying so beats rendering it lying on its face.
        record.setdefault("warnings", [])
        record["warnings"] = sorted(
            set(record.get("warnings") or [])
            | {
                f"up_axis={record['up_axis']} disagrees with the runtime "
                f"up axis {RUNTIME_UP_AXIS}; declare "
                "pitch_offset_degrees to stand the model up"
            }
        )
    if record.get("forward_axis") and record.get("verified_by") in (
        None,
        "",
        "unverified",
    ):
        record["verified_by"] = "declared"
    record["runtime_forward_axis"] = RUNTIME_FORWARD_AXIS
    record["runtime_yaw_degrees"] = runtime_yaw_degrees(record)
    record["needs_vision_check"] = bool(
        record.get("needs_vision_check")
        and record.get("verified_by")
        not in {"agent_vision", "human"}
    )
    return record


def orientation_is_directional(asset_type: str) -> bool:
    return str(asset_type or "").strip().lower() in DIRECTIONAL_ASSET_TYPES


def summarize(orientation: Mapping[str, Any] | None) -> str:
    """One line for a log or a diagnostic."""

    if not orientation:
        return "orientation: unrecorded"
    forward = orientation.get("forward_axis") or "unknown"
    return (
        f"orientation: forward={forward} "
        f"yaw={orientation.get('runtime_yaw_degrees', 0.0):g}° "
        f"verified_by={orientation.get('verified_by', 'unverified')}"
    )


