"""UI schemas and finalized Mechanic contract validation."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pipeline.common.artifacts import (
    path_digest,
    read_json,
)
from pipeline.common.code_mapping import string_list


MECHANIC_CONTRACT_SCHEMA = (
    "gamefactory3a.mechanic_contract.v1"
)
MECHANIC_CONTRACT_FILENAME = "mechanic_contract.json"
UI_BINDING_MANIFEST_SCHEMA = (
    "gamefactory3a.ui_binding_manifest.v1"
)
MECHANIC_FIXTURE_SCHEMA = (
    "gamefactory3a.mechanic_contract_fixture.v1"
)
SCREENSHOT_PLAN_SCHEMA = (
    "gamefactory3a.ui_screenshot_plan.v1"
)
BROWSER_PLAY_MANIFEST_SCHEMA = (
    "gamefactory3a.browser_play_manifest.v1"
)


def file_digest(path: Path) -> dict[str, Any]:
    return path_digest(path)


def contract_entries(
    value: Any,
    section: str,
) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    if isinstance(value, Mapping):
        iterable = [
            (
                str(name),
                (
                    dict(metadata)
                    if isinstance(metadata, Mapping)
                    else {"type": metadata}
                ),
            )
            for name, metadata in value.items()
        ]
    elif isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes),
    ):
        iterable = []
        for index, item in enumerate(value):
            if isinstance(item, str):
                iterable.append((item, {}))
            elif isinstance(item, Mapping):
                name = str(item.get("name") or "")
                iterable.append((name, dict(item)))
            else:
                raise TypeError(
                    f"Mechanic contract {section}[{index}] "
                    "must be a string or object"
                )
    else:
        raise TypeError(
            f"Mechanic contract {section} must be an object or sequence"
        )
    for raw_name, metadata in iterable:
        name = raw_name.strip()
        if not name:
            raise ValueError(
                f"Mechanic contract {section} contains an empty name"
            )
        if name in entries:
            raise ValueError(
                f"Mechanic contract {section} duplicates {name!r}"
            )
        entries[name] = {
            **metadata,
            "name": name,
        }
    if not entries:
        raise ValueError(
            f"Mechanic contract {section} must not be empty"
        )
    return entries


def load_mechanic_contract(
    contract_path: Path,
    gameplay_module_name: str,
) -> tuple[
    dict[str, Any],
    dict[str, dict[str, dict[str, Any]]],
]:
    contract = read_json(
        contract_path,
        "Mechanic contract",
    )
    if contract.get("schema_version") != (
        MECHANIC_CONTRACT_SCHEMA
    ):
        raise ValueError(
            "Mechanic contract schema_version must be "
            f"{MECHANIC_CONTRACT_SCHEMA!r}"
        )
    contract_version = contract.get("contract_version")
    if (
        not isinstance(contract_version, int)
        or isinstance(contract_version, bool)
        or contract_version <= 0
    ):
        raise ValueError(
            "Mechanic contract contract_version must be a "
            "positive integer"
        )
    if str(contract.get("gameplay_module") or "") != (
        gameplay_module_name
    ):
        raise ValueError(
            "Mechanic contract gameplay_module does not match "
            f"the finalized Mechanic metadata: "
            f"{contract.get('gameplay_module')!r} != "
            f"{gameplay_module_name!r}"
        )
    entries = {
        section: contract_entries(
            contract.get(section),
            section,
        )
        for section in ("state", "events", "commands")
    }
    public_api_paths = string_list(
        contract.get("public_api_paths", []),
        "mechanic_contract.public_api_paths",
    )
    if not public_api_paths:
        raise ValueError(
            "Mechanic contract public_api_paths must not be empty"
        )
    return contract, entries


def resolved_binding_definitions(
    task: Mapping[str, Any],
    entries: Mapping[
        str,
        Mapping[str, Mapping[str, Any]],
    ],
    *,
    require_state: bool = True,
) -> tuple[
    dict[str, list[str]],
    dict[str, list[dict[str, Any]]],
]:
    declared: dict[str, list[str]] = {}
    resolved: dict[str, list[dict[str, Any]]] = {}
    for section, task_key in (
        ("state", "state_bindings"),
        ("events", "event_bindings"),
        ("commands", "command_bindings"),
    ):
        names = string_list(
            task.get(task_key, []),
            task_key,
        )
        if section == "state" and require_state and not names:
            raise ValueError(
                "UI task must declare non-empty state_bindings"
            )
        available = entries[section]
        missing = [
            name
            for name in names
            if name not in available
        ]
        if missing:
            raise ValueError(
                f"UI task {task_key} are absent from the "
                "Mechanic contract: "
                + ", ".join(missing)
            )
        declared[section] = names
        resolved[section] = [
            dict(available[name])
            for name in names
        ]
    return declared, resolved
