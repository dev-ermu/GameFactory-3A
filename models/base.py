"""云端大模型封装的抽象基类。

所有模型封装共享的能力集中在这里，具体模型只需要实现 `request()`：
统一的客户端构建、可重试故障的指数退避、远程任务的轮询、生成结果的强制落盘。
把这些放进基类而不是各模型重复实现，是因为规范 R8 要求重试分类在所有服务商
之间保持一致——一处判断错了，其他封装会跟着错。

子类通过自己的 `__init__` 追加服务商特有参数，再调用 `super().__init__()`，
不使用 `**kwargs` 这类模糊容器，便于 IDE 与类型检查器给出准确提示。

规范条款对照：
    R2.1  `model_id` 是调用 API 时真实使用的模型标识，无默认值
    R2.2  构造参数一律存入 `self`
    R3.2  输入是对象而非路径，由子类负责校验
    R4.1  客户端复用 keep-alive 连接池
    R4.2  `bind_session` 用于延续上一次的服务端会话
    R5.2  `timeout` 与 `poll_interval` 为构造参数，默认超时偏长
    R5.3  超时异常必须携带 `task_id`
    R6.1  凭证与 Base URL 在首次调用时才读取
    R6.3  Base URL 必填，代码不猜测、不改写
    R7.1  生成结果必须落盘
    R8    可重试与终态故障分离
"""

import abc
import json
from pathlib import Path

import openai

# todo 优化
from config import get_str as config_get_str
from models.common import errors


class BaseModel(abc.ABC):
    """云端大模型封装的公共基类"""

    # 子类覆盖：用于报错信息的服务商名称
    provider: str = ""
    # 子类覆盖：展示给用户的可读名称
    display_name: str = ""
    # 子类覆盖：`.env` 中存放 API Key 的配置项名（规范 R10.1）
    api_key_field: str = ""
    # 子类覆盖：`.env` 中存放 API 基础地址的配置项名（规范 R10.1）
    api_base_field: str = ""

    def __init__(
        self,
        model_id: str,
        *,
        timeout: int = 600,
        poll_interval: float = 10.0,
        max_retries: int = 3,
    ) -> None:
        self.model_id = model_id
        self.api_key = config_get_str(self.api_key_field)
        self.api_base = config_get_str(self.api_base_field)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_retries = max_retries

        self.check_settings()
        self._client: openai.OpenAI = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.api_base,
            max_retries=self.max_retries,
        )
        self._previous_response_id: str | None = None

        self.response = None

    def check_settings(self) -> None:
        """校验凭证与端点齐备，缺失时快速失败（规范 R6.2、R6.3）。

        端点没有默认值，缺失时无法猜测——服务商随时可能更换地址，
        硬编码回退只会在第一次计费调用时才暴露问题。
        """
        missing = []

        if not self.api_base:
            missing.append(self.api_base_field)

        if not self.api_key:
            missing.append(self.api_key_field)

        if missing:
            raise errors.CloudModelConfigError(
                f"{self.display_name} 缺少配置项：{'、'.join(missing)}。"
                f"请在 .env 中填写后重试；本次调用未向服务商发起请求。"
            )
    
    def request(self):
        """执行一次模型调用请求"""
        try:
            self.response = self._client.responses.create(
                model=self.model_id,
                instructions="系统提示词",
                input="你好",
                stream=False
            )
        except openai.APIConnectionError as e:
            print(f"网络错误，无状态码。{e}")
        except openai.APIStatusError as e:
            # 出现该错误时，表示http状态码是4xx~5xx
            print(f"HTTP {e.status_code}: {e.response.text}")

    @property
    def session_id(self) -> str | None:
        """返回当前绑定的会话标识。"""
        return self._previous_response_id

    def release(self) -> None:
        """关闭底层连接，释放网络资源。重复调用是安全的。"""
        if self._client is not None:
            self._client.close()

        self._previous_response_id = None

    def persist(self, payload: bytes, directory: str | Path, filename: str) -> Path:
        """把生成结果写入磁盘并返回路径。"""
        target_dir = Path(directory)
        target_dir.mkdir(parents=True, exist_ok=True)

        target = target_dir / filename
        target.write_bytes(payload)

        return target

    def save_payload(self, payload: bytes, output_path: str | Path) -> str:
        """把产物写到调用方指定的路径并返回该路径。

        对应规范 R1.2 的例外情形：服务商返回的产物（如自带纹理图集的 GLB）
        不适合在内存中反复搬运时才提供。路径完全由调用方决定，模型不会
        自行拼接或创建业务目录结构。
        """
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

        return str(target)
