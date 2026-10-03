"""Stable preview and orientation-review operations for ThreeClient v1.

An imported model has two properties glTF cannot express and gameplay
code cannot infer: how big it is meant to be, and which way it faces.
Scale is recoverable — a bounding box plus "this is a person" gives it
away. Facing is not: a model rotated 180° has an identical bounding box,
an identical node tree, and identical animation clips. Nothing in the
file distinguishes a character that runs forwards from one that runs
backwards.

What does distinguish them is *looking*. So this namespace renders an
artifact from named axes without a GPU, a display, or a browser, and
returns the images alongside the geometric evidence, so that a vision
model can supply the one fact the pipeline is missing and
``assets.set_orientation`` can record it.

The renders are review evidence, not shipped content: they are written
under the project's ``.a3game/previews`` directory and never staged into
``public/``.
"""

import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..assets import ThreeAssetsClient
from ..assets._internal.inspectors import inspect_source
from ..assets._internal.orientation import (
    RUNTIME_FORWARD_AXIS,
    RUNTIME_UP_AXIS,
    analyze_geometry,
)
from ..config import ThreeClientConfig
from ..contracts import ThreeOperationResult
from ._internal.views import (
    DEFAULT_VIEW_SET,
    VIEW_CONVENTION,
    VIEW_SCREEN_RIGHT,
    VIEW_SETS,
    resolve_axes,
)

#: Rendering pulls in `numpy` and `Pillow`. Importing `ThreeClient` must
#: not: the launchers run under a conda environment provisioned for Node,
#: whose Python is the standard library and nothing else. So the backend is
#: imported at the moment a render is requested, and its absence is
#: reported as anordinary operation failure with an actionable message
#: rather than as anImportError at `from engine_adapters.three_js import
#: ThreeClient`.
BACKEND_REQUIREMENT = (
    "Rendering a preview needs numpy and Pillow in the active interpreter. "
    "Install them (`pip install numpy pillow`), or run the preview from the "
    "repository's own environment instead of the Node toolchain env."
)


class PreviewBackendUnavailable(RuntimeError):
    """Raised when numpy or Pillow is missing from the interpreter."""


def _backend():
    """Import the render backend, or explain why it is unavailable."""

    from . import _internal

    try:
        _internal.require_backend()
    except ImportError as exc:  # numpy or Pillow missing
        raise PreviewBackendUnavailable(
            f"{BACKEND_REQUIREMENT} (original error: {exc})"
        ) from exc
    return _internal


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value or "asset"))
    return cleaned.strip("_") or "asset"


