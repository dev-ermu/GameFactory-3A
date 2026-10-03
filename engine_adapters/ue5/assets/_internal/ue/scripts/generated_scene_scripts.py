"""UE Python scripts for building native maps from generated scene layouts."""

import textwrap
from typing import Any


def build_generated_scene_prepare_script(
    content_root: str,
    *,
    replace_existing: bool,
) -> str:
    """Reject or clear a generated scene Content root before import."""
    return textwrap.dedent(
        f"""\
        import unreal

        content_root = {content_root.rstrip('/')!r}
        replace_existing = {bool(replace_existing)!r}
        exists = unreal.EditorAssetLibrary.does_directory_exist(content_root)
        deleted = False
        if exists:
            if not replace_existing:
                raise RuntimeError(
                    f"目标 UE Scene Content 已存在: {{content_root}}；"
                    "请启用 replace_existing"
                )
            try:
                asset_editor = unreal.get_editor_subsystem(
                    unreal.AssetEditorSubsystem
                )
                close_all = getattr(
                    asset_editor,
                    "close_all_asset_editors",
                    None,
                )
                if callable(close_all):
                    close_all()
            except Exception:
                pass
            try:
                unreal.EditorLoadingAndSavingUtils.load_map(
                    "/Engine/Maps/Entry"
                )
            except Exception:
                pass
            try:
                unreal.SystemLibrary.collect_garbage()
            except Exception:
                pass
            deleted = unreal.EditorAssetLibrary.delete_directory(content_root)
            if not deleted:
                raise RuntimeError(
                    f"删除旧 UE Scene Content 失败: {{content_root}}"
                )
        result = {{
            "ok": True,
            "content_root": content_root,
            "existed": exists,
            "deleted": deleted,
        }}
        """
    )


