"""
engine_adapters/blender/runtime/vfx/smoke_fire.py

A Mantaflow gas simulation: a domain box with an inflow emitter inside it.

Blender's fluid system needs both objects, so both are named under the
manager's prefix and clearing the effect takes the pair — a domain left behind
keeps simulating and keeps its voxel cache for the rest of the session.

Nothing is visible until it is baked, which is far slower than a command should
be, so this only builds the setup and leaves the bake to a full Blender install.
`resolution` is what decides whether that bake takes seconds or hours.

**On Blender 5.0.1's pip wheel a domain and a flow together leave the process
unable to exit.** The bundled Mantaflow scripts are out of step with the
compiled module (`LevelsetGrid has no attribute setConst`); deleting the objects
does not undo it, only emptying the file does — see `Subsystem.shutdown`.
"""

from typing import Tuple

#: Voxels along the domain's longest axis. 32 is coarse and quick to bake; the
#: Blender default of 64 is already slow enough to notice on a preview box.
DEFAULT_RESOLUTION = 32

#: Frames the emitter stays open.
DEFAULT_LIFETIME_FRAMES = 120


def spawn(name: str, location: Tuple[float, float, float],
          kind: str = "smoke", domain_size: float = 4.0,
          resolution: int = DEFAULT_RESOLUTION,
          lifetime_frames: int = DEFAULT_LIFETIME_FRAMES,
          **_ignored) -> str:
    """
    Create the domain and its inflow, from the manager's `name` prefix, as
    `<name>_domain` and `<name>_flow`. Returns the domain's name.

    `kind` is `smoke` or `fire`. `domain_size` is the cube's edge in metres, and
    bounds how far the effect can rise: smoke that reaches the wall stops.
    """
    import bpy  # noqa: PLC0415

    bpy.ops.mesh.primitive_cube_add(size=domain_size, location=location)
    domain = bpy.context.active_object
    domain.name = f"{name}_domain"
    domain_modifier = domain.modifiers.new(name="Fluid", type="FLUID")
    domain_modifier.fluid_type = "DOMAIN"
    domain_modifier.domain_settings.domain_type = "GAS"
    domain_modifier.domain_settings.resolution_max = int(resolution)

    bpy.ops.mesh.primitive_ico_sphere_add(radius=0.15, location=location)
    flow = bpy.context.active_object
    flow.name = f"{name}_flow"
    flow_modifier = flow.modifiers.new(name="Fluid", type="FLUID")
    flow_modifier.fluid_type = "FLOW"
    flow_modifier.flow_settings.flow_type = "FIRE" if kind == "fire" else "SMOKE"
    flow_modifier.flow_settings.flow_behavior = "INFLOW"

    scene = bpy.context.scene
    scene.frame_end = max(scene.frame_end,
                          scene.frame_current + int(lifetime_frames))
    return domain.name
