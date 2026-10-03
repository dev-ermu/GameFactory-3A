"""Shared format constants for host-side validation (no bpy import)."""

# Mesh formats both Blender and trimesh can read with matching vertex order.
SUPPORTED_MESH_SUFFIXES = (".glb", ".gltf", ".obj", ".ply", ".stl", ".fbx")

# Source clips the retarget stage accepts.
SUPPORTED_MOTION_SUFFIXES = (".bvh", ".fbx")

__all__ = ["SUPPORTED_MESH_SUFFIXES", "SUPPORTED_MOTION_SUFFIXES"]
