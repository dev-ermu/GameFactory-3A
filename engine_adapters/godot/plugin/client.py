"""Stable Godot add-on installation operations for GodotClient v1."""

import json
import re
import shutil
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any

from .._internal import (
    GeneratedAssetSourceResolver,
    GodotTransport,
    source_descriptor,
    validate_regular_directory_tree,
)
from ..config import GodotClientConfig
from ..contracts import GodotOperationResult

FRAMEWORK_ROOT = Path(__file__).resolve().parent / "A3GamePlayable"
FRAMEWORK_INSTALL_DIR = "a3game_playable"
FRAMEWORK_AUTOLOAD_NAME = "A3GameRuntime"
FRAMEWORK_AUTOLOAD_PATH = "res://addons/a3game_playable/runtime.gd"
PLUGIN_VALIDATOR_SCRIPT = (
    Path(__file__).resolve().parents[1] / "_scripts" / "validate_plugin.gd"
)
PLUGIN_VALIDATION_SCHEMA = "gamefactory3a.godot.plugin_validation.v1"


def _safe_name(value: str) -> str:
    """把外部传入的加载项名清洗成可安全使用的单层目录名。

    只保留字母、数字、下划线、点和连字符，其余替换成下划线，并去掉首尾的点。
    清洗后为空、或恰好是 ``.`` / ``..`` 时拒绝——那意味着调用方没给出可用名字，
    继续下去会把内容写到项目之外。

    Args:
        value: 候选名字，通常是用户传入的 ``install_dir`` 或源目录名。

    Returns:
        可安全用作单层目录名的字符串。

    Raises:
        ValueError: 清洗后没有剩余有效字符，或结果是一个路径导航片段。
    """
    cleaned = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value or "")).strip("._")
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("Godot add-on name is invalid")
    return cleaned


def _validate_tree(source: Path) -> None:
    """校验目录树里没有符号链接、特殊文件等不安全节点。

    只是 `validate_regular_directory_tree` 的薄封装，用来固定 label 文案，
    让所有报错都以 "Godot add-on source" 开头，便于调用方识别来源。

    Args:
        source: 待校验的加载项目录。

    Raises:
        ValueError: 树里存在符号链接、FIFO、设备文件或逃出根目录的子项。
    """
    validate_regular_directory_tree(source, label="Godot add-on source")


def _addons_directory(project_dir: Path) -> Path:
    """解析 ``<project_dir>/addons``，并确认它确实落在项目根内。

    依次拒绝：项目根不是目录、``addons`` 本身是符号链接、``addons`` 存在但不是目录、
    以及**解析后逃出项目根**的情况。最后一项是路径穿越防护——`Path.resolve()` 会跟随
    符号链接，不校验就可能把内容写到项目之外。

    Args:
        project_dir: Godot 项目根目录。

    Returns:
        ``<project_dir>/addons``（未跟随符号链接的原始路径）。

    Raises:
        NotADirectoryError: 项目根或 addons 路径不是目录。
        ValueError: ``addons`` 是符号链接，或其解析结果逃出项目根。
    """
    root = project_dir.resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Godot project root is not a directory: {root}")
    addons = root / "addons"
    if addons.is_symlink():
        raise ValueError(f"Godot add-ons directory must not be a symlink: {addons}")
    if addons.exists() and not addons.is_dir():
        raise NotADirectoryError(f"Godot add-ons path is not a directory: {addons}")
    resolved = addons.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"Godot add-ons directory escaped the project root: {addons}"
        ) from exc
    return addons


def _install_target(project_dir: Path, install_dir: str) -> Path:
    """解析加载项的安装目标目录，并做与 `_addons_directory` 同级的越界防护。

    目标为 ``<project>/addons/<install_dir>``。拒绝目标本身是符号链接，并确认解析后
    仍在项目根内——``install_dir`` 来自外部，可能含 ``..`` 这类导航片段。

    Args:
        project_dir: Godot 项目根目录。
        install_dir: 安装目录名（单层，不含路径分隔符）。

    Returns:
        未跟随符号链接的安装目标路径。

    Raises:
        ValueError: 目标是符号链接，或其解析结果逃出项目根。
    """
    root = project_dir.resolve(strict=True)
    addons = _addons_directory(root)
    target = addons / install_dir
    if target.is_symlink():
        raise ValueError(f"Godot add-on target must not be a symlink: {target}")
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"Godot add-on target escaped the project root: {target}"
        ) from exc
    return target


def _copied_files(target: Path) -> list[str]:
    """列出目录下所有文件的相对路径（POSIX 分隔符，已排序）。

    用于 ``payload["copied_files"]``，让调用方能核对究竟装进去了哪些文件。

    Args:
        target: 安装完成后的目录。

    Returns:
        形如 ``["runtime.gd", "sub/helper.gd"]`` 的字符串列表。
    """
    return [
        item.relative_to(target).as_posix()
        for item in sorted(target.rglob("*"))
        if item.is_file()
    ]


