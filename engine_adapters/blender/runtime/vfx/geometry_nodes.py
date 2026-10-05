"""
engine_adapters/blender/runtime/vfx/geometry_nodes.py

Attach a geometry-nodes tree to a spawned object.

A tree authored in a `.blend` and pulled in by `blend_scene.load_scene` can be
instantiated here by `tree_name` — that is how a real effect gets built: the art
is authored in Blender, the runtime only places it and drives its inputs.

With no tree named, a pass-through group is built. A Nodes modifier with an
*empty* group logs "must have a group output" and silently does nothing, so the
minimum valid tree is what turns that into a visible object showing nothing.

将一个几何节点树附加到生成的对象上。

在 `.blend` 文件中创建并通过 `blend_scene.load_scene` 导入的节点树，可以通过 `tree_name` 在此处实例化——这就是实际特效的构建方式：美术设计在Blender中完成，运行时只需将其放置并驱动其输入参数即可。

如果没有指定节点树名称，则会生成一个透传组。带有空组的Nodes修改器会提示“必须存在组输出”并静默不执行任何操作，因此能生成可见且不显示任何内容的对象所需的最小有效节点树就是如此。
"""

from typing import Optional, Tuple


def spawn(name: str, location: Tuple[float, float, float],
          tree_name: str = "", inputs: Optional[dict] = None,
          **_ignored) -> str:
    """
    Create the carrier object and its Nodes modifier. Returns the object's name.

    `tree_name` is a node group already in the file, falling back to
    pass-through. `inputs` are written onto the modifier by socket identifier;
    keys the tree does not expose are skipped rather than raising, because the
    same command is often sent at several trees.
    """
    import bpy  # noqa: PLC0415

    # A near-zero plane: geometry nodes usually replace the input geometry
    # entirely, and anything larger would show through the effect.
    bpy.ops.mesh.primitive_plane_add(size=0.01, location=location)
    obj = bpy.context.active_object
    obj.name = name

    modifier = obj.modifiers.new(name="GeometryNodes", type="NODES")
    if tree_name and tree_name in bpy.data.node_groups:
        modifier.node_group = bpy.data.node_groups[tree_name]
    else:
        if tree_name:
            print(f"[vfx] no node group {tree_name!r}; using a pass-through tree")
        modifier.node_group = _passthrough_tree(bpy, f"{name}_tree")

    for key, value in (inputs or {}).items():
        try:
            modifier[key] = value
        except (KeyError, TypeError) as e:
            print(f"[vfx] {name}: input {key!r} not set ({e})")
    return obj.name


def _passthrough_tree(bpy, name: str):
    """The smallest valid geometry-nodes group: input wired to output."""
    tree = bpy.data.node_groups.new(name=name, type="GeometryNodeTree")

    if hasattr(tree, "interface"):
        # Blender 4.0 replaced the flat inputs/outputs lists with one interface.
        tree.interface.new_socket("Geometry", in_out="INPUT",
                                  socket_type="NodeSocketGeometry")
        tree.interface.new_socket("Geometry", in_out="OUTPUT",
                                  socket_type="NodeSocketGeometry")
    else:
        tree.inputs.new("NodeSocketGeometry", "Geometry")
        tree.outputs.new("NodeSocketGeometry", "Geometry")

    group_input = tree.nodes.new("NodeGroupInput")
    group_output = tree.nodes.new("NodeGroupOutput")
    group_input.location = (-200, 0)
    group_output.location = (200, 0)
    if group_input.outputs and group_output.inputs:
        tree.links.new(group_input.outputs[0], group_output.inputs[0])
    return tree
