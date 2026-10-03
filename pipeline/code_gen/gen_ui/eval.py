"""Evaluate finalized Generate-UI artifacts without generation."""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.common import paths
from pipeline.common.artifacts import (
    is_relative_to,
    read_json,
    write_json,
)


TASK_KIND = "ui"


def _string_list(
    value: Any,
    name: str,
) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{name} must be a sequence")
    return [str(item) for item in value]


def evaluate_artifact(
    artifact_dir: str | Path,
) -> dict[str, Any]:
    """Check the finalized UI code-generation artifact contract."""
    root = Path(artifact_dir).expanduser().resolve(
        strict=False
    )
    errors: list[str] = []
    checks: dict[str, bool] = {
        "artifact_dir_exists": root.is_dir(),
        "meta_exists": (root / "meta.json").is_file(),
    }
    meta: dict[str, Any] = {}
    if checks["meta_exists"]:
        try:
            meta = read_json(
                root / "meta.json",
                "UI artifact metadata",
            )
        except (FileNotFoundError, TypeError, ValueError) as exc:
            errors.append(str(exc))
    else:
        errors.append(
            f"UI artifact metadata is missing: {root / 'meta.json'}"
        )

    checks["finalized"] = meta.get("status") == "completed"
    checks["outer_agent_owned"] = (
        meta.get("generation_owner") == "outer_agent"
    )
    checks["task_kind"] = meta.get("task_kind") == TASK_KIND
    meta_errors = meta.get("errors", [])
    if isinstance(meta_errors, Sequence) and not isinstance(
        meta_errors,
        (str, bytes),
    ):
        checks["no_finalize_errors"] = not list(meta_errors)
    else:
        checks["no_finalize_errors"] = False
        errors.append("meta.errors must be a sequence")

    changes: dict[str, list[str]] = {}
    for field in (
        "generated_files",
        "modified_files",
        "deleted_files",
    ):
        try:
            changes[field] = _string_list(
                meta.get(field, []),
                f"meta.{field}",
            )
        except TypeError as exc:
            changes[field] = []
            errors.append(str(exc))
    checks["has_task_owned_changes"] = any(
        changes.values()
    )

    listed_files_exist = True
    for field in ("generated_files", "modified_files"):
        for relative_path in changes[field]:
            target = (
                root / relative_path
            ).resolve(strict=False)
            if (
                not is_relative_to(target, root)
                or not target.is_file()
            ):
                listed_files_exist = False
                errors.append(
                    f"Finalized {field} entry is missing: "
                    f"{relative_path}"
                )
    for relative_path in changes["deleted_files"]:
        target = (
            root / relative_path
        ).resolve(strict=False)
        if not is_relative_to(target, root) or target.exists():
            listed_files_exist = False
            errors.append(
                "Finalized deleted_files entry still exists: "
                f"{relative_path}"
            )
    checks["listed_file_changes_match_workspace"] = (
        listed_files_exist
    )

    artifact_checks = meta.get(
        "required_artifact_checks",
        {},
    )
    if isinstance(artifact_checks, Mapping):
        checks["required_artifacts_passed"] = all(
            value is not False
            for value in artifact_checks.values()
        )
        checks["generated_ui_source"] = (
            artifact_checks.get("generated_ui_source")
            is True
        )
        checks["generated_ui_test_source"] = (
            artifact_checks.get(
                "generated_ui_test_source"
            )
            is True
        )
        checks["screenshot_plan"] = (
            artifact_checks.get("screenshot_plan")
            is True
        )
        checks["ui_binding_manifest"] = (
            artifact_checks.get("ui_binding_manifest")
            is True
        )
        checks["mechanic_contract_fixture"] = (
            artifact_checks.get(
                "mechanic_contract_fixture"
            )
            is True
        )
        checks["browser_play_source"] = (
            artifact_checks.get(
                "browser_play_source"
            )
            is True
        )
        checks["browser_play_test_source"] = (
            artifact_checks.get(
                "browser_play_test_source"
            )
            is True
        )
        checks["browser_play_handoff"] = (
            artifact_checks.get(
                "browser_play_handoff"
            )
            is True
        )
        checks["browser_play_bootstrap"] = (
            artifact_checks.get(
                "browser_play_bootstrap"
            )
            is True
        )
        checks["browser_play_mechanic_free"] = (
            artifact_checks.get(
                "browser_play_mechanic_free"
            )
            is True
        )
        checks["native_runtime_adapter_only"] = (
            artifact_checks.get(
                "native_runtime_adapter_only"
            )
            is True
        )
        checks["context_used"] = (
            artifact_checks.get(
                "context_used"
            )
            is True
        )
        checks["browser_backend_registered"] = (
            artifact_checks.get(
                "browser_backend_registered"
            )
            is True
        )
        checks["task_owned_output_roots"] = (
            artifact_checks.get(
                "task_owned_output_roots"
            )
            is True
        )
        checks["mechanic_contract_unchanged"] = (
            artifact_checks.get(
                "mechanic_contract_unchanged"
            )
            is True
        )
        checks["no_replacement_mechanic_contract"] = (
            artifact_checks.get(
                "no_replacement_mechanic_contract"
            )
            is True
        )
    else:
        checks["required_artifacts_passed"] = False
        checks["generated_ui_source"] = False
        checks["generated_ui_test_source"] = False
        checks["screenshot_plan"] = False
        checks["ui_binding_manifest"] = False
        checks["mechanic_contract_fixture"] = False
        checks["browser_play_source"] = False
        checks["browser_play_test_source"] = False
        checks["browser_play_handoff"] = False
        checks["browser_play_bootstrap"] = False
        checks["browser_play_mechanic_free"] = False
        checks["native_runtime_adapter_only"] = False
        checks["context_used"] = False
        checks["browser_backend_registered"] = False
        checks["task_owned_output_roots"] = False
        checks["mechanic_contract_unchanged"] = False
        checks["no_replacement_mechanic_contract"] = False
        errors.append(
            "meta.required_artifact_checks must be an object"
        )

    finalize_result_path = Path(
        str(meta.get("finalize_result_path") or "")
    ).expanduser().resolve(strict=False)
    checks["finalize_result_exists"] = bool(
        str(meta.get("finalize_result_path") or "").strip()
        and is_relative_to(finalize_result_path, root)
        and finalize_result_path.is_file()
    )

    for name, passed in checks.items():
        if not passed:
            errors.append(
                f"UI artifact check failed: {name}"
            )
    ok = not errors
    return {
        "ok": ok,
        "status": "passed" if ok else "failed",
        "task_kind": TASK_KIND,
        "artifact_dir": str(root),
        "score": 1.0 if ok else 0.0,
        "scope": "code_generation_artifact_contract",
        "authoritative_validation": False,
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
    }