_SECTION_HEADER_PATTERN = re.compile(
    r"(?m)^[ \t]*\[(?P<name>[^\]\r\n]+)\][ \t]*(?:;[^\r\n]*)?(?:\r?\n|\Z)"
)
_EDITOR_PLUGIN_ENTRY_PATTERN = re.compile(
    r"(?m)^(?P<prefix>[ \t]*enabled[ \t]*=[ \t]*)"
    r"(?P<value>[^\r\n]*)(?P<newline>\r?\n|\Z)"
)
_PACKED_STRING_ARRAY_PATTERN = re.compile(r"PackedStringArray\((?P<arguments>.*?)\)")
_PLUGIN_REQUIRED_KEYS = ("name", "author", "version", "description", "script")


def _split_assignment_comment(value: str) -> tuple[str, str]:
    """把 Godot 配置项的值与**未加引号的**行尾注释分开。

    Godot 的 ``.cfg`` / ``project.godot`` 里，``;`` 和 ``#`` 只有在双引号之外才是注释。
    因此需要逐字符扫描并跟踪引号与转义状态，否则值里含 ``#`` 的合法字符串
    （如 ``"res://a#b.gd"``）会被误截断。

    Args:
        value: ``key=...`` 中等号右侧的原始文本（不含换行）。

    Returns:
        ``(值, 注释)``；没有注释时第二项为空串，值已去掉尾部空白。
    """

    in_string = False
    escaped = False
    for index, character in enumerate(value):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in ";#":
            comment_start = index
            while comment_start > 0 and value[comment_start - 1] in " \t":
                comment_start -= 1
            return value[:comment_start].rstrip(), value[comment_start:]
    return value.rstrip(), ""


def _plugin_entry_script(source: Path) -> tuple[str, Path, dict[str, str]]:
    """校验 ``plugin.cfg`` 元数据，并解析出安全的入口脚本路径。

    要求恰好一个 ``[plugin]`` 段，且 ``name`` / ``author`` / ``version`` /
    ``description`` / ``script`` 五项各出现一次、值都是单个带引号字符串。
    ``script`` 还必须是**不逃逸**的相对路径：拒绝反斜杠、NUL、绝对路径、盘符、
    ``://`` 以及 ``.`` / ``..`` / 空片段，最后再解析一次确认落在加载项源目录内。

    Args:
        source: 加载项源目录（应含 ``plugin.cfg``）。

    Returns:
        ``(入口脚本的相对 POSIX 路径, 入口脚本绝对路径, 元数据字典)``。

    Raises:
        ValueError: 段落或必需项缺失、重复，取值格式不合法，或脚本路径不安全。
    """

    descriptor = source / "plugin.cfg"
    text = descriptor.read_text(encoding="utf-8-sig")
    headers = list(_SECTION_HEADER_PATTERN.finditer(text))
    sections: list[tuple[int, int]] = []
    for index, header in enumerate(headers):
        if header.group("name") != "plugin":
            continue
        sections.append(
            (
                header.end(),
                headers[index + 1].start() if index + 1 < len(headers) else len(text),
            )
        )
    if not sections:
        raise ValueError("Godot add-on plugin.cfg has no [plugin] section")
    if len(sections) != 1:
        raise ValueError("Godot add-on plugin.cfg declares [plugin] more than once")

    body_start, body_end = sections[0]
    metadata: dict[str, str] = {}
    for key in _PLUGIN_REQUIRED_KEYS:
        entry_pattern = re.compile(
            rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=[ \t]*"
            r"(?P<value>[^\r\n]*)(?:\r?\n|\Z)"
        )
        entries = list(entry_pattern.finditer(text, body_start, body_end))
        if not entries:
            raise ValueError(
                f"Godot add-on plugin.cfg [plugin] section has no {key} entry"
            )
        if len(entries) != 1:
            raise ValueError(
                "Godot add-on plugin.cfg [plugin] section declares "
                f"{key} more than once"
            )
        raw_value, _comment = _split_assignment_comment(entries[0].group("value"))
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Godot add-on plugin.cfg {key} must be one quoted string"
            ) from exc
        if not isinstance(value, str):
            raise ValueError(f"Godot add-on plugin.cfg {key} must be a string")
        metadata[key] = value

    if not metadata["name"].strip():
        raise ValueError("Godot add-on plugin.cfg name must be non-empty")
    script_value = metadata["script"]
    if not script_value.strip():
        raise ValueError(
            "Godot add-on plugin.cfg script must be a non-empty string path"
        )
    if (
        "\\" in script_value
        or "\x00" in script_value
        or script_value.startswith("/")
        or re.match(r"^[A-Za-z]:", script_value)
        or "://" in script_value
    ):
        raise ValueError("Godot add-on plugin.cfg script must be a safe relative path")
    raw_parts = script_value.split("/")
    relative = PurePosixPath(script_value)
    if (
        relative.is_absolute()
        or not raw_parts
        or any(part in {"", ".", ".."} for part in raw_parts)
    ):
        raise ValueError(
            "Godot add-on plugin.cfg script must be a non-traversing relative path"
        )

    root = source.resolve(strict=True)
    entry = (root / Path(*raw_parts)).resolve(strict=True)
    try:
        entry.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            "Godot add-on plugin.cfg script escaped the add-on source"
        ) from exc
    if not stat.S_ISREG(entry.lstat().st_mode):
        raise ValueError(
            "Godot add-on plugin.cfg script must resolve to a regular file"
        )
    return relative.as_posix(), entry, metadata


