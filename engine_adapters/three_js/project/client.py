"""Stable project inspection operations for ThreeClient v1."""

import json
import re
from pathlib import Path
from typing import Any

from ..config import THREE_ASSET_TYPE_DEFAULT_DESTS, ThreeClientConfig
from ..contracts import ThreeOperationResult


DEFAULT_THREE_DEPENDENCY = "^0.185.0"
DEFAULT_VITE_DEPENDENCY = "^6.1.0"
DEFAULT_VITEST_DEPENDENCY = "^2.1.0"
DEFAULT_PLAYWRIGHT_DEPENDENCY = "^1.49.0"

PACKAGE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _validate_project_name(project_name: str) -> str:
    normalized = (
        str(project_name or "")
        .strip()
        .lower()
        .replace(" ", "-")
        .replace("_", "-")
    )
    if not PACKAGE_NAME_PATTERN.fullmatch(normalized):
        raise ValueError(
            "three.js project name must be a valid npm package name "
            "(lowercase letters, digits, '.', '-', '_'): "
            f"{project_name!r}"
        )
    return normalized


def _package_json(project_name: str) -> dict[str, Any]:
    return {
        "name": project_name,
        "private": True,
        "version": "0.0.0",
        "type": "module",
        "description": "3AGameFactory generated three.js project.",
        "scripts": {
            "dev": "vite",
            "serve": "vite",
            "build": "vite build",
            "preview": "vite preview",
            "test": "vitest run --reporter=json "
            "--outputFile=.a3game/reports/vitest-report.json",
            "test:e2e": "playwright test --reporter=json",
        },
        "dependencies": {
            "three": DEFAULT_THREE_DEPENDENCY,
        },
        "devDependencies": {
            "vite": DEFAULT_VITE_DEPENDENCY,
            "vitest": DEFAULT_VITEST_DEPENDENCY,
            "@playwright/test": DEFAULT_PLAYWRIGHT_DEPENDENCY,
        },
    }


def _vite_config(port: int) -> str:
    return "\n".join(
        (
            "import { defineConfig } from 'vite';",
            "import { resolve } from 'node:path';",
            "",
            "// Serving stays on loopback unless asked otherwise. A project",
            "// on a remote dev box opts in with A3GAME_DEV_HOST=0.0.0.0,",
            "// and allowedHosts stops Vite rejecting the forwarded Host",
            "// header a tunnel or IDE port forward produces.",
            "const server = {",
            f"  port: Number(process.env.A3GAME_DEV_PORT ?? {int(port)}),",
            "  strictPort: true,",
            "  host: process.env.A3GAME_DEV_HOST ?? '127.0.0.1',",
            "  allowedHosts: true,",
            "};",
            "",
            "export default defineConfig({",
            "  server,",
            "  preview: server,",
            "  resolve: {",
            "    alias: {",
            "      '@': resolve(process.cwd(), 'src'),",
            "      '@a3game/playable': resolve(",
            "        process.cwd(),",
            "        'packages/a3game-playable/src/index.js',",
            "      ),",
            "    },",
            "  },",
            "  build: {",
            "    outDir: 'dist',",
            "    sourcemap: true,",
            "    target: 'es2022',",
            "  },",
            "});",
            "",
        )
    )


def _index_html(project_name: str) -> str:
    return "\n".join(
        (
            "<!doctype html>",
            '<html lang="en">',
            "  <head>",
            '    <meta charset="UTF-8" />',
            '    <meta name="viewport" content="width=device-width, '
            'initial-scale=1.0" />',
            f"    <title>{project_name}</title>",
            "    <style>",
            "      html, body { margin: 0; height: 100%; "
            "background: #101014; overflow: hidden; }",
            "      #a3game-viewport { position: absolute; inset: 0; }",
            "      #a3game-hud { position: absolute; inset: 0; "
            "pointer-events: none; }",
            "    </style>",
            "  </head>",
            "  <body>",
            '    <div id="a3game-viewport"></div>',
            '    <div id="a3game-hud"></div>',
            '    <script type="module" src="/src/main.js"></script>',
            "  </body>",
            "</html>",
            "",
        )
    )


