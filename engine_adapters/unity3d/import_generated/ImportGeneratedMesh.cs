// engine_adapters/unity3d/import_generated/ImportGeneratedMesh.cs
//
// Imports a mesh produced by models/gen_3d_object (Tripo / Meshy)
// into a Unity project and turns it into a usable prefab.
//
// This is an **Editor** script: copy it to <UnityProject>/Assets/Editor/ (any
// folder named "Editor" works). It never runs at play time — edit-time import
// produces real assets that VFX Graph, Niagara-equivalents and prefab variants
// can reference, which runtime glTF loading cannot.
//
// GLB/GLTF support comes from glTFast's ScriptedImporter, so this file has **no
// compile-time dependency** on the package:
//     Window > Package Manager > + > Add package by name > com.unity.cloud.gltfast
// FBX / OBJ are handled by Unity natively and need nothing installed.
//
// CLI (what pipeline/ calls):
//     Unity -batchmode -quit -projectPath <proj> \
//           -executeMethod ImportGeneratedMesh.RunFromCLI \
//           --src <abs path to model.glb> \
//           --dest Assets/Generated/Meshes \
//           --name Sword_001 \
//           --usage asset \
//           --report <abs path to import_report.json>
//
// Exit code is 0 on success, 1 on failure; --report always describes what
// happened, so the caller never has to scrape the log.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

public static class ImportGeneratedMesh
{
    /// <summary>Usage tier — see agent_skills / task 7 part B4.</summary>
    public enum Usage
    {
        /// Ordinary game asset (character, prop, weapon). No decimation, no
        /// pivot change, no rescale. This is the default and covers most output.
        Asset,
        /// Single-mesh effect (energy shield, beam, blade arc). Triangle count is
        /// not the problem; pivot and tiling UVs are.
        VfxStandalone,
        /// One mesh instanced by a particle system (sword storm, debris, crows).
        /// Budget is per-mesh-triangles x instances, so it wants low poly,
        /// a meaningful pivot and a normalized size.
        VfxParticle
    }

    [Serializable]
    public class ImportReport
    {
        public bool ok;
        public string source = "";
        public string assetPath = "";
        public string prefabPath = "";
        public string usage = "";
        public int triangles;
        public int vertices;
        public int meshes;
        public int materials;
        public int extractedTextures;
        public int generatedMaterials;
        public int remappedMaterials;
        /// One line per material: shader plus every texture slot that is bound.
        /// A material count alone cannot tell "textured" from "imported white".
        public List<string> materialDetails = new List<string>();
        public int boundTextures;
        public float[] boundsCenter = new float[3];
        public float[] boundsExtents = new float[3];
        public List<string> warnings = new List<string>();
        public string error = "";
    }

    [Serializable]
    private class ImportJob
    {
        public string src = "";
        public string dest = "";
        public string name = "";
        public string usage = "";
        public int target_tris;
        public string pivot = "";
        public bool normalize_scale;
        public string prefab_dest = "";
    }

    // ── CLI ───────────────────────────────────────────────────────────────────

    /// <summary>
    /// Entry point for `-executeMethod`. Reads `--src / --dest / --name /
    /// --usage / --target-tris / --pivot / --normalize-scale / --report`.
    /// </summary>
    public static void RunFromCLI()
    {
        var args = ParseArgs(Environment.GetCommandLineArgs());
        var report = new ImportReport();
        string reportPath = Get(args, "report", null);

        try
        {
            ImportJob job = ReadJob(args);
            string src = Value(job.src, Get(args, "src", null));
            if (string.IsNullOrEmpty(src))
                throw new ArgumentException("--src <path to .glb/.fbx/.obj> is required");

            report = Import(
                src,
                Value(job.dest, Get(args, "dest", "Assets/Generated/Meshes")),
                Value(job.name, Get(args, "name", null)),
                ParseUsage(Value(job.usage, Get(args, "usage", "asset"))),
                job.target_tris > 0
                    ? (int?)job.target_tris
                    : ParseIntOrNull(Get(args, "target-tris", null)),
                Value(job.pivot, Get(args, "pivot", null)),
                job.normalize_scale || args.ContainsKey("normalize-scale"),
                Value(
                    job.prefab_dest,
                    Get(args, "prefab-dest", "Assets/Generated/Prefabs"))
            );
        }
        catch (Exception e)
        {
            report.ok = false;
            report.error = e.ToString();
            Debug.LogError("[ImportGeneratedMesh] " + e);
        }

        WriteReport(report, reportPath);
        if (Application.isBatchMode)
            EditorApplication.Exit(report.ok ? 0 : 1);
    }

    // ── Import ────────────────────────────────────────────────────────────────

