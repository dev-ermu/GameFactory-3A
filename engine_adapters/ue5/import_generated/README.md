# ue5/import_generated

Turns a file produced by `models/gen_3d_object` into a usable UE5 asset.

> Scope note: this directory is the **importer for generated assets**. Engine
> interface functions and serving code migrated in task 1 live one level up in
> `engine_adapters/ue5/`; keep the two apart.

## Files

| File | Runs where | Purpose |
|------|-----------|---------|
| `import_mesh.py` | Unreal's Python | import → validate → report |
| `../../../scripts/import_generated_asset.py` | host Python | finds the editor, launches the above, reads the report |

## Quick start

```bash
# one asset
python scripts/import_generated_asset.py \
    --src test_data/outputs/<game>/<run>/assets/3d_object/<task>/model.glb \
    --engine ue5 --uproject D:/proj/MyGame/MyGame.uproject

# everything one generation run produced
python scripts/import_generated_asset.py --engine ue5 \
    --summary test_data/outputs/<game>/<run>/3d_object_results_summary.json
```

Or call the engine directly. Parameters go through a **job file** named by
`AAAGF_IMPORT_JOB`, because `-script="file.py --a b"` has to survive both the
shell and UE's own argument parser and paths lose their quoting on the way:

```bat
echo {"src":"C:/out/model.glb","dest":"/Game/Generated/Meshes", ^
      "name":"Sword_001","usage":"asset","report":"C:/out/ue5_import.json"} > C:/out/job.json
set AAAGF_IMPORT_JOB=C:/out/job.json
set AAAGF_UE_QUIT_WHEN_DONE=1
UnrealEditor.exe MyGame.uproject ^
  -ExecutePythonScript=engine_adapters/ue5/import_generated/import_mesh.py ^
  -unattended -nopause -nosplash -stdout
```

### Why the full editor and not a commandlet

`--ue-mode editor` (the default) launches `UnrealEditor.exe`; `--ue-mode
commandlet` launches `UnrealEditor-Cmd.exe -run=pythonscript`, which starts
faster and opens no window.

**The commandlet route does not work on UE 5.7.** Both AssetTools entry points
(`import_assets_automated` and `import_asset_tasks`) complete the import and then
sync the Content Browser, which asserts in `FSlateApplication::Get()` because a
commandlet has no Slate application. The mesh is built and saved first, so the
crash looks like a success followed by a stack dump. Measured, not guessed:

```
LogStaticMesh: Built static mesh /Game/Generated/Meshes/StubSword
LogInterchangeEngine: Interchange import completed [.../stub_sword.glb]
LogWindows: Error: Assertion failed: CurrentApplication.IsValid()
            [SlateApplication.h] [Line: 321]
```

`InterchangeManager.import_asset` avoids AssetTools and does not crash, but the
scripted call is asynchronous: it returns before any asset exists. It stays in
the route list as a last resort, not as the answer.

If a future build fixes the sync, `--ue-mode commandlet` becomes the faster
option again; nothing else has to change.

Inside the editor's Python console the ordinary CLI flags work too:

```python
import import_mesh
import_mesh.main(["--src", "C:/out/model.glb", "--dest", "/Game/Generated/Meshes"])
```

The project needs the **Python Editor Script Plugin** enabled:

```json
"Plugins": [ { "Name": "PythonScriptPlugin", "Enabled": true } ]
```

`--report` always describes the outcome, so a caller never scrapes the log:

```json
{
  "ok": true,
  "asset_path": "/Game/Generated/Meshes/Sword_001",
  "tris": 24418, "vertices": 12907, "lods": 1,
  "bounds": {"origin": [...], "box_extent": [...], "sphere_radius": 71.4},
  "materials": ["Material_0"],
  "warnings": []
}
```

## Formats

| Format | Route | Notes |
|--------|-------|-------|
| `.glb` / `.gltf` | Interchange glTF translator | default output of every backend; single file, textures embedded |
| `.fbx` | `FbxImportUI` (or Interchange in newer builds) | fallback when a project cannot use glTF |
| `.obj` / `.usd` | Interchange | untested here |

**Enable the glTF importer plugin** if `.glb` yields nothing — the script says so
explicitly instead of failing silently.

## Coordinate system — verified, not assumed

glTF is Y-up, right-handed, metric; UE is Z-up, left-handed, centimetre. **The
translator does the whole conversion**, so do not pre-rotate or pre-scale the
file. Measured on UE 5.7 with a GLB spanning 1.0 × 1.0 × 1.1 m:

```
"bounds": {"origin": [50.0, 55.0, 50.0], "box_extent": [50.0, 55.0, 50.0]}
```

1 m arrives as 100 uu, and the glTF Z axis (the 1.1 m one) arrives as UE Y.
Triangle and vertex counts came through exactly (12 tris, 36 verts).

The bounds are in the report of every import, so this stays checkable per asset
rather than being an assumption in a doc.

## `--usage` — three tiers, default is not VFX

`gen_3d_object` mostly produces ordinary game assets. VFX is an opt-in branch.

| `--usage` | For | Triangles | Pivot | Scale |
|-----------|-----|-----------|-------|-------|
| `asset` (default) | props, weapons, characters | untouched | untouched | untouched |
| `vfx_standalone` | energy shield / beam / blade arc — one mesh, no particles | untouched | re-centred (`--pivot bottom` for something growing off the ground) | optional |
| `vfx_particle` | sword storm / debris / flocks — a mesh instanced by Niagara | budget = per-mesh tris × instances | re-centred | normalized to 1 m |

