# 面向机械管线开发的Blender工具

本文档说明了`engine_adapters/blender/`运行前所需的条件、每项依赖的必要性，以及缺少这些依赖时会出现的错误特征。配套脚本`blender_install.sh`可自动完成所有安装步骤；本文档则用于确定需要安装的内容以及解读错误信息。

整个安装过程无需使用`sudo`权限：仅需一个可移植的Blender压缩包，以及一个包含主机系统缺失的共享库的Conda环境前缀。由于没有任何内容会被安装到系统层面，因此即便安装出错，也只需执行`rm -rf`命令即可恢复，不会损坏整机。

本方案已在Ubuntu 22.04.4系统（内核5.15，glibc 2.35）上针对**Blender 4.5.12 LTS版本**验证通过，且无需root权限。glibc是主机必须满足的唯一要求，Conda环境无法弥补这一缺口：可移植版Blender需要较新版本的glibc；若在旧版发行版上运行，启动时会出现`GLIBC_2.xx not found`错误，而非提示缺少`.so`文件。

## 两种使用方式

有两种解释器可以运行相关代码，多数场景下两者并无区别——但游戏管线在某处对解释器有特定要求。

| | Blender应用程序 | `pip install bpy` 轮子包 |
|---|---|---|
| `import_generated/`、`render_preview.py` | 支持 | 支持 |
| `game/`目录下的无头模式：模拟、烘焙、渲染 | 支持 | 未测试 |
| `game/ --play`（实时窗口模式） | **必须，不可或缺** | 不支持 |

`--play`参数会打开真实窗口并运行对应的模态操作符。`interactive.py`脚本会检查`bpy.app.background`变量，若不满足要求则会直接报错而非降级运行：我们特意没有提供离屏运行路径，因为无法交互的“交互模式”不过是披着交互外衣的慢速无头运行罢了。因此，若你想使用实时窗口功能，必须安装Blender应用程序；轮子包仅能满足导入需求。

## 安装步骤

空间占用是执行步骤0的原因：整个过程大约需要**2.5 GB**存储空间（361 MB的压缩包、1.2 GB的解压文件、0.9 GB的Conda环境前缀），常见的安装失败原因是用户主目录或容器根目录的可用空间不足几百MB。

```bash
# 0. 选择一个有足够空间的文件系统。后续所有操作都在此目录下执行。
export AAAGF_TOOLS_DIR=/path/with/space/.aaagf
df -h "$(dirname "$AAAGF_TOOLS_DIR")"

# 1. 下载可移植的Blender压缩包。无需安装程序，无需root权限。
mkdir -p "$AAAGF_TOOLS_DIR"
cd "$AAAGF_TOOLS_DIR"
curl -fL -O https://download.blender.org/release/Blender4.5/blender-4.5.12-linux-x64.tar.xz
tar -xf blender-4.5.12-linux-x64.tar.xz

# 2. 将Blender依赖的共享库安装到Conda环境前缀中。
conda create -y -p "$AAAGF_TOOLS_DIR/envs/bl" -c conda-forge \
    xorg-libxi xorg-libxxf86vm xorg-libxfixes xorg-libxrender xorg-libxext \
    xorg-libx11 xorg-libsm xorg-libice libxkbcommon mesalib libglu ffmpeg

# 3. 仅当你想在没有物理显示器的情况下使用--play功能时才执行此步。
conda create -y -p "$AAAGF_TOOLS_DIR/envs/xvfb" -c conda-forge xorg-xvfb-server
```

步骤2中的12个软件包需要**一次性通过一条命令安装**，切勿逐个安装，否则会触发错误提示。具体原因可参考下表的第一行说明。

随后需要加载一个环境脚本，因为其中三个环境变量很容易被人遗忘，且缺失时不会给出明确提示：```bash
export BLENDER_HOME="$AAAGF_TOOLS_DIR/blender-4.5.12-linux-x64"
export BLENDER="$BLENDER_HOME/blender"
export AAAGF_BLENDER="$BLENDER"                      # 启动器读取的路径
export LD_LIBRARY_PATH="$AAAGF_TOOLS_DIR/envs/bl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export XDG_CACHE_HOME="$AAAGF_TOOLS_DIR/cache"       # Cycles内核缓存路径
export TMPDIR="$AAAGF_TOOLS_DIR/tmp"
mkdir -p "$XDG_CACHE_HOME" "$TMPDIR"
```

## 故障现象及解决方法

