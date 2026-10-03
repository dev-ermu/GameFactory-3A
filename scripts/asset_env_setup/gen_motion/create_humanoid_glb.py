"""Create a watertight, single-mesh T-pose humanoid GLB for integration tests."""

import argparse
from pathlib import Path


def create_humanoid(path: Path, pitch: float = 0.025) -> None:
    import numpy as np
    import trimesh

    x, y, z = np.indices((96, 36, 116))
    occupied = np.zeros((96, 36, 116), dtype=bool)

    # Torso, neck and horizontally extended arms overlap into one volume.
    occupied |= (
        (x >= 34) & (x <= 61)
        & (y >= 10) & (y <= 25)
        & (z >= 43) & (z <= 79)
    )
    occupied |= (
        (x >= 43) & (x <= 52)
        & (y >= 13) & (y <= 22)
        & (z >= 77) & (z <= 87)
    )
    occupied |= (
        (x >= 5) & (x <= 90)
        & (y >= 13) & (y <= 22)
        & (z >= 68) & (z <= 77)
    )

    # Head and hands are ellipsoids that overlap their neighbours.
    occupied |= (
        ((x - 47.5) / 11.0) ** 2
        + ((y - 17.5) / 10.0) ** 2
        + ((z - 94.0) / 13.0) ** 2
        <= 1.0
    )
    for hand_x in (5.0, 90.0):
        occupied |= (
            ((x - hand_x) / 6.0) ** 2
            + ((y - 17.5) / 6.0) ** 2
            + ((z - 72.0) / 6.0) ** 2
            <= 1.0
        )

    # Pelvis and two legs overlap the torso and include simple feet.
    occupied |= (
        (x >= 32) & (x <= 63)
        & (y >= 10) & (y <= 25)
        & (z >= 36) & (z <= 48)
    )
    for left, right in ((34, 44), (51, 61)):
        occupied |= (
            (x >= left) & (x <= right)
            & (y >= 13) & (y <= 22)
            & (z >= 8) & (z <= 40)
        )
        occupied |= (
            (x >= left - 1) & (x <= right + 1)
            & (y >= 5) & (y <= 22)
            & (z >= 3) & (z <= 10)
        )

    mesh = trimesh.voxel.ops.matrix_to_marching_cubes(
        occupied,
        pitch=pitch,
    )
    mesh.remove_unreferenced_vertices()
    mesh.merge_vertices()
    mesh.fix_normals()
    mesh.apply_translation(-mesh.bounds.mean(axis=0))
    height = float(mesh.extents[2])
    mesh.apply_scale(1.8 / height)
    mesh.visual.vertex_colors = [175, 145, 125, 255]

    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(path, file_type="glb")
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Failed to create humanoid GLB: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("--pitch", type=float, default=0.025)
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    create_humanoid(output, pitch=args.pitch)
    print(f"Wrote {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
