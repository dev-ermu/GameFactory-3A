"""UI artifact validation and workspace finalization."""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from pipeline.code_gen.gen_ui.contracts import (
    BROWSER_PLAY_MANIFEST_SCHEMA,
    MECHANIC_CONTRACT_FILENAME,
    MECHANIC_FIXTURE_SCHEMA,
    SCREENSHOT_PLAN_SCHEMA,
    UI_BINDING_MANIFEST_SCHEMA,
    file_digest,
)
from pipeline.common.artifacts import (
    is_relative_to,
    read_json,
)
from pipeline.common.code_mapping import (
    resolve_browser_backend_registration,
    resolve_engine_registration,
    validate_context_used,
)
from pipeline.common.finalize import finalize_workspace


_GENERIC_BINDING_NAMES = {
    "id",
    "name",
    "state",
    "status",
    "type",
    "value",
}


def _optional_json(
    path: Path,
    name: str,
) -> dict[str, Any]:
    try:
        return read_json(path, name)
    except (FileNotFoundError, TypeError, ValueError):
        return {}


def _mechanic_binding_violations(
    workspace: Path,
    source_paths: Sequence[str],
    bindings: Mapping[str, Sequence[str]],
    *,
    owner: str,
) -> list[str]:
    forbidden_names = {
        str(name).strip().lower()
        for values in bindings.values()
        for name in values
        if (
            str(name).strip()
            and str(name).strip().lower()
            not in _GENERIC_BINDING_NAMES
        )
    }
    violations: list[str] = []
    for relative_path in source_paths:
        path = workspace / relative_path
        if not path.is_file():
            continue
        try:
            source = path.read_text(
                encoding="utf-8",
                errors="ignore",
            ).lower()
        except OSError as exc:
            violations.append(
                f"Unable to inspect {owner} source "
                f"{relative_path}: {exc}"
            )
            continue
        forbidden_tokens = {
            "mechanic_contract",
            "mechanic_contract_fixture",
            "mechanic_public_paths",
            "state_bindings",
            "event_bindings",
            "command_bindings",
        }
        matches = sorted(
            token
            for token in forbidden_tokens | forbidden_names
            if re.search(
                rf"\b{re.escape(token)}\b",
                source,
            )
        )
        if matches:
            violations.append(
                f"{owner} must not reproduce or consume "
                f"Mechanic UI in {relative_path}: "
                + ", ".join(matches)
            )
    return violations


