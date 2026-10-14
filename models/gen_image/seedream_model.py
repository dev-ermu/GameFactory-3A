"""Seedream 图像生成封装（火山方舟）。

火山方舟兼容 OpenAI 协议，因此这里使用官方 Python 包的 Images API
`client.images.generate()`（规范 R3.1）。Base URL 由用户在 `.env` 中填写，
代码原样传入，不做任何拼接（规范 R6.4）。

主推模型为 `doubao-seedream-5-0-flash-260915`，支持 2K 尺寸、多图参考
与图生图编辑。

参考来源：https://console.volcengine.com/ark/region:cn-beijing/openManagement

服务端生成结果的可复现性无法保证（规范 R3.4）：`seed` 会透传给服务端，
但服务端不承诺确定性输出。
"""

import base64
import io

import httpx2
from openai import OpenAI
from PIL import Image

from models.base import BaseModel
from models.common import errors

# 主推模型标识，建议直接使用。
RECOMMENDED_MODEL_ID = "doubao-seedream-5-0-flash-260915"

# 服务商支持的尺寸预设。
SUPPORTED_SIZES = ("1K", "2K", "4K")


class SeedreamModel(BaseModel):
    """Seedream 图像生成与编辑模型。"""

    provider = "volcengine"
    display_name = "Seedream"

    def __init__(
        self,
        model_id: str,
        *,
        size: str = "2K",
        watermark: bool = True,
        response_format: str = "url",
        api_key: str | None = None,
        api_base: str | None = None,
        timeout: int = 300,
        poll_interval: float = 10.0,
        max_retries: int = 3,
        output_format: str = "png",
        verbose: bool = False,
    ) -> None:
        """保存 Seedream 特有参数，其余交给基类。"""
        super().__init__(
            model_id,
            api_key=api_key,
            api_base=api_base,
            timeout=timeout,
            poll_interval=poll_interval,
            max_retries=max_retries,
            output_format=output_format,
            verbose=verbose,
        )

        if size not in SUPPORTED_SIZES:
            raise ValueError(
                f"size 只支持 {SUPPORTED_SIZES}，收到 {size!r}"
            )

        if response_format not in ("url", "b64_json"):
            raise ValueError(
                f"response_format 只支持 'url' 或 'b64_json'，收到 {response_format!r}"
            )

        self.size = size
        self.watermark = watermark
        self.response_format = response_format

    def credential_spec(self) -> tuple[str, str]:
        """返回火山方舟需要的配置项名。"""
        return ("ark_api_key", "ark_api_base")

    def request(
        self,
        prompt: str,
        image: Image.Image | None = None,
        seed: int = 42,
        reference_images: list[Image.Image] | None = None,
        n: int = 1,
        steps: int | None = None,
    ) -> Image.Image:
        """生成一张图像并返回 PIL 图像。

        Args:
            prompt: 描述期望输出的文本提示词，不能为空。
            image: 参考图，用于图生图编辑；传 `None` 则为纯文生图。
            seed: 随机种子，会透传给服务端，但不保证结果可复现。
            reference_images: 多张参考图，用于保持主体一致性。
            n: 生成张数，本方法只返回第一张。
            steps: 为插槽兼容而保留，Seedream 没有扩散步数参数，会被忽略。

        Returns:
            RGB 模式的 `PIL.Image.Image`。
        """
        del steps

        if not prompt or not prompt.strip():
            raise ValueError("Seedream 的 prompt 不能为空")

        client = self.openai_client()
        result = self.call_with_retry(
            lambda: self._generate(client, prompt, image, reference_images, seed, n)
        )

        return self._decode(result)

    def _generate(
        self,
        client: OpenAI,
        prompt: str,
        image: Image.Image | None,
        reference_images: list[Image.Image] | None,
        seed: int,
        n: int,
    ):
        """调用 Images API 并返回原始响应对象。"""
        extra_body: dict = {"watermark": self.watermark}
        references = list(reference_images or [])

        if image is not None:
            references.insert(0, image)

        if references:
            extra_body["image"] = [_encode_image(item) for item in references]

        return client.images.generate(
            model=self.model_id,
            prompt=prompt,
            size=self.size,
            response_format=self.response_format,
            n=n,
            extra_body={"seed": seed, **extra_body},
        )

    def _decode(self, result) -> Image.Image:
        """把 Images API 的响应转换为 PIL 图像。

        服务商可能返回图片 URL，也可能直接返回 base64；两条路径都要覆盖。
        """
        data = getattr(result, "data", None) or []

        if not data:
            raise errors.CloudModelServerError(
                "Seedream 响应中没有图像数据，请确认模型标识与配额是否正确"
            )

        item = data[0]
        url = getattr(item, "url", None)
        encoded = getattr(item, "b64_json", None)

        if url:
            return Image.open(io.BytesIO(self._download(url))).convert("RGB")

        if encoded:
            return Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")

        raise errors.CloudModelServerError(
            f"Seedream 响应中既没有 url 也没有 b64_json：{item!r}"
        )

    def _download(self, url: str) -> bytes:
        """下载图片字节，失败时归类为可重试的网络故障。"""
        try:
            with httpx2.Client(timeout=60.0, follow_redirects=True) as client:
                response = client.get(url)

                if response.status_code >= 500:
                    raise errors.CloudModelServerError(
                        f"下载 Seedream 结果时服务端返回 {response.status_code}"
                    )

                response.raise_for_status()
                return response.content
        except errors.CloudModelError:
            raise
        except Exception as exc:
            raise errors.CloudModelNetworkError(
                f"下载 Seedream 结果失败：{exc}"
            ) from exc


def _encode_image(image: Image.Image) -> str:
    """把 PIL 图像编码为 PNG 的 base64 data URI。

    规范 R3.2 要求输入是对象而非路径，因此这里接受 `PIL.Image.Image`，
    由模型自行完成编码，不依赖调用方先把文件落到磁盘。
    """
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    return f"data:image/png;base64,{encoded}"