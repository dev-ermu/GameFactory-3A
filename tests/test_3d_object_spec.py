#!/usr/bin/env python3
"""
tests/test_3d_object_spec.py

Prove the spec route to a 3D object builds the mesh it claims to, and refuses
the ones it should.

Run:

    python tests/test_3d_object_spec.py

Companion to the generated route. No dependencies, no network, no GPU, no model —
which is the point. This is the one 3D asset path that can be regression-tested at
all: a generated mesh is one sample of a model's behaviour and cannot be varied, so
a generation test can only check that a file appeared. A spec is data, so the mesh
that follows from it is deterministic and every gate has a case that must fail.

Two classes of check here, and the second is the one that matters.

    THE GATES CATCH WHAT THEY WERE WRITTEN FOR. Each case reproduces a defect
    recorded in img2threejs [1] — the rotation-instead-of-mirror, the
    zero-thickness part, the declared size that disagrees with the parts. A
    gate whose failing case is not pinned down decays into decoration.

    THE GATES DO NOT CATCH ANYTHING ELSE. The risk with a gate is not a missed
    defect, which shows up in the review sheet — it is a false positive that
    blocks a legitimate asset, because that trains whoever hits it to pass
    `strict=False` and then no gate means anything. So a true mirror, a
    deliberately hovering part, and a spec at the budget limit all have to
    pass.

[1] https://github.com/img2threejs/img2threejs
"""

import json
import math
import struct
import sys
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

PASSED: list[str] = []
FAILED: list[str] = []




def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  ok   {name}")
        return
    FAILED.append(f"{name}: {detail}")
    print(f"  FAIL {name} {detail}")
def spec(parts: list[dict], **overrides) -> dict:
    """A minimal valid spec with `parts` swapped in."""
    base = {
        "subject": "test rig",
        "units": "metres",
        "forward": "+z",
        "asset_type": "prop",
        "height_metres": 1.0,
    }
    base.update(overrides)
    base["parts"] = parts
    return base
def failed_gates(candidate: dict) -> list[str]:
    from operators.gen_3d_object.funcs.code_asset import run_gates, validate_spec

    return run_gates(validate_spec(candidate))["failures"]


def _write_textured_fixture(path: Path, png: bytes) -> None:
    """A minimal GLB: one textured quad, with UVs and a metallic-roughness map.

    Written by hand because the point is to exercise the *reader* against a
    file this repository's writer did not produce — a fixture round-tripped
    through our own writer would only prove the two agree, which is exactly
    the assumption that lets a decoding bug survive.
    """

    import json as json_module
    import struct as struct_module

    positions = [(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0),
                 (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0)]
    normals = [(0.0, 0.0, 1.0)] * 4
    uvs = [(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
    indices = [0, 1, 2, 0, 2, 3]

    buffer = bytearray()
    views: list[dict] = []

    def add(payload: bytes, target: int | None = None) -> int:
        while len(buffer) % 4:
            buffer.append(0)
        view = {"buffer": 0, "byteOffset": len(buffer), "byteLength": len(payload)}
        if target is not None:
            view["target"] = target
        buffer.extend(payload)
        views.append(view)
        return len(views) - 1

    position_view = add(b"".join(struct_module.pack("<3f", *p) for p in positions), 34962)
    normal_view = add(b"".join(struct_module.pack("<3f", *n) for n in normals), 34962)
    uv_view = add(b"".join(struct_module.pack("<2f", *t) for t in uvs), 34962)
    index_view = add(b"".join(struct_module.pack("<H", i) for i in indices), 34963)
    image_view = add(png)

    document = {
        "asset": {"version": "2.0", "generator": "test fixture"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        # A node transform, so the reader has to apply one.
        "nodes": [{"mesh": 0, "translation": [0.0, 0.25, 0.0],
                   "scale": [2.0, 2.0, 2.0]}],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
            "indices": 3, "material": 0, "mode": 4,
        }]}],
        "materials": [{
            "name": "painted",
            "pbrMetallicRoughness": {
                "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                # The defaults an exporter leaves behind when the channels are
                # in a map. Inheriting them is the defect under test.
                "metallicFactor": 1.0,
                "roughnessFactor": 1.0,
                "baseColorTexture": {"index": 0},
                "metallicRoughnessTexture": {"index": 1},
            },
        }],
        "textures": [{"source": 0}, {"source": 0}],
        "images": [{"bufferView": image_view, "mimeType": "image/png"}],
        "accessors": [
            {"bufferView": position_view, "componentType": 5126, "count": 4,
             "type": "VEC3", "min": [-0.5, -0.5, 0.0], "max": [0.5, 0.5, 0.0]},
            {"bufferView": normal_view, "componentType": 5126, "count": 4,
             "type": "VEC3"},
            {"bufferView": uv_view, "componentType": 5126, "count": 4,
             "type": "VEC2"},
            {"bufferView": index_view, "componentType": 5123, "count": 6,
             "type": "SCALAR"},
        ],
        "bufferViews": views,
        "buffers": [{"byteLength": len(buffer)}],
    }

    json_chunk = bytearray(json_module.dumps(document).encode("utf-8"))
    while len(json_chunk) % 4:
        json_chunk.append(ord(" "))
    binary_chunk = bytearray(buffer)
    while len(binary_chunk) % 4:
        binary_chunk.append(0)

    total = 12 + 8 + len(json_chunk) + 8 + len(binary_chunk)
    with open(path, "wb") as handle:
        handle.write(struct_module.pack("<4sII", b"glTF", 2, total))
        handle.write(struct_module.pack("<I4s", len(json_chunk), b"JSON"))
        handle.write(json_chunk)
        handle.write(struct_module.pack("<I4s", len(binary_chunk), b"BIN\x00"))
        handle.write(binary_chunk)


# ---- spec: what a valid spec is ---------------------------------------------


def test_spec_correction_terminates() -> None:
    print("\nbounded correction loop")
    from operators.gen_3d_object.funcs.code_asset import correct_spec, validate_spec

    def wrong(height: float = 3.0) -> dict:
        return validate_spec(spec(
            [{"id": "b", "kind": "box", "size": [0.5, height, 0.5], "at": [0, height / 2, 0]}],
            height_metres=1.0,
        ))

    fixed = correct_spec(wrong(), lambda current, _f: {**current, "height_metres": 3.0})
    check("a reviser that fixes the defect passes", fixed["ok"] and fixed["stop_reason"] == "passed")

    # THE RECORDED FAILURE. An unbounded loop spent 45 minutes recording a car
    # that never moved, because a lookup returned None and nothing raised.
    # Each of these is a way that loop fails to converge, and each must stop.
    stuck = correct_spec(wrong(), lambda current, _f: current)
    check(
        "a reviser that changes nothing stops as `repeating`",
        stuck["stop_reason"] == "repeating",
        f"got {stuck['stop_reason']}",
    )

    def raiser(_current: dict, _failures: list[str]) -> dict:
        raise KeyError("vehicle")

    broke = correct_spec(wrong(), raiser)
    check(
        "a reviser that raises is reported, not swallowed",
        broke["stop_reason"] == "revise_failed" and "KeyError" in broke["detail"],
        f"got {broke}",
    )

    state = {"n": 0}

    def swap(current: dict, _failures: list[str]) -> dict:
        state["n"] += 1
        height = 3.0 if state["n"] % 2 else 4.0
        return {
            **current,
            "parts": [{"id": "b", "kind": "box", "size": [0.5, height, 0.5],
                       "at": [0, height / 2, 0]}],
        }

    stalled = correct_spec(wrong(), swap)
    check(
        "a reviser that makes no progress stops",
        stalled["stop_reason"] in ("repeating", "oscillating", "no_progress"),
        f"got {stalled['stop_reason']}",
    )
    check("the stop reason is explained", bool(stalled.get("detail")))
    check(
        "the least-broken spec is returned, not the last one",
        stalled["spec"]["subject"] == "test rig",
    )


def test_spec_rejects_flat_and_misscaled() -> None:
    print("\nsolidity and scale")

    thin = failed_gates(spec([
        {"id": "sheet", "kind": "box", "size": [1.0, 1.0, 1e-7], "at": [0, 0.5, 0]},
    ]))
    check(
        "a zero-thickness part is caught",
        any("edge-on" in message for message in thin),
        f"got {thin}",
    )

    # Real sheet metal must still be allowed, or the gate blocks a door panel.
    plate = failed_gates(spec(
        [{"id": "panel", "kind": "box", "size": [0.8, 2.0, 0.004], "at": [0, 1.0, 0]}],
        height_metres=2.0,
    ))
    check("4 mm sheet metal passes", not plate, f"got {plate}")

    mismatch = failed_gates(spec(
        [{"id": "b", "kind": "box", "size": [0.5, 3.0, 0.5], "at": [0, 1.5, 0]}],
        height_metres=1.0,
    ))
    check(
        "parts disagreeing with the declared height is caught",
        any("declares" in message for message in mismatch),
        f"got {mismatch}",
    )

    decimal = failed_gates(spec(
        [{"id": "door", "kind": "box", "size": [0.01, 0.008, 0.002], "at": [0, 0.004, 0]}],
        height_metres=0.008,
    ))
    check(
        "a misplaced decimal point is caught",
        any("plausible range" in message for message in decimal),
        f"got {decimal}",
    )

    agreeing = failed_gates(spec(
        [{"id": "b", "kind": "box", "size": [0.5, 1.8, 0.5], "at": [0, 0.9, 0]}],
        height_metres=1.8, asset_type="avatar",
    ))
    check("a spec whose size matches its declaration passes", not agreeing, f"got {agreeing}")


def test_spec_rejects_malformed() -> None:
    print("\nspec validation")
    from operators.gen_3d_object.funcs.code_asset import SpecError, validate_spec

    def rejects(name: str, candidate: dict, expect: str) -> None:
        try:
            validate_spec(candidate)
        except SpecError as exc:
            check(name, expect in str(exc), f"wrong reason: {exc}")
        else:
            check(name, False, "accepted a spec it should have rejected")

    body = [{"id": "b", "kind": "box", "size": [0.5, 1.0, 0.5], "at": [0, 0.5, 0]}]

    # Facing and units have no defaults on purpose: an assumed facing is the
    # defect `orientation_review` exists to catch, and it looks correct until
    # the asset is in a scene walking backwards.
    missing_forward = spec(body)
    del missing_forward["forward"]
    rejects("a missing facing is refused", missing_forward, "spec.forward")

    bad_axis = spec(body, forward="north")
    rejects("an unknown axis is refused", bad_axis, "spec.forward")

    rejects("non-metre units are refused", spec(body, units="cm"), "spec.units")
    rejects("an empty part list is refused", spec([]), "non-empty")
    rejects(
        "a duplicate part id is refused",
        spec(body + [{"id": "b", "kind": "box", "size": [1, 1, 1]}]),
        "duplicate part id",
    )
    rejects(
        "an unknown primitive is refused",
        spec([{"id": "x", "kind": "nurbs", "size": [1, 1, 1]}]),
        "unknown kind",
    )
    rejects(
        "a zero dimension is refused",
        spec([{"id": "x", "kind": "box", "size": [1, 0, 1]}]),
        "positive",
    )
    rejects("a spec with no subject is refused", spec(body, subject=""), "subject")

    valid = validate_spec(spec(body))
    check("a valid spec normalises", valid["forward"] == "+z" and len(valid["parts"]) == 1)


# ---- gate: the gates, and what each must let through ------------------------


def test_gate_budget_and_connectivity() -> None:
    print("\nbudget and connectivity")
    from operators.gen_3d_object.funcs.code_asset import (
        check_connectivity,
        estimate_triangles,
        run_gates,
        validate_spec,
    )

    fat = failed_gates(spec([
        {"id": "ball", "kind": "sphere", "size": [1, 1, 1], "at": [0, 0.5, 0], "segments": 256},
    ]))
    check(
        "a budget overrun is caught",
        any("budget" in message for message in fat),
        f"got {fat}",
    )
    check(
        "the message says to lower segments, not to decimate",
        any("segments" in message for message in fat),
    )

    lean = failed_gates(spec([
        {"id": "ball", "kind": "sphere", "size": [1, 1, 1], "at": [0, 0.5, 0], "segments": 24},
    ]))
    check("a spec inside its budget passes", not lean, f"got {lean}")

    # Floating parts are reported and never failed: a hovering crystal is a
    # design, and failing it would make the gate wrong for a whole class of
    # asset while catching a misplaced wheel either way.
    hovering = validate_spec(spec(
        [
            {"id": "base", "kind": "box", "size": [0.5, 0.5, 0.5], "at": [0, 0.25, 0]},
            {"id": "orb", "kind": "sphere", "size": [0.2, 0.2, 0.2], "at": [0, 1.6, 0]},
        ],
        height_metres=1.7,
    ))
    report = run_gates(hovering)
    check("a hovering part does not fail the spec", report["ok"], f"got {report['failures']}")
    check(
        "a hovering part is reported",
        any("touch nothing" in message for message in report["warnings"]),
        f"got {report['warnings']}",
    )

    connected = check_connectivity(validate_spec(spec([
        {"id": "body", "kind": "box", "size": [0.5, 0.5, 0.5], "at": [0, 0.25, 0]},
        {"id": "lid", "kind": "box", "size": [0.5, 0.05, 0.5], "at": [0, 0.52, 0]},
    ])))
    check(
        "touching parts are not reported as isolated",
        not connected["isolated_parts"],
        f"got {connected['isolated_parts']}",
    )


def test_gate_budget_matches_writer() -> None:
    """The budget gate must count what the writer actually emits.

    Pinned per primitive and per segment count because the first draft used
    `segments ** 2` for the round shapes where the writer rings them at
    `segments // 2`. That over-counted by exactly 2x, so the budget gate
    would have rejected meshes that were inside their budget — and a gate
    that rejects good work gets bypassed, after which it protects nothing.
    """

    print("\nthe estimate is the mesh")
    from models.common.glb_writer import build_part
    from operators.gen_3d_object.funcs.code_asset import estimate_triangles

    profiles = {
        "lathe": ((0.5, -0.5), (0.4, 0.0), (0.5, 0.5)),
        "extrude": ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (0.0, 0.6), (-0.5, 0.5)),
    }
    for kind in ("box", "cylinder", "cone", "sphere", "torus", "lathe", "extrude"):
        for segments in (3, 8, 12, 16, 32):
            part = {
                "id": kind, "kind": kind, "size": (1.0, 1.0, 1.0),
                "at": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0),
                "segments": segments, "profile": profiles.get(kind),
                "material": "default",
            }
            _positions, _normals, indices = build_part(part)
            actual = len(indices) // 3
            estimated = estimate_triangles({"parts": [part]})
            check(
                f"{kind} at {segments} segments: estimate == mesh",
                actual == estimated,
                f"estimated {estimated}, wrote {actual}",
            )


def test_gate_chirality() -> None:
    print("\nchirality — the recorded rotation-for-mirror bug")

    hull = {"id": "hull", "kind": "box", "size": [0.4, 1.0, 0.4], "at": [0, 0.5, 0]}

    # THE RECORDED DEFECT. img2threejs negated x AND z, which is a 180-degree
    # rotation about Y. A rotation preserves handedness, so both halves were
    # the same hand. Measured on the thumb tip: z +0.288 against -0.288.
    rotated = failed_gates(spec([
        hull,
        {"id": "lamp-r", "kind": "box", "size": [0.1, 0.1, 0.1], "at": [0.3, 0.8, 0.288]},
        {"id": "lamp-l", "kind": "box", "size": [0.1, 0.1, 0.1], "at": [-0.3, 0.8, -0.288]},
    ]))
    check(
        "a rotated pair is caught",
        any("ROTATED" in message for message in rotated),
        f"got {rotated}",
    )
    check(
        "the message names the fix",
        any("Negate the lateral axis only" in message for message in rotated),
    )

    translated = failed_gates(spec([
        hull,
        {"id": "lamp-r", "kind": "box", "size": [0.1, 0.1, 0.1], "at": [0.3, 0.8, 0.2]},
        {"id": "lamp-l", "kind": "box", "size": [0.1, 0.1, 0.1], "at": [0.3, 0.8, 0.2]},
    ]))
    check(
        "a pair on the same side is caught",
        any("translated" in message for message in translated),
        f"got {translated}",
    )

    lopsided = failed_gates(spec([
        hull,
        {"id": "lamp-r", "kind": "box", "size": [0.1, 0.1, 0.1], "at": [0.3, 0.8, 0.2]},
        {"id": "lamp-l", "kind": "box", "size": [0.2, 0.1, 0.1], "at": [-0.3, 0.8, 0.2]},
    ]))
    check(
        "a mirrored pair of different sizes is caught",
        any("differ" in message for message in lopsided),
        f"got {lopsided}",
    )

    half = failed_gates(spec([
        hull,
        {"id": "lamp-r", "kind": "box", "size": [0.1, 0.1, 0.1], "at": [0.3, 0.8, 0.2]},
    ]))
    check(
        "a pair with one half missing is caught",
        any("only the right half" in message for message in half),
        f"got {half}",
    )

    # The false positive that would matter most: a correct mirror.
    mirrored = failed_gates(spec([
        hull,
        {"id": "lamp-r", "kind": "box", "size": [0.1, 0.1, 0.1], "at": [0.3, 0.8, 0.2]},
        {"id": "lamp-l", "kind": "box", "size": [0.1, 0.1, 0.1], "at": [-0.3, 0.8, 0.2]},
    ]))
    check("a true reflection passes", not mirrored, f"got {mirrored}")

    # An unpaired part must not be dragged into the pair logic by its name.
    unsuffixed = failed_gates(spec([hull, {
        "id": "barrel", "kind": "cylinder", "size": [0.1, 0.5, 0.1], "at": [0, 0.9, 0],
    }]))
    check("an unpaired part is not treated as half a pair", not unsuffixed, f"got {unsuffixed}")


