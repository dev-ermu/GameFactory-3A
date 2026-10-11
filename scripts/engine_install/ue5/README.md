# Unreal Scripts

These launchers are thin wrappers around the public `UEClient(api_version="v1")`
API.

This directory intentionally contains only Windows/Linux launchers and this
README. Python implementation lives in `engine_adapters/ue5/cli.py`:

```text
scripts/engine_install/ue5/*.cmd or *.sh -> engine_adapters.ue5.cli -> UEClient
```

```powershell
scripts\engine_install\ue5\create_project.cmd `
  --ue-root D:\UE\UE_5.4 `
  --project-path D:\Projects\GeneratedGame

scripts\engine_install\ue5\import_asset.cmd `
  --ue-root D:\UE\UE_5.4 `
  --project D:\Projects\GeneratedGame\GeneratedGame.uproject `
  --game-id gameA_cyberpunk_shooter `
  --task-id cyberpunk_sword_001 `
  --type prop `
  --artifact-key glb_path

scripts\engine_install\ue5\run.cmd `
  --ue-root D:\UE\UE_5.4 `
  --project D:\Projects\GeneratedGame\GeneratedGame.uproject `
  --map /Game/Maps/Arena
```

Asset import accepts repository task identities, not arbitrary source paths.
Platform gateway and browser serving are not started by these scripts.
