"""MiniMaxH3Model — MP4 generation through MiniMax API or local INT8 weights.

References:
    https://platform.minimax.io/docs/guides/video-generation
    https://docs.comfy.org/tutorials/video/minimax/minimax-h3
    https://huggingface.co/Comfy-Org/MiniMax-H3

Local prerequisites:
    ComfyUI native MiniMax H3 nodes, CUDA PyTorch and the official quantized
    component weights.
    Install with ``bash scripts/asset_env_setup/cg_video/minimax_h3_install.sh``.

CONTRACT DEVIATIONS (only the ``runtime="api"`` route; the local route follows
                     model_require.md directly; see
                     agent_skills/develop_harness/api_model_require.md):
  C1  R2.1/R2.2 -> R9.1  API ``model_path`` is a provider model version id.
  C2  R2.3      -> R9.2  API accepts and ignores ``device``; local honours it.
  C3  R3.6      -> R9.3  API uses no torch context; local uses inference_mode.
  C4  R4.1-R4.3 -> R9.4  API unload closes its HTTP session.
  C5  R3.3/R3.4 -> R9.5  Hailuo API accepts but ignores seed; server-side
                         reproducibility is not guaranteed. Local forwards it.
  C6  R3.1      -> R9.6  API submit/poll/retrieve/download is hidden by infer.
  C7  R1.2              infer_and_save writes only the caller-provided path.
  C8  (new)     -> R9.8  API calls use the billed-response cache.
  C9  (new)     -> R9.9  API retries use shared terminal/retryable classes.

Usage:
    model = MiniMaxH3Model(model_path="Comfy-Org/MiniMax-H3", runtime="local")
    data = model.infer(request)  # encoded MP4 bytes
"""

from __future__ import annotations

import gc
import io
import logging
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from models.common import cloud_api
from models.gen_cg_video.utils import VideoGenerationInput, VideoGenerationMode

logger = logging.getLogger(__name__)

#: `.env` 变量名；URL 由用户填写在 `.env` 里，代码不保留 URL 字面量（R9.7）。
ENV_KEY = "MINIMAX_API_KEY"
ENV_BASE = "MINIMAX_API_BASE"
DEFAULT_MODEL = "MiniMax-Hailuo-2.3"
DEFAULT_LOCAL_MODEL = "Comfy-Org/MiniMax-H3"
MODEL_ALIASES = {
    "minimax-h3": DEFAULT_MODEL,
    "hailuo-2.3": DEFAULT_MODEL,
    "minimax-hailuo-2.3": DEFAULT_MODEL,
    "minimax-h3-fast": "MiniMax-Hailuo-2.3-Fast",
    "hailuo-2.3-fast": "MiniMax-Hailuo-2.3-Fast",
}
DONE_STATES = ("success",)
FAILED_STATES = ("fail", "failed")
SUPPORTED_FORMATS = ("mp4",)
FL2VA_MODEL = (
    "diffusion_models/"
    "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
)
REF2VA_MODEL = (
    "diffusion_models/"
    "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
)
TEXT_ENCODER = "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "vae/minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "vae/minimax_h3_audio_vae_fp32.safetensors"
COMMON_LOCAL_FILES = (TEXT_ENCODER, VIDEO_VAE, AUDIO_VAE)
LOCAL_WEIGHT_FILES = (FL2VA_MODEL, REF2VA_MODEL, *COMMON_LOCAL_FILES)


def _partition_for_mode(mode: VideoGenerationMode) -> str:
    return (
        REF2VA_MODEL
        if mode is VideoGenerationMode.REFERENCE_TO_VIDEO
        else FL2VA_MODEL
    )


def _required_files_for_mode(mode: VideoGenerationMode) -> tuple[str, ...]:
    """Return the exact official files for one native ComfyUI workflow."""
    return (_partition_for_mode(mode), *COMMON_LOCAL_FILES)


def _aligned_frame_count(duration_sec: float) -> int:
    """Apply the official 17k+5 frame grid at the model's native 24 fps."""
    frames = max(5, round(float(duration_sec) * 24))
    return frames + (5 - frames % 17) % 17


