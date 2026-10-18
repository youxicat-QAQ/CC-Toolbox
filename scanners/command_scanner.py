"""Command 扫描器 — 扫描 commands/*.md（含子目录命名空间）"""
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


def scan_all() -> List[dict]:
    """扫描 commands 目录下所有 .md（递归一层以上子目录）。

    name 用相对路径转命名空间格式：顶层 commit.md → commit，
    子目录 git/commit.md → git:commit（#16）。
    """
    commands = []
    cmds_dir = config.CLAUDE_BASE / "commands"
    if not cmds_dir.exists():
        return commands

    try:
        files = sorted(cmds_dir.rglob("*.md"))
    except OSError as exc:
        logger.warning("命令目录不可读，跳过 %s：%s", cmds_dir, exc)
        return commands

    for f in files:
        # 相对路径 → 命名空间 name（子目录以 : 连接）
        try:
            rel_parts = f.relative_to(cmds_dir).with_suffix("").parts
        except ValueError:
            rel_parts = (f.stem,)
        name = ":".join(rel_parts) if rel_parts else f.stem

        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("命令文件不可读，跳过 %s：%s", f, exc)
            continue

        lines = text.strip().split("\n")

        # 第一行去 # 前缀作为描述
        description = ""
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                if len(stripped) > 5:
                    description = stripped[:200]
                    break
            elif stripped.startswith("# ") and len(stripped) > 2:
                # 标题行本身也可以作为描述
                desc = stripped.lstrip("# ").strip()
                if not description:
                    description = desc[:200]

        # 内容预览
        content = "\n".join(lines[:30])[:500]

        commands.append({
            "name": name,
            "description": description,
            "content": content,
            "path": str(f),
        })

    return commands


def get_commands(force_refresh: bool = False) -> List[dict]:
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
