"""
pipeline/common/config.py

唯一配置模块的 **Pipeline 侧视图**。

实现放在 `<REPO_PATH>/config.py`——一个顶层模块，这样 `models/` 无需 import
`pipeline/` 也能用它（`model_require.md` R1.1）。本文件只是 re-export，让 Pipeline 代码
有一个明确的 import 入口。

**取配置一律读 `settings` 对象**，不要再按环境变量名包一层：

    from pipeline.common import config
    config.settings.tripo_api_base
    config.require_cloud_or_exit(("tripo",), context="3D-object backend")

本模块**不新增任何取值函数**：需要新配置项就加到 `config.Settings` 的字段上，
那样 `.env`、校验、诊断会一起生效。
"""

from config import (  # noqa: F401
    REPO_ROOT,
    ConfigError,
    Settings,
    api_cache_dir,
    require_cloud_or_exit,
    settings,
)

__all__ = [
    "REPO_ROOT",
    "ConfigError",
    "Settings",
    "api_cache_dir",
    "require_cloud_or_exit",
    "settings",
]
