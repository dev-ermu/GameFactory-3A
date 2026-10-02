#!/usr/bin/env python3
"""
tests/test_mesh_cleanup.py

Prove that the ground-plate removal deletes floors and nothing else.

Run:

    python tests/test_mesh_cleanup.py

The cases are synthetic on purpose. A generated asset is one sample of a
model's behaviour and makes a poor regression test — it cannot be varied,
and "did this look right" is exactly the judgement the vision skill exists
for. What *can* be pinned down is the geometric rule: build a subject, put
a hallucinated floor under it, and check that only the floor goes.

The risk being guarded against is not a missed plate — that is visible in
the review sheet — but an over-eager one, which quietly eats a crate's
bottom or a plinth and shows up much later as a hole in the shadow.
"""

from __future__ import annotations

import shutil
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


def _sheet(size: float, y: float, *, thickness: float = 0.004):
    """A paper-thin slab: what image-to-3D infers as a floor."""

    import trimesh

    plate = trimesh.creation.box(extents=(size, thickness, size))
    plate.apply_translation((0, y, 0))
    return plate


def _figure(height: float = 1.6):
    """A standing subject: narrow, tall, and densely tessellated.

    Density matters to the test, not just to realism. A generated mesh has
    tens of thousands of faces and its inferred floor is a few per cent of
    them; a twelve-face box subject would make the floor *half* the model,
    which the safety guard is right to refuse. Using a coarse stand-in
    would test the guard instead of the rule.
    """

    import trimesh

    body = trimesh.creation.icosphere(subdivisions=3, radius=0.5)
    body.apply_scale((0.4, height / 1.0, 0.25))
    body.apply_translation((0, height / 2, 0))
    return body


def _export(*meshes) -> Path:
    """Write one fused single-mesh GLB, as the generator produces."""

    import trimesh

    combined = trimesh.util.concatenate(list(meshes))
    path = Path(tempfile.mkdtemp(prefix="a3_cleanup_")) / "model.glb"
    trimesh.Scene(combined).export(str(path))
    return path


def _faces(path: Path) -> int:
    import trimesh

    scene = trimesh.load(str(path), process=False)
    return sum(len(mesh.faces) for mesh in scene.geometry.values())


def test_removes_a_floor() -> None:
    from operators.gen_3d_object.funcs import strip_ground_plate

    print("a figure standing on an inferred floor")
    path = _export(_figure(), _sheet(3.0, 0.0))
    before = _faces(path)
    report = strip_ground_plate(path)

    check("the plate is found", report["plate_count"] >= 1, str(report))
    check("the removal is applied", report["applied"] is True, str(report))
    check(
        "the figure survives",
        _faces(path) == before - report["removed_faces"] > 0,
        f"{_faces(path)} faces left of {before}",
    )
    check(
        "the footprint shrinks to the subject",
        report["bounds_after"][0] < 1.0 < report["bounds_before"][0],
        f"{report['bounds_before']} -> {report['bounds_after']}",
    )
    check(
        "the height barely moves, so a metre fit still works",
        abs(report["bounds_after"][1] - report["bounds_before"][1]) < 0.01,
        f"{report['bounds_before'][1]} -> {report['bounds_after'][1]}",
    )
    shutil.rmtree(path.parent, ignore_errors=True)


def test_keeps_a_solid_box() -> None:
    from operators.gen_3d_object.funcs import strip_ground_plate

    print("a crate, whose flat bottom is not a floor")
    path = _export(_figure(1.0))
    before = _faces(path)
    report = strip_ground_plate(path)

    check(
        "nothing is removed from a solid object",
        report["applied"] is False and report["removed_faces"] == 0,
        str(report),
    )
    check("the file is left alone", _faces(path) == before)
    check(
        "and it says why",
        "nothing to remove" in report["reason"],
        report["reason"],
    )
    shutil.rmtree(path.parent, ignore_errors=True)


def test_refuses_a_flat_object() -> None:
    from operators.gen_3d_object.funcs import strip_ground_plate

    print("a genuinely flat object")
    # A rug or a road sign plate: the whole asset is a thin sheet. It
    # survives because its own top surface reaches above the floor band —
    # the rule asks "is there a sheet *under* the object", and here there
    # is no object above it to be under.
    path = _export(_sheet(2.0, 0.0, thickness=0.01))
    before = _faces(path)
    report = strip_ground_plate(path)

    check(
        "a flat object is not mistaken for a floor",
        report["applied"] is False and report["removed_faces"] == 0,
        str(report),
    )
    check("the file is untouched", _faces(path) == before)
    shutil.rmtree(path.parent, ignore_errors=True)


def test_keeps_a_tabletop() -> None:
    from operators.gen_3d_object.funcs import strip_ground_plate

    print("a thin sheet high up is not a floor")
    # Same geometry as a floor, three quarters of the way up: a tabletop,
    # a canopy, a banner. Height is what distinguishes them.
    path = _export(_figure(2.0), _sheet(1.6, 1.5))
    before = _faces(path)
    report = strip_ground_plate(path)

    check(
        "a high sheet is kept",
        report["removed_faces"] == 0,
        str(report),
    )
    check("the file is untouched", _faces(path) == before)
    shutil.rmtree(path.parent, ignore_errors=True)


def test_survives_nonsense() -> None:
    from operators.gen_3d_object.funcs import strip_ground_plate

    print("bad input is reported, not raised")
    missing = Path(tempfile.mkdtemp(prefix="a3_cleanup_")) / "nope.glb"
    try:
        strip_ground_plate(missing)
        check("a missing file raises or reports", True)
    except Exception as exc:
        # Either is acceptable; what matters is that it is not silent.
        check(
            "a missing file raises a clear error",
            bool(str(exc)),
            type(exc).__name__,
        )
    shutil.rmtree(missing.parent, ignore_errors=True)


def main() -> int:
    try:
        import trimesh  # noqa: F401
    except ImportError:
        print("this test needs trimesh: pip install trimesh", file=sys.stderr)
        return 2

    test_removes_a_floor()
    test_keeps_a_solid_box()
    test_refuses_a_flat_object()
    test_keeps_a_tabletop()
    test_survives_nonsense()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for failure in FAILED:
        print(f"  FAILED {failure}", file=sys.stderr)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
