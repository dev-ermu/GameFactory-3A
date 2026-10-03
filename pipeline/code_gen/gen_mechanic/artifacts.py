"""Mechanic artifact validation and workspace finalization."""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from pipeline.code_gen.gen_mechanic.contracts import (
    validate_mechanic_contract,
)
from pipeline.common.artifacts import read_json
from pipeline.common.code_mapping import (
    resolve_engine_registration,
    validate_context_used,
)
from pipeline.common.finalize import finalize_workspace


_UE_ENGINE_IDS = {
    "ue",
    "ue5",
    "unreal",
    "unreal_engine",
    "unrealengine",
}
_UE_SOURCE_SUFFIXES = {
    ".h",
    ".hh",
    ".hpp",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".cs",
    ".ini",
    ".uplugin",
    ".uproject",
}
_UE_UI_PATTERNS = (
    ("AHUD", re.compile(r"\bAHUD\b")),
    ("DrawHUD", re.compile(r"\bDrawHUD\b")),
    ("UUserWidget", re.compile(r"\bUUserWidget\b")),
    (
        "Engine/Canvas.h",
        re.compile(r"Engine[\\/]Canvas\.h"),
    ),
    (
        "GameFramework/HUD.h",
        re.compile(r"GameFramework[\\/]HUD\.h"),
    ),
    ("HUDClass", re.compile(r"\bHUDClass\b")),
    ("Canvas", re.compile(r"\bCanvas\b")),
    ("UMG", re.compile(r"\bUMG\b")),
    ("Slate", re.compile(r"\bSlate(?:Core)?\b")),
)
_GODOT_ENGINE_IDS = {
    "godot",
    "godot4",
    "godot_engine",
}
_GODOT_SOURCE_SUFFIXES = {
    ".gd",
    ".tscn",
    ".tres",
}
_GODOT_UI_PATTERNS = (
    ("CanvasLayer", re.compile(r"\bCanvasLayer\b")),
    ("Control", re.compile(r"\bControl\b")),
    ("Container", re.compile(r"\b[A-Za-z]*Container\b")),
    ("Label", re.compile(r"\bLabel\b")),
    ("Button", re.compile(r"\b(?:BaseButton|Button|TextureButton)\b")),
    ("Panel", re.compile(r"\b(?:Panel|PanelContainer)\b")),
    ("ProgressBar", re.compile(r"\bProgressBar\b")),
    ("ColorRect", re.compile(r"\bColorRect\b")),
    ("TextureRect", re.compile(r"\bTextureRect\b")),
    ("CombatUI", re.compile(r"\bCombatUI\b|combat_ui\.gd")),
    ("res://ui/", re.compile(r"res://ui[\\/]")),
)
_GODOT_UI_PATH_PARTS = {
    "ui",
    "hud",
    "widget",
    "widgets",
    "overlay",
}
_UNITY_ENGINE_IDS = {
    "unity",
    "unity3d",
    "unity_engine",
}
_UNITY_SOURCE_SUFFIXES = {
    ".cs",
}
_UNITY_UI_PATTERNS = (
    ("Canvas", re.compile(r"\bCanvas\b")),
    ("UnityEngine.UI", re.compile(r"using\s+UnityEngine\.UI\b")),
    ("Button", re.compile(r"\bButton\b")),
    ("Text", re.compile(r"\bText\b")),
    ("Image", re.compile(r"\bImage\b")),
    ("RectTransform", re.compile(r"\bRectTransform\b")),
    ("ScrollRect", re.compile(r"\bScrollRect\b")),
    ("Toggle", re.compile(r"\bToggle\b")),
    ("Slider", re.compile(r"\bSlider\b")),
    ("TMP_Text", re.compile(r"\bTMP_Text\b")),
)
_UNITY_UI_PATH_PARTS = {
    "ui",
    "hud",
    "widget",
    "widgets",
    "overlay",
}


def _has_files(path: Path) -> bool:
    return path.is_dir() and any(
        item.is_file()
        for item in path.rglob("*")
    )


def scan_unity_ui_contamination(
    workspace: Path,
    current_task_files: Mapping[str, Mapping[str, Any]],
) -> tuple[bool, list[str]]:
    """Reject native UI implementation accidentally put in a Unity Mechanic."""
    violations: list[str] = []
    for relative_path in current_task_files:
        normalized = PurePosixPath(str(relative_path).replace("\\", "/"))
        path = workspace.joinpath(*normalized.parts)
        if (
            not path.is_file()
            or path.suffix.lower() not in _UNITY_SOURCE_SUFFIXES
        ):
            continue
        # A generated test may mention UI types while asserting that UI is
        # absent; only inspect implementation files here.
        if any("test" in part.lower() for part in normalized.parts):
            continue
        if {
            part.lower() for part in normalized.parts[:-1]
        } & _UNITY_UI_PATH_PARTS:
            violations.append(
                "Unity Mechanic source is under a UI-owned path in "
                f"{relative_path}"
            )
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            violations.append(
                "Unable to inspect generated Unity Mechanic source "
                f"{relative_path}: {exc}"
            )
            continue
        matches = [
            name
            for name, pattern in _UNITY_UI_PATTERNS
            if pattern.search(source)
        ]
        if matches:
            violations.append(
                "Unity Mechanic source contains forbidden UI "
                f"implementation in {relative_path}: "
                + ", ".join(matches)
            )
    return not violations, violations


