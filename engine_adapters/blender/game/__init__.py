"""
engine_adapters/blender/game

The gameplay half of the Blender adapter: what a generated mechanic is built
out of. `../runtime/` drives a *live* Blender for interactive inspection; this
package instead simulates a whole match headlessly, bakes it onto keyframes and
renders it, which is what a benchmark needs — a fixed-timestep run that produces
the same video and the same numbers every time.

    kernel       fixed-timestep loop, actors, event log, the `Game` base class
    prims        shared unit meshes; spawning, aiming, stretching, ribbons
    materials    cached Principled and emissive materials, plus a palette
    assets       resolving an asset reference to a file, and importing it once
    figures      posing a humanoid model from the numbers the rules compute
    clips        playing authored glTF actions (walk, punch, death) on a rig
    camera_rigs  first-person, chase and side-on cameras
    hud          screen-space bars, pips, labels and vignettes as camera-parented geometry
    recorder     keyframe baking, Cycles setup, MP4 and thumbnail export
    controls     the input surface a player drives, and how keys map onto it
    interactive  the same rules stepped live in a window, from a keyboard

A generated mechanic can therefore be watched or played, and the two are not
separate implementations: `interactive` steps the same `tick()` at the same fixed
timestep, and a played session records its input so `Game.run(source=...)` can
re-render it offline and get the same run back.

Everything here imports `bpy`, so it only loads inside Blender or a Python with
the `bpy` wheel. A generated game subclasses `kernel.Game`, and the modules
above are the vocabulary it writes in — see `../examples/`
for four worked examples and `../../../agent_skills/engine_context/blender_api.md`
for the API caveats they were written against.
"""

__all__ = ["kernel", "prims", "materials", "assets", "figures", "clips", "hud",
           "camera_rigs", "recorder", "controls", "interactive"]
