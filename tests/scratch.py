"""
tests/scratch.py — 测试期临时数据目录的统一入口。

所有单元测试的临时目录都建在 `settings.test_data_dir`（默认 ``<repo>/tests/data``）
之下，而不是系统临时目录。这样做的好处：

1. **便于清理**——跑完测试只需删掉一个目录，不会残留在 ``%TEMP%`` 里；
2. **便于排查**——失败时留下的现场仍在仓库内，能直接查看；
3. **统一隔离**——不同机器、CI 上位置一致，不会因为系统临时目录的权限或
   路径长度限制（Windows 上 ``%TEMP%`` 路径很深）而失败。

本模块**刻意保持轻量**：只依赖标准库与 `config`。
不要在这里 import `tests.harness`——它会连带拉入 numpy 与 Pillow，
而只想建个临时目录的测试（如安装器测试）不该为此付出代价。
"""

import shutil
import tempfile
from pathlib import Path

from config import settings

__all__ = ["test_data_dir", "scratch_dir", "temp_dir", "clear_scratch"]


def test_data_dir() -> Path:
    """返回测试临时数据根目录，确保它存在。

    Returns:
        ``settings.test_data_dir`` 指向的目录（默认 ``<repo>/tests/data``）。

    Note:
        该配置是**相对路径**，按项目约定所有测试都必须从仓库根目录运行。
    """
    path = Path(settings.test_data_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def scratch_dir(prefix: str) -> str:
    """在测试数据目录下创建一个临时目录，返回其路径字符串。

    与 :func:`temp_dir` 的区别：本函数**不负责清理**，需要调用方自己
    ``shutil.rmtree``——适合那些要跨函数边界保留目录的测试。

    Args:
        prefix: 目录名前缀，便于识别来源。

    Returns:
        临时目录的绝对路径字符串。
    """
    return tempfile.mkdtemp(prefix=prefix, dir=test_data_dir())


def temp_dir(prefix: str) -> tempfile.TemporaryDirectory:
    """在测试数据目录下创建一个**自动清理**的临时目录。

    直接替换裸用的 ``tempfile.TemporaryDirectory()``：

        with temp_dir("godot-adapter-test-") as directory:
            ...

    Args:
        prefix: 目录名前缀，便于识别来源。

    Returns:
        ``tempfile.TemporaryDirectory`` 对象；``.name`` 是目录路径。
    """
    return tempfile.TemporaryDirectory(prefix=prefix, dir=test_data_dir())


def clear_scratch() -> None:
    """清空测试数据目录下的全部内容。

    供「跑完一整轮测试后统一清理」使用，例如::

        python -c "from tests.scratch import clear_scratch; clear_scratch()"
    """
    root = test_data_dir()
    for entry in root.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)
