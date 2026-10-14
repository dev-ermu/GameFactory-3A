"""云端大模型调用过程中抛出的异常体系。

区分异常类型的目的只有一个：让 `BaseModel` 能够判断失败是否值得重试。
可重试的故障（限流、服务端错误、网络抖动）与终态故障（参数错误、
认证失败、余额不足）在响应特征上完全不同，混为一谈会导致两种后果——
要么浪费额度反复重试注定失败的请求，要么让临时抖动直接终止任务。

异常层级对应规范 R8 的分类要求。
"""


class CloudModelError(RuntimeError):
    """所有云端模型异常的基类。"""
    pass


class CloudModelConfigError(CloudModelError):
    """配置缺失或不合法，例如未填写 API Key 或 API Base URL。

    对应规范 R6.2：此类问题必须尽早暴露，且错误信息要指明缺哪个配置项。
    """
    pass


class CloudModelAuthError(CloudModelError):
    """认证失败，对应 HTTP 401 与 403。属于终态故障，不可重试。"""
    pass


class CloudModelQuotaError(CloudModelError):
    """额度不足，对应 HTTP 402。属于终态故障，不可重试。"""
    pass


class CloudModelRequestError(CloudModelError):
    """请求参数错误，对应 HTTP 400。属于终态故障，不可重试。"""
    pass


class CloudModelRateLimitError(CloudModelError):
    """触发服务商限流，对应 HTTP 429。属于可重试故障。"""
    pass


class CloudModelServerError(CloudModelError):
    """服务商内部错误，对应 HTTP 5xx。属于可重试故障。"""
    pass


class CloudModelNetworkError(CloudModelError):
    """连接被重置、读取超时等传输层故障。属于可重试故障。"""
    pass


class CloudTaskError(CloudModelError):
    """远程任务在服务端执行失败。"""
    pass


class CloudTaskTimeout(CloudTaskError):
    """等待远程任务超时。

    对应规范 R5.3：异常信息中必须携带 `task_id`。任务在服务端仍会继续
    执行，调用方可以据此稍后取回结果，不必重新提交并重复计费。
    """

    def __init__(self, message: str, task_id: str | None = None) -> None:
        """记录超时任务的任务标识，便于调用方事后恢复。"""
        super().__init__(message)
        self.task_id = task_id