`--target-tris` is advisory and defaults to none. There is no hard cap: 2 K
triangles is plenty for a sword that covers forty pixels while trailing a glow,
and Nanite plus GPU simulation moves the limit again. Measure the frame time.

**Reduce at generation time, not here** — `TripoModel(low_poly=True)` or
`decimation_target=...` keeps UVs and normals intact; decimating a 2 M-face mesh
afterwards does not. If `--target-tris` is exceeded, the script attempts a
reduction and always records a warning saying so.

## Verified

Executed against **UE 5.7**, `--ue-mode editor`, on a blank project and on a real
one (a VFX project whose `.uproject` did not have the Python plugin — the plugin
was turned on for that run with `--ue-extra=-EnablePlugins=PythonScriptPlugin`,
leaving the project file untouched).

A **textured** GLB (cube, embedded PNG, PBR material):

```json
{"ok": true, "asset_path": "/Game/Generated/Meshes/AAAGF_SmokeCube",
 "tris": 12, "vertices": 24, "lods": 1,
 "bounds": {"origin": [50,50,50], "box_extent": [50,50,50]},
 "materials": ["StubCheckerMaterial"],
 "warnings": ["3 assets imported (…/Textures/StubChecker, …/Materials/StubCheckerMaterial, …/StaticMeshes/stub_cube_textured)",
              "asset moved …/stub_cube_textured → …/AAAGF_SmokeCube"]}
```

Geometry, unit conversion, the material, the embedded texture and three
`.uasset` files on disk all check out. Reproduce the fixture with
`tests/harness/stubs.py:make_textured_glb()` — it needs no API key.

Two Interchange behaviours the importer works around, both visible in the
warnings rather than hidden:

- it names the asset after the **source file** and buries it under
  `<file>/StaticMeshes/`, ignoring the import task's `destination_name`, so the
  mesh is moved to `<dest>/<name>` afterwards;
- it emits the texture and the material as **separate packages**. Saving only the
  mesh leaves them dirty in memory and the editor exits with a mesh referencing a
  material that never reached disk, so every imported package is saved.

A **real generated asset** (Meshy image-to-3D, 8.4 MB, 19 288 triangles, four
embedded PBR textures) imported into a real VFX project produced six assets, all
saved: four `Texture2D`, one `Material`, one `StaticMesh`.

`--usage vfx_particle` on the same asset is verified too: the `automated` route
declined (it cannot carry an import offset), the run fell through to the
`task` route which carried them on a duplicated Interchange pipeline, and the
result came back re-centred with `box_extent [39.4, 47.4, 50.0]` — the largest
bound normalized to exactly 100 uu.

One wrinkle: the two routes place the generated material and textures
differently. `automated` puts them under `<source>/Materials/` and
`<source>/Textures/`; `task` puts them flat in the destination folder. Importing
the same source both ways therefore leaves two sets, each referenced by its own
mesh.

**Not verified**: FBX / OBJ / USD paths, multi-material assets, and
`--target-tris` reduction. Every optional engine property is probed with
`getattr` before use, so a build that lacks one lands a warning in the report
instead of a crash.

## Do not run this while the project is open

The importer launches its own editor process. Running it against a project that
is already open in the editor means two editors on one project: the assets land
on disk but the open editor keeps showing its own stale view of the Content
Browser, which reads exactly like "the import silently did nothing". Close the
editor first, or reopen it afterwards.

## Nanite changes what `tris` means

UE 5.7 enables Nanite on imported static meshes, and
`StaticMesh.get_num_triangles(0)` then returns the **fallback** mesh — built to a
relative-error target, not to the source density. Measured on the asset above:

| | triangles |
|---|---|
| source GLB | 19 288 |
| Unity | 19 288 |
| UE `get_num_triangles(0)` | **4 480** |

Nothing was lost in the import; the two engines are reporting different meshes.
UE's own build log spells all three numbers out:

```
LogStaticMesh: Adjacency [0.01s], tris: 19288, UVs 1     ← what UE read from the file
LogStaticMesh: Fallback [0.15s], num tris: 4480          ← what get_num_triangles(0) returns
LogStaticMesh: ConstrainClusters: Input: 311 Clusters, 39188 Triangles
```

The 39 188 is the whole Nanite cluster hierarchy — the 19 288 leaf triangles plus
the coarser parent levels of the LOD DAG, roughly 2x, which is normal.

The report therefore carries `source_tris` (read from the GLB by the launcher
before the engine starts) and a `nanite` block next to `tris`:

```json
{"tris": 4480, "source_tris": 19288,
 "nanite": {"enabled": true, "fallback_percent_triangles": 1.0,
            "fallback_relative_error": 1.0}}
```

Size a mesh-particle budget off `source_tris`, not off `tris` — and remember
Nanite relaxes that budget substantially in the first place (part B4.2).

## Normal-map convention

glTF normal maps are OpenGL convention (green up); UE defaults to DirectX
convention (green down). Tripo even names its map `NormalGL_*`. The translator is
expected to handle the flip, but a mishandled green channel shows up only as
lighting leaning the wrong way, which no report catches. Worth one look with a
moving light the first time a project imports a normal-mapped asset.
