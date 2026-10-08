"""Tests for gen_motion: retargeting, mapping registry and motion sources."""

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_TEST_DIR = _REPO_ROOT / "tests"
if str(_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_TEST_DIR))

import test_rigging_retarget  # noqa: E402
from tests.harness import (
    make_minimal_glb,
    retarget_info,
    retarget_mapping,
    stub_retarget_motion,
)

from operators.gen_motion.funcs.fetch_motion import (  # noqa: E402
    fetch_motion,
    list_motion_sources,
    measure_bvh_extent,
    suggest_global_scale,
)
from operators.gen_motion.funcs.retarget_utils.mapping_presets import (  # noqa: E402
    identify_motion_file,
    identify_source_skeleton,
    normalise_mapping,
    registry,
)
from operators.gen_motion.funcs.retarget_utils.validate_mapping import (  # noqa: E402
    load_and_validate_mapping,
)
from operators.gen_motion.funcs.retarget_motion import (  # noqa: E402
    _subprocess_env as _retarget_subprocess_env,
    ensure_retarget_runtime,
    normalise_mesh_ext,
    normalise_source_ext,
    retarget_motion,
)
from operators.gen_motion.metrics import evaluate  # noqa: E402
from operators.gen_motion.operator import GenMotionOperator  # noqa: E402


class MotionRetargetFixture:
    def __init__(self, root: Path):
        self.source = root / "source.bvh"
        self.target = root / "target.glb"
        self.rig = root / "target_rig.txt"
        self.mapping = root / "mapping.json"
        self.source.write_text(
            "HIERARCHY\nROOT Hips\nMOTION\nFrames: 1\n"
            "Frame Time: 0.033333\n",
            encoding="utf-8",
        )
        self.target.write_bytes(b"glTF" + bytes(64))
        self.rig.write_text(
            "joints joint0 0 0 0\nroot joint0\n"
            "skin 0 joint0 1.0\n",
            encoding="utf-8",
        )
        self.mapping.write_text(
            json.dumps(retarget_mapping(), indent=2),
            encoding="utf-8",
        )

    def task(self, *, mapping: bool = True) -> dict:
        return {
            "task_id": "retarget_unit",
            "task_type": "retarget",
            "source_motion_path": str(self.source),
            "target_glb_path": str(self.target),
            "target_rig_path": str(self.rig),
            "mapping_path": str(self.mapping) if mapping else None,
            "fps": 20,
        }


