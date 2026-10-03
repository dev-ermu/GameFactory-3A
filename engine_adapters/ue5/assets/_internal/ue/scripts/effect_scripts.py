"""UE Python script builders for effect package registration."""

import textwrap
from typing import Any


def _effect_script_helpers() -> str:
    return textwrap.dedent("""\
        import unreal

        def _asset_class_name(asset_data):
            try:
                return str(asset_data.asset_class_path.asset_name)
            except Exception:
                try:
                    return str(asset_data.asset_class)
                except Exception:
                    return ""

        def _asset_record(asset_data):
            return {
                "name": str(asset_data.asset_name),
                "path": str(asset_data.package_name),
                "class": _asset_class_name(asset_data),
                "package_path": str(asset_data.package_path),
            }

        def _loaded_asset_record(asset):
            if asset is None:
                return {}
            asset_path = str(asset.get_path_name()).split(".", 1)[0]
            return {
                "name": asset_path.rsplit("/", 1)[-1],
                "path": asset_path,
                "class": asset.get_class().get_name(),
                "package_path": asset_path.rsplit("/", 1)[0],
            }
    """)


def build_effect_content_register_script(root_path: str) -> str:
    return _effect_script_helpers() + textwrap.dedent(f"""\
        root_path = {root_path!r}
        asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
        try:
            asset_registry.scan_paths_synchronous(
                [root_path],
                force_rescan=True,
            )
        except TypeError:
            asset_registry.scan_paths_synchronous([root_path])
        assets = asset_registry.get_assets_by_path(
            root_path,
            recursive=True,
        )
        all_assets = [_asset_record(asset) for asset in assets]
        effect_classes = {{
            "NiagaraSystem",
            "NiagaraEmitter",
            "ParticleSystem",
        }}
        playable_classes = {{
            "NiagaraSystem",
            "ParticleSystem",
        }}
        effect_assets = [
            asset
            for asset in all_assets
            if asset["class"] in effect_classes
        ]
        playable_effects = [
            asset
            for asset in effect_assets
            if asset["class"] in playable_classes
        ]
        result = {{
            "ok": bool(playable_effects),
            "root_path": root_path,
            "effects": effect_assets,
            "playable_effects": playable_effects,
            "assets": all_assets,
        }}
    """)


def build_generated_effect_entry_script(
    build: dict[str, Any],
    destination_root: str,
    *,
    effect_id: str,
    replace_existing: bool,
) -> str:
    mode = str(build.get("mode") or "none").strip().lower()
    entry_asset = str(build.get("entry_asset") or "").strip()
    template = str(build.get("template") or "").strip()
    output_name = str(
        build.get("output_name")
        or f"NS_{effect_id}"
    ).strip()
    return _effect_script_helpers() + textwrap.dedent(f"""\
        mode = {mode!r}
        destination_root = {destination_root!r}.rstrip("/")
        entry_asset = {entry_asset!r}
        template_path = {template!r}
        output_name = {output_name!r}
        replace_existing = {bool(replace_existing)!r}
        playable_classes = {{
            "NiagaraSystem",
            "ParticleSystem",
        }}

        if mode == "existing_asset":
            asset = unreal.EditorAssetLibrary.load_asset(entry_asset)
            record = _loaded_asset_record(asset)
            if not record:
                result = {{
                    "ok": False,
                    "mode": mode,
                    "error": f"Effect asset not found: {{entry_asset}}",
                }}
            elif record["class"] not in playable_classes:
                result = {{
                    "ok": False,
                    "mode": mode,
                    "error": (
                        f"Entry asset is not a playable effect: "
                        f"{{record['class']}} {{record['path']}}"
                    ),
                }}
            else:
                result = {{
                    "ok": True,
                    "mode": mode,
                    "effect": record,
                    "reused": True,
                }}
        elif mode == "duplicate_template":
            if not unreal.EditorAssetLibrary.does_directory_exist(
                destination_root
            ):
                unreal.EditorAssetLibrary.make_directory(destination_root)
            destination_asset = (
                destination_root + "/" + output_name
            )
            existing = unreal.EditorAssetLibrary.load_asset(
                destination_asset
            )
            if existing is not None and not replace_existing:
                asset = existing
                reused = True
            else:
                if existing is not None:
                    unreal.EditorAssetLibrary.delete_asset(
                        destination_asset
                    )
                template_asset = unreal.EditorAssetLibrary.load_asset(
                    template_path
                )
                if template_asset is None:
                    result = {{
                        "ok": False,
                        "mode": mode,
                        "error": (
                            f"Niagara template not found: "
                            f"{{template_path}}"
                        ),
                    }}
                    asset = None
                    reused = False
                else:
                    asset = unreal.EditorAssetLibrary.duplicate_asset(
                        template_path,
                        destination_asset,
                    )
                    reused = False
                    if asset is not None:
                        unreal.EditorAssetLibrary.save_asset(
                            destination_asset,
                            only_if_is_dirty=False,
                        )
            if asset is not None:
                record = _loaded_asset_record(asset)
                if record["class"] not in playable_classes:
                    result = {{
                        "ok": False,
                        "mode": mode,
                        "error": (
                            f"Template output is not a playable effect: "
                            f"{{record['class']}} {{record['path']}}"
                        ),
                    }}
                else:
                    result = {{
                        "ok": True,
                        "mode": mode,
                        "effect": record,
                        "reused": reused,
                        "template": template_path,
                    }}
        else:
            result = {{
                "ok": True,
                "mode": "none",
                "effect": None,
            }}
    """)


__all__ = [
    "build_effect_content_register_script",
    "build_generated_effect_entry_script",
]
