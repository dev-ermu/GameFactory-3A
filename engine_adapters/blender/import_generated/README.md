# blender/import_generated

Turns a file produced by `models/` into a conditioned, measured Blender asset.

> Scope note: this directory is the **importer for generated assets**. The rig /
> retarget / preview code one level up in `engine_adapters/blender/` is "how
> Blender does X"; this is "how our artifacts get in". Keep the two apart.

## Files

| File | Runs where | Purpose |
|------|-----------|---------|
| `import_mesh.py` | a `bpy` interpreter | import → condition → measure → export → report |
| `../../../scripts/import_generated_asset.py` | host Python | finds Blender, launches the above, reads the report |

## Quick start

```bash
# one asset, through the launcher
python scripts/import_generated_asset.py --engine blender \
    --src test_data/outputs/<game>/<run>/assets/3d_object/<task>/model.glb \
    --blender-preview

# everything one generation run produced
python scripts/import_generated_asset.py --engine blender \
    --summary test_data/outputs/<game>/<run>/3d_object_results_summary.json
```

Or call Blender directly. Parameters go through a **job file** named by
`AAAGF_IMPORT_JOB` — the same channel the UE5 importer uses, so the launcher
builds one job shape for every engine:

```bash
echo '{"src":"/out/model.glb","dest":"/out/library","name":"Sword_001",
       "usage":"asset","export":["glb"],"report":"/out/blender_import.json"}' > /out/job.json
AAAGF_IMPORT_JOB=/out/job.json AAAGF_BLENDER_EXIT_ON_DONE=1 \
blender --background --factory-startup --python import_mesh.py
```

`AAAGF_BLENDER_EXIT_ON_DONE` matters: `blender --background --python x.py` exits
0 whatever the script returned, so without it a failed import looks like a
success to any caller that checks the exit code.

The ordinary CLI flags work too, after Blender's bare `--`:

```bash
blender --background --factory-startup --python import_mesh.py -- \
    --src /out/model.glb --dest /out/library --usage vfx_particle --preview
```

## Formats

| Format | Operator | Notes |
|--------|----------|-------|
| `.glb` / `.gltf` | `import_scene.gltf` | default output of every backend; axis and unit conversion is automatic |
| `.fbx` | `import_scene.fbx` | |
| `.obj` | `wm.obj_import`, else `import_scene.obj` | Blender 4.x replaced the Python importer with a C++ one |
| `.ply` | `wm.ply_import`, else `import_mesh.ply` | how a world export is looked at before any engine is involved |
| `.stl` | `wm.stl_import`, else `import_mesh.stl` | |
| `.usd` / `.usda` / `.usdc` / `.usdz` | `wm.usd_import` | |
| `.abc` | `wm.alembic_import` | |

Both operator names are probed for the three formats that moved, so the same
file works on 3.6 and on 4.x. A build that exposes neither raises a message
naming both instead of an `AttributeError`.

## What "conditioning" covers

| Step | When | Why it is here and not in the engine |
|------|------|--------------------------------------|
| join meshes | always, when the import produced more than one | a game asset is one object; joining before measuring makes `tris` the number the engine will see |
| pivot | `--pivot`, or the tier default | applied to the **mesh data**, not the object transform, because exporters bake transforms away |
| normalize scale | `--normalize-scale` | largest bound → 1 m (the UE5 importer says 100, working in centimetres) |
| decimate | `--target-tris` | a Decimate modifier, applied. The fallback, not the plan — see below |
| export | `--export glb fbx blend` | the point of the whole detour: hand the engine a format it likes. One flag, several values — repeating `--export` replaces rather than accumulates |
| preview | `--preview` | one Cycles-CPU poster frame; `../render_preview.py` is the richer version |

## `--usage` — three tiers, default is not VFX

Identical to the UE5 importer's, so one `--usage` means the same thing whichever
engine receives the asset.

| `--usage` | For | Triangles | Pivot | Scale |
|-----------|-----|-----------|-------|-------|
| `asset` (default) | props, weapons, characters | untouched | untouched | untouched |
| `vfx_standalone` | one mesh, no particles | untouched | re-centred | optional |
| `vfx_particle` | a mesh instanced by a particle system | budget = per-mesh tris × instances | re-centred | normalized to 1 m |

