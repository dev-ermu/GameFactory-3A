# O-Voxel：一种原生3D表示方式

**O-Voxel**是一种稀疏的、基于体素的原生3D表示方式，专为高质量的3D生成与重建而设计。与传统依赖场（如占用场、有符号距离场）的方法不同，O-Voxel采用**灵活双网格**机制，能够稳健地表示具有任意拓扑结构的表面（包括非流形表面和开放表面），以及**体积表面属性**，例如基于物理的渲染（PBR）材质属性。

该库提供了高效的实现方案，可实现网格与O-Voxel之间的即时双向转换，同时配备了用于稀疏体素压缩、序列化及渲染的工具。

![概览](assets/overview.webp)

## 主要特性

- **🧱 灵活双网格**：一种几何表示方式，通过求解改进的二次误差函数（QEF）来精准捕捉尖锐特征与开放边界，无需依赖闭合网格。
- **🎨 体积PBR属性**：原生支持与稀疏体素网格对齐的基于物理的渲染属性（基础颜色、金属度、粗糙度、不透明度）。
- **⚡ 即时双向转换**：无需进行耗时的有符号距离场计算、泛洪填充或迭代优化，即可快速完成`网格 <-> O-Voxel`转换。
- **💾 高效压缩**：支持自定义的`.vxz`格式，利用Z序/希尔伯特曲线编码技术紧凑存储稀疏体素结构。
- **🛠️ 可直接用于生产**：提供相关工具，可将转换后的资产直接导出为带有UV展开和纹理烘焙功能的`.glb`格式。

## 安装

```bash
git clone -b main https://github.com/microsoft/TRELLIS.2.git --recursive
pip install TRELLIS.2/o_voxel --no-build-isolation
```

## 快速入门

> 更多详细用法可参考[示例](examples)目录。

### 1. 将网格转换为O-Voxel [[链接]](examples/mesh2ovox.py)
将标准3D网格（含纹理）转换为O-Voxel表示形式。

```python
asset = trimesh.load("path/to/mesh.glb")

# 1. 几何体素化（灵活双网格）
# 返回：已占用索引、双顶点（QEF解）以及边交点信息
mesh = asset.to_mesh()
vertices = torch.from_numpy(mesh.vertices).float()
faces = torch.from_numpy(mesh.faces).long()
voxel_indices, dual_vertices, intersected = o_voxel.convert.mesh_to_flexible_dual_grid(
    vertices, faces,
    grid_size=RES,                              # 分辨率
    aabb=[[-0.5,-0.5,-0.5],[0.5,0.5,0.5]],      # 轴对齐包围盒
    face_weight=1.0,                            # QEF中的面项权重
    boundary_weight=0.2,                         # QEF中的边界项权重
    regularization_weight=1e-2,                 # QEF中的正则化项权重
    timing=True
)
## 排序以确保几何体素化与材质体素化保持一致
vid = o_voxel.serialize.encode_seq(voxel_indices)
mapping = torch.argsort(vid)
voxel_indices = voxel_indices[mapping]
dual_vertices = dual_vertices[mapping]
intersected = intersected[mapping]
```# 2. 材质体素化（体积属性）
# 返回值：包含‘base_color’、‘metallic’、‘roughness’等键的字典。
voxel_indices_mat, attributes = o_voxel.convert.textured_mesh_to_volumetric_attr(
    asset,
    grid_size=RES,
    aabb=[[-0.5,-0.5,-0.5],[0.5,0.5,0.5]],
    timing=True
)
## 进行排序以确保几何体与材质体素化结果对齐
vid_mat = o_voxel.serialize.encode_seq(voxel_indices_mat)
mapping_mat = torch.argsort(vid_mat)
attributes = {k: v[mapping_mat] for k, v in attributes.items()}

