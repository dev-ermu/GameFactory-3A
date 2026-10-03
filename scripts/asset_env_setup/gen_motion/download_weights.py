"""Download only the Puppeteer and HumanML3D weights used by 3AGameFactory."""

import argparse
import os
import zipfile
from pathlib import Path


PUPPETEER_FILES = (
    ("facebook/opt-350m", "config.json", "skeleton/third_partys/opt-350m"),
    (
        "Maikou/Michelangelo",
        "checkpoints/aligned_shape_latents/shapevae-256.ckpt",
        "skeleton/third_partys/Michelangelo",
    ),
    (
        "Seed3D/Puppeteer",
        "skeleton_ckpts/puppeteer_skeleton_w_diverse_pose.pth",
        "skeleton",
    ),
    (
        "mikaelaangel/partfield-ckpt",
        "model_objaverse.ckpt",
        "skinning/third_partys/PartField/ckpt",
    ),
    (
        "Seed3D/Puppeteer",
        "skinning_ckpts/puppeteer_skin_w_diverse_pose_depth1.pth",
        "skinning",
    ),
)
MOMASK_FILE_ID = "1vXS7SHJBgWPt59wupQ5UUzhFObrnGkQ0"


def _data_root() -> Path:
    configured = os.environ.get("A3GF_RUNTIME_ROOT")
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return Path(configured).expanduser() if configured else base / "gamefactory3a"


def _cache_root() -> Path:
    configured = os.environ.get("A3GF_CACHE_ROOT")
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return Path(configured).expanduser() if configured else base / "gamefactory3a"


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            target = (destination / item.filename).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"Unsafe path in MoMask archive: {item.filename}")
        bundle.extractall(destination)


def _download_puppeteer(source: Path) -> list[Path]:
    from huggingface_hub import hf_hub_download

    outputs = []
    for repo_id, filename, relative_root in PUPPETEER_FILES:
        local_dir = source / relative_root
        local_dir.mkdir(parents=True, exist_ok=True)
        print(f"[weights] {repo_id}/{filename}")
        output = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=local_dir,
        )
        outputs.append(Path(output))
    return outputs


def _link_michelangelo(puppeteer: Path) -> None:
    target = puppeteer / "skinning/third_partys/Michelangelo"
    if target.exists() or target.is_symlink():
        return
    source = puppeteer / "skeleton/third_partys/Michelangelo"
    try:
        target.symlink_to(source, target_is_directory=True)
    except OSError as exc:
        raise RuntimeError(
            "Could not link the shared Michelangelo directory. Run on Linux "
            "or WSL2 and check filesystem symlink support."
        ) from exc


def _download_momask(source: Path, cache: Path) -> list[Path]:
    import gdown

    archive = cache / "momask_humanml3d_models.zip"
    if not archive.is_file() or not zipfile.is_zipfile(archive):
        partial = archive.with_suffix(".zip.partial")
        partial.parent.mkdir(parents=True, exist_ok=True)
        print("[weights] MoMask HumanML3D archive")
        result = gdown.download(
            id=MOMASK_FILE_ID,
            output=str(partial),
            quiet=False,
            resume=True,
        )
        if not result or not zipfile.is_zipfile(partial):
            raise RuntimeError(f"MoMask download is not a valid ZIP: {partial}")
        partial.replace(archive)

    destination = source / "checkpoints/t2m"
    print(f"[weights] extracting HumanML3D models -> {destination}")
    _safe_extract(archive, destination)
    return [
        destination
        / "t2m_nlayer8_nhead6_ld384_ff1024_cdp0.1_rvq6ns/model/latest.tar",
        destination
        / "tres_nlayer8_ld384_ff1024_rvq6ns_cdp0.2_sw/model/net_best_fid.tar",
        destination
        / "rvq_nq6_dc512_nc512_noshare_qdp0.2/model/net_best_fid.tar",
        destination / "length_estimator/model/finest.tar",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-root",
        default=str(_data_root()),
        help="Source and weight root (default: A3GF_RUNTIME_ROOT).",
    )
    parser.add_argument(
        "--cache-root",
        default=str(_cache_root()),
        help="Download cache root (default: A3GF_CACHE_ROOT).",
    )
    parser.add_argument("--skip-puppeteer", action="store_true")
    parser.add_argument("--skip-momask", action="store_true")
    args = parser.parse_args()

    root = Path(args.runtime_root).expanduser().resolve()
    cache = Path(args.cache_root).expanduser().resolve() / "downloads"
    puppeteer = root / "sources/Puppeteer"
    momask = root / "sources/momask-codes"
    required: list[Path] = []

    if not args.skip_puppeteer:
        required.extend(_download_puppeteer(puppeteer))
        _link_michelangelo(puppeteer)
    if not args.skip_momask:
        required.extend(_download_momask(momask, cache))

    missing = [str(path) for path in required if not path.is_file() or not path.stat().st_size]
    if missing:
        raise RuntimeError("Required outputs are missing:\n  - " + "\n  - ".join(missing))
    print("[weights] selected motion weights are ready")


if __name__ == "__main__":
    main()
