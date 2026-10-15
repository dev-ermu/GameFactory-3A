"""Tripo3D 三维建模封装（官方 SDK）。

Tripo 提供官方 Python 包 `tripo3d`，其接口是异步的。本项目对外暴露的
`request()` 按规范 R5 保持同步，因此这里用 `asyncio.run` 把一次完整的
"提交任务 → 轮询 → 下载"包在同一个事件循环里跑完，调用方感知不到异步。

Base URL 由用户在 `.env` 中填写，原样传给 SDK（规范 R6.4）。

参考来源：https://developers.tripo3d.com/zh/docs/sdk

服务端生成结果的可复现性无法保证（规范 R3.4）：`seed` 会透传给服务端，
但服务端不承诺确定性输出。
"""

import asyncio

import requests
from tripo3d import TripoClient
from tripo3d.models import TaskStatus

from models.base import BaseModel
from models.common import errors

# 服务商支持的模型版本，与 SDK 的枚举保持一致。
SUPPORTED_VERSIONS = (
    "P1-20260311",
    "Turbo-v1.0-20250506",
    "v3.1-20260211",
    "v3.0-20250812",
    "v2.5-20250123",
    "v2.0-20240919",
    "v1.4-20240625",
)

# 主推模型版本。
RECOMMENDED_MODEL_ID = "v3.1-20260211"

# 服务商支持的导出格式，与 SDK 的枚举保持一致（均为大写）。
SUPPORTED_FORMATS = ("GLTF", "USDZ", "FBX", "OBJ", "STL", "3MF")

# `output_format` 的默认值，与项目其余部分统一使用小写扩展名。
DEFAULT_OUTPUT_FORMAT = "gltf"


