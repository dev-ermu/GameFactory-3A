# 组合示例

同样的三个模型，各构建两次：一次仅使用基础几何体，另一次则加入生成的组件进行组合。将它们并排展示，因为两种构建方式的差异直观可见，无需过多描述。

每个视频都记录了对应的参数——零件数量、三角形面数、纹理数量，以及与规格要求相比的高度差异。

## 仅使用基础几何体

所有零件均为立方体、圆柱体、球体或车削轮廓，通过`attach`方式连接，而非依赖绝对坐标定位。构建仅需几秒钟，无需GPU支持，也无需API密钥，且能精准还原关键尺寸：如轨道的槽距、轴距以及桶体直径等。

<table>
  <tr>
    <td width="33%">
      <video src="https://github.com/user-attachments/assets/a8e8be8f-3b5b-453c-a3de-fe2dc4dfaad4" width="100%" controls muted playsinline></video>
    </td>
    <td width="33%">
      <video src="https://github.com/user-attachments/assets/d6dc4f29-c233-4a3b-b873-055c77070e6b" width="100%" controls muted playsinline></video>
    </td>
    <td width="33%">
      <video src="https://github.com/user-attachments/assets/f258e7d7-81d9-4fdc-a1d0-81ae70cbd484" width="100%" controls muted playsinline></video>
    </td>
  </tr>
  <tr>
    <td align="center"><sub>女性骑士 · 89个零件 · 12,420个三角形面 · 无纹理</sub></td>
    <td align="center"><sub>突击步枪 · 63个零件 · 4,040个三角形面 · 无纹理</sub></td>
    <td align="center"><sub>赛车 · 64个零件 · 7,224个三角形面 · 无纹理</sub></td>
  </tr>
</table>

## 使用生成的组件

效果更为精细。部分零件是通过图像转3D模型生成的网格，同样依据规格要求放置：以主体为参照进行测量，通过单一缩放因子保持生成时的比例，并设定特定的朝向。这种处理方式能实现基础几何体无法达到的表面细节——三角形面数可达前者的3到8倍，同时还需调用模型数据。

<table>
  <tr>
    <td width="33%">
      <video src="https://github.com/user-attachments/assets/ad475ab9-f102-4353-bc99-64f5f532995a" width="100%" controls muted playsinline></video>
    </td>
    <td width="33%">
      <video src="https://github.com/user-attachments/assets/e4b525b8-7d54-42ed-b7db-c1dac5d53d62" width="100%" controls muted playsinline></video>
    </td>
    <td width="33%">
      <video src="https://github.com/user-attachments/assets/47237e48-9407-4c76-9d84-05fee356cb2d" width="100%" controls muted playsinline></video>
    </td>
  </tr>
  <tr>
    <td align="center"><sub>适配生成T型姿势身体的盔甲与靴子 · 12个零件 · 32,364个三角形面 · 12种纹理</sub></td>
    <td align="center"><sub>在指定机身上安装的生成握把与枪托 · 58个零件 · 12,927个三角形面</sub></td>
    <td align="center"><sub>安装在指定底盘上的生成外壳 · 53个零件 · 15,672个三角形面</sub></td>
  </tr>
</table>

## 角色与服装动画服装会借助肩部、肘部、腕部和下半身标记点来贴合现有角色，同时保留其材质和UV信息。蒙皮权重会将贴合后的衣物与角色的骨骼绑定在一起，随后通过行走动画来驱动角色与衣物的整体运动。

<table>
  <tr>
    <td width="50%" align="center"><sub>组合方案1 · 源素材</sub></td>
    <td width="50%" align="center"><sub>组合方案2 · 源素材</sub></td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img src="https://github.com/user-attachments/assets/f4000dde-0043-41ae-af5f-663c0bb9e14f" width="100%" alt="角色与服装组合方案1的源素材" />
    </td>
    <td width="50%" valign="top">
      <img src="https://github.com/user-attachments/assets/a8791e14-df61-42a3-8a9e-42ce1df21085" width="100%" alt="角色与服装组合方案2的源素材" />
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <video src="https://github.com/user-attachments/assets/6a9a2f2e-bdee-4d7d-bcf3-2600f04abebc" width="100%" controls muted playsinline></video>
    </td>
    <td width="50%" valign="top">
      <video src="https://github.com/user-attachments/assets/586052f1-f4fb-4f85-a9fe-29503188aa0c" width="100%" controls muted playsinline></video>
    </td>
  </tr>
  <tr>
    <td align="center"><sub>行走动画</sub></td>
    <td align="center"><sub>原地动画</sub></td>
  </tr>
</table>

## 如何选择二者

对于步枪和汽车而言，基础版本已经具备可用性，生成的模型只是最终的优化版本。这两种情况中每个部件都作为独立的glTF节点存在，因此车轮仍能转动，弹匣也能正常更换。

骑士模型则属于不适合使用组合功能的案例。为了做出大致符合预期的形象，团队花费了约12小时进行了**8次人工调整**，其中的缺陷属于测量误差而非建模问题——每个中间模型都构建得十分规整，且在渲染前就通过了各项检查：
- 导入的肩甲被识别为*左侧*肩部部件。由于两个肩部使用了同一网格，导致右侧肩甲的护片会向内覆盖在肋骨上。虽然“左右对称性检查”判定两者位置对称，但实际并非如此。
- 名为`greave_pair.glb`的网格并非护胫，而是一整只及膝靴。将其放置在`shin`（小腿）插槽中时，靴底会离地面81毫米，而角色本身的脚则裸露在下方。
- 脚部高度标记点返回的是搜索窗口的上限位置而非实际脚部位置，因此据此制作的靴子会出现长度大于宽度的现象。

对于车辆、武器、建筑这类刚性装配体，建议采用规格化建模方式——这类模型的部件必须保持可分离性且尺寸精确。应直接生成完整的模型。
