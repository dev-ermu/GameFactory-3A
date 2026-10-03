"""Stable Unity Test Framework operations for UnityClient v1."""

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence

from .._internal.transport import find_unity_binary
from ..config import UnityClientConfig
from ..contracts import UnityDiagnostic, UnityOperationResult


_OPERATION = "testing.run_automation_tests"
_REPORT_FILENAME = "nunit-results.xml"
_CONTROLLED_ARGUMENT_NAMES = (
    "-testresults",
    "-runtests",
    "-testplatform",
    "-batchmode",
    "-logfile",
    "-quit",
)


def _int_attr(
    element: ET.Element,
    name: str,
    default: int = 0,
) -> int:
    value = element.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _resolve_report_dir(
    project_path: Path,
    report_dir: str,
) -> Path:
    text = str(report_dir or "").strip()
    if not text:
        return project_path / "TestResults"
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = project_path / path
    return path.resolve(strict=False)


def _report_file_signature(
    report_file: Path,
) -> tuple[int, int] | None:
    try:
        stat = report_file.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _parse_nunit_report(
    report_file: Path,
) -> dict[str, Any]:
    """Parse a NUnit XML test report and extract summary counts."""
    if not report_file.is_file():
        return {
            "ok": False,
            "errors": [
                f"Test report was not found: {report_file}"
            ],
            "diagnostics": [],
            "warnings": [],
            "payload": {},
        }
    try:
        tree = ET.parse(str(report_file))
    except ET.ParseError as exc:
        return {
            "ok": False,
            "errors": [
                "Test report could not be parsed: "
                f"{type(exc).__name__}: {exc}"
            ],
            "diagnostics": [],
            "warnings": [],
            "payload": {},
        }
    except Exception as exc:
        return {
            "ok": False,
            "errors": [
                "Test report could not be read: "
                f"{type(exc).__name__}: {exc}"
            ],
            "diagnostics": [],
            "warnings": [],
            "payload": {},
        }

    root = tree.getroot()
    total = _int_attr(root, "total")
    passed = _int_attr(root, "passed")
    failed = _int_attr(root, "failed")
    skipped = _int_attr(root, "skipped")
    inconclusive = _int_attr(root, "inconclusive")

    diagnostics: list[UnityDiagnostic] = []
    for test_case in root.iter("test-case"):
        if test_case.get("result") != "Failed":
            continue
        name = (
            test_case.get("fullname")
            or test_case.get("name")
            or "Unnamed test"
        )
        failure_elem = test_case.find("failure")
        message = ""
        if failure_elem is not None:
            message_elem = failure_elem.find("message")
            if message_elem is not None and message_elem.text:
                message = message_elem.text.strip()
        if not message:
            message = f"{name}: Unity test failed"
        diagnostics.append(
            UnityDiagnostic(
                severity="error",
                message=message,
                code="UNITY_TEST_FAILED",
                file=name,
                source="unity_test_report",
            )
        )

    errors: list[str] = []
    if total == 0:
        errors.append("Test report contains no tests")
    if failed > 0:
        errors.append(f"{failed} Unity test(s) failed")

    return {
        "ok": not errors,
        "errors": errors,
        "diagnostics": diagnostics,
        "warnings": [],
        "payload": {
            "tests_found": total,
            "tests_passed": passed,
            "tests_failed": failed,
            "tests_skipped": skipped,
            "tests_inconclusive": inconclusive,
        },
    }


def _unique_strings(
    values: Sequence[str],
) -> list[str]:
    return list(
        dict.fromkeys(
            value for value in values if value
        )
    )