class TripoModel(BaseModel):
    """Tripo3D 三维模型生成模型。"""

    provider = "tripo"
    display_name = "Tripo3D"
    api_key_field = "tripo_api_key"
    api_base_field = "tripo_api_base"

    def __init__(
        self,
        model_id: str,
        *,
        face_limit: int | None = None,
        texture: bool = True,
        pbr: bool = True,
        quad: bool = False,
        texture_quality: str = "standard",
        geometry_quality: str = "standard",
        timeout: int = 1800,
        poll_interval: float = 10.0,
        max_retries: int = 3,
        output_format: str = DEFAULT_OUTPUT_FORMAT,
        verbose: bool = False,
    ) -> None:
        """保存 Tripo 特有参数，其余交给基类。"""
        super().__init__(
            model_id,
            timeout=timeout,
            poll_interval=poll_interval,
            max_retries=max_retries,
            output_format=output_format,
            verbose=verbose,
        )

        if model_id not in SUPPORTED_VERSIONS:
            raise ValueError(
                f"model_id 必须是 Tripo 支持的版本之一：{SUPPORTED_VERSIONS}"
            )

        if output_format.upper() not in SUPPORTED_FORMATS:
            raise ValueError(
                f"output_format 只支持 {SUPPORTED_FORMATS}，收到 {output_format!r}"
            )

        self.face_limit = face_limit
        self.texture = texture
        self.pbr = pbr
        self.quad = quad
        self.texture_quality = texture_quality
        self.geometry_quality = geometry_quality

    def request(
        self,
        image: bytes | None = None,
        prompt: str = "",
        seed: int = 42,
        decimation_target: int | None = None,
        texture_size: int | None = None,
    ) -> bytes:
        """生成三维模型并返回模型文件的字节。

        Args:
            image: 参考图的 PNG 字节，用于图生模；传 `None` 则为文生模。
            prompt: 文本提示词，仅文生模时使用。
            seed: 随机种子，会透传给服务端，但不保证结果可复现。
            decimation_target: 目标面数上限，对应服务端的 `face_limit`。
            texture_size: 贴图边长，在格式转换阶段生效。

        Returns:
            模型文件的字节内容。
        """
        if image is None and not prompt.strip():
            raise ValueError("图生模需要 image，文生模需要 prompt，两者不能都为空")

        return asyncio.run(
            self._generate(image, prompt, seed, decimation_target, texture_size)
        )

    def request_and_save(
        self,
        image: bytes | None = None,
        output_path: str = "",
        seed: int = 42,
        decimation_target: int | None = None,
        texture_size: int | None = None,
    ) -> str:
        """生成三维模型并写入调用方指定的路径。

        对应规范 R1.2 的例外情形：模型自带纹理图集，不适合在内存中反复
        搬运。路径完全由调用方决定，模型不会自行拼接业务目录。
        """
        if not output_path:
            raise ValueError("output_path 必须由调用方提供")

        payload = self.request(image, "", seed, decimation_target, texture_size)

        return self.save_payload(payload, output_path)
    
    async def _generate(
        self,
        image: bytes | None,
        prompt: str,
        seed: int,
        decimation_target: int | None,
        texture_size: int | None,
    ) -> bytes:
        """在事件循环中完成提交、轮询与下载三步。"""

        async with TripoClient(api_key=self.api_key, v3_base_url=self.api_base) as client:
            task_id = await self._submit(client, image, prompt, seed, decimation_target)
            task = await client.wait_for_task(
                task_id,
                polling_interval=self.poll_interval,
                timeout=float(self.timeout),
                verbose=self.verbose,
            )

            self._check_task(task, task_id)

            url = task.output.pbr_model or task.output.model

            if not url:
                raise errors.CloudTaskError(f"Tripo 任务 {task_id} 没有返回模型地址")

            converted = await self._convert(client, task_id, decimation_target, texture_size)

            if converted:
                url = converted

            return await asyncio.to_thread(self._download, url)

    async def _submit(
        self,
        client: TripoClient,
        image: bytes | None,
        prompt: str,
        seed: int,
        decimation_target: int | None,
    ) -> str:
        """提交生成任务并返回任务标识。"""
        common: dict = {
            "model_version": self.model_id,
            "texture": self.texture,
            "pbr": self.pbr,
            "model_seed": seed,
            "texture_seed": seed,
            "texture_quality": self.texture_quality,
            "geometry_quality": self.geometry_quality,
        }

        face_limit = self.face_limit if decimation_target is None else decimation_target

        if face_limit is not None:
            common["face_limit"] = face_limit

        if image is not None:
            return await client.image_to_model(image, **common)

        return await client.text_to_model(prompt, **common)

    def _check_task(self, task, task_id: str) -> None:
        """校验任务是否成功进入终态。"""
        status = task.status

        if status == TaskStatus.SUCCESS:
            return

        reason = getattr(task, "error_msg", "") or str(status)

        if status in (TaskStatus.CANCELLED, TaskStatus.EXPIRED, TaskStatus.BANNED):
            raise errors.CloudTaskError(f"Tripo 任务 {task_id} 已终止：{reason}")

        raise errors.CloudTaskError(f"Tripo 任务 {task_id} 失败：{reason}")

    async def _convert(
        self,
        client: TripoClient,
        task_id: str,
        decimation_target: int | None,
        texture_size: int | None,
    ) -> str | None:
        """按当前 `output_format` 转换模型，返回新的下载地址。

        GLB 是 Tripo 的原生格式，无需转换；其余格式需要额外走一次
        `convert_model`。
        """
        if self.output_format.lower() in ("gltf", "glb"):
            return None

        converted_id = await client.convert_model(
            original_model_task_id=task_id,
            format=self.output_format.upper(),
            quad=self.quad,
            face_limit=decimation_target,
            texture_size=texture_size,
        )

        task = await client.wait_for_task(
            converted_id,
            polling_interval=self.poll_interval,
            timeout=float(self.timeout),
            verbose=self.verbose,
        )

        self._check_task(task, converted_id)

        return task.output.model

    def _download(self, url: str) -> bytes:
        """下载模型文件，失败时归类为可重试的网络故障。"""
        try:
            response = requests.get(url, timeout=(30.0, 120.0))
            response.raise_for_status()
            return response.content
        except errors.CloudModelError:
            raise
        except Exception as exc:
            raise errors.CloudModelNetworkError(
                f"下载 Tripo 模型失败：{exc}"
            ) from exc