def test_gate_open_mesh_warns_only() -> None:
    """An unclosed mesh is warned; an unclosed primitive still fails.

    The same measurement, two different meanings, and collapsing them
    either way is wrong. An unclosed *primitive* has a fix in the spec —
    nearly always a lathe profile that does not return to the axis — so
    failing it is actionable. An unclosed *generated* mesh is what the
    generator returned; no spec edit repairs it, and blocking an asset over
    a few boundary edges on a grip means the gate gets bypassed rather than
    the mesh improved, and then it protects nothing.

    Measured on a real fetched part: the scope generated for the rifle came
    back with 103 boundary edges while the grip and stock had none, so this
    is the common case and not a hypothetical.
    """

    print("\nan unclosed generated part warns but does not block")
    from models.common import glb_writer
    from operators.gen_3d_object.funcs.code_asset import MESH_KIND, check_windings

    with tempfile.TemporaryDirectory() as directory:
        fixture = glb_writer.write_spec_glb(
            {
                "subject": "cube", "units": "metres", "forward": "+z",
                "height_metres": 1.0, "materials": {},
                "parts": [{
                    "id": "c", "kind": "box", "size": (1.0, 1.0, 1.0),
                    "at": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0),
                    "segments": 16, "profile": None, "material": "d",
                }],
            },
            str(Path(directory) / "cube.glb"),
        )

        mesh_part = {
            "id": "fetched", "kind": MESH_KIND, "source": fixture,
            "size": (0.3, 0.3, 0.3), "at": (0.0, 0.15, 0.0),
            "rotation": (0.0, 0.0, 0.0), "segments": 16, "profile": None,
            "material": "default",
        }
        box_part = {
            "id": "authored", "kind": "box", "size": (0.3, 0.3, 0.3),
            "at": (0.4, 0.15, 0.0), "rotation": (0.0, 0.0, 0.0),
            "segments": 16, "profile": None, "material": "default",
            "chamfer": 0.0,
        }

        # Drop the last triangle of whatever is built, which opens a hole
        # without touching anything else — same vertices, same bounds.
        original = glb_writer.build_part

        def holed(part: dict) -> tuple:
            positions, normals, indices = original(part)
            return positions, normals, indices[:-3]

        glb_writer.build_part = holed
        try:
            report = check_windings({"parts": [mesh_part]})
            check(
                "an unclosed generated part does not block",
                report["ok"] and report["unclosed_generated"]
                and not report["unclosed"],
                f"ok={report['ok']}, generated={report['unclosed_generated']}, "
                f"primitive={report['unclosed']}",
            )
            check(
                "and it is warned about by name",
                any("fetched" in message for message in report["warnings"]),
                f"warnings={report['warnings']}",
            )

            report = check_windings({"parts": [box_part]})
            check(
                "an unclosed primitive still fails",
                not report["ok"] and report["unclosed"]
                and not report["unclosed_generated"],
                f"ok={report['ok']}, primitive={report['unclosed']}",
            )
        finally:
            glb_writer.build_part = original


def test_gate_orientation() -> None:
    """A generated part's declared long axis must match where it lands.

    Written after the rifle's grip came out facing across the weapon. The
    mesh's own longest axis was its x, so `rotation: [-8, 0, 0]` — the
    intuitive reading of "rake it back" — tilted it in the plane it was
    already flat in. Every other gate passed: the bounds were right, the
    winding was right, the scale was right, and the part was sideways.

    The reason no other gate can see this is that nothing in a generated
    file says which of its axes is length. So the spec has to say, and the
    check has to be against the placed vertices.

    It is also why the same rotation cannot be carried from one version of a
    part to the next: regenerating the grip textured produced a file whose
    correct rotation was `+90` where the previous one needed `-90`. A new
    file is a new set of axes.
    """

    print("\nthe orientation gate catches a sideways part")
    from models.common.glb_writer import write_spec_glb
    from operators.gen_3d_object.funcs.code_asset import (
        MESH_KIND, SpecError, check_orientation, validate_spec,
    )

    with tempfile.TemporaryDirectory() as directory:
        # A part that is clearly longest on its own y, so a rotation that
        # moves it is unambiguous.
        source = write_spec_glb(
            {
                "subject": "post", "units": "metres", "forward": "+z",
                "height_metres": 1.0, "materials": {},
                "parts": [{
                    "id": "p", "kind": "box", "size": (0.2, 1.0, 0.3),
                    "at": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0),
                    "segments": 16, "profile": None, "material": "d",
                }],
            },
            str(Path(directory) / "post.glb"),
        )

        def spec(rotation: tuple, long_axis: str | None) -> dict:
            part = {
                "id": "post", "kind": MESH_KIND, "source": source,
                "size": (0.5, 0.5, 0.5), "at": (0.0, 0.25, 0.0),
                "rotation": rotation, "material": "default",
            }
            if long_axis:
                part["long_axis"] = long_axis
            return validate_spec({
                "subject": "a post", "units": "metres", "forward": "+z",
                "parts": [part],
            })

        report = check_orientation(spec((0.0, 0.0, 0.0), "y"))
        check(
            "an upright part declared upright passes",
            not report["warnings"],
            f"warnings={report['warnings']}",
        )

        # Laid on its side but still claiming y: the defect.
        report = check_orientation(spec((0.0, 0.0, 90.0), "y"))
        check(
            "a part rotated onto its side is caught",
            any("long_axis" in message for message in report["warnings"]),
            f"warnings={report['warnings']}",
        )
        check(
            "and the measured axis is reported so the fix is obvious",
            report["parts_checked"][0]["measured_long_axis"] == "x",
            f"{report['parts_checked'][0]}",
        )

        # Rotated *and* declared correctly: no warning. Asserting only the
        # failing case would leave a gate that fires on any rotation at all.
        report = check_orientation(spec((0.0, 0.0, 90.0), "x"))
        check(
            "a part rotated onto its side and declared so passes",
            not report["warnings"],
            f"warnings={report['warnings']}",
        )

        # Undeclared: silent. The field is optional because for a near-cubic
        # part the longest axis is noise, and a gate that demanded a
        # declaration nobody could give would be bypassed.
        report = check_orientation(spec((0.0, 0.0, 90.0), None))
        check(
            "an undeclared long axis is not guessed at",
            not report["warnings"] and report["parts_checked"],
            f"warnings={report['warnings']}",
        )

        # A near-cubic part is skipped rather than judged on noise.
        cube = write_spec_glb(
            {
                "subject": "cube", "units": "metres", "forward": "+z",
                "height_metres": 1.0, "materials": {},
                "parts": [{
                    "id": "c", "kind": "box", "size": (1.0, 1.0, 1.0),
                    "at": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0),
                    "segments": 16, "profile": None, "material": "d",
                }],
            },
            str(Path(directory) / "cube.glb"),
        )
        report = check_orientation(validate_spec({
            "subject": "a cube", "units": "metres", "forward": "+z",
            "parts": [{
                "id": "cube", "kind": MESH_KIND, "source": cube,
                "size": (0.5, 0.5, 0.5), "at": (0.0, 0.25, 0.0),
                "long_axis": "z",
            }],
        }))
        check(
            "a part with no dominant axis is skipped, not failed on noise",
            not report["warnings"]
            and report["parts_checked"][0].get("skipped"),
            f"{report['parts_checked'][0]}",
        )

        # Refusals: a bad axis name, and the field on a primitive.
        for label, part in (
            ("an unknown axis name", {
                "id": "p", "kind": MESH_KIND, "source": source,
                "size": (0.5, 0.5, 0.5), "long_axis": "up"}),
            ("long_axis on a box", {
                "id": "p", "kind": "box", "size": (0.5, 0.5, 0.5),
                "long_axis": "y"}),
        ):
            try:
                validate_spec({
                    "subject": "x", "units": "metres", "forward": "+z",
                    "parts": [part],
                })
                check(f"{label} is refused", False, "it was accepted")
            except SpecError:
                check(f"{label} is refused", True, "")


def test_gate_provenance_warns_then_blocks() -> None:
    """The gate must say what generation bought and what it cost.

    Its job is not to prevent generated parts — it is to keep the trade
    visible, because after export the two kinds are indistinguishable and
    only one of them can still be adjusted by editing a number. Two
    thresholds, and the reason they differ is the point:

    A composition that is mostly generated triangles is warned, since a
    grip and a stock legitimately outweigh forty small primitives.

    A composition that is mostly generated *parts as well as* triangles is
    failed, because at that point it is a generated asset with primitives
    attached, and it would be reported as `verified_by="spec"` while
    nothing had verified the facing of the mesh carrying it.
    """

    print("\nthe provenance gate reports the trade")
    from models.common.glb_writer import write_spec_glb
    from operators.gen_3d_object.funcs.code_asset import (
        MESH_KIND, check_provenance, validate_spec,
    )

    with tempfile.TemporaryDirectory() as directory:
        # A dense fixture, so a single mesh part can dominate a budget the way
        # a real generated part does.
        fixture = write_spec_glb(
            {
                "subject": "dense", "units": "metres", "forward": "+z",
                "height_metres": 1.0, "materials": {},
                "parts": [{
                    "id": "ball", "kind": "sphere", "size": (1.0, 1.0, 1.0),
                    "at": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0),
                    "segments": 48, "profile": None, "material": "d",
                }],
            },
            str(Path(directory) / "dense.glb"),
        )

        def spec(parts: list[dict]) -> dict:
            return validate_spec({
                "subject": "assembly", "units": "metres", "forward": "+z",
                "asset_type": "prop", "materials": {}, "parts": parts,
            })

        primitives = [
            {"id": f"box-{index}", "kind": "box", "size": (0.05, 0.05, 0.05),
             "at": (index * 0.06, 0.03, 0.0), "material": "default"}
            for index in range(6)
        ]
        mesh_part = {
            "id": "moulded", "kind": MESH_KIND, "source": fixture,
            "size": (0.2, 0.2, 0.2), "at": (0.0, 0.2, 0.0),
            "material": "default",
        }

        # No generated parts: the gate is silent rather than absent, so a
        # pure-primitive spec does not pay for a check it does not need.
        report = check_provenance(spec(primitives))
        check(
            "a spec with no generated parts passes silently",
            report["ok"] and not report["warnings"]
            and report["generated_triangles"] == 0,
            f"{report}",
        )

        # Mostly generated triangles: warned, not failed.
        report = check_provenance(spec(primitives + [mesh_part]))
        check(
            "a composition dominated by generated triangles is warned",
            report["ok"] and any(
                "generated" in message for message in report["warnings"]
            ),
            f"ok={report['ok']}, warnings={report['warnings']}",
        )
        check(
            "and the per-part cost is reported, not just the total",
            report["generated_parts"][0]["triangles"] > 0
            and 0.0 < report["generated_parts"][0]["share"] <= 1.0,
            f"{report['generated_parts']}",
        )

        # Mostly generated parts *and* triangles: failed.
        report = check_provenance(spec([
            dict(mesh_part, id="moulded-a"),
            dict(mesh_part, id="moulded-b", at=(0.3, 0.2, 0.0)),
            {"id": "pin", "kind": "box", "size": (0.01, 0.01, 0.01),
             "at": (0.0, 0.005, 0.0), "material": "default"},
        ]))
        check(
            "a composition that is really a generated asset is failed",
            not report["ok"]
            and any("composition" in message for message in report["failures"]),
            f"ok={report['ok']}, failures={report['failures']}",
        )

        # The boundary, pinned. Both conditions are required, and each on its
        # own would fail work that is correct: a real weapon is 77% generated
        # triangles because a grip outweighs forty small primitives, and a
        # bracket is legitimately one plate plus one moulded pad. Asserting
        # only the failing case would leave the threshold as a claim.
        report = check_provenance(spec([
            {"id": "plate", "kind": "box", "size": (0.3, 0.02, 0.3),
             "at": (0.0, 0.01, 0.0), "material": "default"},
            {"id": "post", "kind": "cylinder", "size": (0.02, 0.1, 0.02),
             "at": (0.0, 0.07, 0.0), "material": "default"},
            dict(mesh_part, id="pad"),
        ]))
        check(
            "two stated parts beside a generated one is a composition, not a "
            "disguise",
            report["ok"] and report["generated_share"] > 0.9,
            f"ok={report['ok']}, share={report['generated_share']}, "
            f"failures={report['failures']}",
        )
        report = check_provenance(spec([
            {"id": "plate", "kind": "box", "size": (0.3, 0.02, 0.3),
             "at": (0.0, 0.01, 0.0), "material": "default"},
            dict(mesh_part, id="pad"),
        ]))
        check(
            "but one stated part beside it is decoration on something fetched",
            not report["ok"],
            f"ok={report['ok']}, share={report['generated_share']}",
        )

        # A non-uniform size is honoured by taking the largest component, and
        # the gate says so — the author wrote three numbers and got one.
        report = check_provenance(spec([
            dict(mesh_part, size=(0.2, 0.05, 0.1)),
        ]))
        check(
            "a non-uniform size on a generated part is called out",
            any("not uniform" in message for message in report["warnings"]),
            f"warnings={report['warnings']}",
        )
        report = check_provenance(spec([mesh_part]))
        check(
            "and a uniform one is not",
            not any("not uniform" in message for message in report["warnings"]),
            f"warnings={report['warnings']}",
        )


# ---- geom: primitive geometry -----------------------------------------------


def test_glb_output_roundtrip() -> None:
    print("\nGLB output")
    from models.common.glb_utils import glb_json_chunk, glb_summary, is_glb
    from operators.gen_3d_object.funcs.code_asset import build_code_asset

    crate = spec(
        [
            {"id": "body", "kind": "box", "size": [0.6, 0.6, 0.6],
             "at": [0, 0.3, 0], "material": "wood"},
            {"id": "hoop", "kind": "torus", "size": [0.4, 0.4, 0.4],
             "at": [0, 0.5, 0], "material": "iron", "segments": 12},
        ],
        subject="wooden supply crate",
        # 0.7 m, not 0.6: the hoop sits proud of the box, and the composed
        # height is what the scale gate measures. Writing 0.6 here is exactly
        # the declared-versus-actual mismatch the gate is for, and it caught
        # this while the test was being written.
        height_metres=0.7,
        materials={
            "wood": {"baseColor": [0.45, 0.3, 0.18, 1], "roughness": 0.85},
            "iron": {"baseColor": [0.35, 0.35, 0.38, 1], "metallic": 1.0, "roughness": 0.4},
        },
    )

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "crate.glb"
        report = build_code_asset(crate, str(out))
        check("the spec builds", report["ok"], f"got {report['failures']}")
        check("a file was written", out.exists())

        data = out.read_bytes()
        check("the output is a GLB", is_glb(data))

        summary = glb_summary(data)
        check("the GLB parses", "error" not in summary, summary.get("error", ""))
        check(
            "the estimate matches the mesh",
            summary["triangles"] == report["triangles"],
            f"estimated {report['triangles']}, wrote {summary['triangles']}",
        )
        check("both materials survive", summary["materials"] == 2, f"got {summary['materials']}")
        check(
            "the generator is recorded",
            summary["generator"] == "3AGameFactory/glb_writer",
        )

        doc = glb_json_chunk(data)
        # The property a reconstructed mesh cannot offer: parts stay
        # addressable, so gameplay can still move one.
        check(
            "part ids survive as node names",
            [node["name"] for node in doc["nodes"]] == ["body", "hoop"],
            f"got {[node.get('name') for node in doc['nodes']]}",
        )
        check(
            "POSITION carries min/max",
            all(
                "min" in accessor and "max" in accessor
                for accessor in doc["accessors"]
                if accessor["type"] == "VEC3" and "min" in accessor
            ),
        )
        check(
            "the spec is kept inside the file it produced",
            doc["extras"]["gamefactory3a"]["spec"]["subject"] == "wooden supply crate",
        )
        check(
            "facing and size are stated, not inferred",
            report["forward_axis"] == "+z" and report["scale_hint_metres"] == 0.7,
        )

        # `strict` must not write. An asset that exists gets used.
        broken = spec([{"id": "sheet", "kind": "box", "size": [1, 1, 1e-7], "at": [0, 0.5, 0]}])
        blocked = Path(tmp) / "blocked.glb"
        refused = build_code_asset(broken, str(blocked))
        check(
            "a failed gate writes nothing",
            not refused["ok"] and refused["glb_path"] is None and not blocked.exists(),
        )
        check(
            "and says nothing was written",
            any("nothing was written" in message for message in refused["warnings"]),
        )


