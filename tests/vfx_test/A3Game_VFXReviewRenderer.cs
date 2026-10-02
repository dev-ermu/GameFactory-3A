using System;
using System.IO;
using A3Game.EngineAdapters;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class A3GameVFXReviewRenderer
{
    const int Size = 512;
    const int Fps = 30;
    const int FrameCount = 60;
    const string ParticlePackRoot =
        "Assets/UnityTechnologies/ParticlePack/EffectExamples";
    const string FirePrefab = ParticlePackRoot +
        "/Fire & Explosion Effects/Prefabs/MediumFlames.prefab";
    const string SmokePrefab = ParticlePackRoot +
        "/Smoke & Steam Effects/Prefabs/SmokeEffect.prefab";
    const string LargeFirePrefab = ParticlePackRoot +
        "/Fire & Explosion Effects/Prefabs/LargeFlames.prefab";
    const string WildFirePrefab = ParticlePackRoot +
        "/Fire & Explosion Effects/Prefabs/WildFire.prefab";
    const string RisingSteamPrefab = ParticlePackRoot +
        "/Smoke & Steam Effects/Prefabs/RisingSteam.prefab";
    const string RocketTrailPrefab = ParticlePackRoot +
        "/Smoke & Steam Effects/Prefabs/RocketTrail.prefab";

    public static void Run()
    {
        var outputRoot = Environment.GetEnvironmentVariable("AAAGF_VFX_REVIEW_ROOT");
        if (string.IsNullOrWhiteSpace(outputRoot))
            throw new InvalidOperationException("AAAGF_VFX_REVIEW_ROOT is required");

        RenderCase("fire", "fire", outputRoot, () =>
            SpawnLibraryPrefabOrFallback(LargeFirePrefab, 0.65f, () => A3GameVFX.SpawnFire(
                Vector3.zero, new FireOptions { loop = true, duration = 2f })));
        RenderCase("smoke", "smoke", outputRoot, () =>
            SpawnParticlePackSmoke());

        Debug.Log("[AAAGF_VFX_REVIEW] PASS: rendered Particle Pack fire and smoke review frames");
    }

    public static void RunCandidates()
    {
        var outputRoot = Environment.GetEnvironmentVariable("AAAGF_VFX_REVIEW_ROOT");
        if (string.IsNullOrWhiteSpace(outputRoot))
            throw new InvalidOperationException("AAAGF_VFX_REVIEW_ROOT is required");

        RenderCase("fire_medium", "fire", outputRoot,
            () => SpawnLibraryPrefab(FirePrefab, 0.75f));
        RenderCase("fire_large", "fire", outputRoot,
            () => SpawnLibraryPrefab(LargeFirePrefab, 0.42f));
        RenderCase("fire_wild", "fire", outputRoot,
            () => SpawnLibraryPrefab(WildFirePrefab, 0.38f));
        RenderCase("smoke_effect", "smoke", outputRoot,
            () => SpawnLibraryPrefab(SmokePrefab, 0.5f));
        RenderCase("smoke_rising", "smoke", outputRoot,
            () => SpawnLibraryPrefab(RisingSteamPrefab, 0.8f));
        RenderCase("smoke_rocket", "smoke", outputRoot,
            () => SpawnLibraryPrefab(RocketTrailPrefab, 0.45f));

        Debug.Log("[AAAGF_VFX_REVIEW] PASS: rendered six Particle Pack candidates");
    }

    public static void RunSmokeCandidates()
    {
        var outputRoot = Environment.GetEnvironmentVariable("AAAGF_VFX_REVIEW_ROOT");
        if (string.IsNullOrWhiteSpace(outputRoot))
            throw new InvalidOperationException("AAAGF_VFX_REVIEW_ROOT is required");

        RenderCase("smoke_effect", "smoke", outputRoot,
            () => SpawnLibraryPrefab(SmokePrefab, 0.5f));
        RenderCase("smoke_rising", "smoke", outputRoot,
            () => SpawnLibraryPrefab(RisingSteamPrefab, 0.8f));

        Debug.Log("[AAAGF_VFX_REVIEW] PASS: rendered two Particle Pack smoke candidates");
    }

    static GameObject SpawnLibraryPrefab(string prefabPath, float scale)
    {
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
        if (prefab == null)
            throw new InvalidOperationException($"Particle Pack prefab missing: {prefabPath}");
        Debug.Log($"[AAAGF_VFX_REVIEW] Using Particle Pack prefab: {prefabPath}");
        return A3GameVFX.SpawnPrefab(
            prefab, Vector3.zero, Quaternion.identity, Vector3.one * scale);
    }

    static GameObject SpawnParticlePackSmoke()
    {
        var texturePath = ParticlePackRoot +
            "/Smoke & Steam Effects/Textures/SmokePuff04.png";
        var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(texturePath);
        if (texture == null)
            throw new InvalidOperationException($"Particle Pack texture missing: {texturePath}");
        return A3GameVFX.SpawnSmoke(
            Vector3.zero,
            new SmokeOptions
            {
                loop = true,
                duration = 4f,
                lifetime = 3f,
                emissionRate = 25f,
                riseSpeed = 1f,
                startSize = 0.9f,
                radius = 0.3f,
                color = new Color(0.42f, 0.45f, 0.48f, 0.68f),
                particleTexture = texture,
                textureSheetTiles = new Vector2Int(5, 5),
            });
    }

    static GameObject SpawnLibraryPrefabOrFallback(
        string prefabPath, float scale, Func<GameObject> fallback)
    {
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
        if (prefab != null)
            return SpawnLibraryPrefab(prefabPath, scale);

        Debug.LogWarning(
            $"[AAAGF_VFX_REVIEW] Particle Pack prefab missing: {prefabPath}; " +
            "using procedural fallback");
        return fallback();
    }

    static void RenderCase(
        string caseName, string category, string outputRoot, Func<GameObject> spawn)
    {
        EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        var cameraObject = new GameObject("ReviewCamera");
        var camera = cameraObject.AddComponent<Camera>();
        camera.transform.position = category == "smoke"
            ? new Vector3(0f, 1.4f, -6.5f)
            : new Vector3(0f, 1.2f, -5.5f);
        camera.transform.LookAt(new Vector3(0f, 1.0f, 0f));
        camera.clearFlags = CameraClearFlags.SolidColor;
        camera.backgroundColor = new Color(0.035f, 0.04f, 0.05f, 1f);
        camera.fieldOfView = 38f;
        camera.allowHDR = true;

        var lightObject = new GameObject("ReviewLight");
        var light = lightObject.AddComponent<Light>();
        light.type = LightType.Directional;
        light.intensity = 1.2f;
        light.transform.rotation = Quaternion.Euler(40f, -35f, 0f);

        var root = spawn();
        var systems = root.GetComponentsInChildren<ParticleSystem>(true);
        for (var index = 0; index < systems.Length; index++)
        {
            systems[index].useAutoRandomSeed = false;
            systems[index].randomSeed = (uint)(1000 + index);
            systems[index].Stop(false, ParticleSystemStopBehavior.StopEmittingAndClear);
            systems[index].Play(false);
        }
        var output = Path.Combine(outputRoot, caseName);
        Directory.CreateDirectory(output);
        var target = new RenderTexture(Size, Size, 24, RenderTextureFormat.ARGB32);
        camera.targetTexture = target;
        var texture = new Texture2D(Size, Size, TextureFormat.RGB24, false);

        try
        {
            for (var frame = 0; frame < FrameCount; frame++)
            {
                foreach (var system in systems)
                    system.Simulate(1f / Fps, false, false, true);
                camera.Render();
                RenderTexture.active = target;
                texture.ReadPixels(new Rect(0, 0, Size, Size), 0, 0);
                texture.Apply(false);
                File.WriteAllBytes(
                    Path.Combine(output, $"{frame:0000}.png"), texture.EncodeToPNG());
            }
        }
        finally
        {
            RenderTexture.active = null;
            camera.targetTexture = null;
            UnityEngine.Object.DestroyImmediate(texture);
            UnityEngine.Object.DestroyImmediate(target);
            UnityEngine.Object.DestroyImmediate(root);
            UnityEngine.Object.DestroyImmediate(cameraObject);
            UnityEngine.Object.DestroyImmediate(lightObject);
        }
    }
}
