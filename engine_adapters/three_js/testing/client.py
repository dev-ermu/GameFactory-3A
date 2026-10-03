"""Stable automated test execution operations for ThreeClient v1."""

import json
import time
from pathlib import Path
from typing import Any, Iterable

from .._internal.transport import NodeToolchain
from ..config import ThreeClientConfig
from ..contracts import ThreeDiagnostic, ThreeOperationResult


SUPPORTED_RUNNERS = ("vitest", "playwright")
DEFAULT_REPORT_RELATIVE = {
    "vitest": ".a3game/reports/vitest-report.json",
    "playwright": ".a3game/reports/playwright-report.json",
}
DEFAULT_SCRIPT = {
    "vitest": "test",
    "playwright": "test:e2e",
}


def _iter_vitest_cases(
    payload: dict[str, Any],
) -> Iterable[dict[str, Any]]:
    for suite in payload.get("testResults") or []:
        if not isinstance(suite, dict):
            continue
        suite_name = str(
            suite.get("name") or suite.get("displayName") or ""
        )
        assertions = suite.get("assertionResults")
        if isinstance(assertions, list):
            for case in assertions:
                if not isinstance(case, dict):
                    continue
                yield {
                    "suite": suite_name,
                    "name": str(
                        case.get("fullName")
                        or case.get("title")
                        or ""
                    ),
                    "status": str(case.get("status") or""),
                    "duration": case.get("duration"),
                    "messages": [
                        str(item)
                        for item in case.get("failureMessages") or []
                    ],
                }
            continue
        yield {
            "suite": suite_name,
            "name": suite_name,
            "status": str(suite.get("status") or ""),
            "duration": suite.get("duration"),
            "messages": [
                str(suite.get("message") or "")
            ]
            if suite.get("message")
            else [],
        }


def _iter_playwright_cases(
    suites: Any,
    prefix: str = "",
) -> Iterable[dict[str, Any]]:
    if not isinstance(suites, list):
        return
    for suite in suites:
        if not isinstance(suite, dict):
            continue
        title = str(suite.get("title") or "")
        path = f"{prefix} > {title}".strip(" >") if title else prefix
        for spec in suite.get("specs") or []:
            if not isinstance(spec, dict):
                continue
            spec_title = str(spec.get("title") or "")
            statuses: list[str] = []
            messages: list[str] = []
            duration = 0
            for test in spec.get("tests") or []:
                if not isinstance(test, dict):
                    continue
                for result in test.get("results") or []:
                    if not isinstance(result, dict):
                        continue
                    statuses.append(str(result.get("status") or ""))
                    duration += int(result.get("duration") or 0)
                    error = result.get("error")
                    if isinstance(error, dict) and error.get("message"):
                        messages.append(str(error["message"]))
            status = "passed"
            if not statuses:
                status = "skipped"
            elif any(item == "failed" for item in statuses):
                status = "failed"
            elif any(item == "timedOut" for item in statuses):
                status = "failed"
            elif all(item == "skipped" for item in statuses):
                status = "skipped"
            yield {
                "suite": path,
                "name": f"{path} > {spec_title}".strip(" >"),
                "status": status,
                "duration": duration,
                "messages": messages,
            }
        yield from _iter_playwright_cases(
            suite.get("suites"),
            path,
        )


