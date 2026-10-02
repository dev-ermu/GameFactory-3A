using System;
using System.Collections.Generic;
using A3Game.EngineAdapters;
using UnityEditor;
using UnityEngine;

public static class A3GameVFXSmoke
{
    public static void Run()
    {
        var roots = new List<GameObject>();
        GameObject template = null;
        try
        {
            roots.Add(A3GameVFX.SpawnSmoke(
                Vector3.zero, new SmokeOptions { loop = false, duration = 0.1f }));
            roots.Add(A3GameVFX.SpawnFire(
                Vector3.right, new FireOptions { loop = false, duration = 0.1f }));
            roots.Add(A3GameVFX.SpawnExplosion(Vector3.forward));
            roots.Add(A3GameVFX.SpawnDust(Vector3.left));
            roots.Add(A3GameVFX.SpawnInkSmoke(Vector3.zero));
            roots.Add(A3GameVFX.SpawnFrostFire(Vector3.zero));
            roots.Add(A3GameVFX.SpawnCyberFire(Vector3.zero));

            template = new GameObject("VFXTemplate");
            template.AddComponent<ParticleSystem>();
            roots.Add(A3GameVFX.SpawnPrefab(
                template, Vector3.up, Quaternion.identity, Vector3.one));

            foreach (var root in roots)
            {
                if (root == null || root.GetComponentsInChildren<ParticleSystem>().Length == 0)
                    throw new InvalidOperationException("VFX function returned no ParticleSystem");
                A3GameVFX.Stop(root, true);
            }
            Debug.Log("[AAAGF_VFX_TEST] PASS: Unity VFX functions executed");
        }
        finally
        {
            foreach (var root in roots)
                if (root != null) UnityEngine.Object.DestroyImmediate(root);
            if (template != null) UnityEngine.Object.DestroyImmediate(template);
        }
    }
}
