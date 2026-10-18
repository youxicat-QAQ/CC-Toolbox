"""用户路径配置 — 从 paths_config.json 读写自定义扫描路径，与 config 默认值合并

三组配置键：
- skill_paths           自定义技能扫描目录（追加到 config.SKILL_PATHS 之后）
- cli_paths             自定义 CLI 扫描目录（追加到 config.CLI_PATHS 之后）
- extra_mcp_project_dirs  额外 MCP 项目目录（仅自定义，无默认项）
"""
import copy
import json
import logging
import os
import threading
from pathlib import Path
from typing import List

import config

logger = logging.getLogger(__name__)

# 配置文件固定放本项目目录（不放用户家目录，便于随仓库分发默认空配置）
PATHS_CONFIG_FILE = Path(__file__).parent / "paths_config.json"

# 合法的三组配置键
_FIELDS = ("skill_paths", "cli_paths", "extra_mcp_project_dirs")

# 读-改-写共享锁（RLock：update_group 持锁后调 _save，_save 内部再拿同一把锁，可重入防死锁）
_lock = threading.RLock()


def _load() -> dict:
    """读取配置文件；缺失/损坏返回 {}，非 list 的值修正为 []。

    不缓存到内存（每次调用都读盘）——配置文件小，且读取方（get_merged_*、
    is_configured_path）多在扫描/API 请求路径上，需要看到最新值。
    """
    if not PATHS_CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(PATHS_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("paths_config.json 解析失败（%s），按空配置处理：%s",
                       exc, PATHS_CONFIG_FILE)
        return {}
    if not isinstance(data, dict):
        logger.warning("paths_config.json 根节点应为对象，按空配置处理：actual=%s",
                       type(data).__name__)
        return {}
    # 三键中值非 list 的按 [] 修正，避免下游拿到 str/int 却当 list 迭代
    for key in _FIELDS:
        if not isinstance(data.get(key), list):
            data[key] = []
    return data


def _save(data: dict) -> None:
    """原子写配置文件（tmp + os.replace，参考 desc_cache.py 模式）。"""
    with _lock:
        tmp = PATHS_CONFIG_FILE.with_name(PATHS_CONFIG_FILE.name + ".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, PATHS_CONFIG_FILE)
        except Exception:
            # 写入/替换失败时清理临时文件，主文件保持原样，然后 re-raise
            try:
                tmp.unlink()
            except OSError:
                pass
            raise


def get_config() -> dict:
    """返回完整配置（深拷贝，调用方改副本不影响内部状态）。"""
    return copy.deepcopy(_load())


def _merge(defaults: List[Path], custom: List[str]) -> List[Path]:
    """把 config 默认路径与用户自定义路径合并为 list[Path]。

    - 逐项 Path(p).expanduser()
    - 字符串级去重保序（str() 比较），先出现的默认项优先
    """
    result: List[Path] = []
    seen: set = set()
    for item in list(defaults) + list(custom):
        p = Path(item).expanduser()
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        result.append(p)
    return result


def get_merged_skill_paths() -> List[Path]:
    """config.SKILL_PATHS 默认 + 用户自定义 skill_paths 合并去重。"""
    return _merge(config.SKILL_PATHS, _load().get("skill_paths", []))


def get_merged_cli_paths() -> List[Path]:
    """config.CLI_PATHS 默认 + 用户自定义 cli_paths 合并去重。"""
    return _merge(config.CLI_PATHS, _load().get("cli_paths", []))


def get_extra_mcp_dirs() -> List[Path]:
    """仅用户自定义的额外 MCP 项目目录（无默认项）。"""
    return [Path(p).expanduser() for p in _load().get("extra_mcp_project_dirs", [])]


def update_group(group: str, paths: List[str]) -> dict:
    """更新一组配置并落盘，返回最新 get_config()。

    - group 必须 ∈ _FIELDS，否则 ValueError（调用方转 400）
    - paths 必须是 list，否则 TypeError（调用方转 400）
    - 逐项 strip、去空、str(Path(p).expanduser()) 规范化后保存
    - 锁内 load → 改 → save，防并发覆盖
    """
    if group not in _FIELDS:
        raise ValueError(f"未知配置组：{group!r}")
    if not isinstance(paths, list):
        raise TypeError("paths 必须是 list")

    cleaned = []
    seen: set = set()
    for raw in paths:
        s = str(raw).strip()
        if not s:
            continue
        norm = str(Path(s).expanduser())
        if norm in seen:
            continue
        seen.add(norm)
        cleaned.append(norm)

    with _lock:
        data = _load()
        data[group] = cleaned
        _save(data)
    return get_config()


def _all_configured_paths() -> List[Path]:
    """合并三组路径（skill + cli + mcp_extra）供精确匹配用。"""
    return (get_merged_skill_paths()
            + get_merged_cli_paths()
            + get_extra_mcp_dirs())


def is_configured_path(candidate: str) -> bool:
    """candidate 的 resolve 是否精确等于任一已配置路径的 resolve。"""
    try:
        cand = Path(candidate).expanduser().resolve()
    except OSError:
        return False
    for p in _all_configured_paths():
        try:
            if p.resolve() == cand:
                return True
        except OSError:
            continue
    return False


# /api/paths/open 允许打开的白名单文件名（供 open 接口放行，防任意路径打开）
KNOWN_USER_FILES = {
    "paths_config.json",
    "ai_descriptions.json",
    "ai_descriptions.example.json",
}


def is_known_user_file(candidate: str) -> bool:
    """candidate 是否为本项目目录下的已知用户配置文件（精确白名单）。"""
    try:
        cand = Path(candidate).expanduser().resolve()
        base = PATHS_CONFIG_FILE.parent.resolve()
    except OSError:
        return False
    return cand.parent == base and cand.name in KNOWN_USER_FILES
