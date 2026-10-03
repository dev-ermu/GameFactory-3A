"""UE Python scripts for importing XV3dGS Gaussian Splat assets."""

import textwrap


def build_gaussian_splat_import_script(
    source_path: str,
    destination_path: str,
    asset_name: str,
) -> str:
    """Import one PLY and persist both XV3dGS generated packages."""

    return textwrap.dedent(
        f"""\
        import unreal

        source_path = {source_path!r}
        destination_path = {destination_path.rstrip('/')!r}
        asset_name = {asset_name!r}
        buffer_path = destination_path + "/" + asset_name
        actor_path = buffer_path + "_actor"

        for old_path in (actor_path, buffer_path):
            if unreal.EditorAssetLibrary.does_asset_exist(old_path):
                if not unreal.EditorAssetLibrary.delete_asset(old_path):
                    raise RuntimeError(
                        f"Failed to replace existing Gaussian asset: {{old_path}}"
                    )

        task = unreal.AssetImportTask()
        task.set_editor_property("filename", source_path)
        task.set_editor_property("destination_path", destination_path)
        task.set_editor_property("destination_name", asset_name)
        task.set_editor_property("automated", True)
        task.set_editor_property("replace_existing", True)
        # XV3dGS creates a second Blueprint package after the buffer import.
        # Save both packages explicitly after the factory has completed.
        task.set_editor_property("save", False)
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

        imported_paths = [
            str(path)
            for path in (
                task.get_editor_property("imported_object_paths") or []
            )
        ]
        if not imported_paths:
            raise RuntimeError(
                "XV3dGS import returned no GSRuntimeBuffer asset"
            )

        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        registry.scan_paths_synchronous([destination_path], True)
        if not unreal.EditorAssetLibrary.does_asset_exist(buffer_path):
            raise RuntimeError(
                f"XV3dGS buffer package was not generated: {{buffer_path}}"
            )
        if not unreal.EditorAssetLibrary.does_asset_exist(actor_path):
            raise RuntimeError(
                f"XV3dGS actor Blueprint was not generated: {{actor_path}}"
            )

        buffer_asset = unreal.load_asset(buffer_path)
        if (
            buffer_asset is None
            or buffer_asset.get_class().get_name() != "GSRuntimeBuffer"
        ):
            actual_class = (
                buffer_asset.get_class().get_name()
                if buffer_asset is not None
                else "<missing>"
            )
            raise RuntimeError(
                "XV3dGS imported an unexpected buffer class: "
                + actual_class
            )

        actor_class = unreal.EditorAssetLibrary.load_blueprint_class(
            actor_path
        )
        if actor_class is None:
            raise RuntimeError(
                f"Unable to load XV3dGS actor Blueprint class: {{actor_path}}"
            )
        actor_default = unreal.get_default_object(actor_class)
        configured_buffer_path = str(
            actor_default.get_editor_property("buffer_package_path")
        )
        if configured_buffer_path != buffer_path:
            actor_default.set_editor_property(
                "buffer_package_path",
                buffer_path,
            )

        saved_buffer = unreal.EditorAssetLibrary.save_asset(
            buffer_path,
            only_if_is_dirty=False,
        )
        saved_actor = unreal.EditorAssetLibrary.save_asset(
            actor_path,
            only_if_is_dirty=False,
        )
        unreal.EditorAssetLibrary.save_directory(
            destination_path,
            only_if_is_dirty=False,
            recursive=True,
        )
        if not saved_buffer or not saved_actor:
            raise RuntimeError(
                "Failed to persist XV3dGS buffer and actor Blueprint"
            )

        result = {{
            "ok": True,
            "source_path": source_path,
            "destination_path": destination_path,
            "asset_name": asset_name,
            "buffer_path": buffer_path,
            "buffer_class": buffer_asset.get_class().get_name(),
            "actor_path": actor_path,
            "actor_class": actor_class.get_name(),
            "configured_buffer_path": str(
                actor_default.get_editor_property("buffer_package_path")
            ),
            "imported_paths": imported_paths,
            "saved_buffer": bool(saved_buffer),
            "saved_actor": bool(saved_actor),
        }}
        """
    )


__all__ = ["build_gaussian_splat_import_script"]
