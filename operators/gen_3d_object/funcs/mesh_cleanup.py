"""Remove the ground plate image-to-3D invents under a standing subject.

TRELLIS.2 crops its input to the subject's alpha bounding box with no
margin, so a full-body figure touches the top and bottom of the frame it
reconstructs from. Given a subject standing on the frame edge it
frequently infers a floor, and emits a flat slab spanning the whole
footprint of the unit box.

Measured on a generated character: two sheets of 4457 and 4072 faces,
each with extents ``[1.001, 0.003, 1.001]`` — a full-width, paper-thin
plane, 11% of the triangle budget, that the game never asked for. In the
scene it is worse than wasteful: normalised to a 1.8 m character that slab
becomes a 2.4 m grey pancake under their boots, defeating the ground
material and contact shadow meant to sit there.

It cannot be prompted away, because it is not in the concept image — the
image is clean and the inference adds the floor.

The removal is exact rather than heuristic, and that is worth spelling
out. A first attempt tested faces for "low, horizontal, and outside the
silhouette", which needed three thresholds and still left a ragged sheet
behind, because a hallucinated floor is crumpled and its normals wander.
A second attempt split the mesh into connected components and dropped the
ones spanning the whole footprint, which removed the two big sheets and
left three hundred shards of the same floor behind.

What actually separates a floor from an object is simpler, and needs no
notion of width at all:

    an isolated, paper-thin component lying at the base of the model

Real geometry is not made of loose sheets. A crate's flat bottom belongs
to a component whose extents include the crate's height; a plinth under a
statue is connected to the statue. Only an invented floor arrives as free
sheets 0.3% of the model's height thick, and it arrives as many of them.

That leaves the floor's **rubble** — hundreds of small lumps strewn across
where the floor was, too thick to be sheets. They are removed by a second
property, equally free of tuning: geometry lying *below* the object and
*outside its own footprint* is not part of the object. The footprint is
measured from whatever stands above the floor band, so a wide subject
keeps its wide base and a narrow one does not acquire confetti.
"""

from pathlib import Path
from typing import Any

#: Thinner than this fraction of the model's height counts as a sheet.
SHEET_THICKNESS = 0.02

#: Only components whose top lies below this height can be floor.
FLOOR_CEILING = 0.25

#: How far outside the object's own footprint debris must lie. Slack
#: enough that a splayed base — boots, a tree's roots — is kept.
FOOTPRINT_SLACK = 1.1

#: Ignore only degenerate scraps. This was originally set at 8 faces, on
#: the reasoning that a handful of triangles is not worth the risk — which
#: was exactly wrong: the floor's rubble arrives as *hundreds* of 7-face
#: patches, and the guard kept every one of them. Both tests below are
#: conservative on their own terms, so size adds nothing.
MIN_COMPONENT_FACES = 2

#: Refuse to remove more than this: past it the diagnosis was wrong and
#: the object really is a flat thing.
MAX_REMOVED_FRACTION = 0.4


def strip_ground_plate(
    glb_path: str | Path,
    *,
    thickness: float = SHEET_THICKNESS,
    ceiling: float = FLOOR_CEILING,
    slack: float = FOOTPRINT_SLACK,
    write: bool = True,
) -> dict[str, Any]:
    """Delete a hallucinated floor, and its rubble, from a generated GLB.

    Returns a report: ``applied``, ``removed_faces``, ``removed_fraction``,
    ``plate_count``, ``debris_count``, ``bounds_before``/``bounds_after``,
    and ``reason``. Never raises for a mesh it cannot improve — it reports
    ``applied: False`` and leaves the file alone, because a wrongly
    "cleaned" asset is worse than one with a slab.
    """

    import numpy as np
    import trimesh
    from trimesh.graph import connected_components

    path = Path(glb_path)
    report: dict[str, Any] = {
        "path": str(path),
        "applied": False,
        "removed_faces": 0,
        "removed_fraction": 0.0,
        "plate_count": 0,
        "debris_count": 0,
        "reason": "",
    }

    scene = trimesh.load(str(path), process=False)
    meshes = (
        list(scene.geometry.values())
        if isinstance(scene, trimesh.Scene)
        else [scene]
    )
    if len(meshes) != 1:
        report["reason"] = f"expected one mesh, found {len(meshes)}"
        return report

    mesh = meshes[0]
    if len(mesh.faces) == 0:
        report["reason"] = "empty mesh"
        return report

    vertices = mesh.vertices
    extents = np.asarray(mesh.extents, dtype=float)
    height = float(extents[1])
    report["bounds_before"] = [round(float(v), 4) for v in extents]
    if height <= 0:
        report["reason"] = "degenerate bounds"
        return report

    floor_ceiling = float(vertices[:, 1].min()) + height * ceiling

    # The object's own footprint, taken from what stands clear of the floor.
    standing = vertices[vertices[:, 1] > floor_ceiling]
    if len(standing) == 0:
        report["reason"] = "the whole model lies within the floor band"
        return report
    centre = np.array(
        [
            (standing[:, 0].min() + standing[:, 0].max()) / 2,
            (standing[:, 2].min() + standing[:, 2].max()) / 2,
        ]
    )
    radius = np.array(
        [
            (standing[:, 0].max() - standing[:, 0].min()) / 2,
            (standing[:, 2].max() - standing[:, 2].min()) / 2,
        ]
    )
    radius = np.maximum(radius, height * 1e-3) * slack

    groups = connected_components(
        mesh.face_adjacency,
        nodes=np.arange(len(mesh.faces)),
    )
    drop = np.zeros(len(mesh.faces), dtype=bool)
    plates = 0
    debris = 0
    for group in groups:
        if len(group) < MIN_COMPONENT_FACES:
            continue
        points = vertices[mesh.faces[group].reshape(-1)]
        low = points.min(axis=0)
        high = points.max(axis=0)
        if high[1] > floor_ceiling:
            continue  # reaches into the object: keep it
        if (high[1] - low[1]) <= height * thickness:
            drop[group] = True     # a sheet: the floor itself
            plates += 1
            continue
        inside = np.abs(
            (low[[0, 2]] + high[[0, 2]]) / 2 - centre
        ) <= radius
        if not inside.all():
            drop[group] = True     # rubble strewn beside the object
            debris += 1

    removed = int(drop.sum())
    fraction = removed / len(mesh.faces)
    report["removed_faces"] = removed
    report["removed_fraction"] = round(float(fraction), 4)
    report["plate_count"] = plates
    report["debris_count"] = debris
    if removed == 0:
        report["reason"] = "nothing to remove"
        return report
    if fraction > MAX_REMOVED_FRACTION:
        report["reason"] = (
            f"would remove {fraction:.0%} of the mesh, which is not a "
            "floor but the object itself"
        )
        return report

    mesh.update_faces(~drop)
    mesh.remove_unreferenced_vertices()
    report["bounds_after"] = [round(float(v), 4) for v in mesh.extents]
    report["applied"] = True
    if write:
        # Export as a scene so the PBR material and its texture survive.
        trimesh.Scene(mesh).export(str(path))
    return report
