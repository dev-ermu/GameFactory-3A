"""
pipeline/common/config.py

唯一配置模块的 **Pipeline 侧视图**。

实现放在 `<REPO_PATH>/global_config.py`——一个顶层模块，这样 `models/` 无需 import
`pipeline/` 也能用它（`model_require.md` R1.1）。本文件存在的唯一目的是让 Pipeline
代码有一个明确的 import 入口：

    from pipeline.common import config
    config.require_cloud_or_exit(("tripo",), context="3D-object backend")

这里全部是再导出；要加行为请改 `global_config`，不要在此重复实现。
"""
from __future__ import annotations

from global_config import (  # noqa: F401
    BACKEND_SWITCHES,
    ENV_EXAMPLE_FILE,
    ENV_FILE,
    PROVIDERS,
    REPO_ROOT,
    ConfigError,
    Provider,
    api_cache_dir,
    cloud_env_template,
    describe,
    get,
    is_set,
    loaded_values,
    load,
    output_root,
    parse_env_file,
    require,
    require_cloud,
    require_cloud_or_exit,
)

__all__ = [
    "BACKEND_SWITCHES",
    "ConfigError",
    "ENV_EXAMPLE_FILE",
    "ENV_FILE",
    "PROVIDERS",
    "Provider",
    "REPO_ROOT",
    "api_cache_dir",
    "cloud_env_template",
    "describe",
    "get",
    "is_set",
    "load",
    "loaded_values",
    "output_root",
    "parse_env_file",
    "require",
    "require_cloud",
    "require_cloud_or_exit",
]
