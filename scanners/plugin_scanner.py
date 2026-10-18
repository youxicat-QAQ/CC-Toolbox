"""Plugin 扫描器 — 扫描 plugins 缓存目录 + installed_plugins.json"""
import json
import logging
import threading
import time
from pathlib import Path
from typing import List, Optional

import config

logger = logging.getLogger(__name__)

_cache: List[dict] = []
_cache_time: Optional[float] = None
_cache_lock = threading.Lock()


def _version_sort_key(v: str):
    """版本号按数字段元组比较（"10.1.0" > "2.9.0"），非数字段防御性跳过。"""
    return tuple(int(x) for x in v.split(".") if x.isdigit())


def _read_plugin_json(plugin_dir: Path) -> Optional[dict]:
    """读取插件目录下的 plugin.json（可能在 .claude-plugin/ 里）。"""
    for candidate in [plugin_dir / ".claude-plugin" / "plugin.json", plugin_dir / "plugin.json"]:
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                logger.warning("plugin.json 解析失败，跳过 %s：%s", candidate, exc)
                return None
    return None


def _collect_skills_commands_agents(plugin_dir: Path) -> dict:
    """收集插件下的 skills/commands/agents 目录（目录不可读只损失该子项，不中断）。"""
    skills = []
    skills_dir = plugin_dir / "skills"
    if skills_dir.exists():
        try:
            skills = sorted([d.name for d in skills_dir.iterdir() if d.is_dir()])
        except OSError as exc:
            logger.warning("插件 skills 目录不可读，跳过 %s：%s", skills_dir, exc)

    commands = []
    commands_dir = plugin_dir / "commands"
    if commands_dir.exists():
        try:
            commands = sorted([f.stem for f in commands_dir.glob("*.md")])
        except OSError as exc:
            logger.warning("插件 commands 目录不可读，跳过 %s：%s", commands_dir, exc)

    agents = []
    agents_dir = plugin_dir / "agents"
    if agents_dir.exists():
        try:
            agents = sorted([f.stem for f in agents_dir.glob("*.md")])
        except OSError as exc:
            logger.warning("插件 agents 目录不可读，跳过 %s：%s", agents_dir, exc)

    return {"skills": skills, "commands": commands, "agents": agents}


def _read_installed_plugins(plugins_dir: Path) -> dict:
    """从 installed_plugins.json 读 name → (path, source, version)。

    条目级容错：坏条目（非对象、installPath 缺失/为空、路径不存在）记告警后
    跳过，继续解析后续条目（#12）。
    """
    installed_paths = {}
    installed_path_abs = plugins_dir / "installed_plugins.json"
    if not installed_path_abs.exists():
        return installed_paths
    try:
        raw = json.loads(installed_path_abs.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("installed_plugins.json 解析失败，跳过方式一扫描：%s", exc)
        return installed_paths

    if not (isinstance(raw, dict) and isinstance(raw.get("plugins"), dict)):
        return installed_paths

    for key, entries in raw["plugins"].items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            try:
                if not isinstance(entry, dict):
                    raise TypeError(f"条目非对象（{type(entry).__name__}）")
                ip_raw = entry.get("installPath")
                # 空串/None 直接跳过：Path("") 会退化为 cwd（#12 的坑）
                if not ip_raw or not isinstance(ip_raw, str):
                    continue
                ip = Path(ip_raw)
                if not ip.exists():
                    continue
                # 取 @ 之前的名字作为显示名
                display_name = key.split("@")[0] if "@" in key else key
                installed_paths[display_name] = {
                    "path": ip,
                    "source": entry.get("source", ""),
                    "version": entry.get("version", ""),
                }
            except Exception as exc:
                logger.warning("installed_plugins.json 条目损坏，跳过 %r：%s", key, exc)
                continue
    return installed_paths


def scan_all() -> List[dict]:
    """扫描已安装的插件。"""
    plugins = []
    plugins_dir = config.CLAUDE_BASE / "plugins"
    if not plugins_dir.exists():
        return plugins

    # ── 方式一：从 installed_plugins.json 读取精确安装路径 ──
    installed_paths = _read_installed_plugins(plugins_dir)

    done_paths = set()
    for name, info in installed_paths.items():
        ip = info["path"]
        if str(ip) in done_paths:
            continue
        done_paths.add(str(ip))

        meta = _read_plugin_json(ip)
        if meta is None:
            continue

        subs = _collect_skills_commands_agents(ip)
        plugins.append({
            "name": name,
            "version": info["version"] or meta.get("version", ""),
            "description": meta.get("description", ""),
            "author": meta.get("author", ""),
            "source": info["source"],
            "skills": subs["skills"],
            "commands": subs["commands"],
            "agents": subs["agents"],
            "path": str(ip),
        })

    # ── 方式二：遍历 plugins 目录下子目录 ──
    # 处理 cache/ 下的插件（多版本共存，按数字段元组取最新一个）
    cache_dir = plugins_dir / "cache"
    if cache_dir.exists():
        cache_target = cache_dir.resolve()
        seen_names = {p["name"] for p in plugins}
        try:
            publishers = sorted(cache_target.iterdir())
        except OSError as exc:
            logger.warning("插件缓存目录不可读，跳过方式二扫描 %s：%s", cache_target, exc)
            publishers = []
        for publisher in publishers:
            try:
                if not publisher.is_dir() or publisher.name.startswith("."):
                    continue
                plugin_dirs = sorted(publisher.iterdir())
            except OSError as exc:
                logger.warning("插件发布者目录不可读，跳过 %s：%s", publisher, exc)
                continue
            for plugin_name_dir in plugin_dirs:
                try:
                    if not plugin_name_dir.is_dir() or plugin_name_dir.name.startswith("."):
                        continue
                    versions = sorted(
                        [v for v in plugin_name_dir.iterdir()
                         if v.is_dir() and not v.name.startswith(".")],
                        key=lambda v: _version_sort_key(v.name),
                    )
                except OSError as exc:
                    logger.warning("插件版本目录不可读，跳过 %s：%s", plugin_name_dir, exc)
                    continue
                if not versions:
                    continue
                latest = versions[-1]
                display_name = plugin_name_dir.name

                # 如果 installed_plugins 已经扫到了就跳过
                if display_name in seen_names:
                    continue

                meta = _read_plugin_json(latest)
                if meta is None:
                    continue

                subs = _collect_skills_commands_agents(latest)
                plugins.append({
                    "name": display_name,
                    "version": meta.get("version", ""),
                    "description": meta.get("description", ""),
                    "author": meta.get("author", ""),
                    "source": "",
                    "skills": subs["skills"],
                    "commands": subs["commands"],
                    "agents": subs["agents"],
                    "path": str(latest),
                })
                seen_names.add(display_name)

    return plugins


def get_plugins(force_refresh: bool = False) -> List[dict]:
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
