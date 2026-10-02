"""Open the approved A3Game VFX assets for interactive UE review."""
from __future__ import annotations

import unreal

from ue5_test_paths import content_path


REVIEW_MAP = content_path("Maps/PreviewStage")
REVIEW_ASSETS = (
    ("01 natural fire", content_path("Preview/seq_NS_Fire")),
    ("02 natural smoke", content_path("Preview/seq_NS_Smoke_Plume")),
    ("03 natural style baseline", content_path("Preview/seq_NS_Fire")),
    ("04 ink", content_path("Sequences/seq_sp_ink_full_c0")),
    ("05 frost", content_path("Sequences/seq_sp_ice_full_c0")),
    ("06 cyber", content_path("Sequences/seq_sp_cyber_full_c0")),
    ("07 punch fire", content_path("Sequences/seq_punch_fire_review_c0")),
)


def register_review_menu() -> None:
    menus = unreal.ToolMenus.get()
    main_menu = menus.find_menu("LevelEditor.MainMenu")
    if main_menu is None:
        raise RuntimeError("could not find the UE level-editor main menu")

    review_menu = main_menu.add_sub_menu(
        "A3Game",
        "A3Game",
        "A3GameVFXReview",
        "A3Game VFX Review",
        "Open the nine-result VFX review entries",
    )
    for index, (label, path) in enumerate(REVIEW_ASSETS, start=1):
        entry = unreal.ToolMenuEntry(
            name=f"A3GameVFXReview_{index:02d}",
            type=unreal.MultiBlockType.MENU_ENTRY,
        )
        entry.set_label(label)
        entry.set_tool_tip(path)
        command = (
            "asset = unreal.EditorAssetLibrary.load_asset(" + repr(path) + "); "
            "unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)"
            ".open_editor_for_assets([asset])"
        )
        entry.set_string_command(
            unreal.ToolMenuStringCommandType.PYTHON,
            "",
            command,
        )
        review_menu.add_menu_entry("A3GameVFXReview", entry)
    menus.refresh_all_widgets()


def main() -> None:
    level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not level_editor.load_level(REVIEW_MAP):
        raise RuntimeError(f"could not load review map: {REVIEW_MAP}")

    loaded = []
    missing = []
    for label, path in REVIEW_ASSETS:
        asset = unreal.EditorAssetLibrary.load_asset(path)
        if asset is None:
            missing.append(f"{label}: {path}")
        else:
            loaded.append(asset)
    if missing:
        raise RuntimeError("missing review assets: " + "; ".join(missing))

    register_review_menu()
    unreal.EditorAssetLibrary.sync_browser_to_objects(
        [asset.get_path_name() for asset in loaded]
    )
    asset_editors = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
    asset_editors.open_editor_for_assets([loaded[3]])
    unreal.log(
        "[AAAGF_VFX_REVIEW] Registered seven UE review menu entries and opened ink. "
        "Use A3Game VFX Review in the main menu; Unity contains entries 08-09."
    )


main()
