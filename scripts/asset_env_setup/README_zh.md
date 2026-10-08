# 资产环境配置

请使用与对应资产任务匹配的目录。每个任务的入口即为标准的安装路径。该目录根目录下的`cloud_api_install.sh`是各任务专属云API封装器共用的实现代码；除非没有适用的任务专属封装器，否则请勿在新的代理工作流中调用它。

| 资产任务 | 安装路径 | 用途 |
|---|---|---|
| 图像 / T-pose | `image/cloud_api_install.sh`、`image/qwen_image_install.sh` | 云端Seedream封装器，以及本地Qwen图像编辑工具（集成RMBG和Depth Anything功能）。 |
| 3D场景 | `3d_scene/` | 预留给场景生成相关的配置；目前无需全仓库级别的安装程序。 |
| 动作生成 | `gen_motion/install.sh`、`gen_motion/runtime_env.sh` | 固定版本的Puppeteer、MoMask、动作重定向相关环境，以及选定的模型权重。 |
| 音频 | `audio/cloud_api_install.sh` | 云端音频后端共用的HTTP依赖项。 |

