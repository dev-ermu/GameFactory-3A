"""Private transport contract for communicating with Unreal Engine."""

from typing import Any, Protocol


class Transport(Protocol):
    def execute(
        self,
        script: str,
        timeout: int = 120,
    ) -> dict[str, Any]:
        ...

    def execute_json(
        self,
        script: str,
        result_var: str = "result",
        timeout: int = 120,
    ) -> Any:
        ...
