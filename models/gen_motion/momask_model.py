"""
MoMaskModel — text-to-human-motion generation through the official MoMask CLI.

Reference: https://github.com/EricGuo5513/momask-codes

The upstream repository owns top-level packages named ``models`` and ``utils``
and assumes its own working directory.  A subprocess prevents those namespaces
from colliding with 3AGameFactory while this wrapper exposes an in-memory API.
"""

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any


DEFAULT_T2M_NAME = "t2m_nlayer8_nhead6_ld384_ff1024_cdp0.1_rvq6ns"
DEFAULT_RES_NAME = "tres_nlayer8_ld384_ff1024_rvq6ns_cdp0.2_sw"
DEFAULT_VQ_NAME = "rvq_nq6_dc512_nc512_noshare_qdp0.2"


class MoMaskModel:
    """Thin wrapper around MoMask HumanML3D text-to-motion generation."""

    def __init__(
        self,
        model_path: str,
        device: str = "cuda",
        *,
        python_bin: str | None = None,
        gpu: int = 0,
        dataset_name: str = "t2m",
        name: str = DEFAULT_T2M_NAME,
        res_name: str = DEFAULT_RES_NAME,
        vq_name: str = DEFAULT_VQ_NAME,
        verbose: bool = False,
    ):
        self.model_path = str(model_path)
        self.device = str(device)
        self.python_bin = str(python_bin or sys.executable)
        self.gpu = int(gpu)
        self.dataset_name = str(dataset_name)
        self.name = str(name)
        self.res_name = str(res_name)
        self.vq_name = str(vq_name)
        self.verbose = bool(verbose)
        self._loaded = False

    def load(self) -> None:
        """Validate the MoMask source tree and selected checkpoints."""
        root = Path(self.model_path).expanduser().resolve()
        python_bin = Path(self.python_bin).expanduser().resolve()
        required = {
            "MoMask entrypoint": root / "gen_t2m.py",
            "MoMask masked transformer": (
                root / "checkpoints" / self.dataset_name / self.name / "opt.txt"
            ),
            "MoMask masked transformer weights": (
                root
                / "checkpoints"
                / self.dataset_name
                / self.name
                / "model"
                / "latest.tar"
            ),
            "MoMask residual transformer": (
                root
                / "checkpoints"
                / self.dataset_name
                / self.res_name
                / "opt.txt"
            ),
            "MoMask residual transformer weights": (
                root
                / "checkpoints"
                / self.dataset_name
                / self.res_name
                / "model"
                / "net_best_fid.tar"
            ),
            "MoMask RVQ options": (
                root
                / "checkpoints"
                / self.dataset_name
                / self.vq_name
                / "opt.txt"
            ),
            "MoMask RVQ weights": (
                root
                / "checkpoints"
                / self.dataset_name
                / self.vq_name
                / "model"
                / "net_best_fid.tar"
            ),
            "MoMask length estimator": (
                root
                / "checkpoints"
                / self.dataset_name
                / "length_estimator"
                / "model"
                / "finest.tar"
            ),
        }
        if not python_bin.is_file():
            raise RuntimeError(
                "MoMask Python executable does not exist: "
                f"{python_bin}. Set A3GF_MOMASK_PYTHON or pass "
                "--momask-python."
            )
        missing = [
            f"{label}: {path}"
            for label, path in required.items()
            if not path.is_file() or path.stat().st_size == 0
        ]
        if missing:
            raise RuntimeError(
                "MoMask runtime is incomplete.\n  - "
                + "\n  - ".join(missing)
                + "\nRun scripts/asset_env_setup/gen_motion/install.sh first."
            )
        self.model_path = str(root)
        self.python_bin = str(python_bin)
        self._loaded = True

    def unload(self) -> None:
        """Release wrapper state; subprocess exit already releases model VRAM."""
        self._loaded = False

    def infer(
        self,
        prompt: str,
        seed: int = 42,
        *,
        motion_length: int = 0,
        repeat_times: int = 1,
        cond_scale: float = 4.0,
        time_steps: int = 18,
        temperature: float = 1.0,
        use_ik: bool = True,
        in_place: bool = False,
        in_place_lock_height: bool = False,
    ) -> dict[str, Any]:
        """Generate a HumanML3D motion.

        Args:
            prompt: Natural-language motion description.
            seed: Reproducible MoMask sampling seed.
            motion_length: Number of 20 FPS poses, or zero for estimation.
            repeat_times: Number of samples requested from upstream.
            cond_scale: Masked-transformer classifier-free guidance.
            time_steps: Mask-generate iterations.
            temperature: Sampling temperature.
            use_ik: Prefer the foot-IK BVH as ``bvh_bytes``.
            in_place: Remove root X/Z translation from returned BVHs.
            in_place_lock_height: Also lock root vertical translation.

        Returns:
            A dictionary with selected/raw/IK BVH bytes, optional joints
            ``float32[nframe,22,3]``, optional preview MP4 bytes and ``fps=20``.
        """
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if motion_length < 0:
            raise ValueError("motion_length must be non-negative")
        if not self._loaded:
            self.load()

        ext = f"aaagf_{uuid.uuid4().hex}"
        root = Path(self.model_path)
        generation_root = root / "generation" / ext
        gpu_id = -1 if self.device.lower() == "cpu" else 0
        command = [
            self.python_bin,
            str(
                (
                    Path(__file__).with_name("momask_utils")
                    / "momask_entrypoint.py"
                ).resolve()
            ),
            "gen_t2m.py",
            "--gpu_id",
            str(gpu_id),
            "--dataset_name",
            self.dataset_name,
            "--name",
            self.name,
            "--res_name",
            self.res_name,
            "--ext",
            ext,
            "--text_prompt",
            prompt.strip(),
            "--motion_length",
            str(int(motion_length)),
            "--repeat_times",
            str(int(repeat_times)),
            "--cond_scale",
            str(float(cond_scale)),
            "--time_steps",
            str(int(time_steps)),
            "--temperature",
            str(float(temperature)),
            "--seed",
            str(int(seed)),
        ]
        env = _subprocess_env(self.python_bin)
        if self.device.lower() != "cpu":
            env["CUDA_VISIBLE_DEVICES"] = str(self.gpu)
        try:
            proc = subprocess.run(
                command,
                cwd=str(root),
                env=env,
                capture_output=True,
                text=True,
            )
            if self.verbose and proc.stdout:
                print(proc.stdout, end="")
            if proc.returncode != 0:
                raise RuntimeError(
                    "MoMask generation subprocess failed.\n"
                    f"Command: {subprocess.list2cmdline(command)}\n"
                    f"Return code: {proc.returncode}\n"
                    f"stdout tail:\n{(proc.stdout or '')[-2500:]}\n"
                    f"stderr tail:\n{(proc.stderr or '')[-2500:]}"
                )

            animation_dir = generation_root / "animations" / "0"
            joints_dir = generation_root / "joints" / "0"
            raw_path = _first(
                path
                for path in animation_dir.glob("*.bvh")
                if not path.name.endswith("_ik.bvh")
            )
            ik_path = _first(animation_dir.glob("*_ik.bvh"))
            if raw_path is None and ik_path is None:
                raise RuntimeError(
                    "MoMask returned successfully but produced no BVH under "
                    f"{animation_dir}"
                )

            raw_bytes = raw_path.read_bytes() if raw_path else None
            ik_bytes = ik_path.read_bytes() if ik_path else None
            if in_place:
                if raw_bytes is not None:
                    raw_bytes = _make_bvh_in_place(
                        raw_bytes,
                        lock_height=in_place_lock_height,
                    )
                if ik_bytes is not None:
                    ik_bytes = _make_bvh_in_place(
                        ik_bytes,
                        lock_height=in_place_lock_height,
                    )

            joints_path = _first(joints_dir.glob("*_ik.npy" if use_ik else "*.npy"))
            if joints_path is None:
                joints_path = _first(joints_dir.glob("*.npy"))
            joints = None
            if joints_path is not None:
                import numpy as np

                joints = np.load(joints_path).astype("float32", copy=False)
                if in_place and joints.ndim == 3 and joints.shape[1] > 0:
                    joints = joints.copy()
                    joints[:, :, 0] -= joints[:, 0:1, 0]
                    joints[:, :, 2] -= joints[:, 0:1, 2]
                    if in_place_lock_height:
                        delta = joints[:, 0:1, 1] - joints[0:1, 0:1, 1]
                        joints[:, :, 1] -= delta

            preview_path = _first(
                animation_dir.glob("*_ik.mp4" if use_ik else "*.mp4")
            )
            if preview_path is None:
                preview_path = _first(animation_dir.glob("*.mp4"))
            selected = (
                ik_bytes if use_ik and ik_bytes is not None else raw_bytes
            ) or ik_bytes
            return {
                "bvh_bytes": selected,
                "raw_bvh_bytes": raw_bytes,
                "ik_bvh_bytes": ik_bytes,
                "joints": joints,
                "preview_mp4_bytes": (
                    preview_path.read_bytes() if preview_path else None
                ),
                "fps": 20,
                "seed": int(seed),
            }
        finally:
            shutil.rmtree(generation_root, ignore_errors=True)

    def infer_and_save(
        self,
        prompt: str,
        output_path: str,
        seed: int = 42,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run ``infer`` and save the selected BVH to ``output_path``."""
        result = self.infer(prompt, seed=seed, **kwargs)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(bytes(result["bvh_bytes"]))
        return {**result, "motion_bvh_path": str(output)}


def _first(paths: Any) -> Path | None:
    values = sorted(paths)
    return values[0] if values else None


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


def _make_bvh_in_place(data: bytes, *, lock_height: bool) -> bytes:
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    motion_index = next(
        (i for i, line in enumerate(lines) if line.strip() == "MOTION"),
        None,
    )
    channel_line = next(
        (line.strip() for line in lines[: motion_index or 0] if line.strip().startswith("CHANNELS")),
        None,
    )
    if motion_index is None or channel_line is None:
        return data
    parts = channel_line.split()
    count = int(parts[1])
    names = parts[2 : 2 + count]
    columns = {
        name: names.index(name)
        for name in ("Xposition", "Yposition", "Zposition")
        if name in names
    }
    frame_time_index = next(
        (
            i
            for i in range(motion_index + 1, len(lines))
            if lines[i].strip().lower().startswith("frame time:")
        ),
        None,
    )
    if frame_time_index is None:
        return data
    locked_y: str | None = None
    for index in range(frame_time_index + 1, len(lines)):
        values = lines[index].split()
        if len(values) < count:
            continue
        for axis in ("Xposition", "Zposition"):
            if axis in columns:
                values[columns[axis]] = "0.000000"
        if lock_height and "Yposition" in columns:
            locked_y = locked_y or values[columns["Yposition"]]
            values[columns["Yposition"]] = locked_y
        lines[index] = " ".join(values)
    return ("\n".join(lines) + "\n").encode("utf-8")


__all__ = ["MoMaskModel"]