def _result(
    *,
    ok: bool,
    artifacts: Sequence[Mapping[str, Any]] = (),
    diagnostics: Sequence[UnityDiagnostic] = (),
    warnings: Sequence[str] = (),
    errors: Sequence[str] = (),
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return UnityOperationResult(
        operation=_OPERATION,
        ok=ok,
        artifacts=tuple(
            dict(artifact) for artifact in artifacts
        ),
        diagnostics=tuple(diagnostics),
        warnings=tuple(_unique_strings(warnings)),
        errors=tuple(_unique_strings(errors)),
        payload=dict(payload),
    ).to_dict()


def _base_payload() -> dict[str, Any]:
    return {
        "command": [],
        "cwd": "",
        "test_filter": "",
        "report_dir": "",
        "report_file": "",
        "dry_run": False,
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "timed_out": False,
        "tests_found": 0,
        "tests_passed": 0,
        "tests_failed": 0,
        "tests_skipped": 0,
        "tests_inconclusive": 0,
    }


class UnityTestingClient:
    """Run Unity EditMode automation tests and parse NUnit XML reports."""

    def __init__(self, config: UnityClientConfig) -> None:
        self._config = config

    def run_automation_tests(
        self,
        test_filter: str,
        *,
        report_dir: str = "",
        extra_args: Sequence[str] = (),
        timeout: float | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        filter_text = str(test_filter or "").strip()
        base_payload: dict[str, Any] = _base_payload()
        base_payload["test_filter"] = filter_text

        if not filter_text:
            return _result(
                ok=False,
                errors=["test_filter must not be empty"],
                payload=base_payload,
            )
        if any(
            character in filter_text
            for character in (";", "\r", "\n")
        ):
            return _result(
                ok=False,
                errors=[
                    "test_filter must not contain command "
                    "separators"
                ],
                payload=base_payload,
            )
        if timeout is not None and timeout <= 0:
            return _result(
                ok=False,
                errors=["timeout must be greater than zero"],
                payload=base_payload,
            )
        if isinstance(extra_args, (str, bytes)):
            return _result(
                ok=False,
                errors=[
                    "extra_args must be a sequence of "
                    "arguments, not a string"
                ],
                payload=base_payload,
            )
        resolved_extra_args = [
            str(argument) for argument in extra_args
        ]
        for argument in resolved_extra_args:
            lowered = argument.strip().casefold()
            if any(
                lowered == name
                or lowered.startswith(f"{name}=")
                for name in _CONTROLLED_ARGUMENT_NAMES
            ):
                return _result(
                    ok=False,
                    errors=[
                        "extra_args must not override "
                        "TestResults, RunTests, TestPlatform, "
                        "BatchMode, or Quit"
                    ],
                    payload=base_payload,
                )

        unity = find_unity_binary(self._config.unity_root)
        project_path = self._config.project_path
        if unity is None or not unity.exists():
            return _result(
                ok=False,
                errors=[
                    f"Unity editor binary was not found: "
                    f"{unity or '<not configured>'}"
                ],
                payload=base_payload,
            )
        if project_path is None or not project_path.is_dir():
            return _result(
                ok=False,
                errors=[
                    "project_path does not resolve to an "
                    "existing Unity project directory"
                ],
                payload=base_payload,
            )

        resolved_report_dir = _resolve_report_dir(
            project_path,
            report_dir,
        )
        report_file = (
            resolved_report_dir / _REPORT_FILENAME
        )
        log_file = resolved_report_dir / "unity-tests.log"
        command = [
            str(unity),
            "-batchmode",
            "-nographics",
            "-runTests",
            "-projectPath",
            str(project_path),
            "-logFile",
            str(log_file),
            "-testResults",
            str(report_file),
            "-testPlatform",
            "EditMode",
        ]
        if filter_text:
            command.extend(["-testFilter", filter_text])
        command.extend(resolved_extra_args)
        base_payload.update(
            {
                "command": command,
                "cwd": str(project_path),
                "report_dir": str(resolved_report_dir),
                "report_file": str(report_file),
                "log_file": str(log_file),
                "dry_run": dry_run,
            }
        )
        if dry_run:
            return _result(
                ok=True,
                artifacts=[
                    {
                        "type": "automation_report",
                        "path": str(resolved_report_dir),
                        "state": "planned",
                    }
                ],
                payload=base_payload,
            )

        try:
            resolved_report_dir.mkdir(
                parents=True,
                exist_ok=True,
            )
        except OSError as exc:
            return _result(
                ok=False,
                errors=[
                    "Test report directory could not be "
                    f"created: {type(exc).__name__}: {exc}"
                ],
                payload=base_payload,
            )
        previous_signature = _report_file_signature(
            report_file
        )

        process_errors: list[str] = []
        try:
            completed = subprocess.run(
                command,
                cwd=str(project_path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
            )
            process_log = (
                log_file.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
                if log_file.is_file()
                else ""
            )
            base_payload.update(
                {
                    "returncode": completed.returncode,
                    "stdout": process_log,
                    "stderr": "",
                }
            )
            if completed.returncode != 0:
                process_errors.append(
                    "Unity test process failed with "
                    f"exit code {completed.returncode}"
                )
        except subprocess.TimeoutExpired as exc:
            base_payload.update(
                {
                    "stdout": _text(exc.stdout),
                    "stderr": _text(exc.stderr),
                    "timed_out": True,
                }
            )
            process_errors.append(
                "Unity test process timed out"
                + (
                    f" after {timeout} seconds"
                    if timeout is not None
                    else ""
                )
            )
        except Exception as exc:
            process_errors.append(
                "Unity test process could not be started: "
                f"{type(exc).__name__}: {exc}"
            )

        current_signature = _report_file_signature(
            report_file
        )
        report_is_fresh = (
            current_signature is not None
            and current_signature != previous_signature
        )
        artifacts: list[dict[str, Any]] = []
        report_errors: list[str] = []
        report_warnings: list[str] = []
        diagnostics: list[UnityDiagnostic] = []
        if report_is_fresh:
            artifacts.append(
                {
                    "type": "automation_report",
                    "path": str(resolved_report_dir),
                    "state": "ready",
                }
            )
            report = _parse_nunit_report(report_file)
            base_payload.update(report["payload"])
            diagnostics.extend(report["diagnostics"])
            report_errors.extend(report["errors"])
            report_warnings.extend(report["warnings"])
        elif current_signature is None:
            report_errors.append(
                f"Test report was not produced: {report_file}"
            )
        else:
            report_errors.append(
                "Test report was not updated by this run: "
                f"{report_file}"
            )

        errors = [
            *process_errors,
            *report_errors,
        ]
        ok = not errors
        return _result(
            ok=ok,
            artifacts=artifacts,
            diagnostics=diagnostics,
            warnings=report_warnings,
            errors=errors,
            payload=base_payload,
        )
