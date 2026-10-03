"""UE Python scripts for registering native .uasset/.umap content packs."""

import textwrap


def build_native_scene_register_script(
    content_root_path: str,
    map_paths: list[str],
    selected_map_path: str,
    *,
    load_map: bool = True,
    repair_missing_collision: bool = False,
) -> str:
    return textwrap.dedent(f"""\
        import unreal

        content_root_path = {content_root_path!r}
        map_paths = {list(map_paths)!r}
        selected_map_path = {selected_map_path!r}
        load_map = {bool(load_map)!r}
        repair_missing_collision = {bool(repair_missing_collision)!r}
        warnings = []

        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        registry.scan_paths_synchronous([content_root_path], True)

        discovered_maps = []
        for map_path in map_paths:
            try:
                exists = unreal.EditorAssetLibrary.does_asset_exist(map_path)
            except Exception:
                exists = False
            discovered_maps.append({{"path": map_path, "exists": bool(exists)}})

        selected_exists = any(
            item["path"] == selected_map_path and item["exists"]
            for item in discovered_maps
        )
        if not selected_exists:
            raise RuntimeError(
                "UE Asset Registry 未发现主 Map: "
                + selected_map_path
                + "。资源可能由更高版本 UE 保存，或目录层级不正确。"
            )

        player_start = None
        suggested_spawn = None
        spawn_source = ""
        render_repairs = []
        framed_actor = ""
        stationary_point_lights = 0
        converted_stationary_point_lights = 0
        actor_count = 0
        collision_component_count = 0
        landscape_collision_components = 0
        static_mesh_component_count = 0
        collision_class_counts = {{}}
        static_mesh_usage = {{}}
        collision_assets = []
        repaired_collision_assets = []
        missing_collision_assets = []
        usable_static_mesh_components = 0
        if load_map:
            try:
                loaded_world = unreal.EditorLoadingAndSavingUtils.load_map(selected_map_path)
            except Exception as exc:
                raise RuntimeError("加载 UE 原生 Map 失败: " + selected_map_path + ": " + str(exc))
            if loaded_world is None:
                raise RuntimeError("UE 返回空 World，无法加载 Map: " + selected_map_path)

            try:
                actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
            except Exception:
                actors = unreal.EditorLevelLibrary.get_all_level_actors()
            actor_count = len(actors)
            landscape_candidates = []
            house_candidates = []
            for actor in actors:
                try:
                    class_name = actor.get_class().get_name()
                    actor_label = actor.get_actor_label()
                except Exception:
                    class_name = ""
                    actor_label = ""
                try:
                    primitive_components = actor.get_components_by_class(unreal.PrimitiveComponent)
                except Exception:
                    primitive_components = []
                for component in primitive_components:
                    try:
                        collision_enabled = str(component.get_collision_enabled())
                    except Exception:
                        collision_enabled = ""
                    if "NO_COLLISION" in collision_enabled:
                        continue
                    component_class = component.get_class().get_name()
                    collision_component_count += 1
                    collision_class_counts[component_class] = (
                        collision_class_counts.get(component_class, 0) + 1
                    )
                    if "LandscapeHeightfieldCollisionComponent" in component_class:
                        landscape_collision_components += 1
                    try:
                        is_static_mesh_component = isinstance(
                            component,
                            unreal.StaticMeshComponent,
                        )
                    except Exception:
                        is_static_mesh_component = False
                    if not is_static_mesh_component:
                        continue
                    try:
                        static_mesh = component.get_editor_property("static_mesh")
                    except Exception:
                        static_mesh = None
                    if static_mesh is None:
                        continue
                    static_mesh_path = static_mesh.get_path_name().split(".", 1)[0]
                    if not static_mesh_path.startswith("/Game/"):
                        continue
                    static_mesh_component_count += 1
                    usage = static_mesh_usage.setdefault(
                        static_mesh_path,
                        {{"components": 0, "profiles": []}},
                    )
                    usage["components"] += 1
                    try:
                        profile_name = str(component.get_collision_profile_name())
                    except Exception:
                        profile_name = ""
                    if profile_name and profile_name not in usage["profiles"]:
                        usage["profiles"].append(profile_name)
                if class_name in ("Landscape", "LandscapeStreamingProxy"):
                    try:
                        origin, extent = actor.get_actor_bounds(False)
                        landscape_candidates.append((
                            actor_label.lower() == "backdrop",
                            abs(float(extent.x) * float(extent.y)),
                            origin,
                            extent,
                        ))
                    except Exception:
                        pass
                if "House" in class_name or "House" in actor_label:
                    try:
                        origin, extent = actor.get_actor_bounds(False)
                        house_candidates.append((
                            abs(float(origin.x)) + abs(float(origin.y)),
                            actor_label,
                            origin,
                            extent,
                        ))
                    except Exception:
                        pass
                if class_name == "PointLight":
                    try:
                        light_component = actor.get_component_by_class(unreal.LightComponent)
                        mobility = str(light_component.get_editor_property("mobility")) if light_component else ""
                        if "STATIONARY" in mobility:
                            stationary_point_lights += 1
                            movable = getattr(
                                getattr(unreal, "ComponentMobility", None),
                                "MOVABLE",
                                None,
                            )
                            if movable is not None:
                                light_component.set_editor_property(
                                    "mobility",
                                    movable,
                                )
                                converted_stationary_point_lights += 1
                                render_repairs.append({{
                                    "actor": actor_label,
                                    "repair": (
                                        "stationary_point_light_to_movable"
                                    ),
                                }})
                    except Exception:
                        pass
                if class_name == "PostProcessVolume":
                    try:
                        settings = actor.get_editor_property("settings")
                        min_brightness = float(settings.get_editor_property("auto_exposure_min_brightness"))
                        max_brightness = float(settings.get_editor_property("auto_exposure_max_brightness"))
                        if min_brightness > max_brightness:
                            before = {{
                                "auto_exposure_min_brightness": min_brightness,
                                "auto_exposure_max_brightness": max_brightness,
                            }}
                            for property_name, value in (
                                ("override_auto_exposure_bias", True),
                                ("auto_exposure_bias", 1.5),
                                ("override_auto_exposure_min_brightness", True),
                                ("override_auto_exposure_max_brightness", True),
                                ("auto_exposure_min_brightness", 1.0),
                                ("auto_exposure_max_brightness", 1.0),
                                ("override_auto_exposure_min_ev100", True),
                                ("override_auto_exposure_max_ev100", True),
                                ("auto_exposure_min_ev100", 0.0),
                                ("auto_exposure_max_ev100", 0.0),
                            ):
                                try:
                                    settings.set_editor_property(property_name, value)
                                except Exception:
                                    pass
                            actor.set_editor_property("settings", settings)
                            render_repairs.append({{
                                "actor": actor_label,
                                "repair": "normalized_invalid_auto_exposure_range",
                                "before": before,
                            }})
                    except Exception as exc:
                        warnings.append("检查 PostProcessVolume 曝光失败: " + str(exc))
                if class_name == "PlayerStart" and player_start is None:
                    location = actor.get_actor_location()
                    rotation = actor.get_actor_rotation()
                    player_start = {{
                        "location": {{
                            "x": float(location.x),
                            "y": float(location.y),
                            "z": float(location.z),
                        }},
                        "rotation": {{
                            "pitch": float(rotation.pitch),
                            "yaw": float(rotation.yaw),
                            "roll": float(rotation.roll),
                        }},
                        "scale": {{"x": 1.0, "y": 1.0, "z": 1.0}},
                    }}
                    spawn_source = "player_start"

            aggregate_properties = (
                "box_elems",
                "sphere_elems",
                "sphyl_elems",
                "convex_elems",
                "tapered_capsule_elems",
                "level_set_elems",
                "skinned_level_set_elems",
            )
            complex_as_simple = getattr(
                getattr(unreal, "CollisionTraceFlag", None),
                "CTF_USE_COMPLEX_AS_SIMPLE",
                None,
            )
            for static_mesh_path, usage in sorted(static_mesh_usage.items()):
                static_mesh = unreal.EditorAssetLibrary.load_asset(static_mesh_path)
                body_setup = None
                simple_shape_count = 0
                trace_flag = ""
                repair_error = ""
                if static_mesh is not None:
                    try:
                        body_setup = static_mesh.get_editor_property("body_setup")
                    except Exception:
                        body_setup = None
                if body_setup is not None:
                    try:
                        trace_flag = str(body_setup.get_editor_property("collision_trace_flag"))
                    except Exception:
                        trace_flag = ""
                    try:
                        aggregate_geometry = body_setup.get_editor_property("agg_geom")
                    except Exception:
                        aggregate_geometry = None
                    if aggregate_geometry is not None:
                        for property_name in aggregate_properties:
                            try:
                                simple_shape_count += len(
                                    aggregate_geometry.get_editor_property(property_name)
                                )
                            except Exception:
                                pass
                usable_collision = bool(
                    simple_shape_count > 0
                    or "COMPLEX_AS_SIMPLE" in trace_flag
                )
                repaired = False
                if (
                    not usable_collision
                    and repair_missing_collision
                    and body_setup is not None
                    and complex_as_simple is not None
                ):
                    try:
                        body_setup.set_editor_property(
                            "collision_trace_flag",
                            complex_as_simple,
                        )
                        body_setup.invalidate_physics_data()
                        body_setup.create_physics_meshes()
                        unreal.EditorAssetLibrary.save_loaded_asset(
                            static_mesh,
                            only_if_is_dirty=False,
                        )
                        trace_flag = str(
                            body_setup.get_editor_property("collision_trace_flag")
                        )
                        usable_collision = True
                        repaired = True
                        repaired_collision_assets.append(static_mesh_path)
                    except Exception as exc:
                        repair_error = str(exc)
                if usable_collision:
                    usable_static_mesh_components += int(usage["components"])
                else:
                    missing_collision_assets.append(static_mesh_path)
                collision_assets.append({{
                    "path": static_mesh_path,
                    "components": int(usage["components"]),
                    "profiles": list(usage["profiles"]),
                    "simple_shapes": int(simple_shape_count),
                    "trace_flag": trace_flag,
                    "usable": bool(usable_collision),
                    "repaired": bool(repaired),
                    "repair_error": repair_error,
                }})

            if missing_collision_assets:
                warnings.append(
                    "有 "
                    + str(len(missing_collision_assets))
                    + " 个已启用碰撞的 StaticMesh 没有简单碰撞；"
                    + (
                        "已尝试修复，失败项见 collision.assets"
                        if repair_missing_collision
                        else "可启用 repair_missing_collision 使用 Complex as Simple 修复"
                    )
                )

            if player_start is None and house_candidates:
                house_candidates.sort(key=lambda item: item[0])
                _, framed_actor, origin, extent = house_candidates[0]
                clearance = max(float(extent.x) * 0.35, 300.0)
                suggested_spawn = {{
                    "location": {{
                        "x": float(origin.x - extent.x - clearance),
                        "y": float(origin.y),
                        "z": float(origin.z - extent.z + 92.0),
                    }},
                    "rotation": {{"pitch": 0.0, "yaw": 0.0, "roll": 0.0}},
                    "scale": {{"x": 1.0, "y": 1.0, "z": 1.0}},
                }}
                spawn_source = "house_clearance"
            elif player_start is None and landscape_candidates:
                landscape_candidates.sort(key=lambda item: (item[0], item[1]))
                _, _, origin, extent = landscape_candidates[0]
                suggested_spawn = {{
                    "location": {{
                        "x": float(origin.x),
                        "y": float(origin.y),
                        "z": float(origin.z + extent.z + 200.0),
                    }},
                    "rotation": {{"pitch": 0.0, "yaw": 0.0, "roll": 0.0}},
                    "scale": {{"x": 1.0, "y": 1.0, "z": 1.0}},
                }}
                spawn_source = "landscape_bounds"

            if player_start is None and suggested_spawn is not None:
                try:
                    spawn_location = suggested_spawn["location"]
                    spawn_rotation = suggested_spawn["rotation"]
                    actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                    auto_player_start = actor_subsystem.spawn_actor_from_class(
                        unreal.PlayerStart,
                        unreal.Vector(
                            float(spawn_location["x"]),
                            float(spawn_location["y"]),
                            float(spawn_location["z"]),
                        ),
                        unreal.Rotator(
                            pitch=float(spawn_rotation["pitch"]),
                            yaw=float(spawn_rotation["yaw"]),
                            roll=float(spawn_rotation["roll"]),
                        ),
                    )
                    if auto_player_start is not None:
                        auto_player_start.set_actor_label("A3Game_AutoPlayerStart")
                        player_start = suggested_spawn
                        spawn_source = "auto_player_start:" + spawn_source
                        unreal.EditorLevelLibrary.save_current_level()
                except Exception as exc:
                    warnings.append("创建自动 PlayerStart 失败: " + str(exc))

            if house_candidates:
                house_candidates.sort(key=lambda item: item[0])
                _, framed_actor, origin, extent = house_candidates[0]
                distance = max(
                    abs(float(extent.x)),
                    abs(float(extent.y)),
                    abs(float(extent.z)),
                    400.0,
                ) * 4.0
                camera_location = unreal.Vector(
                    origin.x - distance,
                    origin.y - distance,
                    origin.z + max(float(extent.z) * 1.5, 600.0),
                )
                camera_rotation = unreal.MathLibrary.find_look_at_rotation(camera_location, origin)
                try:
                    unreal.EditorLevelLibrary.set_level_viewport_camera_info(camera_location, camera_rotation)
                except Exception as exc:
                    warnings.append("设置场景预览相机失败: " + str(exc))

            try:
                unreal.SystemLibrary.execute_console_command(loaded_world, "viewmode lit")
            except Exception:
                pass
            if render_repairs:
                try:
                    unreal.EditorLevelLibrary.save_current_level()
                except Exception as exc:
                    warnings.append("保存渲染兼容修复失败: " + str(exc))
            if stationary_point_lights:
                warnings.append(
                    "场景包含 "
                    + str(stationary_point_lights)
                    + " 个 Stationary PointLight；已转换 "
                    + str(converted_stationary_point_lights)
                    + " 个为 Movable，避免依赖未随包提供的烘焙照明"
                )
            try:
                unreal.EditorLevelLibrary.editor_invalidate_viewports()
            except Exception:
                pass

        result = {{
            "ok": True,
            "content_root_path": content_root_path,
            "selected_map_path": selected_map_path,
            "maps": discovered_maps,
            "loaded": bool(load_map),
            "actor_count": actor_count,
            "player_start": player_start,
            "suggested_spawn": suggested_spawn,
            "spawn_source": spawn_source,
            "render_repairs": render_repairs,
            "framed_actor": framed_actor,
            "stationary_point_lights": stationary_point_lights,
            "converted_stationary_point_lights": (
                converted_stationary_point_lights
            ),
            "collision": {{
                "collidable": bool(
                    landscape_collision_components > 0
                    or usable_static_mesh_components > 0
                    or collision_component_count > static_mesh_component_count
                ),
                "collision_components": collision_component_count,
                "collision_component_classes": collision_class_counts,
                "landscape_collision_components": landscape_collision_components,
                "static_mesh_components": static_mesh_component_count,
                "usable_static_mesh_components": usable_static_mesh_components,
                "active_static_mesh_assets": len(collision_assets),
                "usable_static_mesh_assets": len([
                    item for item in collision_assets if item["usable"]
                ]),
                "missing_static_mesh_assets": missing_collision_assets,
                "repaired_static_mesh_assets": repaired_collision_assets,
                "repair_missing_collision": bool(repair_missing_collision),
                "assets": collision_assets,
            }},
            "warnings": warnings,
        }}
    """)


__all__ = ["build_native_scene_register_script"]