def test_geom_primitives_are_sane() -> None:
    print("\ngeometry sanity")
    from models.common.glb_writer import build_part, rotated_bounds

    for kind in ("box", "cylinder", "cone", "sphere", "torus", "lathe", "extrude"):
        part = {
            "id": kind, "kind": kind, "size": (1.0, 1.0, 1.0), "at": (0.0, 0.0, 0.0),
            "rotation": (0.0, 0.0, 0.0), "segments": 12, "profile": None,
            "material": "default",
        }
        positions, normals, indices = build_part(part)
        check(f"{kind}: produces triangles", len(indices) >= 3 and len(indices) % 3 == 0)
        check(f"{kind}: one normal per vertex", len(normals) == len(positions))
        check(
            f"{kind}: every index is in range",
            all(0 <= index < len(positions) for index in indices),
        )
        check(
            f"{kind}: normals are unit length",
            all(
                abs(math.sqrt(x * x + y * y + z * z) - 1.0) < 1e-6
                for x, y, z in normals
            ),
        )
        check(
            f"{kind}: fits its declared extent",
            all(abs(value) <= 0.5 + 1e-6 for point in positions for value in point),
        )

    # The gates and the writer must measure the same object. A draft of
    # `part_bounds` swapped extents for right angles, which is exact at 90
    # degrees and silently wrong at 30 — so a rotation the spec is allowed to
    # use is what this pins down.
    from operators.gen_3d_object.funcs.code_asset import part_bounds

    tilted = {
        "id": "t", "kind": "box", "size": (1.0, 0.2, 0.2), "at": (0.0, 0.0, 0.0),
        "rotation": (0.0, 0.0, 30.0), "segments": 16, "profile": None,
        "material": "default",
    }
    gate_low, gate_high = part_bounds(tilted)
    writer_low, writer_high = rotated_bounds(
        tilted["size"], tilted["at"], tilted["rotation"]
    )
    check(
        "the gates and the writer agree at 30 degrees",
        gate_low == writer_low and gate_high == writer_high,
    )
    positions, _n, _i = build_part(tilted)
    actual_high = max(point[1] for point in positions)
    check(
        "and the bound is the real mesh bound",
        abs(actual_high - gate_high[1]) < 1e-6,
        f"bound {gate_high[1]:.6f}, mesh {actual_high:.6f}",
    )

    # A lathe profile is not confined to the ±size/2 box the other kinds are:
    # it lives in its own coordinates, and measuring it as a unit box made
    # the scale gate disagree with the written mesh by the profile's own
    # extent. Found building a rifle whose barrel measured 1.018 m as a box
    # and 0.41 m as a mesh. Extrude likewise, and under rotation.
    lathe = {
        "id": "l", "kind": "lathe", "size": (1.0, 1.0, 1.0),
        "at": (0.0, 0.118, 0.125), "rotation": (0.0, 0.0, 0.0), "segments": 12,
        "profile": ((0.011, -0.185), (0.011, 0.100), (0.016, 0.225)),
        "material": "default",
    }
    l_low, l_high = part_bounds(lathe)
    l_pos, _n, _i = build_part(lathe)
    l_actual_low = [min(p[axis] for p in l_pos) for axis in range(3)]
    l_actual_high = [max(p[axis] for p in l_pos) for axis in range(3)]
    check(
        "a lathe is measured by its profile, not by its size",
        all(abs(l_low[a] - l_actual_low[a]) < 1e-9
            and abs(l_high[a] - l_actual_high[a]) < 1e-9 for a in range(3)),
        f"bound {l_low}/{l_high} vs mesh {l_actual_low}/{l_actual_high}",
    )

    extruded = {
        "id": "e", "kind": "extrude", "size": (1.0, 1.0, 0.048),
        "at": (0.0, 0.1, 0.0), "rotation": (10.0, 0.0, 0.0), "segments": 12,
        "profile": ((-0.02, -0.25), (0.012, -0.25), (0.012, -0.13), (-0.02, -0.13)),
        "material": "default",
    }
    e_low, e_high = part_bounds(extruded)
    e_pos, _n, _i = build_part(extruded)
    e_actual_low = [min(p[axis] for p in e_pos) for axis in range(3)]
    e_actual_high = [max(p[axis] for p in e_pos) for axis in range(3)]
    check(
        "an extrude under rotation is measured by its profile",
        all(abs(e_low[a] - e_actual_low[a]) < 1e-9
            and abs(e_high[a] - e_actual_high[a]) < 1e-9 for a in range(3)),
        f"bound {e_low}/{e_high} vs mesh {e_actual_low}/{e_actual_high}",
    )


def test_geom_chamfer_keeps_solid_closed() -> None:
    """A chamfer must change the silhouette without breaking the solid.

    Three properties, each of which a hand-wound bevel gets wrong in a way
    that a screenshot hides. Every undirected edge used exactly twice, or
    the mesh has a hole that only shows once something is behind it. Positive
    signed volume, or some faces wind inward and vanish under backface
    culling in an engine while looking fine in a viewer that does not cull.
    And still inside the unrotated extent box, which is what lets the scale
    and connectivity gates stay ignorant of this field entirely.
    """

    print("\na chamfered box is still a solid")
    from models.common.glb_writer import build_part, rotated_bounds
    from operators.gen_3d_object.funcs.code_asset import (
        MAX_CHAMFER, SpecError, estimate_triangles, validate_spec,
    )

    previous_volume = None
    for chamfer in (0.0, 0.02, 0.12, 0.3, 0.49):
        part = {
            "id": "b", "kind": "box", "size": (0.3, 0.1, 0.7),
            "at": (0.1, 0.2, 0.3), "rotation": (20.0, 35.0, 10.0),
            "segments": 16, "chamfer": chamfer, "material": "default",
        }
        positions, _normals, indices = build_part(part)
        triangles = len(indices) // 3

        edges: dict[frozenset, int] = {}
        for triangle in range(triangles):
            corners = [positions[indices[triangle * 3 + k]] for k in range(3)]
            keys = [tuple(round(v, 9) for v in c) for c in corners]
            for a, b in ((0, 1), (1, 2), (2, 0)):
                edge = frozenset((keys[a], keys[b]))
                edges[edge] = edges.get(edge, 0) + 1
        check(
            f"chamfer {chamfer}: every edge is shared by exactly two triangles",
            all(count == 2 for count in edges.values()),
            f"{sum(1 for c in edges.values() if c != 2)} edges are not shared twice",
        )

        volume = 0.0
        for triangle in range(triangles):
            a, b, c = [positions[indices[triangle * 3 + k]] for k in range(3)]
            volume += (
                a[0] * (b[1] * c[2] - b[2] * c[1])
                - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0])
            ) / 6.0
        check(
            f"chamfer {chamfer}: every face winds outward",
            volume > 0.0,
            f"signed volume {volume:+.6f}, so some faces face inward",
        )
        if previous_volume is not None:
            check(
                f"chamfer {chamfer}: cutting edges back removes material",
                volume < previous_volume,
                f"volume {volume:.6f} did not fall below {previous_volume:.6f}",
            )
        previous_volume = volume

        low, high = rotated_bounds(part["size"], part["at"], part["rotation"])
        check(
            f"chamfer {chamfer}: the solid stays inside the unchamfered bound",
            all(
                low[axis] - 1e-9 <= min(p[axis] for p in positions)
                and max(p[axis] for p in positions) <= high[axis] + 1e-9
                for axis in range(3)
            ),
            "a chamfered box escaped the box it was cut from",
        )
        check(
            f"chamfer {chamfer}: estimate == mesh",
            estimate_triangles({"parts": [part]}) == triangles,
            f"estimated {estimate_triangles({'parts': [part]})}, wrote {triangles}",
        )

    # Out of range is refused, not clamped: at 0.5 the bevels have eaten the
    # faces they were cutting back and the part is no longer a box, so a spec
    # that still calls it one would be describing something that is not there.
    for bad in (MAX_CHAMFER, 0.8, -0.1):
        try:
            validate_spec({
                "subject": "x", "units": "metres", "forward": "+z",
                "parts": [{"id": "b", "kind": "box", "size": (1.0, 1.0, 1.0),
                           "chamfer": bad}],
            })
            check(f"chamfer {bad} is refused", False, "it was accepted")
        except SpecError:
            check(f"chamfer {bad} is refused", True, "")


def test_geom_all_primitives_face_outward() -> None:
    """No primitive may be inside-out, and the writer's normals must agree.

    Written after the rifle's muzzle kept coming out wrong. The cause was
    not the muzzle: `_lathe`, `_cylinder`, `_sphere` and `_torus` all wound
    their quads as (a, b, b+1) where outward is (a, b+1, b), so every lathed,
    cylindrical, spherical and toroidal part in the library was inverted. A
    unit cylinder had a signed volume of -0.26 where the true answer is
    +0.785 — negative because it faced inward, and small because the caps
    were wound correctly and cancelled most of the wall.

    It survived every earlier check because none of them looked. The GLB was
    valid, the triangle counts matched, the bounds were right, and the viewer
    does not cull backfaces, so an inverted solid shades exactly like a
    correct one. It would have appeared first in an engine — the far side of
    the handoff, which is the expensive place to find it.

    Three properties, checked on all seven primitives plus the chamfered box:

    * signed volume positive — every face winds outward
    * no boundary edges — the surface is closed, so "inside" is defined
    * stored normals agree with the triangles' geometric facing, or lighting
      and culling disagree about which side is which
    """

    print("\nevery primitive is a closed, outward-facing solid")
    from models.common.glb_writer import build_part

    quarter_pi = math.pi / 4.0
    cases: tuple[tuple[str, str, dict[str, object], float | None], ...] = (
        ("box", "box", {}, 1.0),
        ("chamfered box", "box", {"chamfer": 0.15}, None),
        ("cylinder", "cylinder", {}, quarter_pi),
        ("cone", "cone", {}, quarter_pi / 3.0),
        ("sphere", "sphere", {}, 4.0 / 3.0 * math.pi * 0.125),
        ("torus", "torus", {}, None),
        ("lathe", "lathe",
         {"profile": ((0.0, -0.5), (0.5, -0.5), (0.5, 0.5), (0.0, 0.5))},
         quarter_pi),
        ("extrude", "extrude",
         {"profile": ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5))}, 1.0),
    )

    for label, kind, extra, expected_volume in cases:
        part = {
            "id": kind, "kind": kind, "size": (1.0, 1.0, 1.0),
            "at": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0),
            "segments": 96, "profile": None, "material": "default", **extra,
        }
        positions, normals, indices = build_part(part)
        triangles = len(indices) // 3

        volume = 0.0
        opposed = 0
        edges: dict[frozenset, int] = {}
        for triangle in range(triangles):
            a, b, c = [positions[indices[triangle * 3 + k]] for k in range(3)]
            volume += (
                a[0] * (b[1] * c[2] - b[2] * c[1])
                - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0])
            ) / 6.0

            edge1 = [b[i] - a[i] for i in range(3)]
            edge2 = [c[i] - b[i] for i in range(3)]
            cross = (
                edge1[1] * edge2[2] - edge1[2] * edge2[1],
                edge1[2] * edge2[0] - edge1[0] * edge2[2],
                edge1[0] * edge2[1] - edge1[1] * edge2[0],
            )
            # Degenerate triangles have no facing to disagree with. They are
            # unavoidable where a lathe profile touches the axis and a whole
            # ring collapses to a point.
            if math.sqrt(sum(v * v for v in cross)) > 1e-12:
                stored = normals[indices[triangle * 3]]
                if sum(cross[i] * stored[i] for i in range(3)) < 0.0:
                    opposed += 1

            keys = [tuple(round(v, 7) for v in point) for point in (a, b, c)]
            for first, second in ((0, 1), (1, 2), (2, 0)):
                edge = frozenset((keys[first], keys[second]))
                edges[edge] = edges.get(edge, 0) + 1

        check(
            f"{label}: signed volume is positive, so it is not inside-out",
            volume > 0.0,
            f"signed volume {volume:+.6f}",
        )
        check(
            f"{label}: the surface is closed",
            not any(count == 1 for count in edges.values()),
            f"{sum(1 for c in edges.values() if c == 1)} boundary edge(s)",
        )
        check(
            f"{label}: stored normals agree with the triangles' facing",
            opposed == 0,
            f"{opposed} of {triangles} triangles face against their normal",
        )
        if expected_volume is not None:
            # At 96 segments the inscribed tessellation is under the true
            # volume by well under a percent. Checking the value and not just
            # its sign is what catches a winding that is reversed on only
            # part of the surface, where the error partly cancels.
            check(
                f"{label}: volume converges on the analytic {expected_volume:.5f}",
                abs(volume - expected_volume) / expected_volume < 0.01,
                f"got {volume:.6f}, expected {expected_volume:.6f}",
            )


def test_geom_open_profile_refused() -> None:
    """A lathe profile whose ends leave the axis makes an open tube.

    This is the mistake the rifle's muzzle kept hitting, and it is easy to
    make because the profile reads perfectly sensibly: a list of radii down
    the length of a barrel. But a revolved profile only encloses a volume if
    it starts and ends on the axis of revolution, or the result is a pipe
    with two open ends — no inside, no watertight surface, and a hole through
    which the interior is visible.

    Refused at validation rather than reported by a gate, because unlike a
    proportion or a placement there is no version of this that was intended.
    """

    print("\na lathe profile must close on its axis")
    from operators.gen_3d_object.funcs.code_asset import SpecError, validate_spec

    def spec(profile: object) -> dict:
        return {
            "subject": "turned part", "units": "metres", "forward": "+z",
            "parts": [{
                "id": "p", "kind": "lathe", "size": (1.0, 1.0, 1.0),
                "profile": profile,
            }],
        }

    closed = ((0.0, -0.5), (0.5, -0.5), (0.5, 0.5), (0.0, 0.5))
    validate_spec(spec(closed))
    check("a profile that starts and ends on the axis is accepted", True, "")

    for label, profile in (
        ("both ends off the axis", ((0.5, -0.5), (0.5, 0.5))),
        ("the far end off the axis", ((0.0, -0.5), (0.5, -0.5), (0.5, 0.5))),
        ("the near end off the axis", ((0.5, -0.5), (0.5, 0.5), (0.0, 0.5))),
    ):
        try:
            validate_spec(spec(profile))
            check(f"{label} is refused", False, "it was accepted")
        except SpecError:
            check(f"{label} is refused", True, "")

    for label, profile in (
        ("a negative radius", ((0.0, -0.5), (-0.5, -0.5), (-0.5, 0.5), (0.0, 0.5))),
        ("a single point", ((0.0, 0.0),)),
        ("a non-pair entry", ((0.0, -0.5), (0.5,), (0.0, 0.5))),
    ):
        try:
            validate_spec(spec(profile))
            check(f"{label} is refused", False, "it was accepted")
        except SpecError:
            check(f"{label} is refused", True, "")

    # An extrude outline is a different shape of requirement: it is pushed
    # along z and capped, so it must be a closed loop of at least three
    # points, but it has no axis to touch.
    validate_spec({
        "subject": "extruded part", "units": "metres", "forward": "+z",
        "parts": [{
            "id": "p", "kind": "extrude", "size": (1.0, 1.0, 1.0),
            "profile": ((-0.5, -0.5), (0.5, -0.5), (0.0, 0.5)),
        }],
    })
    check("a three-point extrude outline is accepted", True, "")

    try:
        validate_spec({
            "subject": "extruded part", "units": "metres", "forward": "+z",
            "parts": [{
                "id": "p", "kind": "extrude", "size": (1.0, 1.0, 1.0),
                "profile": ((-0.5, -0.5), (0.5, -0.5)),
            }],
        })
        check("a two-point extrude outline is refused", False, "it was accepted")
    except SpecError:
        check("a two-point extrude outline is refused", True, "")


