# world_mirror_utils — 第三方引入的HunyuanWorld-Mirror

这是[HunyuanWorld-Mirror](https://github.com/Tencent-Hunyuan/HunyuanWorld-Mirror)的网络定义文件，HunyuanWorld-Mirror是Hunyuan WorldPlay实现3D重建所依赖的前馈几何模型。其权重文件可在HuggingFace平台的`tencent/HunyuanWorld-Mirror`仓库中下载。

该文件源自`HY-WorldPlay/worldcompass/reward_function/HunyuanWorldMirror/src`。版权所有©2025腾讯，依据《腾讯HunyuanWorld-Mirror社区许可协议》发布；完整协议内容可查看上游仓库。

## 本地修改说明

1. **导入前缀重写**：将`reward_function.HunyuanWorldMirror.src.*`替换为`models.gen_3d_scene.world_mirror_utils.src.*`，这样该模块就能作为普通的子包使用，无需额外调整`sys.path`。

2. **移除高斯溅射相关分支**。网格生成功能仅读取深度、点云图、法线和相机相关数据。随之被移除的文件包括：`models/rasterization.py`、`utils/frustum.py`、`utils/sh_utils.py`、`utils/act_gs.py`，以及`models/worldmirror.py`中的`gs_head`/`gs_renderer`构建与前向传播逻辑，还有无人调用的`prepare_contexts`。这一操作也同时去除了对`gsplat`的依赖。

   已发布的检查点文件中仍包含67个以`gs_`开头的张量，因此`WorldMirrorModel`在加载状态字典时会采用非严格模式，并会校验所有被跳过的键是否都以`gs_`开头。`WorldMirror.__init__`仍然接受`enable_gs`参数，因为`config.json`中设置了该选项，但实际并不会生效。

3. **删除无用模块以减小依赖规模**：删除了整个`src/utils/`目录下的文件（`geometry.py`、`video_utils.py`、`warnings.py`——这些文件从未被其他模块引用），以及`render_utils.py`（依赖moviepy）、`color_map.py`（依赖colorspacious和jaxtyping）、`build_pycolmap_recon.py`（依赖pycolmap）、`gs_effects.py`、`cropping.py`、`save_utils.py`、`inference_utils.py`和`visual_util.py`。

   `visual_util.py`中包含上游版本的深度转网格代码（`create_image_mesh`、`convert_predictions_to_glb_scene`）。这段代码特意未被引入本项目——取而代之的是`operators/gen_3d_scene/funcs/points_to_mesh.py`，因为上游版本的代码正是导致该文件头部所描述的网格孔洞问题的根源。

## 从上游仓库更新方法

```bash
SRC=/path/to/HunyuanWorldMirror
cp -r "$SRC/src" world_mirror_utils/
find world_mirror_utils -name '*.py' -print0 | xargs -0 perl -pi -e \
  's/reward_function\.HunyuanWorldMirror\.src\./models.gen_3d_scene.world_mirror_utils.src./g'
```

之后需重新应用上述第2点和第3点的修改。
