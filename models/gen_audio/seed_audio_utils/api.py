"""Seed Audio-specific HTTP client and request headers."""

import threading
import uuid
from typing import Any, Optional

from models.common import cloud_api


class SeedAudioAPIClient(cloud_api.CloudAPIClient):
    """Cloud client that keeps Seed Audio authentication isolated.

    Seed Audio uses a raw ``X-Api-Key`` header and requires a fresh
    ``X-Api-Request-Id`` for each logical request.  The shared cloud client is
    intentionally left unchanged for Meshy, Tripo, Seedance and future APIs.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: int = 60,
        max_retries: int = 3,
        backoff: float = 1.5,
        user_agent: str = "3AGameFactory/0.1 (+https://github.com/OpenDCAI/GameFactory-3A)",
    ):
        super().__init__(
            base_url,
            api_key,
            timeout=timeout,
            max_retries=max_retries,
            backoff=backoff,
            auth_header="X-Api-Key",
            auth_template="{key}",
            user_agent=user_agent,
        )
        self._request_lock = threading.Lock()
        self.last_request_id: Optional[str] = None

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
        files: Optional[dict] = None,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
        expect_json: bool = True,
    ) -> Any:
        """Send one request with a unique provider trace id.

        The lock keeps the session-level request id stable across retries and
        prevents concurrent calls on the same model instance from sharing one.
        """
        request_id = str(uuid.uuid4())
        with self._request_lock:
            self.last_request_id = request_id
            self.session.headers["X-Api-Request-Id"] = request_id
            return super().request(
                method,
                path,
                json_body=json_body,
                files=files,
                data=data,
                params=params,
                expect_json=expect_json,
            )
