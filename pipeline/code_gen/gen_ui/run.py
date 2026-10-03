"""Prepare or finalize one outer-Agent Generate-UI task."""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.code_gen.gen_ui.artifacts import (
    finalize,
    required_artifact_checks as _required_artifact_checks,
)
from pipeline.code_gen.gen_ui.contracts import (
    MECHANIC_CONTRACT_FILENAME,
    MECHANIC_CONTRACT_SCHEMA,
    MECHANIC_FIXTURE_SCHEMA,
    SCREENSHOT_PLAN_SCHEMA,
    UI_BINDING_MANIFEST_SCHEMA,
    contract_entries as _contract_entries,
    load_mechanic_contract as _load_mechanic_contract,
    resolved_binding_definitions as _resolved_binding_definitions,
)
from pipeline.code_gen.gen_ui.packet import (
    BROWSER_PLAY_DELIVERY_MODE,
    CONTEXT_ROOT,
    DEFAULT_REQUIRED_ARTIFACTS,
    ENGINE_NATIVE_DELIVERY_MODE,
    FULL_UI_DELIVERY_MODE,
    PROMPTS_ROOT,
    REPAIR_PROMPT_PATH,
    SKILL_PATH,
    SYSTEM_PROMPT_PATH,
    TASK_KIND,
    TASK_PROMPT_PATH,
    delivery_mode as _delivery_mode,
    prepare,
)
from pipeline.common import paths
from pipeline.common.artifacts import read_json
from pipeline.common.code_mapping import select_task


def _direct_task(
    args: argparse.Namespace,
) -> dict[str, Any]:
    if not args.engine:
        raise ValueError(
            "--engine is required with --requirement-path"
        )
    if not args.mechanic_artifact:
        raise ValueError(
            "--mechanic-artifact is required with "
            "--requirement-path"
        )
    if not args.design_doc:
        raise ValueError(
            "--design-doc is required with --requirement-path"
        )
    viewports: list[list[int]] = []
    for value in args.viewport or ["1920x1080"]:
        match = re.fullmatch(
            r"\s*(\d+)\s*[xX]\s*(\d+)\s*",
            value,
        )
        if not match:
            raise ValueError(
                "--viewport must use WIDTHxHEIGHT"
            )
        viewports.append(
            [
                int(match.group(1)),
                int(match.group(2)),
            ]
        )
    _delivery_mode(args.ui_target)
    task: dict[str, Any] = {
        "game_id": args.game,
        "task_id": args.task_id or "demo_ui",
        "engine": args.engine,
        "ui_target": args.ui_target,
        "requirement_path": args.requirement_path,
        "design_doc_path": args.design_doc,
        "mechanic_artifact_path": (
            args.mechanic_artifact
        ),
        "project_name": args.project_name,
        "ui_module_name": args.module_name,
        "example_paths": list(args.example),
        "reference_image_dir": (
            args.reference_image_dir
        ),
        "state_bindings": list(
            args.state_binding
        ),
        "event_bindings": list(
            args.event_binding
        ),
        "command_bindings": list(
            args.command_binding
        ),
        "screens": list(args.screen),
        "view_constraints": {},
        "viewports": viewports,
        "forbidden_ui": [],
        "acceptance_criteria": [],
        "required_output_artifacts": list(
            DEFAULT_REQUIRED_ARTIFACTS
        ),
    }
    return {
        key: value
        for key, value in task.items()
        if value is not None and value != ""
    }


