# Unreal脚本

这些启动器只是对公开的`UEClient(api_version="v1")` API的简易封装。

该目录中特意仅包含Windows/Linux平台的启动器以及本README文件。Python实现代码位于`engine_adapters/ue5/cli.py`中：

```text
scripts/ue/*.cmd或*.sh -> engine_adapters.ue5.cli -> UEClient
```

```powershell
scripts\ue\create_project.cmd `
  --ue-root D:\UE\UE_5.4 `
  --project-path D:\Projects\GeneratedGame

scripts\ue\import_asset.cmd `
  --ue-root D:\UE\UE_5.4 `
  --project D:\Projects\GeneratedGame\GeneratedGame.uproject `
  --game-id gameA_cyberpunk_shooter `
  --task-id cyberpunk_sword_001 `
  --type prop `
  --artifact-key glb_path

scripts\ue\run.cmd `
  --ue-root D:\UE\UE_5.4 `
  --project D:\Projects\GeneratedGame\GeneratedGame.uproject `
  --map /Game/Maps/Arena
```

资产导入功能接受的是仓库任务标识，而非任意源路径。平台网关和浏览器服务并非由这些脚本启动。
