"""Prepare deterministic outer-Agent Mechanic task packets."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pipeline.code_gen.gen_mechanic.contracts import (
    MECHANIC_CONTRACT_FILENAME,
    MECHANIC_CONTRACT_SCHEMA,
)
from pipeline.common import paths
from pipeline.common.artifacts import (
    identifier,
    json_text,
    read_required_text,
    render_template,
    resolve_repo_path,
)
from pipeline.common.code_mapping import (
    CONTEXT_USED_SCHEMA,
    EXAMPLE_REFERENCE_PURPOSES,
    mapping_list,
    provenance_digests,
    repair_payload,
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


TASK_KIND = "mechanic"
CONTEXT_ROOT = (
    paths.REPO_ROOT
    / "agent_skills"
    / "code_gen"
    / "mechanic"
)
SKILL_PATH = CONTEXT_ROOT / "game_generation.md"
PROMPTS_ROOT = CONTEXT_ROOT / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_ROOT / "system.md"
TASK_PROMPT_PATH = PROMPTS_ROOT / "task.md"
REPAIR_PROMPT_PATH = PROMPTS_ROOT / "repair.md"


def prepare(
    inp: dict[str, Any],
    *,
    run_id: str = paths.DEFAULT_RUN_ID,
    output_dir: str | None = None,
    default_game_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Compose one Mechanic packet without loading a Model or Operator."""
    if not isinstance(inp, Mapping):
        raise TypeError("Mechanic task must be an object")
    task = dict(inp)
    mode = str(task.get("mode") or "generate").strip().lower()
    if mode not in {"generate", "repair"}:
        raise ValueError(
            "Mechanic task mode must be generate or repair"
        )
    repair, repair_attempt = repair_payload(task, mode)
    task_id = str(task.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("Mechanic task must contain task_id")
    requested_engine = str(
        task.get("engine") or ""
    ).strip()
    if not requested_engine:
        raise ValueError("Mechanic task must contain engine")
    registration = resolve_engine_registration(
        requested_engine
    )
    engine = str(registration["engine_id"])
    engine_context_root = Path(
        registration["context_root"]
    )
    example_roots = resolve_engine_example_roots(
        registration,
        "mechanic_example",
    )
    suggested_examples = resolve_engine_example_paths(
        task,
        registration,
        "mechanic_example",
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
    project_name = identifier(
        task.get("project_name")
        or f"A3Game_{task_id}",
        "A3Game",
    )
    gameplay_module_name = identifier(
        task.get("gameplay_module_name")
        or f"{project_name}_Gameplay",
        "GeneratedGameplay",
    )
    requirement_path = resolve_repo_path(
        str(task.get("requirement_path") or ""),
        "requirement_path",
        require_file=True,
    )
    requirement = read_required_text(
        requirement_path,
        "Mechanic requirement",
    )
    general_requirement_path = (
        paths.TEST_SAMPLES_ROOT
        / game_id
        / "general_requirement.txt"
    ).resolve(strict=False)
    general_requirement = (
        general_requirement_path.read_text(encoding="utf-8")
        if general_requirement_path.is_file()
        else ""
    )
    system_prompt = read_required_text(
        SYSTEM_PROMPT_PATH,
        "Mechanic system Prompt",
    )
    task_template = read_required_text(
        TASK_PROMPT_PATH,
        "Mechanic task Prompt",
    )
    repair_template = read_required_text(
        REPAIR_PROMPT_PATH,
        "Mechanic repair Prompt",
    )
    read_required_text(
        SKILL_PATH,
        "Game Mechanic Generation Skill",
    )

    stage_dir = code_gen_stage_dir(
        workspace,
        mode=mode,
        repair_attempt=repair_attempt,
    )
    packet_path = stage_dir / "task_packet.json"
    agent_task = dict(task)
    for repeated_key in (
        "asset_sources",
        "motion_sources",
        "acceptance_criteria",
        "operator_execution",
        "example_paths",
        "examples",
        "mechanic_example_paths",
        "mode",
        "repair",
    ):
        agent_task.pop(repeated_key, None)
    task_prompt = render_template(
        task_template,
        {
            "WORKSPACE": str(workspace),
            "PROJECT_NAME": project_name,
            "GAMEPLAY_MODULE_NAME": gameplay_module_name,
            "GAME_GENERATION_SKILL_PATH": str(SKILL_PATH),
            "TASK_PACKET_PATH": str(packet_path),
            "TASK_JSON": json_text(agent_task),
            "GENERAL_REQUIREMENT": general_requirement,
            "REQUIREMENT": requirement,
            "ACCEPTANCE_CRITERIA": json_text(
                task.get("acceptance_criteria", [])
            ),
            "ASSET_SOURCES": json_text(
                task.get("asset_sources", [])
            ),
            "MOTION_SOURCES": json_text(
                task.get("motion_sources", [])
            ),
            "ENGINE": engine,
            "ENGINE_CONTEXT_ROOT": str(
                engine_context_root
            ),
            "MECHANIC_EXAMPLE_ROOTS": json_text(
                [str(path) for path in example_roots]
            ),
            "MECHANIC_EXAMPLE_PATHS": json_text(
                [
                    str(path)
                    for path in suggested_examples
                ]
            ),
            "EXAMPLE_REFERENCE_PURPOSES": json_text(
                list(EXAMPLE_REFERENCE_PURPOSES)
            ),
            "CONTEXT_USED_PATH": str(
                workspace / "context_used.json"
            ),
        },
    )
    repair_prompt = ""
    if mode == "repair":
        repair_prompt = render_template(
            repair_template,
            {
                "WORKSPACE": str(workspace),
                "REPAIR_ATTEMPT": str(repair["attempt"]),
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
        *example_roots,
    ]
    if general_requirement_path.is_file():
        read_only_paths.append(general_requirement_path)
    validate_boundaries(workspace, read_only_paths)

    packet_id = (
        f"{game_id}:{run_id}:{task_id}:"
        f"{mode}:{repair_attempt}"
    )
    provenance_paths = [
        engine_context_root,
        *example_roots,
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
        "project_name": project_name,
        "gameplay_module_name": gameplay_module_name,
        "task": agent_task,
        "context": {
            "general_requirement": general_requirement,
            "general_requirement_path": (
                str(general_requirement_path)
                if general_requirement_path.is_file()
                else ""
            ),
            "requirement": requirement,
            "requirement_path": str(requirement_path),
            "acceptance_criteria": string_list(
                task.get("acceptance_criteria", []),
                "acceptance_criteria",
            ),
            "asset_sources": mapping_list(
                task.get("asset_sources", []),
                "asset_sources",
            ),
            "motion_sources": mapping_list(
                task.get("motion_sources", []),
                "motion_sources",
            ),
            "engine_context_root": str(
                engine_context_root
            ),
            "skill_path": str(SKILL_PATH),
            "prompt_template_paths": {
                "system": str(SYSTEM_PROMPT_PATH),
                "task": str(TASK_PROMPT_PATH),
                "repair": str(REPAIR_PROMPT_PATH),
            },
            "mechanic_example_roots": [
                str(path)
                for path in example_roots
            ],
            "mechanic_example_paths": [
                str(path)
                for path in suggested_examples
            ],
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
            "agent_may_declare_benchmark_success": False,
            "agent_may_generate_ui": False,
        },
        "mechanic_contract": {
            "path": str(
                workspace / MECHANIC_CONTRACT_FILENAME
            ),
            "schema_version": MECHANIC_CONTRACT_SCHEMA,
            "required_sections": [
                "state",
                "events",
                "commands",
                "public_api_paths",
            ],
            "gameplay_module": gameplay_module_name,
            "public_runtime_adapter_required": True,
        },
        "context_usage_contract": {
            "path": str(
                workspace / "context_used.json"
            ),
            "schema_version": CONTEXT_USED_SCHEMA,
            "required_context": [
                {
                    "stage": "mechanic",
                    "role": "engine_api",
                }
            ],
            "required_examples": {},
            "example_roots": {
                "mechanic_example": [
                    str(path)
                    for path in example_roots
                ]
            },
            "required_example_roles": [
                "mechanic_example"
            ],
            "example_purpose_required": True,
            "allowed_example_purposes": list(
                EXAMPLE_REFERENCE_PURPOSES
            ),
        },
        "repair": repair,
        "required_output_artifacts": string_list(
            task.get("required_output_artifacts", []),
            "required_output_artifacts",
        ),
        "standard_output_layout": standard_layout,
    }
    instructions = (
        "# Prepared Mechanic Code Generation\n\n"
        f"Packet: `{packet_path}`\n\n"
        "Read the Skill and Engine Context paths from the packet before "
        "editing. Discover the registered Engine API inside the supplied "
        "Engine Context root. Do not scan the entire Example root. Select the "
        "smallest useful set of structural Mechanic Example files needed to "
        "learn the Engine's plugin/module and native code workflow. "
        "Examples are educational references only, not base implementations, "
        "templates, inheritance targets, or gameplay constraints. Freely "
        "implement mechanics not present in the Examples. Do not require a "
        "genre or mechanic match; an FPS reference may guide the plugin "
        "architecture of a MOBA or unrelated game. The absence of a similar "
        "Example is never a blocker.\n\n"
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