    /// <summary>
    /// Copy `srcPath` into the project, import it, and save a prefab.
    /// </summary>
    /// <param name="srcPath">Absolute path to the generated mesh file.</param>
    /// <param name="destFolder">Project-relative folder, e.g. Assets/Generated/Meshes.</param>
    /// <param name="assetName">Asset base name; defaults to the source file name.</param>
    /// <param name="usage">Tier that decides pivot / scale handling.</param>
    /// <param name="targetTris">Advisory triangle budget; Unity cannot decimate
    /// on import, so exceeding it produces a warning telling the caller to
    /// regenerate low-poly (that is cheaper and keeps UVs intact).</param>
    /// <param name="pivot">null | "keep" | "center" | "bottom".</param>
    /// <param name="normalizeScale">Scale the prefab root so the largest bound is 1 unit.</param>
    /// <param name="prefabFolder">Where the prefab is written.</param>
    public static ImportReport Import(
        string srcPath,
        string destFolder = "Assets/Generated/Meshes",
        string assetName = null,
        Usage usage = Usage.Asset,
        int? targetTris = null,
        string pivot = null,
        bool normalizeScale = false,
        string prefabFolder = "Assets/Generated/Prefabs")
    {
        var report = new ImportReport { source = srcPath, usage = usage.ToString() };

        if (!File.Exists(srcPath))
            throw new FileNotFoundException("generated mesh not found", srcPath);

        string ext = Path.GetExtension(srcPath).ToLowerInvariant();
        if (ext != ".glb" && ext != ".gltf" && ext != ".fbx" && ext != ".obj")
            report.warnings.Add($"unusual extension {ext}; Unity may have no importer for it");

        if (string.IsNullOrEmpty(assetName))
            assetName = SanitizeName(Path.GetFileNameWithoutExtension(srcPath));

        // 1. Copy into the project. Unity only imports what lives under Assets/.
        Directory.CreateDirectory(destFolder);
        string assetPath = $"{destFolder}/{assetName}{ext}";
        CopyReplace(srcPath, assetPath);
        AssetDatabase.ImportAsset(assetPath, ImportAssetOptions.ForceUpdate);
        AssetDatabase.Refresh();
        report.assetPath = assetPath;

        var materialRepair = RepairImportedModelMaterials.Repair(assetPath, assetName);
        report.extractedTextures = materialRepair.extractedTextures;
        report.generatedMaterials = materialRepair.generatedMaterials;
        report.remappedMaterials = materialRepair.remappedMaterials;
        report.boundTextures = materialRepair.boundTextures;
        report.warnings.AddRange(materialRepair.warnings);
        AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

        // 2. The importer output. For .glb this is glTFast's ScriptedImporter —
        //    a null here almost always means the package is missing.
        var imported = AssetDatabase.LoadMainAssetAtPath(assetPath) as GameObject;
        if (imported == null)
        {
            if (ext == ".glb" || ext == ".gltf")
                throw new InvalidOperationException(
                    $"Unity produced no GameObject for {assetPath}. Install the glTF " +
                    "importer: Window > Package Manager > + > Add package by name > " +
                    "com.unity.cloud.gltfast   (or generate FBX instead: " +
                    "MeshyModel(output_format=\"fbx\")).");
            throw new InvalidOperationException($"Unity produced no GameObject for {assetPath}");
        }

        // 3. Instantiate so the hierarchy can be adjusted, then save a prefab.
        var instance = (GameObject)PrefabUtility.InstantiatePrefab(imported);
        try
        {
            var root = new GameObject(assetName);
            instance.transform.SetParent(root.transform, worldPositionStays: false);

            Measure(root, report);

            // glTF is Y-up / metres and Unity is Y-up / metres, so no axis fix is
            // needed here — unlike UE5, which is Z-up / centimetres.
            ApplyUsage(root, instance, usage, pivot, normalizeScale, targetTris, report);

            // Re-measure so the report describes the prefab as saved, not as
            // imported — the vfx tiers move the pivot and rescale the root.
            Measure(root, report, warnOnEmpty: false);

            Directory.CreateDirectory(prefabFolder);
            // Deterministic path, overwritten on re-import. GenerateUniqueAssetPath
            // would accumulate "obj_0 1.prefab", "obj_0 2.prefab" every time the
            // same task is regenerated, and nothing downstream would follow.
            string prefabPath = $"{prefabFolder}/{assetName}.prefab";
            if (File.Exists(prefabPath))
                report.warnings.Add($"replaced existing prefab {prefabPath}");
            PrefabUtility.SaveAsPrefabAsset(root, prefabPath);
            report.prefabPath = prefabPath;

            UnityEngine.Object.DestroyImmediate(root);
        }
        finally
        {
            if (instance != null && instance.transform.parent == null)
                UnityEngine.Object.DestroyImmediate(instance);
        }

        AssetDatabase.SaveAssets();
        report.ok = true;
        Debug.Log($"[ImportGeneratedMesh] {report.prefabPath}  tris={report.triangles}  " +
                  $"materials={report.materials} textures={report.extractedTextures} " +
                  $"remaps={report.remappedMaterials} boundTextures={report.boundTextures} " +
                  $"warnings={report.warnings.Count}");
        return report;
    }