def test_geom_profile_winding_agnostic() -> None:
    """The direction a profile is traced must not change the solid.

    A stock outline traced clockwise and the same outline traced
    anticlockwise describe the same shape, and both are natural to write. So
    did the rifle's stock, which was traced clockwise and came out
    inside-out while every gate passed — the winding of the walls and caps
    depends on the direction of travel, and the writer had assumed one.

    The alternative to normalising was to document a required direction. That
    puts the burden on whoever writes the spec, for a property they cannot
    check by looking at the render, to prevent a defect that only appears
    after the handoff. Deriving it from the signed area instead means there
    is no wrong way to enter an outline.
    """

    print("\na profile may be traced either way round")
    from models.common.glb_writer import build_part

    def solid(kind: str, profile: tuple) -> tuple[int, float]:
        part = {
            "id": kind, "kind": kind, "size": (1.0, 1.0, 1.0),
            "at": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0),
            "segments": 24, "profile": profile, "material": "default",
        }
        positions, _normals, indices = build_part(part)
        volume = 0.0
        for triangle in range(len(indices) // 3):
            a, b, c = [positions[indices[triangle * 3 + k]] for k in range(3)]
            volume += (
                a[0] * (b[1] * c[2] - b[2] * c[1])
                - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0])
            ) / 6.0
        return len(indices), volume

    # An L-shaped outline, so the test would not pass by symmetry.
    outline = ((-0.4, -0.3), (0.5, -0.3), (0.5, 0.0), (0.1, 0.0),
               (0.1, 0.45), (-0.4, 0.45))
    forward_count, forward_volume = solid("extrude", outline)
    reversed_count, reversed_volume = solid("extrude", tuple(reversed(outline)))
    check(
        "an extrude outline traced clockwise gives the same solid",
        forward_count == reversed_count
        and abs(forward_volume - reversed_volume) < 1e-12,
        f"{forward_volume:+.9f} vs {reversed_volume:+.9f}",
    )
    check(
        "and that solid faces outward whichever way it was traced",
        forward_volume > 0.0 and reversed_volume > 0.0,
        f"{forward_volume:+.9f} / {reversed_volume:+.9f}",
    )

    # A stepped profile, written breech-to-muzzle and then muzzle-to-breech.
    stepped = ((0.0, -0.5), (0.30, -0.5), (0.30, -0.1),
               (0.18, 0.0), (0.18, 0.42), (0.0, 0.5))
    forward_count, forward_volume = solid("lathe", stepped)
    reversed_count, reversed_volume = solid("lathe", tuple(reversed(stepped)))
    check(
        "a lathe profile written from the far end gives the same solid",
        forward_count == reversed_count
        and abs(forward_volume - reversed_volume) < 1e-12,
        f"{forward_volume:+.9f} vs {reversed_volume:+.9f}",
    )
    check(
        "and that solid faces outward whichever end it started from",
        forward_volume > 0.0 and reversed_volume > 0.0,
        f"{forward_volume:+.9f} / {reversed_volume:+.9f}",
    )


def test_geom_windings_catches_inverted() -> None:
    """The gate must fail a solid that is inside-out, and pass one that is not.

    The gate exists because four primitives shipped inverted and every
    other gate passed them. So it is not enough to assert it passes correct
    geometry — that it did before the bug was fixed. It has to be shown
    failing on geometry that is actually inverted, which means reversing a
    real part's triangles and putting that through the gate.
    """

    print("\nthe windings gate catches an inverted part")
    from models.common import glb_writer
    from operators.gen_3d_object.funcs.code_asset import check_windings

    spec = {
        "subject": "turned and boxed part", "units": "metres", "forward": "+z",
        "parts": [
            {"id": "body", "kind": "box", "size": (0.4, 0.4, 0.4),
             "at": (0.0, 0.2, 0.0), "rotation": (0.0, 0.0, 0.0),
             "segments": 16, "profile": None, "material": "default",
             "chamfer": 0.1},
            {"id": "spindle", "kind": "lathe", "size": (1.0, 1.0, 1.0),
             "at": (0.0, 0.2, 0.0), "rotation": (0.0, 0.0, 0.0),
             "segments": 20, "material": "default",
             "profile": ((0.0, -0.2), (0.1, -0.2), (0.08, 0.15), (0.0, 0.2))},
        ],
    }

    report = check_windings(spec)
    check(
        "correct geometry passes the windings gate",
        report["ok"] and not report["inverted"] and not report["unclosed"],
        f"failures: {report['failures']}",
    )

    # Reverse every triangle, which is exactly the defect: same vertices,
    # same bounds, same triangle count, valid GLB, faces pointing inward.
    original = glb_writer.build_part

    def inverted(part: dict) -> tuple:
        positions, normals, indices = original(part)
        flipped = []
        for triangle in range(len(indices) // 3):
            a, b, c = indices[triangle * 3:triangle * 3 + 3]
            flipped.extend([a, c, b])
        return positions, normals, flipped

    glb_writer.build_part = inverted
    try:
        report = check_windings(spec)
    finally:
        glb_writer.build_part = original

    check(
        "an inside-out part fails the windings gate",
        not report["ok"] and len(report["inverted"]) == 2,
        f"ok={report['ok']}, inverted={report['inverted']}",
    )
    check(
        "and the failure says which parts and that they are inside-out",
        any("inside-out" in message for message in report["failures"])
        and any("body" in message and "spindle" in message
                for message in report["failures"]),
        f"failures: {report['failures']}",
    )

    # An unclosed part: a lathe profile whose ends leave the axis. Built
    # directly, bypassing validate_spec, which now refuses this at authoring
    # time — the gate is the second line of defence for a spec that reached
    # the writer another way.
    open_ended = {
        "subject": "open tube", "units": "metres", "forward": "+z",
        "parts": [{
            "id": "tube", "kind": "lathe", "size": (1.0, 1.0, 1.0),
            "at": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0),
            "segments": 16, "material": "default",
            "profile": ((0.2, -0.3), (0.2, 0.3)),
        }],
    }
    report = check_windings(open_ended)
    check(
        "a tube with open ends fails the windings gate",
        not report["ok"] and report["unclosed"],
        f"ok={report['ok']}, unclosed={report['unclosed']}",
    )


# ---- mesh: generated meshes joining as parts --------------------------------


def test_mesh_composes_like_primitive() -> None:
    """A `mesh` part must behave as the gates already expect a part to.

    The whole value of composing rather than generating whole is that
    downstream code does not branch on provenance: a generated grip is
    placed by `at`, measured by `part_bounds`, budgeted by
    `estimate_triangles` and checked by `windings` exactly like a box. So
    what is asserted here is *sameness* — every invariant the primitives
    already satisfy, satisfied by a mesh read off disk.

    The fixture is written by this repository's own writer rather than
    checked in as a binary, which also makes the round trip a real test: a
    known mesh out through `write_spec_glb`, back in through
    `read_glb_mesh`, and the triangle count and winding have to survive.

    The one thing that is deliberately *not* the same is the scaling rule.
    A mesh is fitted by a single factor so it keeps the proportions it was
    generated with, because stretching a moulded shape to fill a box is a
    worse defect than a shape that is not exactly the requested thickness.
    That makes `size` a request rather than an extent, which is why the
    bound has to come from the vertices.
    """

    print("\na generated mesh composes like a primitive")
    from models.common.glb_writer import (
        build_part, effective_size, rotated_bounds, write_spec_glb,
    )
    from operators.gen_3d_object.funcs.code_asset import (
        MESH_KIND, SpecError, check_windings, estimate_triangles, run_gates,
        validate_spec,
    )

    with tempfile.TemporaryDirectory() as directory:
        # An L-shaped fixture: not symmetric on any axis, so a bound computed
        # by the wrong rule cannot match by luck.
        fixture = write_spec_glb(
            {
                "subject": "fixture", "units": "metres", "forward": "+z",
                "height_metres": 1.0, "materials": {},
                "parts": [
                    {"id": "tall", "kind": "box", "size": (0.4, 1.0, 0.3),
                     "at": (0.0, 0.0, 0.0), "rotation": (0.0, 0.0, 0.0),
                     "segments": 16, "profile": None, "material": "d"},
                    {"id": "foot", "kind": "box", "size": (0.9, 0.2, 0.3),
                     "at": (0.25, -0.4, 0.0), "rotation": (0.0, 0.0, 0.0),
                     "segments": 16, "profile": None, "material": "d"},
                ],
            },
            str(Path(directory) / "fixture.glb"),
        )
        fixture_triangles = 24        # two sharp boxes

        def part(size, rotation=(0.0, 0.0, 0.0), at=(0.0, 0.2, 0.0)):
            return {
                "id": "generated", "kind": MESH_KIND, "source": fixture,
                "size": size, "at": at, "rotation": rotation,
                "segments": 16, "profile": None, "material": "default",
            }

        positions, normals, indices = build_part(part((0.5, 0.5, 0.5)))
        check(
            "the fixture survives the round trip with its triangles intact",
            len(indices) // 3 == fixture_triangles,
            f"wrote {fixture_triangles}, read back {len(indices) // 3}",
        )
        check(
            "and with a normal per vertex",
            len(normals) == len(positions),
            f"{len(positions)} positions, {len(normals)} normals",
        )

        check(
            "the triangle estimate reads the file rather than guessing",
            estimate_triangles({"parts": [part((0.5, 0.5, 0.5))]})
            == fixture_triangles,
            f"estimated "
            f"{estimate_triangles({'parts': [part((0.5, 0.5, 0.5))]})}",
        )

        # The bound must equal the mesh at any angle. A box's bound can be had
        # from its eight transformed corners; a mesh that does not reach its
        # corners cannot, and the discrepancy only appears once rotated.
        for rotation in ((0.0, 0.0, 0.0), (0.0, 90.0, 0.0), (-8.0, 0.0, 0.0),
                         (23.0, 41.0, 17.0)):
            candidate = part((0.5, 0.5, 0.5), rotation=rotation)
            placed, _normals, _indices = build_part(candidate)
            actual_low = [min(p[axis] for p in placed) for axis in range(3)]
            actual_high = [max(p[axis] for p in placed) for axis in range(3)]
            low, high = rotated_bounds(
                candidate["size"], candidate["at"], rotation,
                kind=MESH_KIND, source=fixture,
            )
            check(
                f"the bound equals the mesh at rotation {rotation}",
                all(
                    abs(low[axis] - actual_low[axis]) < 1e-9
                    and abs(high[axis] - actual_high[axis]) < 1e-9
                    for axis in range(3)
                ),
                f"bound {[round(v, 6) for v in low]}..."
                f"{[round(v, 6) for v in high]} against mesh "
                f"{[round(v, 6) for v in actual_low]}..."
                f"{[round(v, 6) for v in actual_high]}",
            )

        # A non-uniform size is reduced to its largest component, and both the
        # writer and the bound have to agree about that. Disagreeing is the
        # defect the lathe bounds already produced once.
        check(
            "a non-uniform size on a mesh part collapses to one factor",
            effective_size((0.5, 0.1, 0.2), MESH_KIND) == (0.5, 0.5, 0.5),
            f"got {effective_size((0.5, 0.1, 0.2), MESH_KIND)}",
        )
        stretched, _n, _i = build_part(part((0.5, 0.1, 0.2)))
        uniform, _n, _i = build_part(part((0.5, 0.5, 0.5)))
        check(
            "so it writes the same mesh as the uniform request",
            all(
                abs(stretched[index][axis] - uniform[index][axis]) < 1e-12
                for index in range(len(uniform)) for axis in range(3)
            ),
            "a non-uniform size changed the geometry",
        )

        # `windings` treats the mesh like everything else, because it is
        # measuring the evaluated triangles and does not know the provenance.
        report = check_windings({"parts": [part((0.5, 0.5, 0.5))]})
        check(
            "the windings gate passes a well-formed generated part",
            report["ok"] and not report["inverted"],
            f"failures: {report['failures']}",
        )

        # And the composition as a whole passes, which is the claim: a spec
        # mixing the two kinds is not a special case anywhere.
        mixed = validate_spec({
            "subject": "bracket with a moulded pad", "units": "metres",
            "forward": "+z", "asset_type": "prop", "height_metres": 0.5,
            "materials": {},
            "parts": [
                {"id": "plate", "kind": "box", "size": (0.3, 0.02, 0.3),
                 "at": (0.0, 0.01, 0.0), "material": "default",
                 "chamfer": 0.1},
                {"id": "pad", "kind": MESH_KIND, "source": fixture,
                 "size": (0.5, 0.5, 0.5), "at": (0.0, 0.27, 0.0),
                 "material": "default"},
            ],
        })
        gates = run_gates(mixed)
        check(
            "a spec mixing primitives and generated parts passes every gate",
            gates["ok"],
            f"failures: {gates['failures']}",
        )
        check(
            "and the provenance gate reports which parts were generated",
            [
                entry["id"]
                for report in gates["reports"] if report["gate"] == "provenance"
                for entry in report["generated_parts"]
            ] == ["pad"],
            f"reports: {[r['gate'] for r in gates['reports']]}",
        )

        # Refusals. A missing source and a source on a primitive are both
        # authoring mistakes with no version that was intended: the first has
        # no geometry at all, and the second is a generated part that was
        # meant to be one and silently is not.
        for label, faulty in (
            ("a mesh part with no source", {"id": "p", "kind": MESH_KIND,
                                            "size": (0.5, 0.5, 0.5)}),
            ("a mesh part whose source is missing", {
                "id": "p", "kind": MESH_KIND, "size": (0.5, 0.5, 0.5),
                "source": str(Path(directory) / "absent.glb")}),
            ("a source on a box", {"id": "p", "kind": "box",
                                   "size": (0.5, 0.5, 0.5),
                                   "source": fixture}),
        ):
            try:
                validate_spec({
                    "subject": "x", "units": "metres", "forward": "+z",
                    "parts": [faulty],
                })
                check(f"{label} is refused", False, "it was accepted")
            except SpecError:
                check(f"{label} is refused", True, "")


def test_mesh_mirror_keeps_faces_outward() -> None:
    """`mirror` must reflect geometry *and* keep the surface facing outward.

    A generated pair arrives as one hand. The fetched pauldron's mass leans 0.32
    of its half-width toward -x — it is a left shoulder — and the same mesh on
    both shoulders had the right one's lames hanging inboard over the ribs. Every
    gate passed it: the chirality gate checks that the two *positions* mirror,
    which they did, so the wrong hand was invisible to everything but a render.

    Not expressible as a rotation, which is why it is its own field: 180 degrees
    about y would face the lames outboard and swap front for back as well.

    The winding is the part that can silently go wrong. A reflection flips
    handedness, so negating a coordinate without reversing each triangle turns
    the whole surface inside out — it still builds, still measures the same, and
    renders as a part lit from within.
    """

    print("\na generated pair that arrived as one hand can be mirrored")
    from operators.gen_3d_object.funcs.code_asset import (
        SpecError, build_code_asset, validate_spec)

    # An asymmetric solid, so a mirror is detectable at all: a wedge whose
    # profile leans one way. A symmetric part would pass either way round.
    wedge = [[-0.05, 0.0], [0.05, 0.0], [0.02, 0.06], [-0.05, 0.03]]

    from operators.gen_3d_object.funcs.code_asset_templates import compose

    def spec_for(mirror):
        part = {"id": "wedge", "kind": "extrude", "size": [1.0, 1.0, 0.04],
                "at": [0.0, 0.03, 0.0], "profile": wedge, "material": "steel",
                "segments": 8}
        if mirror:
            part["mirror"] = mirror
        return compose.compose(
            subject="a wedge", body=[part], height_metres=0.06,
            asset_type="prop",
            materials={"steel": {"baseColor": [0.6, 0.6, 0.6, 1.0]}})

    from models.common.glb_utils import read_glb_mesh

    def centroid(path):
        """Mean vertex x. Bounds cannot see a reflection of a centred part —
        they are identical either way round — so the mass is what to measure."""
        mesh = read_glb_mesh(Path(path).read_bytes())
        points = list(mesh["positions"])
        return round(sum(point[0] for point in points) / len(points), 6)

    with tempfile.TemporaryDirectory() as tmp:
        plain_path, flipped_path = Path(tmp) / "a.glb", Path(tmp) / "b.glb"
        plain = build_code_asset(spec_for(None), str(plain_path))
        flipped = build_code_asset(spec_for("x"), str(flipped_path))
        plain_lean, flipped_lean = centroid(plain_path), centroid(flipped_path)

    check("a mirrored part builds", flipped["ok"], str(flipped.get("failures")))
    check(
        "and the windings gate is satisfied, so the surface still faces out",
        not any("inward" in str(note).lower() or "inverted" in str(note).lower()
                for note in flipped.get("failures", [])),
        f"windings complained: {flipped.get('failures')}",
    )
    # The real assertion: a reflection is not a no-op on an asymmetric part.
    # Bounds are unchanged by design — the profile is centred — so this compares
    # where the mass went, which is what a mirror actually moves.
    check(
        "the two are the same size",
        [round(v, 6) for v in plain["bounds"]["extents"]]
        == [round(v, 6) for v in flipped["bounds"]["extents"]],
        f"{plain['bounds']['extents']} vs {flipped['bounds']['extents']}",
    )
    check(
        "and the mirrored copy's mass leans the other way",
        plain_lean != 0.0 and abs(plain_lean + flipped_lean) < 1e-9,
        f"plain leans {plain_lean}, mirrored {flipped_lean} — a mirror that "
        "changes nothing is a mirror that was not applied",
    )

    # An axis that is not an axis, refused where it is written.
    try:
        validate_spec(spec_for("sideways"))
        check("a bad mirror axis is refused", False, "it was accepted")
    except SpecError as exc:
        check("a bad mirror axis is refused", "'x', 'y' or 'z'" in str(exc),
              f"got {exc}")


