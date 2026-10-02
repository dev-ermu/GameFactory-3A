# unity3d/import_generated

Turns a file produced by `models/gen_3d_object` into a Unity **prefab**.

> Scope note: this directory is the **importer for generated assets**. Engine
> interface functions and serving code migrated in task 1 live one level up in
> `engine_adapters/unity3d/`; keep the two apart.

## Files

| File | Runs where | Purpose |
|------|-----------|---------|
| `ImportGeneratedMesh.cs` | Unity Editor (`Assets/Editor/`) | import → prefab → validate → report |
| `../../../scripts/import_generated_asset.py` | host Python | finds Unity, copies this script into the project, launches it, reads the report |

## Quick start

The Unity Editor must already be activated in the matching Unity Hub (or
opened as a licensed Editor) before this command is run. Licensing is owned by
Unity Hub, not this importer; an exit code 199 or a missing LicensingClient IPC
channel is reported as a blocked host prerequisite.

```bash
python scripts/import_generated_asset.py \
    --src test_data/outputs/<game>/<run>/assets/3d_object/<task>/model.glb \
    --engine unity --unity-project D:/proj/MyGame
```

The launcher copies `ImportGeneratedMesh.cs` into `<project>/Assets/Editor/`
first — Unity only compiles editor code that lives in a folder named `Editor`,
so it cannot be referenced from this repo in place. Pass
`--no-install-editor-script` once you have vendored it yourself.

Direct invocation:

```bash
Unity -batchmode -quit -nographics -projectPath D:/proj/MyGame \
      -executeMethod ImportGeneratedMesh.RunFromCLI \
      --src C:/out/model.glb --dest Assets/Generated/Meshes \
      --name Sword_001 --report C:/out/unity_import.json
```

In the editor there is also **3AGameFactory ▸ Import generated mesh…**.

## Prerequisite: glTF support

Unity has no built-in glTF importer. Install glTFast once per project:

```
Window ▸ Package Manager ▸ + ▸ Add package by name ▸ com.unity.cloud.gltfast
```

or add it to `Packages/manifest.json`:

```json
{ "dependencies": { "com.unity.cloud.gltfast": "6.16.0" } }
```

`ImportGeneratedMesh.cs` has **no compile-time dependency** on the package — it
copies the file under `Assets/` and lets the ScriptedImporter handle it, then
reports an actionable error if nothing came out. Edit-time import is deliberate:
it produces real assets that prefabs, VFX Graph and Timeline can reference,
which runtime `GltfImport` cannot.

FBX and OBJ need nothing installed. If glTFast cannot be added to a project,
generate FBX instead: `MeshyModel(output_format="fbx")`.

## Output

```
Assets/Generated/Meshes/Sword_001.glb        the imported source asset
Assets/Generated/Prefabs/Sword_001.prefab    what you drop into a scene
```

The report:

```json
{
  "ok": true,
  "assetPath": "Assets/Generated/Meshes/Sword_001.glb",
  "prefabPath": "Assets/Generated/Prefabs/Sword_001.prefab",
  "triangles": 24418, "vertices": 12907, "meshes": 1, "materials": 1,
  "materialDetails": ["model_material_0 | shader=glTF-pbrMetallicRoughness | tex: baseColorTexture=texture_0, normalTexture=texture_2"],
  "boundTextures": 4,
  "boundsCenter": [0,0,0], "boundsExtents": [0.35,0.71,0.04],
  "warnings": []
}
```

`materialDetails` and `boundTextures` exist because a material **count** cannot
tell a textured asset from one that imported white: the mesh, the material and
the prefab can all be present while every texture slot is empty. That is the
usual shape of a glTFast or render-pipeline mismatch, and it now raises a
warning instead of passing silently.

A prefab rather than a bare mesh, because the prefab root is where the pivot
offset and the normalized scale live, and because particle systems and VFX Graph
reference prefabs.

## Coordinate system

glTF and Unity are both Y-up and metric, so no axis conversion happens here
(unlike UE5, which is Z-up and centimetre). glTFast handles the handedness flip.

## `--usage` — three tiers, default is not VFX

| `--usage` | For | Triangles | Pivot | Scale |
|-----------|-----|-----------|-------|-------|
| `asset` (default) | props, weapons, characters | untouched | untouched | untouched |
| `vfx_standalone` | shield / beam / blade arc — one mesh, no particles | untouched | re-centred (`--pivot bottom` for something growing off the ground) | optional |
| `vfx_particle` | debris / sword storm — a mesh instanced by a particle system | budget = per-mesh tris × instances | re-centred | normalized to 1 unit |

Unity **cannot decimate on import**. If `--target-tris` is exceeded the report
says so and tells you to regenerate low-poly (`low_poly=True` on the cloud
backends), which is both cheaper and kinder to the UVs.

## Render pipeline

Materials come in through glTFast's shaders. Built-in, URP and HDRP each need a
different shader variant set; confirm which pipeline the target project uses
before judging a "material looks wrong" report. Nothing in this script rewrites
materials — for `vfx_standalone` the material almost always has to be swapped
for an emissive / translucent / fresnel one by hand.

## Verified

Executed in batch mode against **Unity 6000.5.2f1** with
`com.unity.cloud.gltfast` 6.16.0, built-in render pipeline:

- untextured GLB, `usage=asset` — prefab, 12/12 triangles, report round-trip;
- **textured** GLB (cube, embedded PNG, PBR material) — 12 tris, 24 verts,
  1 material, no warnings. Reproduce the fixture with
  `tests/harness/stubs.py:make_textured_glb()`, no API key needed;
- `usage=vfx_particle` — pivot re-centred to the origin and the largest bound
  normalized to 1 unit, both confirmed in the re-measured bounds;
- batch through `--summary`, and re-import overwriting the previous prefab.

**Not verified**: URP / HDRP material conversion (built-in only so far), and
FBX / OBJ paths.

## Looking at the result by hand

The batch importer reports numbers; only your eyes catch "the mesh is inside
out" or "the texture is on the wrong island". To inspect a run:

1. Unity Hub ▸ Add ▸ Add project from disk ▸ pick the project folder, open it
   with the matching editor version (**do not** run a batch import while the
   project is open in the editor — the running editor keeps showing its own view
   of the Content Browser and the newly written assets look missing);
2. Project window ▸ `Assets/Generated/Prefabs/` ▸ drag the prefab into the scene;
3. check three things the report cannot: the silhouette, whether the textures
   land on the right places, and the orientation (glTF is Y-up like Unity, so
   an asset lying on its face means the source is wrong, not the import);
4. select the mesh under the prefab root and read the Inspector's mesh info line
   against `triangles` in the report.

A fresh project takes a few minutes on first open while packages resolve and
`Library/` is rebuilt. `Library/` is disposable — deleting it is also the fix
when package compilation goes wrong.

### If Unity exits 1 with no report

Check the `.unity.log` next to the report. Compile errors spread across
`com.unity.collections`, `com.unity.test-framework` and glTFast mean the
project's package cache resolved inconsistently — delete `<project>/Library/`
and run again. That happened once here and re-resolving fixed it.
