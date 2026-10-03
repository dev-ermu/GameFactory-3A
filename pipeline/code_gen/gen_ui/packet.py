"""Prepare deterministic outer-Agent UI task packets."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pipeline.code_gen.gen_ui.contracts import (
    MECHANIC_CONTRACT_FILENAME,
    MECHANIC_FIXTURE_SCHEMA,
    SCREENSHOT_PLAN_SCHEMA,
    UI_BINDING_MANIFEST_SCHEMA,
    file_digest,
    load_mechanic_contract,
    resolved_binding_definitions,
)
from pipeline.common import paths
from pipeline.common.artifacts import (
    identifier,
    is_relative_to,
    json_text,
    read_json,
    read_required_text,
    render_template,
    resolve_repo_path,
)
from pipeline.common.code_mapping import (
    CONTEXT_USED_SCHEMA,
    EXAMPLE_REFERENCE_PURPOSES,
    provenance_digests,
    repair_payload,
    resolve_browser_play_registration,
    resolve_engine_example_paths,
    resolve_engine_example_roots,
    resolve_engine_registration,
    string_list,
    validate_boundaries,
)
from pipeline.common.prepare import (
    DEFAULT_RESERVED_ROOTS,
    code_gen_stage_dir,
    prepare_workspace,
    resolve_task_workspace,
)


TASK_KIND = "ui"
CONTEXT_ROOT = (
    paths.REPO_ROOT
    / "agent_skills"
    / "code_gen"
    / "ui"
)
SKILL_PATH = CONTEXT_ROOT / "game_ui_generation.md"
PROMPTS_ROOT = CONTEXT_ROOT / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_ROOT / "system.md"
TASK_PROMPT_PATH = PROMPTS_ROOT / "task.md"
REPAIR_PROMPT_PATH = PROMPTS_ROOT / "repair.md"
ENGINE_NATIVE_DELIVERY_MODE = "engine_native"
BROWSER_PLAY_DELIVERY_MODE = "browser_play"
FULL_UI_DELIVERY_MODE = (
    "engine_native_then_browser_play"
)
DEFAULT_REQUIRED_ARTIFACTS = (
    "ui_source",
    "ui_tests",
    "ui_binding_manifest",
    "mechanic_contract_fixture",
    "context_used",
    "browser_play_source",
    "browser_play_tests",
    "browser_play_handoff",
    "screenshot_plan",
)
_REFERENCE_IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
}


def delivery_mode(ui_target: str) -> str:
    normalized = (
        str(ui_target or "")
        .strip()
        .lower()
        .replace("-", "_")
    )
    if not normalized:
        raise ValueError("UI task must contain ui_target")
    first_token = normalized.split("_", 1)[0]
    if first_token in {"browser", "web"}:
        raise ValueError(
            "browser/web ui_target is not a standalone Generate-UI "
            "mode. Declare the engine runtime target; Browser Play is "
            "generated automatically after the engine-native UI."
        )
    if (
        normalized in {
            "engine_native",
            "engine_runtime",
            "native_runtime",
        }
        or normalized.endswith("_runtime")
    ):
        return FULL_UI_DELIVERY_MODE
    raise ValueError(
        "Unsupported ui_target. Use an engine runtime target; "
        "Browser Play is appended automatically."
    )


def _design_document(
    task: Mapping[str, Any],
    game_id: str,
) -> tuple[Path, str]:
    explicit = str(
        task.get("design_doc_path") or ""
    ).strip()
    path = (
        resolve_repo_path(
            explicit,
            "design_doc_path",
            require_file=True,
        )
        if explicit
        else (
            paths.TEST_SAMPLES_ROOT
            / game_id
            / "pipeline"
            / "design_doc.txt"
        ).resolve(strict=False)
    )
    return path, read_required_text(
        path,
        "Game design document",
    )


def viewport_list(
    value: Any,
) -> list[dict[str, int]]:
    if isinstance(value, (str, bytes)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError("viewports must be a sequence")
    result: list[dict[str, int]] = []
    seen: set[tuple[int, int]] = set()
    for index, item in enumerate(value):
        if isinstance(item, Mapping):
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
        elif (
            isinstance(item, Sequence)
            and not isinstance(item, (str, bytes))
            and len(item) == 2
        ):
            width = int(item[0])
            height = int(item[1])
        else:
            raise TypeError(
                f"viewports[{index}] must be an object "
                "or [width, height]"
            )
        if width <= 0 or height <= 0:
            raise ValueError(
                f"viewports[{index}] dimensions must be positive"
            )
        key = (width, height)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "width": width,
                "height": height,
            }
        )
    if not result:
        raise ValueError(
            "UI task must declare non-empty viewports"
        )
    return result


def screen_names(value: Any) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError("screens must be a sequence")
    names: list[str] = []
    for index, item in enumerate(value):
        if isinstance(item, Mapping):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if not name:
            raise ValueError(
                f"screens[{index}] must declare a non-empty name"
            )
        if name not in names:
            names.append(name)
    return names


def resolve_mechanic_artifact(
    task: Mapping[str, Any],
    *,
    fallback_game_id: str,
) -> tuple[Path, dict[str, Any], dict[str, str]]:
    explicit = str(
        task.get("mechanic_artifact_path") or ""
    ).strip()
    descriptor: dict[str, str]
    if explicit:
        root = resolve_repo_path(
            explicit,
            "mechanic_artifact_path",
            must_exist=True,
        )
        descriptor = {
            "game_id": "",
            "run_id": "",
            "task_kind": "mechanic",
            "task_id": root.name,
        }
    else:
        raw_descriptor = task.get("mechanic_task")
        if not isinstance(raw_descriptor, Mapping):
            raise TypeError(
                "UI task must contain mechanic_task or "
                "mechanic_artifact_path"
            )
        mechanic_task = dict(raw_descriptor)
        task_kind = str(
            mechanic_task.get("task_kind")
            or "mechanic"
        ).strip()
        if task_kind != "mechanic":
            raise ValueError(
                "mechanic_task.task_kind must be mechanic"
            )
        mechanic_game_id = str(
            mechanic_task.get("game_id")
            or fallback_game_id
        ).strip()
        mechanic_run_id = str(
            mechanic_task.get("run_id") or ""
        ).strip()
        mechanic_task_id = str(
            mechanic_task.get("task_id") or ""
        ).strip()
        if not mechanic_run_id or not mechanic_task_id:
            raise ValueError(
                "mechanic_task must contain run_id and task_id"
            )
        root = paths.task_output_dir(
            mechanic_game_id,
            "mechanic",
            mechanic_task_id,
            run_id=mechanic_run_id,
            create=False,
        ).resolve(strict=False)
        descriptor = {
            "game_id": mechanic_game_id,
            "run_id": mechanic_run_id,
            "task_kind": task_kind,
            "task_id": mechanic_task_id,
        }
    if not root.is_dir():
        raise FileNotFoundError(
            f"Mechanic artifact was not found: {root}"
        )
    meta = read_json(
        root / "meta.json",
        "Mechanic artifact metadata",
    )
    if meta.get("status") != "completed":
        raise ValueError(
            "Mechanic artifact must be finalized before UI generation"
        )
    if meta.get("ok") is False:
        raise ValueError(
            "Mechanic artifact reports a failed result"
        )
    return root, meta, descriptor


def mechanic_contract_path(
    task: Mapping[str, Any],
    mechanic_root: Path,
) -> Path:
    explicit = str(
        task.get("mechanic_contract_path") or ""
    ).strip()
    required_path = (
        mechanic_root / MECHANIC_CONTRACT_FILENAME
    ).resolve(strict=False)
    if explicit:
        path = resolve_repo_path(
            explicit,
            "mechanic_contract_path",
            require_file=True,
        )
        if not is_relative_to(path, mechanic_root):
            raise ValueError(
                "mechanic_contract_path must be inside the "
                "Mechanic artifact"
            )
        if path != required_path:
            raise ValueError(
                "mechanic_contract_path must point to the "
                "Mechanic artifact root "
                f"{MECHANIC_CONTRACT_FILENAME}"
            )
    if not required_path.is_file():
        raise FileNotFoundError(
            "Finalized Mechanic artifact is missing the "
            f"mandatory {MECHANIC_CONTRACT_FILENAME}: "
            f"{required_path}"
        )
    return required_path


def mechanic_public_paths(
    mechanic_root: Path,
    contract: Mapping[str, Any],
) -> list[Path]:
    result: set[Path] = set()
    for relative_path in string_list(
        contract.get("public_api_paths", []),
        "mechanic_contract.public_api_paths",
    ):
        path = (
            mechanic_root / relative_path
        ).resolve(strict=False)
        if (
            not is_relative_to(path, mechanic_root)
            or not path.is_file()
        ):
            raise ValueError(
                "Mechanic contract public_api_paths "
                f"entry is invalid: {relative_path}"
            )
        result.add(path)
    if not result:
        raise ValueError(
            "Mechanic contract must expose at least one "
            "public runtime-adapter path"
        )
    return sorted(result)


def optional_reference_context(
    task: Mapping[str, Any],
) -> tuple[Path | None, list[Path]]:
    raw = str(
        task.get("reference_image_dir") or ""
    ).strip()
    if not raw:
        return None, []
    path = resolve_repo_path(
        raw,
        "reference_image_dir",
        must_exist=True,
    )
    if not path.is_dir():
        raise ValueError(
            f"reference_image_dir must be a directory: {path}"
        )
    images = [
        item.resolve(strict=False)
        for item in sorted(path.rglob("*"))
        if (
            item.is_file()
            and item.suffix.lower()
            in _REFERENCE_IMAGE_SUFFIXES
        )
    ]
    return path, images


def prepare(
    inp: dict[str, Any],
    *,
    run_id: str = paths.DEFAULT_RUN_ID,
    output_dir: str | None = None,
    default_game_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Compose one UI packet without loading a Model or Operator."""
    if not isinstance(inp, Mapping):
        raise TypeError("UI task must be an object")
    task = dict(inp)
    mode = str(
        task.get("mode") or "generate"
    ).strip().lower()
    if mode not in {"generate", "repair"}:
        raise ValueError(
            "UI task mode must be generate or repair"
        )
    repair, repair_attempt = repair_payload(
        task,
        mode,
    )
    task_id = str(
        task.get("task_id") or ""
    ).strip()
    if not task_id:
        raise ValueError(
            "UI task must contain task_id"
        )
    requested_engine = str(
        task.get("engine") or ""
    ).strip()
    if not requested_engine:
        raise ValueError(
            "UI task must contain engine"
        )
    registration = resolve_engine_registration(
        requested_engine
    )
    engine = str(registration["engine_id"])
    engine_context_root = Path(
        registration["context_root"]
    )
    mechanic_examples = resolve_engine_example_paths(
        task,
        registration,
        "mechanic_example",
    )
    mechanic_example_roots = resolve_engine_example_roots(
        registration,
        "mechanic_example",
    )
    ui_examples = resolve_engine_example_paths(
        task,
        registration,
        "ui_example",
    )
    ui_example_roots = resolve_engine_example_roots(
        registration,
        "ui_example",
    )
    browser_play_examples = resolve_engine_example_paths(
        task,
        registration,
        "browser_play_example",
    )
    browser_play = (
        resolve_browser_play_registration(engine)
    )
    ui_target = str(
        task.get("ui_target")
        or "engine_runtime"
    ).strip()
    resolved_delivery_mode = delivery_mode(
        ui_target
    )

    game_id, workspace, standard_layout = (
        resolve_task_workspace(
            task,
            task_kind=TASK_KIND,
            task_id=task_id,
            run_id=run_id,
            output_dir=output_dir,
            default_game_id=default_game_id,
        )
    )
    mechanic_root, mechanic_meta, mechanic_descriptor = (
        resolve_mechanic_artifact(
            task,
            fallback_game_id=game_id,
        )
    )
    mechanic_engine = str(
        mechanic_meta.get("engine") or ""
    ).strip()
    if not mechanic_engine:
        raise ValueError(
            "Finalized Mechanic metadata is missing engine"
        )
    mechanic_registration = resolve_engine_registration(
        mechanic_engine
    )
    canonical_mechanic_engine = str(
        mechanic_registration["engine_id"]
    )
    if canonical_mechanic_engine != engine:
        raise ValueError(
            "UI task engine does not match the Mechanic artifact: "
            f"{engine!r} != {canonical_mechanic_engine!r}"
        )
    mechanic_module_name = str(
        mechanic_meta.get(
            "gameplay_module_name"
        )
        or ""
    ).strip()
    if not mechanic_module_name:
        raise ValueError(
            "Finalized Mechanic metadata is missing "
            "gameplay_module_name"
        )
    requested_mechanic_module = str(
        task.get("gameplay_module_name") or ""
    ).strip()
    if (
        requested_mechanic_module
        and requested_mechanic_module
        != mechanic_module_name
    ):
        raise ValueError(
            "UI task gameplay_module_name does not match "
            "the finalized Mechanic artifact"
        )
    project_name = identifier(
        task.get("project_name")
        or mechanic_meta.get("project_name")
        or f"A3Game_{task_id}",
        "A3Game",
    )
    gameplay_module_name = identifier(
        mechanic_module_name,
        "GeneratedGameplay",
    )
    ui_module_name = identifier(
        task.get("ui_module_name")
        or f"{gameplay_module_name}UI",
        "GeneratedUI",
    )
    requirement_path = resolve_repo_path(
        str(
            task.get("requirement_path") or ""
        ),
        "requirement_path",
        require_file=True,
    )
    requirement = read_required_text(
        requirement_path,
        "UI requirement",
    )
    general_requirement_path = (
        paths.TEST_SAMPLES_ROOT
        / game_id
        / "general_requirement.txt"
    ).resolve(strict=False)
    general_requirement = (
        general_requirement_path.read_text(
            encoding="utf-8"
        )
        if general_requirement_path.is_file()
        else ""
    )
    design_document_path, design_document = (
        _design_document(task, game_id)
    )
    screens = screen_names(task.get("screens", []))
    if not screens:
        raise ValueError(
            "UI task must declare non-empty screens"
        )
    acceptance_criteria = string_list(
        task.get("acceptance_criteria", []),
        "acceptance_criteria",
    )
    forbidden_ui = string_list(
        task.get("forbidden_ui", []),
        "forbidden_ui",
    )
    raw_constraints = task.get(
        "view_constraints",
        {},
    )
    if not isinstance(raw_constraints, Mapping):
        raise TypeError(
            "view_constraints must be an object"
        )
    view_constraints = dict(raw_constraints)
    viewports = viewport_list(
        task.get("viewports", [])
    )
    contract_path = mechanic_contract_path(
        task,
        mechanic_root,
    )
    mechanic_contract, contract_entries = (
        load_mechanic_contract(
            contract_path,
            mechanic_module_name,
        )
    )
    bindings, resolved_bindings = (
        resolved_binding_definitions(
            task,
            contract_entries,
            require_state=True,
        )
    )
    public_paths = mechanic_public_paths(
        mechanic_root,
        mechanic_contract,
    )
    runtime_adapter = {
        "access": "public_contract_query",
        "gameplay_module": (
            gameplay_module_name
        ),
        "public_paths": [
            str(path)
            for path in public_paths
        ],
        "direct_gameplay_access": False,
    }
    empty_bindings = {
        "state": [],
        "events": [],
        "commands": [],
    }
    delivery_plan = [
        {
            "order": 1,
            "stage": ENGINE_NATIVE_DELIVERY_MODE,
            "engine_context_root": str(
                engine_context_root
            ),
            "output_root": "generated_ui",
            "mechanic_example_roots": [
                str(path)
                for path in mechanic_example_roots
            ],
            "mechanic_example_paths": [
                str(path)
                for path in mechanic_examples
            ],
            "ui_example_roots": [
                str(path)
                for path in ui_example_roots
            ],
            "ui_example_paths": [
                str(path)
                for path in ui_examples
            ],
            "mechanic_bindings": bindings,
            "mechanic_runtime_adapter": (
                runtime_adapter
            ),
            "mechanic_public_paths": [
                str(path)
                for path in public_paths
            ],
        },
        {
            "order": 2,
            "stage": BROWSER_PLAY_DELIVERY_MODE,
            "depends_on": [
                ENGINE_NATIVE_DELIVERY_MODE,
            ],
            "engine_context_root": str(
                engine_context_root
            ),
            "owner": "outer_agent",
            "output_root": "generated_ui/browser_play",
            "browser_play": browser_play,
            "browser_play_example_paths": [
                str(path)
                for path in browser_play_examples
            ],
            "mechanic_bindings": empty_bindings,
            "mechanic_runtime_adapter": None,
            "mechanic_public_paths": [],
        },
    ]
    reference_dir, reference_images = (
        optional_reference_context(task)
    )
    mechanic_contract_digest = file_digest(
        contract_path
    )

    system_prompt = read_required_text(
        SYSTEM_PROMPT_PATH,
        "UI system Prompt",
    )
    task_template = read_required_text(
        TASK_PROMPT_PATH,
        "UI task Prompt",
    )
    repair_template = read_required_text(
        REPAIR_PROMPT_PATH,
        "UI repair Prompt",
    )
    read_required_text(
        SKILL_PATH,
        "Game UI Generation Skill",
    )

    stage_dir = code_gen_stage_dir(
        workspace,
        mode=mode,
        repair_attempt=repair_attempt,
    )
    packet_path = stage_dir / "task_packet.json"
    agent_task = dict(task)
    for repeated_key in (
        "acceptance_criteria",
        "state_bindings",
        "event_bindings",
        "command_bindings",
        "screens",
        "view_constraints",
        "viewports",
        "forbidden_ui",
        "example_paths",
        "examples",
        "mechanic_example_paths",
        "ui_example_paths",
        "browser_play_example_paths",
        "mode",
        "repair",
    ):
        agent_task.pop(repeated_key, None)
    task_prompt = render_template(
        task_template,
        {
            "WORKSPACE": str(workspace),
            "PROJECT_NAME": project_name,
            "GAMEPLAY_MODULE_NAME": (
                gameplay_module_name
            ),
            "UI_MODULE_NAME": ui_module_name,
            "UI_TARGET": ui_target,
            "DELIVERY_MODE": (
                resolved_delivery_mode
            ),
            "UI_GENERATION_SKILL_PATH": str(
                SKILL_PATH
            ),
            "TASK_PACKET_PATH": str(packet_path),
            "TASK_JSON": json_text(agent_task),
            "GENERAL_REQUIREMENT": (
                general_requirement
            ),
            "DESIGN_DOCUMENT": design_document,
            "REQUIREMENT": requirement,
            "ACCEPTANCE_CRITERIA": json_text(
                acceptance_criteria
            ),
            "ENGINE": engine,
            "DELIVERY_PLAN": json_text(
                delivery_plan
            ),
            "ENGINE_CONTEXT_ROOT": str(
                engine_context_root
            ),
            "MECHANIC_EXAMPLE_PATHS": json_text(
                [
                    str(path)
                    for path in mechanic_examples
                ]
            ),
            "MECHANIC_EXAMPLE_ROOTS": json_text(
                [
                    str(path)
                    for path in mechanic_example_roots
                ]
            ),
            "UI_EXAMPLE_PATHS": json_text(
                [
                    str(path)
                    for path in ui_examples
                ]
            ),
            "UI_EXAMPLE_ROOTS": json_text(
                [
                    str(path)
                    for path in ui_example_roots
                ]
            ),
            "BROWSER_PLAY_EXAMPLE_PATHS": json_text(
                [
                    str(path)
                    for path in browser_play_examples
                ]
            ),
            "EXAMPLE_REFERENCE_PURPOSES": json_text(
                list(EXAMPLE_REFERENCE_PURPOSES)
            ),
            "BROWSER_PLAY_HANDOFF": json_text(
                browser_play
            ),
            "MECHANIC_ARTIFACT_PATH": str(
                mechanic_root
            ),
            "MECHANIC_META_JSON": json_text(
                mechanic_meta
            ),
            "MECHANIC_CONTRACT_PATH": str(
                contract_path
            ),
            "MECHANIC_CONTRACT_JSON": json_text(
                mechanic_contract
            ),
            "MECHANIC_PUBLIC_PATHS": json_text(
                [
                    str(path)
                    for path in public_paths
                ]
            ),
            "MECHANIC_RUNTIME_ADAPTER": (
                json_text(runtime_adapter)
            ),
            "STATE_BINDINGS": json_text(
                bindings["state"]
            ),
            "EVENT_BINDINGS": json_text(
                bindings["events"]
            ),
            "COMMAND_BINDINGS": json_text(
                bindings["commands"]
            ),
            "RESOLVED_BINDINGS": json_text(
                resolved_bindings
            ),
            "SCREENS": json_text(screens),
            "VIEW_CONSTRAINTS": json_text(
                view_constraints
            ),
            "VIEWPORTS": json_text(viewports),
            "FORBIDDEN_UI": json_text(
                forbidden_ui
            ),
            "REFERENCE_IMAGE_DIR": (
                str(reference_dir)
                if reference_dir is not None
                else "none"
            ),
            "REFERENCE_IMAGE_PATHS": json_text(
                [
                    str(path)
                    for path in reference_images
                ]
            ),
            "CONTEXT_USED_PATH": str(
                workspace
                / "generated_ui"
                / "context_used.json"
            ),
        },
    )
    repair_prompt = ""
    if mode == "repair":
        repair_prompt = render_template(
            repair_template,
            {
                "WORKSPACE": str(workspace),
                "REPAIR_ATTEMPT": str(
                    repair["attempt"]
                ),
                "MAX_REPAIR_ATTEMPTS": str(
                    repair["max_attempts"]
                ),
                "FAILURES_JSON": json_text(
                    repair["failures"]
                ),
                "PREVIOUS_RESULT_JSON": json_text(
                    repair["previous_result"]
                ),
            },
        )

    read_only_paths = [
        SKILL_PATH,
        SYSTEM_PROMPT_PATH,
        TASK_PROMPT_PATH,
        REPAIR_PROMPT_PATH,
        engine_context_root,
        requirement_path,
        design_document_path,
        mechanic_root,
        Path(browser_play["frontend_root"]),
        *mechanic_example_roots,
        *ui_example_roots,
        *browser_play_examples,
    ]
    if general_requirement_path.is_file():
        read_only_paths.append(
            general_requirement_path
        )
    if reference_dir is not None:
        read_only_paths.append(reference_dir)
    validate_boundaries(
        workspace,
        read_only_paths,
    )

    requested_output_artifacts = string_list(
        task.get(
            "required_output_artifacts",
            DEFAULT_REQUIRED_ARTIFACTS,
        ),
        "required_output_artifacts",
    )
    required_output_artifacts = list(
        dict.fromkeys(
            [
                *requested_output_artifacts,
                *DEFAULT_REQUIRED_ARTIFACTS,
            ]
        )
    )
    packet_id = (
        f"{game_id}:{run_id}:{task_id}:"
        f"{mode}:{repair_attempt}"
    )
    provenance_paths = [
        engine_context_root,
        *mechanic_example_roots,
        *ui_example_roots,
        *browser_play_examples,
    ]
    packet = {
        "packet_id": packet_id,
        "generation_owner": "outer_agent",
        "game_id": game_id,
        "run_id": run_id,
        "task_kind": TASK_KIND,
        "task_id": task_id,
        "mode": mode,
        "repair_attempt": repair_attempt,
        "engine": engine,
        "delivery_mode": resolved_delivery_mode,
        "delivery_plan": delivery_plan,
        "project_name": project_name,
        "gameplay_module_name": (
            gameplay_module_name
        ),
        "ui_module_name": ui_module_name,
        "ui_target": ui_target,
        "identity": {
            "ui_module_name": ui_module_name,
            "ui_target": ui_target,
            "delivery_mode": (
                resolved_delivery_mode
            ),
            "mechanic_task_id": (
                mechanic_descriptor["task_id"]
            ),
            "mechanic_run_id": (
                mechanic_descriptor["run_id"]
            ),
        },
        "task": agent_task,
        "context": {
            "general_requirement": (
                general_requirement
            ),
            "general_requirement_path": (
                str(general_requirement_path)
                if general_requirement_path.is_file()
                else ""
            ),
            "design_document": design_document,
            "design_document_path": str(
                design_document_path
            ),
            "requirement": requirement,
            "requirement_path": str(
                requirement_path
            ),
            "acceptance_criteria": (
                acceptance_criteria
            ),
            "delivery_mode": (
                resolved_delivery_mode
            ),
            "delivery_plan": delivery_plan,
            "engine_context_root": str(
                engine_context_root
            ),
            "skill_path": str(SKILL_PATH),
            "prompt_template_paths": {
                "system": str(
                    SYSTEM_PROMPT_PATH
                ),
                "task": str(TASK_PROMPT_PATH),
                "repair": str(
                    REPAIR_PROMPT_PATH
                ),
            },
            "mechanic_artifact_path": str(
                mechanic_root
            ),
            "mechanic_task": (
                mechanic_descriptor
            ),
            "mechanic_meta": mechanic_meta,
            "mechanic_contract_path": str(
                contract_path
            ),
            "mechanic_contract": (
                mechanic_contract
            ),
            "mechanic_contract_digest": (
                mechanic_contract_digest
            ),
            "mechanic_public_paths": [
                str(path)
                for path in public_paths
            ],
            "mechanic_runtime_adapter": (
                runtime_adapter
            ),
            "bindings": bindings,
            "resolved_bindings": (
                resolved_bindings
            ),
            "screens": screens,
            "view_constraints": (
                view_constraints
            ),
            "viewports": viewports,
            "forbidden_ui": forbidden_ui,
            "reference_image_dir": (
                str(reference_dir)
                if reference_dir is not None
                else ""
            ),
            "reference_image_paths": [
                str(path)
                for path in reference_images
            ],
            "mechanic_example_roots": [
                str(path)
                for path in mechanic_example_roots
            ],
            "mechanic_example_paths": [
                str(path)
                for path in mechanic_examples
            ],
            "ui_example_roots": [
                str(path)
                for path in ui_example_roots
            ],
            "ui_example_paths": [
                str(path)
                for path in ui_examples
            ],
            "browser_play_example_paths": [
                str(path)
                for path in browser_play_examples
            ],
            "browser_play": browser_play,
            "browser_backend": browser_play["backend"],
            "provenance_digests": (
                provenance_digests(
                    provenance_paths
                )
            ),
        },
        "instructions": {
            "system_prompt": system_prompt,
            "task_prompt": task_prompt,
            "repair_prompt": repair_prompt,
        },
        "boundaries": {
            "allowed_write_root": str(workspace),
            "reserved_paths": list(
                DEFAULT_RESERVED_ROOTS
            ),
            "read_only_paths": [
                str(path)
                for path in read_only_paths
            ],
            "agent_may_execute_tests": False,
            "agent_may_capture_screenshots": False,
            "agent_may_declare_benchmark_success": False,
            "agent_may_modify_mechanic": False,
            "agent_may_reimplement_gameplay": False,
            "agent_may_bind_mechanic": True,
            "agent_may_inspect_mechanic_public_paths": True,
            "agent_may_use_browser_serving_api": True,
            "allowed_task_output_roots": [
                "generated_ui",
            ],
            "stage_boundaries": {
                ENGINE_NATIVE_DELIVERY_MODE: {
                    "may_bind_mechanic": True,
                    "may_inspect_mechanic_public_paths": True,
                    "output_root": "generated_ui",
                },
                BROWSER_PLAY_DELIVERY_MODE: {
                    "owner": "outer_agent",
                    "may_bind_mechanic": False,
                    "may_inspect_mechanic_public_paths": False,
                    "browser_play": browser_play,
                    "output_root": (
                        "generated_ui/browser_play"
                    ),
                    "agent_may_generate_frontend": True,
                },
            },
        },
        "mechanic_contract": {
            "path": str(contract_path),
            "schema_version": (
                mechanic_contract[
                    "schema_version"
                ]
            ),
            "contract_version": (
                mechanic_contract[
                    "contract_version"
                ]
            ),
            "gameplay_module": (
                mechanic_contract[
                    "gameplay_module"
                ]
            ),
            "sha256": (
                mechanic_contract_digest[
                    "sha256"
                ]
            ),
            "bindings": bindings,
            "runtime_adapter": runtime_adapter,
        },
        "ui_output_contract": {
            "root": "generated_ui",
            "delivery_mode": (
                resolved_delivery_mode
            ),
            "engine_native_root": "generated_ui",
            "browser_play_root": (
                "generated_ui/browser_play"
            ),
            "binding_manifest_schema": (
                UI_BINDING_MANIFEST_SCHEMA
            ),
            "mechanic_fixture_schema": (
                MECHANIC_FIXTURE_SCHEMA
            ),
            "screenshot_plan_schema": (
                SCREENSHOT_PLAN_SCHEMA
            ),
            "context_used_schema": (
                CONTEXT_USED_SCHEMA
            ),
            "screens": screens,
            "viewports": viewports,
            "mechanic_fixture_required": True,
            "browser_play_frontend_owner": "outer_agent",
            "browser_play_tests_required": True,
            "browser_play_handoff_required": True,
            "browser_play_manifest_schema": (
                "gamefactory3a.browser_play_manifest.v1"
            ),
            "browser_play_may_bind_mechanic": False,
        },
        "context_usage_contract": {
            "path": str(
                workspace
                / "generated_ui"
                / "context_used.json"
            ),
            "schema_version": CONTEXT_USED_SCHEMA,
            "required_context": [
                {
                    "stage": "engine_native",
                    "role": "engine_api",
                },
                {
                    "stage": "browser_play",
                    "role": "browser_serving_api",
                },
            ],
            "required_examples": {},
            "example_roots": {
                "mechanic_example": [
                    str(path)
                    for path in mechanic_example_roots
                ],
                "ui_example": [
                    str(path)
                    for path in ui_example_roots
                ],
                "browser_play_example": [
                    str(path)
                    for path in browser_play_examples
                ],
            },
            "required_example_roles": [
                "mechanic_example",
                "ui_example",
                "browser_play_example",
            ],
            "example_purpose_required": True,
            "allowed_example_purposes": list(
                EXAMPLE_REFERENCE_PURPOSES
            ),
        },
        "repair": repair,
        "required_output_artifacts": (
            required_output_artifacts
        ),
        "standard_output_layout": (
            standard_layout
        ),
    }
    instructions = (
        "# Prepared UI Code Generation\n\n"
        f"Packet: `{packet_path}`\n\n"
        "Read the UI Skill, Mechanic artifact, and both supplied Context "
        "APIs before editing. Do not scan entire Example roots. Select the "
        "smallest useful set of Mechanic and native UI reference files needed "
        "to learn plugin/module and code patterns, but never use them as base "
        "implementations, templates, or "
        "runtime dependencies. Any same-Engine genre is valid architecture "
        "guidance. Do not require a genre, mechanic, HUD, or visual match; no "
        "analogous Example is needed. Read the required Browser Play "
        "reference. "
        "Discover the Engine and Browser Serving APIs. Complete the "
        "engine-native UI, then generate the Browser Play frontend "
        "against the registered backend, Browser Play Example, and "
        "repository-owned player frontend reference. Do not generate "
        "backend source.\n\n"
        "## System Guidance\n\n"
        f"{system_prompt.rstrip()}\n\n"
        "## Task Guidance\n\n"
        f"{task_prompt.rstrip()}\n"
    )
    if repair_prompt:
        instructions += (
            "\n## Repair Guidance\n\n"
            f"{repair_prompt.rstrip()}\n"
        )
    return prepare_workspace(
        packet,
        workspace=workspace,
        stage_dir=stage_dir,
        instructions=instructions,
        reserved_roots=DEFAULT_RESERVED_ROOTS,
        force=force,
    )
