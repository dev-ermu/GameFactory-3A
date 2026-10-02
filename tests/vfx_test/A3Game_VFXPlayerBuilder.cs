using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class A3GameVFXPlayerBuilder
{
    const string ParticlePackRoot =
        "Assets/UnityTechnologies/ParticlePack/EffectExamples";
    const string ScenePath = "Assets/A3Game_VFXReview/RuntimeCapture.unity";
    const string SmokeShaderPath =
        "Assets/A3Game_VFXReview/Runtime/A3Game_SoftParticle.shader";
    const string GeneratedSmokeMaterialPath =
        "Assets/A3Game_VFXReview/Runtime/A3Game_ParticlePackSmoke.mat";

    [MenuItem("A3Game/VFX/Open Interactive Review")]
    public static void OpenInteractiveReview()
    {
        EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
        Debug.Log(
            "[AAAGF_VFX_REVIEW] Opened interactive fire/smoke scene. " +
            "Enter Play mode to view both effects side by side.");
    }

    public static void Build()
    {
        var playerPath = Environment.GetEnvironmentVariable("AAAGF_VFX_PLAYER_PATH");
        if (string.IsNullOrWhiteSpace(playerPath))
            throw new InvalidOperationException("AAAGF_VFX_PLAYER_PATH is required");

        EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        var cameraObject = new GameObject("ReviewCamera");
        cameraObject.tag = "MainCamera";
        var camera = cameraObject.AddComponent<Camera>();
        camera.clearFlags = CameraClearFlags.SolidColor;
        camera.backgroundColor = new Color(0.035f, 0.04f, 0.05f, 1f);
        camera.fieldOfView = 38f;
        camera.allowHDR = true;

        var lightObject = new GameObject("ReviewLight");
        var light = lightObject.AddComponent<Light>();
        light.type = LightType.Directional;
        light.intensity = 1.2f;
        light.transform.rotation = Quaternion.Euler(40f, -35f, 0f);

        var runner = new GameObject("RuntimeCapture")
            .AddComponent<A3GameVFXRuntimeCapture>();
        runner.reviewCamera = camera;
        runner.cases = new[]
        {
            MakeCase("fire_large", "fire",
                ParticlePackRoot + "/Fire & Explosion Effects/Prefabs/LargeFlames.prefab",
                0.65f),
            MakeLibrarySmokeCase(
                ParticlePackRoot + "/Smoke & Steam Effects/Textures/SmokePuff04.png"),
        };

        EditorSceneManager.SaveScene(EditorSceneManager.GetActiveScene(), ScenePath);
        Directory.CreateDirectory(Path.GetDirectoryName(playerPath));
        var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
        {
            scenes = new[] { ScenePath },
            locationPathName = playerPath,
            target = BuildTarget.StandaloneWindows64,
            options = BuildOptions.None,
        });
        if (report.summary.result != BuildResult.Succeeded)
            throw new InvalidOperationException(
                $"Runtime review player build failed: {report.summary.result}");
        Debug.Log($"[AAAGF_VFX_PLAYER] PASS: built {playerPath}");
    }

    static A3GameVFXCaptureCase MakeCase(
        string name, string category, string prefabPath, float scale)
    {
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
        if (prefab == null)
            throw new InvalidOperationException($"Particle Pack prefab missing: {prefabPath}");
        return new A3GameVFXCaptureCase
        {
            name = name,
            category = category,
            prefab = prefab,
            scale = scale,
        };
    }

    static A3GameVFXCaptureCase MakeLibrarySmokeCase(string texturePath)
    {
        var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(texturePath);
        if (texture == null)
            throw new InvalidOperationException($"Particle Pack texture missing: {texturePath}");
        var shader = AssetDatabase.LoadAssetAtPath<Shader>(SmokeShaderPath);
        if (shader == null)
            throw new InvalidOperationException($"A3Game shader missing: {SmokeShaderPath}");
        if (AssetDatabase.LoadAssetAtPath<Material>(GeneratedSmokeMaterialPath) != null)
            AssetDatabase.DeleteAsset(GeneratedSmokeMaterialPath);
        var material = new Material(shader) { name = "A3Game_ParticlePackSmoke" };
        material.mainTexture = texture;
        material.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
        material.SetInt("_DstBlend", (int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
        material.SetInt("_ZWrite", 0);
        material.renderQueue = 3000;
        AssetDatabase.CreateAsset(material, GeneratedSmokeMaterialPath);
        AssetDatabase.SaveAssets();
        return new A3GameVFXCaptureCase
        {
            name = "smoke_library_texture",
            category = "smoke",
            particleMaterial = material,
        };
    }
}