def test_mesh_texture_survives() -> None:
    """A generated part's UVs and base-colour image must reach the output.

    This is most of what a generated part contributes. A grip's stippling
    and a car shell's panel decals live in the atlas, not the mesh, so a
    composition that drops the texture has paid for geometry and thrown
    away the reason it was fetched — while still looking plausible, because
    the part inherits the spec's flat PBR factors and merely appears
    undecorated rather than broken.

    Four properties, each of which fails silently:

    * UVs are written, and only for the parts that have them. A primitive
      given arbitrary UVs samples an arbitrary corner of somebody else's
      atlas, which is worse than no texture at all.
    * the image bytes are carried, so the output is self-contained. A GLB
      referencing an external file is not something an engine import can use.
    * one copy per source, however many times the part is placed. Four
      identical wheels sharing a 3 MB atlas is 3 MB; not sharing it is 12.
    * a metallic-roughness *map* means its factors cannot be inherited.
      Measured on the fetched grip: `metallicFactor 1.0, roughnessFactor
      1.0`, which are glTF defaults meant to multiply a map. Copied across
      without the map they scale, a stippled polymer grip renders as
      sandblasted steel.
    """

    print("\na fetched texture survives composition")
    from models.common.glb_utils import glb_json_chunk, read_glb_mesh
    from models.common.glb_writer import load_mesh_asset, write_spec_glb

    # A fixture with a base-colour texture, built by hand rather than fetched
    # so the test needs no network and no checked-in binary. A 1x1 PNG is
    # enough: what is under test is the plumbing, not the image.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080200000090"
        "7753de0000000c4944415408d763f8cfc0000003010100189dd1a2000000"
        "0049454e44ae426082"
    )

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "textured.glb"
        _write_textured_fixture(source, png)

        asset = load_mesh_asset(str(source))
        check(
            "the fixture's UVs are read back",
            asset["has_uvs"] and len(asset["uvs"]) == len(asset["positions"]),
            f"has_uvs={asset['has_uvs']}, "
            f"{len(asset['uvs'])} uvs for {len(asset['positions'])} vertices",
        )
        check(
            "and its base-colour image bytes",
            asset["materials"] and asset["materials"][0]["image"] == png,
            f"materials={[m['name'] for m in asset['materials']]}",
        )
        check(
            "a metallic-roughness map is carried, so its factors stand",
            asset["materials"][0]["factors_from"] == "file"
            and asset["materials"][0]["metallic"] == 1.0
            and asset["materials"][0]["mrImage"] is not None,
            f"factors_from={asset['materials'][0]['factors_from']}, "
            f"metallic={asset['materials'][0]['metallic']}, "
            f"mrImage={asset['materials'][0]['mrImage'] is not None}",
        )
        # The factors are only trustworthy *because* the map came with them: an
        # exporter writing those channels to a texture leaves the factors at
        # glTF's 1.0 to multiply it. Taking the colour alone and inheriting
        # `metallicFactor 1.0` would render a polymer pad as steel, so a
        # declared map whose bytes cannot be read still has to fall back.
        no_bytes = {
            "materials": [{
                "pbrMetallicRoughness": {
                    "metallicFactor": 1.0, "roughnessFactor": 1.0,
                    "metallicRoughnessTexture": {"index": 7},
                },
            }],
            "textures": [], "images": [], "bufferViews": [],
        }
        from models.common.glb_utils import _read_materials

        fallback = _read_materials(no_bytes, b"")[0]
        check(
            "a declared map that cannot be read falls back to dielectric",
            fallback["factors_from"] == "assumed"
            and fallback["metallic"] == 0.0,
            f"factors_from={fallback['factors_from']}, "
            f"metallic={fallback['metallic']}",
        )

        # Compose: one primitive, and the same fetched part placed twice.
        def mesh_part(part_id: str, at: tuple) -> dict:
            return {
                "id": part_id, "kind": "mesh", "source": str(source),
                "size": (0.3, 0.3, 0.3), "at": at, "rotation": (0.0, 0.0, 0.0),
                "segments": 16, "profile": None, "material": "steel",
                "chamfer": 0.0, "long_axis": None,
            }

        out = write_spec_glb(
            {
                "subject": "two pads on a plate", "units": "metres",
                "forward": "+z", "height_metres": 0.5,
                "materials": {"steel": {"baseColor": [0.5, 0.5, 0.55, 1.0],
                                        "metallic": 1.0, "roughness": 0.3}},
                "parts": [
                    {"id": "plate", "kind": "box", "size": (0.6, 0.02, 0.6),
                     "at": (0.0, 0.01, 0.0), "rotation": (0.0, 0.0, 0.0),
                     "segments": 16, "profile": None, "material": "steel",
                     "chamfer": 0.1, "source": None, "long_axis": None},
                    mesh_part("pad-a", (-0.2, 0.16, 0.0)),
                    mesh_part("pad-b", (0.2, 0.16, 0.0)),
                ],
            },
            str(Path(directory) / "composed.glb"),
        )
        document = glb_json_chunk(Path(out).read_bytes())

        textured = [
            "TEXCOORD_0" in primitive["attributes"]
            for mesh in document["meshes"] for primitive in mesh["primitives"]
        ]
        check(
            "UVs are written for the fetched parts and not the primitive",
            textured == [False, True, True],
            f"per-primitive TEXCOORD_0: {textured}",
        )
        # Two images, not one: base colour and metallic-roughness. The second
        # is what makes a steel plate read as steel — dropping it left every
        # generated piece of the knight's armour rendering as grey plastic,
        # because dielectric factors were being substituted for a map that was
        # sitting in the source file all along.
        check(
            "both maps travel inside the GLB, so it is self-contained",
            len(document.get("images", [])) == 2
            and all("bufferView" in image for image in document["images"])
            and [image["name"] for image in document["images"]] == [
                "pad-a-basecolour", "pad-a-metallicroughness"],
            f"images={[i.get('name') for i in document.get('images', [])]}",
        )
        check(
            "one copy of each map for two placements of the same source",
            len(document.get("textures", [])) == 2,
            f"{len(document.get('textures', []))} textures for two placements "
            "of a source with two maps",
        )
        check(
            "and a sampler is stated rather than left to the importer",
            len(document.get("samplers", [])) == 1,
            f"samplers={document.get('samplers')}",
        )
        check(
            "the primitive keeps the spec's own material",
            any(material["name"] == "steel"
                for material in document["materials"]),
            f"materials={[m['name'] for m in document['materials']]}",
        )

        # A map is sized to the part, because a texture is only worth the pixels
        # that land on screen. Every piece fetched for the knight arrived at
        # 2048x2048 whatever it was: the 0.13 m gauntlet carried the same atlas
        # as the 1.72 m body, thirteen times the density, and the asset came to
        # 33.9 MB. Sized per part it is 3.8 MB with the body still at 2048.
        from models.common.glb_writer import _texture_budget

        budgets = [(1.72, 2048), (0.85, 1024), (0.66, 512), (0.26, 256),
                   (0.13, 128)]
        for metres, expected in budgets:
            check(
                f"a {metres:.2f} m part earns {expected} px",
                _texture_budget(metres) == expected,
                f"got {_texture_budget(metres)}",
            )
        check(
            "a part smaller than the floor still gets legible pixels",
            _texture_budget(0.001) == 128,
            f"got {_texture_budget(0.001)}",
        )
        check(
            "and nothing earns more than the ceiling",
            _texture_budget(50.0) == 2048,
            f"got {_texture_budget(50.0)}",
        )

        back = read_glb_mesh(Path(out).read_bytes())
        check(
            "the composed file round-trips with its UVs",
            back["has_uvs"] and len(back["uvs"]) == len(back["positions"]),
            f"has_uvs={back['has_uvs']}",
        )


# ---- route: which route a subject takes -------------------------------------


def test_route_declines_rather_than_guesses() -> None:
    print("\nrouting — declining is a result")
    from operators.gen_3d_object.funcs.code_asset import suits_code_asset

    crate = suits_code_asset("wooden supply crate")
    check("a crate routes to code", crate["suitable"] and crate["route"] == "code")

    face = suits_code_asset("human face", asset_type="avatar")
    check(
        "a face routes to generation",
        not face["suitable"] and face["route"] == "generate",
        f"got {face}",
    )
    check("declining says why", "organic" in face["reason"])

    golem = suits_code_asset("stone golem creature")
    check(
        "a subject reading both ways is ambiguous, not guessed",
        golem["route"] == "ambiguous",
        f"got {golem}",
    )

    unknown = suits_code_asset("zorblatt")
    check("an unknown subject is ambiguous", unknown["route"] == "ambiguous")

    # This used to assert a caller could pass a `Vocabulary` of 141 words —
    # substitution of *content* inside four categories the router had hardcoded,
    # so a domain that did not fit them had nowhere to go. What is substituted
    # now is the *judgement*: a strategy says how a subject assembles, and the
    # route follows.
    from operators.gen_3d_object.funcs.code_asset_templates import routing

    def zorblatt(subject: str, asset_type: str = "prop"):
        if "zorblatt" not in routing.words(subject):
            return None
        return routing.Claim(
            topology=routing.COMPOSED,
            strength=1.0,
            evidence=("zorblatt",),
            reason="a zorblatt is a stack of plates",
        )

    routed = suits_code_asset("zorblatt", strategies=[("zorblatt", zorblatt)])
    check(
        "a caller's own strategy decides the route",
        routed["route"] == "code" and routed["suitable"]
        and routed["topology"] == routing.COMPOSED,
        f"got {routed['route']} at {routed['confidence']}",
    )
    check(
        "and passing strategies leaves the registry alone",
        suits_code_asset("zorblatt")["route"] == "ambiguous"
        and "zorblatt" not in routing.registered(),
        "a per-call strategy leaked into the global registry",
    )
    # A structural claim is not outvoted by counted evidence, whoever makes it:
    # the tiering is in the router, not in the shipped strategies.
    def wyrm(subject: str, asset_type: str = "prop"):
        if "wyrm" not in routing.words(subject):
            return None
        return routing.Claim(
            topology=routing.NESTED,
            strength=1.0,
            evidence=("wyrm",),
            tier=routing.STRUCTURAL,
            reason="a wyrm is a host that its barding is fitted to",
        )

    from operators.gen_3d_object.funcs.code_asset_templates import rigid_template

    barded = suits_code_asset(
        "wyrm with steel plate barding", asset_type="avatar",
        strategies=[("wyrm", wyrm), ("rigid", rigid_template.claim)],
    )
    check(
        "a caller's structural claim outranks counted evidence",
        barded["route"] == "generate" and barded["topology"] == routing.NESTED,
        f"got {barded['route']} via {barded['claimed_by']}",
    )


def test_route_new_domain_registers() -> None:
    """A domain nobody anticipated must route by *registering*, not by editing.

    The test the previous design could not pass. That version let a caller pass
    a longer word list, but the four categories those words went into were
    hardcoded in the function reading them — substituting content inside a fixed
    taxonomy is not extensibility.

    Nothing in `code_asset.py`, `routing.py` or either `*_template` package is
    edited to make this work.
    """

    print("\na new domain routes without editing the router")
    from operators.gen_3d_object.funcs.code_asset import suits_code_asset
    from operators.gen_3d_object.funcs.code_asset_templates import routing

    before = routing.registered()

    def submarine(subject: str, asset_type: str = "prop"):
        seen = routing.words(subject)
        found = tuple(word for word in ("submarine", "sub", "hull", "conning",
                                        "periscope", "bathysphere") if word in seen)
        if not found:
            return None
        return routing.Claim(
            topology=routing.COMPOSED,
            strength=float(len(found)),
            evidence=found,
            builder="fleet.templates.submarine",
            reason=f"a {found[0]} is a hull with fittings bolted along it",
        )

    routing.register("submarine", submarine)
    try:
        result = suits_code_asset("bathysphere")
        check(
            "a registered domain decides the route",
            result["route"] == "code" and result["claimed_by"] == "submarine",
            f"got {result['route']} via {result['claimed_by']}",
        )
        check(
            "and carries the builder that can make it",
            result["builder"] == "fleet.templates.submarine",
            f"got {result['builder']!r}",
        )

        # A new domain that changed unrelated routes would be a regression
        # disguised as a feature.
        for subject, expected in (("wooden crate", "code"),
                                  ("oak tree", "generate"),
                                  ("woman knight", "generate"),
                                  ("knight helmet", "code")):
            check(
                f"registering a domain leaves {subject!r} at {expected}",
                suits_code_asset(subject)["route"] == expected,
                f"got {suits_code_asset(subject)['route']}",
            )

        # Two strategies on one name makes the route depend on import order,
        # which presents as unstable rather than wrong.
        try:
            routing.register("submarine", submarine)
            check("a duplicate registration is refused", False, "it was accepted")
        except ValueError as exc:
            check(
                "a duplicate registration is refused, and says how to override",
                "replace=True" in str(exc),
                f"got {exc}",
            )
    finally:
        routing.unregister("submarine")

    check(
        "unregistering leaves the registry as it was",
        routing.registered() == before,
        f"{before} -> {routing.registered()}",
    )
    check(
        "and the domain stops deciding once withdrawn",
        suits_code_asset("bathysphere")["route"] == "ambiguous",
    )

    # A raising strategy must neither decide the route by crashing nor be
    # swallowed: the failure names it.
    def broken(subject: str, asset_type: str = "prop"):
        raise KeyError("chart not loaded")

    try:
        suits_code_asset("anything", strategies=[("broken", broken)])
        check("a failing strategy is reported", False, "it passed silently")
    except RuntimeError as exc:
        check(
            "a failing strategy is reported with its name",
            "broken" in str(exc),
            f"got {exc}",
        )


