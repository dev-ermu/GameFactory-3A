"""
engine_adapters/blender/runtime/vfx/particles.py

A burst of particles from a small emitter — sparks, dust, debris.

The classic particle system rather than geometry nodes: it needs no node tree
and renders in Cycles without a bake. Emission is a short window from the
current frame so the burst reads as an event; a continuous emitter is better
authored as part of the set.

一小块发射源产生的粒子爆发——比如火花、灰尘、碎屑。

这里选用的是传统的粒子系统而非几何节点：它无需节点树，且能在Cycles渲染器中直接渲染，无需预先烘焙。由于粒子发射仅发生在当前帧的短暂窗口期内，因此这种爆发效果会被表现为一次性事件；若是需要持续发射的效果，则更适合作为场景集合的一部分来创建。
"""

from typing import Tuple

#: Frames the emitter stays open. Short: this is an impact, not a fountain.
EMISSION_FRAMES = 5

SHAPES = ("sphere", "cube")


def spawn(name: str, location: Tuple[float, float, float],
          count: int = 500, lifetime: int = 60,
          emitter_shape: str = "sphere", velocity: float = 1.5,
          randomness: float = 0.5, **_ignored) -> str:
    """
    Create the emitter and its particle system. Returns the object's name,
    which is the manager's `name` exactly.

    `emitter_shape` is one of `SHAPES` — a sphere throws evenly, a cube along
    its faces. `velocity` is m/s along the emitter's normals and `randomness`
    (0 to 1) is how much it varies per particle.
    """
    import bpy  # noqa: PLC0415

    if emitter_shape == "cube":
        bpy.ops.mesh.primitive_cube_add(size=0.2, location=location)
    else:
        bpy.ops.mesh.primitive_ico_sphere_add(radius=0.1, location=location)
    emitter = bpy.context.active_object
    emitter.name = name

    emitter.modifiers.new(name="ParticleSystem", type="PARTICLE_SYSTEM")
    settings = emitter.particle_systems[-1].settings
    settings.count = int(count)
    settings.lifetime = int(lifetime)
    settings.frame_start = bpy.context.scene.frame_current
    settings.frame_end = bpy.context.scene.frame_current + EMISSION_FRAMES
    settings.emit_from = "VOLUME"
    settings.physics_type = "NEWTON"
    settings.normal_factor = float(velocity)
    settings.factor_random = float(randomness)

    scene = bpy.context.scene
    scene.frame_end = max(scene.frame_end,
                          settings.frame_end + int(lifetime))
    return emitter.name