    // ── Post-import ───────────────────────────────────────────────────────────

    static void ApplyUsage(GameObject root, GameObject instance, Usage usage,
                           string pivot, bool normalizeScale, int? targetTris,
                           ImportReport report)
    {
        // Tier defaults. An explicit --pivot / --normalize-scale always wins.
        switch (usage)
        {
            case Usage.Asset:
                // Default tier: touch nothing. A prop must land exactly as authored.
                if (string.IsNullOrEmpty(pivot)) pivot = "keep";
                break;
            case Usage.VfxStandalone:
                if (string.IsNullOrEmpty(pivot)) pivot = "center";
                report.warnings.Add(
                    "vfx_standalone: check the material (emissive / translucent / " +
                    "fresnel, not PBR) and that UVs tile seamlessly if the texture scrolls");
                break;
            case Usage.VfxParticle:
                if (string.IsNullOrEmpty(pivot)) pivot = "center";
                normalizeScale = true;
                break;
        }

        if (pivot != "keep")
            ApplyPivot(root, instance, pivot, report);

        if (normalizeScale)
        {
            var b = CurrentBounds(root);
            float largest = Mathf.Max(b.size.x, Mathf.Max(b.size.y, b.size.z));
            if (largest > 1e-6f)
            {
                root.transform.localScale = Vector3.one / largest;
                report.warnings.Add($"normalized scale by 1/{largest:F4}");
            }
        }

        if (targetTris.HasValue && report.triangles > targetTris.Value)
        {
            // B4.3 — decimating here would wreck UVs and normals. The right fix
            // is upstream: TripoModel(low_poly=True) / MeshyModel(low_poly=True),
            // or decimation_target on the generation call.
            report.warnings.Add(
                $"{report.triangles} triangles exceeds target_tris={targetTris.Value}; " +
                "Unity does not decimate on import. Regenerate low-poly instead " +
                "(low_poly=True / decimation_target=...).");
        }
    }

    static void ApplyPivot(GameObject root, GameObject instance, string pivot,
                           ImportReport report)
    {
        var b = CurrentBounds(root);
        Vector3 target;
        switch ((pivot ?? "center").ToLowerInvariant())
        {
            case "center": target = b.center; break;
            case "bottom": target = new Vector3(b.center.x, b.min.y, b.center.z); break;
            case "top":    target = new Vector3(b.center.x, b.max.y, b.center.z); break;
            default:
                report.warnings.Add($"unknown pivot '{pivot}'; left unchanged");
                return;
        }
        // Move the child, not the root: the root transform stays the prefab's
        // handle, so instantiating it places the chosen point at the origin.
        instance.transform.localPosition -= target;
        report.warnings.Add($"pivot moved to {pivot} (offset {-target})");
    }

