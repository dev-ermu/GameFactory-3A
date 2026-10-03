"""Compatibility entrypoint for the pinned MoMask inference script."""

import runpy
import sys
from collections.abc import Iterable
from pathlib import Path


def _artist_list_setter(name: str, add_method: str):
    def setter(axes, values: Iterable[object]) -> None:
        for artist in list(getattr(axes, name)):
            artist.remove()
        add = getattr(axes, add_method)
        for artist in values:
            add(artist)

    return setter


def _install_matplotlib_compatibility() -> None:
    # MoMask was released with Matplotlib 3.1.3 and clears 3D artists through
    # ``ax.lines = []`` and ``ax.collections = []``.  CPython 3.10 wheels start
    # at Matplotlib 3.5, where both attributes became read-only ArtistLists.
    from matplotlib.axes import Axes
    from mpl_toolkits.mplot3d import axes3d

    for name, add_method in (
        ("lines", "add_line"),
        ("collections", "add_collection"),
    ):
        descriptor = getattr(Axes, name)
        if isinstance(descriptor, property) and descriptor.fset is None:
            setattr(
                Axes,
                name,
                descriptor.setter(_artist_list_setter(name, add_method)),
            )

    axes3d_class = axes3d.Axes3D
    if not getattr(axes3d_class, "_aaagf_registers_with_figure", False):
        # Matplotlib 3.4 and earlier registered ``Axes3D(fig)`` on ``fig``.
        # MoMask relies on that side effect, but modern Matplotlib requires an
        # explicit ``fig.add_axes(ax)``.  Without it the saved MP4 contains the
        # title only even though every skeleton line is computed.
        class RegisteredAxes3D(axes3d_class):
            _aaagf_registers_with_figure = True

            def __init__(self, figure, *args, **kwargs):
                super().__init__(figure, *args, **kwargs)
                if self not in figure.axes:
                    figure.add_axes(self)

        axes3d.Axes3D = RegisteredAxes3D


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: momask_entrypoint.py <gen_t2m.py> [args ...]")
    script = Path(sys.argv.pop(1)).expanduser().resolve()
    sys.path.insert(0, str(script.parent))
    _install_matplotlib_compatibility()
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
