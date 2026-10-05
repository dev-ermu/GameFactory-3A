# VFX测试

从仓库根目录运行离线适配器套件：

```bash
python -m unittest test.vfx_test.test_vfx_adapters -v
```

Unreal集成脚本会从`AAAGF_VFX_TEST_CONTENT_ROOT`路径下获取特定项目的预览资源。需将其设置为包含`Maps`、`Preview`、`Review`和`Sequences`文件夹的Unreal内容目录，例如`/Game/MyProject/VFXTests`。文件系统输出路径则由现有的`AAAGF_VFX_REVIEW_ROOT`、`AAAGF_PUNCH_FIRE_OUTPUT_DIR`和`AAAGF_VFX_PLAYER_PATH`变量分别指定。