def scan_ue_ui_contamination(
    workspace: Path,
    current_task_files: Mapping[str, Mapping[str, Any]],
) -> tuple[bool, list[str]]:
    violations: list[str] = []
    for relative_path in current_task_files:
        path = workspace / relative_path
        if (
            not path.is_file()
            or path.suffix.lower() not in _UE_SOURCE_SUFFIXES
        ):
            continue
        try:
            source = path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except OSError as exc:
            violations.append(
                "Unable to inspect generated Mechanic source "
                f"{relative_path}: {exc}"
            )
            continue
        matches = [
            name
            for name, pattern in _UE_UI_PATTERNS
            if pattern.search(source)
        ]
        if matches:
            violations.append(
                "UE Mechanic source contains forbidden UI "
                f"implementation in {relative_path}: "
                + ", ".join(matches)
            )
    return not violations, violations


def scan_godot_ui_contamination(
    workspace: Path,
    current_task_files: Mapping[str, Mapping[str, Any]],
) -> tuple[bool, list[str]]:
    """Reject native UI implementation accidentally put in a Godot Mechanic."""
    violations: list[str] = []
    for relative_path in current_task_files:
        normalized = PurePosixPath(str(relative_path).replace("\\", "/"))
        path = workspace.joinpath(*normalized.parts)
        if (
            not path.is_file()
            or path.suffix.lower() not in _GODOT_SOURCE_SUFFIXES
        ):
            continue
        # A generated test may mention UI types while asserting that UI is
        # absent; only inspect implementation files here.
        if any("test" in part.lower() for part in normalized.parts):
            continue
        if {
            part.lower() for part in normalized.parts[:-1]
        } & _GODOT_UI_PATH_PARTS:
            violations.append(
                "Godot Mechanic source is under a UI-owned path in "
                f"{relative_path}"
            )
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            violations.append(
                "Unable to inspect generated Godot Mechanic source "
                f"{relative_path}: {exc}"
            )
            continue
        matches = [
            name
            for name, pattern in _GODOT_UI_PATTERNS
            if pattern.search(source)
        ]
        if matches:
            violations.append(
                "Godot Mechanic source contains forbidden UI "
                f"implementation in {relative_path}: "
                + ", ".join(matches)
            )
    return not violations, violations


