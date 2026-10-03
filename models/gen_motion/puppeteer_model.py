"""
PuppeteerModel — automatic skeleton and skinning prediction for 3D meshes.

Reference: https://github.com/Seed3D/Puppeteer

The upstream project is intentionally executed in isolated subprocesses because
its skeleton and skinning stages have different working-directory assumptions
and use torchrun.  The public 3AGameFactory interface remains memory based.

Puppeteer rigging requires CUDA.  Constructing the wrapper on CPU is supported
for harness tests, but ``infer()`` fails fast with an actionable error.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


DEFAULT_SKELETON_CKPT = (
    "skeleton_ckpts/puppeteer_skeleton_w_diverse_pose.pth"
)
DEFAULT_SKINNING_CKPT = (
    "skinning_ckpts/puppeteer_skin_w_diverse_pose_depth1.pth"
)
DEFAULT_LLM_CONFIG = "third_partys/opt-350m"


class PuppeteerModel:
    """Thin wrapper around the official Puppeteer rigging pipeline."""

    def __init__(
        self,
        model_path: str,
        device: str = "cuda",
        *,
        python_bin: str | None = None,
        skeleton_ckpt: str = DEFAULT_SKELETON_CKPT,
        skinning_ckpt: str = DEFAULT_SKINNING_CKPT,
        llm_config: str = DEFAULT_LLM_CONFIG,
        input_pc_num: int = 8192,
        skinning_depth: int = 1,
        gpu: int = 0,
        verbose: bool = False,
    ):
        self.model_path = str(model_path)
        self.device = str(device)
        self.python_bin = str(python_bin or sys.executable)
        self.skeleton_ckpt = str(skeleton_ckpt)
        self.skinning_ckpt = str(skinning_ckpt)
        self.llm_config = str(llm_config)
        self.input_pc_num = int(input_pc_num)
        self.skinning_depth = int(skinning_depth)
        self.gpu = int(gpu)
        self.verbose = bool(verbose)
        self._loaded = False

    def load(self) -> None:
        """Validate source, interpreter and checkpoints without loading VRAM."""
        root = Path(self.model_path).expanduser().resolve()
        python_bin = Path(self.python_bin).expanduser().resolve()
        required = {
            "Puppeteer skeleton entrypoint": root / "skeleton" / "demo.py",
            "Puppeteer skinning entrypoint": root / "skinning" / "main.py",
            "Puppeteer skeleton checkpoint": (
                root / "skeleton" / self.skeleton_ckpt
            ),
            "Puppeteer skinning checkpoint": (
                root / "skinning" / self.skinning_ckpt
            ),
            "Puppeteer local OPT config": (
                root / "skeleton" / self.llm_config / "config.json"
            ),
            "Michelangelo ShapeVAE checkpoint": (
                root
                / "skeleton"
                / "third_partys"
                / "Michelangelo"
                / "checkpoints"
                / "aligned_shape_latents"
                / "shapevae-256.ckpt"
            ),
            "PartField checkpoint": (
                root
                / "skinning"
                / "third_partys"
                / "PartField"
                / "ckpt"
                / "model_objaverse.ckpt"
            ),
        }
        if not python_bin.is_file():
            raise RuntimeError(
                "Puppeteer Python executable does not exist: "
                f"{python_bin}. Set A3GF_PUPPETEER_PYTHON or pass "
                "--puppeteer-python."
            )
        missing = [
            f"{label}: {path}"
            for label, path in required.items()
            if not path.is_file() or path.stat().st_size == 0
        ]
        if missing:
            raise RuntimeError(
                "Puppeteer runtime is incomplete.\n  - "
                + "\n  - ".join(missing)
                + "\nRun scripts/asset_env_setup/gen_motion/install.sh first."
            )
        self.model_path = str(root)
        self.python_bin = str(python_bin)
        self._loaded = True

    def unload(self) -> None:
        """Release wrapper state; GPU memory already dies with subprocesses."""
        self._loaded = False

    def infer(
        self,
        mesh: bytes,
        mesh_format: str = ".glb",
        seed: int = 42,
        *,
        post_filter: bool = True,
        master_port: int = 10009,
    ) -> dict[str, Any]:
        """Predict a skeleton and skin weights for one mesh.

        Args:
            mesh: Complete mesh file content.
            mesh_format: Input extension such as ``.glb`` or ``.obj``.
            seed: Seed forwarded to both upstream inference stages.
            post_filter: Smooth skin weights over one-ring neighbours.
            master_port: Local torchrun rendezvous port.

        Returns:
            A dictionary containing ``rig_text``, ``skeleton_text``,
            ``mesh_obj_bytes`` and integer structure counts.
        """
        if self.device.lower() == "cpu":
            raise RuntimeError(
                "Puppeteer skeleton inference requires CUDA in the official "
                "implementation. Use device='cuda'; CPU remains supported for "
                "constructing the wrapper and running 3AGameFactory stub tests."
            )
        if not isinstance(mesh, (bytes, bytearray)) or not mesh:
            raise ValueError("mesh must be non-empty file bytes")
        if not self._loaded:
            self.load()

        ext = _normalise_mesh_format(mesh_format)
        with tempfile.TemporaryDirectory(prefix="aaagf_puppeteer_") as tmp:
            work = Path(tmp)
            source = work / f"avatar{ext}"
            source.write_bytes(bytes(mesh))
            mesh_dir = work / "mesh"
            skeleton_dir = work / "skeletons"
            skin_dir = work / "skin"
            mesh_dir.mkdir()
            skeleton_dir.mkdir()
            skin_dir.mkdir()
            mesh_obj = mesh_dir / "avatar.obj"
            _convert_to_obj(source, mesh_obj)

            skeleton_root = Path(self.model_path) / "skeleton"
            skeleton_save_name = "aaagf_skeleton"
            skeleton_output_root = work / "skeleton_output"
            skeleton_started = time.time()
            self._run(
                [
                    self.python_bin,
                    "demo.py",
                    "--input_path",
                    str(mesh_obj),
                    "--pretrained_weights",
                    self.skeleton_ckpt,
                    "--llm",
                    self.llm_config,
                    "--output_dir",
                    str(skeleton_output_root),
                    "--save_name",
                    skeleton_save_name,
                    "--input_pc_num",
                    str(self.input_pc_num),
                    "--seed",
                    str(int(seed)),
                    "--apply_marching_cubes",
                    "--joint_token",
                    "--seq_shuffle",
                ],
                cwd=skeleton_root,
                stage="skeleton",
            )
            predicted = (
                skeleton_output_root
                / skeleton_save_name
                / "avatar_pred.txt"
            )
            _require_fresh_output(
                predicted,
                "Puppeteer skeleton",
                newer_than=skeleton_started,
            )
            skeleton_path = skeleton_dir / "avatar.txt"
            shutil.copyfile(predicted, skeleton_path)

            skinning_root = Path(self.model_path) / "skinning"
            command = [
                self.python_bin,
                "-m",
                "torch.distributed.run",
                "--nproc_per_node=1",
                f"--master_port={int(master_port)}",
                "main.py",
                "--num_workers",
                "1",
                "--batch_size",
                "1",
                "--generate",
                "--save_skin_npy",
                "--pretrained_weights",
                self.skinning_ckpt,
                "--input_skel_folder",
                str(skeleton_dir),
                "--mesh_folder",
                str(mesh_dir),
                "--depth",
                str(self.skinning_depth),
                "--seed",
                str(int(seed)),
                "--save_folder",
                str(skin_dir),
            ]
            if post_filter:
                command.append("--post_filter")
            skinning_started = time.time()
            self._run(
                command,
                cwd=skinning_root,
                stage="skinning",
            )
            rig_path = skin_dir / "generate" / "avatar_skin.txt"
            _require_fresh_output(
                rig_path,
                "Puppeteer skinning",
                newer_than=skinning_started,
            )

            rig_text = rig_path.read_text(encoding="utf-8")
            skeleton_text = skeleton_path.read_text(encoding="utf-8")
            return {
                "rig_text": rig_text,
                "skeleton_text": skeleton_text,
                "mesh_obj_bytes": mesh_obj.read_bytes(),
                "joint_count": sum(
                    line.startswith("joints ") for line in rig_text.splitlines()
                ),
                "skin_vertex_count": sum(
                    line.startswith("skin ") for line in rig_text.splitlines()
                ),
                "seed": int(seed),
            }

    def infer_and_save(
        self,
        mesh: bytes,
        output_path: str,
        seed: int = 42,
        *,
        mesh_format: str = ".glb",
        skeleton_output_path: str | None = None,
        mesh_obj_output_path: str | None = None,
        post_filter: bool = True,
        master_port: int = 10009,
    ) -> dict[str, str | int | None]:
        """Run ``infer`` and save artifacts to caller-provided paths."""
        result = self.infer(
            mesh,
            mesh_format=mesh_format,
            seed=seed,
            post_filter=post_filter,
            master_port=master_port,
        )
        rig_path = _write_text(output_path, str(result["rig_text"]))
        skeleton_path = (
            _write_text(skeleton_output_path, str(result["skeleton_text"]))
            if skeleton_output_path
            else None
        )
        mesh_path = (
            _write_bytes(
                mesh_obj_output_path,
                bytes(result["mesh_obj_bytes"]),
            )
            if mesh_obj_output_path
            else None
        )
        return {
            "rig_path": rig_path,
            "skeleton_path": skeleton_path,
            "mesh_obj_path": mesh_path,
            "joint_count": int(result["joint_count"]),
            "skin_vertex_count": int(result["skin_vertex_count"]),
        }

    def _run(self, command: list[str], *, cwd: Path, stage: str) -> None:
        env = _subprocess_env(self.python_bin)
        env["CUDA_VISIBLE_DEVICES"] = str(self.gpu)
        env.setdefault("PYTHONHASHSEED", "0")
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
        )
        if self.verbose and proc.stdout:
            print(proc.stdout, end="")
        if proc.returncode == 0:
            return
        raise RuntimeError(
            f"Puppeteer {stage} subprocess failed.\n"
            f"Command: {subprocess.list2cmdline(command)}\n"
            f"Return code: {proc.returncode}\n"
            f"stdout tail:\n{(proc.stdout or '')[-2500:]}\n"
            f"stderr tail:\n{(proc.stderr or '')[-2500:]}"
        )


def _subprocess_env(python_bin: str) -> dict[str, str]:
    env = os.environ.copy()
    prefix = Path(python_bin).expanduser().resolve().parent.parent
    env["PATH"] = str(prefix / "bin") + os.pathsep + env.get("PATH", "")
    lib = prefix / "lib"
    if os.name != "nt" and lib.is_dir():
        env["LD_LIBRARY_PATH"] = (
            str(lib) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        )
    return env


def _normalise_mesh_format(value: str) -> str:
    ext = value.lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    if ext not in {".glb", ".obj", ".ply", ".stl"}:
        raise ValueError(
            "mesh_format must be .glb, .obj, .ply or .stl, "
            f"got {value!r}"
        )
    return ext


def _convert_to_obj(source: Path, output: Path) -> None:
    if source.suffix.lower() == ".obj":
        shutil.copyfile(source, output)
        return
    try:
        import trimesh
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Puppeteer mesh conversion requires trimesh in the controller "
            "environment."
        ) from exc
    loaded = trimesh.load(
        str(source),
        force="scene",
        process=False,
        maintain_order=True,
    )
    if isinstance(loaded, trimesh.Scene):
        to_geometry = getattr(loaded, "to_geometry", None)
        mesh = (
            to_geometry()
            if callable(to_geometry)
            else loaded.dump(concatenate=True)
        )
    else:
        mesh = loaded
    if mesh is None or getattr(mesh, "vertices", None) is None:
        raise ValueError(f"Could not extract mesh geometry from {source}")
    mesh.export(str(output), file_type="obj")


#: How far a fresh file's mtime may sit behind the moment the stage started.
#: `time.time()` and the filesystem's timestamps do not come from the same
#: clock, and a couple of milliseconds of disagreement is normal — measured at
#: ~2 ms here. The check exists to catch output left by a *previous* run, which
#: is seconds to hours old, so a second of slack costs it nothing.
_MTIME_TOLERANCE_SEC = 1.0


def _require_fresh_output(
    path: Path,
    label: str,
    *,
    newer_than: float,
) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"{label} produced no usable output: {path}")
    if path.stat().st_mtime + _MTIME_TOLERANCE_SEC < newer_than:
        raise RuntimeError(
            f"{label} output is stale and predates this run: {path}"
        )


def _write_text(path_like: str, value: str) -> str:
    path = Path(path_like)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return str(path)


def _write_bytes(path_like: str, value: bytes) -> str:
    path = Path(path_like)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return str(path)


__all__ = ["PuppeteerModel"]
