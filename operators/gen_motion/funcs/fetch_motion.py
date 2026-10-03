"""
Ingest an external motion clip (Mixamo, CMU, …) for retargeting.

Manual sources (login-gated) refuse automated download — pass a local path.
Writes ``*_motion_source.json`` next to the clip for licence tracking.
"""

import json
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .retarget_utils.formats import SUPPORTED_MOTION_SUFFIXES
from .retarget_utils.mapping_presets import (
    identify_motion_file,
    read_rig_joint_names,
)

SUPPORTED_MOTION_FORMATS = SUPPORTED_MOTION_SUFFIXES
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class MotionSource:
    """One external motion library."""

    name: str
    title: str
    url: str
    formats: tuple[str, ...]
    skeleton: str | None
    access: str  # "manual" | "direct"
    licence: str
    nominal_units: str
    how_to_download: str
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        data = asdict(self)
        data["formats"] = list(self.formats)
        data["notes"] = list(self.notes)
        return data


MOTION_SOURCES: dict[str, MotionSource] = {
    "mixamo": MotionSource(
        name="mixamo",
        title="Adobe Mixamo",
        url="https://www.mixamo.com/",
        formats=(".fbx",),
        skeleton="mixamo",
        access="manual",
        licence="Free with Adobe account; do not redistribute raw clips.",
        nominal_units="centimetres",
        how_to_download=(
            "Sign in at mixamo.com → Download → FBX Binary, Skin=Without Skin. "
            "Pass the file as path=."
        ),
        notes=("Prefer Without Skin; use global_scale=0.01 vs metre-scale rigs.",),
    ),
    "mocap_online": MotionSource(
        name="mocap_online",
        title="MoCap Online",
        url="https://mocaponline.com/pages/free-animations",
        formats=(".fbx", ".bvh"),
        skeleton="ue5_mannequin",
        access="manual",
        licence="Free samples via zero-cost checkout; check pack terms.",
        nominal_units="centimetres",
        how_to_download=(
            "Checkout the free sample pack, then pass the archive/file as path=."
        ),
    ),
    "cmu_bvh": MotionSource(
        name="cmu_bvh",
        title="CMU MoCap (BVH conversion)",
        url="http://mocap.cs.cmu.edu/",
        formats=(".bvh",),
        skeleton="cmu_bvh",
        access="direct",
        licence="Free for all uses; please credit CMU / NSF EIA-0196217.",
        nominal_units="inches",
        how_to_download="Pass url= to a .bvh (or .zip + member=).",
        notes=("Quality varies; preview before committing.",),
    ),
    "bandai_namco": MotionSource(
        name="bandai_namco",
        title="Bandai Namco Research Motion Dataset",
        url=(
            "https://github.com/BandaiNamcoResearchInc/"
            "Bandai-Namco-Research-Motiondataset"
        ),
        formats=(".bvh",),
        skeleton=None,
        access="direct",
        licence="CC BY-NC-ND 4.0 — research only, not for shipped games.",
        nominal_units="centimetres",
        how_to_download="Pass url= to a raw dataset .bvh on GitHub.",
    ),
    "local": MotionSource(
        name="local",
        title="Local file",
        url="",
        formats=SUPPORTED_MOTION_FORMATS,
        skeleton=None,
        access="manual",
        licence="Whatever the file came with — record it in the task.",
        nominal_units="unknown",
        how_to_download="Pass path= to a .bvh or .fbx on disk.",
    ),
}


def list_motion_sources() -> list[dict]:
    return [source.as_dict() for source in MOTION_SOURCES.values()]


def get_motion_source(name: str) -> MotionSource:
    try:
        return MOTION_SOURCES[str(name).lower()]
    except KeyError:
        available = ", ".join(sorted(MOTION_SOURCES))
        raise KeyError(
            f"Unknown motion source {name!r}. Known: {available}"
        ) from None


