"""Download and install the Woosh-DFlow checkpoints from the official release."""

import os
import shutil
import stat
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator


DEFAULT_WOOSH_RELEASE_BASE_URL = (
    "https://github.com/SonyResearch/Woosh/releases/download/v1.0.0"
)


def ensure_woosh_dflow_checkpoints(
    dflow_path: str | Path,
    autoencoder_path: str | Path,
    text_conditioner_path: str | Path,
    *,
    auto_download: bool = True,
    release_base_url: str = DEFAULT_WOOSH_RELEASE_BASE_URL,
) -> None:
    """Ensure all three checkpoints required by Woosh-DFlow are installed.

    Existing valid directories are never downloaded again. Missing checkpoints
    are fetched from Sony's official GitHub Release and installed at the exact
    paths supplied by the caller, regardless of the archive's ``checkpoints/``
    prefix.
    """
    checkpoints = (
        ("Woosh-DFlow", Path(dflow_path).expanduser().resolve()),
        ("Woosh-AE", Path(autoencoder_path).expanduser().resolve()),
        ("TextConditionerA", Path(text_conditioner_path).expanduser().resolve()),
    )
    missing = [(name, path) for name, path in checkpoints if not _is_ready(path)]
    if not missing:
        return

    if not auto_download:
        formatted = ", ".join(f"{name} ({path})" for name, path in missing)
        raise FileNotFoundError(
            f"Missing Woosh checkpoint(s): {formatted}. Enable automatic download "
            "or download the three v1.0.0 release archives manually."
        )

    for name, target in missing:
        _ensure_release_asset(name, target, release_base_url.rstrip("/"))


def _is_ready(path: Path) -> bool:
    return (path / "config.yaml").is_file()


@contextmanager
def _download_lock(target: Path) -> Iterator[None]:
    """Serialize installers for one target; OS releases the lock on process exit."""
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.parent / f".{target.name}.download.lock"
    lock_file = lock_path.open("a+b")
    try:
        try:
            import fcntl
        except ImportError:
            # Woosh targets Linux/macOS. Keep a functional fallback for other
            # platforms, while atomic final installation still prevents a
            # partially extracted checkpoint from being observed.
            yield
        else:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


def _ensure_release_asset(name: str, target: Path, release_base_url: str) -> None:
    with _download_lock(target):
        # Another process may have completed the installation while this one
        # waited for the lock.
        if _is_ready(target):
            return
        if target.exists():
            raise FileExistsError(
                f"Woosh checkpoint directory exists but is incomplete: {target}. "
                "Move or remove that directory, then retry the automatic download."
            )

        url = f"{release_base_url}/{name}.zip"
        print(f"[woosh] {name} is missing; downloading {url}")
        with tempfile.TemporaryDirectory(
            prefix=f".{name}.download-", dir=str(target.parent)
        ) as temp_dir:
            temp_root = Path(temp_dir)
            archive_path = temp_root / f"{name}.zip"
            staged_checkpoint = temp_root / name
            _download_file(url, archive_path)
            print(f"[woosh] Extracting {name} -> {target}")
            _extract_checkpoint(archive_path, name, staged_checkpoint)
            if not _is_ready(staged_checkpoint):
                raise RuntimeError(
                    f"Downloaded {name}.zip did not contain {name}/config.yaml. "
                    "The release archive layout may have changed."
                )
            os.replace(staged_checkpoint, target)
        print(f"[woosh] Installed {name} at {target}")


def _download_file(
    url: str,
    destination: Path,
    *,
    retries: int = 3,
    timeout_sec: int = 60,
) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "3AGameFactory-WooshDownloader/1.0"},
    )
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                total_header = response.headers.get("Content-Length")
                total = int(total_header) if total_header else None
                downloaded = 0
                last_report = time.monotonic()
                with destination.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        downloaded += len(chunk)
                        now = time.monotonic()
                        if now - last_report >= 5:
                            print(_progress_message(downloaded, total))
                            last_report = now
            if total is not None and downloaded != total:
                raise OSError(
                    f"Incomplete download: received {downloaded} of {total} bytes"
                )
            print(_progress_message(downloaded, total, complete=True))
            return
        except (OSError, urllib.error.URLError) as exc:
            destination.unlink(missing_ok=True)
            if attempt == retries:
                raise RuntimeError(
                    f"Failed to download {url} after {retries} attempts. "
                    "Set WOOSH_RELEASE_BASE_URL to a reachable mirror, or download "
                    "and extract the archive manually."
                ) from exc
            print(f"[woosh] Download attempt {attempt} failed: {exc}; retrying...")


def _progress_message(downloaded: int, total: int | None, complete: bool = False) -> str:
    downloaded_mib = downloaded / (1024 * 1024)
    prefix = "[woosh] Download complete:" if complete else "[woosh] Downloaded"
    if total:
        total_mib = total / (1024 * 1024)
        percent = downloaded * 100 / total
        return f"{prefix} {downloaded_mib:.1f}/{total_mib:.1f} MiB ({percent:.1f}%)"
    return f"{prefix} {downloaded_mib:.1f} MiB"


def _extract_checkpoint(archive_path: Path, name: str, destination: Path) -> None:
    """Safely extract only the named checkpoint directory from a release zip."""
    extracted_files = 0
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            parts = PurePosixPath(info.filename).parts
            try:
                checkpoint_index = parts.index(name)
            except ValueError:
                continue
            relative_parts = parts[checkpoint_index + 1 :]
            if not relative_parts:
                continue

            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise RuntimeError(f"Refusing symlink in Woosh archive: {info.filename}")

            output_path = destination.joinpath(*relative_parts)
            if not output_path.resolve().is_relative_to(destination.resolve()):
                raise RuntimeError(f"Unsafe path in Woosh archive: {info.filename}")
            if info.is_dir():
                output_path.mkdir(parents=True, exist_ok=True)
                continue

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, output_path.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            extracted_files += 1

    if not extracted_files:
        raise RuntimeError(f"No {name} files were found in {archive_path.name}.")