def _parse_report(
    runner: str,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    if runner == "vitest":
        return list(_iter_vitest_cases(payload))
    return list(_iter_playwright_cases(payload.get("suites")))


class ThreeTestingClient:
    """Run generated web tests and report authoritative counts."""

    def __init__(self, config: ThreeClientConfig) -> None:
        self._config = config
        self._toolchain = NodeToolchain(config)

    def run_automation_tests(
        self,
        *,
        runner: str = "vitest",
        test_filter: str = "",
        script: str = "",
        report_path: str = "",
        timeout: float | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Run web automation tests, parse a fresh report, and score it."""

        normalized_runner = str(runner or "").strip().lower()
        if normalized_runner not in SUPPORTED_RUNNERS:
            supported = ", ".join(SUPPORTED_RUNNERS)
            return ThreeOperationResult.failure(
                "testing.run_automation_tests",
                f"Unsupported runner {runner!r}; supported: {supported}",
            ).to_dict()

        project_dir = self._config.project_dir
        project_file = self._config.project_file
        if project_dir is None or project_file is None:
            return ThreeOperationResult.failure(
                "testing.run_automation_tests",
                "project_path is not configured",
            ).to_dict()
        if not project_file.is_file():
            return ThreeOperationResult.failure(
                "testing.run_automation_tests",
                "project_path does not resolve to an existing "
                "package.json file",
            ).to_dict()

        resolved_script = (
            str(script or "").strip()
            or DEFAULT_SCRIPT[normalized_runner]
        )
        resolved_report = Path(
            str(report_path or "").strip()
            or (
                project_dir
                / DEFAULT_REPORT_RELATIVE[normalized_runner]
            )
        )
        if not resolved_report.is_absolute():
            resolved_report = project_dir / resolved_report

        extra_args: list[str] = []
        if test_filter:
            if normalized_runner == "vitest":
                extra_args.extend(["-t", str(test_filter)])
            else:
                extra_args.extend(["--grep", str(test_filter)])
        if normalized_runner == "playwright":
            extra_args.extend(
                ["--reporter", f"json:{resolved_report}"]
            )

        payload: dict[str, Any] = {
            "runner": normalized_runner,
            "script": resolved_script,
            "cwd": str(project_dir),
            "test_filter": test_filter,
            "report_path": str(resolved_report),
            "extra_args": extra_args,
            "dry_run": dry_run,
        }
        if dry_run:
            return ThreeOperationResult.success(
                "testing.run_automation_tests",
                payload=payload,
            ).to_dict()

        # A stale report must never be scored as a fresh result.
        if resolved_report.is_file():
            resolved_report.unlink()
        resolved_report.parent.mkdir(parents=True, exist_ok=True)
        started_at = time.time()

        try:
            result = self._toolchain.run_script(
                resolved_script,
                cwd=project_dir,
                extra_args=extra_args,
                timeout=timeout,
                environment=(
                    {
                        "VITEST_JSON_OUTPUT_FILE": str(
                            resolved_report
                        ),
                    }
                    if normalized_runner == "vitest"
                    else None
                ),
            )
        except Exception as exc:
            return ThreeOperationResult.failure(
                "testing.run_automation_tests",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()

        payload.update(result.to_dict())
        payload["duration_seconds"] = round(
            time.time() - started_at,
            3,
        )

        if not resolved_report.is_file():
            return ThreeOperationResult.failure(
                "testing.run_automation_tests",
                "Test runner produced no report; a zero exit code "
                "alone is not success",
                payload=payload,
            ).to_dict()
        if resolved_report.stat().st_mtime < started_at - 1.0:
            return ThreeOperationResult.failure(
                "testing.run_automation_tests",
                "Test report is stale; refusing to score a report "
                "written before this run",
                payload=payload,
            ).to_dict()
        try:
            report = json.loads(
                resolved_report.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError) as exc:
            return ThreeOperationResult.failure(
                "testing.run_automation_tests",
                f"Test report is not readable JSON: {exc}",
                payload=payload,
            ).to_dict()
        if not isinstance(report, dict):
            return ThreeOperationResult.failure(
                "testing.run_automation_tests",
                "Test report must be a JSON object",
                payload=payload,
            ).to_dict()

        cases = _parse_report(normalized_runner, report)
        passed = [
            case for case in cases if case["status"] == "passed"
        ]
        failed = [
            case
            for case in cases
            if case["status"] in {"failed", "timedOut"}
        ]
        skipped = [
            case
            for case in cases
            if case["status"] in {"skipped", "pending", "todo"}
        ]
        diagnostics = [
            ThreeDiagnostic(
                severity="error",
                code="THREE_TEST_FAILED",
                message=(
                    case["messages"][0]
                    if case["messages"]
                    else f"Test failed: {case['name']}"
                ),
                file=str(case.get("suite") or ""),
                source=normalized_runner,
            )
            for case in failed
        ]
        payload.update(
            {
                "matched_count": len(cases),
                "passed_count": len(passed),
                "failed_count": len(failed),
                "skipped_count": len(skipped),
                "cases": cases,
                "failed_cases": failed,
            }
        )

        if not cases:
            return ThreeOperationResult.failure(
                "testing.run_automation_tests",
                "Test report matched zero tests; generated tests "
                "must exist and be discoverable",
                payload=payload,
            ).to_dict()
        if failed:
            return ThreeOperationResult.failure(
                "testing.run_automation_tests",
                f"{len(failed)} of {len(cases)} tests failed",
                diagnostics=diagnostics,
                payload=payload,
            ).to_dict()
        return ThreeOperationResult.success(
            "testing.run_automation_tests",
            artifacts=[
                {
                    "type": "web_test_report",
                    "path": str(resolved_report),
                    "state": "ready",
                }
            ],
            warnings=(
                [f"{len(skipped)} tests were skipped"]
                if skipped
                else []
            ),
            payload=payload,
        ).to_dict()