def evaluate(
    *,
    game_id: str,
    task_id: str,
    run_id: str = paths.DEFAULT_RUN_ID,
) -> dict[str, Any]:
    """Evaluate one existing standard-layout UI artifact."""
    artifact_dir = paths.task_output_dir(
        game_id,
        TASK_KIND,
        task_id,
        run_id=run_id,
        create=False,
    )
    result = evaluate_artifact(artifact_dir)
    result.update(
        {
            "game_id": game_id,
            "run_id": run_id,
            "task_id": task_id,
        }
    )
    output_dir = paths.eval_output_dir(
        game_id,
        TASK_KIND,
        task_id,
        run_id=run_id,
    )
    metrics_path = output_dir / "metrics.json"
    result["metrics_path"] = str(metrics_path)
    write_json(metrics_path, result)
    return result


def run_from_jsonl(
    tasks_path: str | Path,
    *,
    run_id: str = paths.DEFAULT_RUN_ID,
    game_filter: str | None = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for task, game_id in paths.iter_tasks(
        tasks_path,
        game_filter=game_filter,
    ):
        selected_task_id = str(
            task.get("task_id") or ""
        )
        if task_id and selected_task_id != task_id:
            continue
        if not selected_task_id:
            raise ValueError(
                "UI evaluation task is missing task_id"
            )
        results.append(
            evaluate(
                game_id=game_id,
                task_id=selected_task_id,
                run_id=run_id,
            )
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate finalized UI code-generation artifacts "
            "without triggering generation."
        )
    )
    parser.add_argument("--game", default=None)
    parser.add_argument("--tasks", default=None)
    parser.add_argument("--task-id", default=None)
    parser.add_argument(
        "--run-id",
        default=paths.DEFAULT_RUN_ID,
    )
    args = parser.parse_args(argv)
    tasks_path = paths.resolve_tasks_path(
        TASK_KIND,
        args.tasks,
        args.game,
    )
    results = run_from_jsonl(
        tasks_path,
        run_id=args.run_id,
        game_filter=args.game,
        task_id=args.task_id,
    )
    print(
        json.dumps(
            results,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if all(
        result["ok"]
        for result in results
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
