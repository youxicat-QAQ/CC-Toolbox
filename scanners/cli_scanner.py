"""CLI 工具扫描器 — 扫描配置目录 + PATH"""
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

import config
from paths_config import get_merged_cli_paths

logger = logging.getLogger(__name__)

_cache: List[dict] = []
_cache_time: Optional[float] = None
_cache_lock = threading.Lock()

# Windows 可执行后缀白名单（npm shim 为 .cmd/.ps1，原生 .exe，另有 .bat/.com/.ahk）
EXECUTABLE_SUFFIXES = {".exe", ".cmd", ".bat", ".com", ".ps1", ".ahk"}

# 同名工具多后缀共存时的优先级（数值越小越优先；消除 iterdir 顺序依赖，#M-5）
_SUFFIX_PRIORITY = {".exe": 0, ".cmd": 1, ".bat": 2, ".com": 3, ".ps1": 4, ".ahk": 5}


def _suffix_rank(path: str) -> int:
    """返回可执行文件后缀的去重优先级（未知后缀最低）。"""
    return _SUFFIX_PRIORITY.get(Path(path).suffix.lower(), 99)


def _is_executable(name: str, parent: str = "") -> bool:
    """判断文件名是否为可执行文件。

    有后缀 → 必须命中白名单；无后缀 → 仅认 .bin 目录内的 npm shim
    （npm 在 .bin 下生成的无扩展名 bash shim），其余无后缀文件（LICENSE、
    README 等）一律不收。parent 为文件所在目录路径或空串。
    """
    suffix = Path(name.lower()).suffix
    if suffix:
        return suffix in EXECUTABLE_SUFFIXES
    return Path(parent).name == ".bin"


def _scan_directory(dir_path: Path, category: str = "general") -> List[dict]:
    """扫描单个目录（不跑 --version/--help，详情时延迟加载）。"""
    tools = []
    if not dir_path.exists():
        return tools
    try:
        items = list(dir_path.iterdir())
    except OSError as exc:
        # 无权限/目录被删：告警跳过整个目录（与 _scan_path 的防护一致）
        logger.warning("CLI 目录不可读，跳过 %s：%s", dir_path, exc)
        return tools
    for item in items:
        try:
            if item.name.startswith("."):
                continue
            if not (item.is_file() or item.is_symlink()):
                continue
            if _is_executable(item.name, str(item.parent)):
                name = item.stem if item.suffix.lower() in EXECUTABLE_SUFFIXES else item.name
            else:
                continue
        except OSError as exc:
            logger.warning("CLI 条目检查失败，跳过 %s：%s", item, exc)
            continue
        if name in config.SKIP_CLI_TOOLS:
            continue
        tools.append({
            "name": name,
            "path": str(item),
            "version": None,
            "description": "",
            "category": category,
        })
    return tools


# _scan_path 读取的环境变量名（模块级可覆盖，测试可 monkeypatch 以隔离系统 PATH）
PATH_ENV_VAR = "PATH"


def _scan_path() -> List[dict]:
    """扫描系统 PATH（不跑 --version/--help 以免太慢）。"""
    tools = []
    path_dirs = os.environ.get(PATH_ENV_VAR, "").split(os.pathsep)
    seen: Set[str] = set()
    limit = 200  # 限制 PATH 工具数量

    for dir_path in path_dirs:
        if len(seen) >= limit:
            break
        dir_path = dir_path.strip()
        if not dir_path:
            continue  # 空项在 Path("") 下会退化为 cwd，跳过防误扫
        p = Path(dir_path)
        if not p.exists():
            continue
        try:
            for item in p.iterdir():
                if len(seen) >= limit:
                    break
                if item.name.startswith("."):
                    continue
                if not (item.is_file() or item.is_symlink()):
                    continue
                if _is_executable(item.name, str(item.parent)):
                    name = item.stem if item.suffix.lower() in EXECUTABLE_SUFFIXES else item.name
                else:
                    continue
                if name in config.SKIP_CLI_TOOLS or name in seen:
                    continue
                seen.add(name)
                tools.append({
                    "name": name,
                    "path": str(item),
                    "version": None,
                    "description": "",
                    "category": "path",
                })
        except OSError as exc:
            # 无权限/目录被删：告警跳过该目录剩余部分（与 _scan_directory 同构，#M-2）
            logger.warning("PATH 目录不可读，跳过 %s：%s", dir_path, exc)
    return tools


