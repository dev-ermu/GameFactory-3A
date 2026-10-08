"""
Godot 4引擎适配器测试

GodotEngineLogicTests

    逻辑测试。返回值结构、注册表事务、路径封闭性、配置解析。
    此测试不依赖于Godot真实运行环境。

GodotMockTransportTests

    验证调用引擎的流程：argv、超时、进程组、失败回滚。
    `GodotTransport.run`被替换成记录器，**不启动任何进程**。

GodotRealEngineTests

    验证「引擎契约是否成立」：`.import` sidecar 布局、Godot 的报错文本、
    退出码 0 却没产物。使用Godot真实运行环境。
    
    由`A3GAME_TEST_GODOT_EXECUTABLE`指定Godot可执行文件，设置为空则整体跳过。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import struct
import base64
import hashlib
import time
from pathlib import Path
from unittest import mock

from engine_adapters.godot import GodotClient
from engine_adapters.godot._internal import godot_import_error_lines
from engine_adapters.godot._internal.transport import GodotProcessResult
from engine_adapters.godot.contracts import GodotOperationResult
from engine_adapters.godot.config import MINIMUM_GODOT_VERSION, probe_godot_version
from config import settings
from pipeline.common import paths
from pipeline.common.code_mapping import (
    normalize_engine_id,
    resolve_browser_backend_registration,
    resolve_engine_registration,
)

GODOT_EXECUTABLE: Path = settings.godot_executable

#: 适配器每次返回必须正好是这七个key
RESULT_KEYS = {
    "ok",
    "operation",
    "artifacts",
    "diagnostics",
    "warnings",
    "errors",
    "payload",
}


class EngineTestBase(unittest.TestCase):
    """
    三个测试类共用的沙箱：临时目录 + 配置注入 + 空工程。

    配置**只在`settings`实例上注入**，因此实际配置项并不会泄露到测试中。
    """

    def setUp(self) -> None:
        test_data_dir = Path(settings.test_data_dir)
        test_data_dir.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="godot-adapter-test-", dir=test_data_dir)
        self.addCleanup(self.temporary.cleanup)

        # 给paths.OUTPUT_ROOT进行patch
        self.root = Path(self.temporary.name)
        self.output_root_patch = mock.patch.object(paths, "OUTPUT_ROOT", 
            self.root / "outputs"
        )
        self.output_root_patch.start()
        self.addCleanup(self.output_root_patch.stop)

        self.settings_patch = mock.patch.multiple(
            settings,
            godot_data_root=str(self.root / "adapter-data"),
            godot_artifact_registry=None,
            godot_executable=None,
            godot_project=None,
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

        self.project = self.root / "GodotProject"
        self.client = GodotClient(
            project_path=self.project,
            godot_executable=GODOT_EXECUTABLE,
            editor_timeout=120,
            import_timeout=120,
        )

    # todo: 写的什么东西
    def assert_result(self, result: dict, *, ok: bool | None = None) -> None:
        """返回值必须正好是`RESULT_KEYS`，且永远可 JSON 序列化。"""
        self.assertEqual(RESULT_KEYS, set(result), result)
        json.dumps(result, allow_nan=False)
        if ok is not None:
            self.assertIs(result["ok"], ok, result)

    @staticmethod
    def corrupt_embedded_texture_gltf() -> bytes:
        mesh_buffer = struct.pack(
            "<9f3H",
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0,
            1,
            2,
        )
        document = {
            "asset": {"version": "2.0", "generator": "GameFactory-3A test"},
            "buffers": [
                {
                    "uri": "data:application/octet-stream;base64,"
                    + base64.b64encode(mesh_buffer).decode("ascii"),
                    "byteLength": len(mesh_buffer),
                }
            ],
            "bufferViews": [
                {"buffer": 0, "byteOffset": 0, "byteLength": 36, "target": 34962},
                {
                    "buffer": 0,
                    "byteOffset": 36,
                    "byteLength": 6,
                    "target": 34963,
                },
            ],
            "accessors": [
                {
                    "bufferView": 0,
                    "componentType": 5126,
                    "count": 3,
                    "type": "VEC3",
                    "min": [0.0, 0.0, 0.0],
                    "max": [1.0, 1.0, 0.0],
                },
                {
                    "bufferView": 1,
                    "componentType": 5123,
                    "count": 3,
                    "type": "SCALAR",
                },
            ],
            "images": [{"uri": "data:image/png;base64,bm90IGEgcG5n"}],
            "textures": [{"source": 0}],
            "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
            "meshes": [
                {
                    "primitives": [
                        {
                            "attributes": {"POSITION": 0},
                            "indices": 1,
                            "material": 0,
                        }
                    ]
                }
            ],
            "nodes": [{"mesh": 0}],
            "scenes": [{"nodes": [0]}],
            "scene": 0,
        }
        return json.dumps(document, separators=(",", ":")).encode("utf-8")

    def godot_import_cache(self, target: Path) -> dict[str, bytes]:
        resource_path = "res://" + target.relative_to(self.project).as_posix()
        digest = hashlib.md5(resource_path.encode()).hexdigest()
        cache_root = self.project / ".godot" / "imported"
        return {
            path.name: path.read_bytes()
            for path in sorted(cache_root.glob(f"{target.name}-{digest}.*"))
            if path.is_file()
        }

    def make_artifact(
        self,
        *,
        task_id: str,
        suffix: str,
        content: bytes,
        task_kind: str = "3d_object",
        artifact_key: str = "glb_path",
    ) -> tuple[dict[str, str], Path]:
        game_id = "godot_adapter_test"
        run_id = "run_001"
        task_dir = paths.task_output_dir(game_id, task_kind, task_id, run_id=run_id)
        artifact = task_dir / f"artifact{suffix}"
        artifact.write_bytes(content)
        (task_dir / "meta.json").write_text(
            json.dumps(
                {
                    "game_id": game_id,
                    "run_id": run_id,
                    "task_kind": task_kind,
                    "task_id": task_id,
                    artifact_key: str(artifact),
                }
            ),
            encoding="utf-8",
        )
        return (
            {
                "game_id": game_id,
                "run_id": run_id,
                "task_kind": task_kind,
                "task_id": task_id,
                "artifact_key": artifact_key,
            },
            artifact,
        )


class GodotEngineLogicTests(EngineTestBase):
    """纯逻辑层：不依赖引擎产物，验证适配器自身的契约与事务语义。

    运行时会话状态、测试报告路径、配置解析、跨引擎方法签名一致性。
    """

    def setUp(self) -> None:
        super().setUp()
        self.created = self.client.project.create(project_name="Godot Test")
    
    def test_game_create(self) -> None:
        """测试Godot项目是否创建成功"""
        self.assert_result(self.created, ok=True)

    def test_addons_install_rejects(self) -> None:
        """若插件为autoload，安装插件就会失败，测试所有addons目录所有内容都会还原"""
        project_file = self.project / "project.godot"
        custom_autoload = 'A3GameRuntime="*res://addons/custom/runtime.gd"'

        original_text = project_file.read_text()
        project_file.write_text(
            f"""{original_text}\n[autoload] ; preserve this section comment\n{custom_autoload}\n""",
            encoding='utf-8'
        )

        project_before = project_file.read_bytes()
        # 遍历文件夹条目
        addons_dir_before = sorted(
            path.relative_to(self.project).as_posix() for path in (self.project / "addons").rglob("*")
        )

        conflict = self.client.plugin.install_framework()

        self.assert_result(conflict, ok=False)
        self.assertIn("FileExistsError", " ".join(conflict["errors"]))
        self.assertIn("replace_existing=True", " ".join(conflict["errors"]))
        self.assertEqual(project_before, project_file.read_bytes())
        addons_dir_after = sorted(path.relative_to(self.project).as_posix() for path in (self.project / "addons").rglob("*"))
        self.assertEqual(addons_dir_before, addons_dir_after)

        addon_target = self.project / "addons" / "a3game_playable"
        self.assertFalse(addon_target.exists())

    def test_testing_report_path_failures(self) -> None:
        """测试run_automation_tests函数接收到错误参数时，处理是否正确"""
        regular_file = self.project / "report-parent"
        regular_file.write_text("not a directory", encoding="utf-8")

        # 模拟传参错误
        result = self.client.testing.run_automation_tests(
            report_path=regular_file / "report.json"
        )

        self.assert_result(result, ok=False)
        self.assertIn("NotADirectoryError", " ".join(result["errors"]))
        self.assertEqual(
            str((regular_file / "report.json").resolve(strict=False)),
            result["payload"]["report_path"],
        )


    def test_testing_rejects_report_input_collisions_without_writing(self) -> None:
        project_file = self.project / "project.godot"
        original_project = project_file.read_bytes()
        project_collision = self.client.testing.run_automation_tests(
            report_path=project_file
        )
        self.assert_result(project_collision, ok=False)
        self.assertIn("protected input", " ".join(project_collision["errors"]))
        self.assertEqual(original_project, project_file.read_bytes())

        custom_runner = self.project / "tests" / "custom_runner.gd"
        custom_runner.write_bytes(b"extends SceneTree\n")
        original_runner = custom_runner.read_bytes()
        runner_collision = self.client.testing.run_automation_tests(
            script="res://tests/custom_runner.gd",
            report_path=custom_runner,
        )
        self.assert_result(runner_collision, ok=False)
        self.assertIn("protected input", " ".join(runner_collision["errors"]))
        self.assertEqual(original_runner, custom_runner.read_bytes())

        test_script = self.project / "tests" / "test_preserved.gd"
        test_script.write_bytes(b"extends RefCounted\nfunc run_test(): return true\n")
        original_test = test_script.read_bytes()
        test_collision = self.client.testing.run_automation_tests(
            report_path=test_script
        )
        self.assert_result(test_collision, ok=False)
        self.assertIn("protected input", " ".join(test_collision["errors"]))
        self.assertEqual(original_test, test_script.read_bytes())

    def test_obj_format_and_non_serializable_parameters_fail_structurally(self) -> None:
        """格式不被支持、参数不可序列化时，适配器返回结构化失败且不污染状态。
        """
        obj_source, _ = self.make_artifact(
            task_id="unsupported-obj",
            suffix=".obj",
            content=b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n",
        )
        for asset_type in (
            "environment",
            "prop",
            "scene",
            "static_mesh",
            "weapon",
        ):
            with self.subTest(asset_type=asset_type):
                obj_validation = self.client.assets.validate(obj_source, asset_type)
                self.assert_result(obj_validation, ok=False)
                self.assertIn(
                    f"Unsupported {asset_type} format .obj",
                    obj_validation["errors"][0],
                )
        self.assert_result(self.client.world.build(obj_source), ok=False)

        # `object()` 满足 `Mapping` 注解，不是类型错误；它验证的是「参数必须能
        # JSON 序列化」这条真实契约，以及失败时不得抛裸异常。
        invalid_join = self.client.runtime.sessions.join(parameters={"bad": object()})
        self.assert_result(invalid_join, ok=False)
        self.assertEqual("runtime.sessions.join", invalid_join["operation"])
        json.dumps(invalid_join)
        self.assertEqual(
            [], self.client.runtime.sessions.snapshot()["payload"]["sessions"]
        )

        joined = self.client.runtime.sessions.join()
        self.assert_result(joined, ok=True)

    def test_runtime_session_reset_and_clear_remove_only_target_state(self) -> None:
        messages: list[dict] = []

        def acknowledge(message: dict, **_kwargs) -> dict:
            messages.append(dict(message))
            return {"ok": True, "operation": message["operation"], "reachable": True}

        sessions = self.client.runtime.sessions
        with mock.patch.object(sessions, "_send", side_effect=acknowledge):
            joined_default = sessions.join(participant_id="default")
            joined_arena_a = sessions.join(participant_id="arena-a", world_id="arena")
            joined_arena_b = sessions.join(participant_id="arena-b", world_id="arena")
            joined_lobby = sessions.join(participant_id="lobby", world_id="lobby")
            for joined in (
                joined_default,
                joined_arena_a,
                joined_arena_b,
                joined_lobby,
            ):
                self.assert_result(joined, ok=True)

            reset_arena = sessions.reset_world(world_id="arena")
            self.assert_result(reset_arena, ok=True)
            self.assertEqual("arena", reset_arena["payload"]["world_id"])
            self.assertEqual(2, reset_arena["payload"]["removed_sessions"])
            self.assertEqual(2, reset_arena["payload"]["sessions_remaining"])
            self.assertEqual(0, sessions.snapshot(world_id="arena")["payload"]["count"])
            self.assertEqual(1, sessions.snapshot(world_id="lobby")["payload"]["count"])

            repeated_reset = sessions.reset_world(world_id="arena")
            self.assert_result(repeated_reset, ok=True)
            self.assertEqual(0, repeated_reset["payload"]["removed_sessions"])
            self.assertEqual(2, repeated_reset["payload"]["sessions_remaining"])

            reset_default = sessions.reset_world()
            self.assert_result(reset_default, ok=True)
            self.assertEqual("world_001", reset_default["payload"]["world_id"])
            self.assertEqual(1, reset_default["payload"]["removed_sessions"])
            self.assertEqual(1, reset_default["payload"]["sessions_remaining"])
            self.assertEqual(
                ["lobby"],
                [
                    session["world_id"]
                    for session in sessions.snapshot()["payload"]["sessions"]
                ],
            )

            clear_retained = sessions.clear_entity(
                controller_id=joined_lobby["payload"]["controller_id"],
                destroy_actor=False,
            )
            self.assert_result(clear_retained, ok=True)
            self.assertFalse(clear_retained["payload"]["destroy_actor"])
            self.assertEqual(1, clear_retained["payload"]["removed_sessions"])
            self.assertEqual(0, clear_retained["payload"]["sessions_remaining"])
            self.assertEqual(
                {
                    "operation": "entity.clear",
                    "entity_id": joined_lobby["payload"]["entity_id"],
                    "destroy_actor": False,
                },
                messages[-1],
            )

            joined_destroy = sessions.join(participant_id="destroy", world_id="arena")
            clear_destroyed = sessions.clear_entity(
                entity_id=joined_destroy["payload"]["entity_id"]
            )
            self.assert_result(clear_destroyed, ok=True)
            self.assertTrue(clear_destroyed["payload"]["destroy_actor"])
            self.assertEqual(1, clear_destroyed["payload"]["removed_sessions"])
            self.assertEqual(0, sessions.snapshot()["payload"]["count"])

            message_count = len(messages)
            missing = sessions.clear_entity(entity_id="missing")
            self.assert_result(missing, ok=False)
            self.assertEqual(message_count, len(messages))

        reset_messages = [
            message for message in messages if message["operation"] == "world.reset"
        ]
        self.assertEqual(
            ["arena", "arena", "world_001"],
            [message["world_id"] for message in reset_messages],
        )


    def test_runtime_leave_deactivates_controller_and_rejects_false_input(self) -> None:
        messages: list[dict] = []

        def acknowledge(message: dict, **_kwargs) -> dict:
            messages.append(dict(message))
            if message["operation"] == "session.input" and message["input"]["seq"] == 2:
                return {
                    "ok": False,
                    "operation": message["operation"],
                    "reachable": True,
                    "error": "Unknown controller_id",
                }
            return {
                "ok": True,
                "operation": message["operation"],
                "reachable": True,
            }

        sessions = self.client.runtime.sessions
        with mock.patch.object(sessions, "_send", side_effect=acknowledge):
            joined = sessions.join(participant_id="lifecycle")
            self.assert_result(joined, ok=True)
            controller_id = joined["payload"]["controller_id"]

            accepted = sessions.apply_input(controller_id, move_x=0.5, seq=1)
            self.assert_result(accepted, ok=True)
            accepted_input = dict(accepted["payload"]["input"])

            rejected_by_runtime = sessions.apply_input(
                controller_id,
                move_x=0.75,
                seq=2,
            )
            self.assert_result(rejected_by_runtime, ok=False)
            self.assertIn("rejected", " ".join(rejected_by_runtime["errors"]))
            self.assertEqual(
                accepted_input,
                sessions.snapshot()["payload"]["sessions"][0]["last_input"],
            )

            left = sessions.leave(controller_id=controller_id)
            self.assert_result(left, ok=True)
            self.assertFalse(left["payload"]["active"])
            self.assertFalse(left["payload"]["online"])
            message_count = len(messages)

            after_leave = sessions.apply_input(controller_id, move_x=1.0, seq=3)
            heartbeat = sessions.heartbeat(controller_id)
            self.assert_result(after_leave, ok=False)
            self.assert_result(heartbeat, ok=False)
            self.assertEqual(message_count, len(messages))

            snapshot = sessions.snapshot()["payload"]["sessions"][0]
            self.assertFalse(snapshot["active"])
            self.assertFalse(snapshot["online"])
            self.assertEqual(accepted_input, snapshot["last_input"])


    def test_runtime_participant_reconnect_replaces_active_controller(self) -> None:
        native_sessions: dict[str, dict] = {}
        messages: list[dict] = []

        def bridge(message: dict, **_kwargs) -> dict:
            messages.append(dict(message))
            operation = message["operation"]
            if operation == "status":
                return {
                    "ok": True,
                    "operation": operation,
                    "reachable": True,
                    "sessions": len(native_sessions),
                }
            if operation == "session.join":
                replaced = [
                    controller_id
                    for controller_id, session in native_sessions.items()
                    if session["participant_id"] == message["participant_id"]
                ]
                if any(
                    native_sessions[controller_id]["entity_id"] != message["entity_id"]
                    for controller_id in replaced
                ):
                    return {
                        "ok": False,
                        "operation": operation,
                        "reachable": True,
                        "error": "participant entity mismatch",
                    }
                for controller_id in replaced:
                    native_sessions.pop(controller_id)
                native_sessions[message["controller_id"]] = dict(message)
                return {
                    "ok": True,
                    "operation": operation,
                    "reachable": True,
                    "replaced_controllers": len(replaced),
                    "sessions": len(native_sessions),
                }
            if operation == "session.leave":
                native_sessions.pop(message["controller_id"], None)
                return {
                    "ok": True,
                    "operation": operation,
                    "reachable": True,
                    "sessions": len(native_sessions),
                }
            if operation == "session.input":
                accepted = message["controller_id"] in native_sessions
                return {
                    "ok": accepted,
                    "operation": operation,
                    "reachable": True,
                    "error": "" if accepted else "Unknown controller_id",
                }
            if operation == "entity.clear":
                removed = [
                    controller_id
                    for controller_id, session in native_sessions.items()
                    if session["entity_id"] == message["entity_id"]
                ]
                for controller_id in removed:
                    native_sessions.pop(controller_id)
                return {
                    "ok": True,
                    "operation": operation,
                    "reachable": True,
                    "removed_sessions": len(removed),
                    "sessions": len(native_sessions),
                }
            raise AssertionError(f"unexpected bridge operation: {operation}")

        sessions = self.client.runtime.sessions
        with mock.patch.object(sessions, "_send", side_effect=bridge):
            first = sessions.join(participant_id="reconnect", world_id="arena")
            second = sessions.join(participant_id="reconnect", world_id="ignored")
            self.assert_result(first, ok=True)
            self.assert_result(second, ok=True)
            first_controller = first["payload"]["controller_id"]
            second_controller = second["payload"]["controller_id"]
            self.assertNotEqual(first_controller, second_controller)
            self.assertEqual(
                first["payload"]["entity_id"], second["payload"]["entity_id"]
            )
            self.assertEqual("arena", second["payload"]["world_id"])
            self.assertEqual(1, second["payload"]["bridge"]["replaced_controllers"])

            message_count = len(messages)
            old_input = sessions.apply_input(first_controller, seq=1)
            self.assert_result(old_input, ok=False)
            self.assertEqual(message_count, len(messages))
            native_old_input = sessions._send(
                {
                    "operation": "session.input",
                    "controller_id": first_controller,
                    "input": {"seq": 1},
                }
            )
            self.assertFalse(native_old_input["ok"])

            snapshot = sessions.snapshot()["payload"]
            participant_sessions = [
                session
                for session in snapshot["sessions"]
                if session["participant_id"] == "reconnect"
            ]
            self.assertEqual(2, len(participant_sessions))
            self.assertEqual(
                [False, True], [item["active"] for item in participant_sessions]
            )
            self.assertEqual(1, snapshot["active_count"])
            self.assertEqual(snapshot["active_count"], sessions.probe()["sessions"])

            left = sessions.leave(participant_id="reconnect")
            self.assert_result(left, ok=True)
            self.assertEqual(second_controller, left["payload"]["controller_id"])
            self.assertEqual(second_controller, messages[-1]["controller_id"])
            new_input = sessions.apply_input(second_controller, seq=2)
            self.assert_result(new_input, ok=False)
            native_new_input = sessions._send(
                {
                    "operation": "session.input",
                    "controller_id": second_controller,
                    "input": {"seq": 2},
                }
            )
            self.assertFalse(native_new_input["ok"])
            snapshot = sessions.snapshot()["payload"]
            self.assertEqual(0, snapshot["active_count"])
            self.assertEqual(snapshot["active_count"], sessions.probe()["sessions"])

            cleared = sessions.clear_entity(participant_id="reconnect")
            self.assert_result(cleared, ok=True)
            self.assertEqual(2, cleared["payload"]["removed_sessions"])
            self.assertEqual(0, sessions.snapshot()["payload"]["count"])


    def test_corrupt_artifact_registry_fails_without_overwriting_source(
        self,
    ) -> None:
        registry_path = self.client._config.artifact_registry_path
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        first_entry = {
            "artifact_id": "duplicate",
            "asset_id": "first",
            "type": "prop",
            "backend_path": "res://assets/imported/props/first.glb",
            "source_path": "/generated/first.glb",
            "backend_class": "PackedScene",
            "state": "ready",
            "spawnable": True,
            "metadata": {},
        }
        second_entry = {
            **first_entry,
            "asset_id": "second",
            "backend_path": "res://assets/imported/props/second.glb",
            "source_path": "/generated/second.glb",
        }
        missing_asset_id = dict(first_entry)
        missing_asset_id.pop("asset_id")
        malformed_payloads = {
            "truncated_json": b'{"artifacts":[',
            "wrong_schema": json.dumps(
                {
                    "schema_version": "gamefactory3a.godot.artifacts.v0",
                    "artifacts": [],
                }
            ).encode(),
            "top_level_list": b"[]",
            "wrong_artifacts_container": json.dumps(
                {
                    "schema_version": "gamefactory3a.godot.artifacts.v1",
                    "artifacts": {},
                }
            ).encode(),
            "non_object_entry": json.dumps(
                {
                    "schema_version": "gamefactory3a.godot.artifacts.v1",
                    "artifacts": ["not-an-artifact"],
                }
            ).encode(),
            "missing_required_field": json.dumps(
                {
                    "schema_version": "gamefactory3a.godot.artifacts.v1",
                    "artifacts": [missing_asset_id],
                }
            ).encode(),
            "wrong_field_type": json.dumps(
                {
                    "schema_version": "gamefactory3a.godot.artifacts.v1",
                    "artifacts": [{**first_entry, "spawnable": "yes"}],
                }
            ).encode(),
            "wrong_metadata_type": json.dumps(
                {
                    "schema_version": "gamefactory3a.godot.artifacts.v1",
                    "artifacts": [{**first_entry, "metadata": []}],
                }
            ).encode(),
            "duplicate_artifact_id": json.dumps(
                {
                    "schema_version": "gamefactory3a.godot.artifacts.v1",
                    "artifacts": [first_entry, second_entry],
                }
            ).encode(),
            "ambiguous_asset_id": json.dumps(
                {
                    "schema_version": "gamefactory3a.godot.artifacts.v1",
                    "artifacts": [
                        first_entry,
                        {
                            **second_entry,
                            "artifact_id": "second-artifact",
                            "asset_id": "first",
                        },
                    ],
                }
            ).encode(),
            "ambiguous_backend_path": json.dumps(
                {
                    "schema_version": "gamefactory3a.godot.artifacts.v1",
                    "artifacts": [
                        first_entry,
                        {
                            **second_entry,
                            "artifact_id": "second-artifact",
                            "backend_path": first_entry["backend_path"],
                        },
                    ],
                }
            ).encode(),
        }

        for name, malformed in malformed_payloads.items():
            with self.subTest(name=name):
                registry_path.write_bytes(malformed)
                listed = self.client.assets.list_registered()
                self.assert_result(listed, ok=False)
                self.assertIn("registry read failed", listed["errors"][0])
                with self.assertRaises((json.JSONDecodeError, TypeError, ValueError)):
                    self.client.assets._register_resource(
                        resource_path="res://assets/imported/recovery.glb",
                        asset_type="prop",
                        asset_id="must_not_replace_registry",
                    )
                self.assertEqual(malformed, registry_path.read_bytes())

        valid = json.dumps(
            {
                "schema_version": "gamefactory3a.godot.artifacts.v1",
                "artifacts": [],
            }
        ).encode()
        registry_path.write_bytes(valid)
        with mock.patch(
            "engine_adapters.godot._internal.registry.read_managed_text",
            side_effect=OSError("forced registry read failure"),
        ), mock.patch.object(
            self.client.assets._registry, "_write"
        ) as write:
            listed = self.client.assets.list_registered()
            self.assert_result(listed, ok=False)
            self.assertIn("forced registry read failure", listed["errors"][0])
            with self.assertRaisesRegex(OSError, "forced registry read failure"):
                self.client.assets._register_resource(
                    resource_path="res://assets/imported/recovery.glb",
                    asset_type="prop",
                    asset_id="must_not_replace_registry",
                )
            write.assert_not_called()
        self.assertEqual(valid, registry_path.read_bytes())


    def test_artifact_registry_rejects_ambiguous_upsert_without_writing(self) -> None:
        first = self.client.assets._register_resource(
            resource_path="res://assets/imported/props/first.glb",
            asset_type="prop",
            asset_id="shared-reference",
            backend_class="PackedScene",
        )
        registry_path = self.client._config.artifact_registry_path
        original = registry_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "ambiguous lookup reference"):
            self.client.assets._register_resource(
                resource_path="res://assets/imported/motions/second.glb",
                asset_type="motion",
                asset_id="shared-reference",
                backend_class="PackedScene",
            )
        self.assertEqual(original, registry_path.read_bytes())

        with self.assertRaisesRegex(ValueError, "ambiguous lookup reference"):
            self.client.assets._register_resource(
                resource_path="res://assets/imported/props/third.glb",
                asset_type="prop",
                asset_id=first.artifact_id,
                backend_class="PackedScene",
            )
        self.assertEqual(original, registry_path.read_bytes())


    def test_invalid_source_arguments_return_structured_failures(self) -> None:
        class MalformedSource(dict):
            def keys(self):
                raise RuntimeError("broken mapping")

            def __iter__(self):
                raise RuntimeError("broken mapping")

            def __str__(self) -> str:
                raise RuntimeError("unprintable source")

        unsafe_path = self.root / "not-a-component"
        json_unsafe_source = {
            "game_id": unsafe_path,
            "run_id": "run",
            "task_kind": "3d_object",
            "task_id": "task",
            "nested": {
                "paths": [unsafe_path, (unsafe_path,)],
                "not_finite": float("nan"),
            },
        }
        for source in (
            None,
            "not-a-source-descriptor",
            MalformedSource(),
            json_unsafe_source,
        ):
            with self.subTest(source_type=type(source).__name__):
                results = (
                    self.client.assets.import_asset(source, "prop"),
                    self.client.assets.validate(source, "prop"),
                    self.client.assets.resolve_source(source, asset_type="prop"),
                    self.client.plugin.install(source),
                    self.client.bindings.bind_pbr_material(
                        asset_id="invalid",
                        source=source,
                        mesh_assets=["missing"],
                    ),
                    self.client.world.build(source),
                )
                for result in results:
                    self.assert_result(result, ok=False)
                    self.assertIsInstance(result["payload"].get("source"), dict)
                    json.loads(json.dumps(result, allow_nan=False))
                if source is json_unsafe_source:
                    normalized = results[0]["payload"]["source"]
                    self.assertEqual(str(unsafe_path), normalized["game_id"])
                    self.assertEqual(
                        [str(unsafe_path), [str(unsafe_path)]],
                        normalized["nested"]["paths"],
                    )
                    self.assertEqual("nan", normalized["nested"]["not_finite"])


    def test_runtime_process_launch_group_settings_are_cross_platform(self) -> None:
        from engine_adapters.godot._internal import transport as transport_module

        with mock.patch.object(transport_module.os, "name", "posix"):
            self.assertEqual(
                {"start_new_session": True},
                transport_module.managed_process_kwargs(),
            )
        with mock.patch.object(transport_module.os, "name", "nt"):
            windows = transport_module.managed_process_kwargs()
        self.assertEqual(
            int(
                getattr(
                    transport_module.subprocess,
                    "CREATE_NEW_PROCESS_GROUP",
                    0x00000200,
                )
            ),
            windows["creationflags"],
        )


    def test_install_directory_contains_only_install_entry_points(self) -> None:
        wrapper_root = Path("scripts/engine_install/godot")
        self.assertEqual(
            {"README.md", "README_zh.md", "install.cmd", "install.py", "install.sh"},
            {item.name for item in wrapper_root.iterdir() if item.is_file()},
        )
        for removed in (
            "create_project.cmd",
            "create_project.sh",
            "import_asset.cmd",
            "import_asset.sh",
            "run.cmd",
            "run.sh",
        ):
            self.assertFalse((wrapper_root / removed).exists())
        readme = (wrapper_root / "README.md").read_text(encoding="utf-8")
        self.assertIn("engine_adapters.godot", readme)
        self.assertIn("create-project", readme)
        self.assertIn("import-asset", readme)
        self.assertIn("launch-game", readme)
        self.assertNotIn("godot/create_project.sh", readme)
        self.assertNotIn("godot/import_asset.sh", readme)
        self.assertNotIn("godot/run.sh", readme)


    def test_compatibility_godot_executable_priority_matches_client(self) -> None:
        from engine_adapters.godot.config import GodotClientConfig
        from scripts import import_generated_asset as compatibility

        explicit = self.root / "explicit-godot"
        configured = self.root / "configured-godot"
        # Godot 可执行文件只有一个变量名 `A3GAME_GODOT_EXECUTABLE`，没有旧名回退。
        # 适配器从 `settings` 读；`compatibility` 是尚未迁移的独立配置面，仍读环境
        # 变量，所以这里两侧都给同一个值——断言的正是「两个入口解析结果一致」。
        with mock.patch.dict(
            os.environ, {"A3GAME_GODOT_EXECUTABLE": str(configured)}, clear=False
        ), mock.patch.multiple(settings, godot_executable=str(configured)):
            self.assertEqual(configured.resolve(), compatibility.find_godot())
            self.assertEqual(
                configured.resolve(),
                GodotClientConfig.resolve(project_path=self.project).godot_executable,
            )
            # 显式入参优先于配置。
            self.assertEqual(
                explicit.resolve(),
                compatibility.find_godot(str(explicit)),
            )


    def test_compatibility_launcher_reports_timeout(self) -> None:
        from scripts import import_generated_asset as compatibility

        with mock.patch.object(
            compatibility.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(
                ["godot", "--import"], 2, output="partial output"
            ),
        ):
            result = compatibility.run_engine(
                ["godot", "--import"],
                self.root / "timeout-report.json",
                "godot",
                2,
                False,
            )
        self.assertIs(result["ok"], False)
        self.assertIn("timed out after 2 seconds", result["error"])
        self.assertEqual("partial output", result["stdout_tail"])


class GodotMockTransportTests(EngineTestBase):
    """替身层：验证**我们怎么调用引擎**，全程不启动任何进程。

    只包含断言对象是「适配器发给引擎的命令」的用例——argv 形状、超时、
    进程组、CLI 结构化错误。引擎**实际**会产生什么（导入产物、导出文件、
    原生报告、场景可实例化）属于真机层，不在这里用替身假装。
    """

    def setUp(self) -> None:
        super().setUp()
        # 基类造的 client 指向假可执行文件；这里把 `GodotTransport.run` 换成
        # mock，于是没有任何进程会被启动。
        self.transport = mock.MagicMock(spec=GodotProcessResult)
        self.transport.return_value = GodotProcessResult(
            command=(), returncode=0, stdout="", stderr="", duration_seconds=0.0
        )
        patcher = mock.patch(
            "engine_adapters.godot._internal.transport.GodotTransport.run",
            self.transport,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        created = self.client.project.create(project_name="Godot Test")
        self.assert_result(created, ok=True)

    def assert_godot_called(self, *fragments: str) -> None:
        """断言引擎被调用过，且参数里含有这些片段。"""
        calls = [call.args[0] for call in self.transport.call_args_list if call.args]
        self.assertTrue(calls, "GodotTransport.run was never called")
        rendered = [" ".join(map(str, args)) for args in calls]
        for fragment in fragments:
            self.assertTrue(
                any(fragment in line for line in rendered),
                "%r not in any Godot invocation: %s" % (fragment, rendered),
            )


    def test_project_create_rejects_wrong_managed_path_types_without_writing(
        self,
    ) -> None:
        project_file = self.root / "project-root-is-a-file"
        project_file.write_bytes(b"unchanged")
        root_client = GodotClient(
            project_path=project_file,
            godot_executable=GODOT_EXECUTABLE,
        )

        root_result = root_client.project.create(project_name="Reject File Root")

        self.assert_result(root_result, ok=False)
        self.assertIn("directory", " ".join(root_result["errors"]).lower())
        self.assertEqual(b"unchanged", project_file.read_bytes())

        project = self.root / "managed-directory-is-a-file"
        project.mkdir()
        assets = project / "assets"
        assets.write_bytes(b"unchanged")
        directory_client = GodotClient(
            project_path=project,
            godot_executable=GODOT_EXECUTABLE,
        )

        directory_result = directory_client.project.create(
            project_name="Reject File Directory"
        )

        self.assert_result(directory_result, ok=False)
        self.assertIn("directory", " ".join(directory_result["errors"]).lower())
        self.assertEqual(b"unchanged", assets.read_bytes())
        self.assertFalse((project / "project.godot").exists())
        self.assertFalse((project / "main.tscn").exists())


    def test_project_create_explicit_directory_and_marker_are_equivalent(
        self,
    ) -> None:
        client = GodotClient(godot_executable=GODOT_EXECUTABLE)
        for identity in ("directory", "project_file"):
            for dry_run in (True, False):
                with self.subTest(identity=identity, dry_run=dry_run):
                    project = self.root / f"create-{identity}-{dry_run}"
                    project_file = project / "project.godot"
                    project_identity = (
                        project_file if identity == "project_file" else project
                    )

                    result = client.project.create(
                        project_path=project_identity,
                        project_name="Project Identity",
                        dry_run=dry_run,
                    )

                    self.assert_result(result, ok=True)
                    self.assertEqual(
                        str(project.resolve(strict=False)),
                        result["payload"]["project_path"],
                    )
                    self.assertEqual(
                        str(project_file.resolve(strict=False)),
                        result["payload"]["project_file"],
                    )
                    self.assertFalse(project_file.is_dir())
                    self.assertEqual(not dry_run, project_file.is_file())
                    self.assertFalse((project_file / "project.godot").exists())


    def test_cli_configuration_failures_are_structured_json(self) -> None:
        cases = (
            (
                ["--runtime-port", "70000", "info"],
                {},
                "Godot runtime UDP port",
            ),
            (
                [
                    "--project",
                    str(self.project),
                    "--godot",
                    str(GODOT_EXECUTABLE),
                    "info",
                ],
                {"A3GAME_GODOT_EDITOR_TIMEOUT": "0"},
                "editor_timeout",
            ),
        )
        for arguments, overrides, expected_error in cases:
            with self.subTest(arguments=arguments):
                environment = os.environ.copy()
                for name in (
                    "A3GAME_GODOT_RUNTIME_PORT",
                    "A3GAME_GODOT_EDITOR_TIMEOUT",
                    "A3GAME_GODOT_IMPORT_TIMEOUT",
                ):
                    environment.pop(name, None)
                environment.update(overrides)
                process = subprocess.run(
                    [sys.executable, "-m", "engine_adapters.godot", *arguments],
                    cwd=Path(__file__).resolve().parents[1],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(1, process.returncode, process)
                result = json.loads(process.stdout)
                self.assert_result(result, ok=False)
                self.assertEqual("cli.info", result["operation"])
                self.assertIn(expected_error, " ".join(result["errors"]))
                self.assertNotIn("Traceback", process.stderr)


    def test_plugin_installs_reject_ambiguous_enabled_settings_atomically(
        self,
    ) -> None:
        task_dir = paths.task_output_dir(
            "godot_adapter_test",
            "3d_object",
            "ambiguous_plugin_source",
            run_id="run_001",
        )
        source_root = task_dir / "custom_addon"
        source_root.mkdir()
        (source_root / "plugin.cfg").write_text(
            '[plugin]\nname="Custom Add-on"\ndescription=""\n'
            'author="Test"\nversion="1.0"\nscript="plugin.gd"\n',
            encoding="utf-8",
        )
        (source_root / "plugin.gd").write_text(
            "@tool\nextends EditorPlugin\n",
            encoding="utf-8",
        )
        (task_dir / "meta.json").write_text(
            json.dumps(
                {
                    "game_id": "godot_adapter_test",
                    "run_id": "run_001",
                    "task_kind": "3d_object",
                    "task_id": "ambiguous_plugin_source",
                    "plugin_path": str(source_root),
                }
            ),
            encoding="utf-8",
        )
        source = {
            "game_id": "godot_adapter_test",
            "run_id": "run_001",
            "task_kind": "3d_object",
            "task_id": "ambiguous_plugin_source",
            "artifact_key": "plugin_path",
        }
        other_resource = "res://addons/last/plugin.cfg"

        for installer in ("framework", "custom"):
            target_resource = (
                "res://addons/a3game_playable/plugin.cfg"
                if installer == "framework"
                else "res://addons/custom_addon/plugin.cfg"
            )
            target_name = (
                "a3game_playable" if installer == "framework" else "custom_addon"
            )
            for layout in ("duplicate_keys", "duplicate_sections"):
                for target_first in (True, False):
                    label = f"{installer}-{layout}-{target_first}"
                    with self.subTest(case=label):
                        project = self.root / label
                        client = GodotClient(
                            project_path=project,
                            godot_executable=GODOT_EXECUTABLE,
                            editor_timeout=5,
                            import_timeout=5,
                        )
                        self.assert_result(
                            client.project.create(project_name=label),
                            ok=True,
                        )
                        first, second = (
                            (target_resource, other_resource)
                            if target_first
                            else (other_resource, target_resource)
                        )
                        declarations = (
                            "\n[editor_plugins]\n"
                            + f"enabled=PackedStringArray({json.dumps(first)})\n"
                        )
                        if layout == "duplicate_keys":
                            declarations += (
                                f"enabled=PackedStringArray({json.dumps(second)})\n"
                            )
                        else:
                            declarations += (
                                "\n[editor_plugins]\n"
                                + "enabled=PackedStringArray("
                                + json.dumps(second)
                                + ")\n"
                            )
                        project_file = project / "project.godot"
                        project_file.write_text(
                            project_file.read_text(encoding="utf-8") + declarations,
                            encoding="utf-8",
                        )
                        target = project / "addons" / target_name
                        target.mkdir()
                        marker = target / "user-marker.txt"
                        marker.write_text("preserve", encoding="utf-8")
                        project_before = project_file.read_bytes()

                        if installer == "framework":
                            result = client.plugin.install_framework(
                                replace_existing=True
                            )
                        else:
                            result = client.plugin.install(
                                source,
                                install_dir="custom_addon",
                                replace_existing=True,
                            )

                        self.assert_result(result, ok=False)
                        self.assertIn("ambiguous", " ".join(result["errors"]))
                        self.assertEqual(project_before, project_file.read_bytes())
                        self.assertEqual("preserve", marker.read_text(encoding="utf-8"))


    def test_configuration_and_failure_edges(self) -> None:
        with self.assertRaises(ValueError):
            GodotClient(
                project_path=self.project,
                godot_executable=GODOT_EXECUTABLE,
                api_version="v2",
            )
        missing = GodotClient(
            project_path=self.project,
            godot_executable=self.root / "missing-godot",
        )
        self.assert_result(missing.project.validate(), ok=False)
        missing_preset = self.client.build.project(
            preset="Missing", output_path="builds/missing"
        )
        self.assert_result(missing_preset, ok=False)
        # 配置只有一个来源：`settings` 单例，且每项只有一个环境变量名。
        with mock.patch.multiple(
            settings,
            godot_project=str(self.project),
            godot_executable=str(GODOT_EXECUTABLE),
        ):
            configured_client = GodotClient()
        self.assertEqual(self.project.resolve(), configured_client._config.project_dir)
        self.assertEqual(
            GODOT_EXECUTABLE.resolve(), configured_client._config.godot_executable
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