def _prepare_command(
    args: argparse.Namespace,
) -> int:
    run_id = (
        paths.new_run_id()
        if args.run_id == "auto"
        else args.run_id
    )
    if args.requirement_path:
        task = _direct_task(args)
    else:
        tasks_path = paths.resolve_tasks_path(
            TASK_KIND,
            args.tasks,
            args.game,
        )
        task = select_task(
            tasks_path,
            game_id=args.game,
            task_id=args.task_id,
            task_name="UI",
        )
        if args.mechanic_artifact:
            task["mechanic_artifact_path"] = (
                args.mechanic_artifact
            )
            task.pop("mechanic_artifact", None)
            task.pop("mechanic_task", None)
    if args.mode:
        task["mode"] = args.mode
    if args.repair_json:
        task["mode"] = "repair"
        task["repair"] = read_json(
            args.repair_json,
            "UI repair payload",
        )
    packet = prepare(
        task,
        run_id=run_id,
        output_dir=args.out_dir,
        default_game_id=args.game,
        force=args.force,
    )
    print(
        json.dumps(
            {
                "packet_id": packet["packet_id"],
                "workspace": packet["workspace"],
                "task_packet_path": packet[
                    "artifacts"
                ]["task_packet_path"],
                "instructions_path": packet[
                    "artifacts"
                ]["instructions_path"],
                "skill_path": packet["context"][
                    "skill_path"
                ],
                "engine_context_root": packet[
                    "context"
                ]["engine_context_root"],
                "delivery_mode": packet[
                    "delivery_mode"
                ],
                "mechanic_example_roots": packet[
                    "context"
                ]["mechanic_example_roots"],
                "mechanic_example_paths": packet[
                    "context"
                ]["mechanic_example_paths"],
                "ui_example_roots": packet[
                    "context"
                ]["ui_example_roots"],
                "ui_example_paths": packet[
                    "context"
                ]["ui_example_paths"],
                "browser_play_example_paths": packet[
                    "context"
                ]["browser_play_example_paths"],
                "browser_backend": packet[
                    "context"
                ]["browser_backend"],
                "mechanic_artifact_path": packet[
                    "context"
                ]["mechanic_artifact_path"],
                "mechanic_contract_path": packet[
                    "context"
                ]["mechanic_contract_path"],
                "design_document_path": packet[
                    "context"
                ]["design_document_path"],
                "reference_image_paths": packet[
                    "context"
                ]["reference_image_paths"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _finalize_command(
    args: argparse.Namespace,
) -> int:
    result = finalize(
        args.packet,
        summary=args.summary,
    )
    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if result["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare or finalize one outer-Agent UI "
            "code-generation task."
        )
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )
    prepare_parser = subparsers.add_parser(
        "prepare",
        help="Prepare one UI task packet and workspace.",
    )
    prepare_parser.add_argument(
        "--game",
        default=None,
        help=(
            "Game project id. Known: "
            f"{paths.list_games() or '<none>'}"
        ),
    )
    prepare_parser.add_argument(
        "--tasks",
        default=None,
        help=(
            "Explicit JSONL path; overrides the --game "
            "task-list lookup."
        ),
    )
    prepare_parser.add_argument(
        "--task-id",
        default=None,
    )
    prepare_parser.add_argument(
        "--run-id",
        default=paths.DEFAULT_RUN_ID,
    )
    prepare_parser.add_argument(
        "--out-dir",
        default=None,
    )
    prepare_parser.add_argument(
        "--mode",
        choices=["generate", "repair"],
        default=None,
    )
    prepare_parser.add_argument(
        "--repair-json",
        default=None,
    )
    prepare_parser.add_argument(
        "--requirement-path",
        default=None,
    )
    prepare_parser.add_argument(
        "--design-doc",
        default=None,
    )
    prepare_parser.add_argument(
        "--engine",
        default=None,
    )
    prepare_parser.add_argument(
        "--ui-target",
        default="engine_runtime",
    )
    prepare_parser.add_argument(
        "--mechanic-artifact",
        default=None,
    )
    prepare_parser.add_argument(
        "--project-name",
        default=None,
    )
    prepare_parser.add_argument(
        "--module-name",
        default=None,
    )
    prepare_parser.add_argument(
        "--reference-image-dir",
        default=None,
    )
    prepare_parser.add_argument(
        "--state-binding",
        action="append",
        default=[],
    )
    prepare_parser.add_argument(
        "--event-binding",
        action="append",
        default=[],
    )
    prepare_parser.add_argument(
        "--command-binding",
        action="append",
        default=[],
    )
    prepare_parser.add_argument(
        "--screen",
        action="append",
        default=[],
    )
    prepare_parser.add_argument(
        "--viewport",
        action="append",
        default=[],
        help=(
            "Required viewport in WIDTHxHEIGHT form."
        ),
    )
    prepare_parser.add_argument(
        "--example",
        action="append",
        default=[],
    )
    prepare_parser.add_argument(
        "--force",
        action="store_true",
    )
    prepare_parser.set_defaults(
        handler=_prepare_command
    )

    finalize_parser = subparsers.add_parser(
        "finalize",
        help="Finalize a directly edited UI workspace.",
    )
    finalize_parser.add_argument(
        "--packet",
        required=True,
    )
    finalize_parser.add_argument(
        "--summary",
        default="",
    )
    finalize_parser.set_defaults(
        handler=_finalize_command
    )
    return parser


def main(
    argv: list[str] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (
        FileExistsError,
        FileNotFoundError,
        TypeError,
        ValueError,
    ) as exc:
        parser.error(str(exc))
    return 2


__all__ = [
    "build_parser",
    "finalize",
    "main",
    "prepare",
]


if __name__ == "__main__":
    raise SystemExit(main())
