"""Encode UE MRQ PNG sequences into review MP4s and contact sheets."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import cv2


CASES = ("fire", "smoke")


def find_frames(root: Path) -> list[Path]:
    frames = sorted(root.rglob("*.png"))
    if not frames:
        raise RuntimeError(f"no PNG frames found under {root}")
    return frames


def find_ffmpeg(explicit: Path | None) -> str:
    candidates = [
        str(explicit) if explicit else None,
        shutil.which("ffmpeg"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("ffmpeg was not found; pass --ffmpeg with an ffmpeg.exe path")


def encode_case(
    kind: str, frames: list[Path], out_dir: Path, fps: int, ffmpeg: str
) -> dict:
    first = cv2.imread(str(frames[0]), cv2.IMREAD_COLOR)
    if first is None:
        raise RuntimeError(f"cannot read frame: {frames[0]}")
    height, width = first.shape[:2]
    mp4_path = out_dir / f"{kind}.mp4"
    samples = []
    sample_indices = {0, len(frames) // 3, 2 * len(frames) // 3, len(frames) - 1}
    for index, path in enumerate(frames):
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if frame is None or frame.shape[:2] != (height, width):
            raise RuntimeError(f"invalid frame: {path}")
        if index in sample_indices:
            labeled = frame.copy()
            cv2.putText(
                labeled,
                f"{index / fps:.1f}s",
                (18, 38),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            samples.append(labeled)

    input_pattern = str(frames[0].parent / "%04d.png")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-framerate",
            str(fps),
            "-i",
            input_pattern,
            "-frames:v",
            str(len(frames)),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(mp4_path),
        ],
        check=True,
    )

    sheet = cv2.hconcat(samples)
    sheet_path = out_dir / f"{kind}_contact_sheet.jpg"
    if not cv2.imwrite(str(sheet_path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 92]):
        raise RuntimeError(f"could not write contact sheet: {sheet_path}")

    capture = cv2.VideoCapture(str(mp4_path))
    encoded_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    capture.release()
    if encoded_frames != len(frames):
        raise RuntimeError(
            f"encoded frame mismatch for {kind}: {encoded_frames} != {len(frames)}"
        )
    return {
        "video": mp4_path.name,
        "contact_sheet": sheet_path.name,
        "fps": fps,
        "frames": len(frames),
        "resolution": [width, height],
        "duration_seconds": round(len(frames) / fps, 3),
        "codec": "h264",
        "pixel_format": "yuv420p",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--ffmpeg", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg(args.ffmpeg)

    records = {}
    for kind in CASES:
        records[kind] = encode_case(
            kind, find_frames(args.frames_root / kind), args.output, args.fps, ffmpeg
        )
    manifest = {
        "status": "pending_human_review",
        "rendered_at": datetime.now(timezone.utc).isoformat(),
        "engine": "Unreal Engine 5.7",
        "effects": records,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