def build_generated_scene_map_script(
    map_path: str,
    actors: list[dict[str, Any]],
    *,
    spawn_point: dict[str, Any] | None = None,
    replace_existing: bool = False,
    add_default_lighting: bool = True,
    add_default_ground: bool = False,
    safety_floor: dict[str, Any] | None = None,
    preview_in_editor: bool = True,
) -> str:
    """Create a native UE level, place imported assets, and save the map."""
    return textwrap.dedent(
        f"""\
        import unreal

        map_path = {map_path!r}
        actor_specs = {actors!r}
        spawn_point = {dict(spawn_point or {})!r}
        replace_existing = {bool(replace_existing)!r}
        add_default_lighting = {bool(add_default_lighting)!r}
        add_default_ground = {bool(add_default_ground)!r}
        safety_floor = {dict(safety_floor or {})!r}
        preview_in_editor = {bool(preview_in_editor)!r}

        def _vector(value, default):
            value = value if isinstance(value, dict) else {{}}
            return unreal.Vector(
                float(value.get("x", default[0])),
                float(value.get("y", default[1])),
                float(value.get("z", default[2])),
            )

        def _rotator(value):
            value = value if isinstance(value, dict) else {{}}
            pitch = float(value.get("pitch", 0.0))
            yaw = float(value.get("yaw", 0.0))
            roll = float(value.get("roll", 0.0))
            try:
                return unreal.Rotator(pitch=pitch, yaw=yaw, roll=roll)
            except Exception:
                result = unreal.Rotator()
                for name, component in (
                    ("pitch", pitch),
                    ("yaw", yaw),
                    ("roll", roll),
                ):
                    result.set_editor_property(name, component)
                return result

        def _spawn_actor(actor_class, location, rotation):
            actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            try:
                return actor_subsystem.spawn_actor_from_class(
                    actor_class,
                    location,
                    rotation,
                )
            except Exception:
                return unreal.EditorLevelLibrary.spawn_actor_from_class(
                    actor_class,
                    location,
                    rotation,
                )

        def _vector_dict(value):
            return {{
                "x": float(value.x),
                "y": float(value.y),
                "z": float(value.z),
            }}

        def _editor_world():
            try:
                return unreal.get_editor_subsystem(
                    unreal.UnrealEditorSubsystem
                ).get_editor_world()
            except Exception:
                return unreal.EditorLevelLibrary.get_editor_world()

        def _grounded_spawn_location(seed):
            world = _editor_world()
            if world is None:
                return seed, False
            start = unreal.Vector(
                float(seed.x),
                float(seed.y),
                max(float(seed.z) + 50000.0, 50000.0),
            )
            end = unreal.Vector(
                float(seed.x),
                float(seed.y),
                min(float(seed.z) - 50000.0, -50000.0),
            )
            try:
                trace_result = unreal.SystemLibrary.line_trace_single(
                    world,
                    start,
                    end,
                    unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
                    True,
                    [],
                    unreal.DrawDebugTrace.NONE,
                    True,
                )
            except Exception as exc:
                warnings.append(
                    f"PlayerStart 地面检测失败: {{exc}}"
                )
                return seed, False
            hit = None
            hit_ok = False
            values = (
                trace_result
                if isinstance(trace_result, tuple)
                else (trace_result,)
            )
            for value in values:
                if isinstance(value, bool):
                    hit_ok = hit_ok or value
                elif hasattr(value, "impact_point"):
                    hit = value
            if hit is None or not hit_ok:
                return seed, False
            try:
                normal = hit.impact_normal
                if float(normal.z) < 0.55:
                    return seed, False
                point = hit.impact_point
                return unreal.Vector(
                    float(point.x),
                    float(point.y),
                    float(point.z) + 93.0,
                ), True
            except Exception:
                return seed, False

        def _create_level(asset_path):
            level_subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
            create = getattr(level_subsystem, "new_level", None)
            if callable(create):
                created = create(asset_path)
            else:
                created = unreal.EditorLevelLibrary.new_level(asset_path)
            if created is False:
                raise RuntimeError(f"创建 UE Level 失败: {{asset_path}}")

        def _static_mesh_collision(mesh):
            body_setup = None
            simple_shape_count = 0
            trace_flag = ""
            error = ""
            try:
                body_setup = mesh.get_editor_property("body_setup")
            except Exception as exc:
                error = str(exc)
            if body_setup is not None:
                try:
                    trace_flag = str(
                        body_setup.get_editor_property("collision_trace_flag")
                    )
                except Exception:
                    pass
                try:
                    aggregate_geometry = body_setup.get_editor_property(
                        "agg_geom"
                    )
                except Exception:
                    aggregate_geometry = None
                if aggregate_geometry is not None:
                    for property_name in (
                        "box_elems",
                        "sphere_elems",
                        "sphyl_elems",
                        "convex_elems",
                        "tapered_capsule_elems",
                        "level_set_elems",
                        "skinned_level_set_elems",
                    ):
                        try:
                            simple_shape_count += len(
                                aggregate_geometry.get_editor_property(
                                    property_name
                                )
                            )
                        except Exception:
                            pass
            return {{
                "body_setup": body_setup,
                "simple_shapes": int(simple_shape_count),
                "trace_flag": trace_flag,
                "usable": bool(
                    simple_shape_count > 0
                    or "COMPLEX_AS_SIMPLE" in trace_flag
                ),
                "error": error,
            }}

        def _ensure_static_mesh_collision(mesh, force_complex=False):
            audit = _static_mesh_collision(mesh)
            repaired = False
            repair_error = ""
            complex_enabled = "COMPLEX_AS_SIMPLE" in audit["trace_flag"]
            if (
                (not audit["usable"] or (force_complex and not complex_enabled))
                and audit["body_setup"] is not None
            ):
                collision_flag = getattr(
                    getattr(unreal, "CollisionTraceFlag", None),
                    "CTF_USE_COMPLEX_AS_SIMPLE",
                    None,
                )
                if collision_flag is not None:
                    try:
                        body_setup = audit["body_setup"]
                        body_setup.set_editor_property(
                            "collision_trace_flag",
                            collision_flag,
                        )
                        body_setup.invalidate_physics_data()
                        body_setup.create_physics_meshes()
                        unreal.EditorAssetLibrary.save_loaded_asset(
                            mesh,
                            only_if_is_dirty=False,
                        )
                        repaired = True
                    except Exception as exc:
                        repair_error = str(exc)
            result = _static_mesh_collision(mesh)
            result.pop("body_setup", None)
            result["repaired"] = repaired
            result["repair_error"] = repair_error
            result["force_complex"] = bool(force_complex)
            result["complex_as_simple"] = (
                "COMPLEX_AS_SIMPLE" in result["trace_flag"]
            )
            return result

        def _configure_component_collision(component, enabled):
            if enabled:
                component.set_collision_profile_name("BlockAll")
                component.set_collision_enabled(
                    unreal.CollisionEnabled.QUERY_AND_PHYSICS
                )
                component.set_collision_object_type(
                    unreal.CollisionChannel.ECC_WORLD_STATIC
                )
                component.set_collision_response_to_all_channels(
                    unreal.CollisionResponseType.ECR_BLOCK
                )
                try:
                    component.set_can_ever_affect_navigation(True)
                except Exception:
                    pass
            else:
                component.set_collision_profile_name("NoCollision")
                component.set_collision_enabled(
                    unreal.CollisionEnabled.NO_COLLISION
                )
                component.set_collision_response_to_all_channels(
                    unreal.CollisionResponseType.ECR_IGNORE
                )
                try:
                    component.set_can_ever_affect_navigation(False)
                except Exception:
                    pass

        def _component_collision(component):
            pawn_response = ""
            try:
                pawn_response = str(
                    component.get_collision_response_to_channel(
                        unreal.CollisionChannel.ECC_PAWN
                    )
                )
            except Exception:
                pass
            enabled = str(component.get_collision_enabled())
            return {{
                "enabled": enabled,
                "profile": str(component.get_collision_profile_name()),
                "pawn_response": pawn_response,
                "disabled": "NO_COLLISION" in enabled,
                "blocks_pawn": bool(
                    "NO_COLLISION" not in enabled
                    and "ECR_BLOCK" in pawn_response
                ),
            }}

        if unreal.EditorAssetLibrary.does_asset_exist(map_path):
            if not replace_existing:
                raise RuntimeError(
                    f"目标 UE Map 已存在: {{map_path}}；请启用 replace_existing"
                )
            try:
                unreal.EditorLoadingAndSavingUtils.load_map("/Engine/Maps/Entry")
            except Exception:
                pass
            if not unreal.EditorAssetLibrary.delete_asset(map_path):
                raise RuntimeError(f"删除已有 UE Map 失败: {{map_path}}")

        _create_level(map_path)
        spawned = []
        warnings = []
        collision_actors = []
        collision_failures = []
        placement_failures = []
        if add_default_ground:
            ground_mesh = unreal.load_asset("/Engine/BasicShapes/Plane.Plane")
            if isinstance(ground_mesh, unreal.StaticMesh):
                ground = _spawn_actor(
                    unreal.StaticMeshActor,
                    unreal.Vector(0.0, 0.0, 0.0),
                    _rotator({{}}),
                )
                if ground is not None:
                    ground_component = ground.get_editor_property(
                        "static_mesh_component"
                    )
                    ground_component.set_static_mesh(ground_mesh)
                    _configure_component_collision(ground_component, True)
                    ground.set_actor_scale3d(
                        unreal.Vector(20.0, 20.0, 1.0)
                    )
                    ground.set_actor_label("A3Game_DefaultGround")
                    mesh_collision = _ensure_static_mesh_collision(ground_mesh)
                    component_collision = _component_collision(
                        ground_component
                    )
                    collision_actors.append({{
                        "entity_id": "__default_ground__",
                        "actor_label": ground.get_actor_label(),
                        "asset_path": ground_mesh.get_path_name(),
                        "requested": True,
                        "mesh": mesh_collision,
                        "component": component_collision,
                    }})
                    if (
                        not mesh_collision["usable"]
                        or not component_collision["blocks_pawn"]
                    ):
                        collision_failures.append("__default_ground__")
                else:
                    placement_failures.append("__default_ground__: spawn failed")
            else:
                placement_failures.append(
                    "__default_ground__: 无法加载 /Engine/BasicShapes/Plane"
                )

        safety_floor_result = {{"enabled": False}}
        if bool(safety_floor.get("enabled", False)):
            floor_mesh = unreal.load_asset("/Engine/BasicShapes/Cube.Cube")
            if isinstance(floor_mesh, unreal.StaticMesh):
                center = _vector(
                    safety_floor.get("location"),
                    (0.0, 0.0, -20.0),
                )
                size = _vector(
                    safety_floor.get("size"),
                    (2000.0, 2000.0, 20.0),
                )
                guard = _spawn_actor(
                    unreal.StaticMeshActor,
                    center,
                    _rotator({{}}),
                )
                if guard is not None:
                    guard_component = guard.get_editor_property(
                        "static_mesh_component"
                    )
                    guard_component.set_static_mesh(floor_mesh)
                    _configure_component_collision(guard_component, True)
                    guard_component.set_visibility(False, True)
                    guard.set_actor_hidden_in_game(True)
                    guard.set_actor_scale3d(
                        unreal.Vector(
                            max(float(size.x), 1.0) / 100.0,
                            max(float(size.y), 1.0) / 100.0,
                            max(float(size.z), 1.0) / 100.0,
                        )
                    )
                    guard.set_actor_label("A3Game_SafetyFloor")
                    mesh_collision = _ensure_static_mesh_collision(floor_mesh)
                    component_collision = _component_collision(
                        guard_component
                    )
                    collision_actors.append({{
                        "entity_id": "__safety_floor__",
                        "actor_label": guard.get_actor_label(),
                        "asset_path": floor_mesh.get_path_name(),
                        "requested": True,
                        "mesh": mesh_collision,
                        "component": component_collision,
                    }})
                    if (
                        not mesh_collision["usable"]
                        or not component_collision["blocks_pawn"]
                    ):
                        collision_failures.append("__safety_floor__")
                    spawned.append({{
                        "entity_id": "__safety_floor__",
                        "actor_label": guard.get_actor_label(),
                        "asset_path": floor_mesh.get_path_name(),
                        "backend_class": "StaticMesh",
                        "collision": True,
                        "visible": False,
                    }})
                    safety_floor_result = {{
                        "enabled": True,
                        "location": _vector_dict(center),
                        "size": _vector_dict(size),
                    }}
                else:
                    placement_failures.append(
                        "__safety_floor__: spawn failed"
                    )
            else:
                placement_failures.append(
                    "__safety_floor__: 无法加载 /Engine/BasicShapes/Cube"
                )

        for index, spec in enumerate(actor_specs):
            asset_path = str(spec.get("asset_path") or "")
            asset = unreal.load_asset(asset_path)
            if asset is None:
                placement_failures.append(
                    f"{{spec.get('entity_id') or asset_path}}: 无法加载场景资产 {{asset_path}}"
                )
                continue
            transform = spec.get("transform") or {{}}
            location = _vector(
                transform.get("location"),
                (0.0, 0.0, 0.0),
            )
            rotation = _rotator(transform.get("rotation"))
            scale = _vector(
                transform.get("scale"),
                (1.0, 1.0, 1.0),
            )
            actor_label = str(
                spec.get("actor_label")
                or spec.get("entity_id")
                or f"SceneActor_{{index}}"
            )
            collision_requested = bool(spec.get("collision", True))
            force_complex_collision = bool(
                spec.get("force_complex_collision", False)
            )
            visible = bool(spec.get("visible", True))
            backend_class = str(spec.get("backend_class") or "")

            if isinstance(asset, unreal.StaticMesh):
                actor = _spawn_actor(
                    unreal.StaticMeshActor,
                    location,
                    rotation,
                )
                if actor is None:
                    placement_failures.append(
                        f"{{spec.get('entity_id') or asset_path}}: "
                        f"创建 StaticMeshActor 失败 {{asset_path}}"
                    )
                    continue
                component = actor.get_editor_property(
                    "static_mesh_component"
                )
                component.set_static_mesh(asset)
                _configure_component_collision(
                    component,
                    collision_requested,
                )
                component.set_visibility(visible, True)
                actor.set_actor_scale3d(scale)
                actor.set_actor_label(actor_label)
                actor.set_actor_hidden_in_game(not visible)
                mesh_collision = (
                    _ensure_static_mesh_collision(
                        asset,
                        force_complex=force_complex_collision,
                    )
                    if collision_requested
                    else {{
                        "simple_shapes": 0,
                        "trace_flag": "",
                        "usable": False,
                        "error": "",
                        "repaired": False,
                        "repair_error": "",
                        "force_complex": False,
                        "complex_as_simple": False,
                    }}
                )
                component_collision = _component_collision(component)
                collision_actors.append({{
                    "entity_id": str(spec.get("entity_id") or ""),
                    "actor_label": actor.get_actor_label(),
                    "asset_path": asset_path,
                    "requested": collision_requested,
                    "mesh": mesh_collision,
                    "component": component_collision,
                }})
                if collision_requested and (
                    not mesh_collision["usable"]
                    or (
                        force_complex_collision
                        and not mesh_collision["complex_as_simple"]
                    )
                    or not component_collision["blocks_pawn"]
                ):
                    collision_failures.append(
                        str(spec.get("entity_id") or asset_path)
                    )
                if (
                    not collision_requested
                    and not component_collision["disabled"]
                ):
                    collision_failures.append(
                        str(spec.get("entity_id") or asset_path)
                        + ": collision disable failed"
                    )
                spawned.append(
                    {{
                        "entity_id": str(spec.get("entity_id") or ""),
                        "actor_label": actor.get_actor_label(),
                        "asset_path": asset_path,
                        "backend_class": "StaticMesh",
                        "collision": collision_requested,
                        "visible": visible,
                    }}
                )
                continue

            asset_class = asset.get_class().get_name()
            if (
                backend_class in {{
                    "Blueprint",
                    "BlueprintGeneratedClass",
                }}
                or asset_class == "Blueprint"
            ):
                if collision_requested:
                    placement_failures.append(
                        f"{{spec.get('entity_id') or asset_path}}: "
                        "Blueprint 场景实体不能作为自动碰撞网格"
                    )
                    continue
                actor_class = (
                    unreal.EditorAssetLibrary.load_blueprint_class(
                        asset_path
                    )
                )
                if actor_class is None:
                    placement_failures.append(
                        f"{{spec.get('entity_id') or asset_path}}: "
                        f"无法加载 Blueprint Class {{asset_path}}"
                    )
                    continue
                actor = _spawn_actor(
                    actor_class,
                    location,
                    rotation,
                )
                if actor is None:
                    placement_failures.append(
                        f"{{spec.get('entity_id') or asset_path}}: "
                        f"创建 Blueprint Actor 失败 {{asset_path}}"
                    )
                    continue
                actor.set_actor_scale3d(scale)
                actor.set_actor_label(actor_label)
                spawned.append(
                    {{
                        "entity_id": str(spec.get("entity_id") or ""),
                        "actor_label": actor.get_actor_label(),
                        "asset_path": asset_path,
                        "backend_class": backend_class or asset_class,
                        "collision": False,
                        "visible": True,
                    }}
                )
                continue

            if not isinstance(asset, unreal.StaticMesh):
                placement_failures.append(
                    f"{{spec.get('entity_id') or asset_path}}: "
                    f"场景包无法放置 {{asset_path}} "
                    f"({{asset_class}})"
                )
                continue

        spawn_transform = spawn_point if isinstance(spawn_point, dict) else {{}}
        requested_spawn_location = _vector(
            spawn_transform.get("location"),
            (0.0, 0.0, 100.0),
        )
        resolved_spawn_location, spawn_grounded = (
            _grounded_spawn_location(requested_spawn_location)
        )
        player_start = _spawn_actor(
            unreal.PlayerStart,
            resolved_spawn_location,
            _rotator(spawn_transform.get("rotation")),
        )
        if player_start is not None:
            player_start.set_actor_label("A3Game_PlayerStart")
        resolved_spawn_transform = dict(spawn_transform)
        resolved_spawn_transform["location"] = _vector_dict(
            resolved_spawn_location
        )

        if add_default_lighting:
            directional = _spawn_actor(
                unreal.DirectionalLight,
                unreal.Vector(0.0, 0.0, 1000.0),
                _rotator({{"pitch": -45.0, "yaw": -30.0, "roll": 0.0}}),
            )
            if directional is not None:
                directional.set_actor_label("A3Game_DirectionalLight")
            sky = _spawn_actor(
                unreal.SkyLight,
                unreal.Vector(0.0, 0.0, 500.0),
                _rotator({{}}),
            )
            if sky is not None:
                sky.set_actor_label("A3Game_SkyLight")

        if placement_failures:
            raise RuntimeError(
                "生成场景存在未成功放置的物体: "
                + " | ".join(placement_failures)
            )
        if collision_failures:
            raise RuntimeError(
                "生成场景存在无法阻挡 Pawn 的碰撞物体: "
                + ", ".join(collision_failures)
            )

        if not unreal.EditorLevelLibrary.save_current_level():
            raise RuntimeError(f"保存 UE Map 失败: {{map_path}}")
        unreal.EditorAssetLibrary.save_directory(
            map_path.rsplit("/", 1)[0],
            only_if_is_dirty=False,
            recursive=True,
        )

        requested_collision_actors = [
            item for item in collision_actors if item["requested"]
        ]
        blocking_collision_actors = [
            item
            for item in requested_collision_actors
            if item["mesh"]["usable"]
            and item["component"]["blocks_pawn"]
        ]
        collision_result = {{
            "collidable": bool(
                requested_collision_actors
                and len(blocking_collision_actors)
                == len(requested_collision_actors)
            ),
            "requested_actors": len(requested_collision_actors),
            "blocking_actors": len(blocking_collision_actors),
            "disabled_actors": len([
                item
                for item in collision_actors
                if (
                    not item["requested"]
                    and item["component"]["disabled"]
                )
            ]),
            "failures": list(collision_failures),
            "actors": collision_actors,
        }}
        result = {{
            "ok": True,
            "map_path": map_path,
            "actor_count": len(spawned),
            "actors": spawned,
            "player_start": resolved_spawn_transform,
            "player_start_grounded": bool(spawn_grounded),
            "default_lighting": add_default_lighting,
            "default_ground": add_default_ground,
            "safety_floor": safety_floor_result,
            "collision": collision_result,
            "warnings": warnings,
        }}
        if not preview_in_editor:
            try:
                unreal.EditorLoadingAndSavingUtils.load_map("/Engine/Maps/Entry")
            except Exception as exc:
                result["warnings"].append(
                    f"生成地图后无法切回 Entry: {{exc}}"
                )
        """
    )


__all__ = [
    "build_generated_scene_map_script",
    "build_generated_scene_prepare_script",
]
