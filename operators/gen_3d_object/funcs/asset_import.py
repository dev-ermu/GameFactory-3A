"""Hand a 3D artifact to the three.js adapter.

A generated mesh only becomes part of a game once the engine adapter has
staged it and rewritten the runtime manifest, and that handover has three
rules that are easy to get wrong:

1. **Write a task output first.** The adapter's asset API consumes
   *repository task identities* — ``(game_id, run_id, task_kind, task_id)``
   plus an artifact key — not filesystem paths. That is what makes an
   import reproducible from a run directory, and why nothing here copies a
   file into ``public/`` itself.
2. **Declare the facing axis.** glTF cannot express it and the runtime
   cannot guess it, so an import that omits it gives a character even odds
   of running backwards. See
   ``agent_skills/asset_qa/imported_asset_orientation.md``.
3. **Declare the real-world size.** A generated mesh is normalised into a
   unit box; ``scale_hint_metres`` is how a prop ends up prop-sized.
"""

import shutil
from pathlib import Path
from typing import Any, Mapping

from pipeline.common import paths

TASK_KIND = "3d_object"


def find_project_file(
    game_id: str,
    run_id: str = paths.DEFAULT_RUN_ID,
    hint: str = "",
) -> Path | None:
    """Locate the generated Vite project's ``package.json`` for one game.

    Resolved rather than concatenated, so relocating the output root does
    not break asset import. ``hint`` is a ``mechanic/<task_id>`` relative
    path, for a run that produced more than one project.
    """

    run_root = paths.run_dir(game_id, run_id)
    if hint:
        candidate = run_root / hint / "package.json"
        return candidate if candidate.is_file() else None
    matches = sorted(run_root.glob("mechanic/*/package.json"))
    return matches[0] if matches else None


def stage_task_output(
    game_id: str,
    task_id: str,
    artifact: Path,
    *,
    run_id: str = paths.DEFAULT_RUN_ID,
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write one GLB plus ``meta.json`` as a proper task output."""

    task_dir = paths.task_output_dir(
        game_id, TASK_KIND, task_id, run_id=run_id
    )
    target = task_dir / artifact.name
    if target.resolve() != artifact.resolve():
        shutil.copyfile(artifact, target)
    paths.write_task_meta(
        task_dir,
        {
            "game_id": game_id,
            "run_id": run_id,
            "task_kind": TASK_KIND,
            "task_id": task_id,
            "glb_path": target.name,
            "bytes": target.stat().st_size,
            **dict(meta or {}),
        },
    )
    return {
        "game_id": game_id,
        "run_id": run_id,
        "task_kind": TASK_KIND,
        "task_id": task_id,
        "output_dir": str(task_dir),
        "glb_path": str(target),
    }


def import_asset(
    game_id: str,
    task_id: str,
    *,
    asset_id: str,
    asset_type: str = "prop",
    run_id: str = paths.DEFAULT_RUN_ID,
    forward_axis: str = "",
    scale_hint_metres: float | None = None,
    verified_by: str = "",
    notes: str = "",
    project_hint: str = "",
    preview: bool = True,
) -> dict[str, Any]:
    """Stage one task output into a game's three.js project.

    Returns ``{imported, backend_path, orientation, preview_sheet,
    warnings, errors}``. A missing project is reported, not raised: the
    task output is still on disk and can be imported once the mechanic
    task has produced somewhere to put it.
    """

    outcome: dict[str, Any] = {
        "imported": False,
        "backend_path": "",
        "orientation": {},
        "preview_sheet": "",
        "warnings": [],
        "errors": [],
    }
    project_file = find_project_file(game_id, run_id, project_hint)
    if project_file is None:
        outcome["errors"].append(
            f"No generated project found for {game_id}; the task output was "
            "written and can be imported once one exists"
        )
        return outcome

    from engine_adapters.three_js import ThreeClient

    client = ThreeClient(project_path=str(project_file))
    options: dict[str, Any] = {
        "asset_id": asset_id,
        "replace_existing": True,
    }
    if forward_axis:
        options["forward_axis"] = forward_axis
        options["verified_by"] = verified_by or "declared"
    elif verified_by:
        options["verified_by"] = verified_by
    if scale_hint_metres:
        options["scale_hint_metres"] = float(scale_hint_metres)
    if notes:
        options["notes"] = notes

    result = client.assets.import_asset(
        {
            "game_id": game_id,
            "run_id": run_id,
            "task_kind": TASK_KIND,
            "task_id": task_id,
            "artifact_key": "glb_path",
        },
        str(asset_type or "prop").strip().lower(),
        options=options,
    )
    outcome["project_file"] = str(project_file)
    outcome["warnings"] = list(result.get("warnings") or [])
    if not result.get("ok"):
        outcome["errors"] = list(result.get("errors") or [])
        return outcome

    payload = result.get("payload") or {}
    outcome["imported"] = True
    outcome["backend_path"] = str(payload.get("backend_path") or "")
    outcome["orientation"] = dict(payload.get("orientation") or {})

    if preview:
        # Produced in the same pass as the import, because the decision an
        # agent has to make is cheapest while the asset is still fresh.
        report = client.preview.orientation_report(asset_id)
        if report.get("ok"):
            outcome["preview_sheet"] = str(
                (report.get("payload") or {}).get("contact_sheet") or ""
            )
        else:
            outcome["warnings"].extend(
                str(item) for item in report.get("errors") or []
            )
    return outcome
