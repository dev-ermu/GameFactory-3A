"""
Blender playable runtime: a live `bpy` session driven by JSON commands.

The rest of `engine_adapters/blender/` is batch work: a file goes in, a
conditioned file comes out, the process exits. This is the other mode — one
long-lived process holding a scene that commands mutate while it runs, so a
world can be walked around before it is committed to a game engine.

`serve.py` is the entry point; everything else is importable on its own.

Blender可播放运行时：一种由JSON命令驱动的实时`bpy`会话。

`engine_adapters/blender/`目录下的其余代码属于批处理模式：输入一个文件，输出一个经过处理后的文件，随后进程结束。而这种模式则不同——它是一个长期运行的进程，会持续维护一个场景，在运行过程中该场景的命令会被动态修改，如此便能在将场景导入游戏引擎之前先进行预览和交互。

`serve.py`是程序的入口；其余模块均可独立导入使用。

"""