def test_route_wearer_routes_to_generate() -> None:
    """A figure in armour is a figure; a helmet on its own is a helmet.

    Found while building the knight demo. `suits_code_asset("female knight
    in plate armour", asset_type="avatar")` returned `code` at 0.9
    confidence, because "armour" is in the hard-surface list and neither
    "knight" nor "female" was in the organic one. The balance of evidence
    was counting vocabulary rather than reading what the object is — armour
    on a person takes its curvature from a torso, and a torso is not
    arithmetic over primitives.

    The interesting part is that the fix must not over-reach. Each piece of
    that knight's kit is a perfectly good spec subject, which is what makes
    the hybrid route work: generate the head and cuirass, state the greaves
    and the sword. So a wearer word plus an item word has to route to
    `code`, not away from it.
    """

    print("\na wearer routes to generation, their kit does not")
    from operators.gen_3d_object.funcs.code_asset import suits_code_asset

    for subject, asset_type in (
        ("female knight in plate armour", "avatar"),
        ("woman knight", "avatar"),
        ("armoured warrior", "avatar"),
    ):
        result = suits_code_asset(subject, asset_type=asset_type)
        check(
            f"{subject!r} routes to generation",
            result["route"] == "generate" and not result["suitable"],
            f"got {result['route']} at {result['confidence']}",
        )

    for subject in ("knight helmet", "plate armour cuirass", "steel greaves",
                    "knight sword", "warrior shield"):
        result = suits_code_asset(subject, asset_type="prop")
        check(
            f"{subject!r} still routes to code",
            result["route"] == "code" and result["suitable"],
            f"got {result['route']} at {result['confidence']}",
        )

    # Whole-word matching, because "man" is inside "human". With substrings
    # this branch claimed a face was someone wearing kit, and the reason it
    # gave said so — a wrong answer delivered confidently.
    face = suits_code_asset("human face", asset_type="avatar")
    check(
        "a face routes to generation as organic, not as a wearer",
        face["route"] == "generate" and "organic" in face["reason"],
        f"got {face['route']}: {face['reason'][:70]}",
    )

    # Unrelated subjects must be untouched by all of this.
    for subject, expected in (("wooden crate", "code"), ("oak tree", "generate"),
                              ("stone golem creature", "ambiguous")):
        result = suits_code_asset(subject)
        check(
            f"{subject!r} still routes to {expected}",
            result["route"] == expected,
            f"got {result['route']}",
        )


# ---- assembly: holding parts together ---------------------------------------


def test_assembly_attach_solves_faces() -> None:
    """`attach` must put one part's face against another's, and keep it there.

    Absolute `at` is the wrong primitive for a relationship, and every gap in
    the assets built before this proved it: a muzzle 9 mm off its barrel, a
    sabaton 16 mm under its shin, a sling loop 26 mm past a rail. Each was
    found by the connectivity gate, measured by hand, and fixed with a number
    that went stale the moment a neighbour moved.

    The case that matters most is a *rotated* target. A part's occupied extent
    is not its `size` once it is turned, so an author computing contact by
    hand has to redo the trigonometry — which is exactly the arithmetic the
    resolver should be doing.
    """

    print("\nattachment solves a surface relationship")
    from operators.gen_3d_object.funcs.code_asset import part_bounds, validate_spec

    spec = validate_spec({
        "subject": "stacked", "units": "metres", "forward": "+z",
        "height_metres": 1.0, "materials": {},
        "parts": [
            {"id": "base", "kind": "box", "size": [0.4, 0.2, 0.4],
             "at": [0, 0.1, 0]},
            {"id": "mid", "kind": "box", "size": [0.3, 0.3, 0.3],
             "attach": {"to": "base", "axis": "y"}},
            {"id": "top", "kind": "box", "size": [0.2, 0.2, 0.2],
             "attach": {"to": "mid", "axis": "y", "gap": 0.02}},
            {"id": "under", "kind": "box", "size": [0.1, 0.1, 0.1],
             "attach": {"to": "base", "axis": "y", "my": "max",
                        "their": "min"}},
            {"id": "side", "kind": "box", "size": [0.1, 0.1, 0.1],
             "attach": {"to": "base", "axis": "x", "my": "min",
                        "their": "max", "offset": [0, 0, 0.05]}},
        ],
    })
    bounds = {part["id"]: part_bounds(part) for part in spec["parts"]}

    check(
        "an attached part's face meets its target's exactly",
        abs(bounds["mid"][0][1] - bounds["base"][1][1]) < 1e-9,
        f"mid starts at {bounds['mid'][0][1]}, base ends at {bounds['base'][1][1]}",
    )
    check(
        "a gap is honoured to the millimetre",
        abs((bounds["top"][0][1] - bounds["mid"][1][1]) - 0.02) < 1e-9,
        f"gap is {bounds['top'][0][1] - bounds['mid'][1][1]}",
    )
    check(
        "attaching by the opposite face hangs the part underneath",
        abs(bounds["under"][1][1] - bounds["base"][0][1]) < 1e-9,
        f"under ends at {bounds['under'][1][1]}, base starts at {bounds['base'][0][1]}",
    )
    check(
        "attachment works on any axis, not just y",
        abs(bounds["side"][0][0] - bounds["base"][1][0]) < 1e-9,
        f"side starts at {bounds['side'][0][0]}, base ends at {bounds['base'][1][0]}",
    )
    check(
        "and `offset` shifts along the other axes",
        abs((bounds["side"][0][2] + bounds["side"][1][2]) / 2 - 0.05) < 1e-9,
        f"side z centre is {(bounds['side'][0][2] + bounds['side'][1][2]) / 2}",
    )

    # The one an author cannot do by hand without redoing the trigonometry.
    rotated = validate_spec({
        "subject": "rotated", "units": "metres", "forward": "+z",
        "height_metres": 1.0, "materials": {},
        "parts": [
            {"id": "tilted", "kind": "box", "size": [0.4, 0.2, 0.4],
             "at": [0, 0.3, 0], "rotation": [0, 0, 30]},
            {"id": "cap", "kind": "box", "size": [0.1, 0.1, 0.1],
             "attach": {"to": "tilted", "axis": "y"}},
        ],
    })
    rotated_bounds_by_id = {p["id"]: part_bounds(p) for p in rotated["parts"]}
    check(
        "attachment tracks a rotated target's real extent",
        abs(rotated_bounds_by_id["cap"][0][1]
            - rotated_bounds_by_id["tilted"][1][1]) < 1e-9,
        f"cap {rotated_bounds_by_id['cap'][0][1]} vs "
        f"tilted {rotated_bounds_by_id['tilted'][1][1]}",
    )


def test_assembly_parent_into_nodes() -> None:
    """`parent` must become a glTF child, and must not transform twice.

    A named part is of no use to gameplay if rotating the limb leaves its
    armour behind, so the hierarchy has to survive export — the claim this
    route makes over a fused generated mesh is precisely that parts stay
    addressable *and* connected.

    The double transform is the trap, and it was live: geometry is built in
    world space because that is what the gates measure, so a child node
    carrying its parent's translation applies the offset twice. Caught by
    reading the file back through its scene graph rather than trusting the
    resolver — a plate placed at y 0.50..0.60 rendered at 0.40..0.80. The
    file was valid and the triangle counts matched, which is the same shape
    of defect as the inverted windings.

    Fixed by moving the child's vertices into the parent's frame rather than
    by dropping the node translation. Dropping it renders identically and
    leaves a useless hierarchy: the parent would swing the child about a
    pivot outside it.
    """

    print("\nnesting survives into the glTF")
    from models.common.glb_utils import glb_json_chunk, read_glb_mesh
    from models.common.glb_writer import write_spec_glb
    from operators.gen_3d_object.funcs.code_asset import part_bounds, validate_spec

    spec = validate_spec({
        "subject": "nested", "units": "metres", "forward": "+z",
        "height_metres": 1.0, "materials": {},
        "parts": [
            # Child declared before its parent, deliberately: requiring
            # dependency order would put the graph back in the author's head.
            {"id": "plate", "kind": "box", "size": [0.12, 0.1, 0.12],
             "parent": "arm", "at": [0, -0.05, 0]},
            {"id": "arm", "kind": "box", "size": [0.08, 0.4, 0.08],
             "at": [0.2, 0.6, 0]},
        ],
    })

    bounds = {part["id"]: part_bounds(part) for part in spec["parts"]}
    check(
        "a child declared before its parent still resolves",
        abs((bounds["plate"][0][0] + bounds["plate"][1][0]) / 2 - 0.2) < 1e-9,
        f"plate x centre {(bounds['plate'][0][0] + bounds['plate'][1][0]) / 2}",
    )

    with tempfile.TemporaryDirectory() as directory:
        out = write_spec_glb(spec, str(Path(directory) / "nested.glb"))
        document = glb_json_chunk(Path(out).read_bytes())
        names = [node["name"] for node in document["nodes"]]

        check(
            "only the root appears in the scene",
            [names[index] for index in document["scenes"][0]["nodes"]] == ["arm"],
            f"scene roots {[names[i] for i in document['scenes'][0]['nodes']]}",
        )
        check(
            "and the child hangs off its parent",
            [names[index] for index
             in document["nodes"][names.index("arm")].get("children", [])]
            == ["plate"],
            f"arm children {document['nodes'][names.index('arm')].get('children')}",
        )

        # The measurement that caught the double transform: what the scene
        # graph actually draws, against what the resolver claimed.
        rendered = read_glb_mesh(Path(out).read_bytes())
        low = [min(part_bounds(p)[0][axis] for p in spec["parts"])
               for axis in range(3)]
        high = [max(part_bounds(p)[1][axis] for p in spec["parts"])
                for axis in range(3)]
        # 1e-6, not 1e-9: GLB stores positions as float32, so a round trip
        # loses about eight significant figures and a tighter bound would be
        # testing the format rather than the transform.
        check(
            "the composed scene graph draws what the resolver placed",
            all(abs(rendered["low"][axis] - low[axis]) < 1e-6
                and abs(rendered["high"][axis] - high[axis]) < 1e-6
                for axis in range(3)),
            f"rendered {[round(v, 6) for v in rendered['low']]}.."
            f"{[round(v, 6) for v in rendered['high']]} against resolver "
            f"{[round(v, 6) for v in low]}..{[round(v, 6) for v in high]}",
        )

    # And again four deep, because two levels cannot show the defect that was
    # actually shipped.
    #
    # glTF composes transforms down a chain. Writing each node its parent's
    # *world* position is right for one level and wrong for every level after:
    # the offset is re-applied once per ancestor. On the knight's
    # upperarm -> forearm -> hand -> gauntlet the gauntlet accumulated
    # 1.28 + 1.06 + 0.92 + 0.96 and landed at 4.21 m on a 1.72 m figure — the
    # sword and shield floated two metres above its head.
    #
    # Every gate passed. They measure the resolved spec, and the spec was right;
    # what was wrong was how it became a file. That is precisely the class of
    # defect this test exists for, and a two-deep fixture is blind to it.
    print("\nand a chain four deep composes once per level, not once per ancestor")
    deep = validate_spec({
        "subject": "four deep", "units": "metres", "forward": "+z",
        "height_metres": 2.0, "materials": {},
        "parts": [
            {"id": "a", "kind": "box", "size": [0.1, 0.1, 0.1],
             "at": [0.30, 1.60, 0.10]},
            {"id": "b", "kind": "box", "size": [0.1, 0.1, 0.1],
             "parent": "a", "at": [0.50, 1.20, 0.20]},
            {"id": "c", "kind": "box", "size": [0.1, 0.1, 0.1],
             "parent": "b", "at": [0.70, 0.80, 0.30]},
            {"id": "d", "kind": "box", "size": [0.1, 0.1, 0.1],
             "parent": "c", "at": [0.90, 0.40, 0.40]},
        ],
    })

    with tempfile.TemporaryDirectory() as directory:
        out = write_spec_glb(deep, str(Path(directory) / "deep.glb"))
        rendered = read_glb_mesh(Path(out).read_bytes())
        low = [min(part_bounds(p)[0][axis] for p in deep["parts"])
               for axis in range(3)]
        high = [max(part_bounds(p)[1][axis] for p in deep["parts"])
                for axis in range(3)]
        check(
            "a four-deep chain renders where it was placed",
            all(abs(rendered["low"][axis] - low[axis]) < 1e-6
                and abs(rendered["high"][axis] - high[axis]) < 1e-6
                for axis in range(3)),
            f"rendered {[round(v, 4) for v in rendered['low']]}.."
            f"{[round(v, 4) for v in rendered['high']]} against resolver "
            f"{[round(v, 4) for v in low]}..{[round(v, 4) for v in high]}",
        )
        # Stated separately because it is the number a reviewer sees first, and
        # the one that was 2.4x out while everything else looked healthy.
        check(
            "and its height is the height that was asked for",
            abs((rendered["high"][1] - rendered["low"][1])
                - (high[1] - low[1])) < 1e-6,
            f"rendered height {rendered['high'][1] - rendered['low'][1]:.4f} "
            f"against placed {high[1] - low[1]:.4f}",
        )

        # The hierarchy has to still be worth having. Dropping the node
        # translations renders identically here and leaves every child pivoting
        # about a point outside itself, so the fix is only correct if the nodes
        # are still nested and still carry offsets.
        document = glb_json_chunk(Path(out).read_bytes())
        names = [node["name"] for node in document["nodes"]]
        chain_ok = True
        for parent_name, child_name in (("a", "b"), ("b", "c"), ("c", "d")):
            children = document["nodes"][names.index(parent_name)].get(
                "children", [])
            chain_ok = chain_ok and [names[index] for index in children] \
                == [child_name]
        check(
            "the chain is still a chain, not four flattened roots",
            chain_ok and len(document["scenes"][0]["nodes"]) == 1,
            f"scene roots {[names[i] for i in document['scenes'][0]['nodes']]}",
        )


def test_assembly_unresolvable_refused() -> None:
    """A relation with no solution is a spec error, not a placement.

    Each of these describes no position at all, so there is nothing for a
    correction loop to weigh and nothing a gate could report about the mesh
    that resulted — because none would result.
    """

    print("\nan unresolvable relation is refused")
    from operators.gen_3d_object.funcs.code_asset import SpecError, validate_spec

    for label, parts in (
        ("a two-part cycle", [
            {"id": "a", "kind": "box", "size": [1, 1, 1],
             "attach": {"to": "b"}},
            {"id": "b", "kind": "box", "size": [1, 1, 1],
             "attach": {"to": "a"}}]),
        ("a three-part cycle", [
            {"id": "a", "kind": "box", "size": [1, 1, 1], "parent": "b"},
            {"id": "b", "kind": "box", "size": [1, 1, 1], "parent": "c"},
            {"id": "c", "kind": "box", "size": [1, 1, 1], "parent": "a"}]),
        ("an unknown attach target", [
            {"id": "a", "kind": "box", "size": [1, 1, 1],
             "attach": {"to": "ghost"}}]),
        ("an unknown parent", [
            {"id": "a", "kind": "box", "size": [1, 1, 1], "parent": "ghost"}]),
        ("self-parenting", [
            {"id": "a", "kind": "box", "size": [1, 1, 1], "parent": "a"}]),
        ("an unknown face", [
            {"id": "a", "kind": "box", "size": [1, 1, 1], "at": [0, 1, 0]},
            {"id": "b", "kind": "box", "size": [1, 1, 1],
             "attach": {"to": "a", "my": "topmost"}}]),
        ("an unknown axis", [
            {"id": "a", "kind": "box", "size": [1, 1, 1], "at": [0, 1, 0]},
            {"id": "b", "kind": "box", "size": [1, 1, 1],
             "attach": {"to": "a", "axis": "up"}}]),
        ("attach without a target", [
            {"id": "a", "kind": "box", "size": [1, 1, 1],
             "attach": {"axis": "y"}}]),
    ):
        try:
            validate_spec({
                "subject": "x", "units": "metres", "forward": "+z",
                "parts": parts,
            })
            check(f"{label} is refused", False, "it was accepted")
        except SpecError:
            check(f"{label} is refused", True, "")


