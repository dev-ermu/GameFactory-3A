"""Validation for gen-motion source-to-Puppeteer bone mapping JSON."""

import json
from pathlib import Path
from typing import Any


def load_and_validate_mapping(path: str | Path) -> dict[str, Any]:
    """Load a mapping and fail early when its required structure is invalid."""
    mapping_path = Path(path)
    if not mapping_path.is_file() or mapping_path.stat().st_size == 0:
        raise FileNotFoundError(
            f"Retarget mapping is missing or empty: {mapping_path}"
        )
    try:
        data = json.loads(mapping_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Invalid retarget mapping JSON: {mapping_path}: {exc}"
        ) from exc

    bone_map = data.get("bone_map")
    if not isinstance(bone_map, dict) or not bone_map:
        raise ValueError(
            f"Retarget mapping must contain a non-empty 'bone_map': {mapping_path}"
        )
    invalid = [
        (source, target)
        for source, target in bone_map.items()
        if not isinstance(source, str)
        or not source
        or not isinstance(target, str)
        or not target
    ]
    if invalid:
        raise ValueError(
            "Retarget mapping bone_map must contain non-empty string pairs; "
            f"invalid entries: {invalid[:3]}"
        )

    roots = data.get("root_bones", {})
    if roots and not isinstance(roots, dict):
        raise ValueError(
            f"Retarget mapping 'root_bones' must be an object: {mapping_path}"
        )
    return data