@contextmanager
def _comfy_import_argv(device: str):
    """Keep ComfyUI's CLI parser from consuming 3AGameFactory runner flags."""
    previous = sys.argv
    argv = [previous[0] if previous else "gamefactory3a"]
    normalized = str(device).strip().lower()
    if normalized == "cpu":
        argv.append("--cpu")
    elif normalized.startswith("cuda:"):
        device_id = normalized.partition(":")[2]
        if not device_id.isdigit():
            raise ValueError(f"invalid CUDA device {device!r}; expected cuda:N")
        argv.extend(("--cuda-device", device_id))
    sys.argv = argv
    try:
        yield
    finally:
        sys.argv = previous


class _ComfyMiniMaxRuntime:
    """Direct adapter around ComfyUI's native MiniMax H3 workflow nodes."""

    def __init__(self, *, comfyui_path: Path, device: str):
        if not comfyui_path.is_dir():
            raise FileNotFoundError(
                f"ComfyUI source was not found at {comfyui_path}. Run "
                "scripts/asset_env_setup/cg_video/minimax_h3_install.sh or set COMFYUI_PATH."
            )
        native_nodes = comfyui_path / "comfy_extras/nodes_minimax_h3.py"
        if not native_nodes.is_file():
            raise FileNotFoundError(
                f"{comfyui_path} does not contain native MiniMax H3 nodes. "
                "Install a current ComfyUI release with "
                "scripts/asset_env_setup/cg_video/minimax_h3_install.sh."
            )

        value = str(comfyui_path.resolve())
        if value not in sys.path:
            sys.path.insert(0, value)

        try:
            with _comfy_import_argv(device):
                import torch
                import folder_paths
                import nodes
                from comfy_extras.nodes_audio import VAEDecodeAudio
                from comfy_extras.nodes_custom_sampler import (
                    BasicGuider,
                    BasicScheduler,
                    KSamplerSelect,
                    RandomNoise,
                    SamplerCustomAdvanced,
                )
                from comfy_extras.nodes_minimax_h3 import (
                    MiniMaxH3ImageToVideo,
                    MiniMaxH3ReferenceToVideo,
                )
                from comfy_extras.nodes_video import CreateVideo
        except ImportError as exc:
            raise RuntimeError(
                "The local MiniMax H3 runtime is incomplete. Install current "
                "ComfyUI and its requirements with "
                "scripts/asset_env_setup/cg_video/minimax_h3_install.sh."
            ) from exc

        self.torch = torch
        self.folder_paths = folder_paths
        self.nodes = nodes
        self.VAEDecodeAudio = VAEDecodeAudio
        self.BasicGuider = BasicGuider
        self.BasicScheduler = BasicScheduler
        self.KSamplerSelect = KSamplerSelect
        self.RandomNoise = RandomNoise
        self.SamplerCustomAdvanced = SamplerCustomAdvanced
        self.MiniMaxH3ImageToVideo = MiniMaxH3ImageToVideo
        self.MiniMaxH3ReferenceToVideo = MiniMaxH3ReferenceToVideo
        self.CreateVideo = CreateVideo
        self._models: dict[Path, Any] = {}
        self._clip_path: Optional[Path] = None
        self._clip = None
        self._video_vae_path: Optional[Path] = None
        self._video_vae = None
        self._audio_vae_path: Optional[Path] = None
        self._audio_vae = None

    def image(self, value):
        """PIL RGB image -> Comfy IMAGE tensor [B,H,W,C], float32 0..1."""
        import numpy as np

        rgb = value.convert("RGB")
        array = np.asarray(rgb, dtype=np.float32) / 255.0
        return self.torch.from_numpy(array).unsqueeze(0)

    @staticmethod
    def _outputs(value) -> tuple[Any, ...]:
        result = getattr(value, "result", value)
        if isinstance(result, tuple):
            return result
        if isinstance(result, list):
            return tuple(result)
        try:
            return tuple(result)
        except TypeError as exc:
            raise RuntimeError(
                "Unexpected ComfyUI NodeOutput returned by MiniMax H3"
            ) from exc

    @classmethod
    def _first(cls, value):
        return cls._outputs(value)[0]

    def _register_files(self, files: dict[str, Path]) -> None:
        categories = {
            "diffusion_model": "diffusion_models",
            "text_encoder": "text_encoders",
            "video_vae": "vae",
            "audio_vae": "vae",
        }
        for key, category in categories.items():
            self.folder_paths.add_model_folder_path(
                category,
                str(files[key].parent),
                is_default=True,
            )

    def _load_components(self, files: dict[str, Path]):
        """Load exact official files with native loaders and quant metadata."""
        self._register_files(files)
        diffusion_path = files["diffusion_model"]
        if diffusion_path not in self._models:
            # ``default`` is required: forcing an fp8 dtype discards the
            # int8/convrot checkpoint's native quantization contract.
            self._models[diffusion_path] = self._first(
                self.nodes.UNETLoader().load_unet(
                    diffusion_path.name,
                    weight_dtype="default",
                )
            )
        if self._clip_path != files["text_encoder"]:
            self._clip = self._first(
                self.nodes.CLIPLoader().load_clip(
                    files["text_encoder"].name,
                    type="minimax",
                    device="default",
                )
            )
            self._clip_path = files["text_encoder"]
        if self._video_vae_path != files["video_vae"]:
            self._video_vae = self._first(
                self.nodes.VAELoader().load_vae(files["video_vae"].name)
            )
            self._video_vae_path = files["video_vae"]
        if self._audio_vae_path != files["audio_vae"]:
            self._audio_vae = self._first(
                self.nodes.VAELoader().load_vae(files["audio_vae"].name)
            )
            self._audio_vae_path = files["audio_vae"]
        return (
            self._models[diffusion_path],
            self._clip,
            self._video_vae,
            self._audio_vae,
        )

    def generate(
        self,
        request: VideoGenerationInput,
        output,
        *,
        files: dict[str, Path],
        width: int,
        height: int,
        fps: float,
        steps: int,
        scheduler: str,
        sampler_name: str,
        ref_image_size: str,
    ) -> None:
        model, clip, video_vae, audio_vae = self._load_components(files)
        frame_count = _aligned_frame_count(request.duration_sec)
        if request.mode is VideoGenerationMode.REFERENCE_TO_VIDEO:
            images = {
                f"ref_image_{index}": self.image(image)
                for index, image in enumerate(request.reference_images)
            }
            positive, latent = self._outputs(
                self.MiniMaxH3ReferenceToVideo.execute(
                    clip=clip,
                    vae=video_vae,
                    audio_vae=audio_vae,
                    prompt=request.prompt,
                    width=int(width),
                    height=int(height),
                    length=frame_count,
                    ref_images=images,
                    ref_videos=None,
                    ref_video_audios=None,
                    ref_audios=None,
                    ref_image_size=ref_image_size,
                )
            )
        else:
            first = (
                self.image(request.first_frame)
                if request.first_frame is not None
                else None
            )
            last = (
                self.image(request.last_frame)
                if request.last_frame is not None
                else None
            )
            positive, latent = self._outputs(
                self.MiniMaxH3ImageToVideo.execute(
                    clip=clip,
                    vae=video_vae,
                    prompt=request.prompt,
                    width=int(width),
                    height=int(height),
                    length=frame_count,
                    first_frame=first,
                    last_frame=last,
                )
            )

        noise = self._first(self.RandomNoise.execute(int(request.seed)))
        guider = self._first(self.BasicGuider.execute(model, positive))
        sampler = self._first(self.KSamplerSelect.execute(sampler_name))
        sigmas = self._first(
            self.BasicScheduler.execute(model, scheduler, int(steps), 1.0)
        )
        sampled = self._first(
            self.SamplerCustomAdvanced.execute(
                noise,
                guider,
                sampler,
                sigmas,
                latent,
            )
        )
        frames = self.nodes.VAEDecode().decode(video_vae, sampled)[0]
        audio = self._first(self.VAEDecodeAudio.execute(audio_vae, sampled))
        video = self._first(
            self.CreateVideo.execute(
                images=frames,
                fps=float(fps),
                audio=audio,
                bit_depth=8,
            )
        )
        video.save_to(output)

    def unload(self) -> None:
        try:
            import comfy.model_management as model_management

            model_management.unload_all_models()
            model_management.soft_empty_cache()
        except (ImportError, AttributeError):
            if getattr(self.torch, "cuda", None) is not None:
                self.torch.cuda.empty_cache()
        self._models.clear()
        self._clip = None
        self._video_vae = None
        self._audio_vae = None


