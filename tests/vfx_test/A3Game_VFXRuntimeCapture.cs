using System;
using System.Collections;
using System.IO;
using A3Game.EngineAdapters;
using UnityEngine;

[Serializable]
public sealed class A3GameVFXCaptureCase
{
    public string name;
    public string category;
    public GameObject prefab;
    public float scale = 1f;
    public Material particleMaterial;
}

public sealed class A3GameVFXRuntimeCapture : MonoBehaviour
{
    const int Size = 512;
    const int Fps = 30;
    const int FrameCount = 90;

    public Camera reviewCamera;
    public A3GameVFXCaptureCase[] cases;

    IEnumerator Start()
    {
        var outputRoot = Environment.GetEnvironmentVariable("AAAGF_VFX_REVIEW_ROOT");
        if (string.IsNullOrWhiteSpace(outputRoot))
        {
            StartInteractiveReview();
            yield break;
        }

        QualitySettings.vSyncCount = 0;
        Application.runInBackground = true;
        Application.targetFrameRate = Fps;
        Time.captureFramerate = Fps;
        Screen.SetResolution(Size, Size, false);
        yield return null;
        yield return null;

        foreach (var captureCase in cases)
            yield return CaptureCase(captureCase, outputRoot);

        Debug.Log("[AAAGF_VFX_PLAYER] PASS: runtime candidates captured");
        Application.Quit(0);
    }

    IEnumerator CaptureCase(A3GameVFXCaptureCase captureCase, string outputRoot)
    {
        reviewCamera.transform.position = captureCase.category == "smoke"
            ? new Vector3(0f, 1.5f, -4.5f)
            : new Vector3(0f, 1.2f, -4.5f);
        reviewCamera.transform.LookAt(new Vector3(0f, 1.25f, 0f));

        var instance = SpawnCase(captureCase, Vector3.zero);
        SeedAndPlay(instance);
        var systems = instance.GetComponentsInChildren<ParticleSystem>(true);
        Debug.Log(
            $"[AAAGF_VFX_PLAYER] {captureCase.name}: systems={systems.Length}, " +
            $"renderers={instance.GetComponentsInChildren<ParticleSystemRenderer>(true).Length}");

        var output = Path.Combine(outputRoot, captureCase.name);
        Directory.CreateDirectory(output);
        var target = new RenderTexture(Size, Size, 24, RenderTextureFormat.ARGB32);
        reviewCamera.targetTexture = target;
        for (var frame = 0; frame < FrameCount; frame++)
        {
            yield return new WaitForEndOfFrame();
            if (frame == 0 || frame == FrameCount / 2 || frame == FrameCount - 1)
            {
                var particles = 0;
                foreach (var system in systems)
                    particles += system.particleCount;
                Debug.Log(
                    $"[AAAGF_VFX_PLAYER] {captureCase.name} frame={frame} " +
                    $"particles={particles}");
            }
            reviewCamera.Render();
            RenderTexture.active = target;
            var texture = new Texture2D(Size, Size, TextureFormat.RGB24, false);
            texture.ReadPixels(new Rect(0, 0, Size, Size), 0, 0);
            texture.Apply(false);
            File.WriteAllBytes(
                Path.Combine(output, $"{frame:0000}.png"), texture.EncodeToPNG());
            Destroy(texture);
        }

        RenderTexture.active = null;
        reviewCamera.targetTexture = null;
        target.Release();
        Destroy(target);
        Destroy(instance);
        yield return null;
    }

    void StartInteractiveReview()
    {
        reviewCamera.transform.position = new Vector3(0f, 1.45f, -6.5f);
        reviewCamera.transform.LookAt(new Vector3(0f, 1.2f, 0f));
        for (var index = 0; index < cases.Length; index++)
        {
            var x = cases.Length == 1 ? 0f : Mathf.Lerp(-1.25f, 1.25f, index / (cases.Length - 1f));
            var instance = SpawnCase(cases[index], new Vector3(x, 0f, 0f));
            instance.name = "REVIEW_" + cases[index].name;
            SeedAndPlay(instance);
        }
        Debug.Log("[AAAGF_VFX_PLAYER] Interactive review: fire and smoke are playing side by side");
    }

    static GameObject SpawnCase(A3GameVFXCaptureCase captureCase, Vector3 position)
    {
        GameObject instance;
        if (captureCase.particleMaterial != null)
        {
            instance = A3GameVFX.SpawnSmoke(
                position,
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
                    particleMaterial = captureCase.particleMaterial,
                    textureSheetTiles = new Vector2Int(5, 5),
                    forceAlphaBlend = false,
                });
        }
        else
        {
            if (captureCase.prefab == null)
                throw new InvalidOperationException($"Missing prefab for {captureCase.name}");
            instance = Instantiate(captureCase.prefab, position, Quaternion.identity);
            instance.transform.localScale = Vector3.one * captureCase.scale;
        }
        return instance;
    }

    static void SeedAndPlay(GameObject instance)
    {
        foreach (var system in instance.GetComponentsInChildren<ParticleSystem>(true))
        {
            system.useAutoRandomSeed = false;
            system.randomSeed = (uint)(2000 + system.transform.GetSiblingIndex());
            system.Play(false);
        }
    }
}