def _main_js() -> str:
    return "\n".join(
        (
            "// 3AGameFactory three.js host entry point.",
            "//",
            "// This file boots the adapter-owned runtime framework "
            "only. Concrete",
            "// gameplay belongs in a generated Gameplay Package under "
            "`packages/`.",
            "import {",
            "  A3GameRuntimeHost,",
            "  A3GameRuntimeSubsystem,",
            "  A3GameWorldSessionSubsystem,",
            "  A3GameAssetLibrary,",
            "} from '@a3game/playable';",
            "",
            "const host = new A3GameRuntimeHost({",
            "  container: '#a3game-viewport',",
            "  hudContainer: '#a3game-hud',",
            "});",
            "",
            "await host.init();",
            "",
            "const assets = new A3GameAssetLibrary({",
            "  manifestUrl: '/assets/manifest.json',",
            "});",
            "await assets.load();",
            "",
            "const session = new A3GameWorldSessionSubsystem({",
            "  worldId: 'world_001',",
            "});",
            "const runtime = new A3GameRuntimeSubsystem({",
            "  host,",
            "  session,",
            "  assets,",
            "});",
            "runtime.onWorldBeginPlay();",
            "",
            "// Generated gameplay registers its own entity factory:",
            "//   runtime.setEntityFactory(new MyGameEntityFactory());",
            "",
            "host.start();",
            "",
            "globalThis.__A3GAME__ = { host, runtime, session, assets };",
            "",
        )
    )


