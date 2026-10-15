"""Seedance 视频生成封装（火山方舟）。

火山方舟兼容 OpenAI 协议，因此这里使用官方 Python 包的 Videos API。
`create_and_poll()` 已经把"提交任务 → 轮询状态"封装为一次同步调用，
正好满足规范 R5 对调用方的要求；Base URL 由用户在 `.env` 中填写，
代码原样传入（规范 R6.4）。

主推模型为 `doubao-seedance-2-0-260128`。

参考来源：https://console.volcengine.com/ark/region:cn-beijing/openManagement

服务端生成结果的可复现性无法保证（规范 R3.4）：`seed` 会透传给服务端，
但服务端不承诺确定性输出。
"""

import base64
import io

from openai import OpenAI
from PIL import Image

from models.base import BaseModel
from models.common import errors
from models.gen_cg_video.utils import VideoGenerationInput, VideoGenerationMode

# 主推模型标识，建议直接使用。
RECOMMENDED_MODEL_ID = "doubao-seedance-2-0-260128"

# 服务商支持的画幅预设。
SUPPORTED_SIZES = ("480p", "720p", "1080p")


class SeedanceModel(BaseModel):
    """Seedance 视频生成模型。"""

    provider = "volcengine"
    display_name = "Seedance"
    api_key_field = "ark_api_key"
    api_base_field = "ark_api_base"

    def __init__(
        self,
        model_id: str,
        *,
        size: str = "720p",
        watermark: bool = False,
        timeout: int = 1800,
        poll_interval: float = 10.0,
        max_retries: int = 3,
        output_format: str = "mp4",
        verbose: bool = False,
    ) -> None:
        """保存 Seedance 特有参数，其余交给基类。"""
        super().__init__(
            model_id,
            timeout=timeout,
            poll_interval=poll_interval,
            max_retries=max_retries,
            output_format=output_format,
            verbose=verbose,
        )

        if size not in SUPPORTED_SIZES:
            raise ValueError(f"size 只支持 {SUPPORTED_SIZES}，收到 {size!r}")

        self.size = size
        self.watermark = watermark

    def request(self, video_input: VideoGenerationInput) -> bytes:
        """生成一段视频并返回 MP4 字节。

        Args:
            video_input: 厂商中立的输入描述，包含提示词、时长与各模式所需
                的参考图像。图像始终是 `PIL.Image.Image` 对象，不是路径。

        Returns:
            MP4 文件的字节内容。
        """
        self._validate(video_input)

        client = self.openai_client()
        video = self.call_with_retry(
            lambda: self._create(client, video_input)
        )

        return self._download(client, video)

    def _validate(self, video_input: VideoGenerationInput) -> None:
        """校验输入是否与所选模式匹配。"""
        if not isinstance(video_input, VideoGenerationInput):
            raise TypeError(
                "video_input 必须是 VideoGenerationInput，"
                f"收到 {type(video_input).__name__}"
            )

        if not video_input.prompt.strip():
            raise ValueError("Seedance 的 prompt 不能为空")

        if video_input.duration_sec <= 0:
            raise ValueError("duration_sec 必须大于 0")

        mode = video_input.mode

        if mode == VideoGenerationMode.TEXT_TO_VIDEO:
            return

        if mode == VideoGenerationMode.FIRST_FRAME_TO_VIDEO:
            if video_input.first_frame is None:
                raise ValueError("first_frame_to_video 需要提供 first_frame")

            return

        if mode == VideoGenerationMode.FIRST_LAST_FRAME_TO_VIDEO:
            if video_input.first_frame is None or video_input.last_frame is None:
                raise ValueError(
                    "first_last_frame_to_video 需要同时提供 first_frame 与 last_frame"
                )

            return

        if mode == VideoGenerationMode.REFERENCE_TO_VIDEO:
            if not video_input.reference_images:
                raise ValueError("reference_to_video 需要提供 reference_images")

    def _create(self, client: OpenAI, video_input: VideoGenerationInput):
        """调用 Videos API 提交任务并等待完成。"""
        extra_body: dict = {
            "watermark": self.watermark,
            "seed": video_input.seed,
        }

        reference = self._pick_reference(video_input)

        if reference is not None:
            extra_body["image"] = _encode_image(reference)

        return client.videos.create_and_poll(
            model=self.model_id,
            prompt=video_input.prompt,
            seconds=str(int(video_input.duration_sec)),
            size=self.size,
            poll_interval_ms=int(self.poll_interval * 1000),
            extra_body=extra_body,
        )

    def _pick_reference(self, video_input: VideoGenerationInput) -> Image.Image | None:
        """按模式挑选用作 `input_reference` 的图像。

        方舟的 Images/Videos API 只接受一张参考图，多图场景仍以首帧为
        主参考，其余图片不参与本次传输。
        """
        if video_input.first_frame is not None:
            return video_input.first_frame

        if video_input.reference_images:
            return video_input.reference_images[0]

        return None

    def _download(self, client: OpenAI, video) -> bytes:
        """下载生成完成的视频内容。"""
        try:
            content = client.videos.download_content(video.id)

            if hasattr(content, "content"):
                content = content.content

            if isinstance(content, (bytes, bytearray)):
                return bytes(content)

            return bytes(content.read())
        except Exception as exc:
            raise errors.CloudModelServerError(
                f"下载 Seedance 结果失败：{exc}"
            ) from exc


def _encode_image(image: Image.Image) -> str:
    """把 PIL 图像编码为 PNG 的 base64 data URI。

    规范 R3.2 要求输入是对象而非路径，编码由模型自己完成。
    """
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    return f"data:image/png;base64,{encoded}"