def test_assembly_chain_group_mirror() -> None:
    """`assembly` must chain, group and mirror — the COMPOSED mechanism.

    The part tables are here rather than in `rigid_template` on purpose: a
    rifle's chamber and a car's wheelbase are content, and shipping them in the
    package would make the next weapon a copy. The joining is what generalises.

    Absolute placement is what produced every gap in these assets — a muzzle
    9 mm off its barrel, a sling loop 26 mm past a rail — each fixed with a
    number that went stale when a neighbour's size changed.
    """

    print("\nrigid parts are joined by relation, not by coordinate")
    from operators.gen_3d_object.funcs.code_asset import build_code_asset
    from operators.gen_3d_object.funcs.code_asset_templates import assembly, compose

    # --- a rifle: a chain, front to back -----------------------------------
    receiver = {"id": "receiver", "kind": "box", "size": [0.05, 0.09, 0.26],
                "at": [0.0, 0.20, 0.0], "material": "steel", "chamfer": 0.15}
    barrel = {"id": "barrel", "kind": "cylinder", "size": [0.022, 0.34, 0.022],
              "rotation": [90.0, 0.0, 0.0], "material": "steel", "segments": 20}
    muzzle = {"id": "muzzle", "kind": "cylinder", "size": [0.030, 0.04, 0.030],
              "rotation": [90.0, 0.0, 0.0], "material": "steel", "segments": 20}
    # Stated, not chained: a magazine hangs *under* the receiver, and `chain`
    # leaves it alone. That is what lets one chain carry a branch.
    magazine = {"id": "magazine", "kind": "box", "size": [0.028, 0.13, 0.075],
                "material": "steel", "chamfer": 0.10,
                "attach": {"to": "receiver", "axis": "y", "my": "max",
                           "their": "min"}}

    parts = assembly.chain([receiver, barrel, muzzle], axis="z")
    check(
        "the first part anchors and keeps its own placement",
        "attach" not in parts[0] and parts[0]["at"] == [0.0, 0.20, 0.0],
    )
    check(
        "each later part attaches to the one before it",
        parts[1]["attach"]["to"] == "receiver"
        and parts[2]["attach"]["to"] == "barrel",
        f"got {[p.get('attach', {}).get('to') for p in parts]}",
    )
    parts = parts + assembly.chain([magazine])
    check(
        "a part that states its own relation is left alone",
        parts[3]["attach"]["their"] == "min",
    )

    with tempfile.TemporaryDirectory() as tmp:
        rifle = build_code_asset(compose.compose(
            subject="tactical assault rifle",
            body=parts, height_metres=0.24, asset_type="prop",
            materials={"steel": {"baseColor": [0.6, 0.62, 0.66, 1.0],
                                 "metallic": 1.0, "roughness": 0.3}},
        ), str(Path(tmp) / "rifle.glb"))
    check("the chained rifle builds", rifle["ok"], str(rifle.get("failures")))

    # Asserted as the actual arithmetic, not as "some offset appeared", because
    # a wrong offset is also an offset. `attach` survives in the solved spec on
    # purpose: the resolver rewrites `at` and leaves the declaration, so the
    # spec still records why the part is where it is.
    solved = {part["id"]: part for part in rifle["spec"]["parts"]}
    receiver_end = solved["receiver"]["at"][2] + 0.26 / 2      # box half-depth
    barrel_half = 0.34 / 2                                     # rotated onto z
    check(
        "the barrel was solved onto the receiver's end face",
        abs(solved["barrel"]["at"][2] - (receiver_end + barrel_half)) < 1e-6,
        f"barrel at z={solved['barrel']['at'][2]:.4f}, "
        f"expected {receiver_end + barrel_half:.4f}",
    )
    check(
        "and the muzzle onto the barrel's, so the chain is end to end",
        abs(solved["muzzle"]["at"][2]
            - (solved["barrel"]["at"][2] + barrel_half + 0.04 / 2)) < 1e-6,
        f"muzzle at z={solved['muzzle']['at'][2]:.4f}",
    )
    check(
        "the relation stays in the spec; only the position is derived",
        solved["barrel"]["attach"]["to"] == "receiver",
    )

    # --- a car: a mirror, and a group for what a group is actually for ------
    #
    # WHEELS ARE NOT GROUPED. `group` states a *face* relation and a wheel has
    # none: its height comes from its own radius, because it must touch the
    # ground. Grouping them to the chassis on `y` put them on the roof (the
    # default faces oppose), and `mid`/`min` instead floated the car 0.17 m up.
    # Both build cleanly and both are wrong. So the axle height is stated, and
    # `group` is used for the parts that do butt against the chassis.
    RADIUS, HALF_TRACK, WHEELBASE = 0.17, 0.86, 1.28
    chassis = {"id": "chassis", "kind": "box", "size": [1.7, 0.30, 3.4],
               "at": [0.0, 0.49, 0.0], "material": "paint", "chamfer": 0.2}
    wheels = [
        {"id": f"wheel-{end}", "kind": "cylinder",
         "size": [RADIUS * 2, 0.22, RADIUS * 2], "rotation": [0.0, 0.0, 90.0],
         "at": [HALF_TRACK, RADIUS, z], "material": "rubber", "segments": 18}
        for end, z in (("front", WHEELBASE / 2), ("rear", -WHEELBASE / 2))
    ]

    both = assembly.mirrored(wheels, axis="x")
    check("mirroring makes both sides", len(both) == 4, f"got {len(both)}")
    check(
        "and puts them on opposite sides of the centreline",
        {round(part["at"][0], 3) for part in both} == {-HALF_TRACK, HALF_TRACK},
        f"got {sorted({round(p['at'][0], 3) for p in both})}",
    )
    check(
        "with ids that distinguish them",
        {part["id"] for part in both} == {"wheel-front-l", "wheel-rear-l",
                                         "wheel-front-r", "wheel-rear-r"},
        f"got {sorted(part['id'] for part in both)}",
    )
    check(
        "and every wheel still touches the ground",
        all(abs(part["at"][1] - RADIUS) < 1e-9 for part in both),
        f"got {sorted({p['at'][1] for p in both})}",
    )

    # Grouped, not chained: chaining would make the scoop's position depend on
    # the spoiler, so removing the spoiler would move the scoop.
    fittings = assembly.group([
        {"id": "spoiler", "kind": "box", "size": [1.5, 0.06, 0.34],
         "at": [0.0, 0.0, -1.5], "material": "paint", "chamfer": 0.3},
        {"id": "scoop", "kind": "box", "size": [0.5, 0.08, 0.6],
         "at": [0.0, 0.0, 0.7], "material": "paint", "chamfer": 0.25},
    ], to="chassis", axis="y")
    check(
        "every fitting attaches to the hub rather than to another fitting",
        all(part["attach"]["to"] == "chassis" for part in fittings),
        f"got {[p['attach']['to'] for p in fittings]}",
    )

    with tempfile.TemporaryDirectory() as tmp:
        car = build_code_asset(compose.compose(
            subject="arcade race car",
            body=[chassis] + both + fittings,
            height_metres=0.72, asset_type="vehicle",
            materials={"paint": {"baseColor": [0.9, 0.2, 0.15, 1.0],
                                 "metallic": 0.3, "roughness": 0.35},
                       "rubber": {"baseColor": [0.06, 0.06, 0.07, 1.0],
                                  "roughness": 0.9}},
        ), str(Path(tmp) / "car.glb"))
    check("the grouped car builds", car["ok"], str(car.get("failures")))

    solved = {part["id"]: part for part in car["spec"]["parts"]}
    check(
        "the car sits on the ground rather than floating or sinking",
        abs(car["bounds"]["low"][1]) < 1e-6,
        f"lowest point at y={car['bounds']['low'][1]}",
    )
    check(
        "and each fitting was solved onto the chassis roof, not onto the other",
        abs(solved["spoiler"]["at"][1] - solved["scoop"]["at"][1]) > 1e-9
        and solved["spoiler"]["at"][1] > chassis["at"][1],
        f"spoiler y={solved['spoiler']['at'][1]:.4f}, "
        f"scoop y={solved['scoop']['at'][1]:.4f}",
    )

    # `group` deliberately does not check the hub — it may be defined later — so
    # the resolver is what must refuse it, by name, with the whole list in hand.
    try:
        with tempfile.TemporaryDirectory() as tmp:
            build_code_asset(compose.compose(
                subject="broken car",
                body=assembly.group(both, to="no-such-chassis"),
                height_metres=0.34, asset_type="vehicle",
                materials={"rubber": {"baseColor": [0.1, 0.1, 0.1, 1.0]}},
            ), str(Path(tmp) / "broken.glb"))
        check("a missing hub is refused", False, "it was accepted")
    except Exception as exc:
        check(
            "a missing hub is refused, naming it",
            "no-such-chassis" in str(exc),
            f"got {str(exc)[:90]}",
        )

    # An axis that is not an axis, caught where it is written rather than as a
    # confusing downstream placement.
    try:
        assembly.chain([receiver, barrel], axis="w")
        check("a bad chain axis is refused", False, "it was accepted")
    except assembly.AssemblyError as exc:
        check("a bad chain axis is refused", "'x', 'y' or 'z'" in str(exc),
              f"got {exc}")


# ---- human: figures and what they wear --------------------------------------


def test_human_construct_kit_follows_limb() -> None:
    """A figure is a body plus what it wears, and the kit must follow the body.

    This is the composition the flat parts list could not express. Written
    flat, a vambrace at y 1.05 merely *coincides* with a forearm at y 1.05,
    and lengthening the arm separates them silently. Here the kit names the
    limb it is worn on, so the relationship is stated and the resolver keeps
    it.

    Also under test: that the composition lives outside the operator. The
    templates are imported, parameterised and substituted into — none of which
    would be possible if the arrangement were a script that performed itself.
    """

    print("\na body can be armoured from templates")
    from operators.gen_3d_object.funcs.code_asset import (
        part_bounds, run_gates, validate_spec,
    )
    from operators.gen_3d_object.funcs.code_asset_templates import compose
    from operators.gen_3d_object.funcs.code_asset_templates.human_template import (
        humanoid, plate_armour)

    body = humanoid.body_parts()
    check(
        "the body template provides every part a kit expects",
        set(plate_armour.REQUIRED_BODY_PARTS).issubset(
            {part["id"] for part in body}),
        "missing: "
        f"{sorted(set(plate_armour.REQUIRED_BODY_PARTS) - {p['id'] for p in body})}",
    )

    spec = validate_spec(compose.compose(
        subject="knight", body=body,
        worn=plate_armour.plate_armour() + plate_armour.sword(),
        height_metres=humanoid.LANDMARKS["height"],
    ))
    gates = run_gates(spec)
    check(
        "a composed figure passes every gate unedited",
        gates["ok"],
        f"failures: {gates['failures']}",
    )

    # Armour follows its limb. Lengthening the forearm has to carry the
    # vambrace, which is the entire claim of parenting over coincidence.
    def vambrace_offset(forearm_shift: float) -> float:
        moved = []
        for part in humanoid.body_parts():
            part = dict(part)
            if part["id"] == "forearm-l":
                part["at"] = [part["at"][0], part["at"][1] + forearm_shift,
                              part["at"][2]]
            moved.append(part)
        placed = validate_spec(compose.compose(
            subject="knight", body=moved,
            worn=plate_armour.plate_armour(),
            height_metres=humanoid.LANDMARKS["height"],
        ))
        by_id = {part["id"]: part for part in placed["parts"]}
        forearm = part_bounds(by_id["forearm-l"])
        vambrace = part_bounds(by_id["vambrace-l"])
        return (vambrace[0][1] + vambrace[1][1]) / 2 - (forearm[0][1] + forearm[1][1]) / 2

    check(
        "moving a limb carries its armour, so the offset is unchanged",
        abs(vambrace_offset(0.0) - vambrace_offset(0.08)) < 1e-9,
        f"{vambrace_offset(0.0):.6f} against {vambrace_offset(0.08):.6f}",
    )

    # One `replace` is the whole difference between the two routes, which is
    # what makes the hybrid version a configuration and not a second script.
    with tempfile.TemporaryDirectory() as directory:
        from models.common.glb_writer import write_spec_glb

        fixture = write_spec_glb(
            validate_spec({
                "subject": "head", "units": "metres", "forward": "+z",
                "height_metres": 0.3, "materials": {},
                "parts": [{"id": "h", "kind": "sphere", "size": [0.2, 0.27, 0.2],
                           "at": [0, 0.135, 0]}],
            }),
            str(Path(directory) / "head.glb"),
        )
        hybrid = validate_spec(compose.compose(
            subject="knight", body=body,
            worn=plate_armour.plate_armour(),
            replace={"head": {"kind": "mesh", "source": fixture,
                              "size": [0.27, 0.27, 0.27], "long_axis": "y",
                              "profile": None}},
            height_metres=humanoid.LANDMARKS["height"],
        ))
        head = next(part for part in hybrid["parts"] if part["id"] == "head")
        check(
            "replacing a part swaps its kind and keeps its relationships",
            head["kind"] == "mesh" and head.get("attach") is not None,
            f"kind={head['kind']}, attach={head.get('attach')}",
        )
        check(
            "and the composed hybrid figure still passes every gate",
            run_gates(hybrid)["ok"],
            f"failures: {run_gates(hybrid)['failures']}",
        )

    # A kit with nothing to attach to is refused by name, before the resolver
    # sees it — a dangling parent reported from inside a graph walk names the
    # wrong thing.
    try:
        compose.compose(
            subject="knight", body=body,
            worn=plate_armour.plate_armour(),
            drop=("forearm-l",),
            height_metres=humanoid.LANDMARKS["height"],
        )
        check("dropping a worn-on limb is refused", False, "it was accepted")
    except compose.CompositionError as exc:
        check(
            "dropping a worn-on limb is refused, naming the orphans",
            "vambrace-l" in str(exc),
            f"message did not name the orphan: {exc}",
        )

    try:
        compose.compose(
            subject="knight", body=body, worn=(),
            replace={"nose": {"kind": "box"}},
            height_metres=humanoid.LANDMARKS["height"],
        )
        check("replacing a part that is not there is refused", False,
              "it was accepted")
    except compose.CompositionError:
        check("replacing a part that is not there is refused", True, "")


def test_human_measure_foot_and_leg_from_geometry() -> None:
    """Two landmarks that reported the measuring apparatus, not the figure.

    Both produced kit that built cleanly, passed every gate, and was visibly
    wrong — the kind of defect that only a render or this kind of arithmetic
    catches.

    `foot_height` was `max(y) - low` over a band defined as the bottom 9% of the
    figure, so it returned the band's own ceiling: 0.1524 m against a 0.1548 m
    cutoff. A boot sized to it stood 0.152 m tall on a 0.133 m width and
    rendered as a cube.

    `leg_x` is read at the thigh and was used to place shin plates. This
    figure's legs splay, so the greaves sat 0.045 m inboard of the legs — far
    enough to miss them entirely, which rendered as four limbs: two plates
    hanging between two bare legs.

    Measures a body produced by an earlier build under `test_data/outputs/`, and
    skips when there is none: those are build products, not fixtures, so a fresh
    checkout has nothing to measure.
    """

    print("\na measurement must measure the body, not the sampling window")
    from operators.gen_3d_object.funcs.code_asset_templates.human_template import (
        figure_fit)

    bodies = sorted(Path("test_data/outputs").glob(
        "*/*/assets/3d_object/*/parts/tpose_body_lo.glb"))
    if not bodies:
        print("  .. skipped, no measured body has been built")
        return
    body = str(bodies[0])

    height = 1.72
    marks = figure_fit.landmarks_for(body, height)

    # The band this used to return. A foot is not 9% of a figure tall.
    band_ceiling = height * 0.09
    check(
        "foot height is the foot, not the band it was found in",
        marks["foot_height"] < band_ceiling * 0.75,
        f"foot_height {marks['foot_height']:.4f} against a "
        f"{band_ceiling:.4f} band — it is reporting the window",
    )
    # An independent landmark for the same place, measured a different way.
    check(
        "and it agrees with the separately measured ankle",
        abs(marks["foot_height"] - marks["ankle_y"]) < 0.04,
        f"foot_height {marks['foot_height']:.4f} vs "
        f"ankle_y {marks['ankle_y']:.4f}",
    )

    # The leg profile follows the limb down instead of reusing the thigh.
    shin_y = (marks["knee_y"] + marks["ankle_y"]) / 2.0
    at_shin = figure_fit.leg_x_at(marks, shin_y)
    check(
        "the leg is measured at the height the plate goes",
        at_shin > marks["leg_x"] * 1.20,
        f"leg_x_at({shin_y:.3f}) = {at_shin:.4f} vs leg_x {marks['leg_x']:.4f} "
        "— the profile is not following the splay",
    )
    check(
        "and a body with no profile falls back rather than reporting zero",
        figure_fit.leg_x_at({"leg_x": 0.33}, 0.5) == 0.33,
    )

    # Each foot separately, as well as the union. Only having the union forced
    # every caller to choose between a bulky boot and one that misses a foot.
    flat = marks["foot_sides"]
    check("each foot is reported, not just the pair", len(flat) == 4,
          f"got {len(flat)} values")
    left_x, right_x = flat[0], flat[2]
    check(
        "the two feet are not in the same place, which is why this is needed",
        abs(abs(left_x) - abs(right_x)) > 0.005,
        f"left {left_x:+.4f} right {right_x:+.4f}",
    )
    check(
        "and one foot is narrower than the pair's union",
        0.0 < marks["foot_span"] < marks["foot_width"],
        f"foot_span {marks['foot_span']:.4f} vs union "
        f"{marks['foot_width']:.4f}",
    )


