"""
engine_adapters/blender/runtime/vfx/manager.py

Spawn an effect by name and be able to take it away again.

Owning the naming is the point of this class. Each effect gets one
`vfx_<kind>_<n>` prefix and a backend must name every object it creates either
exactly that or `<prefix>_<part>`, so cleanup needs no bookkeeping about how
many objects an effect turned out to be. Smoke is a domain *and* a flow emitter,
and leaking one leaves an invisible simulation running in every later render.

根据名称生成特效，并能将其移除。

该类的作用就是统一管理特效命名。每种特效都会采用 `vfx_<类型>_<序号>` 这样的前缀，后端创建的所有物体必须严格使用这一命名规则，或是 `<前缀>_<部件名>` 的形式，因此清理时无需额外记录某种特效究竟对应多少个物体。烟雾特效既包含模拟域也包含流发射器，如果其中一个部分未被正确清理，就会导致后续所有渲染中都有无形的模拟过程在后台运行。
"""

from typing import List, Optional, Tuple

#: Prefix on every object the runtime spawns as an effect. Shared with
#: `scene.blend_scene.RUNTIME_PREFIXES` so `clear_scene` sweeps these too.
VFX_PREFIX = "vfx_"


class VFXManager:
    #: What `trigger` accepts. `smoke` and `fire` share a backend.
    KINDS = ("particle", "geometry_nodes", "grease_pencil", "smoke", "fire")

    def __init__(self) -> None:
        self._spawned: List[str] = []
        self._counter = 0
        #: Set once a fluid simulation has existed in this process. Removing
        #: the objects does not clear it — see `Subsystem.shutdown`.
        self.spawned_fluid = False

    def _next_name(self, kind: str) -> str:
        self._counter += 1
        return f"{VFX_PREFIX}{kind}_{self._counter}"

    def trigger(self, kind: str,
                location: Optional[Tuple[float, float, float]] = None,
                entity_id: Optional[str] = None,
                params: Optional[dict] = None) -> str:
        """
        Spawn one `KINDS` effect and return the prefix that identifies it.

        `location` defaults to the origin, or to where `entity_id` is when that
        names a live character. Effects are never parented, so a moving
        character leaves its effect behind — what an impact or footfall wants.
        `params` reach the backend, which ignores keys it does not know so a
        command written for one kind does not fail against another.
        """
        if kind not in self.KINDS:
            raise ValueError(f"unknown vfx kind {kind!r}; expected one of "
                             f"{', '.join(self.KINDS)}")
        params = dict(params or {})
        name = self._next_name("smoke" if kind in ("smoke", "fire") else kind)
        where = location if location is not None else self._entity_location(entity_id)

        if kind == "particle":
            from .particles import spawn  # noqa: PLC0415

            spawn(name, where, **params)
        elif kind == "geometry_nodes":
            from .geometry_nodes import spawn  # noqa: PLC0415

            spawn(name, where, **params)
        elif kind == "grease_pencil":
            from .grease_pencil import spawn  # noqa: PLC0415

            spawn(name, where, **params)
        else:
            from .smoke_fire import spawn  # noqa: PLC0415

            spawn(name, where, kind=kind, **params)
            self.spawned_fluid = True

        self._spawned.append(name)
        return name

    def clear(self, name: str) -> bool:
        """Remove one effect and every object belonging to it."""
        import bpy  # noqa: PLC0415

        doomed = [o for o in bpy.data.objects
                  if o.name == name or o.name.startswith(f"{name}_")]
        for obj in doomed:
            bpy.data.objects.remove(obj, do_unlink=True)
        if name in self._spawned:
            self._spawned.remove(name)
        return bool(doomed)

    def clear_all(self) -> int:
        """Remove every effect spawned so far. Returns how many were removed."""
        return sum(1 for name in list(self._spawned) if self.clear(name))

    def spawned(self) -> tuple:
        return tuple(self._spawned)

    @staticmethod
    def _entity_location(entity_id: Optional[str]) -> Tuple[float, float, float]:
        if not entity_id:
            return (0.0, 0.0, 0.0)
        import bpy  # noqa: PLC0415

        obj = bpy.data.objects.get(f"player_{entity_id}")
        return tuple(obj.location) if obj is not None else (0.0, 0.0, 0.0)
