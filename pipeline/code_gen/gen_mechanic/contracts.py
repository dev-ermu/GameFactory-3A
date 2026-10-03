"""Mechanic contract schema and deterministic validation."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pipeline.common.artifacts import (
    is_relative_to,
    read_json,
)


MECHANIC_CONTRACT_SCHEMA = (
    "gamefactory3a.mechanic_contract.v1"
)
MECHANIC_CONTRACT_FILENAME = "mechanic_contract.json"


def _contract_collection_present(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes),
    ):
        return bool(value)
    return False


def validate_mechanic_contract(
    workspace: Path,
    gameplay_module_name: str,
) -> tuple[bool, list[str]]:
    contract_path = workspace / MECHANIC_CONTRACT_FILENAME
    if not contract_path.is_file():
        return False, [
            "Required Mechanic contract is missing: "
            f"{MECHANIC_CONTRACT_FILENAME}"
        ]
    try:
        contract = read_json(
            contract_path,
            "Mechanic contract",
        )
    except (FileNotFoundError, TypeError, ValueError) as exc:
        return False, [str(exc)]

    errors: list[str] = []
    if contract.get("schema_version") != (
        MECHANIC_CONTRACT_SCHEMA
    ):
        errors.append(
            "Mechanic contract schema_version must be "
            f"{MECHANIC_CONTRACT_SCHEMA!r}"
        )
    contract_version = contract.get("contract_version")
    if (
        not isinstance(contract_version, int)
        or isinstance(contract_version, bool)
        or contract_version <= 0
    ):
        errors.append(
            "Mechanic contract contract_version must be a "
            "positive integer"
        )
    if str(contract.get("gameplay_module") or "") != (
        gameplay_module_name
    ):
        errors.append(
            "Mechanic contract gameplay_module must match "
            f"{gameplay_module_name!r}"
        )
    for section in ("state", "events", "commands"):
        if not _contract_collection_present(
            contract.get(section)
        ):
            errors.append(
                "Mechanic contract must define a non-empty "
                f"{section} collection"
            )
    raw_public_paths = contract.get("public_api_paths")
    if (
        isinstance(raw_public_paths, (str, bytes))
        or not isinstance(raw_public_paths, Sequence)
        or not raw_public_paths
    ):
        errors.append(
            "Mechanic contract must define non-empty "
            "public_api_paths"
        )
        raw_public_paths = []
    seen: set[Path] = set()
    for index, value in enumerate(raw_public_paths):
        relative = Path(str(value or "").strip())
        if (
            not str(relative)
            or relative.is_absolute()
            or ".." in relative.parts
        ):
            errors.append(
                "Mechanic contract public_api_paths entry "
                f"is invalid at index {index}"
            )
            continue
        target = (workspace / relative).resolve(
            strict=False
        )
        if (
            not is_relative_to(
                target,
                workspace.resolve(strict=False),
            )
            or not target.is_file()
        ):
            errors.append(
                "Mechanic contract public_api_paths entry "
                f"does not exist inside the workspace: {value}"
            )
            continue
        if target in seen:
            errors.append(
                "Mechanic contract public_api_paths contains "
                f"a duplicate entry: {value}"
            )
        seen.add(target)
    return not errors, errors