def fetch_motion(
    *,
    source: str = "local",
    path: str | Path | None = None,
    url: str | None = None,
    member: str | None = None,
    dest_dir: str | Path,
    name: str | None = None,
) -> dict:
    """
    Copy/download one clip into ``dest_dir`` and write provenance JSON.

    Provide exactly one of ``path`` or ``url``. ``url`` is only allowed for
    ``access=direct`` sources.
    """
    library = get_motion_source(source)
    if bool(path) == bool(url):
        raise ValueError(
            "fetch_motion needs exactly one of path= or url=; "
            f"got path={path!r}, url={url!r}"
        )

    destination = Path(dest_dir)
    destination.mkdir(parents=True, exist_ok=True)

    if url:
        if library.access != "direct":
            raise PermissionError(
                f"{library.title} does not allow automated downloads "
                f"({url}).\nDownload by hand:\n  {library.how_to_download}\n"
                "Then pass path=."
            )
        origin = _download(url, destination / "_download")
    else:
        origin = Path(path).expanduser().resolve()
        if not origin.is_file() or origin.stat().st_size == 0:
            raise FileNotFoundError(f"Motion file is missing or empty: {origin}")

    clip = _extract_clip(origin, member, destination, name)
    identified = identify_motion_file(clip)
    provenance = _write_provenance(
        clip,
        library=library,
        origin=str(url or origin),
        member=member,
        identified=identified,
    )
    return {
        "motion_path": str(clip),
        "provenance_path": str(provenance),
        "source": library.name,
        "skeleton": identified.get("skeleton") or library.skeleton,
        "identified": identified,
        "licence": library.licence,
    }