def required_artifact_checks(
    workspace: Path,
    required: Sequence[str],
    current_task_files: Mapping[str, Mapping[str, Any]],
    *,
    engine: str,
    gameplay_module_name: str,
    mechanic_example_roots: Sequence[Path],
    allowed_example_purposes: Sequence[str],
    require_example_purpose: bool,
    provenance_digests: Mapping[
        str,
        Mapping[str, Any],
    ],
) -> tuple[dict[str, bool | None], list[str], list[str]]:
    checks: dict[str, bool | None] = {}
    errors: list[str] = []
    warnings: list[str] = []
    for artifact in required:
        if artifact == "project_file":
            checks[artifact] = _has_files(
                workspace / "project"
            )
        elif artifact == "plugin_dir":
            checks[artifact] = _has_files(
                workspace / "generated_plugin"
            )
        elif artifact == "launch_script":
            checks[artifact] = any(
                path.is_file()
                for path in workspace.glob("launch*")
            )
        elif artifact == "demo_outputs_dir":
            checks[artifact] = (
                workspace / "demo_outputs"
            ).is_dir()
        else:
            checks[artifact] = None
            warnings.append(
                "Finalize has no engine-neutral check for "
                f"required artifact {artifact!r}"
            )
    for artifact, passed in checks.items():
        if passed is False:
            errors.append(
                f"Required Mechanic artifact is missing: {artifact}"
            )

    generated_tests = [
        relative_path
        for relative_path in current_task_files
        if any(
            "test" in part.lower()
            for part in PurePosixPath(relative_path).parts
        )
    ]
    checks["generated_test_source"] = bool(generated_tests)
    if not generated_tests:
        errors.append(
            "No generated Mechanic test source was found"
        )

    contract_ok, contract_errors = (
        validate_mechanic_contract(
            workspace,
            gameplay_module_name,
        )
    )
    checks["mechanic_contract"] = contract_ok
    errors.extend(contract_errors)

    try:
        registration = resolve_engine_registration(
            engine
        )
        context_ok, context_errors = (
            validate_context_used(
                workspace / "context_used.json",
                engine=engine,
                context_expectations=[
                    {
                        "stage": "mechanic",
                        "role": "engine_api",
                        "path": registration[
                            "primary_api"
                        ],
                    }
                ],
                example_expectations={},
                example_roots={
                    "mechanic_example": (
                        mechanic_example_roots
                    ),
                },
                required_example_roles=(
                    "mechanic_example",
                ),
                allowed_example_purposes=(
                    allowed_example_purposes
                ),
                require_example_purpose=(
                    require_example_purpose
                ),
                expected_digests=provenance_digests,
            )
        )
    except (
        FileNotFoundError,
        TypeError,
        ValueError,
    ) as exc:
        context_ok = False
        context_errors = [str(exc)]
    checks["context_used"] = context_ok
    errors.extend(context_errors)

    if engine.strip().lower() in _UE_ENGINE_IDS:
        ui_free, contamination_errors = (
            scan_ue_ui_contamination(
                workspace,
                current_task_files,
            )
        )
        checks["ue_ui_free_source"] = ui_free
        errors.extend(contamination_errors)
    else:
        checks["ue_ui_free_source"] = None
    if engine.strip().lower() in _GODOT_ENGINE_IDS:
        ui_free, contamination_errors = scan_godot_ui_contamination(
            workspace,
            current_task_files,
        )
        checks["godot_ui_free_source"] = ui_free
        errors.extend(contamination_errors)
    else:
        checks["godot_ui_free_source"] = None
    if engine.strip().lower() in _UNITY_ENGINE_IDS:
        ui_free, contamination_errors = scan_unity_ui_contamination(
            workspace,
            current_task_files,
        )
        checks["unity_ui_free_source"] = ui_free
        errors.extend(contamination_errors)
    else:
        checks["unity_ui_free_source"] = None
    return checks, errors, warnings


def finalize(
    packet_path: str | Path,
    *,
    summary: str = "",
) -> dict[str, Any]:
    """Finalize one directly edited Mechanic workspace."""
    packet = read_json(
        packet_path,
        "Prepared Mechanic task packet",
    )
    engine = str(packet.get("engine") or "")
    gameplay_module_name = str(
        packet.get("gameplay_module_name") or ""
    )
    context = packet.get("context")
    if not isinstance(context, Mapping):
        raise TypeError(
            "Prepared Mechanic packet context must be an object"
        )
    raw_example_roots = context.get(
        "mechanic_example_roots"
    )
    if (
        isinstance(raw_example_roots, (str, bytes))
        or not isinstance(raw_example_roots, Sequence)
    ):
        raise TypeError(
            "Prepared Mechanic packet mechanic_example_roots "
            "must be a sequence"
        )
    raw_digests = context.get("provenance_digests")
    if not isinstance(raw_digests, Mapping):
        raise TypeError(
            "Prepared Mechanic packet provenance_digests "
            "must be an object"
        )
    usage_contract = packet.get("context_usage_contract")
    if not isinstance(usage_contract, Mapping):
        raise TypeError(
            "Prepared Mechanic packet context_usage_contract "
            "must be an object"
        )
    raw_purposes = usage_contract.get(
        "allowed_example_purposes",
        [],
    )
    if (
        isinstance(raw_purposes, (str, bytes))
        or not isinstance(raw_purposes, Sequence)
    ):
        raise TypeError(
            "Prepared Mechanic packet allowed_example_purposes "
            "must be a sequence"
        )
    def artifact_checker(
        workspace: Path,
        required: Sequence[str],
        current_task_files: Mapping[str, Mapping[str, Any]],
    ) -> tuple[
        dict[str, bool | None],
        list[str],
        list[str],
    ]:
        return required_artifact_checks(
            workspace,
            required,
            current_task_files,
            engine=engine,
            gameplay_module_name=gameplay_module_name,
            mechanic_example_roots=[
                Path(str(path)).expanduser().resolve(
                    strict=False
                )
                for path in raw_example_roots
            ],
            allowed_example_purposes=[
                str(purpose)
                for purpose in raw_purposes
            ],
            require_example_purpose=bool(
                usage_contract.get(
                    "example_purpose_required",
                    False,
                )
            ),
            provenance_digests={
                str(path): dict(value)
                for path, value in raw_digests.items()
                if isinstance(value, Mapping)
            },
        )

    return finalize_workspace(
        packet_path,
        summary=summary,
        artifact_checker=artifact_checker,
    )