# 保存为压缩的.vxz格式
## 数据打包
dual_vertices = dual_vertices * RES - voxel_indices
dual_vertices = (torch.clamp(dual_vertices, 0, 1) * 255).type(torch.uint8)
intersected = (intersected[:, 0:1] + 2 * intersected[:, 1:2] + 4 * intersected[:, 2:3]).type(torch.uint8)
attributes['dual_vertices'] = dual_vertices
attributes['intersected'] = intersected
o_voxel.io.write("ovoxel_helmet.vxz", voxel_indices, attributes)
```

### 2. 从O-Voxel恢复网格 [[链接]](examples/ovox2mesh.py)
根据稀疏体素数据重建表面网格。

```python
# 加载数据
coords, data = o_voxel.io.read("path/to/ovoxel.vxz")
dual_vertices = data['dual_vertices']
intersected = data['intersected']
base_color = data['base_color']
## ……为简洁起见，省略其他属性

# 解包
dual_vertices = dual_vertices / 255
intersected = torch.cat([
    intersected % 2,
    intersected // 2 % 2,
    intersected // 4 % 2,
], dim=-1).bool()

# 提取网格
# O-Voxel通过连接双顶点来形成四边形，也可根据几何特征对其进行拆分。
rec_verts, rec_faces = o_voxel.convert.flexible_dual_grid_to_mesh(
    coords.cuda(), 
    dual_vertices.cuda(), 
    intersected.cuda(), 
    split_weight=None, # 若设为None则根据最小角度自动拆分
    grid_size=RES,
    aabb=[[-0.5,-0.5,-0.5],[0.5,0.5,0.5]],
)
```

### 3. 导出为GLB格式 [[链接]](examples/ovox2glb.py)
为了在标准3D查看器中可视化，可以对模型进行清理、UV展开，并将体积属性烘焙到纹理中。

```python
# 假设你已经获得了重建后的顶点/面以及体积属性
mesh = o_voxel.postprocess.to_glb(
    vertices=rec_verts,
    faces=rec_faces,
    attr_volume=attr_tensor, # 合并后的属性数据
    coords=coords,
    attr_layout={'base_color': slice(0,3), 'metallic': slice(3,4), ...}, 
    grid_size=RES,
    aabb=[[-0.5,-0.5,-0.5],[0.5,0.5,0.5]],
    decimation_target=100000,
    texture_size=2048,
    verbose=True,
)
mesh.export("rec_helmet.glb")
```

### 4. 体素渲染 [[链接]](examples/render_ovox.py)
直接渲染体素表示形式。

```python
# 加载数据
coords, data = o_voxel.io.read("ovoxel_helmet.vxz")
position = (coords / RES - 0.5).cuda()
base_color = (data['base_color'] / 255).cuda()
```# 渲染
renderer = o_voxel.rasterize.VoxelRenderer(
    rendering_options={"resolution": 512, "ssaa": 2}
)
output = renderer.render(
    position=position,          # 体素中心点
    attrs=base_color,           # 颜色/透明度等属性
    voxel_size=1.0/RES,
    extrinsics=extr,
    intrinsics=intr
)
# output.attr 包含渲染后的图像（通道数, 高度, 宽度）
```

## API 概览

### `o_voxel.convert`
用于网格与O-体素之间转换的核心算法。
*   `mesh_to_flexible_dual_grid`：根据网格与体素网格的交点，确定活跃的稀疏体素，并求解QEF以确定体素内的对偶顶点位置。
*   `flexible_dual_grid_to_mesh`：重新连接对偶顶点以形成表面。
*   `textured_mesh_to_volumetric_attr`：将纹理贴图采样到体素空间中。

### `o_voxel.io`
负责稀疏体素文件的输入输出操作。
*   **支持格式**：`.npz`（NumPy格式）、`.ply`（点云格式）、`.vxz`（自定义压缩格式，推荐使用）。
*   **相关函数**：`read()`、`write()`。

### `o_voxel.serialize`
用于空间哈希和排序的工具函数。
*   `encode_seq` / `decode_seq`：将三维坐标转换为/解码为Morton码（Z序）或希尔伯特曲线，以实现高效的存储和处理。

### `o_voxel.rasterize`
*   `VoxelRenderer`：一种轻量级的渲染器，用于在训练过程中可视化稀疏体素。

### `o_voxel.postprocess`
*   `to_glb`：一套完整的流程，涵盖网格清理、重新网格化、UV展开以及纹理烘焙。