def _download(url: str, into: Path) -> Path:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Only http(s) URLs can be fetched, got {url!r}")

    into.mkdir(parents=True, exist_ok=True)
    filename = Path(urllib.parse.unquote(parsed.path)).name or "download.bin"
    target = into / filename
    request = urllib.request.Request(
        url, headers={"User-Agent": "3AGameFactory/gen_motion"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            declared = int(response.headers.get("Content-Length") or 0)
            if declared > MAX_DOWNLOAD_BYTES:
                raise ValueError(
                    f"{url} is {declared} bytes (limit {MAX_DOWNLOAD_BYTES}). "
                    "Download locally and pass path=."
                )
            written = 0
            with open(target, "wb") as handle:
                while chunk := response.read(1 << 20):
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        handle.close()
                        target.unlink(missing_ok=True)
                        raise ValueError(
                            f"{url} exceeded the {MAX_DOWNLOAD_BYTES} byte limit."
                        )
                    handle.write(chunk)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not download {url}: {exc}") from exc
    if target.stat().st_size == 0:
        raise RuntimeError(f"{url} returned an empty file.")
    return target


def _extract_clip(
    origin: Path,
    member: str | None,
    destination: Path,
    name: str | None,
) -> Path:
    if origin.suffix.lower() == ".zip":
        source_name, payload = _read_zip_member(origin, member)
        clip = destination / (name or Path(source_name).name)
        clip.write_bytes(payload)
    else:
        _validate_motion_suffix(origin)
        clip = destination / (name or origin.name)
        if origin.resolve() != clip.resolve():
            shutil.copyfile(origin, clip)
    _validate_motion_suffix(clip)
    if clip.stat().st_size == 0:
        raise RuntimeError(f"Extracted an empty motion clip: {clip}")
    return clip


def _read_zip_member(archive: Path, member: str | None) -> tuple[str, bytes]:
    with zipfile.ZipFile(archive) as bundle:
        candidates = [
            info.filename
            for info in bundle.infolist()
            if not info.is_dir()
            and Path(info.filename).suffix.lower() in SUPPORTED_MOTION_FORMATS
        ]
        if member:
            matches = [
                item
                for item in candidates
                if item == member or Path(item).name == member
            ]
            if not matches:
                raise KeyError(
                    f"{member!r} not found in {archive.name} "
                    f"({len(candidates)} clips: {candidates[:8]})"
                )
            chosen = matches[0]
        elif len(candidates) == 1:
            chosen = candidates[0]
        elif not candidates:
            raise ValueError(f"{archive.name} contains no .bvh or .fbx clip.")
        else:
            raise ValueError(
                f"{archive.name} holds {len(candidates)} clips; "
                f"pass member=. First: {candidates[:8]}"
            )
        return chosen, bundle.read(chosen)


def _validate_motion_suffix(path: Path) -> None:
    if path.suffix.lower() not in SUPPORTED_MOTION_FORMATS:
        raise ValueError(
            "Motion clips must be "
            f"{' or '.join(SUPPORTED_MOTION_FORMATS)}, got {path.name}"
        )


def _write_provenance(
    clip: Path,
    *,
    library: MotionSource,
    origin: str,
    member: str | None,
    identified: dict,
) -> Path:
    record = {
        "clip": str(clip),
        "source": library.name,
        "source_title": library.title,
        "source_url": library.url,
        "licence": library.licence,
        "origin": origin,
        "archive_member": member,
        "nominal_units": library.nominal_units,
        "declared_skeleton": library.skeleton,
        "identified_skeleton": identified.get("skeleton"),
        "identification_confidence": identified.get("confidence"),
        "notes": list(library.notes),
    }
    path = clip.with_name(f"{clip.stem}_motion_source.json")
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def measure_bvh_extent(bvh_path: str | Path) -> float:
    """Rest-pose height (Y extent) of a BVH hierarchy."""
    positions: list[tuple[float, float, float]] = []
    stack: list[tuple[float, float, float]] = []
    current = (0.0, 0.0, 0.0)
    pending = False

    with open(bvh_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            token = line.split()
            if not token:
                continue
            head = token[0].upper()
            if head == "MOTION":
                break
            if head in {"ROOT", "JOINT", "END"}:
                pending = True
            elif head == "OFFSET" and len(token) >= 4 and pending:
                offset = tuple(float(v) for v in token[1:4])
                current = tuple(a + b for a, b in zip(current, offset))
                positions.append(current)  # type: ignore[arg-type]
                pending = False
            elif head == "{":
                stack.append(current)
            elif head == "}":
                current = stack.pop() if stack else (0.0, 0.0, 0.0)
    if not positions:
        return 0.0
    heights = [p[1] for p in positions]
    return max(heights) - min(heights)


def measure_rig_extent(rig_path: str | Path) -> float:
    """Height of a Puppeteer rig joint cloud (metres)."""
    heights = []
    with open(rig_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            token = line.split()
            if len(token) >= 5 and token[0] == "joints":
                heights.append(float(token[4]))
    return max(heights) - min(heights) if heights else 0.0


def suggest_global_scale(motion_path: str | Path, rig_path: str | Path) -> dict:
    """Suggest ``global_scale`` so clip and rig rest heights match (BVH only)."""
    motion = Path(motion_path)
    rig_extent = measure_rig_extent(rig_path)
    joint_count = len(read_rig_joint_names(rig_path))

    if motion.suffix.lower() != ".bvh":
        return {
            "suggested_global_scale": None,
            "confident": False,
            "motion_extent": None,
            "rig_extent": rig_extent or None,
            "rig_joint_count": joint_count,
            "reason": (
                "Only BVH is measurable here. Mixamo FBX is usually "
                "centimetres — try global_scale=0.01 against a metre-scale rig."
            ),
        }

    motion_extent = measure_bvh_extent(motion)
    if motion_extent <= 1e-6 or rig_extent <= 1e-6:
        return {
            "suggested_global_scale": None,
            "confident": False,
            "motion_extent": motion_extent or None,
            "rig_extent": rig_extent or None,
            "rig_joint_count": joint_count,
            "reason": "One skeleton measured flat; retarget at 1.0 and inspect.",
        }

    ratio = rig_extent / motion_extent
    return {
        "suggested_global_scale": round(ratio, 6),
        "confident": True,
        "motion_extent": round(motion_extent, 6),
        "rig_extent": round(rig_extent, 6),
        "rig_joint_count": joint_count,
        "reason": (
            f"Rest-pose height {motion_extent:.4g} (clip) vs "
            f"{rig_extent:.4g} m (rig)."
        ),
    }


__all__ = [
    "MAX_DOWNLOAD_BYTES",
    "MOTION_SOURCES",
    "MotionSource",
    "SUPPORTED_MOTION_FORMATS",
    "fetch_motion",
    "get_motion_source",
    "list_motion_sources",
    "measure_bvh_extent",
    "measure_rig_extent",
    "suggest_global_scale",
]