    static void Measure(GameObject root, ImportReport report, bool warnOnEmpty = true)
    {
        var meshes = new HashSet<Mesh>();
        int tris = 0, verts = 0;

        foreach (var mf in root.GetComponentsInChildren<MeshFilter>(true))
            if (mf.sharedMesh != null) meshes.Add(mf.sharedMesh);
        foreach (var smr in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            if (smr.sharedMesh != null) meshes.Add(smr.sharedMesh);

        foreach (var mesh in meshes)
        {
            verts += mesh.vertexCount;
            for (int i = 0; i < mesh.subMeshCount; i++)
                tris += (int)(mesh.GetIndexCount(i) / 3);
        }

        var materials = new HashSet<Material>();
        foreach (var r in root.GetComponentsInChildren<Renderer>(true))
            foreach (var m in r.sharedMaterials)
                if (m != null) materials.Add(m);

        var b = CurrentBounds(root);
        report.triangles = tris;
        report.vertices = verts;
        report.meshes = meshes.Count;
        report.materials = materials.Count;
        report.boundsCenter = new[] { b.center.x, b.center.y, b.center.z };
        report.boundsExtents = new[] { b.extents.x, b.extents.y, b.extents.z };

        report.materialDetails.Clear();
        report.boundTextures = 0;
        foreach (var m in materials)
            report.materialDetails.Add(DescribeMaterial(m, report));

        if (!warnOnEmpty) return;
        if (tris == 0) report.warnings.Add("imported object has no triangles");
        if (materials.Count == 0) report.warnings.Add("imported object has no materials");
        if (materials.Count > 0 && report.boundTextures == 0)
            report.warnings.Add(
                "no texture is bound to any material: the mesh imported but it " +
                "will render untextured. Check that the source file embeds its " +
                "textures and that the render pipeline matches the shaders glTFast picked");
    }

    /// <summary>
    /// "name | shader=X | tex: _BaseMap=y, _BumpMap=z" for one material, and
    /// count the bound texture slots into the report.
    /// </summary>
    static string DescribeMaterial(Material m, ImportReport report)
    {
        var shader = m.shader;
        var bound = new List<string>();
        try
        {
            int count = ShaderUtil.GetPropertyCount(shader);
            for (int i = 0; i < count; i++)
            {
                if (ShaderUtil.GetPropertyType(shader, i) != ShaderUtil.ShaderPropertyType.TexEnv)
                    continue;
                string prop = ShaderUtil.GetPropertyName(shader, i);
                var tex = m.GetTexture(prop);
                if (tex == null) continue;
                bound.Add($"{prop}={tex.name}");
                report.boundTextures++;
            }
        }
        catch (Exception e)
        {
            bound.Add($"<could not read shader properties: {e.Message}>");
        }
        string shaderName = shader != null ? shader.name : "<none>";
        // glTF materials often carry no name (Meshy's do not), and an empty
        // string at the front of the line reads like a missing field.
        string matName = string.IsNullOrEmpty(m.name) ? "<unnamed>" : m.name;
        return bound.Count > 0
            ? $"{matName} | shader={shaderName} | tex: {string.Join(", ", bound)}"
            : $"{matName} | shader={shaderName} | tex: <none bound>";
    }

    static Bounds CurrentBounds(GameObject root)
    {
        var renderers = root.GetComponentsInChildren<Renderer>(true);
        if (renderers.Length == 0) return new Bounds(Vector3.zero, Vector3.zero);
        var b = renderers[0].bounds;
        foreach (var r in renderers.Skip(1)) b.Encapsulate(r.bounds);
        return b;
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    static ImportJob ReadJob(Dictionary<string, string> args)
    {
        string jobPath = Get(args, "job", null);
        if (string.IsNullOrEmpty(jobPath) || !File.Exists(jobPath))
            return new ImportJob();
        ImportJob job = JsonUtility.FromJson<ImportJob>(File.ReadAllText(jobPath));
        return job ?? new ImportJob();
    }

    static string Value(string preferred, string fallback)
    {
        return !string.IsNullOrEmpty(preferred) ? preferred : fallback;
    }

    static void CopyReplace(string source, string destination)
    {
        if (File.Exists(destination))
        {
            File.SetAttributes(destination, FileAttributes.Normal);
            File.Delete(destination);
        }
        File.Copy(source, destination, overwrite: false);
        File.SetAttributes(destination, FileAttributes.Normal);
    }

    static void WriteReport(ImportReport report, string reportPath)
    {
        string json = JsonUtility.ToJson(report, prettyPrint: true);
        Debug.Log("[ImportGeneratedMesh] report " + json);
        if (string.IsNullOrEmpty(reportPath)) return;
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(reportPath)));
        File.WriteAllText(reportPath, json);
    }

    static Dictionary<string, string> ParseArgs(string[] argv)
    {
        var args = new Dictionary<string, string>();
        for (int i = 0; i < argv.Length; i++)
        {
            if (!argv[i].StartsWith("--")) continue;
            string key = argv[i].Substring(2);
            string value = (i + 1 < argv.Length && !argv[i + 1].StartsWith("--"))
                ? argv[++i] : "";
            args[key] = value;
        }
        return args;
    }

    static string Get(Dictionary<string, string> args, string key, string fallback)
    {
        if (args.TryGetValue(key, out var v) && !string.IsNullOrEmpty(v)) return v;
        return GameFactory3AEditorBridge.GetArgument(key, fallback);
    }

    static int? ParseIntOrNull(string s)
    {
        return int.TryParse(s, out int v) ? v : (int?)null;
    }

    static Usage ParseUsage(string s)
    {
        switch ((s ?? "asset").ToLowerInvariant().Replace("-", "_"))
        {
            case "asset": return Usage.Asset;
            case "vfx_standalone": return Usage.VfxStandalone;
            case "vfx_particle": return Usage.VfxParticle;
            default:
                throw new ArgumentException(
                    $"unknown --usage {s}; expected asset | vfx_standalone | vfx_particle");
        }
    }

    static string SanitizeName(string name)
    {
        foreach (char c in Path.GetInvalidFileNameChars()) name = name.Replace(c, '_');
        return name.Replace(' ', '_');
    }

    // ── Menu ──────────────────────────────────────────────────────────────────

    [MenuItem("3AGameFactory/Import generated mesh…")]
    static void ImportFromMenu()
    {
        string src = EditorUtility.OpenFilePanel(
            "Pick a generated mesh", "", "glb,gltf,fbx,obj");
        if (string.IsNullOrEmpty(src)) return;
        Import(src);
    }
}
