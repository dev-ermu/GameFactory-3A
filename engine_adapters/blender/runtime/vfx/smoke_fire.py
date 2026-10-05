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


这是一个Mantaflow气体模拟：一个包含内部流入发射器的域盒。

Blender的流体系统需要同时用到这两个物体，因此它们的名称都会加上管理器的前缀；要清除该效果必须同时处理这两个物体——如果遗留了域盒，它会继续模拟并保留其体素缓存，直到会话结束。

在效果被烘焙之前是看不到任何视觉表现的，而烘焙过程的速度远比预期要慢，因此此处仅负责搭建场景，真正的烘焙工作需交由完整的Blender安装环境来完成。`resolution`参数决定了烘焙耗时是几秒还是几小时。

在Blender 5.0.1的pip安装包中，域盒和流物体会导致进程无法退出。捆绑的Mantaflow脚本与编译后的模块版本不兼容（会出现`LevelsetGrid has no attribute setConst`的错误）；删除这些物体也无法解决问题，只有清空文件才能恢复——详见`Subsystem.shutdown`。
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