**Reduce at generation time, not here.** `TripoModel(low_poly=True)` or
`decimation_target=...` keeps UVs and normals intact; a Decimate modifier on a
finished mesh does not. `--target-tris` always records a warning saying so.

## The report is the contract

`--report` always describes the outcome, so a caller never scrapes the log:

```json
{
  "ok": true,
  "object": "Sword_001",
  "tris": 24418, "vertices": 12907, "source_tris": 24418,
  "bounds": {"min": [...], "max": [...]},
  "dimensions": [0.31, 0.08, 1.04],
  "materials": ["Material_0"],
  "exports": {"glb": "/out/library/Sword_001.glb"},
  "preview": "/out/library/Sword_001_preview.png",
  "warnings": []
}
```

`source_tris` is read from the file by the launcher before Blender starts, so a
mismatch with `tris` shows that conditioning changed the mesh rather than that
the import lost something.

## Worlds

A world export is not a mesh file, it is a Gaussian-splat PLY plus one or more
polygon PLYs. Run it through `scripts/prepare_world_asset.py` first — that fuses
the parts and repairs the surface — and import the `world.glb` it writes like any
other asset. Importing the raw collider PLY here works and is useful for looking
at what the generator produced, but it will be a triangle soup: no shared
vertices, cracks between layers, mixed winding.

## Verified

Executed against **Blender 5.0.1**, via the pip `bpy` wheel on Python 3.11, no
display and no GPU. Import, the three tiers, pivot, normalize, decimation, all
three export formats, Cycles-CPU stills and turntables, and the whole world chain
were run by hand; the numbers below are from that session. To reproduce:

```bash
pip install bpy numpy scipy pillow      # the wheel needs Python 3.11 exactly

python scripts/prepare_world_asset.py --src <export_dir> \
    --out-dir /tmp/world --task-id arena --up z --min-component-faces 4
python engine_adapters/blender/import_generated/import_mesh.py \
    --src /tmp/world/world.glb --dest /tmp/lib --name Arena --preview
```

The host side of the route — job files, argument shapes, tier defaults, operator
tables — is covered by `tests/test_world_asset.py`, which needs no Blender.

Measured, not assumed:

| | |
|---|---|
| GLB round trip | 12-triangle cube in, 12 out, dimensions identical after `glb -> Blender -> glb -> Blender` |
| Axis conversion | glTF `(x, y, z)` arrives as Blender `(x, -z, y)`; a Z-up world prepared with `--up z` lands flat, `[2, 1, 0]` |
| A repaired world | 258 triangles, 154 vertices — exactly what `prepare_world_asset.py` reported |
| Decimation | 258 tris with `--target-tris 60` gave exactly 60, plus both warnings |
| `vfx_particle` | bounds re-centred to ±0.5 / ±0.25 and largest bound normalized to 1.0 m |
| Raw collider PLY | 126 triangles across 378 vertices, confirming a PLY shares no corners |

The strongest check counted boundary edges with `bmesh` *after* the import, so
the repair was graded by Blender's topology rather than by the code that
performed it: **0** non-manifold edges and exactly **48** boundary edges, which
is the outer perimeter of a 2 × 1 sheet at eight subdivisions per unit — every
interior crack closed, the captured area's own border left open. Unrepaired, the
same input is 765 boundary edges across 255 loose pieces.

## Two things Blender 5.0 changed

Both are handled, and both are the kind of failure that looks like something else:

- **A relative output path silently writes nothing.** Blender resolves one
  against the blend file, and a headless import has none; `render()` still
  returns `FINISHED`. Every destination is made absolute, and the report only
  names an artifact after confirming it is on disk.
- **The pip wheel has no FFMPEG writer at all** — the `file_format` enum simply
  lacks it, so `--export`-adjacent video is unavailable in a way the Blender
  application does not share. The preview falls back to a PNG sequence and says
  so in `warnings`.

Legacy `import_mesh.*` operators are gone in 5.0 (the namespace is empty), which
is exactly why both names are probed rather than either hardcoded.
