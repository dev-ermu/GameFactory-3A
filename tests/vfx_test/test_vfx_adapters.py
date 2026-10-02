"""Offline contract tests for the reusable engine VFX adapters."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from engine_adapters.ue5.vfx import vfx_functions as vfx
from engine_adapters.ue5.vfx import action_binding, style_presets
from tests.vfx_test import ue5_test_paths


REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeComponent:
    def __init__(self):
        self.asset = None
        self.parameters = {}
        self.active = False

    def set_asset(self, asset):
        self.asset = asset

    def set_variable_bool(self, name, value):
        self.parameters[name] = value

    def set_variable_float(self, name, value):
        self.parameters[name] = value

    def set_variable_vec3(self, name, value):
        self.parameters[name] = value

    def set_variable_linear_color(self, name, value):
        self.parameters[name] = value

    def activate(self, reset):
        self.active = reset

    def deactivate(self):
        self.active = False


class FakeActor:
    def __init__(self, component):
        self.component = component
        self.scale = None
        self.destroyed = False

    def set_actor_scale3d(self, value):
        self.scale = value

    def get_components_by_class(self, _cls):
        return [self.component]

    def destroy_actor(self):
        self.destroyed = True


def make_fake_unreal(missing=False):
    component = FakeComponent()
    actor = FakeActor(component)
    api = SimpleNamespace()
    api.NiagaraActor = type("NiagaraActor", (), {})
    api.NiagaraComponent = type("NiagaraComponent", (), {})
    api.Vector = lambda x, y, z: (x, y, z)
    api.Rotator = lambda **kw: kw
    api.LinearColor = lambda *channels: tuple(channels)
    api.EditorAssetLibrary = SimpleNamespace(
        load_asset=lambda path: None if missing else f"asset:{path}"
    )
    api.EditorLevelLibrary = SimpleNamespace(
        spawn_actor_from_class=lambda cls, location, rotation: actor
    )
    return api, actor, component


class TestUnrealVFXFunctions(unittest.TestCase):
    def test_named_fire_uses_reviewed_template_and_parameters(self):
        api, actor, component = make_fake_unreal()
        with mock.patch.object(vfx, "_get_unreal", return_value=api):
            returned = vfx.spawn_fire(
                (100, 20, 0), scale=0.75, color=(1, 0.3, 0.05, 1)
            )

        self.assertIs(returned, actor)
        self.assertEqual(
            component.asset, f"asset:{vfx.DEFAULT_SYSTEM_PATHS['fire']}"
        )
        self.assertEqual(actor.scale, (0.75, 0.75, 0.75))
        self.assertEqual(
            component.parameters["User.Flame Color"], (1.0, 0.3, 0.05, 1.0)
        )
        self.assertTrue(component.active)

    def test_project_specific_system_path_is_supported(self):
        api, _actor, component = make_fake_unreal()
        with mock.patch.object(vfx, "_get_unreal", return_value=api):
            vfx.spawn_smoke(system_path="/Game/MyVFX/NS_StylizedSmoke")
        self.assertEqual(component.asset, "asset:/Game/MyVFX/NS_StylizedSmoke")

    def test_missing_template_fails_instead_of_using_placeholder(self):
        api, _actor, _component = make_fake_unreal(missing=True)
        with mock.patch.object(vfx, "_get_unreal", return_value=api):
            with self.assertRaises(vfx.VFXAssetNotFound):
                vfx.spawn_smoke()

    def test_stop_deactivates_and_destroys(self):
        api, actor, component = make_fake_unreal()
        component.active = True
        with mock.patch.object(vfx, "_get_unreal", return_value=api):
            vfx.stop_effect(actor, destroy=True)
        self.assertFalse(component.active)
        self.assertTrue(actor.destroyed)

    def test_unknown_category_is_rejected(self):
        with self.assertRaises(ValueError):
            vfx.spawn_effect("waterfall")

    def test_styled_effect_uses_reviewed_ue_system_by_default(self):
        api, _actor, component = make_fake_unreal()
        with mock.patch.object(vfx, "_get_unreal", return_value=api):
            style_presets.spawn_styled_effect("fire", "frost")
        self.assertEqual(
            component.asset,
            f"asset:{style_presets.STYLE_SYSTEM_PATHS['frost']}",
        )

    def test_styled_effect_applies_verified_contract(self):
        api, _actor, component = make_fake_unreal()
        with mock.patch.object(vfx, "_get_unreal", return_value=api):
            style_presets.spawn_styled_effect(
                "fire", "cyber", system_path="/Game/VFX/NS_CyberFire"
            )
        self.assertEqual(component.parameters["User.Flame Color"],
                         (0.02, 0.95, 1.0, 1.0))
        self.assertEqual(component.parameters["User.AAAGF Glitch Rate"], 12.0)

    def test_punch_fire_binding_targets_hand_and_fire(self):
        binding = action_binding.build_punch_fire_binding(
            "/Game/Anim/Punch.Punch", "/Game/Characters/Hero.Hero"
        )
        rule = binding["bindings"][0]["rules"][0]
        self.assertEqual(rule["rule"], "speed_trail")
        self.assertEqual(rule["bone"], "RightHand")
        self.assertEqual(rule["niagara"],
                         "/Game/NiagaraExamples/FX_Misc/NS_Fire.NS_Fire")


class TestUnityAndSkillContracts(unittest.TestCase):
    def test_unity_adapter_exposes_named_and_template_functions(self):
        source = (REPO_ROOT / "engine_adapters" / "unity3d" / "vfx" /
                  "Runtime" / "A3Game_VFX.cs").read_text(encoding="utf-8")
        for function in (
            "SpawnPrefab", "SpawnSmoke", "SpawnFire", "SpawnExplosion",
            "SpawnDust", "SpawnInkSmoke", "SpawnFrostFire",
            "SpawnCyberFire", "Stop",
        ):
            with self.subTest(function=function):
                self.assertIn(f" {function}(", source)

    def test_unity_smoke_supports_material_flipbooks(self):
        source = (REPO_ROOT / "engine_adapters" / "unity3d" / "vfx" /
                  "Runtime" / "A3Game_VFX.cs").read_text(encoding="utf-8")
        for contract in (
            "Material particleMaterial",
            "Vector2Int textureSheetTiles",
            "bool forceAlphaBlend",
            "ps.textureSheetAnimation",
            "ParticleSystemAnimationType.WholeSheet",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, source)

    def test_unity_review_supports_interactive_play_mode(self):
        source = (
            REPO_ROOT / "tests" / "vfx_test" / "A3Game_VFXRuntimeCapture.cs"
        ).read_text(encoding="utf-8")
        self.assertIn("StartInteractiveReview();", source)
        self.assertIn('instance.name = "REVIEW_"', source)

    def test_skill_points_to_both_real_adapters(self):
        skill_dir = (REPO_ROOT / "agent_skills" / "engine_context" /
                     "create-vfx-effects")
        skill = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("engine_adapters/ue5/vfx/vfx_functions.py", skill)
        self.assertIn("engine_adapters/unity3d/vfx/Runtime/A3Game_VFX.cs", skill)
        self.assertIn("Reuse Templates First", skill)
        self.assertIn("Require Visual Approval", skill)

    def test_skill_is_single_file(self):
        skill_dir = (REPO_ROOT / "agent_skills" / "engine_context" /
                     "create-vfx-effects")
        files = sorted(
            path.relative_to(skill_dir).as_posix()
            for path in skill_dir.rglob("*") if path.is_file()
        )
        self.assertEqual(files, ["SKILL.md"])

    def test_ue_assets_resolve_from_configured_content_root(self):
        with mock.patch.dict(
            os.environ,
            {ue5_test_paths.CONTENT_ROOT_ENV: "/Game/Project/VFXTests/"},
        ):
            self.assertEqual(
                ue5_test_paths.content_path("Sequences/Fire"),
                "/Game/Project/VFXTests/Sequences/Fire",
            )

    def test_ue_content_root_is_required(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, ue5_test_paths.CONTENT_ROOT_ENV):
                ue5_test_paths.content_root()


if __name__ == "__main__":
    unittest.main(verbosity=2)