| 症状 | 原因 | 修复方法 |
|---|---|---|
| `error while loading shared libraries: libXrender.so.1` | 该压缩包依赖的X11/GL库在宿主机上不存在。动态链接器只会提示第一个缺失的库，修复后会暴露下一个缺失项——一次只能发现一个，共七个 | 将`LD_LIBRARY_PATH`设置为Conda环境的路径。`ldd "$BLENDER" \| grep 'not found'`可一次性列出全部七个缺失库 |
| 程序能运行，但每次渲染都要重新编译Cycles内核 | `$XDG_CACHE_HOME`所在的分区已满，缓存写入操作**静默失败** | 将`XDG_CACHE_HOME`指向有足够空间的分区 |
| `--play`参数会导致程序立即退出，或提示“需要窗口” | 程序以`--background`模式启动，或当前环境没有设置`$DISPLAY`变量 | 去掉`--background`参数；若需在Xvfb环境下运行，可参考下文说明 |
| 程序显示使用GPU渲染，但实际却在CPU上运算 | 场景中设置了`scene.cycles.device = "GPU"`，但插件偏好设置中并未启用对应的设备，这属于配置错误而非程序报错 | 查看`Recorder._select_device`的输出，它会显示实际启用的设备信息 |
| 不同用户运行同一场景得到的数值结果不一致 | 用户偏好设置和已启用的插件会干扰渲染结果 | 始终使用`--factory-startup`参数启动Blender |

## 无头模式播放

`--play`参数需要窗口环境支持，而容器环境中通常没有显示接口。Xvfb可以提供一个虚拟显示环境：

```bash
"$AAAGF_TOOLS_DIR/envs/xvfb/bin/Xvfb" :99 -screen 0 1280x720x24 &
DISPLAY=:99 "$BLENDER" --factory-startup \
    --python engine_adapters/blender/examples/FPSExample/game.py -- --play
```

这种方式仅用于验证输入路径是否有效，并非真正的游戏运行：通过虚拟帧缓冲区实现的软件GL渲染帧率极低，无法满足正常游戏需求。真正的游戏运行需要真实的显示设备。

## GPU相关说明

Cycles对设备的支持取决于Blender版本和显卡型号，仅仅在列表中显示并不等同于可以正常使用。建议查询Blender自身的检测结果，而非依赖`nvidia-smi`：

```bash
"$BLENDER" -b --factory-startup --python-expr "
import bpy
p = bpy.context.preferences.addons['cycles'].preferences
for backend in ('CUDA','OPTIX','HIP','ONEAPI'):
    try: p.compute_device_type = backend
    except TypeError: print(backend, '未编译进程序'); continue
    d = p.get_devices_for_type(backend)
    print(backend, [x.name for x in d] or '已编译进程序，但无可用设备')"
```

在参考主机（搭载两块H100 PCIe显卡，驱动版本为550.144.03）上运行上述代码后，会发现两张显卡都出现在**CUDA**类别下，而在OPTIX类别下则显示“已编译进程序，但无可用设备”。这并非驱动问题：OptiX需要Hopper架构显卡所不具备的光线追踪核心。通过 `--device CUDA` 参数来调用后端。是否值得这么做取决于每帧的计算量——在 960x540 分辨率、16 次采样的情况下，GPU 的性能仅略优于 CPU；而在 1920x1080 分辨率、128 次采样时，GPU 的性能约为 CPU 的 3 倍。`Recorder.configure_render` 函数会设置 `use_persistent_data` 参数，若不启用该参数，每帧的场景数据上传会成为性能瓶颈，导致 GPU 在处理小尺寸帧时的速度反而比 CPU 更慢。

## 验证步骤

这里采用分层验证的方式，一旦某步失败就能定位到具体出问题的环节：

```bash
"$BLENDER" --version                                    # 第1步：加载器及依赖库检查
"$BLENDER" -b --factory-startup --python-expr "import bpy; print(bpy.app.version_string)"
python -c "import sys; sys.path.insert(0,'.'); import engine_adapters.blender.game"  # 第3步：仅导入模块测试

# 第4步：端到端流程测试，不进行渲染：几秒内即可生成 demo_outputs/events.json 文件
"$BLENDER" -b --factory-startup \
    --python engine_adapters/blender/examples/FPSExample/game.py -- \
    --out-dir /tmp/aaagf_check --no-render
```

第3步甚至无需安装 Blender 即可正常运行——该包经过导入安全处理，因此启动器和 `test/` 目录能在纯 Python 环境下读取其中的常量。

第4步需要 `engine_adapters/blender/examples/` 目录的支持。缺少该目录的话，运行时虽能正常安装，但缺乏可执行的机制。

## 资源为可选项

规范中提及的 3D 资源属于**纯附加内容**。若 `$BLENDER_ASSET_ROOT` 为空或未设置，运行时会针对每个缺失的引用记录一条 `[assets] no model at /Library/...` 日志，随后会回退使用基础几何图形，最终生成的 `events.json` 文件内容完全一致。这一特性是经过实测验证的，而非推测得出：正是这种一致性保证了视觉层的变化不会破坏已生成的游戏逻辑。因此，仅渲染灰色方块的情况并不算故障——这只是没有加载资源的配置而已，其反馈的游戏玩法与正常情况并无区别。
