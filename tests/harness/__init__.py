"""
tests/harness — 离线测试夹具包。

`stubs` 的公开接口在这里再导出一层，调用方写：

    from tests.harness import make_ref_image, build_operator

而不再把 `tests/harness` 注入 `sys.path` 之后 `import stubs`。后者有两个问题：
依赖隐式的路径注入；`stubs` 作为顶层名会遮蔽同名的第三方包。

仍需按子模块路径访问时（例如只想拿模块本身）：

    from tests.harness import stubs

`stubs.py` 的职责说明见其模块 docstring；`smoke.py` 是离线冒烟入口。
"""
from tests.harness import stubs
from tests.harness.stubs import (
    # 图片 / glTF / FBX 夹具
    make_animated_glb,
    make_checker_png,
    make_humanoid_glb,
    make_minimal_glb,
    make_ref_image,
    make_rigged_glb,
    make_stub_fbx,
    make_textured_glb,
    write_ref_image,
    # motion / retarget 辅助
    retarget_info,
    retarget_mapping,
    stub_retarget_motion,
    # 3D 物体
    StubMeshyModel,
    StubTrellis2Model,
    StubTripoModel,
    # 图像 / 抠像 / 深度
    StubDepthAnythingModel,
    StubQwenEditModel,
    StubRMBGModel,
    StubSeedreamModel,
    # 音频
    StubQwen3TTSModel,
    StubSeedAudioModel,
    StubWooshDFlowModel,
    # CG 视频
    StubVideoModel,
    # 3D 场景
    StubWorldMirrorModel,
    StubWorldPlayModel,
    # 动作 / 绑骨 / 动画 / 格式转换
    StubMoMaskModel,
    StubPuppeteerModel,
    StubTripoAnimationModel,
    StubTripoFormatModel,
    StubTripoRigCheckModel,
    StubTripoRiggingModel,
    # 注册表与算子工厂
    OPERATOR_LOCATION,
    STUB_BACKENDS,
    STUB_OPERATOR_KWARGS,
    build_operator,
)

__all__ = [
    "stubs",
    # 图片 / glTF / FBX 夹具
    "make_animated_glb",
    "make_checker_png",
    "make_humanoid_glb",
    "make_minimal_glb",
    "make_ref_image",
    "make_rigged_glb",
    "make_stub_fbx",
    "make_textured_glb",
    "write_ref_image",
    # motion / retarget 辅助
    "retarget_info",
    "retarget_mapping",
    "stub_retarget_motion",
    # 3D 物体
    "StubMeshyModel",
    "StubTrellis2Model",
    "StubTripoModel",
    # 图像 / 抠像 / 深度
    "StubDepthAnythingModel",
    "StubQwenEditModel",
    "StubRMBGModel",
    "StubSeedreamModel",
    # 音频
    "StubQwen3TTSModel",
    "StubSeedAudioModel",
    "StubWooshDFlowModel",
    # CG 视频
    "StubVideoModel",
    # 3D 场景
    "StubWorldMirrorModel",
    "StubWorldPlayModel",
    # 动作 / 绑骨 / 动画 / 格式转换
    "StubMoMaskModel",
    "StubPuppeteerModel",
    "StubTripoAnimationModel",
    "StubTripoFormatModel",
    "StubTripoRigCheckModel",
    "StubTripoRiggingModel",
    # 注册表与算子工厂
    "OPERATOR_LOCATION",
    "STUB_BACKENDS",
    "STUB_OPERATOR_KWARGS",
    "build_operator",
]