def _write_project_files(
    project_dir: Path,
    project_name: str,
    config: ThreeClientConfig,
) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    for destination in sorted(
        set(THREE_ASSET_TYPE_DEFAULT_DESTS.values())
    ):
        (project_dir / "public" / destination).mkdir(
            parents=True,
            exist_ok=True,
        )
    for relative in (
        "src",
        "packages",
        "tests",
        "public/assets",
        ".a3game/reports",
        ".a3game/worlds",
    ):
        (project_dir / relative).mkdir(parents=True, exist_ok=True)

    (project_dir / "package.json").write_text(
        json.dumps(_package_json(project_name), indent=2) + "\n",
        encoding="utf-8",
    )
    (project_dir / "vite.config.js").write_text(
        _vite_config(config.port),
        encoding="utf-8",
    )
    (project_dir / "index.html").write_text(
        _index_html(project_name),
        encoding="utf-8",
    )
    (project_dir / "src" / "main.js").write_text(
        _main_js(),
        encoding="utf-8",
    )
    (project_dir / ".gitignore").write_text(
        "\n".join(
            (
                "node_modules/",
                "dist/",
                ".a3game/reports/",
                "",
            )
        ),
        encoding="utf-8",
    )
    (project_dir / ".a3game-three.json").write_text(
        json.dumps(
            {
                "engine": "three_js",
                "api_version": config.api_version,
                "engine_version": config.engine_version,
                "engine_root": str(config.three_root or ""),
                "project_dir": str(project_dir),
                "project_name": project_name,
                "dev_server_port": config.port,
                "runtime_control_port": config.runtime_port,
                "package_manager": config.package_manager,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


class ThreeProjectClient:
    def __init__(self, config: ThreeClientConfig) -> None:
        self._config = config

    def get_info(self) -> dict[str, Any]:
        project_dir = self._config.project_dir
        project_file = self._config.project_file
        three_root = self._config.three_root
        return ThreeOperationResult.success(
            "project.get_info",
            payload={
                "api_version": self._config.api_version,
                "engine": "three_js",
                "engine_version": self._config.engine_version,
                "three_root": str(three_root or ""),
                "three_root_exists": bool(
                    three_root and three_root.is_dir()
                ),
                "project_path": str(
                    self._config.project_path or ""
                ),
                "project_dir": str(project_dir or ""),
                "project_file": str(project_file or ""),
                "project_exists": bool(
                    project_file and project_file.is_file()
                ),
                "public_root": str(
                    self._config.public_root or ""
                ),
                "dist_root": str(self._config.dist_root or ""),
                "package_manager": self._config.package_manager,
            },
        ).to_dict()

    def create(
        self,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        project_dir = self._config.project_dir
        if project_dir is None:
            return ThreeOperationResult.failure(
                "project.create",
                "project_path is not configured",
            ).to_dict()
        try:
            project_name = _validate_project_name(project_dir.name)
        except ValueError as exc:
            return ThreeOperationResult.failure(
                "project.create",
                str(exc),
            ).to_dict()
        project_file = project_dir / "package.json"
        if project_file.exists():
            return ThreeOperationResult.failure(
                "project.create",
                f"Project already exists: {project_file}",
            ).to_dict()

        payload = {
            "api_version": self._config.api_version,
            "dry_run": dry_run,
            "project_dir": str(project_dir),
            "project_file": str(project_file),
            "project_name": project_name,
            "dev_server_url": self._config.dev_server_url,
            "runtime_url": self._config.runtime_url,
            "package_manager": self._config.package_manager,
            "dependencies": {
                "three": DEFAULT_THREE_DEPENDENCY,
                "vite": DEFAULT_VITE_DEPENDENCY,
            },
        }
        if dry_run:
            return ThreeOperationResult.success(
                "project.create",
                artifacts=[
                    {
                        "type": "three_project",
                        "path": str(project_file),
                        "state": "planned",
                    }
                ],
                payload=payload,
            ).to_dict()

        try:
            _write_project_files(
                project_dir,
                project_name,
                self._config,
            )
        except Exception as exc:
            return ThreeOperationResult.failure(
                "project.create",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()

        return ThreeOperationResult.success(
            "project.create",
            artifacts=[
                {
                    "type": "three_project",
                    "path": str(project_file),
                    "state": "ready",
                }
            ],
            payload=payload,
        ).to_dict()

    def install_dependencies(
        self,
        *,
        timeout: float | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Install Node dependencies for the configured project."""

        from .._internal.transport import NodeToolchain

        project_dir = self._config.project_dir
        project_file = self._config.project_file
        if project_dir is None or project_file is None:
            return ThreeOperationResult.failure(
                "project.install_dependencies",
                "project_path is not configured",
            ).to_dict()
        if not project_file.is_file():
            return ThreeOperationResult.failure(
                "project.install_dependencies",
                "project_path does not resolve to an existing "
                "package.json file",
            ).to_dict()
        toolchain = NodeToolchain(self._config)
        manager = toolchain.package_manager
        if manager is None:
            return ThreeOperationResult.failure(
                "project.install_dependencies",
                "Node package manager was not found: "
                f"{self._config.package_manager}",
            ).to_dict()
        command = [str(manager), "install"]
        payload = {
            "command": command,
            "cwd": str(project_dir),
            "package_manager": self._config.package_manager,
            "dry_run": dry_run,
        }
        if dry_run:
            return ThreeOperationResult.success(
                "project.install_dependencies",
                payload=payload,
            ).to_dict()
        result = toolchain.run(
            command,
            cwd=project_dir,
            timeout=timeout,
        )
        payload.update(result.to_dict())
        if not result.ok:
            return ThreeOperationResult.failure(
                "project.install_dependencies",
                "Dependency installation failed with exit code "
                f"{result.returncode}",
                payload=payload,
            ).to_dict()
        return ThreeOperationResult.success(
            "project.install_dependencies",
            artifacts=[
                {
                    "type": "node_modules",
                    "path": str(project_dir / "node_modules"),
                    "state": "ready",
                }
            ],
            payload=payload,
        ).to_dict()

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        project_dir = self._config.project_dir
        project_file = self._config.project_file
        three_root = self._config.three_root

        if self._config.project_path is None:
            errors.append("project_path is not configured")
        elif project_file is None or not project_file.is_file():
            errors.append(
                "project_path does not resolve to an existing "
                "package.json file"
            )
        if project_dir is not None:
            if not (project_dir / "index.html").is_file():
                errors.append(
                    "project is missing its index.html entry document"
                )
            if not (project_dir / "src" / "main.js").is_file():
                warnings.append(
                    "project is missing src/main.js; the runtime host "
                    "will not boot"
                )
            if not (project_dir / "public").is_dir():
                warnings.append(
                    "project is missing its public/ static root; "
                    "asset import will create it"
                )
            if not (project_dir / "node_modules" / "three").is_dir():
                warnings.append(
                    "three is not installed; run "
                    "project.install_dependencies() before build or "
                    "runtime operations"
                )
        if three_root is not None and not three_root.is_dir():
            warnings.append(
                f"three_root does not exist: {three_root}"
            )

        payload = {
            "api_version": self._config.api_version,
            "project_file": str(project_file or ""),
            "project_dir": str(project_dir or ""),
            "three_root": str(three_root or ""),
            "engine_version": self._config.engine_version,
        }
        if errors:
            return ThreeOperationResult.failure(
                "project.validate",
                *errors,
                warnings=warnings,
                payload=payload,
            ).to_dict()
        return ThreeOperationResult.success(
            "project.validate",
            warnings=warnings,
            payload=payload,
        ).to_dict()
