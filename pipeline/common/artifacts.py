"""Shared Pipeline helpers for files, Prompts, and artifact manifests."""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from pipeline.common import paths


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def read_required_text(path: Path, name: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"{name} was not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"{name} is empty: {path}")
    return text


def resolve_repo_path(
    value: str | Path,
    name: str,
    *,
    must_exist: bool = False,
    require_file: bool = False,
) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = paths.REPO_ROOT / path
    path = path.resolve(strict=False)
    if must_exist and not path.exists():
        raise FileNotFoundError(f"{name} was not found: {path}")
    if require_file and not path.is_file():
        raise FileNotFoundError(f"{name} must be a file: {path}")
    return path


def resolve_workspace_file(
    workspace: str | Path,
    relative_path: str,
) -> Path:
    root = Path(workspace).expanduser().resolve(strict=False)
    relative = Path(str(relative_path or "").strip())
    if (
        not str(relative)
        or relative.is_absolute()
        or ".." in relative.parts
    ):
        raise ValueError(
            "workspace file paths must be non-empty and relative"
        )
    target = (root / relative).resolve(strict=False)
    if not is_relative_to(target, root):
        raise ValueError(
            f"workspace file escapes the workspace: {relative_path}"
        )
    return target


def identifier(value: Any, prefix: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", str(value or ""))
    candidate = "".join(
        part[:1].upper() + part[1:]
        for part in parts
    )
    if not candidate:
        candidate = prefix
    if candidate[0].isdigit():
        candidate = prefix + candidate
    return candidate


def render_template(
    template: str,
    values: Mapping[str, str],
) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    unresolved = sorted(
        set(re.findall(r"\{\{[A-Z0-9_]+\}\}", rendered))
    )
    if unresolved:
        raise ValueError(
            "Prompt template has unresolved markers: "
            + ", ".join(unresolved)
        )
    return rendered


def json_text(value: Any) -> str:
    return json.dumps(
        value,
        indent=2,
        ensure_ascii=False,
        default=str,
    )


def write_json(path: str | Path, value: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json_text(value) + "\n",
        encoding="utf-8",
    )
    return target


def read_json(path: str | Path, name: str) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"{name} was not found: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} is not valid JSON: {target}") from exc
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must contain a JSON object")
    return dict(value)


def _normalized_relative_paths(
    values: Sequence[str],
) -> set[str]:
    result: set[str] = set()
    for value in values:
        pure = PurePosixPath(str(value).replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(
                f"manifest exclusion must be workspace-relative: {value}"
            )
        result.add(pure.as_posix())
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def path_digest(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve(strict=False)
    if target.is_file():
        return {
            "kind": "file",
            "sha256": _sha256(target),
            "size": target.stat().st_size,
            "files": 1,
        }
    if not target.is_dir():
        raise FileNotFoundError(
            f"Digest input was not found: {target}"
        )
    manifest: dict[str, dict[str, Any]] = {}
    total_size = 0
    for item in sorted(target.rglob("*")):
        if not item.is_file():
            continue
        resolved = item.resolve(strict=False)
        if not is_relative_to(resolved, target):
            raise ValueError(
                "Digest input resolves outside its root: "
                f"{item}"
            )
        relative = item.relative_to(target).as_posix()
        size = item.stat().st_size
        manifest[relative] = {
            "sha256": _sha256(item),
            "size": size,
        }
        total_size += size
    serialized = json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "kind": "directory",
        "sha256": hashlib.sha256(serialized).hexdigest(),
        "size": total_size,
        "files": len(manifest),
    }


def build_file_manifest(
    workspace: str | Path,
    *,
    exclude_relative_paths: Sequence[str] = (),
) -> dict[str, dict[str, Any]]:
    root = Path(workspace).expanduser().resolve(strict=False)
    if not root.is_dir():
        return {}
    excluded = _normalized_relative_paths(exclude_relative_paths)
    manifest: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        resolved = path.resolve(strict=False)
        if not is_relative_to(resolved, root):
            raise ValueError(
                f"workspace file resolves outside the workspace: {path}"
            )
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        manifest[relative] = {
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
    return manifest


def partition_manifest(
    manifest: Mapping[str, Mapping[str, Any]],
    reserved_roots: Sequence[str],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    reserved = {str(item).strip("/") for item in reserved_roots}
    task_owned: dict[str, dict[str, Any]] = {}
    pipeline_owned: dict[str, dict[str, Any]] = {}
    for relative_path, metadata in manifest.items():
        first = PurePosixPath(relative_path).parts[0]
        target = (
            pipeline_owned
            if first in reserved
            else task_owned
        )
        target[relative_path] = dict(metadata)
    return task_owned, pipeline_owned


def diff_file_manifests(
    before: Mapping[str, Mapping[str, Any]],
    after: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[str]]:
    before_paths = set(before)
    after_paths = set(after)
    generated = sorted(after_paths - before_paths)
    deleted = sorted(before_paths - after_paths)
    modified = sorted(
        path
        for path in before_paths & after_paths
        if dict(before[path]) != dict(after[path])
    )
    return {
        "generated_files": generated,
        "modified_files": modified,
        "deleted_files": deleted,
    }