class MiniMaxH3Model:
    """Route one CG-video model slot to the API or local quantized runtime.

    Args:
        model_path: API version, local weight directory, complete ComfyUI model
            tree, or Hugging Face quantized-weight repo id.
        device: Local torch device. Accepted and ignored by the API route.
        runtime: ``auto``, ``api`` or ``local``.
        comfyui_path: ComfyUI source directory for local execution.
        hf_cache_dir: Optional Hugging Face snapshot cache override.
        hf_revision: Optional Hugging Face revision; defaults to the repo's
            current default revision.
        local_files_only: Refuse network downloads when true.
        width, height, fps: Local output settings. MiniMax H3 is fixed at 24fps.
        steps, scheduler, sampler_mode: Native ComfyUI sampling settings.
            The official workflow defaults are 20, ``simple`` and
            ``res_multistep``.
        api_key: Explicit key; otherwise ``MINIMAX_API_KEY`` is read lazily.
        timeout, poll_interval, max_retries: API task/retry settings.
        cache_dir: API billed-response cache directory.
        output_format: Encoded container; currently ``mp4`` only.
        resolution, prompt_optimizer, fast_pretreatment: Hailuo API settings.
        api_base, http_timeout: API transport overrides.
        verbose: Enable progress/log output where supported.
    """

    PROVIDER = "minimax-h3"
    API_SUPPORTED_MODES = frozenset(
        {
            VideoGenerationMode.TEXT_TO_VIDEO,
            VideoGenerationMode.FIRST_FRAME_TO_VIDEO,
        }
    )
    LOCAL_SUPPORTED_MODES = frozenset(VideoGenerationMode)

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        device: str = "cuda",
        *,
        runtime: str = "auto",
        comfyui_path: Optional[str] = None,
        hf_cache_dir: Optional[str] = None,
        hf_revision: Optional[str] = None,
        local_files_only: bool = False,
        width: int = 864,
        height: int = 480,
        fps: float = 24.0,
        steps: int = 20,
        scheduler: str = "simple",
        sampler_mode: str = "res_multistep",
        ref_image_size: str = "match",
        api_key: Optional[str] = None,
        timeout: int = 1800,
        poll_interval: float = 10.0,
        max_retries: int = 3,
        cache_dir: Optional[str] = None,
        output_format: str = "mp4",
        resolution: str = "768P",
        prompt_optimizer: bool = True,
        fast_pretreatment: bool = False,
        api_base: Optional[str] = None,
        http_timeout: int = 60,
        verbose: bool = False,
    ):
        requested_model = str(model_path)
        normalized_runtime = str(runtime).strip().lower()
        if normalized_runtime not in {"auto", "api", "local"}:
            raise ValueError("runtime must be 'auto', 'api', or 'local'")
        if normalized_runtime == "auto":
            alias = requested_model.lower()
            normalized_runtime = (
                "api"
                if alias in MODEL_ALIASES or alias.startswith("minimax-hailuo-")
                else "local"
            )

        if normalized_runtime == "local" and (
            requested_model == DEFAULT_MODEL
            or requested_model.lower() == "minimax-h3"
        ):
            requested_model = DEFAULT_LOCAL_MODEL
        self.runtime = normalized_runtime
        # [CONTRACT-DEVIATION C1] Only the API route treats model_path as a
        # provider version id; the local route keeps the R2.1 weight location.
        # [CONTRACT-DEVIATION C2] device is ignored only by the API route.
        self.model_path = (
            MODEL_ALIASES.get(requested_model.lower(), requested_model)
            if self.runtime == "api"
            else requested_model
        )
        self.device = device
        repo_root = Path(__file__).resolve().parents[2]
        self.comfyui_path = Path(
            comfyui_path
            or os.environ.get("COMFYUI_PATH")
            or repo_root / ".models/src/ComfyUI"
        ).expanduser()
        self.hf_cache_dir = hf_cache_dir
        self.hf_revision = hf_revision
        self.local_files_only = bool(local_files_only)
        self.width = int(width)
        self.height = int(height)
        self.fps = float(fps)
        self.steps = int(steps)
        self.scheduler = str(scheduler)
        self.sampler_mode = str(sampler_mode)
        self.ref_image_size = str(ref_image_size)

        self.api_key = api_key
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self.cache_dir = cache_dir
        self.output_format = str(output_format).lower().lstrip(".")
        self.resolution = str(resolution).upper()
        self.prompt_optimizer = bool(prompt_optimizer)
        self.fast_pretreatment = bool(fast_pretreatment)
        # [R9.7] 只有 api 运行方式需要它；在首次调用时才解析，使构造函数既不要求
        # 凭证也不触网。端点由用户在 .env 里配置，代码不含任何 URL 示例。
        self.api_base = api_base
        self.http_timeout = http_timeout
        self.verbose = verbose

        if self.output_format not in SUPPORTED_FORMATS:
            raise ValueError("MiniMaxH3Model currently writes MP4 only")
        if self.runtime == "api" and self.resolution not in ("768P", "1080P"):
            raise ValueError("MiniMax-Hailuo-2.3 resolution must be 768P or 1080P")
        if self.runtime == "local":
            if self.width <= 0 or self.height <= 0:
                raise ValueError("local width and height must be positive")
            if self.width % 32:
                raise ValueError("local width must be divisible by 32")
            if self.height % 32:
                raise ValueError("local height must be divisible by 32")
            if self.fps != 24.0:
                raise ValueError("local MiniMax H3 fps is fixed at 24")
            if self.steps < 1:
                raise ValueError("steps must be positive")
            if self.sampler_mode not in {"euler", "res_multistep"}:
                raise ValueError("sampler_mode must be 'euler' or 'res_multistep'")
            if self.ref_image_size not in {"match", "max"}:
                raise ValueError("ref_image_size must be 'match' or 'max'")

        self._client: Optional[cloud_api.CloudAPIClient] = None
        self._local_runtime: Optional[_ComfyMiniMaxRuntime] = None
        self._local_files: dict[str, dict[str, Path]] = {}
        # [CONTRACT-DEVIATION C8] API calls are billed and therefore cached.
        self._cache = cloud_api.ResponseCache(cache_dir, self.PROVIDER)
        self.last_call_info: dict[str, Any] = {}

    @property
    def supported_modes(self):
        """Capabilities of the selected runtime, not a backend-wide guess."""
        return (
            self.API_SUPPORTED_MODES
            if self.runtime == "api"
            else self.LOCAL_SUPPORTED_MODES
        )

    @property
    def client(self) -> cloud_api.CloudAPIClient:
        """返回惰性完成鉴权的 API 客户端。"""
        if self.runtime != "api":
            raise RuntimeError("the HTTP client is only available in api runtime")
        if self._client is None:
            key = cloud_api.require_api_key(
                self.api_key, ENV_KEY, who="MiniMaxH3Model"
            )
            base = cloud_api.require_api_base(
                self.api_base, ENV_BASE, who="MiniMaxH3Model"
            )
            self._client = cloud_api.CloudAPIClient(
                base,
                key,
                timeout=self.http_timeout,
                # [CONTRACT-DEVIATION C9] Shared HTTP retry classification.
                max_retries=self.max_retries,
            )
        return self._client

    @staticmethod
    def _is_local_path(value: str) -> bool:
        path = Path(value).expanduser()
        return path.exists() or value.startswith(('.', '/', '~'))

    def _snapshot_download(
        self,
        repo_id: str,
        *,
        mode: VideoGenerationMode,
    ) -> Path:
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise RuntimeError(
                "huggingface_hub is required to download MiniMax H3 weights; "
                "run scripts/asset_env_setup/cg_video/minimax_h3_install.sh"
            ) from exc
        kwargs: dict[str, Any] = {
            "repo_id": repo_id,
            "cache_dir": self.hf_cache_dir,
            "local_files_only": self.local_files_only,
            # This exact list is intentional. The Comfy-Org repository holds
            # many full-precision and quantized variants totalling hundreds of
            # GB; an unfiltered snapshot download is never acceptable here.
            "allow_patterns": list(_required_files_for_mode(mode)),
        }
        if self.hf_revision:
            kwargs["revision"] = self.hf_revision
        return Path(snapshot_download(**kwargs)).resolve()

    def _resolve_source(
        self,
        value: str,
        *,
        mode: VideoGenerationMode,
    ) -> Path:
        path = Path(value).expanduser()
        if path.exists():
            if not path.is_dir():
                raise ValueError(f"MiniMax H3 model source must be a directory: {path}")
            return path.resolve()
        if self._is_local_path(value):
            raise FileNotFoundError(f"MiniMax H3 model directory does not exist: {path}")
        if "/" not in value:
            raise ValueError(
                f"{value!r} is neither a local directory nor a Hugging Face repo id"
            )
        return self._snapshot_download(value, mode=mode)

    @staticmethod
    def _find_local_file(root: Path, relative_path: str) -> Optional[Path]:
        """Find one official component in HF or ComfyUI directory layouts."""
        relative = Path(relative_path)
        candidates = [
            root / relative,
            root / "models" / relative,
            root / "ComfyUI" / "models" / relative,
            root / relative.name,
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()

        # A caller may point at a parent such as /models/MiniMax-H3. Accept a
        # uniquely named official file below it, but reject ambiguity.
        matches = list(root.rglob(relative.name))
        if len(matches) == 1 and matches[0].is_file():
            return matches[0].resolve()
        return None

    @classmethod
    def _collect_local_files(
        cls,
        root: Path,
        mode: VideoGenerationMode,
    ) -> dict[str, Path]:
        required = {
            "diffusion_model": _partition_for_mode(mode),
            "text_encoder": TEXT_ENCODER,
            "video_vae": VIDEO_VAE,
            "audio_vae": AUDIO_VAE,
        }
        files: dict[str, Path] = {}
        missing: list[str] = []
        for key, relative_path in required.items():
            found = cls._find_local_file(root, relative_path)
            if found is None:
                missing.append(relative_path)
            else:
                files[key] = found
        if missing:
            raise FileNotFoundError(
                f"MiniMax H3 local files are incomplete for {mode.value} below "
                f"{root}; missing: {', '.join(missing)}"
            )
        return files

    def _prepare_local_files(
        self,
        mode: VideoGenerationMode,
    ) -> dict[str, Path]:
        partition = _partition_for_mode(mode)
        if partition not in self._local_files:
            # Hugging Face downloads are mode-lazy: FL2VA and Ref2VA are never
            # downloaded together unless the caller actually uses both modes.
            source = self._resolve_source(self.model_path, mode=mode)
            self._local_files[partition] = self._collect_local_files(source, mode)
        return self._local_files[partition]

    def _ensure_local_runtime(self) -> _ComfyMiniMaxRuntime:
        if self._local_runtime is None:
            self._local_runtime = _ComfyMiniMaxRuntime(
                comfyui_path=self.comfyui_path,
                device=self.device,
            )
        return self._local_runtime

    def unload(self) -> None:
        """Release API/local resources; safe before use and safe repeatedly."""
        # [CONTRACT-DEVIATION C4] API owns an HTTP session rather than model
        # memory. Local execution releases its ComfyUI models below.
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._local_runtime is not None:
            self._local_runtime.unload()
            self._local_runtime = None
            gc.collect()

    close = unload

    @staticmethod
    def _application_error(response: dict[str, Any]) -> cloud_api.CloudAPIError:
        base = response.get("base_resp")
        message = base.get("status_msg") if isinstance(base, dict) else response
        classified = cloud_api.classify_http_error(400, response)
        return type(classified)(f"MiniMax API error: {message}", payload=response)

    @classmethod
    def _unwrap(cls, response: Any) -> dict[str, Any]:
        if not isinstance(response, dict):
            raise cloud_api.CloudAPIError(
                f"unexpected MiniMax response type {type(response).__name__}: {response!r}"
            )
        base = response.get("base_resp")
        if isinstance(base, dict) and base.get("status_code") not in (None, 0, "0"):
            raise cls._application_error(response)
        return response

    def _validate_request(self, request: VideoGenerationInput) -> None:
        if not isinstance(request, VideoGenerationInput):
            raise TypeError(
                "request must be models.gen_cg_video.VideoGenerationInput, "
                f"not {type(request).__name__}"
            )
        supported = self.supported_modes
        if request.mode not in supported:
            names = ", ".join(sorted(mode.value for mode in supported))
            raise NotImplementedError(
                f"{type(self).__name__} runtime={self.runtime!r} does not support "
                f"{request.mode.value}; supported modes: {names}"
            )
        if self.runtime == "api":
            if request.duration_sec not in (6, 10):
                raise ValueError("MiniMax-Hailuo-2.3 duration_sec must be 6 or 10")
            if self.resolution == "1080P" and request.duration_sec != 6:
                raise ValueError("MiniMax-Hailuo-2.3 supports 1080P only for 6 seconds")
        elif request.duration_sec > 15:
            raise ValueError("local MiniMax H3 duration_sec must not exceed 15 seconds")
        if self.runtime == "local" and request.mode is VideoGenerationMode.REFERENCE_TO_VIDEO:
            if len(request.reference_images) > 9:
                raise ValueError("local MiniMax H3 supports at most 9 reference images")

    def _build_payload(
        self, request: VideoGenerationInput, provider_kwargs: dict[str, Any]
    ) -> tuple[dict[str, Any], Optional[bytes]]:
        payload: dict[str, Any] = {
            "model": self.model_path,
            "prompt": request.prompt,
            "duration": int(request.duration_sec),
            "resolution": self.resolution,
            "prompt_optimizer": self.prompt_optimizer,
            "fast_pretreatment": self.fast_pretreatment,
        }
        # [CONTRACT-DEVIATION C5] Hailuo 2.3 exposes no seed request field.
        first_png = None
        if request.mode is VideoGenerationMode.FIRST_FRAME_TO_VIDEO:
            assert request.first_frame is not None
            first_png = cloud_api.image_to_png_bytes(request.first_frame)
            payload["first_frame_image"] = cloud_api.image_to_data_uri(first_png)
        payload.update(provider_kwargs)
        return payload, first_png

    def _cache_descriptor(self, request, payload, first_png):
        safe_payload = dict(payload)
        safe_payload.pop("first_frame_image", None)
        return {
            "provider": self.PROVIDER,
            "runtime": "api",
            "mode": request.mode.value,
            "payload": safe_payload,
            "first_frame_sha256": (
                cloud_api.bytes_hash(first_png) if first_png is not None else None
            ),
            "output_format": self.output_format,
        }

    def _submit(self, payload: dict[str, Any]) -> str:
        response = self._unwrap(
            self.client.request("POST", "/v1/video_generation", json_body=payload)
        )
        task_id = response.get("task_id")
        if not task_id:
            raise cloud_api.CloudAPIError(
                f"MiniMax accepted the request but returned no task_id: {response}",
                payload=response,
            )
        return str(task_id)

    def _fetch_task(self, task_id: str) -> dict[str, Any]:
        return self._unwrap(
            self.client.request(
                "GET", "/v1/query/video_generation", params={"task_id": task_id}
            )
        )

    def _wait(self, task_id: str, *, verbose: bool) -> dict[str, Any]:
        return cloud_api.poll_task(
            lambda: self._fetch_task(task_id),
            task_id=task_id,
            timeout=self.timeout,
            poll_interval=self.poll_interval,
            done_states=DONE_STATES,
            failed_states=FAILED_STATES,
            verbose=verbose,
        )

    def _retrieve_url(self, file_id: str) -> tuple[str, dict[str, Any]]:
        response = self._unwrap(
            self.client.request("GET", "/v1/files/retrieve", params={"file_id": file_id})
        )
        file_info = response.get("file")
        url = file_info.get("download_url") if isinstance(file_info, dict) else None
        if not isinstance(url, str) or not url.startswith("http"):
            raise cloud_api.CloudAPIError(
                f"MiniMax file {file_id} has no download_url: {response}",
                payload=response,
            )
        return url, file_info

    def _infer_api(self, request, provider_kwargs) -> bytes:
        # [CONTRACT-DEVIATION C3] HTTP inference deliberately has no torch
        # context. Local inference is wrapped in torch.inference_mode().
        verbose = bool(provider_kwargs.pop("verbose", self.verbose))
        payload, first_png = self._build_payload(request, provider_kwargs)
        cache_key = cloud_api.request_hash(
            self._cache_descriptor(request, payload, first_png)
        )
        cached = self._cache.get(cache_key, ext=self.output_format)
        if cached is not None:
            self.last_call_info = {
                "provider": self.PROVIDER,
                "runtime": "api",
                "model": self.model_path,
                "mode": request.mode.value,
                "cached": True,
                "cache_key": cache_key,
                "bytes": len(cached),
                "seed_ignored": request.seed,
            }
            return cached

        t0 = time.time()
        # [CONTRACT-DEVIATION C6] Hide the asynchronous provider lifecycle.
        task_id = self._submit(payload)
        task = self._wait(task_id, verbose=verbose)
        file_id = task.get("file_id")
        if not file_id:
            raise cloud_api.CloudAPIError(
                f"MiniMax task {task_id} succeeded without file_id: {task}",
                task_id=task_id,
                payload=task,
            )
        url, file_info = self._retrieve_url(str(file_id))
        data = self.client.download(url)
        elapsed = time.time() - t0
        self.last_call_info = {
            "provider": self.PROVIDER,
            "runtime": "api",
            "model": self.model_path,
            "mode": request.mode.value,
            "task_id": task_id,
            "file_id": str(file_id),
            "elapsed_sec": round(elapsed, 2),
            "bytes": len(data),
            "cached": False,
            "width": task.get("video_width"),
            "height": task.get("video_height"),
            "provider_bytes": file_info.get("bytes"),
            "seed_ignored": request.seed,
        }
        self._cache.put(cache_key, data, self.last_call_info, ext=self.output_format)
        logger.info(
            "[minimax-h3/api] task=%s mode=%s elapsed=%.1fs bytes=%d",
            task_id,
            request.mode.value,
            elapsed,
            len(data),
        )
        return data

    def _infer_local(self, request, output, provider_kwargs) -> None:
        verbose = bool(provider_kwargs.pop("verbose", self.verbose))
        if provider_kwargs:
            unknown = ", ".join(sorted(provider_kwargs))
            raise TypeError(f"unsupported local MiniMax H3 inference options: {unknown}")
        files = self._prepare_local_files(request.mode)
        runtime = self._ensure_local_runtime()
        t0 = time.time()
        with runtime.torch.inference_mode():
            runtime.generate(
                request,
                output,
                files=files,
                width=self.width,
                height=self.height,
                fps=self.fps,
                steps=self.steps,
                scheduler=self.scheduler,
                sampler_name=self.sampler_mode,
                ref_image_size=self.ref_image_size,
            )
        elapsed = time.time() - t0
        byte_count = (
            output.getbuffer().nbytes
            if isinstance(output, io.BytesIO)
            else Path(output).stat().st_size
        )
        self.last_call_info = {
            "provider": self.PROVIDER,
            "runtime": "local",
            "model": self.model_path,
            "diffusion_model": str(files["diffusion_model"]),
            "text_encoder": str(files["text_encoder"]),
            "video_vae": str(files["video_vae"]),
            "audio_vae": str(files["audio_vae"]),
            "mode": request.mode.value,
            "elapsed_sec": round(elapsed, 2),
            "bytes": byte_count,
            "cached": False,
            "seed": request.seed,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "frame_count": _aligned_frame_count(request.duration_sec),
            "steps": self.steps,
            "scheduler": self.scheduler,
            "sampler": self.sampler_mode,
        }
        if verbose:
            logger.info(
                "[minimax-h3/local] mode=%s elapsed=%.1fs bytes=%d",
                request.mode.value,
                elapsed,
                byte_count,
            )

    def infer(self, request: VideoGenerationInput, **provider_kwargs: Any) -> bytes:
        """Generate one encoded MP4 in memory.

        Args:
            request: Provider-neutral prompt, mode, image inputs and seed.
            **provider_kwargs: API request overrides; local accepts ``verbose``.

        Returns:
            Encoded MP4 bytes.
        """
        self._validate_request(request)
        if self.runtime == "api":
            return self._infer_api(request, dict(provider_kwargs))
        buffer = io.BytesIO()
        self._infer_local(request, buffer, dict(provider_kwargs))
        return buffer.getvalue()

    def infer_and_save(
        self,
        request: VideoGenerationInput,
        output_path: str,
        **provider_kwargs: Any,
    ) -> str:
        """Generate directly at a caller-owned path.

        Args:
            request: Provider-neutral prompt, mode, image inputs and seed.
            output_path: Destination selected by the operator/caller.
            **provider_kwargs: API request overrides; local accepts ``verbose``.

        Returns:
            ``output_path`` as ``str``.
        """
        # [CONTRACT-DEVIATION C7] The model never derives an artifact path.
        if not output_path:
            raise ValueError("output_path is required (model_require.md R1.2)")
        self._validate_request(request)
        if self.runtime == "local":
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            self._infer_local(request, str(out), dict(provider_kwargs))
            return str(out)
        data = self._infer_api(request, dict(provider_kwargs))
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return str(out)
