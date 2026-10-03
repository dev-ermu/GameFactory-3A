"""Verified style contracts for project-specific Niagara systems.

The values summarize VFX-edit/data/kb and VFX-appearance experiments. A style
contract is not a substitute for a Niagara material/system that consumes it.
"""

from copy import deepcopy
from typing import Any

from .vfx_functions import spawn_effect


STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "ink": {
        "primary_color": (0.035, 0.045, 0.05, 0.92),
        "secondary_color": (0.62, 0.66, 0.64, 0.55),
        "layers": ("quantized ink body", "flow-distorted wash", "droplet accents"),
        "user_parameters": {
            "AAAGF Secondary Color": (0.62, 0.66, 0.64, 0.55),
            "AAAGF Color Steps": 4.0,
            "AAAGF Motion Speed": 0.22,
            "AAAGF Distortion Strength": 0.35,
        },
    },
    "frost": {
        "primary_color": (0.3, 0.88, 1.0, 1.0),
        "secondary_color": (0.08, 0.28, 0.92, 1.0),
        "layers": ("cold core", "crystal shards", "view-dependent glints"),
        "user_parameters": {
            "AAAGF Secondary Color": (0.08, 0.28, 0.92, 1.0),
            "AAAGF Specular Emissive": 20.0,
            "AAAGF Shard Rate": 9.0,
            "AAAGF Distortion Strength": 0.08,
        },
    },
    "cyber": {
        "primary_color": (0.02, 0.95, 1.0, 1.0),
        "secondary_color": (1.0, 0.025, 0.68, 1.0),
        "layers": ("cyan energy body", "magenta pulse", "quantized data streaks"),
        "user_parameters": {
            "AAAGF Secondary Color": (1.0, 0.025, 0.68, 1.0),
            "AAAGF Color Steps": 4.0,
            "AAAGF Motion Speed": 0.65,
            "AAAGF Glitch Rate": 12.0,
        },
    },
}

STYLE_SYSTEM_PATHS = {
    "ink": "/Game/VFXGenEngine/SwapFX/NS_sp_ink",
    "frost": "/Game/VFXGenEngine/SwapFX/NS_sp_ice",
    "cyber": "/Game/VFXGenEngine/SwapFX/NS_sp_cyber",
}


def get_style_preset(style: str) -> dict[str, Any]:
    normalized = style.lower().strip()
    if normalized not in STYLE_PRESETS:
        choices = ", ".join(sorted(STYLE_PRESETS))
        raise ValueError(f"unknown VFX style {style!r}; expected one of: {choices}")
    return deepcopy(STYLE_PRESETS[normalized])


def spawn_styled_effect(
    kind: str,
    style: str,
    location=(0.0, 0.0, 0.0),
    *,
    system_path: str | None = None,
    user_parameters: dict[str, Any] | None = None,
    **kwargs: Any,
):
    """Spawn a reviewed style-specific Niagara system.

    The default paths are the style-specific Niagara systems built and reviewed
    in the VFX-edit UE 5.7 project. Override ``system_path`` in projects that
    install the assets elsewhere. Unsupported User parameters are no-ops in
    Unreal, so visual review remains mandatory.
    """
    preset = get_style_preset(style)
    normalized = style.lower().strip()
    parameters = dict(preset["user_parameters"])
    parameters.update(user_parameters or {})
    return spawn_effect(
        kind,
        location,
        system_path=system_path or STYLE_SYSTEM_PATHS[normalized],
        color=preset["primary_color"],
        user_parameters=parameters,
        **kwargs,
    )
