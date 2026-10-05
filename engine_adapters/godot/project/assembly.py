"""Assembly of independent Godot Mechanic and UI module artifacts.

Godot does not have an assembly definition format equivalent to Unity's
``.asmdef`` or Unreal's module rules.  The adapter therefore treats each
artifact as a small package and materializes a product project explicitly:

    mechanic artifact -> product project
    UI artifact       -> product project/ui/<module>
    generated Main    -> composition root that instantiates both

The mechanic package remains runnable without the UI package.  The UI package
is copied only at assembly time and can depend on the mechanic's public
autoload/runtime contract, never on private gameplay nodes.

独立的Godot机制与UI模块构件组装而成。

Godot没有类似于Unity的`.asmdef`或Unreal的模块规则那样的组装定义格式。因此，适配器将每个构件视为一个小包，并显式生成一个产品项目：

    机制构件 -> 产品项目
    UI构件   -> 产品项目/ui/<模块>
    生成的Main脚本 -> 用于实例化这两者的组合根节点

该机制包即便没有UI包也能正常运行。UI包仅在组装阶段被引入，它只能依赖机制部分的公共自动加载/运行时契约，绝不能依赖私有的游戏逻辑节点。”
"""

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ..contracts import GodotOperationResult

_ASSEMBLY_SCHEMA = "gamefactory3a.godot_module_assembly.v1"
_PACKAGE_FILENAMES = ("package.json", "module_manifest.json")
_NATIVE_UI_EXCLUDES = {"Tests", "browser_play"}
_UI_RESOURCE_PATH = re.compile(r"res://ui/combat_ui\.gd")


def _read_optional_json(root: Path, names: tuple[str, ...]) -> dict[str, Any]:
    for name in names:
        path = root / name
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid module metadata {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"Module metadata must be an object: {path}")
        return value
    return {}


