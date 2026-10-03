"""Small, reusable Niagara spawning functions for Unreal Editor Python.

Run this module inside Unreal Editor, where the ``unreal`` module is available.
The named defaults come from the VFX-edit project's reviewed Niagara inventory.
Projects that do not contain NiagaraExamples must pass ``system_path``.
"""

from collections.abc import Mapping, Sequence
from typing import Any


DEFAULT_SYSTEM_PATHS = {
    "smoke": "/Game/NiagaraExamples/FX_Smoke/NS_Smoke_Plume",
    "fire": "/Game/NiagaraExamples/FX_Misc/NS_Fire",
    "explosion": "/Game/NiagaraExamples/FX_Explosions/NS_Explosion_Small",
    "dust": "/Game/NiagaraExamples/FX_Explosions/NS_Dirt_Explosion_Small",
}

_COLOR_PARAMETERS = {
    "smoke": "User.Smoke Color",
    "fire": "User.Flame Color",
    "explosion": "User.Smoke Color",
    "dust": "User.Dirt Color",
}


class VFXAssetNotFound(RuntimeError):
    """Raised when a requested Niagara System is absent from the project."""


def _get_unreal():
    try:
        import unreal  # type: ignore
    except ImportError as exc:  # pragma: no cover - only available in UE
        raise RuntimeError(
            "UE5 VFX functions must run inside Unreal Editor Python"
        ) from exc
    return unreal


def _vector(api: Any, value: Sequence[float]):
    if len(value) != 3:
        raise ValueError("location and scale vectors must contain three values")
    return api.Vector(float(value[0]), float(value[1]), float(value[2]))


def _rotator(api: Any, value: Sequence[float]):
    if len(value) != 3:
        raise ValueError("rotation must be (pitch, yaw, roll)")
    return api.Rotator(
        pitch=float(value[0]), yaw=float(value[1]), roll=float(value[2])
    )


def _set_user_parameter(component: Any, api: Any, name: str, value: Any) -> None:
    parameter = name if name.startswith("User.") else f"User.{name}"
    if isinstance(value, bool):
        component.set_variable_bool(parameter, value)
    elif isinstance(value, (int, float)):
        component.set_variable_float(parameter, float(value))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) == 3:
            component.set_variable_vec3(parameter, _vector(api, value))
        elif len(value) == 4:
            component.set_variable_linear_color(
                parameter,
                api.LinearColor(*(float(channel) for channel in value)),
            )
        else:
            raise TypeError(f"unsupported sequence for Niagara parameter {name!r}")
    else:
        raise TypeError(f"unsupported value for Niagara parameter {name!r}: {value!r}")


def spawn_niagara(
    system_path: str,
    location: Sequence[float] = (0.0, 0.0, 0.0),
    *,
    rotation: Sequence[float] = (0.0, 0.0, 0.0),
    scale: float | Sequence[float] = 1.0,
    user_parameters: Mapping[str, Any] | None = None,
    auto_activate: bool = True,
):
    """Spawn and configure a NiagaraActor in the current editor world.

    Locations are Unreal centimeters and rotation is ``(pitch, yaw, roll)`` in
    degrees. The returned actor is the lifecycle handle for ``stop_effect``.
    """
    api = _get_unreal()
    system = api.EditorAssetLibrary.load_asset(system_path)
    if system is None:
        raise VFXAssetNotFound(
            f"Niagara System not found: {system_path}. Import it or pass a valid "
            "project-specific system_path."
        )

    actor = api.EditorLevelLibrary.spawn_actor_from_class(
        api.NiagaraActor, _vector(api, location), _rotator(api, rotation)
    )
    if actor is None:
        raise RuntimeError("Unreal failed to spawn NiagaraActor in the current world")

    scale_value = (scale, scale, scale) if isinstance(scale, (int, float)) else scale
    actor.set_actor_scale3d(_vector(api, scale_value))
    components = actor.get_components_by_class(api.NiagaraComponent)
    if not components:
        actor.destroy_actor()
        raise RuntimeError("spawned NiagaraActor has no NiagaraComponent")

    component = components[0]
    component.set_asset(system)
    for name, value in (user_parameters or {}).items():
        _set_user_parameter(component, api, name, value)

    if auto_activate:
        component.activate(True)
    else:
        component.deactivate()
    return actor


def spawn_effect(
    kind: str,
    location: Sequence[float] = (0.0, 0.0, 0.0),
    *,
    system_path: str | None = None,
    color: Sequence[float] | None = None,
    user_parameters: Mapping[str, Any] | None = None,
    **kwargs: Any,
):
    """Spawn one of ``smoke``, ``fire``, ``explosion`` or ``dust``."""
    normalized = kind.lower().strip()
    if normalized not in DEFAULT_SYSTEM_PATHS:
        choices = ", ".join(sorted(DEFAULT_SYSTEM_PATHS))
        raise ValueError(f"unknown VFX kind {kind!r}; expected one of: {choices}")

    parameters = dict(user_parameters or {})
    if color is not None:
        parameters.setdefault(_COLOR_PARAMETERS[normalized], color)
    return spawn_niagara(
        system_path or DEFAULT_SYSTEM_PATHS[normalized],
        location,
        user_parameters=parameters,
        **kwargs,
    )


def spawn_smoke(location=(0.0, 0.0, 0.0), **kwargs: Any):
    """Spawn a looping smoke plume and return its NiagaraActor."""
    return spawn_effect("smoke", location, **kwargs)


def spawn_fire(location=(0.0, 0.0, 0.0), **kwargs: Any):
    """Spawn a looping flame effect and return its NiagaraActor."""
    return spawn_effect("fire", location, **kwargs)


def spawn_explosion(location=(0.0, 0.0, 0.0), **kwargs: Any):
    """Spawn a one-shot fire-and-smoke explosion and return its NiagaraActor."""
    return spawn_effect("explosion", location, **kwargs)


def spawn_dust(location=(0.0, 0.0, 0.0), **kwargs: Any):
    """Spawn a one-shot dirt burst and return its NiagaraActor."""
    return spawn_effect("dust", location, **kwargs)


def stop_effect(actor: Any, *, destroy: bool = False) -> None:
    """Deactivate all Niagara components and optionally destroy their actor."""
    if actor is None:
        return
    api = _get_unreal()
    for component in actor.get_components_by_class(api.NiagaraComponent):
        component.deactivate()
    if destroy:
        actor.destroy_actor()
