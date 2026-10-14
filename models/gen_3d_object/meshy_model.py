"""Meshy3D 三维建模封装（暂不可用）。

Meshy AI 未在中国大陆完成备案，境外服务端点访问不稳定，因此本项目暂不
提供该后端。这里保留一个接口兼容的占位实现，原因有二：

1. 规范 R11 要求同一插槽下的各后端接口一致，`operator.py` 才能在不改动
   代码的前提下切换后端。删掉这个类会让 `meshy` 这个后端名直接报
   `ImportError`，掩盖"该后端暂不支持"这一真实原因。
2. 用户若显式选择该后端，应当收到明确提示，而不是一条难以理解的导入错误。

`request()` 无论传入什么参数都会直接抛出 `CloudModelConfigError`，不会
发起任何网络请求，也不会消耗额度。
"""

from models.base import BaseModel
from models.common import errors

# 服务商原定的模型版本标识，保留以便将来恢复接入。
RECOMMENDED_MODEL_ID = "meshy-5"

# 统一对外的错误提示，便于调用方与用户识别原因。
UNSUPPORTED_MESSAGE = (
    "Meshy3D 后端暂不可用：该服务商未在中国大陆完成备案，境外端点访问不稳定，"
    "本项目暂未接入。请改用 Tripo3D：在 .env 中设置 backend_3d_object=tripo。"
)


class MeshyModel(BaseModel):
    """Meshy3D 占位实现，调用时直接报错。"""

    provider = "meshy"
    display_name = "Meshy3D（暂不可用）"

    def __init__(
        self,
        model_id: str,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout: int = 1800,
        poll_interval: float = 10.0,
        max_retries: int = 0,
        output_format: str = "gltf",
        verbose: bool = False,
    ) -> None:
        """接受与其他三维后端一致的构造参数，便于上层无差别切换。"""
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

    def credential_spec(self) -> tuple[str, str]:
        """返回该后端原计划使用的配置项名。"""
        return ("meshy_api_key", "meshy_api_base")

    def request(
        self,
        image: bytes | None = None,
        prompt: str = "",
        seed: int = 42,
        decimation_target: int | None = None,
        texture_size: int | None = None,
    ) -> bytes:
        """始终抛出错误，说明该后端暂不可用。

        形参与 `TripoModel.request` 保持一致，使 `operator.py` 可以对两个
        后端使用同一套调用代码（规范 R11）。

        Raises:
            CloudModelConfigError: 无条件抛出，不会发起网络请求。
        """
        del image, prompt, seed, decimation_target, texture_size

        raise errors.CloudModelConfigError(UNSUPPORTED_MESSAGE)

    def request_and_save(
        self,
        image: bytes | None = None,
        output_path: str = "",
        seed: int = 42,
        decimation_target: int | None = None,
        texture_size: int | None = None,
    ) -> str:
        """始终抛出错误，说明该后端暂不可用。

        形参与 `TripoModel.request_and_save` 保持一致（规范 R11）。

        Raises:
            CloudModelConfigError: 无条件抛出，不会写任何文件。
        """
        del image, output_path, seed, decimation_target, texture_size

        raise errors.CloudModelConfigError(UNSUPPORTED_MESSAGE)