class TestGenMotionOperator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aaagf_motion_test_")
        self.root = Path(self.tmp.name)
        self.fixture = MotionRetargetFixture(self.root)
        self.retarget_fn = mock.Mock(side_effect=stub_retarget_motion)
        self.operator = GenMotionOperator(
            output_dir=str(self.root / "outputs"),
            retarget_fn=self.retarget_fn,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_explicit_mapping_writes_four_artifacts(self):
        result = self.operator.run(self.fixture.task())
        self.assertEqual(result["task_kind"], "motion")
        self.assertEqual(result["game_id"], "")
        for key in (
            "retargeted_fbx_path",
            "anim_only_fbx_path",
            "mapping_path",
            "retarget_info_path",
        ):
            path = Path(result[key])
            self.assertTrue(path.is_file(), key)
            self.assertGreater(path.stat().st_size, 0, key)
            self.assertTrue(path.name.startswith("retarget_unit"))
        self.assertEqual(
            json.loads(Path(result["mapping_path"]).read_text())["bone_map"],
            retarget_mapping()["bone_map"],
        )

    def test_missing_mapping_uses_automatic_mapping_path(self):
        result = self.operator.run(self.fixture.task(mapping=False))
        self.assertTrue(Path(result["mapping_path"]).is_file())
        self.assertIsNone(self.retarget_fn.call_args.kwargs["mapping_path"])

    def test_animation_only_can_be_disabled(self):
        task = self.fixture.task()
        task["export_anim_only"] = False
        result = self.operator.run(task)
        self.assertIsNone(result["anim_only_fbx_path"])

    def test_invalid_mapping_fails_before_function_call(self):
        self.fixture.mapping.write_text('{"bone_map": {}}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "non-empty 'bone_map'"):
            self.operator.run(self.fixture.task())
        self.retarget_fn.assert_not_called()

    def test_wrong_source_extension_is_rejected(self):
        bad_source = self.root / "source.txt"
        bad_source.write_text("not motion", encoding="utf-8")
        task = self.fixture.task()
        task["source_motion_path"] = str(bad_source)
        with self.assertRaisesRegex(ValueError, r"\.bvh'? or '?\.fbx"):
            self.operator.run(task)

    def test_obj_target_mesh_is_accepted_under_either_key(self):
        obj = self.root / "target.obj"
        obj.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
        for key in ("target_mesh_path", "target_glb_path"):
            task = self.fixture.task()
            task.pop("target_glb_path")
            task[key] = str(obj)
            task["task_id"] = f"obj_{key}"
            result = self.operator.run(task)
            self.assertTrue(Path(result["retargeted_fbx_path"]).is_file(), key)
            self.assertEqual(
                self.retarget_fn.call_args.kwargs["target_mesh_path"],
                str(obj),
            )

    def test_unusable_target_mesh_format_is_rejected(self):
        bad = self.root / "target.txt"
        bad.write_text("not a mesh", encoding="utf-8")
        task = self.fixture.task()
        task["target_glb_path"] = str(bad)
        with self.assertRaisesRegex(ValueError, "target mesh must be one of"):
            self.operator.run(task)
        self.retarget_fn.assert_not_called()

    def test_unknown_task_type_is_explicitly_unimplemented(self):
        task = self.fixture.task()
        task["task_type"] = "generate"
        with self.assertRaisesRegex(NotImplementedError, "Unsupported"):
            self.operator.run(task)

    def test_structural_metrics(self):
        result = self.operator.run(self.fixture.task())
        score = evaluate(result, self.fixture.task())
        self.assertTrue(score["artifact_valid"])
        self.assertTrue(score["mapping_valid"])
        self.assertEqual(score["required_chain_coverage"], 1.0)
        self.assertTrue(score["timing_preserved"])
        self.assertEqual(score["fps"], 20)


#: A three-bone Mixamo-named BVH. Short on purpose: identification reads the
#: hierarchy only, so the sample block never has to be realistic.
_MIXAMO_BVH = """HIERARCHY
ROOT mixamorig:Hips
{
  OFFSET 0 0 0
  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
  JOINT mixamorig:Spine
  {
    OFFSET 0 10 0
    CHANNELS 3 Zrotation Xrotation Yrotation
    JOINT mixamorig:Head
    {
      OFFSET 0 50 0
      CHANNELS 3 Zrotation Xrotation Yrotation
      End Site
      {
        OFFSET 0 20 0
      }
    }
  }
}
MOTION
Frames: 1
Frame Time: 0.033333
0 0 0 0 0 0 0 0 0 0 0 0
"""


class TestExternalMotionSources(unittest.TestCase):
    """Bringing a clip in from Mixamo and friends when generation is not good
    enough."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aaagf_fetch_")
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_known_sources_declare_licence_and_access(self):
        sources = {entry["name"]: entry for entry in list_motion_sources()}
        self.assertIn("mixamo", sources)
        self.assertIn("cmu_bvh", sources)
        for entry in sources.values():
            self.assertIn(entry["access"], {"manual", "direct"})
            self.assertTrue(entry["licence"])
            self.assertTrue(entry["how_to_download"])

    def test_local_clip_is_ingested_with_provenance(self):
        clip = self.root / "downloaded.bvh"
        clip.write_text(_MIXAMO_BVH, encoding="utf-8")
        result = fetch_motion(
            source="mixamo",
            path=str(clip),
            dest_dir=str(self.root / "task"),
        )
        self.assertTrue(Path(result["motion_path"]).is_file())
        record = json.loads(
            Path(result["provenance_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(record["source"], "mixamo")
        self.assertTrue(record["licence"])
        self.assertEqual(record["nominal_units"], "centimetres")

    def test_a_zip_download_yields_its_single_clip(self):
        archive = self.root / "pack.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("clips/walk.bvh", _MIXAMO_BVH)
            bundle.writestr("readme.txt", "not a clip")
        result = fetch_motion(
            source="local",
            path=str(archive),
            dest_dir=str(self.root / "task"),
        )
        self.assertTrue(Path(result["motion_path"]).name == "walk.bvh")

    def test_an_ambiguous_archive_asks_which_clip(self):
        archive = self.root / "pack.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("walk.bvh", _MIXAMO_BVH)
            bundle.writestr("run.bvh", _MIXAMO_BVH)
        with self.assertRaisesRegex(ValueError, "pass member="):
            fetch_motion(
                source="local",
                path=str(archive),
                dest_dir=str(self.root / "task"),
            )

    def test_login_gated_sources_refuse_to_be_scraped(self):
        with self.assertRaises(PermissionError) as caught:
            fetch_motion(
                source="mixamo",
                url="https://www.mixamo.com/some/clip.fbx",
                dest_dir=str(self.root / "task"),
            )
        message = str(caught.exception)
        self.assertIn("Sign in at mixamo.com", message)
        self.assertIn("path=", message)

    def test_scale_is_measured_from_both_skeletons(self):
        clip = self.root / "walk.bvh"
        clip.write_text(_MIXAMO_BVH, encoding="utf-8")
        rig = self.root / "rig.txt"
        rig.write_text(
            "joints joint0 0 0 0\njoints joint1 0 0 1.8\nroot joint0\n",
            encoding="utf-8",
        )
        self.assertAlmostEqual(measure_bvh_extent(clip), 80.0, places=3)
        suggestion = suggest_global_scale(clip, rig)
        self.assertTrue(suggestion["confident"])
        self.assertAlmostEqual(
            suggestion["suggested_global_scale"],
            1.8 / 80.0,
            places=6,
        )

    def test_an_fbx_clip_cannot_be_measured_and_says_so(self):
        clip = self.root / "walk.fbx"
        clip.write_bytes(b"Kaydara FBX Binary  \x00" + bytes(32))
        rig = self.root / "rig.txt"
        rig.write_text(
            "joints joint0 0 0 0\njoints joint1 0 0 1.8\nroot joint0\n",
            encoding="utf-8",
        )
        suggestion = suggest_global_scale(clip, rig)
        self.assertFalse(suggestion["confident"])
        self.assertIsNone(suggestion["suggested_global_scale"])
        self.assertIn("centimetres", suggestion["reason"])


class TestRetargetFunction(unittest.TestCase):
    def test_source_extension_validation(self):
        self.assertEqual(normalise_source_ext("BVH"), ".bvh")
        self.assertEqual(normalise_source_ext(".fbx"), ".fbx")
        with self.assertRaisesRegex(ValueError, "source_ext"):
            normalise_source_ext(".glb")

    def test_mesh_extension_validation(self):
        for value in (".glb", "OBJ", ".gltf", ".ply", ".stl"):
            self.assertTrue(normalise_mesh_ext(value).startswith("."))
        with self.assertRaisesRegex(ValueError, "target mesh must be one of"):
            normalise_mesh_ext(".bvh")

    def test_missing_bpy_runtime_has_actionable_error(self):
        ensure_retarget_runtime.cache_clear()
        missing = str(_REPO_ROOT / "does_not_exist" / "python.exe")
        with self.assertRaisesRegex(
            RuntimeError,
            "A3GF_RETARGET_BPY_PYTHON",
        ):
            ensure_retarget_runtime(missing)

    def test_mapping_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapping.json"
            path.write_text('{"bone_map": {"Hips": "joint0"}}')
            data = load_and_validate_mapping(path)
            self.assertEqual(data["bone_map"]["Hips"], "joint0")
            path.write_text('{"bone_map": []}')
            with self.assertRaisesRegex(ValueError, "bone_map"):
                load_and_validate_mapping(path)

    def test_auto_mapping_and_two_export_commands(self):
        module = importlib.import_module(
            "operators.gen_motion.funcs.retarget_motion"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = MotionRetargetFixture(root)

            def fake_run(
                _bpy_python,
                backend_module,
                _args,
                *,
                expected,
                device,
                verbose,
            ):
                self.assertEqual(device, "cpu")
                self.assertFalse(verbose)
                if backend_module.endswith("mapping_auto"):
                    expected[0].write_text(
                        json.dumps(retarget_mapping()),
                        encoding="utf-8",
                    )
                    return
                for path in expected:
                    if path.suffix == ".json":
                        path.write_text(
                            json.dumps(retarget_info(30)),
                            encoding="utf-8",
                        )
                    else:
                        path.write_bytes(
                            b"Kaydara FBX Binary  \x00" + bytes(32)
                        )

            with (
                mock.patch.object(
                    module,
                    "ensure_retarget_runtime",
                    return_value=sys.executable,
                ),
                mock.patch.object(
                    module,
                    "_run_module",
                    side_effect=fake_run,
                ) as run_module,
            ):
                result = retarget_motion(
                    bpy_python=sys.executable,
                    source_motion_path=str(fixture.source),
                    target_mesh_path=str(fixture.target),
                    target_rig_path=str(fixture.rig),
                    output_path=str(root / "retargeted.fbx"),
                    anim_only_output_path=str(root / "animation.fbx"),
                    mapping_path=None,
                    mapping_output_path=str(root / "mapping_out.json"),
                    info_output_path=str(root / "retarget_info.json"),
                )

            self.assertEqual(run_module.call_count, 3)
            modules = [
                call.args[1] for call in run_module.call_args_list
            ]
            self.assertTrue(modules[0].endswith("mapping_auto"))
            self.assertTrue(modules[1].endswith("world_delta"))
            self.assertTrue(modules[2].endswith("world_delta"))
            self.assertIn(
                "--anim-only",
                run_module.call_args_list[2].args[2],
            )
            for key in (
                "retargeted_fbx_path",
                "anim_only_fbx_path",
                "mapping_path",
                "retarget_info_path",
            ):
                self.assertTrue(Path(result[key]).is_file())


_BPY_PYTHON = os.environ.get("A3GF_RETARGET_BPY_PYTHON")


_REAL_ENV = {
    "bpy_python": os.environ.get("A3GF_RETARGET_BPY_PYTHON"),
    "source_motion": os.environ.get("A3GF_RETARGET_SOURCE_MOTION"),
    "target_glb": os.environ.get("A3GF_RETARGET_TARGET_GLB"),
    "target_rig": os.environ.get("A3GF_RETARGET_TARGET_RIG"),
}
_REAL_READY = all(_REAL_ENV.values())


if __name__ == "__main__":
    unittest.main(verbosity=2)
