"""Public command-line entry points backed only by ThreeClient."""

import argparse
import json
import time
from typing import Any, Sequence

from engine_adapters.three_js import ThreeClient


def _emit(result: dict[str, Any]) -> int:
    print(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.get("ok") else 1


def _client(
    args: argparse.Namespace,
    *,
    project_attr: str = "project",
) -> ThreeClient:
    return ThreeClient(
        project_path=getattr(args, project_attr, ""),
        three_root=getattr(args, "three_root", None),
        api_version=args.api_version,
        host=getattr(args, "dev_host", None),
        port=getattr(args, "dev_port", None),
        runtime_host=getattr(args, "runtime_host", None),
        runtime_port=getattr(args, "runtime_port", None),
        package_manager=getattr(args, "package_manager", None),
        node_root=getattr(args, "node_root", None),
    )


def _source_descriptor(
    args: argparse.Namespace,
) -> dict[str, str]:
    return {
        key: value
        for key, value in {
            "game_id": args.game_id,
            "run_id": args.run_id,
            "task_kind": args.task_kind,
            "task_id": args.task_id,
            "artifact_key": args.artifact_key,
        }.items()
        if value
    }


def _create_project(args: argparse.Namespace) -> dict[str, Any]:
    client = _client(args, project_attr="project_path")
    created = client.project.create(dry_run=args.dry_run)
    result = {
        "ok": bool(created.get("ok")),
        "operation": "scripts.create_project",
        "artifacts": list(created.get("artifacts") or []),
        "diagnostics": list(created.get("diagnostics") or []),
        "warnings": list(created.get("warnings") or []),
        "errors": list(created.get("errors") or []),
        "payload": {
            "create": created,
            "framework_requested": not args.skip_framework,
            "install_requested": not args.skip_install,
            "dry_run": args.dry_run,
        },
    }
    if not created.get("ok") or args.dry_run:
        return result

    if not args.skip_framework:
        framework = client.plugin.install_framework()
        result["payload"]["framework"] = framework
        result["ok"] = bool(framework.get("ok"))
        result["artifacts"].extend(framework.get("artifacts") or [])
        result["errors"].extend(framework.get("errors") or [])
        if not framework.get("ok"):
            return result

    if not args.skip_install:
        installed = client.project.install_dependencies(
            timeout=args.install_timeout,
        )
        result["payload"]["install"] = installed
        result["ok"] = bool(installed.get("ok"))
        result["artifacts"].extend(installed.get("artifacts") or [])
        result["warnings"].extend(installed.get("warnings") or [])
        result["errors"].extend(installed.get("errors") or [])
    return result


def _wait_for_runtime(
    client: ThreeClient,
    *,
    world: str,
    no_launch_server: bool,
    timeout: float,
) -> dict[str, Any]:
    def accept_dev_server_readiness(
        status: dict[str, Any],
    ) -> bool:
        payload = status.get("payload") or {}
        dev_server = payload.get("dev_server") or {}
        if not dev_server.get("ok"):
            return False
        status["ok"] = True
        status["errors"] = []
        warnings = list(status.get("warnings") or [])
        warning = (
            "Runtime control channel is unavailable; continuing "
            "because the dev server is ready"
        )
        if warning not in warnings:
            warnings.append(warning)
        status["warnings"] = warnings
        payload["readiness"] = "dev_server"
        status["payload"] = payload
        return True

    status = client.observe.check_status(
        timeout=min(5.0, timeout),
    )
    if status.get("ok") or accept_dev_server_readiness(status):
        return status
    if no_launch_server:
        return status

    launched = client.runtime.launch_dev_server(
        world=world,
        wait_timeout=timeout,
    )
    if not launched.get("ok"):
        return launched

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.observe.check_status(
            timeout=min(3.0, timeout),
        )
        if status.get("ok") or accept_dev_server_readiness(status):
            status["payload"]["launched_dev_server"] = launched
            return status
        time.sleep(1.0)
    status["errors"] = [
        f"three.js runtime was not ready after {timeout:.1f}s"
    ]
    status["payload"]["launched_dev_server"] = launched
    return status


def _import_asset(args: argparse.Namespace) -> dict[str, Any]:
    client = _client(args)
    source = _source_descriptor(args)
    asset_type = str(args.asset_type).strip().lower()
    if args.dry_run:
        resolved = client.assets.resolve_source(
            source,
            asset_type=asset_type,
        )
        return {
            "ok": bool(resolved.get("ok")),
            "operation": "scripts.import_asset",
            "artifacts": list(resolved.get("artifacts") or []),
            "diagnostics": list(resolved.get("diagnostics") or []),
            "warnings": list(resolved.get("warnings") or []),
            "errors": list(resolved.get("errors") or []),
            "payload": {
                "dry_run": True,
                "source": source,
                "asset_type": asset_type,
                "destination": args.destination,
                "resolved": resolved,
            },
        }

    options = {
        key: value
        for key, value in {
            "category": args.category,
            "replace_existing": args.replace_existing,
            "asset_id": args.asset_id,
        }.items()
        if value is not None and value != ""
    }
    if asset_type == "scene":
        result = client.world.build(
            source,
            options={
                "world_id": args.world_id,
                "project_id": args.project_id,
                "publish": not args.no_publish,
                "replace_existing": args.replace_existing,
            },
        )
    elif asset_type == "motion":
        result = client.assets.import_motion(
            source,
            skeleton=args.skeleton,
            destination=args.destination,
            options=options,
        )
    else:
        result = client.assets.import_asset(
            source,
            asset_type,
            destination=args.destination,
            options=options,
        )
    return result


def _run_dev_server(args: argparse.Namespace) -> dict[str, Any]:
    client = _client(args)
    if args.wait_only:
        return _wait_for_runtime(
            client,
            world=args.world,
            no_launch_server=args.no_launch_server,
            timeout=args.runtime_timeout,
        )
    return client.runtime.launch_dev_server(
        script=args.script,
        world=args.world,
        extra_args=args.extra_arg,
        wait_timeout=args.runtime_timeout,
        dry_run=args.dry_run,
    )


def _add_client_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument("--project", required=True)
    parser.add_argument("--three-root", default="")
    parser.add_argument("--node-root", default="")
    parser.add_argument("--api-version", default="v1")
    parser.add_argument("--dev-host", default="127.0.0.1")
    parser.add_argument("--dev-port", type=int, default=5173)
    parser.add_argument("--runtime-host", default="127.0.0.1")
    parser.add_argument("--runtime-port", type=int, default=30040)
    parser.add_argument(
        "--package-manager",
        choices=("npm", "pnpm", "yarn"),
        default="npm",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="a3game-three")
    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    create = commands.add_parser("create-project")
    create.add_argument("--project-path", required=True)
    create.add_argument("--three-root", default="")
    create.add_argument("--node-root", default="")
    create.add_argument("--api-version", default="v1")
    create.add_argument("--dev-port", type=int, default=5173)
    create.add_argument("--runtime-port", type=int, default=30040)
    create.add_argument(
        "--package-manager",
        choices=("npm", "pnpm", "yarn"),
        default="npm",
    )
    create.add_argument(
        "--install-timeout",
        type=float,
        default=None,
    )
    create.add_argument("--skip-framework", action="store_true")
    create.add_argument("--skip-install", action="store_true")
    create.add_argument("--dry-run", action="store_true")

    asset = commands.add_parser("import-asset")
    _add_client_arguments(asset)
    asset.add_argument("--game-id", required=True)
    asset.add_argument("--run-id", default="default")
    asset.add_argument("--task-kind", default="")
    asset.add_argument("--task-id", required=True)
    asset.add_argument("--artifact-key", default="")
    asset.add_argument("--type", dest="asset_type", required=True)
    asset.add_argument("--destination", default="")
    asset.add_argument("--category", default="")
    asset.add_argument("--asset-id", default="")
    asset.add_argument("--skeleton", default="")
    asset.add_argument("--world-id", default="")
    asset.add_argument("--project-id", default="")
    asset.add_argument("--no-publish", action="store_true")
    asset.add_argument(
        "--replace-existing",
        action="store_true",
    )
    asset.add_argument("--dry-run", action="store_true")

    run = commands.add_parser("run")
    _add_client_arguments(run)
    run.add_argument("--script", default="dev")
    run.add_argument("--world", default="")
    run.add_argument(
        "--extra-arg",
        action="append",
        default=[],
    )
    run.add_argument(
        "--runtime-timeout",
        type=float,
        default=60.0,
    )
    run.add_argument("--no-launch-server", action="store_true")
    run.add_argument("--wait-only", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "create-project":
            return _emit(_create_project(args))
        if args.command == "import-asset":
            return _emit(_import_asset(args))
        if args.command == "run":
            return _emit(_run_dev_server(args))
        raise AssertionError(args.command)
    except (
        FileExistsError,
        FileNotFoundError,
        RuntimeError,
        TimeoutError,
        ValueError,
    ) as exc:
        return _emit(
            {
                "ok": False,
                "operation": "scripts.error",
                "artifacts": [],
                "diagnostics": [],
                "warnings": [],
                "errors": [
                    f"{type(exc).__name__}: {exc}"
                ],
                "payload": {},
            }
        )


if __name__ == "__main__":
    raise SystemExit(main())