def _validate_plugin_with_godot(
    source: Path,
    install_dir: str,
    entry_script: str,
    config: GodotClientConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """在隔离的临时工程里，用真实 Godot 加载加载项入口脚本。

    把源目录拷进临时工程、生成最小 ``project.godot``，再以
    ``--editor --script validate_plugin.gd`` 让 Godot 自己实例化入口脚本，并读回它
    写出的 JSON 报告。这是**唯一**能确认「脚本真的是可实例化的 EditorPlugin」的手段
    ——纯文本校验做不到这件事。

    Args:
        source: 已暂存的加载项目录。
        install_dir: 加载项在 ``addons/`` 下的目录名。
        entry_script: 期望的入口脚本相对路径。
        config: 客户端配置，用于取 ``editor_timeout``。

    Returns:
        ``(进程摘要, Godot 报告)``；进程摘要含 returncode 与输出尾部各 4000 字符。

    Raises:
        FileNotFoundError: 校验脚本 ``validate_plugin.gd`` 不存在。
        RuntimeError: Godot 没有产出报告，或报告声称成功但退出码非零。
        ValueError: 报告不是合法 JSON、schema 不符，或脚本不是可实例化的 EditorPlugin。
    """

    if not PLUGIN_VALIDATOR_SCRIPT.is_file():
        raise FileNotFoundError(
            f"Godot plugin validator was not found: {PLUGIN_VALIDATOR_SCRIPT}"
        )
    with tempfile.TemporaryDirectory(
        prefix="a3game-godot-plugin-validate-"
    ) as temporary:
        validation_root = Path(temporary)
        staged = validation_root / "addons" / install_dir
        staged.parent.mkdir(parents=True)
        shutil.copytree(source, staged, symlinks=True)
        _validate_tree(staged)
        staged_entry, _staged_entry_file, _staged_metadata = _plugin_entry_script(
            staged
        )
        if staged_entry != entry_script:
            raise ValueError(
                "Godot add-on entry script changed during native validation"
            )
        (validation_root / "project.godot").write_text(
            "; Isolated GameFactory-3A add-on validation project.\n"
            "config_version=5\n\n"
            "[application]\n"
            'config/name="GameFactory-3A Plugin Validation"\n',
            encoding="utf-8",
        )
        report = validation_root / "plugin-validation.json"
        resource = f"res://addons/{install_dir}/{entry_script}"
        descriptor_resource = f"res://addons/{install_dir}/plugin.cfg"
        validation_config = replace(
            config,
            project_path=validation_root,
            project_path_input=validation_root,
        )
        process = GodotTransport(validation_config).run(
            ["--editor", "--script", str(PLUGIN_VALIDATOR_SCRIPT)],
            timeout=config.editor_timeout,
            environment={
                "A3GAME_GODOT_PLUGIN_RESOURCE": resource,
                "A3GAME_GODOT_PLUGIN_DESCRIPTOR": descriptor_resource,
                "A3GAME_GODOT_PLUGIN_REPORT": str(report),
            },
        )
        process_summary = {
            "returncode": process.returncode,
            "stdout_tail": process.stdout[-4000:],
            "stderr_tail": process.stderr[-4000:],
            "duration_seconds": process.duration_seconds,
        }
        if not report.is_file():
            details = process.stderr.strip() or process.stdout.strip()
            raise RuntimeError(
                "Godot plugin validation produced no report"
                + (f": {details[-4000:]}" if details else "")
            )
        try:
            validation = json.loads(report.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Godot plugin validation report is invalid JSON") from exc
        if not isinstance(validation, dict):
            raise ValueError("Godot plugin validation report must be an object")
        if validation.get("schema_version") != PLUGIN_VALIDATION_SCHEMA:
            raise ValueError("Godot plugin validation report has an unsupported schema")
        if validation.get("resource_path") != resource:
            raise ValueError(
                "Godot plugin validation report does not match the entry script"
            )
        if validation.get("descriptor_path") != descriptor_resource:
            raise ValueError("Godot plugin validation report does not match plugin.cfg")
        if validation.get("ok") is not True:
            detail = str(
                validation.get("error")
                or process.stderr.strip()
                or "Godot could not load the plugin entry script"
            )
            raise ValueError(f"Godot plugin entry validation failed: {detail}")
        if process.returncode != 0:
            raise RuntimeError(
                "Godot plugin validation reported success but exited with "
                f"status {process.returncode}"
            )
        if validation.get("base_type") != "EditorPlugin":
            raise ValueError("Godot plugin entry script must inherit EditorPlugin")
        if validation.get("can_instantiate") is not True:
            raise ValueError("Godot plugin entry script cannot be instantiated")
        if validation.get("is_tool") is not True:
            raise ValueError("Godot plugin entry script must run in tool mode")
        if validation.get("instantiated") is not True:
            raise ValueError(
                "Godot plugin entry script did not produce an EditorPlugin instance"
            )
        if validation.get("instance_class") != "EditorPlugin":
            raise ValueError(
                "Godot plugin entry script produced an unexpected instance type"
            )
        return process_summary, validation


def _editor_plugin_entries(
    text: str,
) -> tuple[
    list[tuple[int, int]],
    list[tuple[int, int, str, str, str, list[str]]],
]:
    """扫描 ``[editor_plugins]`` 段，解析其中的 ``enabled=`` 条目。

    值必须是**单行** ``PackedStringArray("a", "b")``。解析成字符串列表返回，同时保留
    位置、行首缩进、行尾注释与换行风格，供后续原地改写使用（不能重排用户的格式）。

    Args:
        text: ``project.godot`` 的全文。

    Returns:
        ``(段落范围列表, 条目列表)``；条目为
        ``(起始偏移, 结束偏移, 行首前缀, 注释, 换行符, 值列表)``。

    Raises:
        ValueError: 值不是单行 PackedStringArray，或其中元素不是字符串。
    """
    headers = list(_SECTION_HEADER_PATTERN.finditer(text))
    sections: list[tuple[int, int]] = []
    entries: list[tuple[int, int, str, str, str, list[str]]] = []
    for index, header in enumerate(headers):
        if header.group("name") != "editor_plugins":
            continue
        body_start = header.end()
        body_end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        sections.append((body_start, body_end))
        for entry in _EDITOR_PLUGIN_ENTRY_PATTERN.finditer(text, body_start, body_end):
            raw_value, comment = _split_assignment_comment(entry.group("value"))
            packed = _PACKED_STRING_ARRAY_PATTERN.fullmatch(raw_value)
            if packed is None:
                raise ValueError(
                    "Godot editor_plugins/enabled must use a single-line "
                    "PackedStringArray(...) value"
                )
            arguments = packed.group("arguments").strip()
            if arguments.endswith(","):
                arguments = arguments[:-1].rstrip()
            try:
                values = json.loads(f"[{arguments}]") if arguments else []
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "Godot editor_plugins/enabled contains an invalid "
                    "PackedStringArray(...) value"
                ) from exc
            if not isinstance(values, list) or any(
                not isinstance(value, str) for value in values
            ):
                raise ValueError(
                    "Godot editor_plugins/enabled must contain only string paths"
                )
            entries.append(
                (
                    entry.start(),
                    entry.end(),
                    entry.group("prefix"),
                    comment,
                    entry.group("newline"),
                    values,
                )
            )
    return sections, entries


def _validate_plugin_update(
    text: str,
) -> tuple[
    list[tuple[int, int]],
    list[tuple[int, int, str, str, str, list[str]]],
]:
    """改写 ``project.godot`` 之前，拒绝有歧义的 ``[editor_plugins]`` 声明。

    段落重复、或 ``enabled=`` 重复时直接失败，而不是猜哪个是「对的那个」——
    猜错会静默改坏用户的工程配置。

    Args:
        text: ``project.godot`` 的全文。

    Returns:
        ``(段落范围列表, 条目列表)``，可直接交给 `_enable_plugin` 使用。

    Raises:
        ValueError: ``[editor_plugins]`` 或其中的 ``enabled=`` 出现多次。
    """
    sections, entries = _editor_plugin_entries(text)
    if len(sections) > 1:
        raise ValueError(
            "Godot [editor_plugins] is declared more than once; refusing an "
            "ambiguous plugin enablement without changing the project"
        )
    if len(entries) > 1:
        raise ValueError(
            "Godot editor_plugins/enabled is declared more than once; refusing "
            "an ambiguous plugin enablement without changing the project"
        )
    return sections, entries


def _enable_plugin(project_file: Path, install_dir: str) -> None:
    """把加载项的 ``plugin.cfg`` 资源追加进 ``[editor_plugins] enabled``。

    三种落点分别处理：已有 ``enabled=`` 就原地替换（保留缩进、注释、换行风格）；
    有 ``[editor_plugins]`` 段但没有该键就在段尾补一行；两者都没有就新建整个段落。
    写入后**重新解析一次**，确认值真的被保留。

    Args:
        project_file: ``project.godot`` 路径。
        install_dir: 加载项在 ``addons/`` 下的目录名。

    Raises:
        RuntimeError: 写回后重新解析，发现资源没被保留。
    """
    resource = f"res://addons/{install_dir}/plugin.cfg"
    text = project_file.read_text(encoding="utf-8")
    sections, entries = _validate_plugin_update(text)
    replacement = (
        "PackedStringArray("
        + ", ".join(
            json.dumps(item)
            for item in dict.fromkeys([*(entries[0][5] if entries else []), resource])
        )
        + ")"
    )
    if entries:
        start, end, prefix, comment, newline, _values = entries[0]
        updated = text[:start] + prefix + replacement + comment + newline + text[end:]
    elif sections:
        body_start, body_end = sections[0]
        body = text[body_start:body_end]
        newline = "\r\n" if "\r\n" in text else "\n"
        header_separator = "" if text[:body_start].endswith(("\n", "\r")) else newline
        updated_body = (
            header_separator
            + body
            + ("" if not body or body.endswith(("\n", "\r")) else newline)
            + "enabled="
            + replacement
            + newline
        )
        updated = text[:body_start] + updated_body + text[body_end:]
    else:
        newline = "\r\n" if "\r\n" in text else "\n"
        suffix = "" if not text or text.endswith(("\n", "\r")) else newline
        updated = (
            text
            + suffix
            + newline
            + "[editor_plugins]"
            + newline
            + "enabled="
            + replacement
            + newline
        )
    project_file.write_text(updated, encoding="utf-8")

    _sections, updated_entries = _validate_plugin_update(
        project_file.read_text(encoding="utf-8")
    )
    if len(updated_entries) != 1 or resource not in updated_entries[0][5]:
        raise RuntimeError(
            f"Godot did not retain the enabled editor plugin setting: {resource}"
        )


def _autoload_entries(
    text: str, name: str
) -> tuple[
    list[tuple[int, int]],
    list[tuple[int, int, str, str, str, Any]],
]:
    """扫描 ``[autoload]`` 段，解析出指定名字的条目。

    与 `_editor_plugin_entries` 同一套路，但值是单个字符串。解析失败时退回原始文本，
    因为 autoload 的值可能是 Godot 表达式而非 JSON 字符串。

    Args:
        text: ``project.godot`` 的全文。
        name: autoload 名字，例如 ``A3GameRuntime``。

    Returns:
        ``(段落范围列表, 条目列表)``；条目为
        ``(起始偏移, 结束偏移, 行首前缀, 注释, 换行符, 值)``。
    """
    headers = list(_SECTION_HEADER_PATTERN.finditer(text))
    sections: list[tuple[int, int]] = []
    entry_pattern = re.compile(
        rf"(?m)^(?P<prefix>[ \t]*{re.escape(name)}[ \t]*=[ \t]*)"
        r"(?P<value>[^\r\n]*)(?P<newline>\r?\n|\Z)"
    )
    entries: list[tuple[int, int, str, str, str, Any]] = []
    for index, header in enumerate(headers):
        if header.group("name") != "autoload":
            continue
        body_start = header.end()
        body_end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        sections.append((body_start, body_end))
        for existing in entry_pattern.finditer(text, body_start, body_end):
            raw_value, comment = _split_assignment_comment(existing.group("value"))
            try:
                value = json.loads(raw_value)
            except json.JSONDecodeError:
                value = raw_value
            entries.append(
                (
                    existing.start(),
                    existing.end(),
                    existing.group("prefix"),
                    comment,
                    existing.group("newline"),
                    value,
                )
            )
    return sections, entries


def _validate_autoload_update(
    text: str,
    name: str,
    resource: str,
    *,
    replace_existing: bool,
) -> None:
    """确认 autoload 可被安全写入，否则报错让调用方决定。

    这是「宁可不装，也不静默覆盖」策略的落点：同名 autoload 已存在时，只有内容正好是
    期望值才放行；名字被声明多次、或指向别的资源，都抛 `FileExistsError` 并提示用
    ``replace_existing=True`` 显式覆盖。

    Args:
        text: ``project.godot`` 的全文。
        name: 要写入的 autoload 名字。
        resource: 期望的脚本资源路径（不含单例前缀 ``*``）。
        replace_existing: ``True`` 时跳过全部检查，允许覆盖。

    Raises:
        FileExistsError: 同名 autoload 已存在且与期望值不符，或声明次数不为 1。
    """
    _sections, entries = _autoload_entries(text, name)
    expected = "*" + resource
    if not entries or replace_existing:
        return
    values = [entry[5] for entry in entries]
    if len(entries) != 1:
        raise FileExistsError(
            f"Godot autoload {name!r} is declared {len(entries)} times "
            f"with values {values!r}; set replace_existing=True to normalize it"
        )
    if values[0] != expected:
        raise FileExistsError(
            f"Godot autoload {name!r} already points to {values[0]!r}; "
            "set replace_existing=True to replace it"
        )


def _enable_autoload(
    project_file: Path,
    name: str,
    resource: str,
    *,
    replace_existing: bool,
) -> None:
    """把 autoload 设置写入 ``project.godot`` 的 ``[autoload]`` 段。

    Godot 的 autoload 值用 ``*`` 前缀表示「单例」，写入时用 `json.dumps` 补引号。
    三种落点：没有 ``[autoload]`` 段就新建；已有同名条目且允许替换时原地改写
    （多余的同名条目一并删除，**从后往前**改以免偏移失效）；有段无条目则追加到段尾。

    Args:
        project_file: ``project.godot`` 路径。
        name: autoload 名字。
        resource: 脚本资源路径（不含单例前缀 ``*``）。
        replace_existing: ``True`` 时允许覆盖已有条目。
    """
    text = project_file.read_text(encoding="utf-8")
    sections, entries = _autoload_entries(text, name)
    _validate_autoload_update(
        text,
        name,
        resource,
        replace_existing=replace_existing,
    )
    encoded_value = json.dumps("*" + resource)
    setting = f"{name}={encoded_value}"
    if entries and not replace_existing:
        return
    if not sections:
        suffix = "" if text.endswith("\n") else "\n"
        project_file.write_text(
            text + suffix + "\n[autoload]\n" + setting + "\n",
            encoding="utf-8",
        )
        return
    if entries:
        replacements = [
            (
                entries[0][0],
                entries[0][1],
                entries[0][2] + encoded_value + entries[0][3] + entries[0][4],
            ),
            *[
                (start, end, "")
                for start, end, _prefix, _comment, _newline, _value in entries[1:]
            ],
        ]
        for start, end, replacement in reversed(replacements):
            text = text[:start] + replacement + text[end:]
        project_file.write_text(text, encoding="utf-8")
        return
    body_start, body_end = sections[0]
    body = text[body_start:body_end]
    new_body = body + ("" if body.endswith("\n") else "\n") + setting + "\n"
    project_file.write_text(
        text[:body_start] + new_body + text[body_end:],
        encoding="utf-8",
    )


class GodotPluginClient:
    def __init__(self, config: GodotClientConfig) -> None:
        """保存已解析的配置，并建立源解析器。

        Args:
            config: 由 `GodotClientConfig.resolve()` 产出的配置对象。
        """
        self._config = config
        self._sources = GeneratedAssetSourceResolver()

    def install(
        self,
        source: Mapping[str, Any],
        *,
        install_dir: str = "",
        replace_existing: bool = False,
        enable: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """安装一个外部加载项：校验 → 暂存 → 原生验证 → 落盘 → 启用。

        分两阶段：先在 ``try`` 里完成**所有**不写盘的准备工作（解析源、确认
        ``plugin.cfg`` 存在、校验安装目标安全），任何一步失败就返回结构化失败结果；
        真正写盘的部分交给 `_install_tree`，由它统一负责回滚。

        Args:
            source: 源描述符（路径或生成物引用）。
            install_dir: 目标目录名；留空时取源目录名。
            replace_existing: 目标已存在时是否允许替换。
            enable: 是否同时写入 ``project.godot`` 的启用设置。
            dry_run: 只做校验与原生验证，不落盘。

        Returns:
            ``GodotOperationResult`` 字典；失败时 ``ok=False``，errors 里带异常类型名。
        """
        operation = "plugin.install"
        try:
            resolved = self._sources.resolve(source, allow_directory=True)
            source_root = resolved.path
            if not source_root.is_dir():
                raise ValueError("Godot add-on source must be a directory")
            descriptor = source_root / "plugin.cfg"
            if not descriptor.is_file():
                raise FileNotFoundError(
                    f"Godot add-on source has no plugin.cfg: {descriptor}"
                )
            name = _safe_name(install_dir or source_root.name)
            project_dir, project_file = self._project()
            target = _install_target(project_dir, name)
        except Exception as exc:
            return GodotOperationResult.failure(
                operation,
                f"{type(exc).__name__}: {exc}",
                payload={"source": source_descriptor(source)},
            ).to_dict()
        return self._install_tree(
            operation,
            source_root,
            target,
            project_file,
            name,
            source_descriptor=resolved.descriptor(),
            replace_existing=replace_existing,
            enable=enable,
            dry_run=dry_run,
            artifact_type="godot_gameplay_addon",
        )

    def install_framework(
        self,
        *,
        replace_existing: bool = False,
        enable: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """安装适配器自带的 A3GamePlayable 运行时框架。

        与 `install()` 的区别：源固定为包内目录，且会额外注册 ``A3GameRuntime`` autoload
        ——框架需要在游戏启动时自动挂载。

        Args:
            replace_existing: 目标已存在时是否允许替换。
            enable: 是否写入启用设置与 autoload。
            dry_run: 只做校验与原生验证，不落盘。

        Returns:
            ``GodotOperationResult`` 字典。
        """
        operation = "plugin.install_framework"
        try:
            project_dir, project_file = self._project()
            if not (FRAMEWORK_ROOT / "plugin.cfg").is_file():
                raise FileNotFoundError(
                    f"A3GamePlayable framework source was not found: {FRAMEWORK_ROOT}"
                )
            target = _install_target(project_dir, FRAMEWORK_INSTALL_DIR)
        except Exception as exc:
            return GodotOperationResult.failure(
                operation, f"{type(exc).__name__}: {exc}"
            ).to_dict()
        return self._install_tree(
            operation,
            FRAMEWORK_ROOT,
            target,
            project_file,
            FRAMEWORK_INSTALL_DIR,
            source_descriptor={"adapter_owned": "A3GamePlayable"},
            replace_existing=replace_existing,
            enable=enable,
            dry_run=dry_run,
            artifact_type="godot_runtime_framework",
            autoload_name=FRAMEWORK_AUTOLOAD_NAME,
            autoload_path=FRAMEWORK_AUTOLOAD_PATH,
        )

    def list(self) -> dict[str, Any]:
        """列出项目 ``addons/`` 下所有可用的加载项。

        逐个条目判定，任何不安全或不完整的情况都**跳过并记一条 warning**，而不是中断整个
        列举：符号链接、非目录、非普通文件、``plugin.cfg`` 缺失、以及解析后逃出
        ``addons/`` 的描述符。这样一次调用就能看清哪些加载项可用、哪些被拒绝及原因。

        Returns:
            ``GodotOperationResult`` 字典；artifacts 每项含 artifact_id、backend_path 与
            类型（godot_runtime_framework 或 godot_gameplay_addon），payload.count 为总数。
        """
        try:
            project_dir, _project_file = self._project()
            addons = _addons_directory(project_dir)
        except Exception as exc:
            return GodotOperationResult.failure(
                "plugin.list", f"{type(exc).__name__}: {exc}"
            ).to_dict()
        artifacts = []
        warnings = []
        if addons.is_dir():
            resolved_addons = addons.resolve(strict=True)
            for plugin_dir in sorted(addons.iterdir(), key=lambda item: item.name):
                try:
                    plugin_mode = plugin_dir.lstat().st_mode
                except OSError as exc:
                    warnings.append(
                        f"Skipped unreadable Godot add-on entry {plugin_dir.name}: {exc}"
                    )
                    continue
                if stat.S_ISLNK(plugin_mode):
                    warnings.append(
                        f"Skipped symbolic-link Godot add-on: {plugin_dir.name}"
                    )
                    continue
                if not stat.S_ISDIR(plugin_mode):
                    continue
                descriptor = plugin_dir / "plugin.cfg"
                try:
                    descriptor_mode = descriptor.lstat().st_mode
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    warnings.append(
                        "Skipped unreadable Godot add-on descriptor "
                        f"{plugin_dir.name}/plugin.cfg: {exc}"
                    )
                    continue
                if stat.S_ISLNK(descriptor_mode):
                    warnings.append(
                        "Skipped symbolic-link Godot add-on descriptor: "
                        f"{plugin_dir.name}/plugin.cfg"
                    )
                    continue
                if not stat.S_ISREG(descriptor_mode):
                    warnings.append(
                        "Skipped non-regular Godot add-on descriptor: "
                        f"{plugin_dir.name}/plugin.cfg"
                    )
                    continue
                try:
                    resolved_plugin_dir = plugin_dir.resolve(strict=True)
                    resolved_descriptor = descriptor.resolve(strict=True)
                    resolved_plugin_dir.relative_to(resolved_addons)
                    resolved_descriptor.relative_to(resolved_plugin_dir)
                except (OSError, ValueError) as exc:
                    warnings.append(
                        "Skipped Godot add-on descriptor outside project add-ons: "
                        f"{plugin_dir.name}/plugin.cfg ({exc})"
                    )
                    continue
                artifacts.append(
                    {
                        "artifact_id": descriptor.parent.name,
                        "asset_id": descriptor.parent.name,
                        "type": (
                            "godot_runtime_framework"
                            if descriptor.parent.name == FRAMEWORK_INSTALL_DIR
                            else "godot_gameplay_addon"
                        ),
                        "backend": "godot",
                        "backend_class": "EditorPlugin",
                        "backend_path": "res://"
                        + descriptor.relative_to(project_dir).as_posix(),
                        "state": "ready",
                        "metadata": {"path": str(descriptor.parent)},
                    }
                )
        return GodotOperationResult.success(
            "plugin.list",
            artifacts=artifacts,
            warnings=warnings,
            payload={"count": len(artifacts)},
        ).to_dict()

    def _project(self) -> tuple[Path, Path]:
        """取项目根与 ``project.godot``，并确认两者的关系是安全的。

        要求 ``project.godot`` 真实存在、本身不是符号链接，且解析后**直接**位于项目根下
        （``parent == root``，而不是更深或更浅的位置）。

        Returns:
            ``(项目根绝对路径, project.godot 绝对路径)``。

        Raises:
            FileNotFoundError: ``project_path`` 未解析出存在的 ``project.godot``。
            ValueError: 项目文件是符号链接，或不在项目根下。
        """
        project_dir = self._config.project_dir
        project_file = self._config.project_file
        if project_dir is None or project_file is None or not project_file.is_file():
            raise FileNotFoundError(
                "project_path does not resolve to an existing project.godot"
            )
        root = project_dir.resolve(strict=True)
        if project_file.is_symlink():
            raise ValueError(
                f"Godot project file must not be a symlink: {project_file}"
            )
        resolved_project_file = project_file.resolve(strict=True)
        if resolved_project_file.parent != root:
            raise ValueError(
                f"Godot project file escaped the project root: {project_file}"
            )
        return root, resolved_project_file

    def _install_tree(
        self,
        operation: str,
        source: Path,
        target: Path,
        project_file: Path,
        install_dir: str,
        *,
        source_descriptor: Mapping[str, Any],
        replace_existing: bool,
        enable: bool,
        dry_run: bool,
        artifact_type: str,
        autoload_name: str = "",
        autoload_path: str = "",
    ) -> dict[str, Any]:
        """把加载项目录装进项目并可选地启用，全程保证原子性。

        顺序：校验源树 → 解析 ``plugin.cfg`` → 确认目标安全 → 预检 ``project.godot``
        冲突 → 拷入 staging 并**用真实 Godot 验证** → ``dry_run`` 提前返回 →
        备份既有目标 → 落盘 → 改写 ``project.godot``。

        任一环节抛异常都会回滚：删掉已落盘的目标、把备份移回原位、将 ``project.godot``
        还原成原始文本。临时 staging 与备份目录在 ``finally`` 里清理。

        Args:
            operation: 操作名，写入返回结果。
            source: 加载项源目录。
            target: 安装目标目录。
            project_file: ``project.godot`` 路径。
            install_dir: 目标目录名。
            source_descriptor: 写入 payload 的源描述。
            replace_existing: 目标已存在时是否允许替换。
            enable: 是否写入启用设置。
            dry_run: 只做校验与原生验证，不落盘。
            artifact_type: 产物类型（框架或普通加载项）。
            autoload_name: 需注册的 autoload 名字；空则跳过。
            autoload_path: autoload 指向的脚本资源路径。

        Returns:
            成功时为 ``GodotOperationResult.success``（artifacts 含目标路径与 ``res://``
            资源路径，payload 含 entry_script、native_validation、copied_files）；
            失败时为结构化 failure，且磁盘状态已还原。
        """
        resource = f"res://addons/{install_dir}/plugin.cfg"
        payload = {
            "source": dict(source_descriptor),
            "source_path": str(source),
            "target": str(target),
            "plugin": resource,
            "replace_existing": replace_existing,
            "enabled": enable,
            "autoload": autoload_name if enable else "",
            "dry_run": dry_run,
        }
        backup_root: Path | None = None
        backup: Path | None = None
        staging_root: Path | None = None
        original_project: str | None = None
        project_changed = False
        installed = False
        try:
            _validate_tree(source)
            entry_script, _entry_file, plugin_metadata = _plugin_entry_script(source)
            payload["entry_script"] = entry_script
            payload["plugin_metadata"] = plugin_metadata
            checked_target = _install_target(project_file.parent, install_dir)
            if checked_target != target:
                raise ValueError(
                    f"Godot add-on target changed during validation: {target}"
                )
            if (target.exists() or target.is_symlink()) and not replace_existing:
                raise FileExistsError(
                    f"Godot add-on target already exists: {target}; "
                    "set replace_existing=True to replace it"
                )
            project_text = project_file.read_text(encoding="utf-8")
            if enable:
                _validate_plugin_update(project_text)
            if enable and autoload_name and autoload_path:
                _validate_autoload_update(
                    project_text,
                    autoload_name,
                    autoload_path,
                    replace_existing=replace_existing,
                )
            staging_root = Path(tempfile.mkdtemp(prefix="a3game-godot-plugin-stage-"))
            staging = staging_root / target.name
            shutil.copytree(source, staging, symlinks=True)
            _validate_tree(staging)
            staged_entry, _staged_entry_file, staged_metadata = _plugin_entry_script(
                staging
            )
            if staged_entry != entry_script or staged_metadata != plugin_metadata:
                raise ValueError("Godot add-on descriptor changed during staging")
            process_summary, validation = _validate_plugin_with_godot(
                staging,
                install_dir,
                entry_script,
                self._config,
            )
            payload["native_validation"] = {
                "process": process_summary,
                "report": validation,
            }
            if dry_run:
                return GodotOperationResult.success(
                    operation, payload=payload
                ).to_dict()
            original_project = project_text
            checked_target = _install_target(project_file.parent, install_dir)
            if checked_target != target:
                raise ValueError(
                    f"Godot add-on target changed during staging: {target}"
                )
            if (target.exists() or target.is_symlink()) and not replace_existing:
                raise FileExistsError(
                    f"Godot add-on target already exists: {target}; "
                    "set replace_existing=True to replace it"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                backup_root = Path(
                    tempfile.mkdtemp(prefix="a3game-godot-plugin-backup-")
                )
                backup = backup_root / target.name
                shutil.move(str(target), str(backup))
            installed = True
            shutil.move(str(staging), str(target))
            if enable:
                project_changed = True
                _enable_plugin(project_file, install_dir)
                if autoload_name and autoload_path:
                    _enable_autoload(
                        project_file,
                        autoload_name,
                        autoload_path,
                        replace_existing=replace_existing,
                    )
            copied = _copied_files(target)
        except Exception as exc:
            if installed:
                if target.is_symlink() or target.is_file():
                    target.unlink(missing_ok=True)
                elif target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
            if backup is not None and (backup.exists() or backup.is_symlink()):
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(backup), str(target))
            if original_project is not None and project_changed:
                try:
                    project_file.write_text(original_project, encoding="utf-8")
                except OSError:
                    pass
            return GodotOperationResult.failure(
                operation,
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()
        finally:
            if staging_root is not None:
                shutil.rmtree(staging_root, ignore_errors=True)
            if backup_root is not None:
                shutil.rmtree(backup_root, ignore_errors=True)
        payload["copied_files"] = copied
        return GodotOperationResult.success(
            operation,
            artifacts=[
                {
                    "type": artifact_type,
                    "path": str(target),
                    "backend_path": resource,
                    "state": "ready",
                }
            ],
            payload=payload,
        ).to_dict()