def test_human_measure_landmarks_from_vertices() -> None:
    """Landmarks come from the body's vertices, and armour lands on them.

    The template this replaces stated where the knee was and then built a leg
    to match, so the landmark was true by construction and true of nothing
    else. A generated body has joints of its own, and armouring it means
    reading them — which a T-pose makes possible without a skeleton, because
    every limb lies along a known axis and a joint is a change in
    cross-section.

    The check that matters is not any single number: it is that the readings
    come out in anatomical order with human-looking gaps. Two wrong readings
    were caught by exactly that on the way — a waist at 0.65 of height read
    1.169 m on a 1.72 m figure because "narrowest torso below the arms" lands
    on the ribcage, and a crotch read 0.305 because legs are separate from the
    ankles up so scanning upward finds the ankles. A reading that satisfies
    the ordering is not necessarily right; one that violates it is certainly
    wrong, and both of those did.

    The fixture is a T-pose built from primitives, so the test needs no
    network and no checked-in figure — and so the expected landmarks are known
    independently of the code that finds them.
    """

    print("\na figure is measured before it is armoured")
    from models.common.glb_writer import write_spec_glb
    from operators.gen_3d_object.funcs.code_asset import (
        part_bounds, run_gates, validate_spec,
    )
    from operators.gen_3d_object.funcs.code_asset_templates import compose
    from operators.gen_3d_object.funcs.code_asset_templates.human_template import (
        armour_fit, figure_fit)

    # A crude T-pose: known joint heights, arms out along x.
    height = 1.80
    fixture_parts = [
        {"id": "torso", "kind": "box", "size": [0.34, 0.60, 0.20],
         "at": [0.0, 1.16, 0.0]},
        {"id": "head", "kind": "sphere", "size": [0.20, 0.26, 0.22],
         "at": [0.0, 1.66, 0.0]},
        # Clear of the torso, which ends at 1.46. Buried inside it there is no
        # narrow band above the shoulders at all, so the neck reads as the
        # torso's own width — a fixture that cannot exhibit the landmark cannot
        # test the reading of it.
        {"id": "neck", "kind": "cylinder", "size": [0.10, 0.12, 0.10],
         "at": [0.0, 1.50, 0.0]},
        {"id": "hip", "kind": "box", "size": [0.32, 0.18, 0.20],
         "at": [0.0, 0.80, 0.0]},
    ]
    for side, sign in (("l", -1.0), ("r", 1.0)):
        fixture_parts += [
            # Arms out horizontally: this is what makes it a T-pose.
            {"id": f"arm-{side}", "kind": "cylinder",
             "size": [0.62, 0.11, 0.11], "at": [sign * 0.48, 1.40, 0.0],
             "rotation": [0.0, 0.0, 90.0]},
            {"id": f"thigh-{side}", "kind": "cylinder",
             "size": [0.16, 0.42, 0.16], "at": [sign * 0.11, 0.55, 0.0]},
            {"id": f"shin-{side}", "kind": "cylinder",
             "size": [0.12, 0.34, 0.12], "at": [sign * 0.11, 0.19, 0.0]},
        ]

    with tempfile.TemporaryDirectory() as directory:
        body = write_spec_glb(
            validate_spec({
                "subject": "t-pose fixture", "units": "metres",
                "forward": "+z", "height_metres": height, "materials": {},
                "parts": fixture_parts,
            }),
            str(Path(directory) / "tpose.glb"),
        )

        marks = figure_fit.landmarks_for(body, height)

        order = ["ankle_y", "knee_y", "crotch_y", "hip_y", "waist_y",
                 "chest_y", "shoulder_y", "neck_y", "head_y"]
        heights = [marks[name] for name in order]
        check(
            "the landmarks come out in anatomical order",
            all(lower < upper for lower, upper in zip(heights, heights[1:])),
            ", ".join(f"{name} {marks[name]:.3f}" for name in order),
        )

        # Loose bounds on purpose: this is checking a reading is in the right
        # region of a body, not reproducing a particular figure. A tight bound
        # would fail on a stylised one and get the assertion deleted.
        for name, expected, tolerance in (("knee_y", 0.28, 0.10),
                                          ("crotch_y", 0.47, 0.12),
                                          ("waist_y", 0.62, 0.10),
                                          ("shoulder_y", 0.80, 0.10),
                                          ("head_y", 0.92, 0.08)):
            found = marks[name] / height
            check(
                f"{name} reads near {expected:.2f} of height",
                abs(found - expected) < tolerance,
                f"read {found:.3f}, expected {expected:.2f} +- {tolerance}",
            )

        check(
            "the outstretched arm's reach is measured, not assumed",
            marks["arm_reach"] > marks["shoulder_x"] * 2,
            f"reach {marks['arm_reach']:.3f} against "
            f"shoulder_x {marks['shoulder_x']:.3f}",
        )

        # The fixture's torso is 0.34 m wide, so a shoulder is at most half of
        # that plus a little. What this rules out is the reading that was
        # wrong: "the widest torso slice below the arms" put shoulder_x at
        # 0.103 m on a 1.72 m generated figure — a 0.21 m shoulder width, which
        # no adult has — because a slice below the arms crosses the chest and
        # not the joint. The tight number lives on the generated body; here the
        # property is that a shoulder is inboard of the arm and outboard of
        # nothing.
        check(
            "shoulder_x is a shoulder, not a whole wingspan",
            0.0 < marks["shoulder_x"] < marks["arm_reach"] * 0.6,
            f"shoulder_x {marks['shoulder_x']:.3f} against "
            f"reach {marks['arm_reach']:.3f}",
        )

        # The fixture has no hands, so its wrist is the end of the arm. What
        # this pins is the failure mode that mattered: on a real figure the
        # fingers are *flatter* than the wrist, so a search by height alone
        # returned the fingertips at 0.95 of reach and put a gauntlet past the
        # end of the arm. The wrist has to be inboard of the reach and outboard
        # of the elbow, whatever the figure.
        check(
            "the wrist is between the elbow and the end of the arm",
            marks["elbow_x"] < marks["wrist_x"] <= marks["arm_reach"] + 1e-9,
            f"elbow {marks['elbow_x']:.3f}, wrist {marks['wrist_x']:.3f}, "
            f"reach {marks['arm_reach']:.3f}",
        )
        check(
            "the elbow is between the shoulder and the wrist",
            marks["shoulder_x"] < marks["elbow_x"] < marks["wrist_x"],
            f"shoulder {marks['shoulder_x']:.3f}, "
            f"elbow {marks['elbow_x']:.3f}, wrist {marks['wrist_x']:.3f}",
        )

        # Girths, so a wrapped plate can be sized to what it encloses rather
        # than to a length. Bounded rather than pinned to the fixture's stated
        # 0.34 x 0.20 torso, because this fixture is primitives at their
        # default 16 segments and a rotated 16-segment cylinder does not have a
        # clean cross-section to read: its arm's vertices spread over 0.55 m of
        # height, so slices from the ribs to the crown all report the wingspan.
        # Raising the segments was tried and made it worse — more rings around
        # the axis is not more rings along it. The exact numbers are checked
        # against the generated body in `probe_fit.py`, which reads the written
        # file; what a primitive fixture can still show is that a girth is a
        # girth and not a span.
        check(
            "the chest girth is a girth, not a wingspan",
            0.0 < marks["chest_width"] < marks["arm_reach"]
            and 0.0 < marks["chest_depth"] < marks["arm_reach"],
            f"width {marks['chest_width']:.3f}, "
            f"depth {marks['chest_depth']:.3f}, "
            f"reach {marks['arm_reach']:.3f}",
        )
        check(
            "the neck column has height, so a collar can be sized to it",
            0.0 < marks["neck_y"] - marks["neck_bottom_y"] < height * 0.12,
            f"neck_y {marks['neck_y']:.3f}, "
            f"neck_bottom_y {marks['neck_bottom_y']:.3f}",
        )

        # The stated and the measured figure agree on *names*, which is what
        # lets a kit written against one be fitted with the other. They do not
        # agree on values, and must not be confused: on a 1.72 m figure the
        # stated elbow is 0.157 m from the measured one, so fitting armour to a
        # generated mesh with `humanoid.LANDMARKS` puts plates where the body is
        # not. This asserts the overlap so a rename on either side is caught
        # here rather than by a plate hanging in space.
        from operators.gen_3d_object.funcs.code_asset_templates.human_template import (
            humanoid)

        shared = set(humanoid.LANDMARKS) & set(marks)
        check(
            "the stated figure's landmark names are a subset of the measured "
            "ones, bar its own",
            set(humanoid.LANDMARKS) - shared == {"wrist_y"},
            f"stated-only keys {sorted(set(humanoid.LANDMARKS) - shared)}; "
            "a stated landmark with no measured counterpart cannot be fitted",
        )
        check(
            "and the two are genuinely different figures, not a copy",
            any(abs(humanoid.LANDMARKS[name] - marks[name]) > 0.02
                for name in shared if name != "height"),
            "stated and measured landmarks are identical, which means one of "
            "them is not doing its job",
        )

        # A helm scaled to neck-to-crown must not exceed the figure. The
        # earlier `* 1.25` guess put the crown 0.070 m above a 1.72 m figure's
        # own head, and `head_y` carried a `+ 0.02` nudge that made the centre
        # disagree with the span.
        helm_span = height - marks["neck_y"]
        check(
            "a helm sized to neck-to-crown ends at the crown",
            abs((marks["head_y"] + helm_span / 2.0) - height) < 1e-9,
            f"helm top {marks['head_y'] + helm_span / 2.0:.4f} against "
            f"height {height:.4f}",
        )

        # Feet stand wider than thighs. `leg_x` is measured at the thigh, and
        # using it for a sabaton put the plate 0.075 m inboard of the foot —
        # beside it rather than on it.
        check(
            "the foot is measured where the foot is, not under the thigh",
            marks["foot_x"] > marks["leg_x"],
            f"foot_x {marks['foot_x']:.3f} against leg_x {marks['leg_x']:.3f}",
        )

        # A limb offset front-to-back: every slot placed at a literal z=0
        # before this, and on a generated figure the arm's centreline runs at
        # -0.059 while the placements said 0. The plates were the right size on
        # the right landmark, 0.06 m in front of the limb.
        #
        # The arms are moved, not the whole body. Shifting everything was tried
        # and proves nothing: `load_mesh_asset` normalises to the mesh's own
        # bounds, so a bodily shift produces a byte-identical mesh and the test
        # passes or fails for reasons unconnected to the reading. What has to be
        # measured is a limb offset *relative to the body it belongs to*.
        arms_back = [
            {**part, "at": [part["at"][0], part["at"][1], part["at"][2] - 0.07]}
            if part["id"].startswith("arm-") else part
            for part in fixture_parts
        ]
        shifted = write_spec_glb(
            validate_spec({
                "subject": "t-pose fixture, arms set back", "units": "metres",
                "forward": "+z", "height_metres": height, "materials": {},
                "parts": arms_back,
            }),
            str(Path(directory) / "arms_back.glb"),
        )
        shifted_marks = figure_fit.landmarks_for(shifted, height)
        check(
            "arm_z follows the arm back, rather than staying at zero",
            shifted_marks["arm_z"] < marks["arm_z"] - 0.02,
            f"arm_z read {shifted_marks['arm_z']:.4f} with the arms set back "
            f"0.07 m, against {marks['arm_z']:.4f} with them centred",
        )
        # And the placement uses it, which is the point: a measured offset that
        # no slot reads is not a fix.
        shifted_figure = armour_fit.body_part(
            shifted, part_id="figure", height_metres=height, material="skin")
        on_shifted = armour_fit.fit_armour(
            body_id="figure", landmarks=shifted_marks,
            body_origin=shifted_figure["at"],
            pieces=[{"id": "vambrace-l", "slot": "forearm", "side": "l",
                     "kind": "cylinder", "size": [0.12, 0.12, 0.12]}],
        )
        check(
            "a fitted piece lands at the measured depth, not on the centreline",
            abs(on_shifted[0]["at"][2] - shifted_marks["arm_z"]) < 1e-9,
            f"placed at z {on_shifted[0]['at'][2]:.4f}, "
            f"arm_z {shifted_marks['arm_z']:.4f}",
        )

        # A body that is not a T-pose is refused rather than measured badly:
        # with arms down there is no wide band, so no limb axis to read.
        # A figure with its arms *down*: plenty of material, no wide band. The
        # refusal has to name the pose, because "measure this figure" and
        # "measure this T-pose" fail for different reasons and only one of
        # them is fixed by re-posing.
        arms_down = [part for part in fixture_parts
                     if not part["id"].startswith("arm-")]
        for side, sign in (("l", -1.0), ("r", 1.0)):
            arms_down.append({
                "id": f"arm-{side}", "kind": "cylinder",
                "size": [0.11, 0.62, 0.11], "at": [sign * 0.22, 1.10, 0.0],
            })
        no_tpose = write_spec_glb(
            validate_spec({
                "subject": "arms down", "units": "metres", "forward": "+z",
                "height_metres": height, "materials": {},
                "parts": arms_down,
            }),
            str(Path(directory) / "arms_down.glb"),
        )
        try:
            figure_fit.measure_figure(no_tpose)
            check("a figure that is not a T-pose is refused", False,
                  "it was measured anyway")
        except ValueError as exc:
            check(
                "a figure that is not a T-pose is refused, saying why",
                "T-pose" in str(exc),
                f"message did not mention the pose: {exc}",
            )

        # Armour lands on the landmark it names, in the parent's frame.
        figure = armour_fit.body_part(body, part_id="figure",
                                      height_metres=height, material="skin")
        fitted = armour_fit.fit_armour(
            body_id="figure", landmarks=marks, body_origin=figure["at"],
            pieces=[
                # Both knees. The chirality gate refuses a lateral pair with
                # one half missing, and it was right to: the first draft of
                # this test fitted only a left poleyn.
                {"id": "poleyn-l", "slot": "knee", "side": "l",
                 "kind": "sphere", "size": [0.15, 0.13, 0.15]},
                {"id": "poleyn-r", "slot": "knee", "side": "r",
                 "kind": "sphere", "size": [0.15, 0.13, 0.15]},
                {"id": "gorget", "slot": "neck",
                 "kind": "cylinder", "size": [0.17, 0.07, 0.16]},
            ],
        )
        spec = validate_spec(compose.compose(
            subject="fitted", body=[figure] + fitted, worn=(),
            height_metres=height,
        ))
        placed = {part["id"]: part_bounds(part) for part in spec["parts"]}

        for part_id, landmark in (("poleyn-l", "knee_y"), ("gorget", "neck_y")):
            low, high = placed[part_id]
            centre = (low[1] + high[1]) / 2
            check(
                f"{part_id} lands on the measured {landmark}",
                abs(centre - marks[landmark]) < 1e-6,
                f"centre {centre:.4f} against {landmark} {marks[landmark]:.4f}",
            )

        check(
            "and a fitted figure passes every gate",
            run_gates(spec)["ok"],
            f"failures: {run_gates(spec)['failures']}",
        )

        # An unknown slot is refused by name. A silently unplaced plate renders
        # at the origin inside the figure's ankle, which reads as a modelling
        # error rather than a spec one.
        try:
            armour_fit.fit_armour(
                body_id="figure", landmarks=marks, body_origin=figure["at"],
                pieces=[{"id": "x", "slot": "wing", "kind": "box",
                         "size": [0.1, 0.1, 0.1]}],
            )
            check("an unknown slot is refused", False, "it was accepted")
        except ValueError as exc:
            check("an unknown slot is refused", "wing" in str(exc), str(exc)[:60])


def main() -> int:
    print(__doc__.strip().split("\n")[2])
    test_spec_correction_terminates()
    test_spec_rejects_flat_and_misscaled()
    test_spec_rejects_malformed()
    test_gate_budget_and_connectivity()
    test_gate_budget_matches_writer()
    test_gate_chirality()
    test_gate_open_mesh_warns_only()
    test_gate_orientation()
    test_gate_provenance_warns_then_blocks()
    test_glb_output_roundtrip()
    test_geom_primitives_are_sane()
    test_geom_chamfer_keeps_solid_closed()
    test_geom_all_primitives_face_outward()
    test_geom_open_profile_refused()
    test_geom_profile_winding_agnostic()
    test_geom_windings_catches_inverted()
    test_mesh_composes_like_primitive()
    test_mesh_mirror_keeps_faces_outward()
    test_mesh_texture_survives()
    test_route_declines_rather_than_guesses()
    test_route_new_domain_registers()
    test_route_wearer_routes_to_generate()
    test_assembly_attach_solves_faces()
    test_assembly_parent_into_nodes()
    test_assembly_unresolvable_refused()
    test_assembly_chain_group_mirror()
    test_human_construct_kit_follows_limb()
    test_human_measure_foot_and_leg_from_geometry()
    test_human_measure_landmarks_from_vertices()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for failure in FAILED:
        print(f"  - {failure}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