def scan_all() -> List[dict]:
    """扫描全部 CLI 路径 + PATH（按解析路径去重 + 工具名按后缀优先级去重）。

    同名多后缀共存时按 .exe > .cmd > .bat > .com > .ps1 取代（#M-5），
    消除 iterdir 遍历顺序对结果的影响。
    """
    seen_paths: Set[str] = set()
    by_name: Dict[str, dict] = {}
    name_keys: Dict[str, str] = {}  # name → 当前胜出条目的 path key（替换时回收）

    def _add(items: List[dict]) -> None:
        for t in items:
            try:
                pkey = str(Path(t["path"]).resolve())
            except OSError:
                pkey = t["path"]
            if pkey in seen_paths:
                continue
            cur = by_name.get(t["name"])
            if cur is None:
                seen_paths.add(pkey)
                by_name[t["name"]] = t
                name_keys[t["name"]] = pkey
            elif _suffix_rank(t["path"]) < _suffix_rank(cur["path"]):
                # 同名且新条目后缀优先级更高：替换胜出项，回收旧 path key
                seen_paths.discard(name_keys[t["name"]])
                seen_paths.add(pkey)
                by_name[t["name"]] = t
                name_keys[t["name"]] = pkey
            # 同名但优先级不更高：丢弃该条目

    for path_str in get_merged_cli_paths():
        p = path_str.expanduser()
        if p.exists():
            _add(_scan_directory(p, "cli_path"))
        for sub in ["node_modules/.bin", "bin"]:
            sp = p / sub
            if sp.exists():
                _add(_scan_directory(sp, "node"))

    # PATH 扫描只补充看有没有更多
    _add(_scan_path())

    return list(by_name.values())


def get_cli_tools(force_refresh: bool = False) -> List[dict]:
    """带缓存获取（120s TTL；加锁 + double-checked 防并发重复扫描）。"""
    global _cache, _cache_time
    now = time.time()
    if not force_refresh and _cache_time is not None and (now - _cache_time) <= config.CACHE_TTL:
        return _cache
    with _cache_lock:
        now = time.time()
        if not force_refresh and _cache_time is not None and (now - _cache_time) <= config.CACHE_TTL:
            return _cache
        _cache = scan_all()
        _cache_time = now
        return _cache


def _run_argv(path: str, flag: str) -> List[str]:
    """构造执行 argv；.ps1 无法直接 CreateProcess，需经 powershell 包装（#M-5）。"""
    if Path(path).suffix.lower() == ".ps1":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", path, flag]
    return [path, flag]


def get_version(name: str, timeout: float = 5) -> Optional[str]:
    """懒加载 CLI 版本：对该工具 path 执行 `--version`（shell=False + timeout）。

    成功返回 stdout 首个非空行（≤40 字符），失败/超时返回 None。
    成功后写回扫描器缓存该条目的 version 字段：缓存 dict 单键赋值在 GIL 下
    原子，不引入额外竞态；后续详情请求命中非 None 的 version 即不再重跑子进程。
    """
    tools = get_cli_tools()
    target = next((t for t in tools if t["name"] == name), None)
    if not target:
        return None
    path = target.get("path") or ""
    if not path:
        return None
    try:
        r = subprocess.run(_run_argv(path, "--version"), shell=False, capture_output=True,
                           text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except Exception:
        return None
    text = r.stdout or r.stderr or ""
    for line in text.splitlines():
        line = line.strip()
        if line:
            ver = line[:40]
            target["version"] = ver
            return ver
    return None


def get_help_output(name: str) -> dict:
    """获取特定 CLI 工具的 --help 输出。"""
    tools = get_cli_tools()
    target = next((t for t in tools if t["name"] == name), None)
    if not target:
        return {"error": "未找到该工具"}
    try:
        r = subprocess.run(_run_argv(target["path"], "--help"), capture_output=True,
                           text=True, timeout=10, encoding="utf-8", errors="replace")
        output = (r.stdout or r.stderr).strip()
        return {"output": output[:2000]}
    except Exception as e:
        return {"error": str(e)}
