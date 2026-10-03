"""UE Python scripts for managed PBR material creation and mesh binding."""

import re
import textwrap
from typing import Any


def _safe_name(value: str, fallback: str = "Asset") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "").strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or fallback


def build_pbr_material_binding_script(
    asset_id: str,
    texture_sources: dict[str, str],
    mesh_asset_paths: list[str],
    destination_root: str,
    *,
    two_sided: bool = False,
    opacity_mode: str = "masked",
) -> str:
    """Import textures, create a PBR material, and assign it to meshes."""
    safe_asset_id = _safe_name(asset_id)
    texture_dest = f"{destination_root.rstrip('/')}/Textures"
    material_dest = f"{destination_root.rstrip('/')}/Materials"
    material_name = f"M_{safe_asset_id}_PBR"
    return textwrap.dedent(
        f"""\
        import unreal

        asset_id = {safe_asset_id!r}
        texture_sources = {dict(texture_sources)!r}
        mesh_asset_paths = {list(mesh_asset_paths)!r}
        destination_root = {destination_root.rstrip('/')!r}
        texture_dest = {texture_dest!r}
        material_dest = {material_dest!r}
        material_name = {material_name!r}
        two_sided = {bool(two_sided)!r}
        opacity_mode = {str(opacity_mode or "masked").lower()!r}

        def _set(obj, name, value):
            try:
                obj.set_editor_property(name, value)
                return True
            except Exception as exc:
                unreal.log_warning(
                    f"[A3Game] 设置 {{obj}}.{{name}} 失败: {{exc}}"
                )
                return False

        def _set_required(obj, name, value, label):
            if not _set(obj, name, value):
                raise RuntimeError(
                    f"设置必要材质属性失败: {{label}}.{{name}}"
                )
            try:
                actual = obj.get_editor_property(name)
            except Exception as exc:
                raise RuntimeError(
                    f"读取必要材质属性失败: {{label}}.{{name}}: {{exc}}"
                ) from exc
            if actual is None:
                raise RuntimeError(
                    f"必要材质属性为空: {{label}}.{{name}}"
                )
            return actual

        def _import_texture(channel, source_path):
            destination_name = "T_" + asset_id + "_" + channel
            desired_path = texture_dest.rstrip("/") + "/" + destination_name
            task = unreal.AssetImportTask()
            task.set_editor_property("filename", source_path)
            task.set_editor_property("destination_path", texture_dest)
            task.set_editor_property("destination_name", destination_name)
            task.set_editor_property("automated", True)
            task.set_editor_property("replace_existing", True)
            task.set_editor_property("save", True)
            unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
            imported_paths = list(
                task.get_editor_property("imported_object_paths") or []
            )
            texture = unreal.load_asset(
                str(imported_paths[0]) if imported_paths else desired_path
            )
            if not isinstance(texture, unreal.Texture2D):
                raise RuntimeError(
                    f"纹理导入没有生成 Texture2D: {{channel}} {{source_path}}"
                )

            if channel in {{
                "normal",
                "roughness",
                "metallic",
                "specular",
                "ambient_occlusion",
                "opacity",
            }}:
                _set(texture, "srgb", False)
            else:
                _set(texture, "srgb", True)

            if channel == "normal":
                _set(
                    texture,
                    "compression_settings",
                    unreal.TextureCompressionSettings.TC_NORMALMAP,
                )
                source_name = source_path.lower().replace("-", "_")
                if "nor_gl" in source_name or "normal_gl" in source_name:
                    _set(texture, "flip_green_channel", True)
            elif channel in {{
                "roughness",
                "metallic",
                "specular",
                "ambient_occlusion",
                "opacity",
            }}:
                _set(
                    texture,
                    "compression_settings",
                    unreal.TextureCompressionSettings.TC_MASKS,
                )

            unreal.EditorAssetLibrary.save_loaded_asset(
                texture,
                only_if_is_dirty=False,
            )
            return texture

        imported_textures = {{}}
        for channel, source_path in texture_sources.items():
            imported_textures[channel] = _import_texture(
                str(channel),
                str(source_path),
            )

        material_path = material_dest.rstrip("/") + "/" + material_name
        material = unreal.load_asset(material_path)
        if not isinstance(material, unreal.Material):
            material = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                material_name,
                material_dest,
                unreal.Material,
                unreal.MaterialFactoryNew(),
            )
        if not isinstance(material, unreal.Material):
            raise RuntimeError(f"创建 PBR Material 失败: {{material_path}}")

        unreal.MaterialEditingLibrary.delete_all_material_expressions(material)
        _set(material, "two_sided", two_sided)
        if "opacity" in imported_textures and opacity_mode == "masked":
            _set(material, "blend_mode", unreal.BlendMode.BLEND_MASKED)
            _set(material, "opacity_mask_clip_value", 0.333)
        else:
            _set(material, "blend_mode", unreal.BlendMode.BLEND_OPAQUE)

        property_by_channel = {{
            "base_color": unreal.MaterialProperty.MP_BASE_COLOR,
            "normal": unreal.MaterialProperty.MP_NORMAL,
            "roughness": unreal.MaterialProperty.MP_ROUGHNESS,
            "metallic": unreal.MaterialProperty.MP_METALLIC,
            "specular": unreal.MaterialProperty.MP_SPECULAR,
            "ambient_occlusion": unreal.MaterialProperty.MP_AMBIENT_OCCLUSION,
            "opacity": unreal.MaterialProperty.MP_OPACITY_MASK,
            "emissive": unreal.MaterialProperty.MP_EMISSIVE_COLOR,
        }}
        rgb_channels = {{"base_color", "normal", "emissive"}}
        x = -700
        y = -300
        expression_paths = {{}}
        expression_objects = {{}}
        for index, (channel, texture) in enumerate(imported_textures.items()):
            expression = unreal.MaterialEditingLibrary.create_material_expression(
                material,
                unreal.MaterialExpressionTextureSample,
                x,
                y + index * 180,
            )
            if expression is None:
                raise RuntimeError(
                    f"创建 TextureSample 失败: {{channel}}"
                )
            bound_texture = _set_required(
                expression,
                "texture",
                texture,
                "TextureSample[" + channel + "]",
            )
            if bound_texture.get_path_name() != texture.get_path_name():
                raise RuntimeError(
                    f"TextureSample 绑定结果不一致: {{channel}} "
                    f"expected={{texture.get_path_name()}} "
                    f"actual={{bound_texture.get_path_name()}}"
                )
            if channel == "normal":
                sampler = getattr(
                    getattr(unreal, "MaterialSamplerType", None),
                    "SAMPLERTYPE_NORMAL",
                    None,
                )
                if sampler is not None:
                    _set(expression, "sampler_type", sampler)
            elif channel not in {{"base_color", "emissive"}}:
                sampler = getattr(
                    getattr(unreal, "MaterialSamplerType", None),
                    "SAMPLERTYPE_MASKS",
                    None,
                )
                if sampler is not None:
                    _set(expression, "sampler_type", sampler)
            material_property = property_by_channel.get(channel)
            if material_property is not None:
                connected = unreal.MaterialEditingLibrary.connect_material_property(
                    expression,
                    "RGB" if channel in rgb_channels else "R",
                    material_property,
                )
                if connected is False:
                    raise RuntimeError(
                        f"连接材质属性失败: {{channel}} -> {{material_property}}"
                    )
            expression_paths[channel] = expression.get_path_name()
            expression_objects[channel] = expression

        missing_expression_textures = []
        for channel, expression in expression_objects.items():
            try:
                expression_texture = expression.get_editor_property("texture")
            except Exception:
                expression_texture = None
            if expression_texture is None:
                missing_expression_textures.append(channel)
        if missing_expression_textures:
            raise RuntimeError(
                "PBR Material 存在未绑定纹理的 TextureSample: "
                + ", ".join(missing_expression_textures)
            )

        unreal.MaterialEditingLibrary.layout_material_expressions(material)
        unreal.MaterialEditingLibrary.recompile_material(material)
        unreal.EditorAssetLibrary.save_loaded_asset(
            material,
            only_if_is_dirty=False,
        )

        assigned_meshes = []
        skipped_slots = []
        for mesh_path in mesh_asset_paths:
            mesh = unreal.load_asset(mesh_path)
            if not isinstance(mesh, unreal.StaticMesh):
                continue
            slots = list(mesh.get_editor_property("static_materials") or [])
            if not slots:
                mesh.add_material(material)
            else:
                for index, slot in enumerate(slots):
                    names = []
                    for property_name in (
                        "material_slot_name",
                        "imported_material_slot_name",
                    ):
                        try:
                            names.append(
                                str(slot.get_editor_property(property_name))
                            )
                        except Exception:
                            pass
                    slot_name = " ".join(names).lower()
                    if "glass" in slot_name or "transparent" in slot_name:
                        skipped_slots.append(
                            {{
                                "mesh": mesh_path,
                                "slot": index,
                                "name": slot_name,
                            }}
                        )
                        continue
                    mesh.set_material(index, material)
            unreal.EditorAssetLibrary.save_loaded_asset(
                mesh,
                only_if_is_dirty=False,
            )
            assigned_meshes.append(mesh_path)

        unreal.EditorAssetLibrary.save_directory(
            destination_root,
            only_if_is_dirty=False,
            recursive=True,
        )
        result = {{
            "ok": True,
            "asset_id": asset_id,
            "material_path": material_path,
            "texture_paths": {{
                channel: texture.get_path_name().split(".", 1)[0]
                for channel, texture in imported_textures.items()
            }},
            "expression_paths": expression_paths,
            "assigned_meshes": assigned_meshes,
            "skipped_slots": skipped_slots,
        }}
        """
    )


__all__ = ["build_pbr_material_binding_script"]
