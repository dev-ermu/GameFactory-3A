# 第三方

3AGameFactory依赖但不提供供应商的**外部克隆存储库**的登录区域，例如：

- 几何图形和资源库例如`trimesh`。
- 与引擎相关的材质、着色器或资源包存储库。
- 从源代码检出的第三方生成运行时

将每个依赖项克隆到自己的子目录中：

```text
third_party/
├── trimesh/
├── <engine-material-repo>/
└── <runtime-repo>/
```

默认情况下，此文件夹为**git忽略**，此README除外。每个clone保留自己的上游licence，在生成内容之前检查这些条款内容。