def _native_gameplay_access_violations(
    workspace: Path,
    native_source_paths: Sequence[str],
    mechanic_contract: Mapping[str, Any],
) -> list[str]:
    producer_sources: set[str] = set()
    for section in ("state", "events", "commands"):
        entries = mechanic_contract.get(section, [])
        if isinstance(entries, Mapping):
            iterable = entries.values()
        elif (
            isinstance(entries, Sequence)
            and not isinstance(entries, (str, bytes))
        ):
            iterable = entries
        else:
            iterable = []
        for entry in iterable:
            if isinstance(entry, Mapping):
                source = str(
                    entry.get("source") or ""
                ).strip()
                if source:
                    producer_sources.add(
                        source.lower()
                    )

    direct_patterns = (
        re.compile(
            r"\b\w*(?:character|pawn|gamemode|"
            r"weapon)\s*->",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bcast\s*<[^>]*(?:character|pawn|"
            r"gamemode|weapon)[^>]*>",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bgetplayer(?:character|pawn)\b",
            re.IGNORECASE,
        ),
    )
    violations: list[str] = []
    for relative_path in native_source_paths:
        path = workspace / relative_path
        if not path.is_file():
            continue
        try:
            source = path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except OSError as exc:
            violations.append(
                "Unable to inspect engine-native UI source "
                f"{relative_path}: {exc}"
            )
            continue
        source_lower = source.lower()
        matches = [
            pattern.pattern
            for pattern in direct_patterns
            if pattern.search(source)
        ]
        matches.extend(
            f"contract source {producer_source!r}"
            for producer_source in producer_sources
            if producer_source in source_lower
        )
        if matches:
            violations.append(
                "Engine-native UI must use the public "
                f"Mechanic runtime adapter in {relative_path}: "
                + ", ".join(matches)
            )
    return violations


def required_artifact_checks(
    workspace: Path,
    required: Sequence[str],
    current_task_files: Mapping[str, Mapping[str, Any]],
    *,
    engine: str,
    ui_module_name: str,
    mechanic_contract_path: Path,
    mechanic_contract: Mapping[str, Any],
    mechanic_contract_digest: Mapping[str, Any],
    bindings: Mapping[str, Sequence[str]],
    screens: Sequence[str],
    viewports: Sequence[Mapping[str, int]],
    mechanic_example_roots: Sequence[Path],
    ui_example_roots: Sequence[Path],
    browser_play_example_paths: Sequence[Path],
    allowed_example_purposes: Sequence[str],
    require_example_purpose: bool,
    browser_backend: Mapping[str, Any],
    provenance_digests: Mapping[
        str,
        Mapping[str, Any],
    ],
) -> tuple[dict[str, bool | None], list[str], list[str]]:
    fixture_relative = (
        "generated_ui/Tests/fixtures/"
        "mechanic_contract_fixture.json"
    )
    manifest_relative = (
        "generated_ui/ui_binding_manifest.json"
    )
    plan_relative = "generated_ui/screenshot_plan.json"
    context_used_relative = (
        "generated_ui/context_used.json"
    )
    browser_manifest_relative = (
        "generated_ui/browser_play/"
        "browser_play_manifest.json"
    )
    ui_paths = [
        path
        for path in current_task_files
        if PurePosixPath(path).parts[:1]
        == ("generated_ui",)
    ]
    browser_paths = [
        path
        for path in ui_paths
        if PurePosixPath(path).parts[:2]
        == ("generated_ui", "browser_play")
    ]
    native_paths = [
        path
        for path in ui_paths
        if path not in browser_paths
    ]
    native_test_paths = [
        path
        for path in native_paths
        if path != fixture_relative
        and any(
            "test" in part.lower()
            for part in PurePosixPath(path).parts
        )
    ]
    browser_test_paths = [
        path
        for path in browser_paths
        if any(
            "test" in part.lower()
            for part in PurePosixPath(path).parts
        )
    ]
    native_metadata_paths = {
        plan_relative,
        manifest_relative,
        fixture_relative,
        context_used_relative,
    }
    native_source_paths = [
        path
        for path in native_paths
        if path not in native_metadata_paths
        and path not in native_test_paths
    ]
    browser_source_paths = [
        path
        for path in browser_paths
        if path not in browser_test_paths
    ]
    unexpected_paths = [
        path
        for path in current_task_files
        if PurePosixPath(path).parts[:1]
        != ("generated_ui",)
    ]
    replacement_contracts = [
        path
        for path in current_task_files
        if PurePosixPath(path).name.lower()
        == MECHANIC_CONTRACT_FILENAME
    ]

    browser_manifest = _optional_json(
        workspace / browser_manifest_relative,
        "Browser Play manifest",
    )
    browser_root = (
        workspace / "generated_ui" / "browser_play"
    ).resolve(strict=False)
    entry_point = str(
        browser_manifest.get("entry_point") or ""
    ).strip()
    launch_script = str(
        browser_manifest.get("launch_script") or ""
    ).strip()

    def browser_file(relative: str) -> Path | None:
        value = Path(relative)
        if (
            not relative
            or value.is_absolute()
            or ".." in value.parts
        ):
            return None
        target = (browser_root / value).resolve(
            strict=False
        )
        if (
            not is_relative_to(target, browser_root)
            or not target.is_file()
        ):
            return None
        return target

    entry_path = browser_file(entry_point)
    launch_path = browser_file(launch_script)
    backend_entry_point = str(
        browser_backend.get("entry_point") or ""
    ).strip()
    session_bootstrap = browser_manifest.get(
        "session_bootstrap"
    )
    streaming = browser_manifest.get("streaming")
    if not isinstance(streaming, Mapping):
        streaming = browser_manifest.get(
            "pixel_streaming"
        )
    browser_handoff_ok = (
        browser_manifest.get("schema_version")
        == BROWSER_PLAY_MANIFEST_SCHEMA
        and browser_manifest.get("engine") == engine
        and browser_manifest.get("gateway_route") == "/game"
        and browser_manifest.get("backend_entry_point")
        == backend_entry_point
        and entry_path is not None
        and launch_path is not None
        and isinstance(session_bootstrap, Mapping)
        and session_bootstrap.get("mode")
        == "create_or_recover"
        and session_bootstrap.get("health_path")
        == "/api/health"
        and session_bootstrap.get("create_path")
        == "/api/sessions"
        and session_bootstrap.get("recover_path")
        == "/api/sessions/recover"
        and isinstance(streaming, Mapping)
        and streaming.get("external_frontend")
        is False
    )
    if launch_path is not None:
        launch_source = launch_path.read_text(
            encoding="utf-8",
            errors="ignore",
        )
        browser_handoff_ok = (
            browser_handoff_ok
            and "A3GAME_BROWSER_PLAY_DIR" in launch_source
            and "engine_adapters.browser_serving"
            in launch_source
        )

    browser_source = ""
    for relative_path in browser_source_paths:
        path = workspace / relative_path
        if path.suffix.lower() not in {
            ".js",
            ".ts",
            ".html",
        }:
            continue
        try:
            browser_source += path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except OSError:
            continue
    normalized_browser_source = browser_source.lower()
    browser_bootstrap_ok = all(
        token in normalized_browser_source
        for token in (
            "/api/health",
            "/api/sessions",
            "/api/sessions/recover",
        )
    ) and (
        "stream_url" in normalized_browser_source
        or "pixel_streaming_url" in normalized_browser_source
    ) and (
        'method: "post"' in normalized_browser_source
        or "method: 'post'" in normalized_browser_source
    )

    manifest = _optional_json(
        workspace / manifest_relative,
        "UI binding manifest",
    )
    manifest_contract = manifest.get(
        "mechanic_contract"
    )
    manifest_bindings = manifest.get("bindings")
    manifest_screens = manifest.get("screens")
    binding_manifest_ok = (
        manifest.get("schema_version")
        == UI_BINDING_MANIFEST_SCHEMA
        and manifest.get("ui_module") == ui_module_name
        and isinstance(manifest_contract, Mapping)
        and all(
            manifest_contract.get(key)
            == mechanic_contract.get(key)
            for key in (
                "schema_version",
                "contract_version",
                "gameplay_module",
            )
        )
        and manifest_contract.get("sha256")
        == mechanic_contract_digest.get("sha256")
        and isinstance(manifest_bindings, Mapping)
        and all(
            list(
                manifest_bindings.get(section, [])
            )
            == list(bindings[section])
            for section in (
                "state",
                "events",
                "commands",
            )
        )
        and isinstance(manifest_screens, Sequence)
        and not isinstance(
            manifest_screens,
            (str, bytes),
        )
        and all(
            isinstance(value, str)
            for value in manifest_screens
        )
        and set(manifest_screens) == set(screens)
    )

    fixture = _optional_json(
        workspace / fixture_relative,
        "Mechanic contract fixture",
    )
    fixture_contract = fixture.get(
        "mechanic_contract"
    )
    scenarios = fixture.get("scenarios")
    fixture_ok = (
        fixture.get("schema_version")
        == MECHANIC_FIXTURE_SCHEMA
        and isinstance(fixture_contract, Mapping)
        and all(
            fixture_contract.get(key)
            == mechanic_contract.get(key)
            for key in (
                "schema_version",
                "contract_version",
                "gameplay_module",
            )
        )
        and isinstance(scenarios, Sequence)
        and not isinstance(scenarios, (str, bytes))
        and bool(scenarios)
    )

    plan = _optional_json(
        workspace / plan_relative,
        "UI screenshot plan",
    )
    planned = plan.get("screens")
    planned_names = {
        str(item.get("name") or "")
        for item in planned
        if isinstance(item, Mapping)
    } if (
        isinstance(planned, Sequence)
        and not isinstance(planned, (str, bytes))
    ) else set()
    plan_ok = (
        plan.get("schema_version")
        == SCREENSHOT_PLAN_SCHEMA
        and set(screens).issubset(planned_names)
        and bool(viewports)
    )
    contract_unchanged = (
        mechanic_contract_path.is_file()
        and file_digest(mechanic_contract_path)
        == dict(mechanic_contract_digest)
    )
    browser_violations = (
        _mechanic_binding_violations(
            workspace,
            browser_paths,
            bindings,
            owner="Browser Play",
        )
    )
    native_violations = (
        _native_gameplay_access_violations(
            workspace,
            native_source_paths,
            mechanic_contract,
        )
    )
    try:
        registration = resolve_engine_registration(
            engine
        )
        registered_backend = (
            resolve_browser_backend_registration(engine)
        )
        browser_backend_registered = (
            dict(browser_backend)
            == registered_backend
        )
        context_used_ok, context_used_errors = (
            validate_context_used(
                workspace / context_used_relative,
                engine=engine,
                context_expectations=[
                    {
                        "stage": "engine_native",
                        "role": "engine_api",
                        "path": registration[
                            "primary_api"
                        ],
                    },
                    {
                        "stage": "browser_play",
                        "role": (
                            "browser_serving_api"
                        ),
                        "path": registration[
                            "browser_serving_primary_api"
                        ],
                    },
                ],
                example_expectations={},
                example_roots={
                    "mechanic_example": (
                        mechanic_example_roots
                    ),
                    "ui_example": ui_example_roots,
                    "browser_play_example": (
                        browser_play_example_paths
                    ),
                },
                required_example_roles=(
                    "mechanic_example",
                    "ui_example",
                    "browser_play_example",
                ),
                allowed_example_purposes=(
                    allowed_example_purposes
                ),
                require_example_purpose=(
                    require_example_purpose
                ),
                expected_digests=provenance_digests,
            )
        )
    except (
        FileNotFoundError,
        TypeError,
        ValueError,
    ) as exc:
        browser_backend_registered = False
        context_used_ok = False
        context_used_errors = [str(exc)]

    checks: dict[str, bool | None] = {
        "generated_ui_source": bool(
            native_source_paths
        ),
        "generated_ui_test_source": bool(
            native_test_paths
        ),
        "ui_binding_manifest": binding_manifest_ok,
        "mechanic_contract_fixture": fixture_ok,
        "browser_play_source": bool(
            browser_source_paths
        ),
        "browser_play_test_source": bool(
            browser_test_paths
        ),
        "browser_play_handoff": browser_handoff_ok,
        "browser_play_bootstrap": browser_bootstrap_ok,
        "browser_play_mechanic_free": (
            not browser_violations
        ),
        "browser_backend_registered": (
            browser_backend_registered
        ),
        "native_runtime_adapter_only": (
            not native_violations
        ),
        "context_used": context_used_ok,
        "screenshot_plan": plan_ok,
        "task_owned_output_roots": not unexpected_paths,
        "mechanic_contract_unchanged": (
            contract_unchanged
        ),
        "no_replacement_mechanic_contract": (
            not replacement_contracts
        ),
    }
    error_by_check = {
        "generated_ui_source": (
            "No generated UI source or resource file was found"
        ),
        "generated_ui_test_source": (
            "No generated UI test source was found"
        ),
        "ui_binding_manifest": (
            "generated_ui/ui_binding_manifest.json "
            "is missing or inconsistent"
        ),
        "mechanic_contract_fixture": (
            "The mocked Mechanic contract fixture is "
            "missing or invalid"
        ),
        "browser_play_source": (
            "No Browser Play source or resource file was "
            "found under generated_ui/browser_play/"
        ),
        "browser_play_test_source": (
            "No Browser Play test source was found under "
            "generated_ui/browser_play/"
        ),
        "browser_play_handoff": (
            "Browser Play must include a valid "
            "browser_play_manifest.json and thin launch script"
        ),
        "browser_play_bootstrap": (
            "Browser Play must health-check Serving, create or "
            "recover a session, and consume stream_url"
        ),
        "browser_play_mechanic_free": (
            "Browser Play source must not reproduce or "
            "consume Mechanic gameplay UI"
        ),
        "browser_backend_registered": (
            "The selected Engine has no matching registered "
            "Browser Serving backend"
        ),
        "native_runtime_adapter_only": (
            "Engine-native UI source must use only the "
            "public Mechanic runtime adapter"
        ),
        "context_used": (
            "generated_ui/context_used.json is missing, "
            "inconsistent, or references invalid provenance"
        ),
        "screenshot_plan": (
            "generated_ui/screenshot_plan.json is "
            "missing or invalid"
        ),
        "task_owned_output_roots": (
            "UI task-owned files must stay under generated_ui/"
        ),
        "mechanic_contract_unchanged": (
            "The read-only Mechanic contract changed "
            "during UI generation"
        ),
        "no_replacement_mechanic_contract": (
            "UI generation must not copy or replace "
            "mechanic_contract.json"
        ),
    }
    errors = [
        message
        for name, message in error_by_check.items()
        if checks[name] is False
    ]
    errors.extend(browser_violations)
    errors.extend(native_violations)
    errors.extend(context_used_errors)
    known_required = {
        "ui_source": checks["generated_ui_source"],
        "ui_artifact_dir": checks[
            "generated_ui_source"
        ],
        "ui_tests": checks[
            "generated_ui_test_source"
        ],
        "ui_binding_manifest": binding_manifest_ok,
        "mechanic_contract_fixture": fixture_ok,
        "context_used": context_used_ok,
        "browser_play_source": checks[
            "browser_play_source"
        ],
        "browser_play_tests": checks[
            "browser_play_test_source"
        ],
        "browser_play_handoff": checks[
            "browser_play_handoff"
        ],
        "screenshot_plan": plan_ok,
    }
    warnings: list[str] = []
    for artifact in required:
        checks[artifact] = known_required.get(artifact)
        if artifact not in known_required:
            warnings.append(
                "Finalize has no check for required UI "
                f"artifact {artifact!r}"
            )
    for artifact, passed in checks.items():
        if passed is False and artifact in required:
            errors.append(
                f"Required UI artifact is missing: {artifact}"
            )
    return checks, errors, warnings


def finalize(
    packet_path: str | Path,
    *,
    summary: str = "",
) -> dict[str, Any]:
    """Finalize one directly edited UI workspace."""
    from pipeline.code_gen.gen_ui.packet import (
        FULL_UI_DELIVERY_MODE,
    )

    packet = read_json(
        packet_path,
        "Prepared UI task packet",
    )
    context = packet.get("context")
    if not isinstance(context, Mapping):
        raise TypeError(
            "Prepared UI packet context must be an object"
        )
    mechanic_contract = context.get(
        "mechanic_contract"
    )
    mechanic_contract_digest = context.get(
        "mechanic_contract_digest"
    )
    bindings = context.get("bindings")
    screens = context.get("screens")
    viewports = context.get("viewports")
    mechanic_examples = context.get(
        "mechanic_example_paths"
    )
    mechanic_example_roots = context.get(
        "mechanic_example_roots"
    )
    ui_examples = context.get("ui_example_paths")
    ui_example_roots = context.get(
        "ui_example_roots"
    )
    browser_play_examples = context.get(
        "browser_play_example_paths"
    )
    browser_backend = context.get("browser_backend")
    provenance_digests = context.get(
        "provenance_digests"
    )
    delivery_mode = str(
        packet.get("delivery_mode")
        or context.get("delivery_mode")
        or ""
    ).strip()
    if delivery_mode != FULL_UI_DELIVERY_MODE:
        raise ValueError(
            "Prepared UI packet delivery_mode is invalid"
        )
    if not isinstance(mechanic_contract, Mapping):
        raise TypeError(
            "Prepared UI packet mechanic_contract must be an object"
        )
    if not isinstance(
        mechanic_contract_digest,
        Mapping,
    ):
        raise TypeError(
            "Prepared UI packet mechanic_contract_digest "
            "must be an object"
        )
    if not isinstance(bindings, Mapping):
        raise TypeError(
            "Prepared UI packet bindings must be an object"
        )
    if (
        isinstance(screens, (str, bytes))
        or not isinstance(screens, Sequence)
    ):
        raise TypeError(
            "Prepared UI packet screens must be a sequence"
        )
    if (
        isinstance(viewports, (str, bytes))
        or not isinstance(viewports, Sequence)
    ):
        raise TypeError(
            "Prepared UI packet viewports must be a sequence"
        )
    for name, value in (
        (
            "mechanic_example_roots",
            mechanic_example_roots,
        ),
        ("mechanic_example_paths", mechanic_examples),
        ("ui_example_roots", ui_example_roots),
        ("ui_example_paths", ui_examples),
        (
            "browser_play_example_paths",
            browser_play_examples,
        ),
    ):
        if (
            isinstance(value, (str, bytes))
            or not isinstance(value, Sequence)
        ):
            raise TypeError(
                f"Prepared UI packet {name} must be a sequence"
            )
    if not isinstance(browser_backend, Mapping):
        raise TypeError(
            "Prepared UI packet browser_backend "
            "must be an object"
        )
    if not isinstance(provenance_digests, Mapping):
        raise TypeError(
            "Prepared UI packet provenance_digests "
            "must be an object"
        )
    usage_contract = packet.get("context_usage_contract")
    if not isinstance(usage_contract, Mapping):
        raise TypeError(
            "Prepared UI packet context_usage_contract "
            "must be an object"
        )
    allowed_purposes = usage_contract.get(
        "allowed_example_purposes",
        [],
    )
    if (
        isinstance(allowed_purposes, (str, bytes))
        or not isinstance(allowed_purposes, Sequence)
    ):
        raise TypeError(
            "Prepared UI packet allowed_example_purposes "
            "must be a sequence"
        )
    mechanic_contract_path = Path(
        str(
            context.get(
                "mechanic_contract_path"
            )
            or ""
        )
    ).expanduser().resolve(strict=False)
    ui_module_name = str(
        packet.get("ui_module_name") or ""
    )
    engine = str(packet.get("engine") or "")
    def artifact_checker(
        workspace: Path,
        required: Sequence[str],
        current_task_files: Mapping[
            str,
            Mapping[str, Any],
        ],
    ) -> tuple[
        dict[str, bool | None],
        list[str],
        list[str],
    ]:
        return required_artifact_checks(
            workspace,
            required,
            current_task_files,
            engine=engine,
            ui_module_name=ui_module_name,
            mechanic_contract_path=(
                mechanic_contract_path
            ),
            mechanic_contract=mechanic_contract,
            mechanic_contract_digest=(
                mechanic_contract_digest
            ),
            bindings={
                str(section): list(values)
                for section, values in bindings.items()
            },
            screens=[
                str(item)
                for item in screens
            ],
            viewports=[
                dict(item)
                for item in viewports
                if isinstance(item, Mapping)
            ],
            mechanic_example_roots=[
                Path(str(item)).expanduser().resolve(
                    strict=False
                )
                for item in mechanic_example_roots
            ],
            ui_example_roots=[
                Path(str(item)).expanduser().resolve(
                    strict=False
                )
                for item in ui_example_roots
            ],
            browser_play_example_paths=[
                Path(str(item)).expanduser().resolve(
                    strict=False
                )
                for item in browser_play_examples
            ],
            allowed_example_purposes=[
                str(purpose)
                for purpose in allowed_purposes
            ],
            require_example_purpose=bool(
                usage_contract.get(
                    "example_purpose_required",
                    False,
                )
            ),
            browser_backend=dict(browser_backend),
            provenance_digests={
                str(path): dict(value)
                for path, value in provenance_digests.items()
                if isinstance(value, Mapping)
            },
        )

    return finalize_workspace(
        packet_path,
        summary=summary,
        artifact_checker=artifact_checker,
    )