class ThreePreviewClient:
    """Render registered or generated artifacts for review."""

    def __init__(
        self,
        config: ThreeClientConfig,
        assets: ThreeAssetsClient,
    ) -> None:
        self._config = config
        self._assets = assets

    # ── Public operations ────────────────────────────────────────────────

    def render_artifact(
        self,
        reference: str,
        *,
        views: str | Sequence[str] = DEFAULT_VIEW_SET,
        size: int = 384,
        target_samples: int = 2_200_000,
        output_dir: str = "",
    ) -> dict[str, Any]:
        """Render a staged artifact from named axes.

        ``reference`` is an ``artifact_id`` or an ``asset_id``, the same
        two spellings the runtime asset library accepts.
        """

        operation = "preview.render_artifact"
        record = self._find_record(reference)
        if record is None:
            return ThreeOperationResult.failure(
                operation,
                f"Unknown asset reference: {reference}",
            ).to_dict()
        staged = self._staged_path(record)
        if staged is None:
            return ThreeOperationResult.failure(
                operation,
                "project_path is not configured; cannot locate the "
                "staged artifact",
                payload={"reference": reference},
            ).to_dict()
        if not staged.is_file():
            return ThreeOperationResult.failure(
                operation,
                f"Staged artifact was not found: {staged}",
                payload={"reference": reference},
            ).to_dict()
        return self._render(
            operation,
            staged,
            asset_id=str(record.get("asset_id") or reference),
            asset_type=str(record.get("type") or ""),
            views=views,
            size=size,
            target_samples=target_samples,
            output_dir=output_dir,
            extra_payload={
                "reference": reference,
                "artifact_id": record.get("artifact_id"),
                "orientation": dict(
                    (record.get("metadata") or {}).get("orientation") or {}
                ),
            },
        )

    def render_source(
        self,
        source: Mapping[str, Any],
        *,
        asset_type: str = "",
        views: str | Sequence[str] = DEFAULT_VIEW_SET,
        size: int = 384,
        target_samples: int = 2_200_000,
        output_dir: str = "",
    ) -> dict[str, Any]:
        """Render a repository task artifact *before* it is imported.

        Checking orientation before staging is the cheaper order: a model
        that turns out to face the wrong way can be annotated in the same
        ``import_asset`` call that stages it, instead of being staged,
        reviewed, and then re-imported.
        """

        operation = "preview.render_source"
        resolved = self._assets.resolve_source(source, asset_type=asset_type)
        if not resolved.get("ok"):
            resolved["operation"] = operation
            return resolved
        path = Path(str((resolved.get("payload") or {}).get("path") or ""))
        if path.is_dir():
            candidates = sorted(path.rglob("*.glb")) + sorted(
                path.rglob("*.gltf")
            )
            if not candidates:
                return ThreeOperationResult.failure(
                    operation,
                    f"No glTF entry point inside the package: {path}",
                ).to_dict()
            path = candidates[0]
        metadata = dict((resolved.get("payload") or {}).get("metadata") or {})
        return self._render(
            operation,
            path,
            asset_id=str(
                metadata.get("asset_id")
                or source.get("task_id")
                or path.stem
            ),
            asset_type=asset_type
            or str(metadata.get("asset_type") or ""),
            views=views,
            size=size,
            target_samples=target_samples,
            output_dir=output_dir,
            extra_payload={"source": dict(source)},
        )

    def orientation_report(
        self,
        reference: str | Mapping[str, Any],
        *,
        asset_type: str = "",
        size: int = 384,
        output_dir: str = "",
    ) -> dict[str, Any]:
        """Render the four horizontal views plus the geometric evidence.

        This is the operation the ``imported_asset_orientation`` agent
        skill drives. It answers everything that can be answered without
        looking, and states plainly what is left: the returned
        ``decision`` block lists the candidate axes and the exact
        ``assets.set_orientation`` call that records an answer.
        """

        operation = "preview.orientation_report"
        rendered = (
            self.render_artifact(
                reference,
                views="all",
                size=size,
                output_dir=output_dir,
            )
            if isinstance(reference, str)
            else self.render_source(
                reference,
                asset_type=asset_type,
                views="all",
                size=size,
                output_dir=output_dir,
            )
        )
        if not rendered.get("ok"):
            rendered["operation"] = operation
            return rendered

        payload = dict(rendered.get("payload") or {})
        resolved_type = asset_type or str(payload.get("asset_type") or "")
        try:
            inspection = inspect_source(
                Path(str(payload.get("source_path") or "")),
                asset_type=resolved_type,
            )
        except Exception as exc:
            return ThreeOperationResult.failure(
                operation,
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()

        evidence = analyze_geometry(
            inspection,
            asset_type=resolved_type,
            # The renderer composed the node hierarchy, so unlike the glTF
            # accessors it knows how large the model actually is. Handing
            # those extents back is what turns "proportions" into a usable
            # scale hint.
            bounds=self._render_bounds(payload.get("render") or {}),
        )
        target = (
            reference
            if isinstance(reference, str)
            else str(payload.get("asset_id") or "")
        )
        payload["evidence"] = evidence
        payload["decision"] = {
            "question": (
                "In which of the rendered views does the model face the "
                "camera? The axis named in that view's label is the "
                "model's forward axis."
            ),
            "candidate_forward_axes": list(
                evidence.get("candidate_forward_axes") or []
            ),
            "runtime_forward_axis": RUNTIME_FORWARD_AXIS,
            "runtime_up_axis": RUNTIME_UP_AXIS,
            "record_with": (
                "three.assets.set_orientation("
                f"{target!r}, forward_axis='<answer>', "
                "verified_by='agent_vision')"
            ),
            "screen_right_axis": dict(VIEW_SCREEN_RIGHT),
        }
        payload["reflection"] = inspection
        return ThreeOperationResult.success(
            operation,
            artifacts=list(rendered.get("artifacts") or []),
            warnings=list(rendered.get("warnings") or []),
            payload=payload,
        ).to_dict()

    def list_views(self) -> dict[str, Any]:
        """Report the view sets and what each rendered axis means."""

        return ThreeOperationResult.success(
            "preview.list_views",
            payload={
                "view_sets": {
                    name: list(axes) for name, axes in VIEW_SETS.items()
                },
                "screen_right_axis": dict(VIEW_SCREEN_RIGHT),
                "runtime_forward_axis": RUNTIME_FORWARD_AXIS,
                "runtime_up_axis": RUNTIME_UP_AXIS,
                "convention": VIEW_CONVENTION,
            },
        ).to_dict()

    # ── Internals ────────────────────────────────────────────────────────

    def _render(
        self,
        operation: str,
        path: Path,
        *,
        asset_id: str,
        asset_type: str,
        views: str | Sequence[str],
        size: int,
        target_samples: int,
        output_dir: str,
        extra_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            axes = resolve_axes(views)
        except ValueError as exc:
            return ThreeOperationResult.failure(
                operation, str(exc)
            ).to_dict()
        try:
            backend = _backend()
        except PreviewBackendUnavailable as exc:
            return ThreeOperationResult.failure(
                operation,
                str(exc),
                payload={"source_path": str(path)},
            ).to_dict()
        try:
            geometry = backend.load_geometry(path)
            images, info = backend.render_views(
                geometry,
                axes,
                size=size,
                target_samples=target_samples,
            )
        except backend.GeometryUnavailable as exc:
            return ThreeOperationResult.failure(
                operation,
                str(exc),
                payload={"source_path": str(path)},
            ).to_dict()
        except Exception as exc:
            return ThreeOperationResult.failure(
                operation,
                f"{type(exc).__name__}: {exc}",
                payload={"source_path": str(path)},
            ).to_dict()

        stem = _safe_stem(asset_id)
        directory = (
            Path(output_dir).expanduser()
            if output_dir
            else self._config.preview_root / stem
        )
        warnings: list[str] = []
        try:
            view_paths = backend.write_views(images, directory, stem=stem)
            sheet = backend.write_contact_sheet(
                images,
                directory,
                stem=stem,
                title=backend.sheet_title(
                    asset_id,
                    info,
                    extra=[asset_type] if asset_type else [],
                ),
            )
        except Exception as exc:
            return ThreeOperationResult.failure(
                operation,
                f"Rendering succeeded but writing did not: "
                f"{type(exc).__name__}: {exc}",
                payload={"source_path": str(path)},
            ).to_dict()

        if info.get("textured_surface_count", 0) == 0:
            warnings.append(
                "No base colour texture could be decoded, so the views "
                "are shaded flat. A face painted into a texture rather "
                "than modelled will not be visible; judge the facing "
                "direction from the silhouette instead."
            )
        if info.get("triangle_count", 0) < 8:
            warnings.append(
                "The artifact carries almost no geometry; the views may "
                "be empty."
            )

        payload: dict[str, Any] = {
            "asset_id": asset_id,
            "asset_type": asset_type,
            "source_path": str(path),
            "output_dir": str(directory),
            "views": view_paths,
            "contact_sheet": sheet,
            "view_axes": list(axes),
            "render": info,
        }
        payload.update(dict(extra_payload or {}))
        artifacts = [
            {
                "type": "preview_contact_sheet",
                "path": sheet,
                "state": "ready",
            }
        ] + [
            {
                "type": "preview_view",
                "path": view_path,
                "state": "ready",
                "metadata": {"view_axis": axis},
            }
            for axis, view_path in view_paths.items()
        ]
        return ThreeOperationResult.success(
            operation,
            artifacts=artifacts,
            warnings=warnings,
            payload=payload,
        ).to_dict()

    @staticmethod
    def _render_bounds(render: Mapping[str, Any]) -> dict[str, Any] | None:
        low = render.get("bounds_min")
        high = render.get("bounds_max")
        if not isinstance(low, list) or not isinstance(high, list):
            return None
        return {
            "min": list(low),
            "max": list(high),
            "size": list(render.get("bounds_size") or []),
            "center": list(render.get("centre") or []),
        }

    def _find_record(self, reference: str) -> dict[str, Any] | None:
        listed = self._assets.list_registered()
        records: Iterable[dict[str, Any]] = listed.get("artifacts") or []
        key = str(reference or "")
        for record in records:
            if str(record.get("artifact_id")) == key:
                return record
        for record in records:
            if str(record.get("asset_id")) == key:
                return record
        return None

    def _staged_path(self, record: Mapping[str, Any]) -> Path | None:
        public_root = self._config.public_root
        if public_root is None:
            return None
        return public_root / str(
            record.get("backend_path") or ""
        ).lstrip("/")