def _read_module_metadata(
    root: Path,
    *,
    contract_names: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Read package metadata and merge the contract fallback fields.

    Generated artifacts from older runs only have ``package.json`` (and the
    mechanic/UI contract beside it).  Newer artifacts may also carry a
    ``module_manifest.json``.  Keeping this compatibility shim in the
    assembler means both layouts behave like Unity's package/asmdef and UE's
    plugin/module descriptor without forcing a regeneration of old outputs.
    """

    metadata = _read_optional_json(root, _PACKAGE_FILENAMES)
    if contract_names:
        contract = _read_optional_json(root, contract_names)
        for key, value in contract.items():
            metadata.setdefault(key, value)
    return metadata


def _module_name(metadata: dict[str, Any], *, fallback: str, kind: str) -> str:
    value = str(
        metadata.get("module_name")
        or metadata.get("ui_module" if kind == "ui" else "gameplay_module")
        or metadata.get("name")
        or fallback
    ).strip()
    value = re.sub(r"[^0-9A-Za-z_.-]+", "_", value).strip("._")
    if not value:
        raise ValueError(f"{kind} module name is empty")
    return value


def _assert_regular_tree(root: Path, label: str) -> None:
    if not root.is_dir():
        raise ValueError(f"{label} must be a directory: {root}")
    if root.is_symlink():
        raise ValueError(f"{label} must not contain symlinks: {root}")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"{label} must not contain symlinks: {path}")
        if not path.is_file() and not path.is_dir():
            raise ValueError(f"{label} contains a special file: {path}")


def _copy_tree(source: Path, destination: Path, *, exclude_godot_cache: bool = True) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {".godot"} if exclude_godot_cache else set()
        return {name for name in names if name in ignored}

    shutil.copytree(source, destination, ignore=ignore)


def _patch_ui_resources(root: Path, package_path: str) -> None:
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".tscn", ".tres", ".gd"}:
            continue
        text = path.read_text(encoding="utf-8")
        patched = _UI_RESOURCE_PATH.sub(f"res://{package_path}/combat_ui.gd", text)
        if patched != text:
            path.write_text(patched, encoding="utf-8")


def _set_main_scene(project_file: Path, main_scene: str) -> None:
    text = project_file.read_text(encoding="utf-8")
    line = f'run/main_scene="{main_scene}"'
    pattern = re.compile(r"(?m)^run/main_scene=.*$")
    if pattern.search(text):
        text = pattern.sub(line, text, count=1)
    else:
        text = text.rstrip() + f"\n\n[application]\n{line}\n"
    project_file.write_text(text.rstrip() + "\n", encoding="utf-8")


def _composition_scene(ui_scene: str) -> str:
    return (
        "[gd_scene load_steps=3 format=3]\n\n"
        '[ext_resource type="PackedScene" path="res://scenes/Mechanic.tscn" id="1_mechanic"]\n'
        f'[ext_resource type="PackedScene" path="res://{ui_scene}" id="2_ui"]\n\n'
        '[node name="NeonAlleyClash" type="Node"]\n\n'
        '[node name="Mechanic" parent="." instance=ExtResource("1_mechanic")]\n\n'
        '[node name="UI" parent="." instance=ExtResource("2_ui")]\n'
    )


def _remove_accidental_ui_from_mechanic(project_root: Path) -> list[str]:
    removed: list[str] = []
    candidates = (
        project_root / "ui",
        project_root / "scenes" / "CombatUI.tscn",
        project_root / "scripts" / "combat_ui.gd",
    )
    for path in candidates:
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(path.relative_to(project_root).as_posix())
    return removed


def assemble_godot_modules(
    mechanic_artifact: str | Path,
    ui_artifact: str | Path,
    output_project: str | Path,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Materialize an independently assembled Godot product project.

    ``mechanic_artifact`` is the artifact directory containing ``project/`` and
    ``mechanic_contract.json``.  ``ui_artifact`` may be the UI artifact root or
    its ``generated_ui`` directory.  The returned payload is suitable for an
    adapter operation report and includes the exact module-to-product mapping.
    """

    mechanic_root_input = Path(mechanic_artifact).expanduser()
    ui_root_input = Path(ui_artifact).expanduser()
    destination_input = Path(output_project).expanduser()
    _assert_regular_tree(mechanic_root_input, "Mechanic artifact")
    _assert_regular_tree(ui_root_input, "UI artifact")
    if destination_input.is_symlink():
        raise ValueError(
            f"Assembly destination must not be a symlink: {destination_input}"
        )
    mechanic_root = mechanic_root_input.resolve(strict=False)
    ui_root = ui_root_input.resolve(strict=False)
    destination = destination_input.resolve(strict=False)
    mechanic_project = mechanic_root / "project"
    ui_source = ui_root / "generated_ui" if (ui_root / "generated_ui").is_dir() else ui_root

    _assert_regular_tree(ui_source, "UI artifact")
    if not mechanic_project.is_dir():
        raise ValueError(f"Mechanic artifact is missing project/: {mechanic_project}")
    contract = mechanic_root / "mechanic_contract.json"
    if not contract.is_file():
        raise ValueError(f"Mechanic artifact is missing mechanic_contract.json: {contract}")
    ui_scene_source = ui_source / "CombatUI.tscn"
    ui_script_source = ui_source / "combat_ui.gd"
    if not ui_scene_source.is_file() or not ui_script_source.is_file():
        raise ValueError("UI artifact must contain CombatUI.tscn and combat_ui.gd")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Assembly destination already exists: {destination}")
    if destination.is_symlink():
        raise ValueError(f"Assembly destination must not be a symlink: {destination}")
    if destination.exists() and not destination.is_dir():
        raise ValueError(f"Assembly destination must be a directory: {destination}")

    mechanic_metadata = _read_module_metadata(
        mechanic_root,
        contract_names=("mechanic_contract.json",),
    )
    ui_metadata = _read_module_metadata(
        ui_root,
        contract_names=("ui_binding_manifest.json",),
    )
    if ui_source != ui_root:
        # Native UI metadata is commonly inside generated_ui/, while the
        # package descriptor remains at the artifact root.  Merge both so
        # the binding manifest's logical module name wins over a directory
        # basename fallback.
        source_metadata = _read_module_metadata(
            ui_source,
            contract_names=("ui_binding_manifest.json",),
        )
        for key, value in source_metadata.items():
            ui_metadata.setdefault(key, value)
    mechanic_name = _module_name(
        mechanic_metadata,
        fallback=mechanic_root.name,
        kind="mechanic",
    )
    ui_name = _module_name(ui_metadata, fallback=ui_root.name, kind="ui")
    package_dir = f"ui/{ui_name}"
    ui_scene = f"{package_dir}/CombatUI.tscn"
    ui_script = f"{package_dir}/combat_ui.gd"

    payload: dict[str, Any] = {
        "schema_version": _ASSEMBLY_SCHEMA,
        "status": "planned" if dry_run else "assembled",
        "mechanic_module": mechanic_name,
        "ui_module": ui_name,
        "mechanic_artifact": str(mechanic_root),
        "ui_artifact": str(ui_root),
        "output_project": str(destination),
        "composition_root": "scenes/Main.tscn",
        "mechanic_entry_scene": "scenes/Mechanic.tscn",
        "ui_entry_scene": ui_scene,
        "ui_entry_script": ui_script,
        "integration": "runtime_adapter_only",
        "dependency_direction": "ui -> mechanic -> runtime_framework",
    }
    if dry_run:
        return GodotOperationResult.success(
            "project.assemble_modules", payload=payload
        ).to_dict()

    destination.parent.mkdir(parents=True, exist_ok=True)
    stage_path = Path(tempfile.mkdtemp(prefix=".a3game-godot-assembly-", dir=destination.parent))
    try:
        # ``output_project`` is the Godot project directory itself.  Keep the
        # staging directory separate so copytree has a non-existent target;
        # only the inner product directory is renamed into the final path.
        product_project = stage_path / "product"
        _copy_tree(mechanic_project, product_project)
        removed_ui = _remove_accidental_ui_from_mechanic(product_project)
        ui_destination = product_project / package_dir
        ui_destination.mkdir(parents=True, exist_ok=True)
        for source in ui_source.iterdir():
            if source.name in _NATIVE_UI_EXCLUDES or source.name.startswith("."):
                continue
            target = ui_destination / source.name
            if source.is_dir():
                shutil.copytree(source, target)
            elif source.is_file():
                shutil.copy2(source, target)
        _patch_ui_resources(product_project, package_dir)
        (product_project / "scenes" / "Main.tscn").write_text(
            _composition_scene(ui_scene), encoding="utf-8"
        )
        project_file = product_project / "project.godot"
        if not project_file.is_file():
            raise ValueError(f"Mechanic project is missing project.godot: {project_file}")
        _set_main_scene(project_file, "res://scenes/Main.tscn")
        # Keep the public contract next to the assembled product so tools and
        # the UI module can resolve the same API without reaching back into an
        # artifact checkout.
        shutil.copy2(contract, product_project / "mechanic_contract.json")
        (product_project / "mechanic_module_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "gamefactory3a.godot_module_manifest.v1",
                    "module_kind": "mechanic",
                    "module_name": mechanic_name,
                    "engine": "godot",
                    "entry_scene": "scenes/Mechanic.tscn",
                    "entry_script": "scripts/main.gd",
                    "dependencies": {"runtime_framework": "A3GamePlayable"},
                    "ui_owned": False,
                    "standalone": True,
                    "public_contract": "mechanic_contract.json",
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        product_ui_manifest = ui_destination / "module_manifest.json"
        if product_ui_manifest.is_file():
            product_ui_metadata = json.loads(
                product_ui_manifest.read_text(encoding="utf-8")
            )
        else:
            product_ui_metadata = {}
        product_ui_metadata.update(
            {
                "schema_version": "gamefactory3a.godot_module_manifest.v1",
                "module_kind": "ui",
                "module_name": ui_name,
                "engine": "godot",
                "entry_scene": f"{package_dir}/CombatUI.tscn",
                "entry_script": f"{package_dir}/combat_ui.gd",
                "dependencies": {"mechanic_contract": "../../mechanic_contract.json"},
                "runtime_access": "runtime_adapter_only",
                "standalone": False,
            }
        )
        product_ui_manifest.write_text(
            json.dumps(product_ui_metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        payload["removed_accidental_mechanic_ui"] = removed_ui
        payload["product_contract"] = "mechanic_contract.json"
        payload["product_mechanic_manifest"] = "mechanic_module_manifest.json"
        payload["product_ui_manifest"] = f"{package_dir}/module_manifest.json"
        assembly_file = product_project / "assembly_manifest.json"
        assembly_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        if destination.exists():
            shutil.rmtree(destination)
        product_project.rename(destination)
    except Exception:
        shutil.rmtree(stage_path, ignore_errors=True)
        raise
    return GodotOperationResult.success(
        "project.assemble_modules", payload=payload
    ).to_dict()
