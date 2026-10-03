"""Private transports for UnityClient."""

from typing import Any, Protocol


class Transport(Protocol):
    def execute_method(
        self,
        class_method: str,
        *,
        args: dict[str, Any] | None = None,
        timeout: int = 120,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        ...

    def execute_json(
        self,
        class_method: str,
        *,
        args: dict[str, Any] | None = None,
        timeout: int = 120,
    ) -> Any:
        ...
