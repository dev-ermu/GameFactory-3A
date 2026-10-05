"""Exceptions raised by the Browser Serving HTTP client.
浏览器HTTP服务客户端抛出的异常。
"""

from typing import Any


class BrowserServingClientError(RuntimeError):
    pass


class BrowserServingConnectionError(BrowserServingClientError):
    def __init__(self, method: str, url: str, message: str) -> None:
        self.method = method
        self.url = url
        super().__init__(f"{method} {url}: {message}")


class BrowserServingHTTPError(BrowserServingClientError):
    def __init__(
        self,
        *,
        status_code: int,
        method: str,
        url: str,
        detail: str,
        payload: Any = None,
    ) -> None:
        self.status_code = int(status_code)
        self.method = method
        self.url = url
        self.detail = detail
        self.payload = payload
        super().__init__(
            f"{method} {url} returned {status_code}: {detail}"
        )


class BrowserServingResponseError(BrowserServingClientError):
    def __init__(
        self,
        *,
        method: str,
        url: str,
        message: str,
        body: str,
    ) -> None:
        self.method = method
        self.url = url
        self.body = body
        super().__init__(f"{method} {url}: {message}")
